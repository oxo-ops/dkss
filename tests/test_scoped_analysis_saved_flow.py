"""Synthetic normal generation -> durable reservation -> existing save/UI.

Only HTTP transport is fake. The ordinary confirmation, payload, job, save fence,
analysis API and dashboard projection run. No production hook is installed.
"""
from datetime import datetime,timedelta,timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_priority_deterministic_generation import actual_confirmation
from tools.quality.scoped_analysis.ledger import Ledger
from tools.quality.scoped_analysis.pilot import Target,Policy,Request,digest
import vehicle_karte_analysis_ai as generator
from tools.quality.scoped_analysis.http_candidate import post_json_synthetic, COUNT_PATH


class ScopedSavedFlowTests(unittest.TestCase):
    def test_reservation_existing_job_save_shared_screen_and_replay_refusal(self):
        from dkss_app import analysis as service
        from dkss_app.dashboard import get_dashboard_vehicle_attention
        with tempfile.TemporaryDirectory() as tmp, actual_confirmation('progression') as (case,event_id,confirm):
            with case.app.test_request_context('/'):
                payload,_=service.get_vehicle_karte_analysis_job_data(case.vehicle)
                state=service.queue_vehicle_karte_analysis(case.vehicle,payload)
            normalized=json.loads(json.dumps(payload,ensure_ascii=False,default=str))
            target=Target(case.vehicle.company_code,case.vehicle.id,digest(normalized))
            policy=Policy((target,),'synthetic-model',1,6000,500000,50000,'1','2','synthetic only','2026-11-12')
            path=Path(tmp)/'pilot.sqlite';ledger=Ledger.create(path,policy)
            expected=generator.prepare_vehicle_karte_analysis_request(normalized,model=policy.model)
            approved_raw=json.dumps(expected)
            approved=Request(target,approved_raw,hashlib.sha256(approved_raw.encode()).hexdigest(),10000,'synthetic bound')
            transmitted=[]
            http_calls=[]
            owner=self
            class MockConnection:
                def __init__(self,host,timeout,context):
                    owner.assertEqual(host,'api.openai.com')
                    owner.assertTrue(context.check_hostname)
                def request(self,method,url_path,body,headers):
                    self.path=url_path
                    owner.assertEqual(method,'POST')
                    http_calls.append(url_path)
                    if url_path=='/v1/responses':
                        owner.assertEqual(ledger.receipts()[0][3],'reserved')
                        owner.assertEqual(body,approved_raw.encode())
                def getresponse(self):
                    self.status=200
                    return self
                def read(self,limit):
                    if self.path==COUNT_PATH:
                        return json.dumps({'object':'response.input_tokens','input_tokens':10000}).encode()
                    reply={'overview':'synthetic empty model; confirmed facts retained','recommendations':[]}
                    return json.dumps({'status':'completed','output':[{'content':[
                        {'type':'output_text','text':json.dumps(reply)}]}]}).encode()
                def close(self): pass
            def fake_transport(request,**kwargs):
                raw=request.data.decode();self.assertEqual(json.loads(raw),expected)
                if ledger.receipts():
                    raise ValueError('PILOT_ALREADY_ATTEMPTED_NO_RETRY')
                # Existing normal job/save flow with its synthetic company A.
                count_body={key:expected[key] for key in ('model','instructions','input','text','reasoning')}
                counted=post_json_synthetic(COUNT_PATH,json.dumps(count_body).encode(),connection_factory=MockConnection)
                self.assertEqual(counted['input_tokens'],approved.input_token_upper_bound)
                _,number=Ledger(path,policy).reserve_exact_body(approved,raw,observed_target=target)
                transmitted.append(number)
                reply=post_json_synthetic('/v1/responses',raw.encode(),connection_factory=MockConnection)
                ledger.record_outcome(number,'returned')
                return BytesIO(json.dumps(reply).encode())
            def due():
                state.status='pending';state.next_analysis_at=datetime.now(timezone.utc)-timedelta(seconds=1)
                case.db.session.commit()
            due()
            with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only','OPENAI_MODEL':policy.model,
                                        'OPENAI_ANALYSIS_MODEL':policy.model}), \
                 patch.object(generator.urllib.request,'urlopen',side_effect=fake_transport):
                self.assertTrue(service.run_vehicle_karte_analysis_job(state.id))
            case.db.session.refresh(state);saved=state.result_json
            self.assertEqual(state.status,'completed');self.assertEqual(transmitted,[1])
            self.assertEqual(http_calls,[COUNT_PATH,'/v1/responses'])
            result=case.request('GET',f'/vehicle/karte/{case.vehicle.id}/analysis/result').json
            self.assertTrue(result['is_current'])
            item,=result['analysis']['recommendations']
            self.assertEqual(item['priority_assessment']['effective_score'],65)
            self.assertIn(f'confirmation:{event_id}:',item['priority_input_ref'])
            with case.app.test_request_context('/'):
                group=get_dashboard_vehicle_attention(case.vehicle.company_code,case.vehicle.office,[case.vehicle.id])['mine']
            self.assertEqual(group['items'][0]['proposal_id'],item['proposal_id'])
            self.assertEqual(group['items'][0]['priority_assessment']['effective_score'],65)
            for suffix in ('','/analysis'):
                response=case.request('GET',f'/vehicle/karte/{case.vehicle.id}{suffix}')
                self.assertEqual(response.status_code,200)
                self.assertIn('/analysis/result',response.get_data(as_text=True))
            # A lease/job retry cannot cause a second transport completion; old
            # saved result remains. No budget refund merely because save failed.
            due()
            with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only','OPENAI_MODEL':policy.model,
                                        'OPENAI_ANALYSIS_MODEL':policy.model}), \
                 patch.object(generator.urllib.request,'urlopen',side_effect=fake_transport):
                self.assertFalse(service.run_vehicle_karte_analysis_job(state.id))
            case.db.session.refresh(state)
            self.assertEqual(state.result_json,saved)
            self.assertEqual(transmitted,[1]);self.assertEqual(len(ledger.receipts()),1)
            self.assertEqual(http_calls,[COUNT_PATH,'/v1/responses'])

