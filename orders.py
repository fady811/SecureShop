"""Checkout, payment with store credit, order confirmation, order history.
Owner: Member 5

SECURITY rules in this file:
- Lab 1: every price and total is read from the database - at checkout AND
  again inside the payment transaction. Nothing from the browser is trusted.
- Lab 2.1: the coupon is checked again (check_coupon) right before paying,
  and the redemption is recorded only when the payment succeeds.
- Lab 2.3: an order is created ONLY inside pay(), already 'paid'. The
  confirmation page only SHOWS an order; it never creates or changes one.
- IDOR (L2): every order lookup has "AND user_id = ?" and orders are found
  by a random public_id, not by 1, 2, 3 ...
"""
import hmac
import re
import secrets
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from cart import get_cart, load_cart_lines
from coupons import check_coupon
from db import get_db, query_all, query_one
from security import log_audit, login_required

bp = Blueprint("orders", __name__)

PUBLIC_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{10,50}")


class PaymentError(Exception):
    """Raised inside pay() when the order cannot be paid. The message is shown to the user."""


def format_money(cents):
    return f"${cents / 100:,.2f}"


def find_my_order(public_id, paid_only=False):
    """Return the order only if it belongs to the logged-in user, else abort(404).

    SECURITY (IDOR): "AND user_id = ?" uses g.user (from the session). Another
    user's order gives the same 404 as an order that does not exist, so an
    attacker cannot even find out that it exists.
    """
    if not PUBLIC_ID_PATTERN.fullmatch(public_id):
        abort(404)
    sql = "SELECT * FROM orders WHERE public_id = ? AND user_id = ?"
    if paid_only:
        sql += " AND status = 'paid'"
    order = query_one(sql, (public_id, g.user["id"]))
    if order is None:
        abort(404)
    return order


@bp.route("/checkout")
@login_required
def checkout():
    # Rebuilt from the database right now (prices, stock, hidden products).
    lines, subtotal = load_cart_lines()
    if not lines:
        flash("Your cart is empty.", "info")
        return redirect(url_for("cart.view_cart"))

    discount = 0
    coupon_code = session.get("coupon_code")
    if coupon_code:
        coupon, discount, error = check_coupon(g.user["id"], coupon_code, subtotal)
        if error:
            session.pop("coupon_code", None)
            coupon_code, discount = None, 0
            flash(f"Your coupon was removed: {error}", "info")

    # SECURITY: a one-time checkout token. pay() only works with this token
    # and it can create at most ONE order (orders.checkout_token is UNIQUE),
    # so a double click or two tabs cannot pay twice. It also means another
    # website cannot submit the payment form for you (it cannot know the token).
    if "checkout_token" not in session:
        session["checkout_token"] = secrets.token_urlsafe(16)

    total = subtotal - discount
    return render_template("orders/checkout.html", lines=lines, subtotal=subtotal,
                           discount=discount, total=total, coupon_code=coupon_code,
                           credit=g.user["store_credit_cents"],
                           checkout_token=session["checkout_token"])


