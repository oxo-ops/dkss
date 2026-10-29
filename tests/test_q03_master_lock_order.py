"""Real Office mutation versus daily Vehicle -> User save locks, both orders."""
import html
import json
import re

from q04_pg_helpers import PrivatePostgresCase


class VehiclePersonMasterLockTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            items=[{'item_type':'check','content':'Synthetic','input_type':'text',
                    'fixed_template_code':'daily_inspection_truck_trailer'},
                   {'item_type':'approval','approval_label':'Synthetic','approval_allow_general':True}]
            checklist=self.m.Checklist(company_code=self.company,name='Synthetic daily',
                target='車両管理',frequency_unit='day',display_type='month',active=True,
                items_json=json.dumps(items))
            self.db.session.add(checklist)
            self.db.session.flush()
            vehicle=self.m.Vehicle.query.filter_by(company_code=self.company).one()
            row=self.m.VehicleChecklistResult(company_code=self.company,checklist_id=checklist.id,
                vehicle_record_id=vehicle.id,year='2026',month='10',day='23',status='入力中',
                checked_by_username='admin',answers_json='[{"item_no":0,"value":"ok"}]',
                approvals_json='[]',checklist_snapshot_json=json.dumps({'id':checklist.id,
                    'name':checklist.name,'items':items}))
            self.db.session.add(row)
            self.db.session.commit()
            self.row_id=row.id
            self.data={'vehicle_record_id':vehicle.id,'year':'2026','month':'10','day':'23',
                       'approval_notify_users_0':'admin'}
            self.path=f'/vehicle/checklists/{checklist.id}'
        with self.client() as client:
            response=client.get(self.path,query_string={**self.data,'active_day':'23'})
            try:
                self.assertEqual(response.status_code,200)
                match=re.search(r'name="person_selection_token"\s+value="([^"]+)"',response.get_data(as_text=True))
                self.assertIsNotNone(match)
                self.data['person_selection_token']=html.unescape(match[1])
            finally:
                response.close()
        self.foreign_before=self.snapshot(self.other)

    def race(self,operation,master_first):
        master=self.action(f'/master/offices/{self.ids["offices"]}/{operation}',
            {'name':'Renamed'} if operation=='edit' else {})
        complete=self.action(self.path+'/complete',self.data)
        actions=(master,complete) if master_first else (complete,master)
        results,waited=self.schedule(*actions,'unused',first_prefix=(
            'update "user" set office=' if master_first else 'update vehicle set id='))
        mutated,saved=results if master_first else reversed(results)
        self.assertEqual(mutated.get('status'),302,repr(results))
        self.assertEqual(saved.get('status'),200,repr(results))
        self.assertTrue(waited)
        with self.app.app_context():
            row=self.db.session.get(self.m.VehicleChecklistResult,self.row_id)
            self.assertEqual(row.status,'承認待ち')
            self.assertEqual(json.loads(row.answers_json)[0]['value'],'ok')
        self.assertEqual(self.snapshot(self.other),self.foreign_before)

    def test_vehicle_then_office_rename(self):
        self.race('edit',False)

    def test_vehicle_then_office_delete(self):
        self.race('delete',False)

    def test_office_rename_then_vehicle(self):
        self.race('edit',True)

    def test_office_delete_then_vehicle(self):
        self.race('delete',True)
