"""Registration, email confirmation, login, 2FA, logout, password reset.
Owner: Member 1

Rules followed in this file:
- Every SQL query uses "?" placeholders.
- Passwords are hashed with Argon2id and checked with ph.verify(), never ==.
- Tokens (confirm / reset) are random, single use, short-lived and stored
  only as a SHA-256 hash.
- The logged-in user is only ever taken from the signed session.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

import config
from db import get_db, query_one
from security import bump_session_version, client_ip, log_audit

bp = Blueprint("auth", __name__, url_prefix="/auth")

# SECURITY: Argon2id with argon2-cffi's default settings (random salt per hash).
ph = PasswordHasher()

# SECURITY: used when the username does not exist, so the login takes about
# the same time as a real password check (an attacker cannot tell from the
# response time whether a username exists).
DUMMY_HASH = ph.hash("this-is-only-used-to-waste-the-same-time")

GENERIC_LOGIN_ERROR = "Invalid username or password."
GENERIC_RESET_MESSAGE = "If the account exists, a reset link was sent."

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_]+")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def load_common_passwords():
    """Read common_passwords.txt once, when the app starts."""
    with open(config.COMMON_PASSWORDS_FILE, encoding="utf-8") as f:
        return {line.strip().lower() for line in f if line.strip()}


COMMON_PASSWORDS = load_common_passwords()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def validate_username(username):
    """Return an error message, or None if the username is OK."""
    if username == "":
        return "Username is required."
    # SECURITY (Lab 2.2): too long is REJECTED, never cut to fit.
    if len(username) < config.MIN_USERNAME_LENGTH or len(username) > config.MAX_USERNAME_LENGTH:
        return (f"Username must be {config.MIN_USERNAME_LENGTH}-"
                f"{config.MAX_USERNAME_LENGTH} characters.")
    if not USERNAME_PATTERN.fullmatch(username):
        return "Username may only contain letters, numbers and underscore (_)."
    return None


def validate_email(email):
    """Return an error message, or None if the email is OK."""
    if email == "":
        return "Email is required."
    # SECURITY (Lab 2.2): too long is REJECTED, never cut to fit.
    if len(email) > config.MAX_EMAIL_LENGTH:
        return f"Email must be at most {config.MAX_EMAIL_LENGTH} characters."
    if not EMAIL_PATTERN.fullmatch(email):
        return "Please enter a valid email address."
    return None


def validate_password(password, confirm, username=""):
    """Return an error message, or None if the password is OK.
    Other members can import this (e.g. account.py for 'change password')."""
    if password == "":
        return "Password is required."
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters."
    if len(password) > config.MAX_PASSWORD_LENGTH:
        return f"Password must be at most {config.MAX_PASSWORD_LENGTH} characters."
    # SECURITY (L4): refuse passwords that attackers try first.
    if password.lower() in COMMON_PASSWORDS:
        return "This password is too common. Please choose another one."
    if username and password.lower() == username.lower():
        return "Password must not be the same as the username."
    if password != confirm:
        return "The two passwords do not match."
    return None


def new_token():
    """Make a random token. Returns (token for the link, hash for the database).
    SECURITY: only the hash is stored, so a stolen database gives no working links."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_email(to_address, subject, body):
    """There is no mail server: the "email" is written as a text file into outbox/.
    The file name does not contain the email address (no user input in paths)."""
    outbox = current_app.config["OUTBOX_DIR"]
    os.makedirs(outbox, exist_ok=True)
    filename = f"{int(time.time())}_{secrets.token_hex(4)}.txt"
    with open(os.path.join(outbox, filename), "w", encoding="utf-8") as f:
        f.write(f"To: {to_address}\nSubject: {subject}\n\n{body}\n")


