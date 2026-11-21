"""Shared security helpers used by every blueprint:
- load_logged_in_user: runs before every request and puts the user in g.user
- login_required / admin_required: decorators for routes
- log_audit: writes one row to the audit_log table
"""
import functools

from flask import abort, flash, g, redirect, request, session, url_for

from db import get_db, query_one


def load_logged_in_user():
    """Look up the logged-in user from the session.

    SECURITY (Lab 3): the session only holds the user's id, and it is set by
    the server after a successful login. We never read a username or user id
    from a form, URL or our own cookie to decide who the user is.
    We also re-read the role from the database on every request, so if an
    admin removes someone's admin role it takes effect immediately.

    Note: Flask's session is a cookie signed with SECRET_KEY. The user can
    read it but cannot change it without breaking the signature (this is the
    fix for the Lab 3 "verify=carlos" cookie). Never put secrets (passwords,
    TOTP secrets, tokens) in the session.
    "pending_2fa_user_id" (password OK, code not yet entered) is NOT a login:
    only "user_id" makes g.user.
    """
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        user = query_one(
            "SELECT id, username, email, full_name, shipping_address, role, "
            "store_credit_cents, is_disabled, session_version FROM users WHERE id = ?",
            (user_id,),
        )
        # SECURITY: the session is only valid if its session_version still
        # matches the database. Logout, password change and role change
        # increase the number, so an old copied cookie no longer works.
        # A disabled (or deleted) account is logged out at once.
        if (user is None or user["is_disabled"] == 1
                or session.get("session_version") != user["session_version"]):
            session.clear()
        else:
            g.user = user


def bump_session_version(user_id):
    """Make every existing session of this user invalid (see above)."""
    db = get_db()
    db.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (user_id,))
    db.commit()


def login_required(view):
    """Only logged-in users can open this route."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "info")
            # SECURITY: we do not use a ?next= parameter, so attackers
            # cannot turn the login page into an open redirect.
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Only admins can open this route. The check is done on the server
    every time - hiding the Admin link in the menu is NOT protection."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.login"))
        # SECURITY: role from the database (g.user) AND the 2FA step must
        # have been completed in this session.
        if g.user["role"] != "admin" or session.get("mfa_done") is not True:
            # SECURITY: accountability - record who tried to reach admin pages
            log_audit("admin_access_denied", f"path={request.path}")
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def client_ip():
    """IP address of the visitor (used in logs and login attempts)."""
    return request.remote_addr or "unknown"


def log_audit(action, details="", user_id=None):
    """Write one audit row. Use short action names, for example:
    login_success, login_failed, account_locked, order_paid,
    coupon_redeemed, admin_product_updated, admin_access_denied.

    SECURITY: never put passwords, tokens or TOTP codes in `details`.
    """
    if user_id is None and g.get("user") is not None:
        user_id = g.user["id"]
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (user_id, action, details, ip_address) "
        "VALUES (?, ?, ?, ?)",
        (user_id, action, details[:500], client_ip()),
    )
    db.commit()
