"""Authenticated community views, separate from private tracker routes."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.community import (
    PROFILE_FIELDS,
    SharedJob,
    can_view_profile,
    change_friendship,
    comparison_rows,
    discover_profiles,
    friend_lists,
    relationship,
    request_friendship,
    save_profile,
    shared_jobs,
    shortlist_shared_job,
)
from app.contracts import ServiceError
from app.extensions import limiter
from app.forms import ProfileForm
from app.gamification import application_stats
from app.models import JobApplication, User

community = Blueprint("community", __name__, url_prefix="/community")
METRICS = {
    "week": "Last 7 days",
    "today": "Today",
    "total": "Total applications",
    "best_day": "Best day",
    "streak": "Current streak",
}


def _profile(handle):
    return User.query.filter_by(handle=handle.lower()).first_or_404()


@community.route("")
@login_required
def index():
    lists = friend_lists(current_user.id)
    metric = request.args.get("metric", "week")
    if metric not in METRICS:
        metric = "week"
    search = request.args.get("q", "").strip()[:80]
    directory = discover_profiles(current_user.id, search).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=12,
        error_out=False,
    )
    return render_template(
        "community/index.html",
        **lists,
        directory=directory,
        search=search,
        metric=metric,
        metrics=METRICS,
        comparison=comparison_rows(current_user, lists["friends"], metric),
    )


@community.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = ProfileForm(obj=current_user)
    status = 200
    if form.validate_on_submit():
        try:
            save_profile(
                current_user,
                {name: form[name].data for name in PROFILE_FIELDS},
            )
        except ServiceError as error:
            form.handle.errors.append(str(error))
            status = error.status
        else:
            flash(
                "Profile saved. Sharing preferences take effect immediately.",
                "success",
            )
            return redirect(
                url_for("community.profile", handle=current_user.handle)
            )
    elif request.method == "POST":
        status = 422
    return render_template("community/settings.html", form=form), status


@community.route("/u/<handle>")
@login_required
def profile(handle):
    person = _profile(handle)
    allowed = can_view_profile(current_user.id, person)
    pagination = None
    if allowed and person.share_jobs:
        pagination = (
            shared_jobs(current_user.id, person)
            .order_by(
                JobApplication.applied_on.desc(),
                JobApplication.id.desc(),
            )
            .paginate(
                page=max(1, request.args.get("page", 1, type=int)),
                per_page=20,
                error_out=False,
            )
        )
        pagination.items = [SharedJob(*row) for row in pagination.items]
    return render_template(
        "community/profile.html",
        person=person,
        allowed=allowed,
        link=relationship(current_user.id, person.id),
        pagination=pagination,
        progress=application_stats([person.id])[person.id]
        if allowed
        else None,
    )


@community.route("/u/<handle>/request", methods=["POST"])
@login_required
@limiter.limit("20 per minute; 100 per hour")
def add_friend(handle):
    person = _profile(handle)
    request_friendship(current_user, person)
    flash(
        "Friend request sent. Sharing access starts after they accept.",
        "success",
    )
    return redirect(url_for("community.profile", handle=person.handle))


@community.route("/friendships/<int:friendship_id>/<action>", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def manage_friendship(friendship_id, action):
    change_friendship(current_user.id, friendship_id, action)
    messages = {
        "accept": "Friend request accepted.",
        "decline": "Friend request declined.",
        "cancel": "Friend request cancelled.",
        "remove": "Friend removed. Private profile access has ended.",
    }
    flash(messages[action], "success")
    return redirect(url_for("community.index"))


@community.route("/u/<handle>/jobs/<uuid:public_id>/save", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def save_shared_job(handle, public_id):
    job, created = shortlist_shared_job(
        current_user, _profile(handle), str(public_id)
    )
    flash(
        "Job saved to your shortlist."
        if created
        else "This job is already in your tracker.",
        "success",
    )
    return redirect(url_for("jobs.job_detail", job_id=job.id))
