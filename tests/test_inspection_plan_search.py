import unittest
from inspection_plan_excel import annual_rows
class SearchTest(unittest.TestCase):
    def setUp(self):
        self.data={'vehicles':[{'id':1,'number':'品川１００か１０１','chassis_number':'AONAGI-101'},{'id':2,'number':'102','chassis_number':'B'}], 'plans':[{'vehicle_record_id':1,'kind':'ad_hoc','status':'planned','display_state':'reserved','note':'ワイパー交換','factory':'青凪工場'},{'vehicle_record_id':1,'kind':'3month','status':'planned','display_state':'unreserved','note':'オイル交換'},{'vehicle_record_id':999,'kind':'ad_hoc','status':'planned','display_state':'reserved','note':'ワイパー交換'}]}
    def test_fields(self):
        for q in ['ワイパー','青凪工場','突発修理']:
            v,p=annual_rows(self.data,{'q':q});self.assertEqual([x['id'] for x in v],[1]);self.assertEqual(len(p),1)
    def test_normalize_and_empty(self):
        self.assertEqual(len(annual_rows(self.data,{'q':'ＡＯＮＡＧＩ －１０１'})[1]),2)
        self.assertEqual(len(annual_rows(self.data,{})[0]),2)
        self.assertEqual(annual_rows(self.data,{'q':'不存在'}),([],[]))
    def test_filters(self):
        for args in [{'q':'ワイパー','kind':'3month'},{'q':'ワイパー','state':'unreserved'}]: self.assertEqual(annual_rows(self.data,args),([],[]))
        self.data['focus_vehicle_id']=2;self.assertEqual(annual_rows(self.data,{'q':'ワイパー'}),([],[]))
    def test_cancelled_and_foreign(self):
        self.data['plans'][0]['status']='cancelled';self.assertEqual(annual_rows(self.data,{'q':'ワイパー'}),([],[]))
if __name__=='__main__':unittest.main()
