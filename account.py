"""User account page: view and update your profile, change your password.
Owner: Member 6

SECURITY (IDOR): there is no user id in any URL or form here. The account
shown and changed is always g.user (from the signed session).
"""
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

import config
from auth import check_password, ph, register_failure, validate_password
from db import get_db, query_one
from security import log_audit, login_required

bp = Blueprint("account", __name__, url_prefix="/account")



@bp.route("/")
@login_required
def profile():
    return render_template("account/profile.html", user=g.user)


@bp.route("/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "GET":
        return render_template("account/edit.html", errors=[],
                               full_name=g.user["full_name"],
                               shipping_address=g.user["shipping_address"])

    # SECURITY (mass assignment): we read ONLY these two fields. A "role",
    # "store_credit_cents", "email" or "user_id" field added in Burp is never
    # read, and the UPDATE below only names these two columns.
    full_name = request.form.get("full_name", "").strip()
    shipping_address = request.form.get("shipping_address", "").strip()

    errors = []
    # SECURITY (Lab 2.2): too long is REJECTED, never cut to fit.
    if len(full_name) > config.MAX_NAME_LENGTH:
        errors.append(f"Full name must be at most {config.MAX_NAME_LENGTH} characters.")
    if len(shipping_address) > config.MAX_ADDRESS_LENGTH:
        errors.append(f"Shipping address must be at most {config.MAX_ADDRESS_LENGTH} characters.")
    if errors:
        return render_template("account/edit.html", errors=errors, full_name=full_name,
                               shipping_address=shipping_address), 400

    old = g.user
    db = get_db()
    db.execute("UPDATE users SET full_name = ?, shipping_address = ? WHERE id = ?",
               (full_name, shipping_address, g.user["id"]))
    db.commit()
    log_audit("profile_updated",
              f"full_name: {old['full_name']!r} -> {full_name!r}; "
              f"address: {old['shipping_address']!r} -> {shipping_address!r}")
    flash("Your profile was updated.", "success")
    return redirect(url_for("account.profile"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("account/password.html", error=None)

    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    user = query_one("SELECT * FROM users WHERE id = ?", (g.user["id"],))
    # SECURITY: the current password is required, so someone at an unlocked
    # computer (or with a stolen session cookie) cannot take over the account.
    if len(current) > config.MAX_PASSWORD_LENGTH or not check_password(user, current):
        log_audit("password_change_failed", "wrong current password")
        # SECURITY: a wrong current password counts as a failed login, so
        # someone with a stolen session cannot guess the password here
        # without limit. After 5 wrong tries the account is locked and
        # this session is ended.
        if register_failure(user, "wrong current password (change password)"):
            session.clear()
            flash("Too many wrong passwords. Your account is locked for a while.", "error")
            return redirect(url_for("auth.login"))
        return render_template("account/password.html",
                               error="Your current password is not correct."), 400
    error = validate_password(new, confirm, user["username"])
    if error:
        return render_template("account/password.html", error=error), 400

    db = get_db()
    # SECURITY: session_version + 1 logs out every OTHER copy of the session
    # (for example a stolen cookie). This browser gets the new number below,
    # so the user stays logged in here.
    db.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 "
               "WHERE id = ?", (ph.hash(new), user["id"]))
    db.commit()
    session["session_version"] = user["session_version"] + 1
    log_audit("password_changed")
    flash("Your password was changed. Other devices have been logged out.", "success")
    return redirect(url_for("account.profile"))
