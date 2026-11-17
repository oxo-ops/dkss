import copy,sys,unittest
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from daily_inspection_defaults import get_daily_inspection_default
class CriteriaTests(unittest.TestCase):
 def setUp(self):
  self.spec=get_daily_inspection_default()
  self.env=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=True)
  self.show=self.env.get_template('partials/daily_inspection_row_criteria.html').module.criteria_for_item
 def test_all_27_conditions(self):
  self.assertEqual(len(self.spec['items']),27)
  for item in self.spec['items']:
   with self.subTest(code=item['item_code']):
    before=copy.deepcopy(item);s=str(self.show(item,'daily_inspection_truck_trailer'))
    self.assertEqual('エアブレーキ' in s,item['item_code'] in ['daily_04','daily_05','daily_19','daily_20'])
    self.assertEqual('8t' in s,item['item_code']=='daily_18')
    self.assertEqual('適切な時期' in s,item['shaded'])
    self.assertNotIn('注1',s);self.assertEqual(item,before)
 def test_history_and_custom_fallback(self):
  for item in self.spec['items']:
   for key,value in [('content','changed'),('category','changed'),('criteria','custom'),('item_code','unknown'),('criteria_files',['file.pdf']),('choices',['a']),('shaded',not item['shaded'])]:
    x=copy.deepcopy(item);x[key]=value
    self.assertEqual(str(self.show(x,'daily_inspection_truck_trailer')),x['criteria'])
   self.assertEqual(str(self.show(item,'other')),item['criteria'])
 def test_top_block_only_omits_exact_standard(self):
  template=(ROOT/'templates/vehicle_checklist_results.html').read_text()
  begin=template.index('{% set criteria_keys = [] %}');end=template.index('{% if display_mode == "day_list"',begin)
  block='{% from "partials/daily_inspection_row_criteria.html" import is_standard_item %}'+template[begin:end]
  render=self.env.from_string(block)
  rows=copy.deepcopy(self.spec['items'])
  out=render.render(table_checklist={'fixed_template_code':'daily_inspection_truck_trailer','items':rows})
  self.assertNotIn('criteria-box',out)
  rows[0]['criteria']='保全の特別基準'
  out=render.render(table_checklist={'fixed_template_code':'daily_inspection_truck_trailer','items':rows})
  self.assertIn('保全の特別基準',out)
  rows[1]['criteria_files']=['criteria.pdf']
  out=render.render(table_checklist={'fixed_template_code':'daily_inspection_truck_trailer','items':rows})
  self.assertIn('criteria.pdf',out);self.assertIn('【注1】',out)
  out=render.render(table_checklist={'fixed_template_code':'custom','items':self.spec['items']})
  self.assertIn('【注1】',out)
 def test_footer_original_and_changed_fallback(self):
  for f in self.spec['footer_fields']:
   if f['field_type']!='check':continue
   row={'item_type':'check','item_code':'footer_'+str(f['order']),'category':'','content':f['label'],'criteria':self.spec['criteria'],'choices':f['choices'],'shaded':False,'criteria_files':[]}
   self.assertEqual(str(self.show(row,'daily_inspection_truck_trailer')),'✓ 正常 / × 異常')
   row['content']='changed';self.assertEqual(str(self.show(row,'daily_inspection_truck_trailer')),self.spec['criteria'])
 def test_raw_saved_criteria_stays_separate(self):
  template=(ROOT/'templates/vehicle_checklist_results.html').read_text()
  self.env.get_template('vehicle_checklist_results.html')
  self.assertEqual(template.count("data-criteria=\"{{ (item.criteria or '')|e }}\""),2)
  script=(ROOT/'static/js/vehicle_checklist_results.js').read_text()
  self.assertIn('criteriaDisplay || "未設定"',script)
  self.assertRegex(script,r'detailCriteria"\s*\)\.value\s*=\s*criteria')
if __name__=='__main__':unittest.main()
