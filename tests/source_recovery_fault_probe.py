"""Fault injection on current checkout production module with disposable SQLite only.
Four exact model classes are extracted from the checkout model file; application
startup, workers, OCR, credentials, HTTP and live databases are not imported.
"""
import ast
import hashlib
import importlib.util
from pathlib import Path
import socket
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.orm import synonym

BASE = Path(__file__).resolve().parents[1]
# Fail closed on any accidental network use in this dedicated test process.
def no_network(*a, **kw):
    raise AssertionError('NETWORK_FORBIDDEN')
socket.create_connection = no_network
socket.socket.connect = no_network
socket.socket.connect_ex = no_network

pkg = types.ModuleType('source_probe')
pkg.__path__ = [str(BASE / 'dkss_app')]
sys.modules['source_probe'] = pkg
ext = types.ModuleType('source_probe.extensions')
ext.db = db = SQLAlchemy()
sys.modules[ext.__name__] = ext
models = types.ModuleType('source_probe.models')
models.__dict__.update(db=db, datetime=datetime, ZoneInfo=ZoneInfo, synonym=synonym)
raw = (BASE/'dkss_app/models.py').read_text(encoding='utf-8')
names = {'VehicleDocumentSource','VehicleDocumentImportDraft','DocumentQueueSchedule','DomainSchemaRevision'}
parts = [ast.get_source_segment(raw,n) for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name in names]
assert len(parts) == 4
sys.modules[models.__name__] = models
exec(compile('\n\n'.join(parts), str(BASE/'dkss_app/models.py'),'exec'), models.__dict__)
spec = importlib.util.spec_from_file_location('source_probe.document_sources',BASE/'dkss_app/document_sources.py')
source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source
spec.loader.exec_module(source)
Draft, Source = models.VehicleDocumentImportDraft, models.VehicleDocumentSource

class RecoveryFaults(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        self.ctx=self.app.app_context(); self.ctx.push()
        self.app.extensions['dkss']={'document_sources_ready':True}
        db.create_all()
    def tearDown(self):
        db.session.remove(); db.drop_all(); db.engine.dispose(); self.ctx.pop()
    def seed(self, ident, company='FICTIONAL_A', data=None, stored=None, missing=False):
        data=data or ('SYNTHETIC-ORIGINAL-'+ident).encode()
        digest=hashlib.sha256(data).hexdigest()
        if not missing and db.session.get(Source,(company,digest)) is None:
            db.session.add(Source(company_code=company,sha256=digest,content=data if stored is None else stored))
        db.session.add(Draft(id=ident,batch_id=ident,company_code=company,created_by_username='synthetic',document_type='invoice',source_filename='synthetic.txt',_source_file=b'',source_sha256=digest,status='completed',preview_json='{"amount":100}',result_json='{"record_id":1}'))
        db.session.commit()
        return data,digest
    def snapshot(self):
        return [(r.id,r.company_code,r.source_sha256,r._source_file,r.status,r.preview_json,r.result_json) for r in Draft.query.order_by(Draft.id)]
    def test_corrupt_first_source_rejects_without_row_mutation(self):
        self.seed('001',stored=b'SYNTHETIC-CORRUPTION'); before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'): source.restore_inline_sources()
        self.assertEqual(before,self.snapshot()); self.assertEqual(Source.query.one().content,b'SYNTHETIC-CORRUPTION')
    def test_missing_first_source_rejects_without_row_mutation(self):
        self.seed('001',missing=True); before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'): source.restore_inline_sources()
        self.assertEqual(before,self.snapshot()); self.assertEqual(Source.query.count(),0)
    def test_later_corruption_preserves_committed_prefix_then_resumes(self):
        first,_=self.seed('001'); second,digest=self.seed('002',stored=b'SYNTHETIC-CORRUPTION'); third,_=self.seed('003')
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'): source.restore_inline_sources()
        self.assertEqual(db.session.get(Draft,'001')._source_file,first)
        self.assertEqual(db.session.get(Draft,'002')._source_file,b'')
        self.assertEqual(db.session.get(Draft,'003')._source_file,b'')
        # Repair only the injected synthetic fault; this is NOT a production repair instruction.
        db.session.get(Source,('FICTIONAL_A',digest)).content=second; db.session.commit(); db.session.remove()
        self.assertEqual(source.restore_inline_sources(),2)
        self.assertEqual(source.restore_inline_sources(),0)
        after=self.snapshot()
        self.assertEqual([r[:3]+r[4:] for r in before],[r[:3]+r[4:] for r in after])
        self.assertEqual([r[3] for r in after],[first,second,third])
    def test_other_company_source_cannot_rescue_missing_original(self):
        data,digest=self.seed('001',missing=True)
        db.session.add(Source(company_code='FICTIONAL_B',sha256=digest,content=data)); db.session.commit()
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'): source.restore_inline_sources()
        self.assertEqual(before,self.snapshot()); self.assertEqual(Source.query.one().company_code,'FICTIONAL_B')
    def test_deleted_corrupt_source_does_not_block_remaining_recovery(self):
        self.seed('001',stored=b'SYNTHETIC-CORRUPTION'); db.session.get(Draft,'001').status='deleted'; db.session.commit()
        second,_=self.seed('002')
        self.assertEqual(source.restore_inline_sources(),1)
        self.assertEqual(db.session.get(Draft,'001')._source_file,b'')
        self.assertEqual(db.session.get(Draft,'002')._source_file,second)
    def test_commit_interruption_does_not_falsely_restore_current_row(self):
        original,_=self.seed('001'); before=self.snapshot()
        def interrupted(session): raise RuntimeError('SYNTHETIC_INTERRUPTION')
        event.listen(db.session.session_factory.class_,'before_commit',interrupted)
        try:
            with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_INTERRUPTION'): source.restore_inline_sources()
        finally:
            event.remove(db.session.session_factory.class_,'before_commit',interrupted)
            db.session.remove()
        self.assertEqual(before,self.snapshot())
        self.assertEqual(source.restore_inline_sources(),1)
        self.assertEqual(db.session.get(Draft,'001')._source_file,original)

if __name__=='__main__': unittest.main(verbosity=2)
