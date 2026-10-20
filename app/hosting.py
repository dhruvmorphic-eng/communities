"""Anonymous beta sessions, private job ownership and bounded provider usage."""
import hashlib
import hmac
import os
import secrets
import time
from http.cookies import SimpleCookie
import storage


def enabled():return os.environ.get('CNVRTED_HOSTED')=='1'
def secret():return os.environ.get('SESSION_SECRET','')
def digest(value):return hmac.new(secret().encode(),value.encode(),hashlib.sha256).hexdigest()
def csrf(sid):return digest('csrf:'+sid)
def cookie(sid):
    value=sid+'.'+str(int(time.time())+30*86400)
    return value+'.'+digest('session:'+value)
def session(header):
    try:
        jar=SimpleCookie();jar.load(header or '')
        value=jar['cnvrted_session'].value;sid,expiry,signature=value.split('.')
        if len(sid)==32 and all(c in '0123456789abcdef' for c in sid) and int(expiry)>time.time() and hmac.compare_digest(signature,digest('session:'+sid+'.'+expiry)):return sid,False
    except (KeyError,ValueError):pass
    return secrets.token_hex(16),True

def init():
    if enabled():
        from urllib.parse import urlsplit
        p=urlsplit(os.environ.get('PUBLIC_URL',''))
        if p.scheme!='https' or not p.hostname or p.path not in ['', '/']:raise ValueError('Set PUBLIC_URL to the hosted HTTPS origin.')
        if len(secret())<32 or len(os.environ.get('ADMIN_TOKEN',''))<32:raise ValueError('Configure long session and admin secrets before hosting.')
    with storage.connection() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS job_owners(job TEXT PRIMARY KEY, owner TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS usage_limits(bucket TEXT, window TEXT, count INTEGER, PRIMARY KEY(bucket,window));''')
        old=int(time.time())-7*86400
        c.execute('DELETE FROM jobs WHERE id IN (SELECT job FROM job_owners WHERE created_at<?)',(old,))
        c.execute('DELETE FROM job_owners WHERE created_at<?',(old,))
        c.execute('DELETE FROM usage_limits WHERE window<?',(time.strftime('%Y-%m-%d',time.gmtime(time.time()-3*86400)),))

def own(jid,owner):
    with storage.connection() as c:c.execute('INSERT INTO job_owners VALUES(?,?,?)',(jid,owner,int(time.time())))
def owns(jid,owner):
    with storage.connection() as c:return bool(c.execute('SELECT 1 FROM job_owners WHERE job=? AND owner=?',(jid,owner)).fetchone())
def scope(domain,owner):return hashlib.sha256((owner+':'+domain).encode()).hexdigest() if owner else domain

def allow_job(owner,ip,kind):
    if kind not in ['analyze','recommend']:raise ValueError('Only company analysis and recommendations are available in the hosted beta.')
    day=time.strftime('%Y-%m-%d',time.gmtime())
    buckets=[('visitor:'+owner,int(os.environ.get('VISITOR_DAILY_JOBS','12'))),('ip:'+digest(ip),int(os.environ.get('IP_DAILY_JOBS','24'))),('global',int(os.environ.get('GLOBAL_DAILY_JOBS','120')))]
    with storage.LOCK,storage.connection() as c:
        c.execute('BEGIN IMMEDIATE')
        active=c.execute("SELECT count(*) FROM jobs JOIN job_owners ON jobs.id=job_owners.job WHERE owner=? AND status IN ('queued','running')",(owner,)).fetchone()[0]
        if active:raise ValueError('Your previous scan is still running. Please wait for it to finish.')
        for bucket,limit in buckets:
            row=c.execute('SELECT count FROM usage_limits WHERE bucket=? AND window=?',(bucket,day)).fetchone()
            if row and row[0]>=limit:raise ValueError('The beta testing allowance has been reached for today. Please try again tomorrow (UTC).')
        for bucket,_ in buckets:c.execute('INSERT INTO usage_limits VALUES(?,?,1) ON CONFLICT(bucket,window) DO UPDATE SET count=count+1',(bucket,day))
