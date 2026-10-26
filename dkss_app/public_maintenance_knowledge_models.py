"""Model registration, independently cached for each SQLAlchemy extension."""
from datetime import datetime
from zoneinfo import ZoneInfo

def get_models(db):
    registry = getattr(db, "_dkss_model_registry", None)
    if registry is None:
        registry = db._dkss_model_registry = {}
    key = 'public_maintenance_knowledge.py'
    if key in registry:
        return registry[key]
    class PublicKnowledgeCatalog(db.Model):
        __tablename__ = "public_knowledge_catalog"
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, unique=True)
        next_check = db.Column(db.DateTime, nullable=False)
        last_checked = db.Column(db.DateTime)
        lease_token = db.Column(db.String(36))
        lease_until = db.Column(db.DateTime)
        last_error = db.Column(db.String(200), default="")
        requested_scope_hash = db.Column(db.String(64))

    class PublicKnowledgeFile(db.Model):
        __tablename__ = "public_knowledge_file"
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        url = db.Column(db.String(500), nullable=False)
        title = db.Column(db.String(240), nullable=False)
        priority = db.Column(db.Integer, nullable=False, default=0)
        available = db.Column(db.Boolean, nullable=False, default=True)
        next_check = db.Column(db.DateTime, nullable=False)
        last_checked = db.Column(db.DateTime)
        checksum = db.Column(db.String(64), default="")
        document_id = db.Column(db.String(36))
        last_import_month = db.Column(db.String(7))
        status = db.Column(db.String(30), nullable=False, default="pending")
        last_error = db.Column(db.String(200), default="")
        __table_args__ = (db.UniqueConstraint("company_code", "url"),)

    registry[key] = (PublicKnowledgeCatalog, PublicKnowledgeFile,)
    return registry[key]
