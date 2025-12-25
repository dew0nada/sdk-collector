from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Client(db.Model):
    __tablename__ = 'clients'
    
    id = db.Column(db.Integer, primary_key=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.BigInteger, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    
    # From identifiers
    visitor_id = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    
    # From page_info
    page_url = db.Column(db.Text, nullable=False)
    page_title = db.Column(db.Text)
    referrer = db.Column(db.Text)
    
    # Core event data
    event_type = db.Column(db.String(20), nullable=False)  # 'error', 'click', 'page_view'
    sdk_version = db.Column(db.String(20))
    sent_at = db.Column(db.DateTime, nullable=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Raw JSON storage
    raw_data = db.Column(db.JSON, nullable=False)
    
    # Relationships
    client = db.relationship('Client', backref='events')