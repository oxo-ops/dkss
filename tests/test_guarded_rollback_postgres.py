"""Native PostgreSQL retention boundaries; explicit disposable Q08 fixture only.

No network/DB connection on import. CI requires all 24 tests with zero skips.
Events establish order; pg_blocking_pids proves a real server-side row-lock wait.
"""
from concurrent.futures import ThreadPoolExecutor
import re
import threading
import time
import unittest
from unittest.mock import patch

from sqlalchemy import event, text
import test_guarded_rollback_retention as retention
from test_q08_postgres_identity import DisposablePostgres
from test_inspection_document_ai import extraction, pdf_bytes


class RaceTools:
    def auth_client(self):
        client = self.m.app.test_client()
        with self.client.session_transaction() as session:
            auth = dict(session)
        with client.session_transaction() as session:
            session.update(auth)
        return client

    def rows(self, Model, ident):
        self.m.db.session.expire_all()
        row = self.m.db.session.get(Model, ident)
        return {c.key: getattr(row, c.key) for c in Model.__table__.columns}

    def protected_writer(self, Model, ident, operation, *, periodic=False, preload=False, at_boundary=False):
        """Worker reads old row, writer updates without commit, worker blocks, commit.

        The holder never acquires application/business locks. Observer connection
        is from the schema-scoped engine, never DATABASE_URL or a live source.
        """
        engine = self.m.db.engine
        self.m.db.session.remove()
        ready, proceed = threading.Event(), threading.Event()
        pid = []
        def run():
            with self.m.app.app_context():
                try:
                    session = self.m.db.session
                    session.execute(text("SET LOCAL statement_timeout = '12000ms'"))
                    session.execute(text("SET LOCAL lock_timeout = '10000ms'"))
                    pid.append(session.scalar(text('SELECT pg_backend_pid()')))
                    stale = session.get(Model, ident) if preload else None
                    if preload:
                        self.assertFalse(retention.requires_newer_version(stale.result_json, periodic=periodic))
                    def gate():
                        pid[:] = [session.scalar(text('SELECT pg_backend_pid()'))]
                        ready.set()
                        if not proceed.wait(10):
                            raise AssertionError('Worker was not released')
                    if at_boundary:
                        answer = operation(gate)
                    else:
                        gate()
                        answer = operation()
                    # Keep stale in the identity map through the actual operation.
                    self.assertTrue(stale is not None or not preload)
                    return answer
                finally:
                    self.m.db.session.remove()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            try:
                self.assertTrue(ready.wait(10), 'worker did not read old row')
                with engine.connect() as holder:
                    transaction = holder.begin()
                    try:
                        holder_pid = holder.scalar(text('SELECT pg_backend_pid()'))
                        holder.execute(Model.__table__.update().where(Model.id == ident).values(
                            result_json=retention.saved('held', 'periodic' if periodic else 'analysis'),
                            status='completed'))
                        expected = dict(holder.execute(Model.__table__.select().where(Model.id == ident)).mappings().one())
                        proceed.set()
                        deadline = time.monotonic() + 8
                        with engine.connect() as observer:
                            while True:
                                blockers = observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pid[0]})
                                if holder_pid in blockers:
                                    break
                                if future.done():
                                    future.result()
                                    self.fail('Operation completed without waiting for the protected row lock')
                                if time.monotonic() >= deadline:
                                    self.fail('No PostgreSQL lock wait observed')
                                # Bounded polling of a server condition, not a timing-based race.
                                threading.Event().wait(.01)
                        transaction.commit()
                    finally:
                        if transaction.is_active:
                            transaction.rollback()
                answer = future.result(timeout=12)
            finally:
                proceed.set()
        self.assertEqual(expected, self.rows(Model, ident))
        return answer


