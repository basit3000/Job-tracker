"""HTTP views for job applications."""

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

from app.contracts import ServiceError, form_version
from app.forms import JobApplicationForm
from app.gamification import application_stats
from app.models import JOB_STATUSES, JobApplication
from app.services import (
    DEFAULT_SORT,
    JOB_FIELDS,
    SORT_OPTIONS,
    application_filter_choices,
    application_query,
    dashboard_summary,
    delete_application,
    save_application,
)
from app.uploads import download_resume as resume_response

jobs = Blueprint("jobs", __name__)


def _get_job_or_404(job_id):
    return (
        JobApplication.for_user(current_user.id)
        .filter_by(id=job_id)
        .first_or_404()
    )


def _job_form_response(job, *, title, success_message):
    form = JobApplicationForm(obj=job)
    if form.validate_on_submit():
        data = {name: form[name].data for name in JOB_FIELDS}
        try:
            version = (
                form_version(request.form.get("version"))
                if job.id is not None
                else None
            )
            save_application(
                job, data, resume=form.resume.data, version=version
            )
        except ServiceError as error:
            flash(str(error), "danger")
            return render_template(
                "jobs/form.html",
                form=form,
                title=title,
                job=job,
                conflict=error.status == 409,
            ), error.status
        flash(success_message, "success")
        return redirect(url_for("jobs.job_detail", job_id=job.id))
    return render_template("jobs/form.html", form=form, title=title, job=job)


@jobs.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "jobs/dashboard.html",
        **dashboard_summary(current_user.id),
        progress=application_stats([current_user.id])[current_user.id],
    )


@jobs.route("/jobs")
@login_required
def job_list():
    search = request.args.get("q", "", type=str).strip()
    status_filter = request.args.get("status", "", type=str).strip()
    sort = request.args.get("sort", DEFAULT_SORT, type=str)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    filters = {
        name: request.args.get(name, "", type=str).strip()
        for name in ("company", "board", "due")
    }
    pagination = application_query(
        current_user.id,
        search=search,
        status=status_filter,
        sort=sort,
        **filters,
    ).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=25,
        error_out=False,
    )
    return render_template(
        "jobs/list.html",
        applications=pagination.items,
        pagination=pagination,
        filters=filters,
        **application_filter_choices(current_user.id),
        statuses=JOB_STATUSES,
        sort_options=SORT_OPTIONS,
        current_search=search,
        current_status=status_filter,
        current_sort=sort,
    )


@jobs.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id):
    return render_template("jobs/detail.html", job=_get_job_or_404(job_id))


@jobs.route("/jobs/add", methods=["GET", "POST"])
@login_required
def add_job():
    return _job_form_response(
        JobApplication(user_id=current_user.id),
        title="Add Job Application",
        success_message="Job application added.",
    )


@jobs.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    return _job_form_response(
        _get_job_or_404(job_id),
        title="Edit Job Application",
        success_message="Job application updated.",
    )


@jobs.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job(job_id):
    job = _get_job_or_404(job_id)
    delete_application(job, version=form_version(request.form.get("version")))
    flash("Job application deleted.", "success")
    return redirect(url_for("jobs.job_list"))


@jobs.route("/board")
@login_required
def status_board():
    status = request.args.get("status", "shortlisted")
    if status not in JOB_STATUSES:
        abort(404)
    pagination = application_query(current_user.id, status=status).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=25,
        error_out=False,
    )
    return render_template(
        "jobs/board.html",
        statuses=JOB_STATUSES,
        selected=status,
        pagination=pagination,
        columns={
            value: application_query(current_user.id, status=value)
            .limit(10)
            .all()
            for value in JOB_STATUSES
        },
        **dashboard_summary(current_user.id),
    )


@jobs.route("/follow-ups")
@login_required
def follow_ups():
    due = request.args.get("due", "overdue")
    if due not in {"due", "overdue", "today", "upcoming"}:
        abort(404)
    pagination = (
        application_query(current_user.id, due=due, sort="oldest")
        .order_by(None)
        .order_by(JobApplication.follow_up_on, JobApplication.id)
        .paginate(
            page=max(1, request.args.get("page", 1, type=int)),
            per_page=25,
            error_out=False,
        )
    )
    return render_template(
        "jobs/follow-ups.html", pagination=pagination, due=due
    )


@jobs.route("/jobs/<int:job_id>/resume")
@login_required
def download_resume(job_id):
    job = _get_job_or_404(job_id)
    return resume_response(job.resume_filename)
