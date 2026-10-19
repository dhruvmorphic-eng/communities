"""Local durable catalog, evidence, jobs and company-specific feedback."""
import hashlib
import json
import os
import pathlib
import sqlite3
import threading
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.environ.get('CNVRTED_DATA_DIR', ROOT / 'data'))
LOCK = threading.RLock()
DEFAULTS = {'ai_provider': 'openai', 'model': '', 'ai_key': '', 'firecrawl_key': '',
            'exa_key': '', 'background_refresh': False}

def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

def connection():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    c = sqlite3.connect(DATA / 'catalog.sqlite', timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init():
    with connection() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS communities(id TEXT PRIMARY KEY, payload TEXT NOT NULL, added_at TEXT NOT NULL, origin TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, community_id TEXT, url TEXT, checked_at TEXT, status TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT, stage TEXT, created_at TEXT, updated_at TEXT, result TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS profiles(domain TEXT PRIMARY KEY, payload TEXT, updated_at TEXT, discovered_at REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS feedback(domain TEXT, community_id TEXT, value TEXT, updated_at TEXT, PRIMARY KEY(domain,community_id));
        CREATE TABLE IF NOT EXISTS discovery_runs(cache_key TEXT PRIMARY KEY, checked_at REAL, result TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        ''')
        if not c.execute("SELECT 1 FROM meta WHERE key='seed_imported'").fetchone():
            rows = json.loads((ROOT.parent / 'communities.json').read_text())['communities']
            c.executemany('INSERT OR IGNORE INTO communities VALUES(?,?,?,?)',
                          [(r['community_id'], json.dumps(r), now(), 'seed') for r in rows])
            c.execute("INSERT INTO meta VALUES('seed_imported',?)", (now(),))
        c.execute("UPDATE jobs SET status='failed', error='The app restarted before this job finished.', updated_at=? WHERE status IN ('queued','running')", (now(),))

def settings():
    p = DATA / 'settings.json'
    with LOCK:
        d = {**DEFAULTS, 'ai_provider': os.environ.get('AI_PROVIDER', DEFAULTS['ai_provider']), **(json.loads(p.read_text()) if p.exists() else {})}
    ai_env={'gateway':'AI_GATEWAY_API_KEY','openai':'OPENAI_API_KEY','gemini':'GEMINI_API_KEY','anthropic':'ANTHROPIC_API_KEY','openrouter':'OPENROUTER_API_KEY'}
    for field, env in [('ai_key',ai_env.get(d['ai_provider'],'OPENAI_API_KEY')), ('firecrawl_key','FIRECRAWL_API_KEY'), ('exa_key','EXA_API_KEY')]:
        if not d[field]: d[field] = os.environ.get(env, '')
    if not d['model']: d['model'] = os.environ.get('AI_MODEL', '') or (os.environ.get('AI_GATEWAY_MODEL','') if d['ai_provider']=='gateway' else '')
    return d

def public_settings():
    d = settings()
    return {k: bool(v) if k.endswith('_key') else v for k,v in d.items()}

def save_settings(body):
    with LOCK:
        d = settings()
        if body.get('ai_provider',d['ai_provider'])!=d['ai_provider']:
            d['ai_key']=''
        for k in DEFAULTS:
            if k not in body: continue
            if k.endswith('_key'):
                if body[k]: d[k] = str(body[k]).strip()[:2000]
            elif k == 'background_refresh': d[k] = body[k] is True
            else: d[k] = str(body[k]).strip()[:150]
        if d['ai_provider'] not in ['gateway','openai','gemini','anthropic','openrouter']: raise ValueError('Unsupported AI provider.')
        if d['ai_key'] and not d['model']: raise ValueError('Enter the model ID for your AI provider.')
        DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
        p = DATA / 'settings.json'
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd,'w') as f: json.dump(d,f)
        p.chmod(0o600)
    return public_settings()

def all_communities():
    with connection() as c:
        return [json.loads(r['payload']) for r in c.execute('SELECT payload FROM communities')]

def put_community(record, origin='discovered'):
    with connection() as c:
        exists = c.execute('SELECT 1 FROM communities WHERE id=?',(record['community_id'],)).fetchone()
        c.execute('INSERT INTO communities VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                  (record['community_id'], json.dumps(record), now(), origin))
    return not bool(exists)

def observe(cid, url, status, payload):
    with connection() as c:
        c.execute('INSERT INTO observations(community_id,url,checked_at,status,payload) VALUES(?,?,?,?,?)',
                  (cid,url,now(),status,json.dumps(payload)))

def create_job(kind):
    jid = uuid.uuid4().hex
    with connection() as c:
        active = c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        if active >= 3: raise ValueError('Three jobs are already active. Wait for one to finish.')
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',(jid,'queued',kind,now(),now(),None,None))
    return jid

def update_job(jid, stage, status='running', result=None, error=None):
    with connection() as c:
        c.execute('UPDATE jobs SET status=?, stage=?, updated_at=?, result=?, error=? WHERE id=?',
                  (status,stage,now(),json.dumps(result) if result is not None else None,error,jid))

def get_job(jid):
    with connection() as c: row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
    if not row: return None
    d=dict(row);d['result']=json.loads(d['result']) if d['result'] else None
    return d

def feedback(domain, cid, value):
    if value not in ['useful','irrelevant','clear']: raise ValueError('Invalid feedback.')
    with connection() as c:
        if value=='clear': c.execute('DELETE FROM feedback WHERE domain=? AND community_id=?',(domain,cid))
        else: c.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?,?)',(domain,cid,value,now()))

def feedback_for(domain):
    with connection() as c: return {r['community_id']:r['value'] for r in c.execute('SELECT * FROM feedback WHERE domain=?',(domain,))}

def save_profile(domain, profile, discovered=False):
    with connection() as c:
        old=c.execute('SELECT discovered_at FROM profiles WHERE domain=?',(domain,)).fetchone()
        stamp=time.time() if discovered else old[0] if old else 0
        c.execute('INSERT OR REPLACE INTO profiles VALUES(?,?,?,?)',(domain,json.dumps(profile),now(),stamp))

def cache_discovery(key, result=None):
    with connection() as c:
        if result is not None:
            c.execute('INSERT OR REPLACE INTO discovery_runs VALUES(?,?,?)',(key,time.time(),json.dumps(result)))
            return result
        row=c.execute('SELECT * FROM discovery_runs WHERE cache_key=?',(key,)).fetchone()
        if row and time.time()-row['checked_at'] < 86400: return json.loads(row['result'])

def due_profiles():
    with connection() as c:
        return [json.loads(r['payload']) for r in c.execute('SELECT payload FROM profiles WHERE discovered_at<? ORDER BY discovered_at LIMIT 3',(time.time()-86400,))]

def stats():
    with connection() as c:
        counts={r['origin']:r['n'] for r in c.execute('SELECT origin,count(*) n FROM communities GROUP BY origin')}
        latest=c.execute('SELECT max(checked_at) FROM observations').fetchone()[0]
    return {'total':sum(counts.values()),'seed':counts.get('seed',0),'added':sum(v for k,v in counts.items() if k!='seed'),'last_observed_at':latest}
