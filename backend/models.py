"""Database models for the 'mailer' module.

Lives in dedicated schema 'mailer' (configured via module.json).
"""
from datetime import datetime
from app import db


class DemoItem(db.Model):
    """Replace this with your real models."""
    __tablename__ = "demo_item"
    # Schema is set by DATABASE_URL search_path — no need to repeat here.

    id         = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, nullable=False, index=True)
    title      = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
