"""The reader ledger also survives real PostgreSQL ON DELETE CASCADE."""
import hashlib
import test_q08_driving_generation as generation
from test_q08_postgres_identity import DisposablePostgres


class PostgresDrivingGenerationTests(DisposablePostgres, generation.DrivingGenerationTests):
    def save(self, i=1, **kwargs):
        draft_id = 'fixture-' + str(i)
        if not self.m.VehicleDocumentImportDraft.query.filter_by(id=draft_id).first():
            self.m.db.session.add(self.m.VehicleDocumentImportDraft(id=draft_id,
                batch_id='synthetic-batch', company_code='TEST', created_by_username='admin',
                document_type='driving_report', source_filename='synthetic.pdf', source_file=b'synthetic',
                source_sha256=hashlib.sha256(b'synthetic').hexdigest()))
            self.m.db.session.commit()
        return super().save(i, **kwargs)

    def replacement(self, original):
        old_id, identity = original.id, original.account_identity
        self.m.db.session.delete(original)
        self.m.db.session.commit()
        # Explicit reuse models an ID-preserving restore/import. Normal sequences
        # need not reuse an ID; the UUID boundary must hold even if one is reused.
        replacement = self.m.User(id=old_id, company_code='TEST', username='reused', role='user',
            password='unused', last_name='旧利用者', password_changed_at='stamp')
        self.m.db.session.add(replacement)
        self.m.db.session.commit()
        self.assertEqual(replacement.id, old_id)
        self.assertNotEqual(replacement.account_identity, identity)
        self.login('reused')
        return replacement