def record_login_attempt(username, success):
    """Save every login try (also for usernames that do not exist)."""
    if len(username) > config.MAX_USERNAME_LENGTH:
        username = "(too long)"
    db = get_db()
    db.execute(
        "INSERT INTO login_attempts (username, ip_address, success) VALUES (?, ?, ?)",
        (username, client_ip(), 1 if success else 0),
    )
    db.commit()


def register_failure(user, reason):
    """Count one failed login (or one wrong 2FA code) for an existing user.
    Returns True if the account is now locked.

    SECURITY (L4, Lab 3 brute force): after 5 failures the account is locked
    for 1 minute. Every new lock is twice as long (1, 2, 4, 8 ... minutes),
    up to 30 minutes."""
    db = get_db()
    log_audit("login_failed", reason, user_id=user["id"])
    # Increase the counter inside SQL, so two requests at once both count.
    db.execute("UPDATE users SET failed_login_count = failed_login_count + 1 WHERE id = ?",
               (user["id"],))
    row = db.execute("SELECT failed_login_count, lock_count FROM users WHERE id = ?",
                     (user["id"],)).fetchone()
    locked = False
    if row["failed_login_count"] >= config.LOCKOUT_AFTER_FAILURES:
        lock_count = row["lock_count"] + 1
        seconds = min(config.LOCKOUT_BASE_SECONDS * 2 ** (lock_count - 1),
                      config.LOCKOUT_MAX_SECONDS)
        db.execute(
            "UPDATE users SET failed_login_count = 0, lock_count = ?, locked_until = ? WHERE id = ?",
            (lock_count, int(time.time()) + seconds, user["id"]),
        )
        locked = True
    db.commit()
    if locked:
        log_audit("account_locked", f"seconds={seconds}", user_id=user["id"])
    return locked


def check_password(user, password):
    """True if the password matches. Upgrades the hash if settings changed."""
    try:
        ph.verify(user["password_hash"], password)
    except (VerificationError, InvalidHashError):
        return False
    if ph.check_needs_rehash(user["password_hash"]):
        db = get_db()
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (ph.hash(password), user["id"]))
        db.commit()
    return True


def waste_time_like_a_password_check(password):
    """Same work as a real check, so timing does not reveal anything."""
    try:
        ph.verify(DUMMY_HASH, password)
    except VerificationError:
        pass


def finish_login(user, mfa_done=False):
    """The user passed every check: start a fresh session.
    mfa_done=True only after a correct 2FA code (admin pages need it)."""
    db = get_db()
    # SECURITY: reset the brute-force counters only after a full success.
    db.execute(
        "UPDATE users SET failed_login_count = 0, lock_count = 0, locked_until = 0 WHERE id = ?",
        (user["id"],),
    )
    db.commit()
    # SECURITY: clear the old session first (no session fixation, and no
    # leftover pending_2fa_user_id), then store ONLY the user id. The role is
    # read from the database on every request (security.load_logged_in_user).
    session.clear()
    session["user_id"] = user["id"]
    # SECURITY: must match users.session_version on every request
    # (security.load_logged_in_user), so old copied cookies stop working.
    session["session_version"] = user["session_version"]
    session["mfa_done"] = mfa_done
    session.permanent = True        # use the 30-minute lifetime from config
    record_login_attempt(user["username"], True)
    log_audit("login_success", "", user_id=user["id"])


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------

