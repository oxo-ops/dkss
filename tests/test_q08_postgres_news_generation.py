"""Run the same News acceptance against an explicitly isolated PG schema."""
from pathlib import Path
import tempfile

import test_q08_news_generation as acceptance
from test_q08_postgres_identity import DisposablePostgres


class PostgresNewsGenerationTests(DisposablePostgres, acceptance.NewsGenerationTests):
    @classmethod
    def setUpClass(cls):
        DisposablePostgres.setUpClass.__func__(cls)
        from dkss_app import models
        cls.app, cls.db, cls.models = cls.m.app, cls.m.db, models
        cls.temp = tempfile.TemporaryDirectory(prefix='dkss-q08-news-pg-')
        cls.files = Path(cls.temp.name) / 'static'
        cls.app.static_folder = str(cls.files)

    @classmethod
    def tearDownClass(cls):
        try:
            DisposablePostgres.tearDownClass.__func__(cls)
        finally:
            cls.temp.cleanup()
