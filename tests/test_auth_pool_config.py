"""Reproduce Flask engine configuration coercion without DB/network access."""
import unittest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool


class PoolConfiguration(unittest.TestCase):
    def test_flask_config_effective_integer_timeout(self):
        for configured, effective in ((0.2, 0), (1, 1)):
            with self.subTest(configured=configured):
                app = Flask(__name__)
                app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://',
                    SQLALCHEMY_ENGINE_OPTIONS=dict(poolclass=QueuePool,
                        pool_size=2, max_overflow=0, pool_timeout=configured))
                # Use a temporary file URL so Flask does not select StaticPool.
                import tempfile
                with tempfile.TemporaryDirectory() as directory:
                    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + directory + '/unused.db'
                    db = SQLAlchemy(app)
                    with app.app_context():
                        self.assertEqual(db.engine.pool.timeout(), effective)
                        db.engine.dispose()

    def test_direct_engine_does_not_apply_configuration_coercion(self):
        engine = create_engine('sqlite://', poolclass=QueuePool,
                               pool_size=2, max_overflow=0, pool_timeout=0.2)
        try:
            self.assertEqual(engine.pool.timeout(), 0.2)
        finally:
            engine.dispose()
