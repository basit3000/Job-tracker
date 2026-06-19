from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.forms import RegistrationForm, LoginForm
from app.models import User

auth = Blueprint("auth", __name__)
main = Blueprint("main", __name__)


def _is_safe_url(target):
    """Only allow redirects to paths on this host to avoid open-redirects."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/")


@main.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("jobs.dashboard"))
    return render_template("home.html")


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("jobs.dashboard"))

    form = RegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return render_template("register.html", form=form)

        user = User(email=email)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html", form=form)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("jobs.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash("Welcome back!", "success")
            next_page = request.args.get("next")
            if _is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for("jobs.dashboard"))
        flash("Invalid email or password.", "danger")

    return render_template("login.html", form=form)


@auth.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
