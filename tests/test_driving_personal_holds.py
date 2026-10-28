"""Conflicting inspection corrections hold personal metrics without changing sources or access."""
import csv
import io
import unittest
from unittest.mock import patch
import test_driving_person_vehicles as vehicle_tests


class PersonalHoldTests(unittest.TestCase):
    setUpClass=classmethod(vehicle_tests.PersonalVehicleTests.setUpClass.__func__)
    tearDownClass=classmethod(vehicle_tests.PersonalVehicleTests.tearDownClass.__func__)
    setUp=vehicle_tests.PersonalVehicleTests.setUp
    tearDown=vehicle_tests.PersonalVehicleTests.tearDown
    save=vehicle_tests.PersonalVehicleTests.save
    login=vehicle_tests.PersonalVehicleTests.login
    inspection=vehicle_tests.PersonalVehicleTests.inspection
    grant=vehicle_tests.PersonalVehicleTests.grant
    render=vehicle_tests.PersonalVehicleTests.render
    form=vehicle_tests.PersonalVehicleTests.form
    post=vehicle_tests.PersonalVehicleTests.post

    def exclude(self,action='exclude',**kw):
        inspection=self.inspection()
        _,ctx=self.render();item=ctx['driving_vehicles']['candidates'][0]
        self.assertEqual(self.post(self.form(item,action,**kw)).status_code,302)
        return inspection

    def test_later_report_is_readable_but_not_personally_counted_and_sources_stay_intact(self):
        inspection=self.exclude();original=inspection.answers_json
        row=self.save(name='本人');raw=row.details_json
        response,ctx=self.render()
        self.assertIn('加算を保留',response.get_data(as_text=True))
        self.assertEqual(ctx['insights']['summary']['count'],0)
        self.assertIsNone(ctx['insights']['summary']['distance'])
        self.assertIsNone(ctx['insights']['summary']['value'])
        self.assertEqual(ctx['total'],1)
        self.assertEqual(ctx['driving_vehicles']['trips'],[])
        self.assertTrue(ctx['driving_vehicles']['corrections'][0]['reported'])
        self.assertEqual(ctx['reflection']['status'],'empty')
        self.assertEqual(self.client.get('/safety/driving-reports/'+str(row.id)).status_code,200)
        self.assertEqual(inspection.answers_json,original);self.assertEqual(row.details_json,raw)
        csv_response=self.client.get(self.url.replace('?', '/export.csv?'))
        values=list(csv.DictReader(io.StringIO(csv_response.data.decode('utf-8-sig'))))
        self.assertEqual(values[0]['走行距離km'],'100')
        self.assertIn('保留',values[0]['本人集計'])
        comparison=self.client.get(self.url.replace('?', '/export.csv?')+'&view=comparison')
        values=list(csv.DictReader(io.StringIO(comparison.data.decode('utf-8-sig'))))
        self.assertEqual(values[0]['運行数'],'0');self.assertEqual(values[0]['走行距離km'],'')
        self.assertEqual(values[0]['本人集計保留運行数'],'1')
        with patch('driving_report_management.export_pdf',return_value=b'%PDF-fixture') as pdf:
            response=self.client.get('/safety/driving-reports/export.pdf?period=all')
            self.assertEqual(response.status_code,200)
            text=str(pdf.call_args)
            self.assertIn('本人集計を保留',text)
            self.assertIn('以下は日報の原本値',text)
            self.assertNotIn('比較可能指標',text)

    def test_reset_restores_only_affected_day_and_invalidates_ai_input(self):
        self.exclude();self.save(name='本人')
        self.save(2,name='本人',day='2026-10-11',distance='60')
        _,held=self.render();self.assertEqual(held['insights']['summary']['distance'],60)
        item=held['driving_vehicles']['corrections'][0]
        self.assertEqual(self.post(self.form(item,'reset')).status_code,302)
        _,restored=self.render();self.assertEqual(restored['insights']['summary']['distance'],160)
        self.assertEqual(restored['insights']['summary']['count'],2)
        self.assertNotEqual(restored['reflection']['key'],held['reflection']['key'])

    def test_replacement_holds_original_vehicle_but_keeps_other_vehicle_on_same_day(self):
        self.exclude('replace',vehicle_id=self.b.id)
        self.save(name='本人')
        other=self.save(2,name='本人',distance='40');other.vehicle_record_id=self.b.id;self.m.db.session.commit()
        _,ctx=self.render();self.assertEqual(ctx['insights']['summary']['count'],1)
        self.assertEqual(ctx['insights']['summary']['distance'],40)
        self.assertEqual([v['id'] for v in ctx['driving_vehicles']['trips']],[self.b.id])

    def test_company_keeps_operation_while_person_rows_and_focus_hold_it(self):
        self.exclude();self.save(name='本人')
        self.login('admin','admin',self.m.User.query.filter_by(username='admin').one().password_changed_at)
        _,ctx=self.render(self.url+'&scope=company')
        self.assertEqual(ctx['insights']['summary']['distance'],100)
        person=next(p for p in ctx['insights']['drivers'] if p['name']=='本人')
        self.assertEqual(person['current']['count'],0);self.assertEqual(person['hold_count'],1)
        self.assertEqual(person['highlights'],[])
        _,focused=self.render(self.url+'&scope=company&focus='+person['key'])
        self.assertEqual(focused['insights']['summary']['count'],0)
        self.assertIsNotNone(focused['insights']['selected_driver'])
        self.assertEqual(focused['insights']['comparison']['rows'],[])

    def test_stale_inspection_evidence_does_not_hold_a_different_target_date(self):
        inspection=self.exclude();self.save(name='本人')
        inspection.day='11';self.m.db.session.commit()
        _,ctx=self.render();self.assertEqual(ctx['insights']['summary']['distance'],100)
        self.assertEqual(ctx['insights']['personal_hold_count'],0)

    def test_other_account_correction_never_holds_this_person(self):
        self.exclude();row=self.save(name='別人')
        self.m.db.session.add(self.m.User(company_code='TEST',username='two',role='user',password='unused',last_name='別人',password_changed_at='stamp'))
        self.m.db.session.commit();self.login('two')
        _,ctx=self.render();self.assertEqual(ctx['insights']['summary']['distance'],100)
        self.assertEqual(ctx['insights']['personal_hold_count'],0)
