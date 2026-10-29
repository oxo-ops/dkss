"""Synthetic sources with enforced FKs; no OCR or production connection."""
import hashlib
import json
from sqlalchemy import event, text
from test_workflow_regressions import WorkflowRegressionTests
from test_driving_report_insights import row as synthetic
from test_driving_workspace import WorkspaceTests


class DrivingIdentityFixture:
    @classmethod
    def setUpClass(cls):
        WorkflowRegressionTests.setUpClass.__func__(cls)
        with cls.m.app.app_context():
            engine=cls.m.db.engine
            engine._driving_fixture_fk=False
            @event.listens_for(engine,'checkout')
            def fk(connection,record,proxy):
                cursor=connection.cursor()
                cursor.execute('PRAGMA foreign_keys='+('ON' if engine._driving_fixture_fk else 'OFF'))
                cursor.close()

    tearDownClass=classmethod(WorkflowRegressionTests.tearDownClass.__func__)
    render=WorkspaceTests.render

    def setUp(self):
        WorkflowRegressionTests.setUp(self)
        self.m.User.query.filter_by(username='admin').one().office='監査営業所'
        self.m.db.session.add(self.m.Office(company_code='TEST',name='監査営業所'))
        self.m.db.session.commit()
        if self.m.db.engine.dialect.name=='sqlite':
            vid=self.vehicle.id
            self.m.db.engine._driving_fixture_fk=True
            self.m.db.session.remove()
            self.vehicle=self.m.db.session.get(self.m.Vehicle,vid)
            self.assertEqual(self.m.db.session.execute(text('PRAGMA foreign_keys')).scalar(),1)
        self.url='/safety/driving-reports?period=all'

    def tearDown(self):
        if self.m.db.engine.dialect.name=='sqlite':
            self.m.db.engine._driving_fixture_fk=False
            self.m.db.session.rollback()
        WorkflowRegressionTests.tearDown(self)

    def person(self,username='retired',name='監査人物',company='TEST',ident=None):
        values=dict(company_code=company,username=username,role='user',password='unused',
                    last_name=name,password_changed_at='stamp')
        if ident is not None:values['id']=ident
        user=self.m.User(**values);self.m.db.session.add(user);self.m.db.session.commit()
        return user

    def login(self,user):
        with self.client.session_transaction() as state:
            state.clear();state.update(company_code=user.company_code,username=user.username,
                role=user.role,account_identity=user.account_identity,password_changed_at=user.password_changed_at)

    def save(self,index=1,commit=True,**fields):
        source=synthetic(index,name='監査人物',code='REPORT-CODE',**fields)
        draft_id='verified-'+str(index);raw=b'%PDF-1.4 synthetic'
        self.m.db.session.add(self.m.VehicleDocumentImportDraft(id=draft_id,batch_id='verified-batch',
            company_code='TEST',created_by_username='admin',document_type='driving_report',
            status='completed',source_filename='synthetic.pdf',source_file=raw,
            source_sha256=hashlib.sha256(raw).hexdigest()))
        self.m.db.session.flush()
        report=self.m.VehicleDrivingReportRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
            operation_date=source.operation_date,content='NO10_PRIVATE',details_json=source.details_json,
            source_draft_id=draft_id,source_record_index=0,created_by_username='admin')
        self.m.db.session.add(report);self.m.db.session.flush()
        if commit:self.m.db.session.commit()
        return report
