"""Admin panel: users, products, coupons and the audit log.
Owner: Member 6

SECURITY (least privilege): EVERY route here uses @admin_required. It checks
the role from the DATABASE on every request and that the 2FA step was done
in this session. Hiding the Admin link is NOT the protection - this is.
Every change is POST and is written to audit_log with the old and new value.
"""
import re
import sqlite3
import time
from datetime import datetime

import pyotp
from flask import (Blueprint, abort, flash, g, make_response, redirect, render_template,
                   request, url_for)

import config
from catalog import escape_like
from db import get_db, query_all, query_one
from security import admin_required, bump_session_version, log_audit

bp = Blueprint("admin", __name__, url_prefix="/admin")

MONEY_PATTERN = re.compile(r"\d{1,7}(\.\d{1,2})?")             # 12, 12.5, 12.50 (no minus)
SIGNED_MONEY_PATTERN = re.compile(r"[+-]?\d{1,6}(\.\d{1,2})?")  # +10, -5.25
WHOLE_NUMBER_PATTERN = re.compile(r"\d{1,7}")
COUPON_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{3,32}")
MAX_REASON_LENGTH = 200


def dollars_to_cents(text):
    """'12.50' -> 1250. Only call this after the text matched a pattern above."""
    return round(float(text) * 100)


def count_active_admins():
    return query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_disabled = 0")["n"]


def get_user_or_404(user_id):
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user is None:
        abort(404)
    return user


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/")
@admin_required
def dashboard():
    stats = {
        "users": query_one("SELECT COUNT(*) AS n FROM users")["n"],
        "products": query_one("SELECT COUNT(*) AS n FROM products WHERE is_active = 1")["n"],
        "orders": query_one("SELECT COUNT(*) AS n FROM orders WHERE status = 'paid'")["n"],
        "coupons": query_one("SELECT COUNT(*) AS n FROM coupons WHERE is_active = 1")["n"],
    }
    return render_template("admin/dashboard.html", stats=stats)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@bp.route("/users")
@admin_required
def manage_users():
    q = request.args.get("q", "").strip()
    if len(q) > config.MAX_SEARCH_LENGTH:
        flash(f"Search text must be at most {config.MAX_SEARCH_LENGTH} characters.", "error")
        q = ""
    # SECURITY: "?" placeholders, also for the search (% and _ are plain characters).
    pattern = "%" + escape_like(q) + "%"
    users = query_all(
        "SELECT id, username, email, full_name, role, is_confirmed, is_disabled, "
        "store_credit_cents, locked_until FROM users "
        "WHERE username LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' ORDER BY id",
        (pattern, pattern))
    return render_template("admin/users.html", users=users, q=q, now=time.time())


@bp.route("/users/<int:user_id>/toggle-disabled", methods=["POST"])
@admin_required
def toggle_user_disabled(user_id):
    user = get_user_or_404(user_id)
    # SECURITY: an admin cannot lock themselves out, and the last admin stays.
    if user["id"] == g.user["id"]:
        flash("You cannot disable your own account.", "error")
        return redirect(url_for("admin.manage_users"))
    disable = user["is_disabled"] == 0
    if disable and user["role"] == "admin" and count_active_admins() <= 1:
        flash("You cannot disable the last admin.", "error")
        return redirect(url_for("admin.manage_users"))

    db = get_db()
    db.execute("UPDATE users SET is_disabled = ? WHERE id = ?", (1 if disable else 0, user["id"]))
    db.commit()
    if disable:
        bump_session_version(user["id"])        # SECURITY: logged out right now
    log_audit("admin_user_disabled" if disable else "admin_user_enabled",
              f"user={user['username']} is_disabled: {user['is_disabled']} -> {1 if disable else 0}")
    flash(f"{user['username']} was {'disabled' if disable else 'enabled'}.", "success")
    return redirect(url_for("admin.manage_users"))


@bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def change_role(user_id):
    user = get_user_or_404(user_id)
    new_role = request.form.get("role", "")
    # SECURITY: allow-list of roles - anything else is refused.
    if new_role not in ("user", "admin"):
        flash("Unknown role.", "error")
        return redirect(url_for("admin.manage_users"))
    if new_role == user["role"]:
        flash(f"{user['username']} already has the role {new_role}.", "info")
        return redirect(url_for("admin.manage_users"))
    if user["id"] == g.user["id"]:
        flash("You cannot change your own role.", "error")
        return redirect(url_for("admin.manage_users"))
    # SECURITY: never leave the shop without an active admin. (Together with
    # "not yourself" above, this is a second safety net.)
    if user["role"] == "admin" and user["is_disabled"] == 0 and count_active_admins() <= 1:
        flash("You cannot remove the last admin.", "error")
        return redirect(url_for("admin.manage_users"))

    db = get_db()
    secret = None
    if new_role == "admin":
        # SECURITY: every admin must use 2FA, so a new admin gets a new TOTP secret.
        secret = pyotp.random_base32()
        db.execute("UPDATE users SET role = 'admin', totp_secret = ?, totp_last_step = 0 "
                   "WHERE id = ?", (secret, user["id"]))
    else:
        db.execute("UPDATE users SET role = 'user', totp_secret = NULL WHERE id = ?", (user["id"],))
    db.commit()
    # SECURITY: their current session ends, so a new admin must log in WITH 2FA.
    bump_session_version(user["id"])
    log_audit("admin_role_changed", f"user={user['username']} role: {user['role']} -> {new_role}")

    if secret:
        # SECURITY: the secret is shown ONCE, on this page only. It is not put
        # in a flash message (that would store it in the session cookie) and
        # the page asks the browser not to cache it.
        uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="SecureShop")
        response = make_response(render_template("admin/totp_secret.html", user=user,
                                                 secret=secret, uri=uri))
        response.headers["Cache-Control"] = "no-store"
        return response
    flash(f"{user['username']} is now a normal user.", "success")
    return redirect(url_for("admin.manage_users"))


@bp.route("/users/<int:user_id>/credit", methods=["POST"])
@admin_required
def adjust_credit(user_id):
    user = get_user_or_404(user_id)
    # SECURITY: separation of duties - an admin cannot give themselves money.
    if user["id"] == g.user["id"]:
        flash("You cannot change your own store credit. Ask another admin.", "error")
        return redirect(url_for("admin.manage_users"))
    amount_text = request.form.get("amount", "").strip()
    reason = request.form.get("reason", "").strip()

    if not SIGNED_MONEY_PATTERN.fullmatch(amount_text) or dollars_to_cents(amount_text.lstrip("+-")) == 0:
        flash("Amount must be a number like 10, +10.50 or -5 (not 0).", "error")
        return redirect(url_for("admin.manage_users"))
    if len(reason) < 3 or len(reason) > MAX_REASON_LENGTH:
        flash(f"A reason (3-{MAX_REASON_LENGTH} characters) is required.", "error")
        return redirect(url_for("admin.manage_users"))

    cents = dollars_to_cents(amount_text.lstrip("+-"))
    if amount_text.startswith("-"):
        cents = -cents
    db = get_db()
    # SECURITY: "AND store_credit_cents + ? >= 0" - the credit can never go
    # below zero (and the CHECK in schema.sql refuses it too).
    cur = db.execute("UPDATE users SET store_credit_cents = store_credit_cents + ? "
                     "WHERE id = ? AND store_credit_cents + ? >= 0", (cents, user["id"], cents))
    db.commit()
    if cur.rowcount != 1:
        flash("That would make the credit negative. Nothing was changed.", "error")
        return redirect(url_for("admin.manage_users"))
    new_credit = user["store_credit_cents"] + cents
    log_audit("admin_credit_adjusted",
              f"user={user['username']} credit_cents: {user['store_credit_cents']} -> {new_credit} "
              f"reason={reason}")
    flash(f"Credit of {user['username']} is now ${new_credit / 100:,.2f}.", "success")
    return redirect(url_for("admin.manage_users"))


# ---------------------------------------------------------------------------
# Products (no hard delete - order history links to them)
# ---------------------------------------------------------------------------

