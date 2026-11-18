"""Exact loopback synthetic PostgreSQL only; destructive reset is fixture DB only."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_office_summary_restricted import OfficeSummaryTests
class PostgreSQLTests(OfficeSummaryTests):
 def save(self,i=1,**kw):
  import hashlib
  source=b"isolated synthetic driving report"
  self.m.db.session.add(self.m.VehicleDocumentImportDraft(id="fixture-"+str(i),batch_id="fixture-batch-"+str(i),company_code="TEST",created_by_username="admin",document_type="driving_report",source_filename="synthetic.txt",source_file=source,source_sha256=hashlib.sha256(source).hexdigest(),status="confirmed"))
  self.m.db.session.commit()
  return super().save(i,**kw)
 @classmethod
 def setUpClass(cls):
  assert os.environ.get('DKSS_OFFICE_PG_ISOLATED')=='1'
  cls.temp=tempfile.TemporaryDirectory(prefix='office-pg-')
  env={'SECRET_KEY':'isolated-test-secret','ITC_INITIAL_PASSWORD':'Isolated-Only-742!','DATABASE_URL':'postgresql+psycopg2://office_test:office_test@127.0.0.1:55439/office_test','MFA_ENABLED':'false','RENDER':'','OPENAI_API_KEY':'','SMTP_HOST':'','S3_BUCKET_NAME':'','VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':''}
  from dkss_app import create_app
  from application_fixture import ApplicationFixture
  with patch.dict(os.environ,env):cls.m=ApplicationFixture(create_app(initialize_database=True))
  cls.m.app.config.update(TESTING=True,WTF_CSRF_ENABLED=False);cls.m.limiter.enabled=False
  with cls.m.app.app_context():assert cls.m.db.engine.dialect.name=='postgresql'
if __name__=='__main__':unittest.main(defaultTest='PostgreSQLTests',verbosity=2)
