from datetime import datetime, timezone
from uuid import uuid4

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import is_http_url

# Canonical status values used across forms, badges and filters.
JOB_STATUSES = [
    "shortlisted",
    "applied",
    "interviewing",
    "offer",
    "accepted",
    "rejected",
    "closed",
    "skipped",
]
STATUS_LABELS = {status: status.title() for status in JOB_STATUSES}
TERMINAL_STATUSES = {"accepted", "rejected", "closed", "skipped"}


def _utcnow():
    return datetime.now(timezone.utc)


def public_id():
    return str(uuid4())


def status_slug(status):
    """Use the same status class names in models and templates."""
    return (status or "").lower().replace(" ", "-")


class User(UserMixin, db.Model):
    __table_args__ = (
        db.CheckConstraint(
            "password_hash IS NOT NULL OR google_subject IS NOT NULL",
            name="ck_user_login_method",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(512))
    google_subject = db.Column(db.String(255), unique=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    feed_sequence = db.Column(
        db.BigInteger, nullable=False, default=0, server_default="0"
    )

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
        return bool(self.password_hash) and check_password_hash(
            self.password_hash, password
        )

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


class ImportBatch(db.Model):
    """Short-lived private previews and replay-safe import receipts."""

    id = db.Column(db.String(36), primary_key=True, default=public_id)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at = db.Column(
        db.DateTime(timezone=True), nullable=False, index=True
    )
    payload = db.Column(db.JSON)
    options = db.Column(db.JSON)
    result = db.Column(db.JSON)
    connection_id = db.Column(
        db.String(36), db.ForeignKey("source_connection.id"), index=True
    )
    connection_version = db.Column(db.Integer)


class SourceConnection(db.Model):
    """A user's selected external source, encrypted credential and mapping."""

    __table_args__ = (
        db.CheckConstraint("version >= 1", name="ck_source_version"),
        db.CheckConstraint(
            "provider IN ('google_public','google_private','notion')",
            name="ck_source_provider",
        ),
        db.CheckConstraint(
            "interval_minutes IN (0,15,60)", name="ck_source_interval"
        ),
    )
    id = db.Column(db.String(36), primary_key=True, default=public_id)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
    name = db.Column(db.String(80), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.JSON, nullable=False)
    credential_ciphertext = db.Column(db.Text)
    options = db.Column(db.JSON)
    columns = db.Column(db.JSON)
    version = db.Column(
        db.Integer, nullable=False, default=1, server_default="1"
    )
    active = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    interval_minutes = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_synced_at = db.Column(db.DateTime(timezone=True))
    next_sync_at = db.Column(db.DateTime(timezone=True), index=True)
    last_result = db.Column(db.JSON)
    last_error = db.Column(db.String(256))


class SourceRecord(db.Model):
    """Stable external identity and last accepted field values for merging."""

    __table_args__ = (
        db.UniqueConstraint(
            "connection_id", "source_key", name="uq_source_record"
        ),
        db.UniqueConstraint(
            "connection_id", "application_id", name="uq_source_application"
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    connection_id = db.Column(
        db.String(36),
        db.ForeignKey("source_connection.id"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    source_key = db.Column(db.String(64), nullable=False)
    application_id = db.Column(
        db.Integer, db.ForeignKey("job_application.id"), nullable=False
    )
    baseline = db.Column(db.JSON, nullable=False)


class JobApplication(db.Model):
    __table_args__ = (
        db.CheckConstraint("version >= 1", name="ck_job_version"),
        db.CheckConstraint(
            "status IN ('shortlisted','applied','interviewing','offer',"
            "'accepted','rejected','closed','skipped')",
            name="ck_job_status",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, unique=True, default=public_id
    )
    job_title = db.Column(db.String(128), nullable=False)
    company = db.Column(db.String(128), nullable=False)
    location = db.Column(db.String(128))
    salary = db.Column(db.String(64))
    job_url = db.Column(db.String(512))
    contact_person = db.Column(db.String(128))
    status = db.Column(
        db.String(64), default="shortlisted", nullable=False, index=True
    )
    notes = db.Column(db.Text)
    resume_filename = db.Column(db.String(256))
    applied_date = db.Column(db.DateTime, default=_utcnow)
    updated_date = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    applied_on = db.Column(db.Date)
    follow_up_on = db.Column(db.Date, index=True)
    board = db.Column(db.String(128))
    contact_email = db.Column(db.String(254))
    contact_phone = db.Column(db.String(80))
    posted_at = db.Column(db.DateTime(timezone=True))
    posted_at_approximate = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    applicants = db.Column(db.JSON)
    version = db.Column(
        db.Integer, nullable=False, default=1, server_default="1"
    )
    deleted_at = db.Column(db.DateTime(timezone=True))
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )

    user = db.relationship("User", back_populates="applications")
    history = db.relationship(
        "StatusEvent",
        order_by="StatusEvent.id",
        back_populates="application",
        lazy="selectin",
    )
    mappings = db.relationship("ApplicationMapping", lazy="selectin")
    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }

    @classmethod
    def for_user(cls, user_id, *, include_deleted=False):
        """Start every application query with an explicit ownership scope."""
        query = cls.query.filter_by(user_id=user_id)
        return (
            query
            if include_deleted
            else query.filter(cls.deleted_at.is_(None))
        )

    @property
    def status_slug(self):
        return status_slug(self.status)

    @property
    def safe_job_url(self):
        return self.job_url if is_http_url(self.job_url) else None

    @property
    def safe_observation_url(self):
        value = (
            self.applicants.get("url")
            if isinstance(self.applicants, dict)
            else None
        )
        return value if is_http_url(value) else None

    def __repr__(self):
        return f"<JobApplication {self.job_title} @ {self.company}>"


class StatusEvent(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "installation_id",
            "source_event_id",
            name="uq_source_status_event",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, unique=True, default=public_id
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey("job_application.id"),
        nullable=False,
        index=True,
    )
    from_status = db.Column(db.String(64))
    status = db.Column(db.String(64), nullable=False)
    source = db.Column(db.String(16), nullable=False)
    installation_id = db.Column(db.String(128))
    source_event_id = db.Column(db.String(128))
    occurred_at = db.Column(db.DateTime(timezone=True))
    recorded_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    application = db.relationship("JobApplication", back_populates="history")


class ApplicationMapping(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "installation_id",
            "local_record_id",
            name="uq_local_application",
        ),
        db.UniqueConstraint(
            "application_id",
            "installation_id",
            name="uq_application_installation",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    application_id = db.Column(
        db.Integer, db.ForeignKey("job_application.id"), nullable=False
    )
    installation_id = db.Column(db.String(128), nullable=False)
    local_record_id = db.Column(db.String(256), nullable=False)


class ChangeEntry(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "sequence", name="uq_account_change_sequence"
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    sequence = db.Column(db.BigInteger, nullable=False)
    application_id = db.Column(db.String(36), nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)
    source = db.Column(db.String(16), nullable=False)
    mutation_id = db.Column(db.String(128))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Device(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=public_id)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
    installation_id = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    optional_fields = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at = db.Column(db.DateTime(timezone=True))
    revoked_at = db.Column(db.DateTime(timezone=True))
    last_error_code = db.Column(db.String(40))
    last_error_at = db.Column(db.DateTime(timezone=True))


class PairingRequest(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=public_id)
    secret_hash = db.Column(db.String(64), nullable=False)
    code_hash = db.Column(db.String(64), nullable=False, unique=True)
    installation_id = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    optional_fields = db.Column(db.JSON)
    consumed_at = db.Column(db.DateTime(timezone=True))


class MutationReceipt(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "device_id", "mutation_id", name="uq_device_mutation"
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(
        db.String(36), db.ForeignKey("device.id"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    mutation_id = db.Column(db.String(128), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    response = db.Column(db.JSON, nullable=False)
