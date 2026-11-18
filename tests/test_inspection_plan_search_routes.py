"""Actual route and Excel search tests; disposable SQLite fixtures only."""
import unittest
from test_inspection_plan_excel import InspectionPlanExcelTests as Base
class SearchRoutes(unittest.TestCase):
    setUpClass=classmethod(Base.setUpClass.__func__)
    tearDownClass=classmethod(Base.tearDownClass.__func__)
    setUp=Base.setUp
    tearDown=Base.tearDown
    change=Base.change
    save=Base.save
    export=Base.export
    workbook=Base.workbook
    def test_content_factory_kind_and_state(self):
        one=self.change(kind='ad_hoc');one.update(note='ワイパー交換',factory='青凪工場');self.save([one,self.change(mon='2027-01')])
        for query in ['ワイパー','青凪工場','突発修理']:
            response=self.client.get('/vehicle/inspection-plans/export.xlsx',query_string={'scope':'company','year':2026,'q':query})
            wb=self.workbook(response);self.assertEqual(wb['点検明細'].max_row,2);self.assertEqual(wb['点検明細']['C2'].value,'突発修理')
        wb=self.workbook(self.client.get('/vehicle/inspection-plans/export.xlsx',query_string={'scope':'company','year':2026,'q':'ワイパー','state':'completed'}));self.assertEqual(wb['点検明細'].max_row,1)
    def test_search_does_not_expand_company_or_office(self):
        self.vehicle.office='安城';self.m.db.session.commit()
        one=self.change();one['note']='対象交換';self.save([one])
        foreign=self.m.Vehicle(company_code='FOREIGN',chassis_number='対象交換',office='安城');self.m.db.session.add(foreign);self.m.db.session.commit()
        response=self.client.get('/vehicle/inspection-plans/export.xlsx',query_string={'scope':'company','office':'安城','year':2026,'q':'対象交換'})
        wb=self.workbook(response);self.assertEqual(wb['年間点検計画'].max_row,5);self.assertEqual(wb['点検明細'].max_row,2)
        self.assertEqual(self.export('&vehicle_id='+str(foreign.id)+'&q=対象交換').status_code,404)
        self.assertEqual(self.export('&office=foreign-office&q=対象交換').status_code,400)
if __name__=='__main__':unittest.main()