@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("auth/register.html", errors=[], username="", email="")

    # Leading/trailing spaces are removed; nothing else is changed or cut.
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    errors = []
    for error in (validate_username(username), validate_email(email),
                  validate_password(password, confirm, username)):
        if error:
            errors.append(error)

    if not errors and query_one("SELECT id FROM users WHERE username = ?", (username,)):
        errors.append("That username is already taken.")

    if errors:
        # SECURITY: values are shown back through Jinja2 autoescaping (no XSS).
        return render_template("auth/register.html", errors=errors,
                               username=username, email=email), 400

    db = get_db()
    existing = query_one("SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        # SECURITY: do not tell the visitor that this email is registered
        # (that would let attackers find out who has an account). We email
        # the real owner instead and show the normal message below.
        send_email(email, "Someone tried to register with your email",
                   "Someone tried to create a SecureShop account with this email.\n"
                   "If it was you, log in or use 'Forgot password'.")
        log_audit("register_duplicate_email", "", user_id=existing["id"])
    else:
        try:
            # SECURITY (Lab 2.2): role is ALWAYS 'user' - it is never taken
            # from the form or worked out from the email address.
            cur = db.execute(
                "INSERT INTO users (username, email, password_hash, role, is_confirmed, "
                "store_credit_cents) VALUES (?, ?, ?, 'user', 0, ?)",
                (username, email, ph.hash(password), config.STARTING_CREDIT_CENTS),
            )
        except sqlite3.IntegrityError:
            # Someone took the username a moment ago (double submit / race).
            return render_template("auth/register.html", username=username, email=email,
                                   errors=["That username is already taken."]), 400
        user_id = cur.lastrowid

        # SECURITY: account stays inactive until the email is confirmed.
        token, token_hash = new_token()
        db.execute(
            "INSERT INTO email_confirm_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_hash, int(time.time()) + config.CONFIRM_TOKEN_HOURS * 3600),
        )
        db.commit()
        link = url_for("auth.confirm_email", token=token, _external=True)
        send_email(email, "Confirm your SecureShop account",
                   f"Hello {username},\n\nOpen this link to confirm your email:\n{link}\n\n"
                   f"The link works once and expires in {config.CONFIRM_TOKEN_HOURS} hours.")
        log_audit("register", f"username={username}", user_id=user_id)

    flash("Account created. Please confirm your email with the link we sent "
          "(see the outbox/ folder), then log in.", "success")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# 2. Email confirmation
# ---------------------------------------------------------------------------

@bp.route("/confirm/<token>")
def confirm_email(token):
    db = get_db()
    now = int(time.time())
    row = None
    if len(token) <= 100:
        row = query_one(
            "SELECT id, user_id FROM email_confirm_tokens "
            "WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
            (hash_token(token), now),
        )
    if row is None:
        return render_template("auth/message.html", title="Link not valid",
                               message="This confirmation link is invalid, already used or expired.",
                               ok=False), 400

    # SECURITY: single use - "AND used_at IS NULL" stops two requests using it at once.
    cur = db.execute("UPDATE email_confirm_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
                     (now, row["id"]))
    if cur.rowcount != 1:
        return render_template("auth/message.html", title="Link not valid",
                               message="This confirmation link is invalid, already used or expired.",
                               ok=False), 400
    db.execute("UPDATE users SET is_confirmed = 1 WHERE id = ?", (row["user_id"],))
    db.commit()
    log_audit("email_confirmed", "", user_id=row["user_id"])
    return render_template("auth/message.html", title="Email confirmed",
                           message="Your email is confirmed. You can now log in.", ok=True)


# ---------------------------------------------------------------------------
# 3. Login
# ---------------------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("auth/login.html", error=None, username="")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    now = int(time.time())

    user = None
    if (0 < len(username) <= config.MAX_USERNAME_LENGTH
            and 0 < len(password) <= config.MAX_PASSWORD_LENGTH):
        user = query_one("SELECT * FROM users WHERE username = ?", (username,))

    # SECURITY (L5): every failure below shows the SAME message, so an attacker
    # cannot tell "no such user", "wrong password", "locked" or "not confirmed" apart.
    def fail():
        record_login_attempt(username, False)
        return render_template("auth/login.html", error=GENERIC_LOGIN_ERROR,
                               username=username), 401

    if user is None:
        waste_time_like_a_password_check(password)
        log_audit("login_failed", "unknown username")
        return fail()

    if user["locked_until"] > now:
        # SECURITY: while locked we do not even check the password, so
        # guessing during the lock is useless (and does not extend the lock).
        waste_time_like_a_password_check(password)
        log_audit("login_failed", "account is locked", user_id=user["id"])
        return fail()

    if user["is_disabled"]:
        # SECURITY: an admin disabled this account. Same generic message.
        waste_time_like_a_password_check(password)
        log_audit("login_failed", "account is disabled", user_id=user["id"])
        return fail()

    if not check_password(user, password):
        register_failure(user, "wrong password")
        return fail()

    if not user["is_confirmed"]:
        # SECURITY: unconfirmed accounts cannot log in.
        log_audit("login_failed", "email not confirmed", user_id=user["id"])
        return fail()

    if user["role"] == "admin":
        if not user["totp_secret"]:
            # SECURITY: fail secure - an admin without 2FA is not let in.
            log_audit("login_failed", "admin has no 2FA secret", user_id=user["id"])
            return fail()
        # SECURITY (Lab 3): the admin is NOT logged in yet. We remember only
        # who passed the password step, inside the signed session. The code
        # page reads the user from here - never from the form or the URL.
        # The failure counter starts again, so the admin gets 5 tries for the
        # code; lock_count is kept, so repeated locks still get longer.
        db = get_db()
        db.execute("UPDATE users SET failed_login_count = 0 WHERE id = ?", (user["id"],))
        db.commit()
        session.clear()
        session["pending_2fa_user_id"] = user["id"]
        session["pending_2fa_started"] = now
        return redirect(url_for("auth.two_factor"))

    finish_login(user)
    flash("Welcome back!", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# 4. Two-factor code for admins (TOTP)
# ---------------------------------------------------------------------------

def cancel_pending_login(message):
    session.clear()
    flash(message, "error")
    return redirect(url_for("auth.login"))


@bp.route("/two-factor", methods=["GET", "POST"])
def two_factor():
    # SECURITY (Lab 3 2FA bypass): the user comes ONLY from the signed session.
    # Any "user", "username" or "user_id" in the form or URL is ignored.
    user_id = session.get("pending_2fa_user_id")
    started = session.get("pending_2fa_started", 0)
    if user_id is None:
        return redirect(url_for("auth.login"))
    if time.time() - started > config.TOTP_PENDING_MINUTES * 60:
        return cancel_pending_login("The login took too long. Please log in again.")

    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user is None or user["role"] != "admin" or not user["totp_secret"]:
        return cancel_pending_login(GENERIC_LOGIN_ERROR)
    if user["locked_until"] > time.time():
        return cancel_pending_login(GENERIC_LOGIN_ERROR)

    if request.method == "GET":
        return render_template("auth/two_factor.html", error=None)

    code = request.form.get("code", "").strip()
    totp = pyotp.TOTP(user["totp_secret"])

    # Which 30-second time step does the code belong to? valid_window=1 means
    # the previous, current and next step are accepted (small clock drift).
    matched_step = None
    if len(code) == 6 and code.isdigit() and totp.verify(code, valid_window=1):
        now = int(time.time())
        for offset in (-1, 0, 1):
            moment = now + offset * totp.interval
            if hmac.compare_digest(totp.at(moment), code):
                matched_step = moment // totp.interval

    # SECURITY (L5): a code from the same or an older time step than the last
    # accepted one is refused, so a sniffed/used code cannot be replayed.
    # "AND totp_last_step < ?" also stops two requests using one code at once.
    accepted = False
    if matched_step is not None:
        db = get_db()
        cur = db.execute("UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?",
                         (matched_step, user["id"], matched_step))
        db.commit()
        accepted = cur.rowcount == 1

    if not accepted:
        log_audit("2fa_failed", "wrong or reused code", user_id=user["id"])
        # SECURITY: wrong codes count as failed logins. After 5 the account is
        # locked and the pending login is thrown away.
        if register_failure(user, "wrong 2FA code"):
            return cancel_pending_login("Too many wrong codes. Please log in again later.")
        return render_template("auth/two_factor.html", error="Invalid code. Please try again."), 401

    finish_login(user, mfa_done=True)
    flash("Welcome back, admin!", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# 5. Logout
# ---------------------------------------------------------------------------

@bp.route("/logout", methods=["POST"])
def logout():
    # SECURITY: POST only, so another site cannot log you out with a link/image.
    if g.user is not None:
        log_audit("logout")
        # SECURITY: a copy of this session cookie (stolen or saved earlier)
        # stops working too, because its session_version is now too old.
        bump_session_version(g.user["id"])
    session.clear()        # removes user_id and anything else in the session
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# 6. Forgot / reset password
# ---------------------------------------------------------------------------

@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("auth/forgot_password.html", error=None, email="")

    email = request.form.get("email", "").strip().lower()
    error = validate_email(email)
    if error:
        # Only the FORMAT is checked here - this says nothing about whether
        # an account exists.
        return render_template("auth/forgot_password.html", error=error, email=email), 400

    user = query_one("SELECT id, username, email FROM users WHERE email = ?", (email,))
    if user is not None:
        token, token_hash = new_token()
        db = get_db()
        db.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], token_hash, int(time.time()) + config.RESET_TOKEN_MINUTES * 60),
        )
        db.commit()
        link = url_for("auth.reset_password", token=token, _external=True)
        send_email(user["email"], "Reset your SecureShop password",
                   f"Hello {user['username']},\n\nOpen this link to choose a new password:\n"
                   f"{link}\n\nThe link works once and expires in "
                   f"{config.RESET_TOKEN_MINUTES} minutes.\n"
                   "If you did not ask for this, you can ignore this email.")
        log_audit("password_reset_requested", "", user_id=user["id"])

    # SECURITY (L5): the same message whether the account exists or not,
    # so attackers cannot use this page to find registered emails.
    # (No security questions - they are easy to guess or look up.)
    flash(GENERIC_RESET_MESSAGE, "info")
    return redirect(url_for("auth.login"))


