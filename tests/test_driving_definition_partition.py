"""Guard OCR extraction boundaries without merging historical metric series."""
import copy
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import driving_report_ai as ai
from driving_report_data import metrics_summary
from driving_report_insights import metric
from test_driving_report_ai import extraction, pdf_bytes

BASE = dict(source_system='架空帳票', definition_version='fixture-1', report_scope='trip')
ITEM = dict(item_name='急減速回数', definition='当該運行の急減速検知回数。',
            threshold='架空設定：減速度0.3g以上を検知。', unit='回', road_type='一般道',
            value='2', status='candidate')

def rows(items, bases=None):
    return [SimpleNamespace(id=i, company_code='FICTIONAL', vehicle_record_id=1,
            operation_date=f'2026-11-{10+i:02}', details_json=json.dumps({
                **(bases[i-1] if bases else BASE), 'report_number':str(i), 'report_items':[x]}))
            for i,x in enumerate(items,1)]

class DefinitionPartitionTests(unittest.TestCase):
    def test_extraction_transport_receives_partition_rules(self):
        data=extraction()
        with patch.object(ai, 'extract_vehicle_document', return_value=data) as transport:
            ai.extract_driving_reports(pdf_bytes())
        rules=transport.call_args.kwargs['instructions']
        for rule in ['検知条件文をdefinitionに重複させない', '一文全体を保持する',
                     '以上と超を同じ条件にしない', 'thresholdはnull', '一般知識から補完しない']:
            self.assertIn(rule, rules)

    def test_original_extraction_is_not_rewritten(self):
        data=extraction()
        a=data['records'][0]['report_items'][0]
        a.update(ITEM, definition=ITEM['definition']+ITEM['threshold'])
        preview=ai.build_driving_report_preview(data, [])
        self.assertEqual(preview['original_records'][0]['report_items'][0]['definition'], a['definition'])
        preview['records'][0]['report_items'][0]['definition']='edited'
        self.assertEqual(preview['original_records'][0]['report_items'][0]['definition'], a['definition'])

    def test_exact_definition_combines_known_zero_not_missing(self):
        zero={**ITEM,'value':'0'}
        missing={**ITEM,'value':None,'status':'not_recorded'}
        result=metrics_summary(rows([ITEM,zero,missing]))
        self.assertEqual(len(result['groups']),1)
        self.assertEqual(result['groups'][0]['count'],2)
        self.assertEqual([v['value'] for v in result['groups'][0]['values']],['2','0'])
        self.assertEqual(metric(BASE, ITEM, Decimal(200), True)['id'],
                         metric(BASE, zero, Decimal(200), True)['id'])

    def test_condition_differences_and_ocr_split_stay_separate(self):
        variants=[{'threshold':'架空設定：減速度0.4g以上を検知。'},
                  {'threshold':'架空設定：減速度0.3g超を検知。'},
                  {'threshold':ITEM['threshold']+'1秒継続。'},
                  {'definition':ITEM['definition']+ITEM['threshold'], 'threshold':'減速度0.3g以上'},
                  {'unit':'回/h'}, {'road_type':'高速道'}]
        for changes in variants:
            other={**ITEM,**changes}
            with self.subTest(changes=changes):
                self.assertEqual(len(metrics_summary(rows([ITEM,other]))['groups']),2)
                self.assertNotEqual(metric(BASE, ITEM, Decimal(200), True)['id'],
                                    metric(BASE, other, Decimal(200), True)['id'])
        otherbase={**BASE,'definition_version':'fixture-2'}
        self.assertEqual(len(metrics_summary(rows([ITEM,ITEM],[BASE,otherbase]))['groups']),2)
        self.assertNotEqual(metric(BASE, ITEM, Decimal(200), True)['id'],
                            metric(otherbase, ITEM, Decimal(200), True)['id'])

if __name__=='__main__': unittest.main()