def read_product_form():
    """Return (values, errors). Too long or bad values are rejected, never cut."""
    values = {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
        "category": request.form.get("category", "").strip(),
        "price": request.form.get("price", "").strip(),
        "stock": request.form.get("stock", "").strip(),
    }
    errors = []
    if not 1 <= len(values["name"]) <= config.MAX_PRODUCT_NAME_LENGTH:
        errors.append(f"Name must be 1-{config.MAX_PRODUCT_NAME_LENGTH} characters.")
    if len(values["description"]) > config.MAX_PRODUCT_DESCRIPTION_LENGTH:
        errors.append(f"Description must be at most {config.MAX_PRODUCT_DESCRIPTION_LENGTH} characters.")
    if not 1 <= len(values["category"]) <= config.MAX_CATEGORY_LENGTH:
        errors.append(f"Category must be 1-{config.MAX_CATEGORY_LENGTH} characters.")
    # SECURITY: price must be > 0 and stock >= 0 (also CHECKs in schema.sql).
    if not MONEY_PATTERN.fullmatch(values["price"]) or dollars_to_cents(values["price"]) <= 0:
        errors.append("Price must be a number greater than 0, like 19.99.")
    if not WHOLE_NUMBER_PATTERN.fullmatch(values["stock"]):
        errors.append("Stock must be a whole number of 0 or more.")
    return values, errors


@bp.route("/products")
@admin_required
def manage_products():
    products = query_all("SELECT * FROM products ORDER BY id")
    return render_template("admin/products.html", products=products)


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def new_product():
    if request.method == "GET":
        return render_template("admin/product_form.html", values={}, errors=[], product=None)
    values, errors = read_product_form()
    if errors:
        return render_template("admin/product_form.html", values=values, errors=errors,
                               product=None), 400
    db = get_db()
    cur = db.execute("INSERT INTO products (name, description, category, price_cents, stock) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (values["name"], values["description"], values["category"],
                      dollars_to_cents(values["price"]), int(values["stock"])))
    db.commit()
    log_audit("admin_product_created",
              f"product={cur.lastrowid} name={values['name']!r} price_cents={dollars_to_cents(values['price'])}")
    flash(f"Product {values['name']} was added.", "success")
    return redirect(url_for("admin.manage_products"))


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    product = query_one("SELECT * FROM products WHERE id = ?", (product_id,))
    if product is None:
        abort(404)
    if request.method == "GET":
        values = {"name": product["name"], "description": product["description"],
                  "category": product["category"], "price": f"{product['price_cents'] / 100:.2f}",
                  "stock": str(product["stock"])}
        return render_template("admin/product_form.html", values=values, errors=[], product=product)

    values, errors = read_product_form()
    if errors:
        return render_template("admin/product_form.html", values=values, errors=errors,
                               product=product), 400
    new = {"name": values["name"], "description": values["description"],
           "category": values["category"], "price_cents": dollars_to_cents(values["price"]),
           "stock": int(values["stock"])}
    db = get_db()
    db.execute("UPDATE products SET name = ?, description = ?, category = ?, price_cents = ?, "
               "stock = ? WHERE id = ?",
               (new["name"], new["description"], new["category"], new["price_cents"],
                new["stock"], product["id"]))
    db.commit()
    changes = [f"{key}: {product[key]!r} -> {value!r}" for key, value in new.items()
               if product[key] != value]
    log_audit("admin_product_updated", f"product={product['id']} " + "; ".join(changes))
    flash(f"Product {new['name']} was saved.", "success")
    return redirect(url_for("admin.manage_products"))


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@admin_required
def toggle_product(product_id):
    product = query_one("SELECT * FROM products WHERE id = ?", (product_id,))
    if product is None:
        abort(404)
    new_value = 0 if product["is_active"] else 1
    db = get_db()
    db.execute("UPDATE products SET is_active = ? WHERE id = ?", (new_value, product["id"]))
    db.commit()
    log_audit("admin_product_hidden" if new_value == 0 else "admin_product_shown",
              f"product={product['id']} is_active: {product['is_active']} -> {new_value}")
    flash(f"{product['name']} is now {'visible' if new_value else 'hidden'}.", "success")
    return redirect(url_for("admin.manage_products"))


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------

