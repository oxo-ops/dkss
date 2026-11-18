import os,sys,io,re,html,json,base64,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R),str(R/'tests')]
import boto3
from botocore.config import Config
from sqlalchemy.exc import OperationalError
from test_q02_news_boundaries import Q02NewsBoundaryTests
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_PUT(self):
  body=self.rfile.read(int(self.headers['Content-Length']))
  s=self.server;s.puts.append((self.path,dict(self.headers),body));s.objects[self.path]=body
  if len(s.puts)==s.drop:
   self.close_connection=True;self.connection.close();return
  self.send_response(200);self.send_header('ETag','"synthetic-etag"');self.send_header('Content-Length','0');self.end_headers()
 def do_DELETE(self):
  self.server.deletes.append(self.path);self.server.objects.pop(self.path,None)
  self.send_response(204);self.end_headers()
class SDKTests(Q02NewsBoundaryTests):
 def setUp(self):
  super().setUp();self.app.config['WTF_CSRF_ENABLED']=True
  s=ThreadingHTTPServer(('127.0.0.1',0),Handler);s.puts=[];s.deletes=[];s.objects={};s.drop=-1;self.s=s
  thread=threading.Thread(target=s.serve_forever,daemon=True);thread.start()
  self.addCleanup(s.server_close);self.addCleanup(s.shutdown)
  client=boto3.client('s3',endpoint_url=f'http://127.0.0.1:{s.server_port}',region_name='us-east-1',aws_access_key_id='synthetic',aws_secret_access_key='synthetic',config=Config(retries={'total_max_attempts':1},connect_timeout=2,read_timeout=2,s3={'addressing_style':'path'},request_checksum_calculation='when_required',response_checksum_validation='when_required'))
  old=self.app.extensions['dkss']['s3_client'];self.app.extensions['dkss']['s3_client']=client
  self.addCleanup(self.app.extensions['dkss'].__setitem__,'s3_client',old)
  old_bucket=self.app.config['S3_BUCKET_NAME'];self.app.config['S3_BUCKET_NAME']='synthetic-bucket';self.addCleanup(self.app.config.__setitem__,'S3_BUCKET_NAME',old_bucket)
 def submit(self,n=1,commit_loss=False):
  self.actor();page=self.request('GET','/itc/news/new').get_data(as_text=True);data=self.form(title='SDK acceptance')
  for key in ('csrf_token','person_selection_token'):
   found=re.search(r'name="'+key+r'"\s+value="([^"]+)"',page);self.assertIsNotNone(found);data[key]=html.unescape(found[1])
  data['files']=[(io.BytesIO(PNG),f'{i}.png','image/png') for i in range(n)]
  if commit_loss:
   real=self.db.session.commit
   def lost():real();raise OperationalError('synthetic',{},Exception('lost acknowledgement'))
   with patch.object(self.db.session,'commit',side_effect=lost):return self.request('POST','/itc/news/new',data=data,headers={'X-DKSS-Final-Submit':'1'},content_type='multipart/form-data')
  return self.request('POST','/itc/news/new',data=data,content_type='multipart/form-data')
 def test_success_real_sdk(self):
  response=self.submit();self.assertEqual(response.status_code,302);self.assertEqual(len(self.s.objects),1);self.assertFalse(self.s.deletes)
  path,headers,body=self.s.puts[0];headers={k.lower():v for k,v in headers.items()}
  self.assertTrue(path.startswith('/synthetic-bucket/uploads/A/'));self.assertEqual(body,PNG)
  self.assertEqual(headers['x-amz-server-side-encryption'],'AES256');self.assertEqual(headers['cache-control'],'no-store')
  self.assertEqual(self.models.News.query.filter_by(title='SDK acceptance').count(),1)
 def test_put_lost_ack_preserves_unknown_object(self):
  self.s.drop=1;before=self.db_rows();r=self.submit();self.assertEqual(r.status_code,500)
  self.assertEqual(self.db_rows(),before);self.assertEqual(len(self.s.objects),1);self.assertFalse(self.s.deletes);self.dispatch.assert_not_called()
 def test_batch_second_lost_ack_cleans_known_only(self):
  self.s.drop=2;before=self.db_rows();r=self.submit(2);self.assertEqual(r.status_code,500)
  self.assertEqual(self.db_rows(),before);self.assertEqual(self.s.deletes,[self.s.puts[0][0]])
  self.assertEqual(list(self.s.objects),[self.s.puts[1][0]]);self.dispatch.assert_not_called()
 def test_durable_commit_lost_ack_preserves_s3_reference(self):
  r=self.submit(commit_loss=True);self.assertEqual(r.status_code,500)
  row=self.models.News.query.filter_by(title='SDK acceptance').one();names=json.loads(row.files_json)
  self.assertEqual(len(names),1);self.assertIn('/synthetic-bucket/uploads/A/'+names[0],self.s.objects)
  self.assertFalse(self.s.deletes);self.dispatch.assert_not_called()
def load_tests(loader,tests,pattern):return unittest.TestSuite(SDKTests(n) for n in SDKTests.__dict__ if n.startswith('test_'))
if __name__=='__main__':unittest.main(verbosity=2)
