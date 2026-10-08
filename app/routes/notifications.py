"""Private reminder preferences and signed email unsubscribe links."""

from zoneinfo import available_timezones

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.database import database_transaction
from app.extensions import db, limiter
from app.forms import NotificationForm
from app.models import (
    Notification,
    NotificationPreference,
    ReminderDelivery,
    _utcnow,
)
from app.notification_center import (
    CATEGORIES,
    CHANNEL_FIELDS,
    inbox_query,
    notification_url,
    refresh_scheduled_notifications,
    unread_count,
)
from app.notifications import (
    disable_reminders,
    mail_ready,
    preference_from_token,
    save_preferences,
)

notifications = Blueprint(
    "notifications", __name__, url_prefix="/notifications"
)


@notifications.get("")
@login_required
def inbox():
    refresh_scheduled_notifications(current_user.id)
    unread = request.args.get("filter") == "unread"
    query = inbox_query(current_user.id)
    if unread:
        query = query.filter_by(read_at=None)
    pagination = query.order_by(
        Notification.created_at.desc(), Notification.id.desc()
    ).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=20,
        error_out=False,
    )
    return render_template(
        "notifications/inbox.html",
        pagination=pagination,
        unread=unread,
        categories=CATEGORIES,
    )


@notifications.get("/count")
@login_required
def count():
    refresh_scheduled_notifications(current_user.id)
    response = jsonify(unread=unread_count(current_user.id))
    response.headers["Cache-Control"] = "no-store"
    return response


@notifications.post("/read-all")
@login_required
def read_all():
    with database_transaction():
        inbox_query(current_user.id).filter_by(read_at=None).update(
            {"read_at": _utcnow()}
        )
    flash("All notifications marked as read.", "success")
    return redirect(url_for("notifications.inbox"))


@notifications.post("/<notification_id>/<action>")
@login_required
def update(notification_id, action):
    if action not in {"read", "unread", "dismiss", "open"}:
        abort(404)
    notification = (
        inbox_query(current_user.id)
        .filter_by(id=notification_id)
        .first_or_404()
    )
    with database_transaction():
        if action == "dismiss":
            notification.dismissed_at = _utcnow()
            if notification.email_status == "pending":
                notification.email_status = "skipped"
        else:
            notification.read_at = None if action == "unread" else _utcnow()
    if action == "open":
        return redirect(notification_url(notification))
    flash(
        "Notification dismissed."
        if action == "dismiss"
        else f"Notification marked as {action}.",
        "success",
    )
    return redirect(
        url_for(
            "notifications.inbox",
            filter="unread"
            if request.form.get("filter") == "unread"
            else "all",
        )
    )


@notifications.route("/settings", methods=["GET", "POST"])
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
            **{name: getattr(form, name).data for name in CHANNEL_FIELDS},
        )
        flash("Notification preferences saved.", "success")
        return redirect(url_for("notifications.settings"))
    history = (
        ReminderDelivery.query.filter_by(user_id=current_user.id)
        .order_by(ReminderDelivery.created_at.desc())
        .limit(10)
        .all()
    )
    email_history = (
        Notification.query.filter(
            Notification.user_id == current_user.id,
            Notification.email_status != "disabled",
        )
        .order_by(Notification.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "notifications/settings.html",
        form=form,
        ready=mail_ready(),
        history=history,
        email_history=email_history,
    ), 422 if request.method == "POST" else 200


@notifications.route("/unsubscribe/<token>", methods=["GET", "POST"])
@limiter.limit("30 per minute")
def unsubscribe(token):
    preference = preference_from_token(token)
    if preference is None:
        abort(404)
    done = not any(
        (
            preference.email_enabled,
            preference.social_email,
            preference.followups_email,
            preference.sources_email,
        )
    )
    if request.method == "POST":
        disable_reminders(preference)
        done = True
    return render_template("notifications/unsubscribe.html", done=done)