def read_coupon_form(is_new):
    """Return (values for the form, clean values for the database, errors)."""
    form = {key: request.form.get(key, "").strip() for key in
            ("code", "discount_type", "discount_value", "max_discount", "min_total",
             "max_uses", "expires")}
    errors = []
    clean = {"code": form["code"].upper(), "discount_type": form["discount_type"],
             "max_discount_cents": None, "min_total_cents": 0, "max_uses": None,
             "expires_at": None, "discount_value": None}

    if not COUPON_CODE_PATTERN.fullmatch(form["code"]):
        errors.append("Code must be 3-32 characters: letters, numbers, - and _.")
    if form["discount_type"] not in ("percent", "fixed"):
        errors.append("Discount type must be percent or fixed.")
    elif form["discount_type"] == "percent":
        # SECURITY: percent coupons are 1-30% (also a CHECK in schema.sql).
        if (not WHOLE_NUMBER_PATTERN.fullmatch(form["discount_value"])
                or not 1 <= int(form["discount_value"]) <= config.MAX_DISCOUNT_PERCENT):
            errors.append(f"A percent discount must be a whole number from 1 to "
                          f"{config.MAX_DISCOUNT_PERCENT}.")
        else:
            clean["discount_value"] = int(form["discount_value"])
    else:
        if (not MONEY_PATTERN.fullmatch(form["discount_value"])
                or dollars_to_cents(form["discount_value"]) <= 0):
            errors.append("A fixed discount must be an amount greater than 0, like 5 or 7.50.")
        else:
            clean["discount_value"] = dollars_to_cents(form["discount_value"])

    if form["max_discount"]:
        if not MONEY_PATTERN.fullmatch(form["max_discount"]) or dollars_to_cents(form["max_discount"]) <= 0:
            errors.append("Max discount must be an amount greater than 0 (or empty).")
        else:
            clean["max_discount_cents"] = dollars_to_cents(form["max_discount"])
    if form["min_total"]:
        if not MONEY_PATTERN.fullmatch(form["min_total"]):
            errors.append("Minimum cart total must be an amount of 0 or more (or empty).")
        else:
            clean["min_total_cents"] = dollars_to_cents(form["min_total"])
    if form["max_uses"]:
        if not WHOLE_NUMBER_PATTERN.fullmatch(form["max_uses"]) or int(form["max_uses"]) < 1:
            errors.append("Max uses must be a whole number of 1 or more (or empty).")
        else:
            clean["max_uses"] = int(form["max_uses"])
    if form["expires"]:
        try:
            day = datetime.strptime(form["expires"], "%Y-%m-%d")
        except ValueError:
            errors.append("Expiry date must be a real date like 2026-12-31 (or empty).")
        else:
            # valid until the end of that day
            clean["expires_at"] = int(day.replace(hour=23, minute=59, second=59).timestamp())
            if is_new and clean["expires_at"] < time.time():
                errors.append("The expiry date of a new coupon cannot be in the past.")
    return form, clean, errors


@bp.route("/coupons")
@admin_required
def manage_coupons():
    coupons = query_all(
        "SELECT c.*, u.username AS owner_name, "
        "(SELECT COUNT(*) FROM coupon_redemptions r WHERE r.coupon_id = c.id) AS uses "
        "FROM coupons c LEFT JOIN users u ON u.id = c.owner_user_id ORDER BY c.id")
    return render_template("admin/coupons.html", coupons=coupons, now=time.time())


def save_coupon_or_error(sql, params):
    """Run the INSERT/UPDATE; returns an error text if the code already exists."""
    db = get_db()
    try:
        cur = db.execute(sql, params)
        db.commit()
        return cur, None
    except sqlite3.IntegrityError:
        db.rollback()
        return None, "That code already exists (codes are not case-sensitive)."


