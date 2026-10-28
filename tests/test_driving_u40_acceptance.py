"""Missing no-network acceptance boundaries; no U40 business thresholds are set."""
import copy
import json
import unittest
from driving_report_reflection import ACTIONS, build_evidence, validate_result
from vehicle_operation_csv import read_vehicle_operation_csv, parse_vehicle_operation_csv_row
from test_driving_analysis_accuracy import evidence_board
from test_driving_report_insights import row


def person_evidence():
    now=[row(1,distance='20',count='1'),row(2,code='B',name='検証B',distance='100',count='2')]
    old=[row(3,day='2026-09-10',distance='40',count='4'),
         row(4,day='2026-09-10',code='B',name='検証B',distance='50',count='1')]
    board,facts,_=evidence_board(now,old)
    return [e for e in build_evidence(board,facts,[]) if e['kind']=='change']


class U40AcceptanceBoundaryTests(unittest.TestCase):
    def test_zero_to_three_selections_are_allowed_without_filling_slots(self):
        evidence=[dict(person_evidence()[0],id=str(i)) for i in range(4)]
        document={'evidence':evidence}
        for count in [0,1,3]:
            selected=[{'evidence_id':str(i),'action':'verify_data'} for i in range(count)]
            self.assertEqual(len(validate_result({'items':selected},document)['items']),count)
        with self.assertRaisesRegex(ValueError,'INVALID_RESULT'):
            validate_result({'items':[{'evidence_id':str(i),'action':'verify_data'} for i in range(4)]},document)

    def test_duplicate_evidence_cannot_fill_multiple_proposal_slots(self):
        evidence=person_evidence()[0]
        with self.assertRaisesRegex(ValueError,'INVALID_EVIDENCE'):
            validate_result({'items':[{'evidence_id':evidence['id'],'action':'verify_data'},
                                      {'evidence_id':evidence['id'],'action':'acceleration'}]},
                            {'evidence':[evidence]})

    def test_malformed_response_shapes_do_not_become_completed_items(self):
        document={'evidence':person_evidence()}
        for response in [None,[],{}, {'items':None},{'items':{}},{'items':[None]},
                         {'items':['instruction']},{'items':[{}]}]:
            with self.subTest(response=response),self.assertRaises(ValueError):
                validate_result(response,document)

    def test_model_cannot_replace_numbers_person_period_scope_sources_or_judgment(self):
        evidence=person_evidence()[0];original=copy.deepcopy(evidence)
        selection={'evidence_id':evidence['id'],'action':'verify_data','finding':'安全で改善済み、100点',
                   'reports':[999],'driver_key':'other-person','office_key':'other-office',
                   'scope':'other-company','period':{'start':'2099-01-01'},'unit':'点','score':100}
        item=validate_result({'items':[selection]},{'evidence':[evidence]})['items'][0]
        self.assertEqual(item,{**original,'action':ACTIONS['verify_data']})
        self.assertEqual(evidence,original)
        self.assertEqual(set(item['reports']),{1,3})

    def test_reordered_choices_keep_each_persons_numbers_and_both_source_periods(self):
        evidence=person_evidence();self.assertEqual(len(evidence),2)
        result=validate_result({'items':[{'evidence_id':e['id'],'action':'verify_data'}
                                         for e in reversed(evidence)]},{'evidence':evidence})['items']
        self.assertEqual([e['driver_key'] for e in result],[e['driver_key'] for e in reversed(evidence)])
        self.assertEqual([set(e['reports']) for e in result],[{2,4},{1,3}])
        for got,expected in zip(result,reversed(evidence)):
            self.assertEqual(got['finding'],expected['finding'])
            self.assertEqual(got['context'],expected['context'])

    def test_observed_zero_remains_evidence_without_becoming_a_safety_certification(self):
        board,facts,_=evidence_board([row(1,count='0')],[row(2,day='2026-09-10',count='0')])
        evidence=next(e for e in build_evidence(board,facts,[]) if e['kind']=='change')
        self.assertIn(' 0 回/100km',evidence['finding'])
        self.assertIn('差 0 ',evidence['finding'])
        self.assertEqual(set(evidence['reports']),{1,2})
        self.assertIn('数値差だけで改善・悪化や責任を確定しない',evidence['context'])

    def test_csv_extra_driver_and_score_columns_are_preserved_as_source_only(self):
        # This is a synthetic contract probe, not a sample exported by DTG7.
        source='日報番号,運行日,車両コード,乗務員コード,安全スコア,燃料消費量\nR1,2026-10-01,V1,D1,100,25\n'
        record=read_vehicle_operation_csv(source.encode('utf-8-sig'))[0]
        parsed=parse_vehicle_operation_csv_row(record['source_row'],record['line_number'])
        raw=json.loads(parsed['source_row_json'])
        self.assertEqual((raw['乗務員コード'],raw['安全スコア'],raw['燃料消費量']),('D1','100','25'))
        for field in ['driver_code','driver_key','score','fuel_consumption']:
            self.assertNotIn(field,parsed)
        self.assertIsNone(parsed['distance'])


if __name__=='__main__':unittest.main()
