"""CSRF-protected browser approval and revocation of device access."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length

from app.contracts import OPTIONAL_FIELDS, ServiceError
from app.devices import (
    approve_pairing,
    credential_hash,
    revoke_device,
    usable_pairing,
)
from app.models import Device, PairingRequest

integrations = Blueprint("integrations", __name__)


class PairingForm(FlaskForm):
    code = StringField(
        "Pairing code", validators=[DataRequired(), Length(max=32)]
    )
    optional_fields = SelectMultipleField(
        "Optional fields",
        choices=[(name, name) for name in sorted(OPTIONAL_FIELDS)],
    )


@integrations.route("/integrations", methods=["GET", "POST"])
@login_required
def index():
    form = PairingForm()
    pairing = None
    status = 200
    if form.validate_on_submit():
        try:
            if request.form.get("action") == "approve":
                approve_pairing(
                    current_user.id, form.code.data, form.optional_fields.data
                )
                flash(
                    "Device approved. "
                    "The waiting client can now redeem its credential.",
                    "success",
                )
                return redirect(url_for("integrations.index"))
            code = form.code.data.strip().replace("-", "").upper()
            pairing = PairingRequest.query.filter_by(
                code_hash=credential_hash(code)
            ).first()
            usable_pairing(pairing)
            if pairing.user_id is not None:
                raise ServiceError(
                    "pairing_used", "Pairing already approved.", 409
                )
        except ServiceError as error:
            flash(str(error), "danger")
            status = error.status
            pairing = None
    devices = (
        Device.query.filter_by(user_id=current_user.id)
        .order_by(Device.created_at.desc())
        .all()
    )
    return render_template(
        "integrations.html", form=form, pairing=pairing, devices=devices
    ), status


@integrations.post("/integrations/devices/<device_id>/revoke")
@login_required
def revoke(device_id):
    revoke_device(current_user.id, device_id)
    flash("Device disconnected and its credential revoked.", "success")
    return redirect(url_for("integrations.index"))
