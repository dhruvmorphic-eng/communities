import io
import json
import os
import tempfile
import unittest
from email.message import Message
from unittest.mock import patch
import storage
import hosting
import experiments
import engine
import server


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'CNVRTED_HOSTED':'1','PUBLIC_URL':'https://beta.example','SESSION_SECRET':'s'*48,'ADMIN_TOKEN':'a'*48})
        self.env.start();self.data=patch.object(storage,'DATA',__import__('pathlib').Path(self.temp.name));self.data.start()
        storage.init();hosting.init();experiments.init()
        self.sid='1'*32;self.other='2'*32
    def tearDown(self):self.data.stop();self.env.stop();self.temp.cleanup()
    def request(self,path,body=None,sid=None,extra=None):
        h=server.Handler.__new__(server.Handler);h.path=path;h.headers=Message();h.client_address=('203.0.113.1',80)
        headers={'Host':'beta.example','Cookie':'cnvrted_session='+hosting.cookie(sid or self.sid),'Origin':'https://beta.example','X-CSRF-Token':hosting.csrf(sid or self.sid),**(extra or {})}
        data=json.dumps(body).encode() if body is not None else b''
        if body is not None:headers['Content-Length']=str(len(data))
        for k,v in headers.items():h.headers[k]=v
        h.rfile=io.BytesIO(data);response=[];h.send=lambda status,data,kind='application/json':response.extend([status,data])
        (h.do_POST if body is not None else h.do_GET)()
        return response
    def make_job(self,owner=None,kind='analysis'):
        jid=storage.create_job(kind);hosting.own(jid,owner or self.sid)
        storage.update_job(jid,'Complete','completed',result={'kind':kind,'profile':{'domain':'test.example'},'recommendations':[{'community_id':'real'}]})
        return jid
    def test_sessions_reject_tampering_and_have_individual_csrf(self):
        cookie=hosting.cookie(self.sid)
        self.assertEqual(hosting.session('cnvrted_session='+cookie),(self.sid,False))
        self.assertNotEqual(hosting.session('cnvrted_session='+cookie[:-1]+'x')[0],self.sid)
        self.assertNotEqual(hosting.csrf(self.sid),hosting.csrf(self.other))
    def test_private_job_cannot_be_read_or_reused(self):
        jid=self.make_job()
        self.assertEqual(self.request('/api/jobs/'+jid)[0],200)
        self.assertEqual(self.request('/api/jobs/'+jid,sid=self.other)[0],404)
        with patch('engine.storage.settings',return_value={}),self.assertRaises(ValueError):engine.recommend({'analysis_id':jid,'_owner':self.other})
    def test_settings_and_reports_are_owner_only(self):
        self.assertEqual(self.request('/api/settings',{'ai_key':'attacker'})[0],403)
        self.assertEqual(self.request('/api/experiments')[0],401)
        self.assertEqual(self.request('/api/experiments',extra={'X-Admin-Token':'a'*48})[0],200)
    def test_csrf_origin_and_host_rejected(self):
        self.assertEqual(self.request('/api/jobs',{'kind':'analyze'},extra={'X-CSRF-Token':hosting.csrf(self.other)})[0],403)
        self.assertEqual(self.request('/api/jobs',{},extra={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/status',extra={'Host':'evil.example'})[0],403)
    def test_public_ownership_and_experiment_identity_are_server_assigned(self):
        with patch('engine.submit',return_value='job') as submit:
            response=self.request('/api/jobs',{'kind':'analyze','experiment_participant':self.other,'_owner':self.other,'experiment_flow':'f'*32})
            self.assertEqual(response[0],202)
            self.assertEqual(submit.call_args.args[1]['_owner'],self.sid)
            self.assertEqual(submit.call_args.args[1]['experiment_participant'],self.sid)
    def test_feedback_is_scoped_and_foreign_feedback_rejected(self):
        jid=self.make_job(kind='recommendations');body={'job_id':jid,'domain':'test.example','community_id':'real','value':'useful'}
        self.assertEqual(self.request('/api/feedback',body)[0],200)
        self.assertEqual(self.request('/api/feedback',body,sid=self.other)[0],404)
        self.assertEqual(storage.feedback_for(hosting.scope('test.example',self.sid)),{'real':'useful'})
        self.assertEqual(storage.feedback_for(hosting.scope('test.example',self.other)),{})
    def test_daily_and_active_limits(self):
        with patch.dict(os.environ,{'VISITOR_DAILY_JOBS':'1'}):
            hosting.allow_job(self.sid,'203.0.113.1','analyze')
            with self.assertRaises(ValueError):hosting.allow_job(self.sid,'203.0.113.1','recommend')
        jid=storage.create_job('analyze');hosting.own(jid,self.other)
        with self.assertRaises(ValueError):hosting.allow_job(self.other,'203.0.113.2','analyze')
        with self.assertRaises(ValueError):hosting.allow_job(self.other,'203.0.113.2','refresh')
    def test_owner_qa_is_excluded_from_report(self):
        experiments.event({'participant':self.sid,'flow':'f'*32,'event':'started'})
        self.request('/api/experiments',extra={'X-Admin-Token':'a'*48})
        for variant in experiments.report()['results']['ui'].values():self.assertEqual(variant['participants'],0)

if __name__=='__main__':unittest.main()
