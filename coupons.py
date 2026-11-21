"""Coupons and newsletter.
Owner: Member 4

Rules (Lab 2.1 - coupon stacking):
- the session holds ONE coupon CODE (never a discount amount); a new code
  REPLACES the old one, so discounts can never stack
- check_coupon() is the one place where all coupon rules are checked.
  The cart page uses it, and orders.py must call it AGAIN right before
  payment and record the redemption only when payment succeeds
- each user can use a code only ONCE (also UNIQUE(coupon_id, user_id) in the database)
- percent coupons are 1-30%; every discount is capped by the coupon's
  max_discount_cents and can never be more than the cart total
"""
import secrets
import sqlite3
import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

import config
from auth import send_email
from db import get_db, query_one
from security import log_audit, login_required

bp = Blueprint("coupons", __name__)

# Same message for "does not exist", "inactive" and "belongs to someone else",
# so a guesser cannot tell those apart. Only this error counts as a guess.
NOT_VALID = "This coupon code is not valid."


def format_money(cents):
    return f"${cents / 100:,.2f}"


def check_coupon(user_id, code, cart_total_cents):
    """Check every coupon rule on the server.

    Returns (coupon_row, discount_cents, None) if the coupon can be used,
    or (None, 0, error_message) if not. It does NOT change anything in the
    database, so it is safe to call as often as needed (cart page, checkout).
    """
    code = code.strip()
    if code == "":
        return None, 0, "Please enter a coupon code."
    # SECURITY (Lab 2.2): too long is REJECTED, never cut to fit.
    if len(code) > config.MAX_COUPON_CODE_LENGTH:
        return None, 0, f"Coupon codes are at most {config.MAX_COUPON_CODE_LENGTH} characters."

    # The code column is COLLATE NOCASE, so "welcome5" finds "WELCOME5".
    coupon = query_one("SELECT * FROM coupons WHERE code = ?", (code,))
    if coupon is None or coupon["is_active"] != 1:
        return None, 0, NOT_VALID
    # SECURITY: a personal (newsletter) coupon only works for its owner.
    if coupon["owner_user_id"] is not None and coupon["owner_user_id"] != user_id:
        return None, 0, NOT_VALID
    if coupon["expires_at"] is not None and coupon["expires_at"] <= time.time():
        return None, 0, "This coupon has expired."

    # SECURITY (Lab 2.1): each user can use a coupon only once.
    used_by_me = query_one("SELECT 1 FROM coupon_redemptions WHERE coupon_id = ? AND user_id = ?",
                           (coupon["id"], user_id))
    if used_by_me:
        return None, 0, "You have already used this coupon."
    if coupon["max_uses"] is not None:
        uses = query_one("SELECT COUNT(*) AS n FROM coupon_redemptions WHERE coupon_id = ?",
                         (coupon["id"],))["n"]
        if uses >= coupon["max_uses"]:
            return None, 0, "This coupon has been used up."

    if cart_total_cents <= 0:
        return None, 0, "Your cart is empty."
    if cart_total_cents < coupon["min_total_cents"]:
        return None, 0, (f"This coupon needs a cart total of at least "
                         f"{format_money(coupon['min_total_cents'])}.")

    # Work out the discount in whole cents.
    if coupon["discount_type"] == "percent":
        discount = cart_total_cents * coupon["discount_value"] // 100
    else:
        discount = coupon["discount_value"]
    # SECURITY: caps, applied one after the other. (Percent coupons are
    # already limited to 1-30% by the CHECK in schema.sql and by admin.py.)
    if coupon["max_discount_cents"] is not None:
        discount = min(discount, coupon["max_discount_cents"])            # the coupon's own cap
    discount = min(discount, cart_total_cents)                            # never below $0 total
    if discount <= 0:
        return None, 0, "Your cart total is too small for this coupon."
    return coupon, discount, None


def recent_failures(user_id):
    """How many wrong codes this user typed in the last 10 minutes."""
    since = int(time.time()) - config.COUPON_FAILURE_WINDOW_MINUTES * 60
    return query_one(
        "SELECT COUNT(*) AS n FROM coupon_failed_attempts WHERE user_id = ? AND attempted_at > ?",
        (user_id, since),
    )["n"]


