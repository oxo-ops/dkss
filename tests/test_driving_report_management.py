"""v0.21 integration, source preservation, duplicate and access boundaries."""
from identity_fixture import identity_for
import copy,json,unittest
from decimal import Decimal
from types import SimpleNamespace
from io import BytesIO
from unittest.mock import patch
import test_workflow_regressions as workflow
from test_driving_report_ai import extraction,pdf_bytes
from driving_report_data import canonical_operations,match_report,metrics_summary,version,payload
from driving_report_management import export_pdf
import driving_report_ai as ai

class DrivingReportDataTests(unittest.TestCase):
    def row(self,i=1,**fields):
        p=extraction()['records'][0];p.update(fields)
        return SimpleNamespace(id=i,company_code='A',vehicle_record_id=1,operation_date=p['operation_date'],details_json=json.dumps(p),report_number=p.get('report_number'),operation_record_id=None,created_at=None,created_by_username='admin')
    def op(self,**fields):
        values=dict(id=1,company_code='A',vehicle_record_id=1,report_number='R1',operation_date='2026-09-22',departure_at='2026-09-22 05:21:34',arrival_at='2026-09-22 14:48:38',departure_meter=Decimal('198141.39'),arrival_meter=Decimal('198243.24'),distance=Decimal('101.85'));values.update(fields);return SimpleNamespace(**values)
    def test_pdf_csv_same_trip_count_once_and_conflicts_hold(self):
        r=self.row(report_number='R1');o=self.op()
        self.assertEqual(len(canonical_operations([o],[r])),1)
        self.assertEqual(match_report(r,[o])['status'],'matched')
        o.distance=Decimal('102')
        self.assertEqual(match_report(r,[o])['status'],'conflict')
        self.assertEqual(canonical_operations([o],[r]),[])
        p=payload(r);m=match_report(r,[o]);p['reconciliation']={'mode':'linked','operation_id':1,'use':'pdf','fingerprint':m['fingerprint']};r.details_json=json.dumps(p)
        self.assertEqual(canonical_operations([o],[r])[0].distance,Decimal('101.85'))
        o.distance=Decimal('103')
        self.assertEqual(canonical_operations([o],[r]),[])
    def test_same_day_does_not_prove_same_trip(self):
        r=self.row(operation_start_time=None,operation_end_time=None);o=self.op()
        self.assertEqual(match_report(r,[o])['status'],'ambiguous')
        self.assertEqual(len(canonical_operations([o],[r])),1)
    def test_day_totals_and_conflicting_pdf_duplicates_do_not_add_twice(self):
        trip=self.row(report_number='trip',report_scope='trip')
        day=self.row(2,report_number='day',report_scope='daily',distance='500')
        self.assertEqual(sum(o.distance for o in canonical_operations([],[trip,day])),Decimal('101.85'))
        conflicting=self.row(3,report_number='trip',report_scope='trip',distance='102')
        self.assertEqual(canonical_operations([],[trip,conflicting]),[])
    def test_duplicates_monthly_unknown_and_cancelled_do_not_add_distance(self):
        r=self.row();duplicate=self.row(2)
        self.assertEqual(len(canonical_operations([],[r,duplicate])),1)
        for value in [{'report_scope':'monthly'},{'report_scope':'unknown'},{'lifecycle':'cancelled'}]:self.assertEqual(canonical_operations([],[self.row(**value)]),[])
    def test_metrics_keep_definitions_and_weighted_ratio_separate(self):
        rows=[]
        for i,(n,d) in enumerate([(2,100),(3,300)],1):
            r=self.row(i,report_number='r'+str(i),source_system='TEST',definition_version='v1',report_scope='trip');p=payload(r)
            p['report_items'][0].update(value='1',unit='回/km',numerator=str(n),denominator=str(d),denominator_unit='km',definition='X',threshold='Y')
            r.details_json=json.dumps(p);rows.append(r)
        summary=metrics_summary(rows)
        self.assertEqual(summary['groups'][0]['ratio'],'0.0125')
        self.assertEqual(summary['groups'][0]['count'],2)
        p=payload(rows[1]);p['definition_version']='v2';rows[1].details_json=json.dumps(p)
        self.assertEqual(len(metrics_summary(rows)['groups']),2)
        self.assertEqual(metrics_summary([self.row()])['groups'],[])
    def test_extended_extraction_preserves_independent_collections(self):
        data=extraction();r=data['records'][0]
        r.update(report_scope='daily',source_system='Custom',definition_version=None)
        for name in ['events','duties','extra_items']:r[name]=[copy.deepcopy(r['report_items'][0])]
        ai._validate(data);preview=ai.build_driving_report_preview(data,[])
        preview['records'][0]['events'][0]['raw_result']='changed'
        self.assertEqual(preview['original_records'][0]['events'][0]['raw_result'],'0.0回/h')
        missing=extraction();missing['records'][0]['report_scope']=None
        ai._validate(missing);self.assertEqual(missing['records'][0]['report_scope'],'unknown')
    def test_pdf_is_valid_multilingual_and_paginates(self):
        from pypdf import PdfReader
        content=export_pdf(['日本語 日報と指導']*120)
        reader=PdfReader(BytesIO(content))
        self.assertEqual(len(reader.pages),3)
        self.assertIn('日本語 日報と指導',reader.pages[0].extract_text())
        self.assertIn('/FontFile2',reader.pages[0]['/Resources']['/Font']['/F1']['/DescendantFonts'][0]['/FontDescriptor'])

class DrivingReportManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.WorkflowRegressionTests.setUpClass();cls.m=workflow.WorkflowRegressionTests.m
    @classmethod
    def tearDownClass(cls):workflow.WorkflowRegressionTests.tearDownClass()
    setUp=workflow.WorkflowRegressionTests.setUp
    tearDown=workflow.WorkflowRegressionTests.tearDown
    upload_driving_report=workflow.WorkflowRegressionTests.upload_driving_report
    inspection_form=workflow.WorkflowRegressionTests.inspection_form
    def imported(self):
        self.upload_driving_report();draft=self.m.VehicleDocumentImportDraft.query.one()
        self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm',data=self.inspection_form(draft))
        return self.m.VehicleDrivingReportRecord.query.one()
    def test_list_detail_exports_and_shared_edit_roundtrip(self):
        r=self.imported()
        for path in ['/safety/driving-reports',f'/safety/driving-reports/{r.id}',f'/safety/driving-reports/{r.id}/edit']:
            response=self.client.get(path);self.assertEqual(response.status_code,200,path)
        page=self.client.get(f'/safety/driving-reports/{r.id}/edit').get_data(as_text=True)
        self.assertIn('data-invoice-source',page);self.assertIn('record_version',page)
        for ext in ['csv','pdf']:
            response=self.client.get('/safety/driving-reports/export.'+ext)
            self.assertEqual(response.status_code,200);self.assertIn('no-store',response.headers['Cache-Control'])
        form=self.inspection_form(self.m.VehicleDocumentImportDraft.query.one());key=r.source_draft_id+'_0'
        form.update({'record_version':version(r),'driver_name_'+key:'訂正乗務員'})
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/edit',data=form).status_code,302)
        self.assertEqual(payload(r)['driver_name'],'訂正乗務員')
        self.assertEqual(self.client.get('/safety/driving-reports').status_code,200)
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/edit',data=form).status_code,409)
    def test_review_cancel_and_canonical_mileage(self):
        r=self.imported();m=self.m
        rows=m.get_vehicle_canonical_operations('TEST',self.vehicle.id)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].distance,Decimal('101.85'))
        self.assertEqual(m.get_vehicle_operation_summary('TEST',self.vehicle.id)['current_mileage'],Decimal('198243.24'))
        data={'version':version(r),'state':'followup','note':'次回振り返る','next_date':'2026-10-30'}
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/review',data=data).status_code,302)
        self.assertEqual(payload(r)['review']['state'],'followup')
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/review',data=data).status_code,409)
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/reconcile',data={'version':version(r),'mode':'cancelled'}).status_code,302)
        self.assertEqual(m.get_vehicle_canonical_operations('TEST',self.vehicle.id),[])
        self.assertEqual(m.VehicleDrivingReportRecord.query.count(),1)
    def test_assignment_notifies_once_and_cancelled_report_summary_excludes_csv(self):
        r=self.imported();m=self.m
        stamp=m.User.query.filter_by(company_code='TEST',username='admin').one().password_changed_at
        m.db.session.add(m.User(company_code='TEST',username='reviewer',role='admin',password='unused',last_name='確認',first_name='担当',password_changed_at=stamp))
        m.db.session.commit()
        data={'version':version(r),'state':'reviewed','assignee':'reviewer'}
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/review',data=data).status_code,302)
        self.assertEqual(m.Notification.query.filter_by(target_username='reviewer').count(),1)
        data['version']=version(r)
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/review',data=data).status_code,302)
        self.assertEqual(m.Notification.query.filter_by(target_username='reviewer').count(),1)
        m.db.session.add(m.VehicleOperationRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,report_number='csv',operation_date=r.operation_date,distance=101.85,departure_at='2026-09-22 05:21:34',arrival_at='2026-09-22 14:48:38'))
        m.db.session.commit()
        self.client.post(f'/safety/driving-reports/{r.id}/reconcile',data={'version':version(r),'mode':'cancelled'})
        page=self.client.get('/safety/driving-reports?scope=company&period=all&state=cancelled').get_data(as_text=True)
        self.assertIn('重複をまとめた運行 0件',page)
        self.assertEqual(len(m.get_vehicle_canonical_operations('TEST',self.vehicle.id)),1)
    def test_analysis_end_date_excludes_later_reports(self):
        r=self.imported();m=self.m
        self.assertEqual(m.get_vehicle_canonical_operations('TEST',self.vehicle.id,[],end='2026-09-21'),[])
        self.assertEqual(len(m.get_vehicle_canonical_operations('TEST',self.vehicle.id,[],end='2026-09-22')),1)
    def test_second_record_uses_immutable_source_index_in_shared_editor(self):
        source=pdf_bytes();data=extraction(source)
        second=copy.deepcopy(data['records'][0]);second['report_number']='second';second['driver_name']='二番目の乗務員'
        data['records'].append(second)
        with patch.object(self.m,'extract_driving_reports',return_value=data):
            self.client.post('/vehicle/data-import',data={'document_type':'driving_report','document_files':(BytesIO(source),'multi.pdf')})
        draft=self.m.VehicleDocumentImportDraft.query.one();first=draft.id+'_0';key=draft.id+'_1'
        form={k.replace(first,key):(key if k=='include' else v) for k,v in self.inspection_form(draft).items()}
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm',data=form).status_code,302)
        r=self.m.VehicleDrivingReportRecord.query.one();self.assertEqual(r.source_record_index,1)
        page=self.client.get(f'/safety/driving-reports/{r.id}/edit').get_data(as_text=True)
        self.assertIn('driver_name_'+key,page)
        form.update({'record_version':version(r),'driver_name_'+key:'訂正二番目'})
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/edit',data=form).status_code,302)
        self.assertEqual(payload(r)['driver_name'],'訂正二番目')
    def test_reconcile_conflicting_csv_and_keep_source(self):
        r=self.imported();m=self.m;original=m.VehicleDocumentImportDraft.query.one().source_file
        o=m.VehicleOperationRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,report_number='csv1',operation_date=r.operation_date,distance=102)
        m.db.session.add(o);m.db.session.commit()
        self.assertEqual(self.client.post(f'/safety/driving-reports/{r.id}/reconcile',data={'version':version(r),'mode':'linked','operation_id':o.id,'use':'pdf'}).status_code,302)
        self.assertEqual(m.get_vehicle_canonical_operations('TEST',self.vehicle.id)[0].distance,Decimal('101.85'))
        self.assertEqual(m.VehicleDocumentImportDraft.query.one().source_file,original)
    def test_unknown_date_and_collections_survive_confirmation(self):
        source=pdf_bytes();data=extraction(source);p=data['records'][0];p['operation_date']=None;p['operation_end_date']=None;p['extra_items']=[copy.deepcopy(p['report_items'][0])]
        with patch.object(self.m,'extract_driving_reports',return_value=data):
            self.client.post('/vehicle/data-import',data={'document_type':'driving_report','document_files':(BytesIO(source),'unknown.pdf')})
        draft=self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm',data=self.inspection_form(draft)).status_code,302)
        r=self.m.VehicleDrivingReportRecord.query.one();self.assertEqual(r.operation_date,'');self.assertEqual(len(payload(r)['extra_items']),1)
        self.assertEqual(self.m.get_vehicle_canonical_operations('TEST',self.vehicle.id),[])
    def test_filters_csv_formula_and_no_pii_to_general_user(self):
        r=self.imported();p=payload(r);p['driver_name']='=1+1';r.details_json=json.dumps(p);self.m.db.session.commit()
        text=self.client.get('/safety/driving-reports/export.csv?scope=company&period=all&driver=%3D1').data.decode('utf-8-sig');self.assertIn("'=1+1",text)
        self.assertEqual(self.client.get('/safety/driving-reports?start=bad').status_code,400)
        self.m.db.session.add(self.m.User(company_code='TEST',username='viewer',role='user',password='unused',last_name='一般',password_changed_at='viewer-stamp'))
        self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'viewer', app=(self.client).application), username='viewer',role='user',password_changed_at='viewer-stamp')
        for path in ['/safety/driving-reports','/safety/driving-reports/export.csv']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('=1+1',response.get_data(as_text=True))
        self.assertEqual(self.client.get(f'/safety/driving-reports/{r.id}').status_code,404)
        self.assertEqual(self.client.get(f'/vehicle/driving-reports/{r.id}/source').status_code,403)
    def test_ai_input_contains_original_report_evidence(self):
        r=self.imported();m=self.m
        with m.app.test_request_context('/'):
            from flask import session
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            ai_payload,sources=m.get_vehicle_karte_analysis_job_data(self.vehicle)
        fact=next(x for x in ai_payload['records'] if x['source_id']==f'driving_report:{r.id}')
        self.assertEqual(fact['report_items'][0]['raw_result'],'0.0回/h');self.assertIn(f'driving_report:{r.id}',sources)