class PostgresGuardRetentionTests(RaceTools, DisposablePostgres, unittest.TestCase):
    setUp = retention.RetentionDatabaseTests.setUp
    tearDown = retention.RetentionDatabaseTests.tearDown
    upload_inspection = retention.RetentionDatabaseTests.upload_inspection
    inspection_form = retention.RetentionDatabaseTests.inspection_form
    import_record = retention.RetentionDatabaseTests.import_record
    input = retention.RetentionDatabaseTests.input
    cached = retention.RetentionDatabaseTests.cached
    analysis = retention.RetentionDatabaseTests.analysis
    repo = retention.RetentionDatabaseTests.repo

    def test_analysis_mutations_refresh_stale_identity_and_wait_for_new_result(self):
        vehicle_id = self.vehicle.id
        for operation in ('claim', 'finish', 'fail', 'skip', 'renew'):
            with self.subTest(operation=operation):
                self.vehicle = self.m.db.session.get(self.m.Vehicle, vehicle_id)
                row = self.analysis('{}', status='running')
                ident, digest = row.id, row.input_hash
                def act():
                    repo = self.repo()
                    if operation == 'claim':
                        self.assertFalse(repo.claim(ident, digest, 'replacement', retention.NOW))
                    elif operation == 'finish':
                        self.assertFalse(repo.finish(ident, 'token', claimed_hash=digest, snapshot_hash=digest,
                            bundle={'analysis': {'recommendations': []}}, finished=retention.NOW, method='ai'))
                    elif operation == 'renew':
                        with self.assertRaisesRegex(RuntimeError, 'ANALYSIS_LEASE_LOST'):
                            repo.renew(ident, 'token', retention.NOW)
                    elif operation == 'fail':
                        repo.fail(ident, 'token', 'old-failure', retention.NOW)
                    else:
                        repo.skip(ident, 'token')
                self.protected_writer(self.m.VehicleKarteAnalysis, ident, act, preload=True)
                self.m.db.session.delete(self.m.db.session.get(self.m.VehicleKarteAnalysis, ident))
                self.m.db.session.commit()

    def test_stale_analysis_tokens_cannot_change_even_legacy_rows(self):
        row = self.analysis('{}', status='running')
        ident, digest = row.id, row.input_hash
        before = self.rows(type(row), ident)
        repo = self.repo()
        self.assertFalse(repo.finish(ident, 'stale', claimed_hash=digest, snapshot_hash=digest,
            bundle={}, finished=retention.NOW, method='ai'))
        repo.fail(ident, 'stale', 'failure', retention.NOW)
        repo.skip(ident, 'stale')
        with self.assertRaisesRegex(RuntimeError, 'ANALYSIS_LEASE_LOST'):
            repo.renew(ident, 'stale', retention.NOW)
        self.assertEqual(before, self.rows(type(row), ident))

    def generation_race(self, periodic, failure):
        row = self.cached(status='running') if periodic else self.analysis('{}')
        Model, ident = type(row), row.id
        token, record_id = (row.run_token, self.record.id) if periodic else (None, None)
        started, resume = threading.Event(), threading.Event()
        def generate(*args, **kwargs):
            started.set()
            if not resume.wait(10):
                raise AssertionError('Generation not released')
            if failure:
                raise RuntimeError('synthetic old worker failure')
            return {'overview': 'old worker', 'recommendations': []}
        def run():
            with self.m.app.app_context():
                try:
                    if periodic:
                        return self.service.worker('TEST', record_id, token, {})
                    return self.m.run_vehicle_karte_analysis_job(ident)
                finally:
                    self.m.db.session.remove()
        engine = self.m.db.engine
        self.m.db.session.remove()
        target = 'vehicle_periodic_followups.generate_periodic_proposals' if periodic else None
        with patch(target, side_effect=generate) if periodic else patch.object(self.m, 'analyze_vehicle_karte', side_effect=generate):
            with patch.object(self.m, 'get_vehicle_karte_analysis_job_data', return_value=({'_fingerprints': retention.fingerprints(), 'coverage': {}}, {})):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(run)
                    try:
                        self.assertTrue(started.wait(10), 'old worker did not claim/read')
                        with engine.begin() as other:
                            other.execute(Model.__table__.update().where(Model.id == ident).values(
                                result_json=retention.saved('active', 'periodic' if periodic else 'analysis'), status='completed'))
                            expected = dict(other.execute(Model.__table__.select().where(Model.id == ident)).mappings().one())
                    finally:
                        resume.set()
                    future.result(timeout=12)
        self.assertEqual(expected, self.rows(Model, ident))

    def test_claimed_analysis_success_retains_committed_new_result(self):
        self.generation_race(False, False)

    def test_claimed_analysis_failure_retains_committed_new_result(self):
        self.generation_race(False, True)

    def test_periodic_success_retains_committed_new_result(self):
        self.generation_race(True, False)

    def test_periodic_failure_retains_committed_new_result(self):
        self.generation_race(True, True)

    def test_periodic_post_waits_and_refuses_protected_result_before_start(self):
        row = self.cached(status='error')
        ident, api, client = row.id, self.api, self.auth_client()
        with patch.object(self.executor, 'submit') as submit:
            status = self.protected_writer(self.Proposal, ident,
                lambda: client.post(api, json={'retry': True}).status_code, periodic=True)
            self.assertEqual(status, 409)
            submit.assert_not_called()

    def test_periodic_submit_failure_cas_retains_new_result_and_stale_worker_does_nothing(self):
        row = self.cached(status='error')
        ident, old_token = row.id, row.run_token
        engine = self.m.db.engine
        expected = {}
        def submit(*args):
            with engine.begin() as other:
                other.execute(self.Proposal.__table__.update().where(self.Proposal.id == ident).values(
                    result_json=retention.saved('held', 'periodic'), status='completed'))
                expected.update(other.execute(self.Proposal.__table__.select().where(self.Proposal.id == ident)).mappings().one())
            raise RuntimeError('synthetic submit failure')
        with patch.object(self.executor, 'submit', side_effect=submit) as submitting:
            self.client.post(self.api, json={'retry': True})
            submitting.assert_called_once()
        self.assertEqual(expected, self.rows(self.Proposal, ident))
        with patch('vehicle_periodic_followups.generate_periodic_proposals') as generate:
            self.service.worker('TEST', self.record.id, old_token, {})
            generate.assert_not_called()
        self.assertEqual(expected, self.rows(self.Proposal, ident))


    def periodic_final_lock(self, failure):
        row = self.cached(status='running')
        ident, token, record_id = row.id, row.run_token, self.record.id
        def operation(gate):
            def generate(*args):
                gate()
                if failure:
                    raise RuntimeError('synthetic failure')
                return {'overview': 'old', 'recommendations': []}
            with patch('vehicle_periodic_followups.generate_periodic_proposals', side_effect=generate):
                self.service.worker('TEST', record_id, token, {})
        self.protected_writer(self.Proposal, ident, operation, periodic=True, at_boundary=True)

    def test_periodic_final_success_waits_for_protected_writer(self):
        self.periodic_final_lock(False)

    def test_periodic_final_failure_waits_for_protected_writer(self):
        self.periodic_final_lock(True)

    def test_stale_periodic_token_cannot_change_legacy_result(self):
        row = self.cached(status='running')
        ident, record_id = row.id, self.record.id
        before = self.rows(self.Proposal, ident)
        with patch('vehicle_periodic_followups.generate_periodic_proposals') as generate:
            self.service.worker('TEST', record_id, 'stale-token', {})
            generate.assert_not_called()
        self.assertEqual(before, self.rows(self.Proposal, ident))

    def test_duplicate_legacy_claims_have_exactly_one_winner(self):
        row = self.analysis('{}')
        ident, digest = row.id, row.input_hash
        self.m.db.session.remove()
        barrier = threading.Barrier(2)
        def claim(token):
            with self.m.app.app_context():
                try:
                    barrier.wait(timeout=10)
                    return self.repo().claim(ident, digest, token, retention.NOW)
                finally:
                    self.m.db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(claim, ['first', 'second']))
        self.assertEqual(sorted(answers), [False, True])
        state = self.rows(self.m.VehicleKarteAnalysis, ident)
        self.assertEqual(state['lease_token'], ['first', 'second'][answers.index(True)])
        self.assertEqual(state['status'], 'running')

    def test_concurrent_first_creation_fallback_locks_latest_protected_row_before_queue(self):
        Model = self.m.VehicleKarteAnalysis
        self.assertEqual(Model.query.count(), 0)
        vehicle_id, engine = self.vehicle.id, self.m.db.engine
        self.m.db.session.remove()
        ready, proceed = threading.Event(), threading.Event()
        fallback_ready, fallback_proceed = threading.Event(), threading.Event()
        worker_pid, sql = [], []
        gated = []
        def observe(conn, cursor, statement, parameters, context, many):
            if threading.current_thread() is threading.main_thread():
                return
            sql.append(statement)
            if statement.lstrip().startswith('INSERT INTO vehicle_karte_analysis') and not gated:
                gated.append(True)
                ready.set()
                if not proceed.wait(10):
                    raise AssertionError('First insert was not released')
            elif gated and statement.lstrip().startswith('SELECT ') and 'FROM vehicle_karte_analysis' in statement:
                fallback_ready.set()
                if not fallback_proceed.wait(10):
                    raise AssertionError('Uniqueness fallback was not released')
        def queue():
            with self.m.app.app_context():
                try:
                    session = self.m.db.session
                    session.execute(text("SET LOCAL statement_timeout = '12000ms'"))
                    worker_pid.append(session.scalar(text('SELECT pg_backend_pid()')))
                    vehicle = session.get(self.m.Vehicle, vehicle_id)
                    self.m.queue_vehicle_karte_analysis(vehicle, {'_fingerprints':retention.fingerprints(important='changed')})
                    session.commit()
                finally:
                    self.m.db.session.remove()
        event.listen(engine, 'before_cursor_execute', observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(queue)
                try:
                    self.assertTrue(ready.wait(10), 'initial absence/insert boundary not reached')
                    with engine.begin() as creator:
                        ident = creator.execute(Model.__table__.insert().values(company_code='TEST',
                            vehicle_record_id=vehicle_id, result_json='{}').returning(Model.id)).scalar_one()
                    proceed.set()
                    self.assertTrue(fallback_ready.wait(10), 'uniqueness fallback not reached')
                    with engine.connect() as holder:
                        transaction = holder.begin()
                        try:
                            holder_pid = holder.scalar(text('SELECT pg_backend_pid()'))
                            holder.execute(Model.__table__.update().where(Model.id == ident).values(
                                status='completed', result_json=retention.saved('held', 'analysis')))
                            expected = dict(holder.execute(Model.__table__.select().where(Model.id == ident)).mappings().one())
                            fallback_proceed.set()
                            deadline = time.monotonic() + 8
                            with engine.connect() as observer:
                                while holder_pid not in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid':worker_pid[0]}):
                                    if future.done():
                                        future.result()
                                        self.fail('Uniqueness fallback did not wait for protected row')
                                    if time.monotonic() >= deadline:
                                        self.fail('Fallback protected-row wait not observed')
                                    threading.Event().wait(.01)
                            transaction.commit()
                        finally:
                            if transaction.is_active:
                                transaction.rollback()
                    future.result(timeout=12)
                finally:
                    proceed.set()
                    fallback_proceed.set()
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
        selects = [s for s in sql if s.lstrip().startswith('SELECT ') and 'FROM vehicle_karte_analysis' in s]
        self.assertGreaterEqual(len(selects), 2)
        self.assertTrue(all('FOR UPDATE' in s for s in selects), selects)
        self.assertTrue(any('ROLLBACK TO SAVEPOINT' in s for s in sql))
        self.assertEqual(expected, self.rows(Model, ident))


class PostgresGuardDocumentTests(RaceTools, DisposablePostgres, unittest.TestCase):
    setUp = retention.CorrectionRetentionTests.setUp
    tearDown = retention.CorrectionRetentionTests.tearDown
    upload_inspection = retention.CorrectionRetentionTests.upload_inspection
    inspection_form = retention.CorrectionRetentionTests.inspection_form
    worker = retention.CorrectionRetentionTests.worker
    invoice = retention.CorrectionRetentionTests.invoice
    kind_post = retention.CorrectionRetentionTests.kind_post

    def source(self):
        source = pdf_bytes()
        data = extraction(source)
        data['records'][0].update(inspection_type='other', next_inspection_date=None, next_inspection_month=None)
        self.upload_inspection(data=data, source=source)
        draft = self.m.VehicleDocumentImportDraft.query.one()
        form = self.inspection_form(draft)
        form['inspection_type_' + draft.id + '_0'] = 'other'
        self.assertEqual(self.client.post('/vehicle/data-import/' + draft.batch_id + '/confirm', data=form).status_code, 302)
        return draft

    def document_race(self, correction, periodic=False):
        draft = self.source()
        if correction:
            self.assertEqual(self.kind_post(draft, 'maintenance').status_code, 303)
            self.worker(invoice=True)
            replacement = self.m.VehicleDocumentImportDraft.query.filter(self.m.VehicleDocumentImportDraft.id != draft.id).one()
            replacement_id = replacement.id
            key = replacement_id + '_0'
            path = '/vehicle/data-import/' + replacement.batch_id + '/confirm'
            body = {'include': key, 'vehicle_' + key: str(self.vehicle.id), 'date_' + key: '2026-08-01',
                    'content_' + key: '故障修理', 'confirm_kind_correction': 'yes'}
        else:
            path = f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete'
            page = self.client.get(path)
            token = re.search(r'name="delete_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
            body = {'delete_token': token, 'confirm_delete': 'yes'}
        State = self.m.VehicleKarteAnalysis
        state = State.query.filter_by(vehicle_record_id=self.vehicle.id).first()
        if state is None:
            state = State(company_code='TEST', vehicle_record_id=self.vehicle.id, result_json='{}')
            self.m.db.session.add(state)
        self.m.db.session.commit()
        ident = state.id
        Proposal = self.m.periodic_followups.Proposal
        record = self.m.VehiclePeriodicInspectionRecord.query.one()
        proposal = Proposal(company_code='TEST', inspection_record_id=record.id, input_hash='old',
            run_token='old-token', status='completed', result_json='{}', updated_at=retention.NOW.isoformat())
        self.m.db.session.add(proposal)
        self.m.db.session.commit()
        if periodic:
            State, ident = Proposal, proposal.id
        from dkss_app.models import VehicleDocumentSource
        models = [self.m.VehicleDocumentImportDraft, VehicleDocumentSource,
                  self.m.VehiclePeriodicInspectionRecord, self.m.VehicleMaintenanceRecord,
                  self.m.VehiclePartReplacement, self.m.VehicleAnalysisFeedback]
        def snapshot():
            self.m.db.session.remove()
            result = {M.__tablename__: [dict(r) for r in self.m.db.session.execute(M.__table__.select().order_by(*M.__table__.primary_key.columns)).mappings()] for M in models}
            if correction:
                # Normal validation preserves editable replacement preview fields.
                # The original source and all business rows must remain byte-identical.
                for item in result[self.m.VehicleDocumentImportDraft.__tablename__]:
                    if item['id'] == replacement_id:
                        item.pop('preview_json')
            return result
        before = snapshot()
        client = self.auth_client()
        sql = []
        def observe(conn, cursor, statement, parameters, context, many):
            if threading.current_thread() is not threading.main_thread():
                sql.append(statement)
        engine = self.m.db.engine
        event.listen(engine, 'before_cursor_execute', observe)
        try:
            if correction:
                service = self.m.app.extensions['dkss']['document_deletion']
                original_replace = service['replace_source']
                def operation(gate):
                    def final_replace(*args, **kwargs):
                        # Validation locks were released by the preview commit.
                        # Exercise the final save after new business rows were flushed.
                        gate()
                        return original_replace(*args, **kwargs)
                    with patch.dict(service, {'replace_source': final_replace}):
                        return client.post(path, data=body).status_code
                status = self.protected_writer(State, ident, operation, periodic=periodic, at_boundary=True)
            else:
                status = self.protected_writer(State, ident, lambda: client.post(path, data=body).status_code, periodic=periodic)
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
        self.assertIn(status, (400, 409))
        self.assertEqual(before, snapshot())
        state_lock = max(i for i, s in enumerate(sql) if 'vehicle_karte_analysis' in s and 'FOR UPDATE' in s)
        proposal_lock = max(i for i, s in enumerate(sql) if 'periodic_inspection_proposal' in s and 'FOR UPDATE' in s)
        self.assertLess(state_lock, proposal_lock)
        # Draft claiming may occur earlier, but source/business deletion must not.
        self.assertFalse(any(s.lstrip().upper().startswith('DELETE ') for s in sql))
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)

    def test_delete_waits_for_analysis_then_proposal_lock_and_preserves_source(self):
        self.document_race(False)

    def test_kind_final_save_waits_for_analysis_then_proposal_lock_without_partial_replacement(self):
        self.document_race(True)

    def test_delete_waits_for_periodic_proposal_and_preserves_source(self):
        self.document_race(False, True)

    def test_kind_final_save_waits_for_periodic_proposal_without_partial_replacement(self):
        self.document_race(True, True)

    def other_periodic_parent(self, original):
        """A same-vehicle record from another source, not owned by the deletion."""
        from uuid import uuid4
        Draft, Record = self.m.VehicleDocumentImportDraft, self.m.VehiclePeriodicInspectionRecord
        fields = {c.key: getattr(original, c.key) for c in Draft.__table__.columns}
        fields.update(id=str(uuid4()), batch_id=str(uuid4()), source_sha256='e' * 64,
                      result_json='{}', source_file=b'synthetic second source')
        draft = Draft(**fields)
        self.m.db.session.add(draft)
        self.m.db.session.flush()
        record = Record(company_code='TEST', vehicle_record_id=self.vehicle.id,
                        inspection_type='other', inspection_date='2026-08-02',
                        source_draft_id=draft.id, source_record_index=0,
                        created_by_username='admin', details_json='{}')
        self.m.db.session.add(record)
        self.m.db.session.commit()
        return record

    def first_insert(self, periodic, parent_id):
        if periodic:
            return self.m.periodic_followups.Proposal, dict(company_code='TEST',
                inspection_record_id=parent_id, input_hash='new-first', run_token='new-first',
                status='completed', result_json=retention.saved('held', 'periodic'),
                updated_at=retention.NOW.isoformat())
        return self.m.VehicleKarteAnalysis, dict(company_code='TEST', vehicle_record_id=parent_id,
            status='completed', result_json=retention.saved('held', 'analysis'))

    def first_insert_precedes_source_mutation(self, periodic, correction):
        draft = self.source()
        other = self.other_periodic_parent(draft)
        if correction:
            self.assertEqual(self.kind_post(draft, 'maintenance').status_code, 303)
            self.worker(invoice=True)
            replacement = self.m.VehicleDocumentImportDraft.query.filter_by(status='preview').one()
            replacement_id = replacement.id
            key = replacement_id + '_0'
            path = '/vehicle/data-import/' + replacement.batch_id + '/confirm'
            body = {'include':key, 'vehicle_' + key:str(self.vehicle.id), 'date_' + key:'2026-08-01',
                    'content_' + key:'故障修理', 'confirm_kind_correction':'yes'}
        else:
            replacement_id = None
            path = f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete'
            token = re.search(r'name="delete_token" value="([^"]+)"', self.client.get(path).get_data(as_text=True)).group(1)
            body = {'delete_token':token, 'confirm_delete':'yes'}
        Model, values = self.first_insert(periodic, other.id if periodic else self.vehicle.id)
        self.assertEqual(Model.query.count(), 0)
        engine, client = self.m.db.engine, self.auth_client()
        def snapshot():
            with engine.connect() as connection:
                result = {t.name:[dict(r) for r in connection.execute(t.select().order_by(*t.primary_key.columns)).mappings()]
                          for t in self.m.db.metadata.sorted_tables}
            if replacement_id:
                for row in result['vehicle_document_import_draft']:
                    if row['id'] == replacement_id:
                        row.pop('preview_json')
            return result
        before = snapshot()
        self.m.db.session.remove()
        ready, proceed = threading.Event(), threading.Event()
        service = self.m.app.extensions['dkss']['document_deletion']
        original_replace = service['replace_source']
        def boundary(*args, **kwargs):
            # Final correction already flushed new business rows/FK key-share.
            ready.set()
            if not proceed.wait(10):
                raise AssertionError('First-insert holder was not released')
            return original_replace(*args, **kwargs)
        def run():
            with self.m.app.app_context():
                try:
                    if not correction:
                        ready.set()
                        if not proceed.wait(10):
                            raise AssertionError('First-insert holder was not released')
                    return client.post(path, data=body).status_code
                finally:
                    self.m.db.session.remove()
        with patch.dict(service, {'replace_source':boundary} if correction else {}):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(run)
                try:
                    self.assertTrue(ready.wait(10))
                    with engine.connect() as holder:
                        tx = holder.begin()
                        try:
                            # FK parent KEY SHARE remains held until this commit.
                            inserted = holder.execute(Model.__table__.insert().values(**values).returning(Model.id)).scalar_one()
                            expected = dict(holder.execute(Model.__table__.select().where(Model.id == inserted)).mappings().one())
                            proceed.set()
                            status = future.result(timeout=8)  # Cannot wait for holder commit.
                            self.assertIn(status, (400, 409))
                            self.assertEqual(before, snapshot())
                            tx.commit()
                        finally:
                            if tx.is_active:
                                tx.rollback()
                finally:
                    proceed.set()
        self.assertEqual(expected, self.rows(Model, inserted))
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)

    def test_first_analysis_insert_makes_delete_refuse_without_wait_or_mutation(self):
        self.first_insert_precedes_source_mutation(False, False)

    def test_first_other_record_proposal_insert_makes_delete_refuse_without_mutation(self):
        self.first_insert_precedes_source_mutation(True, False)

    def test_first_analysis_insert_rolls_back_final_correction_after_business_flush(self):
        self.first_insert_precedes_source_mutation(False, True)

    def test_first_other_record_proposal_insert_rolls_back_final_correction(self):
        self.first_insert_precedes_source_mutation(True, True)

    def parent_fence_blocks_later_insert(self, kind):
        draft = self.source()
        other = self.other_periodic_parent(draft)
        if kind == 'record':
            Model = self.m.VehiclePeriodicInspectionRecord
            values = {c.key:getattr(other,c.key) for c in Model.__table__.columns if c.key != 'id'}
            values['source_record_index'] = 1
        else:
            Model, values = self.first_insert(kind == 'proposal', other.id if kind == 'proposal' else self.vehicle.id)
        engine = self.m.db.engine
        plan = self.m.app.extensions['dkss']['document_deletion']['plan'](self.vehicle, draft, lock=True)
        self.assertFalse(plan['problems'], plan['problems'])
        guard_pid = self.m.db.session.scalar(text('SELECT pg_backend_pid()'))
        ready, pid = threading.Event(), []
        def insert():
            with engine.begin() as writer:
                writer.execute(text("SET LOCAL statement_timeout = '12000ms'"))
                pid.append(writer.scalar(text('SELECT pg_backend_pid()')))
                ready.set()
                return writer.execute(Model.__table__.insert().values(**values).returning(Model.id)).scalar_one()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(insert)
            try:
                self.assertTrue(ready.wait(10))
                deadline = time.monotonic() + 8
                with engine.connect() as observer:
                    while guard_pid not in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid':pid[0]}):
                        if future.done():
                            future.result()
                            self.fail('First insert crossed the protected parent window')
                        if time.monotonic() >= deadline:
                            self.fail('Expected FK parent wait was not observed')
                        threading.Event().wait(.01)
            finally:
                # Roll back the plan only, then the formerly blocked insert may commit.
                self.m.db.session.rollback()
            inserted = future.result(timeout=12)
        self.assertIsNotNone(self.m.db.session.get(Model, inserted))
        self.assertEqual(self.m.db.session.get(type(draft), draft.id).status, 'completed')

    def test_vehicle_parent_fence_blocks_later_first_analysis_insert(self):
        self.parent_fence_blocks_later_insert('analysis')

    def test_all_periodic_parent_fence_blocks_other_record_first_proposal_insert(self):
        self.parent_fence_blocks_later_insert('proposal')

    def test_vehicle_parent_fence_blocks_new_periodic_parent_insert(self):
        self.parent_fence_blocks_later_insert('record')
