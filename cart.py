"""Shopping cart: view, add, change quantity, remove.
Owner: Member 3

The cart lives in the session as {"product_id": quantity}, for example
{"3": 2, "6": 1}. (Session keys are always text, so the id is stored as text.)

SECURITY (Lab 1): the cart NEVER stores prices or totals. Prices and totals
are read from the products table EVERY time the cart is shown, and again at
checkout. If the browser sends a "price" or "total" field we simply never read it.
"""
import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

import config
from db import query_one
from security import login_required

bp = Blueprint("cart", __name__, url_prefix="/cart")

# Only plain digits: no minus sign, no decimals, no spaces, no "1e3".
# 1-2 digits is enough for 1..10, and it stops huge numbers like 99999999999999999999.
QUANTITY_PATTERN = re.compile(r"\d{1,2}")
PRODUCT_ID_PATTERN = re.compile(r"\d{1,9}")

QUANTITY_ERROR = f"Quantity must be a whole number from 1 to {config.MAX_QUANTITY_PER_ITEM}."


def parse_quantity(text):
    """Return (quantity, None) or (None, error message)."""
    if not QUANTITY_PATTERN.fullmatch(text):
        return None, QUANTITY_ERROR
    quantity = int(text)
    if quantity < 1 or quantity > config.MAX_QUANTITY_PER_ITEM:
        return None, QUANTITY_ERROR
    return quantity, None


def find_active_product(text):
    """Look up the product from a form value. Returns the row or None."""
    if not PRODUCT_ID_PATTERN.fullmatch(text):
        return None
    return query_one(
        "SELECT id, name, price_cents, stock FROM products WHERE id = ? AND is_active = 1",
        (int(text),),
    )


def get_cart():
    """A copy of the cart from the session: {"product_id": quantity}."""
    return dict(session.get("cart", {}))


def save_cart(cart):
    session["cart"] = cart


def load_cart_lines():
    """Build the cart from the DATABASE. Returns (lines, subtotal_cents).

    Every line gets its price from the products table right now.
    Products that are gone or hidden are removed from the cart; if there is
    less stock than the quantity, the quantity is lowered. In both cases the
    user sees a message. orders.py (checkout) uses this function too.
    """
    cart = get_cart()
    lines = []
    subtotal = 0
    changed = False
    for product_id, quantity in list(cart.items()):
        product = query_one(
            "SELECT id, name, price_cents, stock, is_active FROM products WHERE id = ?",
            (int(product_id),),
        )
        if product is None or product["is_active"] != 1:
            del cart[product_id]
            changed = True
            name = product["name"] if product else "A product"
            flash(f"{name} is no longer available and was removed from your cart.", "info")
            continue
        if quantity > product["stock"]:
            changed = True
            if product["stock"] == 0:
                del cart[product_id]
                flash(f"{product['name']} is out of stock and was removed from your cart.", "info")
                continue
            quantity = product["stock"]
            cart[product_id] = quantity
            flash(f"Only {quantity} of {product['name']} left - your quantity was changed.", "info")
        line_total = product["price_cents"] * quantity
        lines.append({
            "product_id": product["id"],
            "name": product["name"],
            "unit_price_cents": product["price_cents"],
            "quantity": quantity,
            "line_total_cents": line_total,
            "max_quantity": min(config.MAX_QUANTITY_PER_ITEM, product["stock"]),
        })
        subtotal += line_total
    if changed:
        save_cart(cart)
    return lines, subtotal


@bp.route("/")
@login_required
def view_cart():
    # Imported here (not at the top) because coupons.py also imports cart.py.
    from coupons import check_coupon

    lines, subtotal = load_cart_lines()

    # The session only holds the coupon CODE. The discount is worked out
    # again now, from the database, with the current cart total.
    coupon_code = session.get("coupon_code")
    discount = 0
    if coupon_code:
        coupon, discount, error = check_coupon(g.user["id"], coupon_code, subtotal)
        if error:
            session.pop("coupon_code", None)
            discount = 0
            coupon_code = None
            flash(f"Your coupon was removed: {error}", "info")

    return render_template("cart/cart.html", lines=lines, subtotal=subtotal,
                           discount=discount, total=subtotal - discount,
                           coupon_code=coupon_code)


@bp.route("/add", methods=["POST"])
@login_required
def add_to_cart():
    # SECURITY (Lab 1): we read ONLY product_id and quantity.
    # A "price" or "total" field added in Burp is never looked at.
    product = find_active_product(request.form.get("product_id", ""))
    if product is None:
        flash("That product does not exist.", "error")
        return redirect(url_for("catalog.product_list"))
    back = url_for("catalog.product_detail", product_id=product["id"])

    quantity, error = parse_quantity(request.form.get("quantity", ""))
    if error:
        flash(error, "error")
        return redirect(back)

    cart = get_cart()
    new_quantity = cart.get(str(product["id"]), 0) + quantity
    if new_quantity > config.MAX_QUANTITY_PER_ITEM:
        flash(f"You can have at most {config.MAX_QUANTITY_PER_ITEM} of one product in your cart.",
              "error")
        return redirect(back)
    if new_quantity > product["stock"]:
        flash(f"Sorry, only {product['stock']} in stock.", "error")
        return redirect(back)

    cart[str(product["id"])] = new_quantity
    save_cart(cart)
    flash(f"Added {quantity} x {product['name']} to your cart.", "success")
    return redirect(url_for("cart.view_cart"))


@bp.route("/update", methods=["POST"])
@login_required
def update_quantity():
    cart = get_cart()
    product = find_active_product(request.form.get("product_id", ""))
    if product is None or str(product["id"]) not in cart:
        flash("That product is not in your cart.", "error")
        return redirect(url_for("cart.view_cart"))

    quantity, error = parse_quantity(request.form.get("quantity", ""))
    if error:
        flash(error + " To remove a product, use Remove.", "error")
        return redirect(url_for("cart.view_cart"))
    if quantity > product["stock"]:
        flash(f"Sorry, only {product['stock']} of {product['name']} in stock.", "error")
        return redirect(url_for("cart.view_cart"))

    cart[str(product["id"])] = quantity
    save_cart(cart)
    flash(f"Quantity of {product['name']} changed to {quantity}.", "success")
    return redirect(url_for("cart.view_cart"))


@bp.route("/remove", methods=["POST"])
@login_required
def remove_from_cart():
    cart = get_cart()
    product_id = request.form.get("product_id", "")
    # Only remove a key that is really in the cart (no other effect possible).
    if product_id in cart:
        del cart[product_id]
        save_cart(cart)
        flash("The product was removed from your cart.", "success")
    else:
        flash("That product is not in your cart.", "error")
    return redirect(url_for("cart.view_cart"))
