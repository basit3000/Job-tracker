from flask import current_app
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    URL,
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    ValidationError,
)

from app.models import JOB_STATUSES, JobApplication, User
from app.utils import is_http_url

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 1024


def strip_text(value):
    return value.strip() if value else value


def normalize_email(value):
    return value.strip().lower() if value else value


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
        choices=[(s, s) for s in JOB_STATUSES],
        validators=[DataRequired()],
    )
    notes = TextAreaField("Notes", validators=[Optional()])
    resume = FileField(
        "Resume",
        validators=[allowed_resume],
    )
    submit = SubmitField("Save")