@bp.route("/checkout/pay", methods=["POST"])
@login_required
def pay():
    # SECURITY (Lab 1): we read ONLY the checkout token from the form.
    # Any "total", "price" or "user_id" field added in Burp is never read.
    token = request.form.get("checkout_token", "")
    expected = session.get("checkout_token", "")
    if not expected or not hmac.compare_digest(token, expected):
        flash("This checkout page is out of date. Please check your order and try again.", "error")
        return redirect(url_for("orders.checkout"))

    user_id = g.user["id"]
    cart = get_cart()
    coupon_code = session.get("coupon_code")
    db = get_db()
    db.commit()                       # make sure no earlier transaction is still open

    try:
        # SECURITY: BEGIN IMMEDIATE locks the database for writing, so two
        # payments at the same moment run one after the other, never mixed.
        db.execute("BEGIN IMMEDIATE")

        # Double click / second tab: this checkout already made an order.
        done = db.execute("SELECT public_id FROM orders WHERE checkout_token = ?",
                          (token,)).fetchone()
        if done:
            db.rollback()
            session.pop("cart", None)
            session.pop("coupon_code", None)
            session.pop("checkout_token", None)
            flash("This order was already paid. You were charged only once.", "info")
            return redirect(url_for("orders.order_confirmation", public_id=done["public_id"]))

        if not cart:
            raise PaymentError("Your cart is empty.")

        # 1. Recalculate everything again, inside the transaction.
        items = []
        subtotal = 0
        for product_id, quantity in cart.items():
            product = db.execute(
                "SELECT id, name, price_cents, stock, is_active FROM products WHERE id = ?",
                (int(product_id),)).fetchone()
            if product is None or product["is_active"] != 1:
                raise PaymentError("A product in your cart is no longer available.")
            if quantity > product["stock"]:
                raise PaymentError(f"Not enough stock for {product['name']}.")
            items.append((product, quantity))
            subtotal += product["price_cents"] * quantity

        # 2. Re-check the coupon (it may have expired or been used meanwhile).
        coupon, discount = None, 0
        if coupon_code:
            coupon, discount, error = check_coupon(user_id, coupon_code, subtotal)
            if error:
                session.pop("coupon_code", None)
                raise PaymentError(f"Your coupon can no longer be used: {error}")
        total = subtotal - discount

        # 3. Take the credit. SECURITY: "AND store_credit_cents >= ?" means the
        # UPDATE changes nothing when the credit is too low - credit can never
        # go below zero (and the CHECK in schema.sql is a second safety net).
        cur = db.execute(
            "UPDATE users SET store_credit_cents = store_credit_cents - ? "
            "WHERE id = ? AND store_credit_cents >= ?",
            (total, user_id, total))
        if cur.rowcount != 1:
            raise PaymentError(f"Not enough store credit. This order costs {format_money(total)}.")

        # 4. Lower the stock (same idea: never below zero).
        for product, quantity in items:
            cur = db.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                             (quantity, product["id"], quantity))
            if cur.rowcount != 1:
                raise PaymentError(f"Not enough stock for {product['name']}.")

        # 5. Create the order - already 'paid', because the money was taken above.
        public_id = secrets.token_urlsafe(12)
        cur = db.execute(
            "INSERT INTO orders (public_id, checkout_token, user_id, status, subtotal_cents, "
            "discount_cents, total_cents, coupon_id, paid_at) "
            "VALUES (?, ?, ?, 'paid', ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (public_id, token, user_id, subtotal, discount, total,
             coupon["id"] if coupon else None))
        order_id = cur.lastrowid

        # 6. Save the items with the price from the database at this moment.
        for product, quantity in items:
            db.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, "
                "quantity) VALUES (?, ?, ?, ?, ?)",
                (order_id, product["id"], product["name"], product["price_cents"], quantity))

        # 7. Record the coupon use. UNIQUE(coupon_id, user_id) makes a second
        # use impossible even if a check above was somehow skipped.
        if coupon:
            db.execute("INSERT INTO coupon_redemptions (coupon_id, user_id, order_id) "
                       "VALUES (?, ?, ?)", (coupon["id"], user_id, order_id))

        db.commit()
    except PaymentError as error:
        db.rollback()                 # SECURITY: nothing is half-done
        log_audit("payment_refused", str(error))
        flash(str(error), "error")
        return redirect(url_for("orders.checkout"))
    except sqlite3.IntegrityError:
        # A database rule (CHECK / UNIQUE) refused something - fail secure.
        db.rollback()
        log_audit("payment_refused", "database rule refused the order")
        flash("The payment could not be completed. Nothing was charged.", "error")
        return redirect(url_for("orders.checkout"))

    # Only now, after the commit: log it and empty the cart.
    log_audit("order_placed", f"order={public_id} total_cents={total} discount_cents={discount}")
    if coupon:
        log_audit("coupon_redeemed", f"coupon_id={coupon['id']} order={public_id}")
    session.pop("cart", None)
    session.pop("coupon_code", None)
    session.pop("checkout_token", None)
    flash("Thank you! Your order is paid.", "success")
    return redirect(url_for("orders.order_confirmation", public_id=public_id))


@bp.route("/orders")
@login_required
def order_history():
    # SECURITY (IDOR): only the logged-in user's orders.
    orders = query_all(
        "SELECT public_id, status, total_cents, created_at FROM orders "
        "WHERE user_id = ? ORDER BY id DESC", (g.user["id"],))
    return render_template("orders/history.html", orders=orders)


@bp.route("/orders/<public_id>")
@login_required
def order_detail(public_id):
    order = find_my_order(public_id)
    items = query_all("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order["id"],))
    return render_template("orders/detail.html", order=order, items=items, confirmation=False)


@bp.route("/orders/<public_id>/confirmation")
@login_required
def order_confirmation(public_id):
    # SECURITY (Lab 2.3): this page only READS. It needs an order that
    # belongs to you AND is 'paid'. Opening it again (or with another id)
    # never creates or changes an order.
    order = find_my_order(public_id, paid_only=True)
    items = query_all("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order["id"],))
    return render_template("orders/detail.html", order=order, items=items, confirmation=True)
