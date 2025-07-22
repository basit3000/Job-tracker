from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import JobApplication

jobs = Blueprint('jobs', __name__)

@jobs.route('/jobs')
@login_required
def job_list():
    applications = JobApplication.query.filter_by(user_id=current_user.id).all()
    return render_template('jobs/list.html', applications=applications)

@jobs.route('/jobs/add', methods=['GET', 'POST'])
@login_required
def add_job():
    if request.method == 'POST':
        company = request.form['company']
        contact_person = request.form.get('contact_person')
        status = request.form.get('status', 'Applied')
        notes = request.form.get('notes')
        
        job = JobApplication(company=company, contact_person=contact_person, status=status,
                             notes=notes, user_id=current_user.id)
        db.session.add(job)
        db.session.commit()
        flash('Job application added.', 'success')
        return redirect(url_for('jobs.job_list'))

    return render_template('jobs/add.html')

@jobs.route('/jobs/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_job(id):
    job = JobApplication.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        job.company = request.form['company']
        job.contact_person = request.form.get('contact_person')
        job.status = request.form.get('status')
        job.notes = request.form.get('notes')
        db.session.commit()
        flash('Job application updated.', 'success')
        return redirect(url_for('jobs.job_list'))

    return render_template('jobs/edit.html', job=job)

@jobs.route('/jobs/<int:id>/delete', methods=['POST'])
@login_required
def delete_job(id):
    job = JobApplication.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(job)
    db.session.commit()
    flash('Job application deleted.', 'success')
    return redirect(url_for('jobs.job_list'))
