from flask import current_app
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    BooleanField,
    DateField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    URL,
    AnyOf,
    DataRequired,
    Email,
    EqualTo,
    Length,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)
from wtforms.widgets import HiddenInput

from app.models import JOB_STATUSES, STATUS_LABELS, JobApplication, User
from app.utils import is_http_url

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 1024


def strip_text(value):
    return value.strip() if value else value


def normalize_email(value):
    return value.strip().lower() if value else value


class NotificationForm(FlaskForm):
    email_enabled = BooleanField("Email me when I haven't applied today")
    timezone_name = SelectField("Your time zone", validators=[DataRequired()])
    reminder_hour = SelectField(
        "Remind me at",
        coerce=int,
        choices=[(hour, f"{hour:02d}:00") for hour in range(24)],
        validators=[NumberRange(min=0, max=23)],
    )
    submit = SubmitField("Save notifications")


class ProfileForm(FlaskForm):
    handle = StringField(
        "Username",
        filters=[normalize_email],
        validators=[
            DataRequired(),
            Length(min=3, max=24),
            Regexp(
                r"^[a-z0-9_]+$",
                message="Use lowercase letters, numbers, and underscores.",
            ),
        ],
    )
    display_name = StringField(
        "Display name",
        filters=[strip_text],
        validators=[Optional(), Length(max=60)],
    )
    bio = TextAreaField(
        "About you",
        filters=[strip_text],
        validators=[Optional(), Length(max=280)],
    )
    profile_visibility = SelectField(
        "Profile visibility",
        choices=[
            ("private", "Private - accepted friends only"),
            ("public", "Public - signed-in community members"),
        ],
        validators=[DataRequired()],
    )
    share_jobs = BooleanField("Share my applied jobs on my profile")
    daily_goal = IntegerField(
        "Daily application goal",
        validators=[DataRequired(), NumberRange(min=1, max=100)],
    )
    submit = SubmitField("Save profile")


def http_url(_form, field):
    if not is_http_url(field.data):
        raise ValidationError("Enter a valid HTTP or HTTPS URL.")


def allowed_resume(_form, field):
    extensions = sorted(current_app.config["ALLOWED_UPLOAD_EXTENSIONS"])
    FileAllowed(
        extensions,
        f"Documents only ({', '.join(extensions)}).",
    )(_form, field)


def _job_text_field(label, column, *, required=False, validators=()):
    """Keep text normalization and length checks aligned with the model."""
    return StringField(
        label,
        filters=[strip_text],
        validators=[
            DataRequired() if required else Optional(),
            Length(max=column.type.length),
            *validators,
        ],
    )


class AccountForm(FlaskForm):
    """Shared email normalization and bounded password inputs."""

    email = StringField(
        "Email",
        filters=[normalize_email],
        validators=[
            DataRequired(),
            Length(max=User.email.type.length),
            Email(),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(max=PASSWORD_MAX_LENGTH)],
    )


class RegistrationForm(AccountForm):
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=PASSWORD_MIN_LENGTH, max=PASSWORD_MAX_LENGTH),
        ],
    )
    confirm = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            Length(max=PASSWORD_MAX_LENGTH),
            EqualTo("password", message="Passwords must match."),
        ],
    )
    submit = SubmitField("Create account")


class LoginForm(AccountForm):
    submit = SubmitField("Log in")


class GoogleLoginForm(FlaskForm):
    intent = HiddenField(
        default="signin",
        validators=[
            DataRequired(),
            AnyOf(["signin", "link", "sheets", "sheet_sync"]),
        ],
    )
    next = HiddenField(validators=[Optional(), Length(max=2048)])
    sheet_url = StringField(
        "Google Sheets link", validators=[Optional(), Length(max=2048)]
    )
    cell_range = StringField(
        "Cell range", validators=[Optional(), Length(max=40)]
    )
    connection_id = HiddenField(validators=[Optional(), Length(max=36)])
    password = PasswordField(
        "Current password",
        validators=[Optional(), Length(max=PASSWORD_MAX_LENGTH)],
    )
    submit = SubmitField("Continue with Google")


class JobApplicationForm(FlaskForm):
    job_title = _job_text_field(
        "Job Title",
        JobApplication.job_title,
        required=True,
    )
    company = _job_text_field(
        "Company",
        JobApplication.company,
        required=True,
    )
    location = _job_text_field(
        "Location",
        JobApplication.location,
    )
    salary = _job_text_field(
        "Salary",
        JobApplication.salary,
    )
    job_url = _job_text_field(
        "Job Posting URL",
        JobApplication.job_url,
        validators=[
            URL(message="Enter a valid URL."),
            http_url,
        ],
    )
    contact_person = _job_text_field(
        "Contact Person",
        JobApplication.contact_person,
    )
    status = SelectField(
        "Status",
        choices=[(s, STATUS_LABELS[s]) for s in JOB_STATUSES],
        validators=[DataRequired()],
    )
    board = _job_text_field("Job board / source", JobApplication.board)
    contact_email = _job_text_field(
        "Contact email", JobApplication.contact_email, validators=[Email()]
    )
    contact_phone = _job_text_field(
        "Contact phone", JobApplication.contact_phone
    )
    applied_on = DateField("Application date", validators=[Optional()])
    follow_up_on = DateField("Follow-up date", validators=[Optional()])
    version = IntegerField(
        "Version",
        widget=HiddenInput(),
        validators=[Optional(), NumberRange(min=1)],
    )
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=20000)])
    resume = FileField(
        "Resume",
        validators=[allowed_resume],
    )
    submit = SubmitField("Save")
