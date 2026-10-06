from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import is_http_url

# Canonical status values used across forms, badges and filters.
JOB_STATUSES = [
    "Wishlist",
    "Applied",
    "Interviewing",
    "Offer",
    "Accepted",
    "Rejected",
]


def _utcnow():
    return datetime.now(timezone.utc)


def status_slug(status):
    """Use the same status class names in models and templates."""
    return (status or "").lower().replace(" ", "-")


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

    @classmethod
    def find_by_email(cls, email):
        return cls.query.filter_by(email=email).first()

    @classmethod
    def from_session_id(cls, user_id):
        """Treat malformed session identifiers as anonymous users."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError, OverflowError):
            return None
        if not 0 < user_id <= 2**31 - 1:
            return None
        return db.session.get(cls, user_id)

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
    status = db.Column(
        db.String(64), default="Applied", nullable=False, index=True
    )
    notes = db.Column(db.Text)
    resume_filename = db.Column(db.String(256))
    applied_date = db.Column(db.DateTime, default=_utcnow)
    updated_date = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )

    user = db.relationship("User", back_populates="applications")

    @classmethod
    def for_user(cls, user_id):
        """Start every application query with an explicit ownership scope."""
        return cls.query.filter_by(user_id=user_id)

    @property
    def status_slug(self):
        return status_slug(self.status)

    @property
    def safe_job_url(self):
        return self.job_url if is_http_url(self.job_url) else None

    def __repr__(self):
        return f"<JobApplication {self.job_title} @ {self.company}>"
