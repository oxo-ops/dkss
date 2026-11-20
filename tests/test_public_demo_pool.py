import importlib.util, pathlib, time, threading, unittest, json, os
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, session
from werkzeug.exceptions import HTTPException
import redis
from redis.connection import Connection, ConnectionPool
from dkss_app import public_demo_sessions as candidate
class Backend:
 def __init__(self,delay=0):self.data={};self.lock=threading.Lock();self.connections=0;self.gets=0;self.clients=0;self.outage=False;self.delay=delay;self.operation_delay=0
class FakeConnection(Connection):
 """Real redis-py ConnectionPool, synthetic transport only: no network/Redis server."""
 def __init__(self,backend,**kw):self.backend=backend;self.pending=None;super().__init__(**kw)
 def connect(self):
  if self._sock is None:
   time.sleep(self.backend.delay)
   with self.backend.lock:self.backend.connections+=1
   self._sock=object()
 def disconnect(self,*a,**kw):self._sock=None
 def can_read(self,timeout=0):return False
 def send_command(self,*args,**kw):self.pending=args
 def read_response(self,**kw):
  b=self.backend
  time.sleep(b.operation_delay)
  if b.outage:raise redis.exceptions.ConnectionError('synthetic outage')
  cmd,*args=self.pending
  with b.lock:
   now=time.time()
   for k,v in list(b.data.items()):
    if v[1]<=now:del b.data[k]
   if cmd=='GET':b.gets+=1;v=b.data.get(args[0]);return None if v is None else v[0].encode()
   if cmd=='SET':
    k,v=args[:2];ttl=int(args[3]);nx='NX' in args
    if nx and k in b.data:return None
    b.data[k]=(v,now+ttl);return b'OK'
   if cmd=='DEL':return int(b.data.pop(args[0],None) is not None)
   raise AssertionError((cmd,args))
def factory(b):
 def make(uri,**kw):
  assert uri.startswith('redis://synthetic.invalid/')
  b.clients+=1
  return redis.Redis(connection_pool=ConnectionPool(connection_class=FakeConnection,backend=b,**kw))
 return make
def app():
 a=Flask('isolated');a.secret_key='synthetic';a.config.update(RATELIMIT_STORAGE_URI='redis://synthetic.invalid/0',PUBLIC_DEMO_EPOCH='epoch1',PUBLIC_DEMO_UNTIL=int(time.time())+3600);return a
def issue(m,a):
 with a.test_request_context('/'):
  session.update(company_code='SYNTHETIC',account_identity='user1');m.issue();return dict(session)
def check(m,a,state):
 with a.test_request_context('/'):
  session.update(state);m.verify()
class Tests(unittest.TestCase):
 def setUp(self):
  self.b=Backend();self.a=app();self.patch=patch('redis.Redis.from_url',side_effect=factory(self.b));self.patch.start();self.addCleanup(self.patch.stop);self.state=issue(candidate,self.a)
 def reject(self,state,status=410):
  with self.assertRaises(HTTPException) as e:check(candidate,self.a,state)
  self.assertEqual(e.exception.code,status)
 def test_each_verify_gets_fresh_state_and_reuses_transport(self):
  for _ in range(10):check(candidate,self.a,self.state)
  self.assertEqual((self.b.clients,self.b.connections,self.b.gets),(1,1,10))
 def test_revocation_immediate(self):
  check(candidate,self.a,self.state)
  with self.a.test_request_context('/'):
   session.update(self.state);candidate.revoke()
  self.reject(self.state)
 def test_expired_or_deleted_record_rejected(self):
  for key,(value,_) in self.b.data.items():self.b.data[key]=(value,0)
  self.reject(self.state)
 def test_company_and_entry_identity_bound(self):
  self.reject(dict(self.state,company_code='OTHER'));self.reject(dict(self.state,public_demo_entry_identity='other'))
 def test_epoch_changed_rejected(self):
  self.a.config['PUBLIC_DEMO_EPOCH']='epoch2';self.reject(self.state)
 def test_missing_or_corrupt_token_rejected(self):
  self.reject(dict(self.state,public_demo_token='bad'));self.reject({})
 def test_corrupt_stored_value_rejected(self):
  for key in self.b.data:self.b.data[key]=('not-owner',time.time()+100)
  self.reject(self.state)
 def test_role_switch_preserves_entry_identity(self):check(candidate,self.a,dict(self.state,account_identity='role2'))
 def test_outage_fails_closed_then_recovers(self):
  self.b.outage=True;self.reject(self.state,503);self.b.outage=False;check(candidate,self.a,self.state)
 def test_issue_outage_does_not_publish_token(self):
  self.b.outage=True
  with self.a.test_request_context('/'):
   session.update(company_code='SYNTHETIC',account_identity='user2')
   with self.assertRaises(HTTPException) as e:candidate.issue()
   self.assertEqual(e.exception.code,503);self.assertNotIn('public_demo_token',session)
 def test_concurrent_first_use_single_client(self):
  a=app();barrier=threading.Barrier(8)
  def worker(i):
   with a.test_request_context('/'):
    barrier.wait();return candidate._store()
  with ThreadPoolExecutor(8) as ex:clients=list(ex.map(worker,range(8)))
  self.assertEqual(len(set(map(id,clients))),1)
 def test_concurrent_verifications(self):
  self.b.operation_delay=.003
  with ThreadPoolExecutor(8) as ex:list(ex.map(lambda _:check(candidate,self.a,self.state),range(100)))
  self.assertEqual(self.b.gets,100);self.assertEqual(self.b.clients,1)
  self.assertGreater(self.b.connections,1);self.assertLessEqual(self.b.connections,8)
 def test_app_isolation_and_uri_rotation(self):
  with self.a.app_context():old=candidate._store()
  with app().app_context():self.assertIsNot(old,candidate._store())
  self.a.config['RATELIMIT_STORAGE_URI']='redis://synthetic.invalid/1'
  with self.a.app_context():self.assertIsNot(old,candidate._store())
 def test_new_pid_uses_new_pool(self):
  with self.a.app_context():
   old=candidate._store()
   with patch.object(candidate.os,'getpid',return_value=os.getpid()+1):self.assertIsNot(old,candidate._store())
 def test_fork_resets_inherited_lock(self):
  if not hasattr(os,'fork'):self.skipTest('fork unavailable')
  candidate._client_lock.acquire()
  pid=os.fork()
  if pid==0:
   acquired=candidate._client_lock.acquire(timeout=.5)
   os._exit(0 if acquired else 1)
  candidate._client_lock.release();_,status=os.waitpid(pid,0);self.assertEqual(status,0)
 def test_testing_memory_unchanged(self):
  a=app();a.testing=True;a.config['RATELIMIT_STORAGE_URI']='memory://';state=issue(candidate,a);check(candidate,a,state)
 def test_invalid_store_scheme_denied(self):
  self.a.config['RATELIMIT_STORAGE_URI']='https://invalid';self.reject(self.state,503)

if __name__=='__main__':unittest.main()
