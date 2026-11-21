"""SecureShop - main application file.

Run with:   flask run
(Run `python seed.py` first to create the database.)
"""
import os
from datetime import timedelta

from flask import Flask, g, render_template, session

import config
from db import close_db
from security import load_logged_in_user

from auth import bp as auth_bp
from catalog import bp as catalog_bp
from cart import bp as cart_bp
from coupons import bp as coupons_bp
from orders import bp as orders_bp
from account import bp as account_bp
from admin import bp as admin_bp

app = Flask(__name__)
app.config.from_object(config)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=config.SESSION_LIFETIME_MINUTES)

# Make sure the fake email folder exists
os.makedirs(config.OUTBOX_DIR, exist_ok=True)

# Database connection is closed after every request
app.teardown_appcontext(close_db)

# Load the logged-in user (if any) before every request
app.before_request(load_logged_in_user)

# One blueprint per feature (one file per team member)
app.register_blueprint(auth_bp)       # Member 1
app.register_blueprint(catalog_bp)    # Member 2
app.register_blueprint(cart_bp)       # Member 3
app.register_blueprint(coupons_bp)    # Member 4
app.register_blueprint(orders_bp)     # Member 5
app.register_blueprint(account_bp)    # Member 6
app.register_blueprint(admin_bp)      # Member 6


@app.template_filter("money")
def money(cents):
    """Show cents as dollars in templates: {{ 133700|money }} -> $1,337.00"""
    return f"${cents / 100:,.2f}"


@app.context_processor
def cart_count():
    """Number of items in the cart, shown in the menu on every page."""
    return {"cart_count": sum(session.get("cart", {}).values()) if g.get("user") else 0}


@app.route("/")
def index():
    return render_template("index.html")


# SECURITY: fail secure - friendly error pages, never a stack trace.
ERROR_MESSAGES = {
    400: "The request was not valid. Please check what you entered.",
    403: "You do not have permission to open this page.",
    404: "We could not find that page.",
    405: "That action is not allowed here.",
    413: "What you sent is too large.",
    500: "Something went wrong on our side. Please try again later.",
}


def render_error(error):
    code = getattr(error, "code", 500) or 500
    message = ERROR_MESSAGES.get(code, ERROR_MESSAGES[500])
    return render_template("error.html", code=code, message=message), code


for error_code in ERROR_MESSAGES:
    app.register_error_handler(error_code, render_error)


if __name__ == "__main__":
    app.run()
