"""Disposable application DB: explicit bridge retains normal claim/save/UI flow."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_priority_deterministic_generation import actual_confirmation
from tools.quality.scoped_analysis.pilot import Policy, Request, Target, digest, SOL_STANDARD_30M, SOL_RATE_SOURCE
from tools.quality.scoped_analysis.ledger import Ledger
from tools.quality.scoped_analysis.final_gate import RESPONSES_URL
from tools.quality.scoped_analysis.http_candidate import COUNT_SOURCE
from tools.quality.scoped_analysis.job_bridge import ScopedJobBridge
from vehicle_karte_analysis_ai import prepare_vehicle_karte_analysis_request


class BridgeSavedTests(unittest.TestCase):
    def test_complete_normal_input_saved_without_global_http_patch(self):
        from dkss_app import analysis as service
        with tempfile.TemporaryDirectory() as tmp, actual_confirmation('progression') as (case,event_id,_):
            with case.app.test_request_context('/'):
                payload,_=service.get_vehicle_karte_analysis_job_data(case.vehicle)
                state=service.queue_vehicle_karte_analysis(case.vehicle,payload)
            target=Target(case.vehicle.company_code,case.vehicle.id,
                digest(json.loads(json.dumps(payload,default=str))))
            policy=Policy((target,),'gpt-6.1-sol',1,6000,500000,250000,'2','10',
                SOL_RATE_SOURCE,'2026-11-12',SOL_STANDARD_30M,RESPONSES_URL)
            body=prepare_vehicle_karte_analysis_request(payload,model=policy.model)
            body['service_tier']='default';raw=json.dumps(body)
            request=Request(target,raw,hashlib.sha256(raw.encode()).hexdigest(),10000,COUNT_SOURCE)
            ledger=Ledger.create(Path(tmp)/'ledger.sqlite',policy)
            calls=[]
            def transport(url,actual):
                self.assertEqual(actual,raw.encode());self.assertEqual(ledger.receipts()[0][3],'reserved')
                calls.append(actual)
                return {'status':'completed','output':[{'content':[{'type':'output_text',
                    'text':json.dumps({'overview':'synthetic only','recommendations':[]})}]}]}
            bridge=ScopedJobBridge(ledger,request,transport=transport)
            state.next_analysis_at=datetime.now(timezone.utc)-timedelta(seconds=1)
            case.db.session.commit()
            with patch('urllib.request.urlopen',side_effect=AssertionError('GLOBAL_HTTP_FORBIDDEN')):
                self.assertTrue(service.run_vehicle_karte_analysis_job(state.id,analysis_adapter=bridge))
            case.db.session.refresh(state);self.assertEqual(state.status,'completed')
            saved=state.result_json;self.assertEqual(len(calls),1)
            self.assertEqual(state.pilot_hold,request.body_sha256)
            self.assertFalse(service.run_vehicle_karte_analysis_job(state.id))
            self.assertEqual(case.request('POST',f'/vehicle/karte/{target.vehicle_id}/analysis').status_code,405)
            # Route currently GET-only; retain defense for a direct legacy POST call.
            from flask import session
            from werkzeug.exceptions import Conflict
            with case.app.test_request_context('/',method='POST'):
                session['username']='admin';session['company_code']=target.company
                with self.assertRaises(Conflict):
                    service.vehicle_karte_analysis(target.vehicle_id)
            result=case.request('GET',f'/vehicle/karte/{case.vehicle.id}/analysis/result').json
            self.assertTrue(result['is_current'])
            item,=result['analysis']['recommendations']
            self.assertEqual(item['priority_assessment']['effective_score'],65)
            with self.assertRaisesRegex(ValueError,'ALREADY_ATTEMPTED'):
                service.run_vehicle_karte_analysis_job(state.id,analysis_adapter=bridge)
            case.db.session.refresh(state);self.assertEqual(state.result_json,saved)
            self.assertEqual(len(calls),1)

    def test_persistent_hold_blocks_normal_retry_after_uncertainty_and_crash(self):
        from copy import deepcopy
        from dkss_app import analysis as service, analysis_worker
        from vehicle_analysis_repository import VehicleAnalysisJobRepository
        class ProcessDeath(BaseException): pass
        for mode in ('uncertain','crash','before_claim'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp, actual_confirmation('progression') as (case,_,__):
                with case.app.test_request_context('/'):
                    payload,_=service.get_vehicle_karte_analysis_job_data(case.vehicle)
                    state=service.queue_vehicle_karte_analysis(case.vehicle,payload)
                target=Target(case.vehicle.company_code,case.vehicle.id,digest(json.loads(json.dumps(payload,default=str))))
                policy=Policy((target,),'gpt-6.1-sol',1,6000,500000,250000,'2','10',
                    SOL_RATE_SOURCE,'2026-11-12',SOL_STANDARD_30M,RESPONSES_URL)
                body=prepare_vehicle_karte_analysis_request(payload,model=policy.model)
                body['service_tier']='default';raw=json.dumps(body)
                request=Request(target,raw,hashlib.sha256(raw.encode()).hexdigest(),10000,COUNT_SOURCE)
                ledger=Ledger.create(Path(tmp)/'ledger.sqlite',policy)
                def fail(*args): raise TimeoutError('synthetic uncertainty')
                bridge=ScopedJobBridge(ledger,request,transport=fail)
                state.next_analysis_at=datetime.now(timezone.utc)-timedelta(seconds=1)
                state_id=state.id;case.db.session.commit()
                if mode=='before_claim':
                    with patch.object(VehicleAnalysisJobRepository,'claim',side_effect=ProcessDeath):
                        with self.assertRaises(ProcessDeath):
                            service.run_vehicle_karte_analysis_job(state_id,analysis_adapter=bridge)
                elif mode=='crash':
                    with patch.object(ledger,'record_outcome',side_effect=ProcessDeath):
                        with self.assertRaises(ProcessDeath):
                            service.run_vehicle_karte_analysis_job(state_id,analysis_adapter=bridge)
                    self.assertEqual(ledger.receipts()[0][3],'reserved')
                else:
                    self.assertFalse(service.run_vehicle_karte_analysis_job(state_id,analysis_adapter=bridge))
                    self.assertEqual(ledger.receipts()[0][3],'uncertain')
                # Fresh DB session simulates process restart; no in-memory bridge needed.
                case.db.session.remove()
                state=case.db.session.get(case.models.VehicleKarteAnalysis,state_id)
                self.assertEqual(state.pilot_hold,request.body_sha256)
                state.next_analysis_at=datetime.now(timezone.utc)-timedelta(hours=2)
                state.lease_expires_at=datetime.now(timezone.utc)-timedelta(hours=2)
                case.db.session.commit()
                with patch.object(service._dkss_common,'analyze_vehicle_karte',side_effect=AssertionError('LEDGER_BYPASS')):
                    self.assertFalse(service.run_vehicle_karte_analysis_job(state_id))
                    self.assertEqual(analysis_worker.run_due_job(case.app),(0,0))
                    # A new input generation and ordinary queue update cannot remove hold.
                    changed=deepcopy(payload);changed['_fingerprints']['important_hash']='new-input'
                    with case.app.test_request_context('/'):
                        state=service.queue_vehicle_karte_analysis(case.db.session.get(case.models.Vehicle,target.vehicle_id),changed)
                    case.db.session.commit()
                    self.assertEqual(state.pilot_hold,request.body_sha256)
                    state.next_analysis_at=datetime.now(timezone.utc)-timedelta(seconds=1)
                    case.db.session.commit()
                    self.assertFalse(service.run_vehicle_karte_analysis_job(state_id))
                # Even a fresh pilot owner cannot silently reuse this held state.
                fresh=ScopedJobBridge(ledger,request,transport=fail)
                with self.assertRaises(ValueError):
                    service.run_vehicle_karte_analysis_job(state_id,analysis_adapter=fresh)
