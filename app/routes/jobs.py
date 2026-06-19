import os
import uuid

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    current_app,
    send_from_directory,
    abort,
)
from flask_login import login_required, current_user
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from app.extensions import db
from app.forms import JobApplicationForm
from app.models import JobApplication, JOB_STATUSES

jobs = Blueprint("jobs", __name__)

SORT_OPTIONS = {
    "newest": ("Newest first", JobApplication.applied_date.desc()),
    "oldest": ("Oldest first", JobApplication.applied_date.asc()),
    "company": ("Company A–Z", JobApplication.company.asc()),
    "title": ("Job title A–Z", JobApplication.job_title.asc()),
}


def _allowed_file(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]


def _save_resume(file_storage):
    """Persist an uploaded resume with a collision-proof name; returns stored name."""
    original = secure_filename(file_storage.filename)
    if not original or not _allowed_file(original):
        return None
    ext = original.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name))
    return stored_name


def _delete_resume(filename):
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    if os.path.isfile(path):
        os.remove(path)


@jobs.route("/dashboard")
@login_required
def dashboard():
    applications = (
        JobApplication.query.filter_by(user_id=current_user.id)
        .order_by(JobApplication.applied_date.desc())
        .all()
    )
    counts = {status: 0 for status in JOB_STATUSES}
    for app_item in applications:
        counts[app_item.status] = counts.get(app_item.status, 0) + 1

    active = sum(counts.get(s, 0) for s in ("Applied", "Interviewing", "Offer"))
    return render_template(
        "jobs/dashboard.html",
        applications=applications,
        counts=counts,
        total=len(applications),
        active=active,
        recent=applications[:5],
    )


@jobs.route("/jobs")
@login_required
def job_list():
    search = request.args.get("q", "", type=str).strip()
    status_filter = request.args.get("status", "", type=str).strip()
    sort = request.args.get("sort", "newest", type=str)
    if sort not in SORT_OPTIONS:
        sort = "newest"

    query = JobApplication.query.filter_by(user_id=current_user.id)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                JobApplication.company.ilike(like),
                JobApplication.job_title.ilike(like),
                JobApplication.location.ilike(like),
                JobApplication.contact_person.ilike(like),
            )
        )
    if status_filter in JOB_STATUSES:
        query = query.filter_by(status=status_filter)

    applications = query.order_by(SORT_OPTIONS[sort][1]).all()

    return render_template(
        "jobs/list.html",
        applications=applications,
        statuses=JOB_STATUSES,
        sort_options=SORT_OPTIONS,
        current_search=search,
        current_status=status_filter,
        current_sort=sort,
    )


@jobs.route("/jobs/<int:id>")
@login_required
def job_detail(id):
    job = JobApplication.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    return render_template("jobs/detail.html", job=job)


@jobs.route("/jobs/add", methods=["GET", "POST"])
@login_required
def add_job():
    form = JobApplicationForm()
    if form.validate_on_submit():
        job = JobApplication(
            job_title=form.job_title.data.strip(),
            company=form.company.data.strip(),
            location=form.location.data,
            salary=form.salary.data,
            job_url=form.job_url.data,
            contact_person=form.contact_person.data,
            status=form.status.data,
            notes=form.notes.data,
            user_id=current_user.id,
        )
        if form.resume.data:
            stored = _save_resume(form.resume.data)
            if stored:
                job.resume_filename = stored
        db.session.add(job)
        db.session.commit()
        flash("Job application added.", "success")
        return redirect(url_for("jobs.job_detail", id=job.id))

    return render_template("jobs/form.html", form=form, title="Add Job Application", job=None)


@jobs.route("/jobs/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_job(id):
    job = JobApplication.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    form = JobApplicationForm(obj=job)

    if form.validate_on_submit():
        job.job_title = form.job_title.data.strip()
        job.company = form.company.data.strip()
        job.location = form.location.data
        job.salary = form.salary.data
        job.job_url = form.job_url.data
        job.contact_person = form.contact_person.data
        job.status = form.status.data
        job.notes = form.notes.data
        if form.resume.data:
            new_name = _save_resume(form.resume.data)
            if new_name:
                _delete_resume(job.resume_filename)
                job.resume_filename = new_name
        db.session.commit()
        flash("Job application updated.", "success")
        return redirect(url_for("jobs.job_detail", id=job.id))

    return render_template("jobs/form.html", form=form, title="Edit Job Application", job=job)


@jobs.route("/jobs/<int:id>/delete", methods=["POST"])
@login_required
def delete_job(id):
    job = JobApplication.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    _delete_resume(job.resume_filename)
    db.session.delete(job)
    db.session.commit()
    flash("Job application deleted.", "success")
    return redirect(url_for("jobs.job_list"))


@jobs.route("/jobs/<int:id>/resume")
@login_required
def download_resume(id):
    job = JobApplication.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    if not job.resume_filename:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        job.resume_filename,
        as_attachment=True,
    )
