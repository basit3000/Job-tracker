from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    TextAreaField,
    SelectField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    URL,
)

from app.models import JOB_STATUSES


class RegistrationForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, message="Password must be at least 8 characters.")],
    )
    confirm = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class JobApplicationForm(FlaskForm):
    job_title = StringField("Job Title", validators=[DataRequired(), Length(max=128)])
    company = StringField("Company", validators=[DataRequired(), Length(max=128)])
    location = StringField("Location", validators=[Optional(), Length(max=128)])
    salary = StringField("Salary", validators=[Optional(), Length(max=64)])
    job_url = StringField(
        "Job Posting URL",
        validators=[Optional(), URL(message="Enter a valid URL."), Length(max=512)],
    )
    contact_person = StringField("Contact Person", validators=[Optional(), Length(max=128)])
    status = SelectField("Status", choices=[(s, s) for s in JOB_STATUSES], validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional()])
    resume = FileField(
        "Resume",
        validators=[FileAllowed(["pdf", "doc", "docx", "rtf", "txt"], "Documents only (pdf, doc, docx, rtf, txt).")],
    )
    submit = SubmitField("Save")
