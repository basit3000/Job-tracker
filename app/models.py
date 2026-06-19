from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


# Canonical status values used across forms, badges and filters.
JOB_STATUSES = ["Wishlist", "Applied", "Interviewing", "Offer", "Accepted", "Rejected"]


def _utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    applications = db.relationship(
        "JobApplication",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="JobApplication.applied_date.desc()",
        lazy=True,
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"


class JobApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_title = db.Column(db.String(128), nullable=False)
    company = db.Column(db.String(128), nullable=False)
    location = db.Column(db.String(128))
    salary = db.Column(db.String(64))
    job_url = db.Column(db.String(512))
    contact_person = db.Column(db.String(128))
    status = db.Column(db.String(64), default="Applied", nullable=False, index=True)
    notes = db.Column(db.Text)
    resume_filename = db.Column(db.String(256))
    applied_date = db.Column(db.DateTime, default=_utcnow)
    updated_date = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    user = db.relationship("User", back_populates="applications")

    @property
    def status_slug(self):
        return (self.status or "").lower().replace(" ", "-")

    def __repr__(self):
        return f"<JobApplication {self.job_title} @ {self.company}>"