@bp.route("/coupons/new", methods=["GET", "POST"])
@admin_required
def new_coupon():
    if request.method == "GET":
        return render_template("admin/coupon_form.html", form={"discount_type": "percent"},
                               errors=[], coupon=None)
    form, clean, errors = read_coupon_form(is_new=True)
    cur = None
    if not errors:
        cur, error = save_coupon_or_error(
            "INSERT INTO coupons (code, discount_type, discount_value, max_discount_cents, "
            "min_total_cents, max_uses, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clean["code"], clean["discount_type"], clean["discount_value"],
             clean["max_discount_cents"], clean["min_total_cents"], clean["max_uses"],
             clean["expires_at"]))
        if error:
            errors.append(error)
    if errors:
        return render_template("admin/coupon_form.html", form=form, errors=errors, coupon=None), 400
    log_audit("admin_coupon_created", f"coupon={cur.lastrowid} " +
              "; ".join(f"{key}={value!r}" for key, value in clean.items()))
    flash(f"Coupon {clean['code']} was created.", "success")
    return redirect(url_for("admin.manage_coupons"))


@bp.route("/coupons/<int:coupon_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_coupon(coupon_id):
    coupon = query_one("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
    if coupon is None:
        abort(404)
    if request.method == "GET":
        def money(cents):
            return "" if cents is None else f"{cents / 100:.2f}"
        form = {
            "code": coupon["code"], "discount_type": coupon["discount_type"],
            "discount_value": (str(coupon["discount_value"]) if coupon["discount_type"] == "percent"
                               else money(coupon["discount_value"])),
            "max_discount": money(coupon["max_discount_cents"]),
            "min_total": money(coupon["min_total_cents"]) if coupon["min_total_cents"] else "",
            "max_uses": "" if coupon["max_uses"] is None else str(coupon["max_uses"]),
            "expires": ("" if coupon["expires_at"] is None
                        else datetime.fromtimestamp(coupon["expires_at"]).strftime("%Y-%m-%d")),
        }
        return render_template("admin/coupon_form.html", form=form, errors=[], coupon=coupon)

    form, clean, errors = read_coupon_form(is_new=False)
    if not errors:
        cur, error = save_coupon_or_error(
            "UPDATE coupons SET code = ?, discount_type = ?, discount_value = ?, "
            "max_discount_cents = ?, min_total_cents = ?, max_uses = ?, expires_at = ? WHERE id = ?",
            (clean["code"], clean["discount_type"], clean["discount_value"],
             clean["max_discount_cents"], clean["min_total_cents"], clean["max_uses"],
             clean["expires_at"], coupon["id"]))
        if error:
            errors.append(error)
    if errors:
        return render_template("admin/coupon_form.html", form=form, errors=errors, coupon=coupon), 400
    changes = [f"{key}: {coupon[key]!r} -> {value!r}" for key, value in clean.items()
               if coupon[key] != value]
    log_audit("admin_coupon_updated", f"coupon={coupon['id']} " + "; ".join(changes))
    flash(f"Coupon {clean['code']} was saved.", "success")
    return redirect(url_for("admin.manage_coupons"))


@bp.route("/coupons/<int:coupon_id>/toggle", methods=["POST"])
@admin_required
def toggle_coupon(coupon_id):
    coupon = query_one("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
    if coupon is None:
        abort(404)
    new_value = 0 if coupon["is_active"] else 1
    db = get_db()
    db.execute("UPDATE coupons SET is_active = ? WHERE id = ?", (new_value, coupon["id"]))
    db.commit()
    log_audit("admin_coupon_deactivated" if new_value == 0 else "admin_coupon_activated",
              f"coupon={coupon['id']} is_active: {coupon['is_active']} -> {new_value}")
    flash(f"Coupon {coupon['code']} is now {'active' if new_value else 'inactive'}.", "success")
    return redirect(url_for("admin.manage_coupons"))


# ---------------------------------------------------------------------------
# Audit log (read only)
# ---------------------------------------------------------------------------

@bp.route("/audit")
@admin_required
def audit_log():
    actions = [row["action"] for row in
               query_all("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    action = request.args.get("action", "")
    if action not in actions:
        action = ""                    # unknown filter value is ignored
    sql = ("SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id = a.user_id ")
    params = []
    if action:
        sql += "WHERE a.action = ? "
        params.append(action)
    sql += "ORDER BY a.id DESC LIMIT 200"
    rows = query_all(sql, params)
    return render_template("admin/audit.html", rows=rows, actions=actions, action=action)
