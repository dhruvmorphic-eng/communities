"""Local, first-party 2x2 experiment assignments and deduplicated funnel events."""
import hashlib
import re
import storage

VERSION='community-v1'
EVENTS={'started','analysis_ready','brief_confirmed','results_viewed','community_clicked','useful','irrelevant','failed'}

def init():
    with storage.connection() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS experiment_participants(id TEXT PRIMARY KEY, version TEXT, ui TEXT, ranking TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS experiment_events(id TEXT PRIMARY KEY, participant TEXT, version TEXT, ui TEXT, ranking TEXT, flow TEXT, event TEXT, job TEXT, community TEXT, created_at TEXT);''')

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',value):raise ValueError('Invalid experiment identifier.')
    return value

def assign(participant):
    participant=identifier(participant)
    digest=hashlib.sha256((VERSION+':'+participant).encode()).digest()
    with storage.connection() as c:
        c.execute('INSERT OR IGNORE INTO experiment_participants VALUES(?,?,?,?,?)',(participant,VERSION,'compact' if digest[0]&1 else 'full','evidence_first' if digest[1]&1 else 'balanced',storage.now()))
        row=c.execute('SELECT * FROM experiment_participants WHERE id=?',(participant,)).fetchone()
    return {k:row[k] for k in ['version','ui','ranking']}

def event(body):
    participant=identifier(body.get('participant'));flow=identifier(body.get('flow'))
    assignment=assign(participant);name=body.get('event')
    if name not in EVENTS:raise ValueError('Unknown experiment event.')
    job_id=str(body.get('job_id',''));cid=str(body.get('community_id',''))
    if name in {'analysis_ready','brief_confirmed','results_viewed','community_clicked','useful','irrelevant'}:
        job=storage.get_job(job_id);result=(job or {}).get('result') or {}
        if not job or job['status']!='completed' or result.get('experiment_participant')!=participant or result.get('experiment_flow')!=flow:raise ValueError('Event does not match a completed experiment job.')
        expected='analysis' if name in {'analysis_ready','brief_confirmed'} else 'recommendations'
        if result.get('kind')!=expected:raise ValueError('Wrong job for this event.')
        if name in {'community_clicked','useful','irrelevant'} and cid not in {r['community_id'] for r in result.get('recommendations',[])}:raise ValueError('Community was not in these results.')
        # Do not count legacy/basic results as exposure to an AI ranking treatment.
        if expected=='recommendations' and not (result.get('experiment') or {}).get('ranking_applied'):
            assignment={**assignment,'ranking':'not_applied'}
    else:job_id='';cid=''
    key=hashlib.sha256('|'.join([participant,VERSION,flow,name,job_id,cid]).encode()).hexdigest()
    with storage.connection() as c:
        c.execute('INSERT OR IGNORE INTO experiment_events VALUES(?,?,?,?,?,?,?,?,?,?)',(key,participant,VERSION,assignment['ui'],assignment['ranking'],flow,name,job_id,cid,storage.now()))
    return {'saved':True}

def report():
    with storage.connection() as c:
        rows=[dict(r) for r in c.execute('SELECT participant,ui,ranking,event FROM experiment_events WHERE version=?',(VERSION,))]
    output={}
    for dimension,variants,denominator in [('ui',['full','compact'],'started'),('ranking',['balanced','evidence_first'],'results_viewed')]:
        output[dimension]={}
        for variant in variants:
            exposed={r['participant'] for r in rows if r[dimension]==variant and r['event']==denominator}
            counts={name:len({r['participant'] for r in rows if r[dimension]==variant and r['event']==name}&exposed) for name in EVENTS}
            output[dimension][variant]={'participants':len(exposed),'unique_participants_by_event':counts,'rates':{name:round(counts[name]/len(exposed),4) if exposed else None for name in ['results_viewed','community_clicked','useful','irrelevant','failed']}}
    return {'version':VERSION,'results':output,'note':'Descriptive counts only; no winner or statistical significance. UI denominator: visitors starting a scan. Ranking denominator: visitors viewing AI-ranked results. Clicks are interest, not joins or sales. Repeat events count once per visitor. Local testing is not customer evidence. Browser storage reset creates a new visitor. No cross-device identity.'}
