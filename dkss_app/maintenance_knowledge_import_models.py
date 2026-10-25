"""Model registration, independently cached for each SQLAlchemy extension."""
from datetime import datetime
from zoneinfo import ZoneInfo

def get_models(db):
    registry = getattr(db, "_dkss_model_registry", None)
    if registry is None:
        registry = db._dkss_model_registry = {}
    key = 'maintenance_knowledge_import.py'
    if key in registry:
        return registry[key]
    class KnowledgeDocument(db.Model):
        __tablename__ = "maintenance_knowledge_document"
        id = db.Column(db.String(36), primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        checksum = db.Column(db.String(64), nullable=False)
        filename = db.Column(db.String(255), nullable=False)
        original_data = db.deferred(db.Column(db.LargeBinary, nullable=False))
        mimetype = db.Column(db.String(50), nullable=False)
        knowledge_ids_json = db.Column(db.Text, nullable=False)
        extraction_json = db.deferred(db.Column(db.Text, nullable=False))
        created_by = db.Column(db.String(50), nullable=False)
        created_at = db.Column(db.String(30), nullable=False)
        __table_args__ = (db.UniqueConstraint("company_code", "checksum"),)

    class KnowledgeRuleExtraction(db.Model):
        __tablename__ = "maintenance_knowledge_rule_extraction"
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        document_id = db.Column(db.String(36), db.ForeignKey(
            "maintenance_knowledge_document.id"), nullable=False, index=True)
        extraction_version = db.Column(db.Integer, nullable=False, default=1)
        document_checksum = db.Column(db.String(64), nullable=False)
        knowledge_ids_json = db.Column(db.Text, nullable=False)
        extraction_json = db.deferred(db.Column(db.Text, nullable=False))
        created_at = db.Column(db.String(30), nullable=False)
        __table_args__ = (db.UniqueConstraint(
            "company_code", "document_id", "extraction_version",
            name="uq_knowledge_rule_extraction_version"),)

    registry[key] = (KnowledgeDocument, KnowledgeRuleExtraction,)
    return registry[key]
