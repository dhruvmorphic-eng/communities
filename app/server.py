#!/usr/bin/env python3
"""Run locally: python3 server.py --port 8765. Python 3.9+, no dependencies."""
import argparse
import http.server
import json
import secrets
import threading
import urllib.parse
import storage
import engine
import experiments
from webfetch import request

TOKEN=secrets.token_urlsafe(32)
PORT=8765
STATIC=storage.ROOT/'static'

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data,kind='application/json'):
        content=json.dumps(data).encode() if kind=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(content)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers();self.wfile.write(content)
    def valid_host(self):
        return self.headers.get('Host') in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']
    def do_GET(self):
        if not self.valid_host():return self.send(403,{'error':'Invalid host.'})
        parsed=urllib.parse.urlsplit(self.path);path=parsed.path
        try:
            if path=='/api/experiments':return self.send(200,experiments.report())
            if path=='/api/status':return self.send(200,{'csrf_token':TOKEN,'settings':storage.public_settings(),'catalog':storage.stats()})
            if path.startswith('/api/jobs/'):
                job=storage.get_job(path.rsplit('/',1)[-1]);return self.send(200 if job else 404,job or {'error':'Job not found.'})
            if path=='/api/catalog':
                q=urllib.parse.parse_qs(parsed.query).get('q',[''])[0].lower()
                rows=[{k:r.get(k) for k in ['community_id','name','source_url','topics','cost_status','evidence_status']} for r in storage.all_communities() if q in (r['name']+' '+' '.join(r['topics'])).lower()]
                return self.send(200,{'total':len(rows),'records':rows[:50]})
            if path=='/api/models':
                d,_,_=request('https://ai-gateway.vercel.sh/v1/models',limit=2_000_000)
                return self.send(200,{'ids':[x['id'] for x in json.loads(d)['data']]})
            files={'/':('index.html','text/html'),'/app.js':('app.js','application/javascript'),'/style.css':('style.css','text/css'),'/assets/slack.svg':('assets/slack.svg','image/svg+xml'),'/assets/discord.svg':('assets/discord.svg','image/svg+xml')}
            if path in files:
                filename,kind=files[path];return self.send(200,(STATIC/filename).read_bytes(),kind)
            return self.send(404,{'error':'Not found.'})
        except Exception as e:return self.send(400,{'error':str(e)[:500]})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-CSRF-Token')!=TOKEN:return self.send(403,{'error':'Refresh the app before submitting.'})
        origin=self.headers.get('Origin')
        if origin and origin not in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']:return self.send(403,{'error':'Invalid origin.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16000:raise ValueError('Request body is too large or empty.')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ValueError('Expected a JSON object.')
            if self.path=='/api/experiments/assign':return self.send(200,experiments.assign(body.get('participant')))
            if self.path=='/api/experiments/event':return self.send(200,experiments.event(body))
            if self.path=='/api/settings':return self.send(200,storage.save_settings(body))
            if self.path=='/api/jobs':
                kind=body.get('kind','recommend')
                if kind not in ['analyze','recommend','add','refresh']:raise ValueError('Unknown job type.')
                return self.send(202,{'job_id':engine.submit(kind,body)})
            if self.path=='/api/feedback':
                domain=str(body.get('domain',''))[:250];cid=str(body.get('community_id',''))[:100]
                if not domain or not cid:raise ValueError('Missing company or community.')
                storage.feedback(domain,cid,body.get('value'));return self.send(200,{'saved':True})
            return self.send(404,{'error':'Not found.'})
        except Exception as e:return self.send(400,{'error':str(e)[:500]})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args();PORT=args.port
    storage.init()
    experiments.init()
    threading.Thread(target=engine.background_loop,daemon=True).start()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'Cnvrted community recommender: http://127.0.0.1:{PORT}',flush=True)
    server.serve_forever()