def find_reset_token(token):
    """Return the token row if it exists, is unused and not expired."""
    if len(token) > 100:
        return None
    return query_one(
        "SELECT t.id, t.user_id, u.username FROM password_reset_tokens t "
        "JOIN users u ON u.id = t.user_id "
        "WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ?",
        (hash_token(token), int(time.time())),
    )


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = find_reset_token(token)
    if row is None:
        return render_template("auth/message.html", title="Link not valid",
                               message="This reset link is invalid, already used or expired. "
                                       "Please ask for a new one.", ok=False), 400

    if request.method == "GET":
        return render_template("auth/reset_password.html", error=None, token=token)

    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")
    error = validate_password(password, confirm, row["username"])
    if error:
        return render_template("auth/reset_password.html", error=error, token=token), 400

    db = get_db()
    # SECURITY: single use - mark the token used (only if it is still unused).
    cur = db.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
                     (int(time.time()), row["id"]))
    if cur.rowcount != 1:
        return render_template("auth/message.html", title="Link not valid",
                               message="This reset link was already used.", ok=False), 400
    # SECURITY: other reset links for this user stop working too.
    db.execute("DELETE FROM password_reset_tokens WHERE user_id = ? AND id != ?",
               (row["user_id"], row["id"]))
    # New hash, the brute-force counters start again, and every old session
    # of this user is logged out (session_version + 1).
    db.execute(
        "UPDATE users SET password_hash = ?, failed_login_count = 0, lock_count = 0, "
        "locked_until = 0, session_version = session_version + 1 WHERE id = ?",
        (ph.hash(password), row["user_id"]),
    )
    db.commit()
    session.clear()
    log_audit("password_reset", "", user_id=row["user_id"])
    flash("Your password was changed. You can now log in.", "success")
    return redirect(url_for("auth.login"))
