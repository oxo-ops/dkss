"""Detail cards preserve source facts, review forms and confirmed-reader boundaries."""
from identity_fixture import identity_for
import json
import unittest
from urllib.parse import urlencode
from driving_report_data import version
import test_driving_workspace as workspace_tests


class DrivingReportDetailUITests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def update(self,**values):
        data=json.loads(self.a.details_json);data.update(values)
        self.a.details_json=json.dumps(data,ensure_ascii=False);self.m.db.session.commit()

    def detail(self):
        response=self.client.get('/safety/driving-reports/'+str(self.a.id))
        self.assertEqual(response.status_code,200)
        return response.get_data(as_text=True)

    def test_event_time_place_and_source_page_remain_literal_without_inference(self):
        self.update(source_pages=[2],events=[dict(item_name='急減速',raw_result='1回',start_at='23:58ごろ',end_at=None,place='交差点付近（原文）',source_page=2,status='confirmed',notes='歩行者を確認',score=None)])
        html=self.detail()
        for value in ['23:58ごろ','交差点付近（原文）','歩行者を確認','#page=2','発生事象']:self.assertIn(value,html)
        self.assertNotIn('23:58:00',html);self.assertNotIn('危険運転',html)
        self.assertNotIn('走行軌跡',html)

    def test_only_a_page_listed_in_the_report_gets_a_pdf_page_link(self):
        self.update(source_pages=[2],events=[dict(item_name='記録',raw_result='原文',source_page=7,status='unknown')])
        html=self.detail();self.assertNotIn('#page=7',html);self.assertIn('原本 7頁',html)
        self.assertIn('原本を開く',html)

    def test_zero_values_are_retained_and_missing_scores_are_not_rendered_as_zero(self):
        self.update(report_items=[dict(item_name='急加速',raw_result='0回',value='0',unit='回',numerator='0',denominator='20',score='0',source_page=1,status='confirmed')],events=[])
        html=self.detail()
        self.assertIn('0回',html);self.assertIn('点数 0',html)
        self.assertIn('<dt>分子</dt><dd>0</dd>',html)
        self.assertNotIn('発生事象</h3>',html)
        self.update(report_items=[dict(item_name='独自項目',raw_result='原文だけ',status='unknown')])
        html=self.detail();self.assertNotIn('点数 0',html)
        self.assertIn('原本ページ未取得',html)

    def test_review_editor_keeps_version_csrf_and_filtered_return_url(self):
        self.update(review=dict(state='followup',action='早めに減速する',driver_explanation='歩行者の飛び出しを確認',next_date='2026-11-05',note='運行条件を聞き取り',comparison_note='同じ車両と期間で比較',outcome='unknown'))
        destination='/safety/driving-reports?period=30d&office=安城#driver-trend'
        response=self.client.get('/safety/driving-reports/'+str(self.a.id)+'?'+urlencode({'return_to':destination}))
        html=response.get_data(as_text=True)
        for value in ['name="csrf_token"','name="version" value="'+version(self.a)+'"','id="report-review"','早めに減速する','歩行者の飛び出しを確認','2026-11-05','同じ車両と期間で比較']:self.assertIn(value,html)
        self.assertIn('period=30d&amp;office=',html)
        self.assertIn('name="return_to"',html)
        self.assertIn('運転実績へ戻る',html)

    def test_confirmed_user_reads_their_details_without_pdf_or_edit_operations(self):
        from dkss_app import driving_access
        from flask import session
        self.update(source_pages=[1],events=[dict(item_name='急減速',raw_result='1回',start_at='09:15',place='原文の場所',source_page=1,status='confirmed')],review=dict(state='followup',action='次の運行を振り返る',next_date='2026-11-05'))
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'));self.m.db.session.commit()
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'one','admin');self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'one', app=(self.client).application), username='one',role='user',password_changed_at='stamp')
        html=self.detail()
        for value in ['09:15','原文の場所','原本 1頁','次の運行を振り返る']:self.assertIn(value,html)
        for value in ['#page=1','原本を開く','閲覧設定を保存','確認内容を保存','取込取消を確定']:self.assertNotIn(value,html)
        self.assertEqual(self.client.get('/safety/driving-reports/'+str(self.b.id)).status_code,404)
        self.assertEqual(self.client.get('/safety/driving-reports/'+str(self.secret.id)).status_code,404)

    def test_empty_collections_do_not_create_four_empty_tables(self):
        self.update(report_items=[],events=[],duties=[],extra_items=[])
        html=self.detail()
        self.assertIn('この日報の項目は未取得です',html)
        self.assertNotIn('driving-report-item-grid',html)
        self.assertIn('運行・帳票の詳しい情報',html)
        self.assertIn('開始積算距離 km',html)


if __name__=='__main__':unittest.main()
