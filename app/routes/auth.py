from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.authentication import (
    EmailAlreadyRegisteredError,
    authenticate_user,
    register_user,
)
from app.extensions import limiter
from app.forms import LoginForm, RegistrationForm
from app.security import AUTH_RATE_LIMIT
from app.utils import is_safe_redirect

auth = Blueprint("auth", __name__)
main = Blueprint("main", __name__)


@auth.before_request
def redirect_authenticated_users():
    if (
        request.endpoint in {"auth.login", "auth.register"}
        and current_user.is_authenticated
    ):
        return redirect(url_for("jobs.dashboard"))


@main.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("jobs.dashboard"))
    return render_template("home.html")


@auth.route("/register", methods=["GET", "POST"])
@limiter.limit(AUTH_RATE_LIMIT, methods=["POST"])
def register():
    if not current_app.config["PUBLIC_SIGNUP_ENABLED"]:
        abort(404)
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            register_user(form.email.data, form.password.data)
        except EmailAlreadyRegisteredError as error:
            flash(str(error), "danger")
        else:
            flash("Account created! Please log in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("register.html", form=form)


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit(AUTH_RATE_LIMIT, methods=["POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = authenticate_user(form.email.data, form.password.data)
        if user:
            session.clear()
            login_user(user)
            flash("Welcome back!", "success")
            next_page = request.args.get("next")
            target = (
                next_page
                if is_safe_redirect(next_page)
                else url_for("jobs.dashboard")
            )
            return redirect(target)
        flash("Invalid email or password.", "danger")

    return render_template("login.html", form=form)


@auth.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    # logout_user sets the marker that expires any existing remember cookie.
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
