"""Only imported when isolated test candidate is enabled."""
from .extensions import db
from sqlalchemy.orm import DeclarativeBase

class CandidateBase(DeclarativeBase):
    pass

class SessionAuthority(CandidateBase):
    __tablename__ = 'session_authority_candidate'
    token_hash = db.Column(db.String(64), primary_key=True)
    account_identity = db.Column(db.String(64), nullable=False, index=True)
    issued_at = db.Column(db.BigInteger, nullable=False)
    idle_until = db.Column(db.BigInteger, nullable=False)
    absolute_until = db.Column(db.BigInteger, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)

