from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

from . import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    jobs = db.relationship('JobApplication', backref='owner', lazy=True)
    applications = db.relationship('JobApplication', back_populates='user', cascade="all, delete-orphan")
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
class JobApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(128), nullable=False)
    contact_person = db.Column(db.String(128))
    status = db.Column(db.String(64), default='Applied')  # e.g. Applied, Interview, Offer, Rejected
    notes = db.Column(db.Text)
    resume_filename = db.Column(db.String(256))
    applied_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    user = db.relationship('User', back_populates='applications')