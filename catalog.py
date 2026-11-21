"""Product catalogue: list, search/filter/sort, detail page.
Owner: Member 2

Rules followed in this file:
- Every query uses "?" placeholders - also the search text.
- Only active products (is_active = 1) are ever shown.
- Bad input is rejected with a friendly message, never "fixed" silently.
"""
import re

from flask import Blueprint, abort, render_template, request

import config
from db import query_all, query_one

bp = Blueprint("catalog", __name__, url_prefix="/products")

# SECURITY: ORDER BY cannot use a "?" placeholder (placeholders are only for
# VALUES, not for column names or ASC/DESC). So the user never gives us SQL:
# they give us a KEY, and we look up the matching SQL text in this fixed
# allow-list. Anything that is not a key here is ignored and the default
# sort is used, e.g. ?sort=price;DROP TABLE users just sorts by name.
SORT_OPTIONS = {
    "name": ("Name (A-Z)", "name ASC"),
    "price_asc": ("Price (low to high)", "price_cents ASC, name ASC"),
    "price_desc": ("Price (high to low)", "price_cents DESC, name ASC"),
}
DEFAULT_SORT = "name"

# Price in dollars: up to 7 digits, optional 1-2 decimals ("10", "10.5", "10.50").
# No minus sign, no "1e5", no "nan" - so the value is always a valid, non-negative number.
PRICE_PATTERN = re.compile(r"\d{1,7}(\.\d{1,2})?")


def parse_price(text, label):
    """Turn "12.50" into 1250 cents. Returns (cents or None, error or None)."""
    if text == "":
        return None, None                        # filter not used
    if not PRICE_PATTERN.fullmatch(text):
        return None, f"{label} must be a number of 0 or more, like 10 or 9.99."
    cents = round(float(text) * 100)
    if cents > config.MAX_PRICE_FILTER_CENTS:
        return None, f"{label} is too large."
    return cents, None


def escape_like(text):
    """Make % and _ in the search text normal characters (not LIKE wildcards).
    This is not about SQL injection ("?" already stops that) - it just makes
    a search for "50%" find "50%" and not everything."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@bp.route("/")
def product_list():
    # .strip() only removes spaces around the text - nothing is cut.
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    min_text = request.args.get("min_price", "").strip()
    max_text = request.args.get("max_price", "").strip()
    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT                      # SECURITY: unknown sort value is ignored

    errors = []
    # SECURITY (Lab 2.2): too long is REJECTED, never cut to fit.
    if len(q) > config.MAX_SEARCH_LENGTH:
        errors.append(f"Search text must be at most {config.MAX_SEARCH_LENGTH} characters.")
    if len(category) > config.MAX_CATEGORY_LENGTH:
        errors.append("Unknown category.")
    min_cents, error = parse_price(min_text, "Minimum price")
    if error:
        errors.append(error)
    max_cents, error = parse_price(max_text, "Maximum price")
    if error:
        errors.append(error)
    if min_cents is not None and max_cents is not None and min_cents > max_cents:
        errors.append("Minimum price cannot be higher than maximum price.")

    categories = [row["category"] for row in query_all(
        "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category")]

    products = []
    if not errors:
        # Build the WHERE part from FIXED pieces of SQL. User input only ever
        # goes into the params list, never into the SQL text.
        sql = "SELECT id, name, category, price_cents, stock FROM products WHERE is_active = 1"
        params = []
        if q:
            # SECURITY (SQL injection): the "%" are added in Python, the text
            # is a parameter. ' OR 1=1 -- is just searched for as a name.
            sql += " AND name LIKE ? ESCAPE '\\'"
            params.append("%" + escape_like(q) + "%")
        if category:
            sql += " AND category = ?"
            params.append(category)
        if min_cents is not None:
            sql += " AND price_cents >= ?"
            params.append(min_cents)
        if max_cents is not None:
            sql += " AND price_cents <= ?"
            params.append(max_cents)
        # Safe: this text comes from our allow-list above, not from the user.
        sql += " ORDER BY " + SORT_OPTIONS[sort][1]
        products = query_all(sql, params)

    # SECURITY (XSS): q is shown back as "Results for ...". Jinja2
    # autoescaping turns <script> into harmless text - never use |safe.
    return render_template(
        "catalog/list.html", products=products, errors=errors, q=q,
        category=category, categories=categories, min_price=min_text,
        max_price=max_text, sort=sort, sort_options=SORT_OPTIONS,
    ), (400 if errors else 200)


@bp.route("/<int:product_id>")
def product_detail(product_id):
    # SECURITY: <int:...> means Flask only calls this for whole numbers;
    # /products/abc or /products/1' OR 1=1 get our custom 404 page.
    product = query_one(
        "SELECT id, name, description, category, price_cents, stock "
        "FROM products WHERE id = ? AND is_active = 1",
        (product_id,),
    )
    if product is None:
        abort(404)            # unknown OR hidden product - same answer
    max_quantity = min(config.MAX_QUANTITY_PER_ITEM, product["stock"])
    return render_template("catalog/detail.html", product=product, max_quantity=max_quantity)