@bp.route("/coupons/apply", methods=["POST"])
@login_required
def apply_coupon():
    # Imported here (not at the top) because cart.py also imports coupons.py.
    from cart import load_cart_lines

    user_id = g.user["id"]
    code = request.form.get("code", "").strip()

    # SECURITY: stop people guessing codes (e.g. Burp Intruder over NEWS-xxxx).
    # After 10 wrong codes in 10 minutes, every code is refused - even a
    # correct one - until the old failures are older than 10 minutes.
    if recent_failures(user_id) >= config.COUPON_MAX_FAILURES:
        log_audit("coupon_guessing_blocked", f"code={code[:config.MAX_COUPON_CODE_LENGTH]}")
        flash("Too many wrong coupon codes. Please try again in a few minutes.", "error")
        return redirect(url_for("cart.view_cart"))

    lines, subtotal = load_cart_lines()
    coupon, discount, error = check_coupon(user_id, code, subtotal)

    if error:
        if error == NOT_VALID:
            db = get_db()
            db.execute("INSERT INTO coupon_failed_attempts (user_id, attempted_at) VALUES (?, ?)",
                       (user_id, int(time.time())))
            db.commit()
        log_audit("coupon_rejected", f"reason={error} code={code[:config.MAX_COUPON_CODE_LENGTH]}")
        flash(error, "error")
        return redirect(url_for("cart.view_cart"))

    # SECURITY (Lab 2.1): ONE code in the session. Setting it overwrites the
    # old one, so WELCOME5 -> SAVE20 -> WELCOME5 still means one coupon.
    # Only the code is stored - the discount is recalculated every time.
    old_code = session.get("coupon_code")
    session["coupon_code"] = coupon["code"]
    log_audit("coupon_applied", f"coupon_id={coupon['id']} discount_cents={discount}")
    if old_code and old_code.upper() != coupon["code"].upper():
        flash(f"Coupon {coupon['code']} applied. It replaced {old_code} "
              "(only one coupon per order).", "success")
    else:
        flash(f"Coupon {coupon['code']} applied: -{format_money(discount)}.", "success")
    return redirect(url_for("cart.view_cart"))


@bp.route("/coupons/remove", methods=["POST"])
@login_required
def remove_coupon():
    session.pop("coupon_code", None)
    flash("The coupon was removed.", "info")
    return redirect(url_for("cart.view_cart"))


@bp.route("/newsletter", methods=["GET", "POST"])
@login_required
def newsletter():
    user = query_one("SELECT id, email, is_confirmed FROM users WHERE id = ?", (g.user["id"],))
    subscribed = query_one("SELECT id FROM newsletter_subscribers WHERE user_id = ? OR email = ?",
                           (user["id"], user["email"]))

    if request.method == "GET":
        return render_template("coupons/newsletter.html", subscribed=subscribed)

    # SECURITY: only confirmed accounts (so nobody farms coupons with fake emails).
    if not user["is_confirmed"]:
        flash("Please confirm your email address first.", "error")
        return redirect(url_for("coupons.newsletter"))
    # SECURITY: one signup per user AND per email address.
    if subscribed:
        flash("You are already subscribed. Each account gets only one newsletter coupon.", "info")
        return redirect(url_for("coupons.newsletter"))

    # SECURITY: the code is random (secrets, not random), so it cannot be
    # predicted; it is tied to this user and can be used once.
    code = "NEWS-" + secrets.token_hex(5).upper()          # e.g. NEWS-3F9A0C12B7
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO coupons (code, discount_type, discount_value, max_discount_cents, "
            "max_uses, owner_user_id) VALUES (?, 'percent', ?, ?, 1, ?)",
            (code, config.NEWSLETTER_DISCOUNT_PERCENT, config.NEWSLETTER_MAX_DISCOUNT_CENTS,
             user["id"]),
        )
        # The email comes from the ACCOUNT, never from the form.
        db.execute("INSERT INTO newsletter_subscribers (user_id, email, coupon_id) VALUES (?, ?, ?)",
                   (user["id"], user["email"], cur.lastrowid))
        db.commit()
    except sqlite3.IntegrityError:
        # Two signups at the same moment: the UNIQUE constraints stop the second one.
        db.rollback()
        flash("You are already subscribed. Each account gets only one newsletter coupon.", "info")
        return redirect(url_for("coupons.newsletter"))

    send_email(user["email"], "Your SecureShop newsletter coupon",
               f"Thanks for subscribing!\n\nYour personal coupon code: {code}\n"
               f"{config.NEWSLETTER_DISCOUNT_PERCENT}% off (at most "
               f"{format_money(config.NEWSLETTER_MAX_DISCOUNT_CENTS)}), one use, "
               "only for your account.")
    log_audit("newsletter_signup", f"coupon_id={cur.lastrowid}")
    flash("You are subscribed! Your personal coupon code was sent to your email "
          "(see the outbox/ folder).", "success")
    return redirect(url_for("coupons.newsletter"))
