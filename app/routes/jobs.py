"""HTTP views for job applications."""

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from app.forms import JobApplicationForm
from app.models import JOB_STATUSES, JobApplication
from app.services import (
    DEFAULT_SORT,
    JOB_FIELDS,
    SORT_OPTIONS,
    dashboard_summary,
    delete_application,
    list_applications,
    save_application,
)
from app.uploads import resume_path

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
        save_application(job, data, resume=form.resume.data)
        flash(success_message, "success")
        return redirect(url_for("jobs.job_detail", job_id=job.id))
    return render_template("jobs/form.html", form=form, title=title, job=job)


@jobs.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "jobs/dashboard.html", **dashboard_summary(current_user.id)
    )


@jobs.route("/jobs")
@login_required
def job_list():
    search = request.args.get("q", "", type=str).strip()
    status_filter = request.args.get("status", "", type=str).strip()
    sort = request.args.get("sort", DEFAULT_SORT, type=str)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    return render_template(
        "jobs/list.html",
        applications=list_applications(
            current_user.id, search=search, status=status_filter, sort=sort
        ),
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
    delete_application(_get_job_or_404(job_id))
    flash("Job application deleted.", "success")
    return redirect(url_for("jobs.job_list"))


@jobs.route("/jobs/<int:job_id>/resume")
@login_required
def download_resume(job_id):
    job = _get_job_or_404(job_id)
    if resume_path(job.resume_filename) is None:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        job.resume_filename,
        as_attachment=True,
    )
