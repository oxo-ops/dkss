"""Fuel evidence uses equivalent quantities once and keeps disputed pairs out of AI."""
import json
import unittest
from decimal import Decimal
from driving_report_fuel import fuel_reading
from driving_report_insights import collect,driver_keys,summarize
from driving_report_reflection import build_evidence
from driving_report_data import payload
import test_driving_report_insights as insight_tests
import test_driving_workspace as workspace_tests


def fuel_metrics(facts):
    return [metric for fact in facts for metric in fact['metrics'] if metric['method']=='fuel']


class FuelEvidenceDataTests(unittest.TestCase):
    def test_equivalent_numbers_and_litre_labels_are_counted_once(self):
        rows=[insight_tests.row(i,report_number='same',distance='100',fuel_consumption=amount,fuel_unit=unit)
              for i,(amount,unit) in enumerate([('10','L'),('10.0','ℓ'),('１０．００',' Ｌ '),('10','リットル')],1)]
        originals=[r.details_json for r in rows]
        facts,issues=collect(rows,{})
        self.assertEqual(len(facts),1);self.assertEqual(issues,[])
        metric=fuel_metrics(facts)[0];summary=summarize(facts,metric['id'])
        self.assertEqual(summary['display'],'10');self.assertEqual(summary['denominator'],10)
        self.assertEqual(summary['basis_display'],'100 km ／ 消費燃料 10 L')
        self.assertEqual([r.details_json for r in rows],originals)

    def test_conflicting_amounts_hold_only_fuel_and_explain_why(self):
        rows=[insight_tests.row(i,report_number='same',distance='100',fuel_consumption=amount,fuel_unit='L')
              for i,amount in [(1,'10'),(2,'20')]]
        facts,issues=collect(rows,{})
        self.assertEqual(fuel_metrics(facts),[]);self.assertEqual(len(facts),1)
        self.assertEqual(facts[0]['distance'],100)
        self.assertTrue(any(m['method']=='rate' for m in facts[0]['metrics']))
        self.assertIn('消費燃料の値が不一致',issues[0]['reason'])

    def test_amount_and_unit_must_be_explicit_on_the_same_copy(self):
        rows=[insight_tests.row(1,report_number='same',fuel_consumption='10',fuel_unit=None),
              insight_tests.row(2,report_number='same',fuel_consumption=None,fuel_unit='L')]
        reading,reason=fuel_reading(rows)
        self.assertIsNone(reading);self.assertIn('同じ日報でL単位',reason)
        for value,unit in [('0','L'),('-1','L'),('NaN','L'),('10','gal'),('10000','mL')]:
            reading,reason=fuel_reading([insight_tests.row(3,fuel_consumption=value,fuel_unit=unit)])
            self.assertIsNone(reading);self.assertTrue(reason)
        self.assertEqual(fuel_reading([insight_tests.row(4)]),(None,''))

    def test_settings_are_separate_between_operations_and_held_between_copies(self):
        a=insight_tests.row(1,fuel_consumption='10',fuel_unit='L',definition_version='v1')
        b=insight_tests.row(2,fuel_consumption='20',fuel_unit='L',definition_version='v2')
        facts,issues=collect([a,b],{});metrics=fuel_metrics(facts)
        self.assertEqual(len({m['id'] for m in metrics}),2)
        self.assertTrue(all(summarize(facts,m['id'])['metric_count']==1 for m in metrics))
        self.assertEqual(issues,[])
        b.details_json=json.dumps(dict(payload(b),report_number='R1'))
        facts,issues=collect([a,b],{})
        self.assertEqual(fuel_metrics(facts),[]);self.assertIn('不一致',issues[0]['reason'])
        b.details_json=json.dumps(dict(payload(b),fuel_consumption='10'))
        facts,issues=collect([a,b],{})
        self.assertEqual(fuel_metrics(facts),[]);self.assertIn('設定版',issues[0]['reason'])

    def test_valid_distinct_operations_still_use_paired_weighted_fuel(self):
        rows=[insight_tests.row(1,distance='100',fuel_consumption='10',fuel_unit='L'),
              insight_tests.row(2,distance='300',fuel_consumption='20.00',fuel_unit='ℓ'),
              insight_tests.row(3,distance='900',fuel_consumption='0',fuel_unit='L')]
        facts,issues=collect(rows,{});metric=fuel_metrics(facts)[0]
        result=summarize(facts,metric['id'])
        self.assertEqual(result['value'],Decimal(400)/30)
        self.assertEqual(result['metric_count'],2);self.assertEqual(result['basis_display'],'400 km ／ 消費燃料 30 L')
        self.assertTrue(any('0・負数' in item['reason'] for item in issues))


class FuelEvidenceRouteTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def fuel(self,row,amount,unit='L'):
        data=payload(row);data.update(fuel_consumption=amount,fuel_unit=unit)
        row.details_json=json.dumps(data);self.m.db.session.commit()

    def test_page_exports_and_ai_share_the_reconciled_fuel(self):
        self.fuel(self.a,'5')
        duplicate=self.save(8,report_number='R1',distance='20',count='1')
        self.fuel(duplicate,'5.00','ℓ')
        self.fuel(self.b,'999');self.fuel(self.secret,'12345')
        _,context=self.render(self.base)
        metric=next(m for m in context['insights']['groups'] if m['method']=='fuel')
        response,context=self.render(self.base+'&metric='+metric['id'])
        self.assertEqual(context['insights']['summary']['display'],'4')
        self.assertIn('20 km ／ 消費燃料 5 L',response.get_data(as_text=True))
        for view in ['comparison','breakdown']:
            exported=self.client.get('/safety/driving-reports/export.csv?period=all&view='+view+'&metric='+metric['id'])
            text=exported.data.decode('utf-8-sig');self.assertIn('20 km ／ 消費燃料 5 L',text)
            self.assertNotIn('999 L',text);self.assertNotIn('12345',text)
        keys,_=driver_keys([self.a,duplicate]);facts,_=collect([self.a,duplicate],{},keys)
        evidence=build_evidence(context['insights'],facts,[])
        self.assertIn('消費燃料 5 L',str(evidence));self.assertNotIn('999',str(evidence))

    def test_conflict_is_visible_and_cannot_supply_an_ai_fuel_claim(self):
        self.fuel(self.a,'5')
        duplicate=self.save(8,report_number='R1',distance='20',count='1');self.fuel(duplicate,'7')
        response,context=self.render(self.base)
        board=context['insights'];self.assertEqual(board['summary']['distance'],20)
        self.assertIn('消費燃料の値が不一致',response.get_data(as_text=True))
        self.assertEqual({item['id'] for item in board['review_notes']},{self.a.id,duplicate.id})
        self.assertFalse(any(m['method']=='fuel' for m in board['groups']))
        keys,_=driver_keys([self.a,duplicate]);facts,_=collect([self.a,duplicate],{},keys)
        evidence=build_evidence(board,facts,[])
        self.assertNotIn('期間燃費',str(evidence))


if __name__=='__main__':unittest.main()
