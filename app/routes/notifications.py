"""Private reminder preferences and signed email unsubscribe links."""

from zoneinfo import available_timezones

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms import NotificationForm
from app.models import NotificationPreference, ReminderDelivery
from app.notifications import (
    disable_reminders,
    mail_ready,
    preference_from_token,
    save_preferences,
)

notifications = Blueprint(
    "notifications", __name__, url_prefix="/notifications"
)


@notifications.route("", methods=["GET", "POST"])
@login_required
def settings():
    preference = db.session.get(NotificationPreference, current_user.id)
    form = NotificationForm(
        obj=preference,
        data={
            "email_enabled": False,
            "timezone_name": "UTC",
            "reminder_hour": 20,
        }
        if preference is None
        else None,
    )
    form.timezone_name.choices = [
        (name, name.replace("_", " "))
        for name in sorted(available_timezones())
    ]
    if form.validate_on_submit():
        save_preferences(
            current_user.id,
            form.email_enabled.data,
            form.timezone_name.data,
            form.reminder_hour.data,
        )
        flash("Notification preferences saved.", "success")
        return redirect(url_for("notifications.settings"))
    history = (
        ReminderDelivery.query.filter_by(user_id=current_user.id)
        .order_by(ReminderDelivery.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "notifications/settings.html",
        form=form,
        ready=mail_ready(),
        history=history,
    ), 422 if request.method == "POST" else 200


@notifications.route("/unsubscribe/<token>", methods=["GET", "POST"])
@limiter.limit("30 per minute")
def unsubscribe(token):
    preference = preference_from_token(token)
    if preference is None:
        abort(404)
    done = not preference.email_enabled
    if request.method == "POST":
        disable_reminders(preference)
        done = True
    return render_template("notifications/unsubscribe.html", done=done)
