"""Settings for SecureShop. Every team member reads limits from here,
so the same rule is used everywhere (one max length per field, etc.)."""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# SECURITY: the secret key signs the session cookie. If someone knows it,
# they can forge a session. Set SECRET_KEY in the environment for a real
# deployment. If it is not set we make a random one (users are logged out
# every time the server restarts, which is fine for development).
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# SECURITY (Lab 3 fix): Flask's session is a cookie that is SIGNED with
# SECRET_KEY. The user can read it, but if they change anything inside it
# (for example user_id=1 -> user_id=2) the signature no longer matches and
# Flask throws the whole session away. In Lab 3 the site trusted a plain
# "verify=carlos" cookie that anyone could edit - a signed session fixes that.

DATABASE = os.path.join(BASE_DIR, "secureshop.db")
SCHEMA_FILE = os.path.join(BASE_DIR, "schema.sql")
OUTBOX_DIR = os.path.join(BASE_DIR, "outbox")          # "sent" emails go here
COMMON_PASSWORDS_FILE = os.path.join(BASE_DIR, "common_passwords.txt")

# SECURITY: fail secure - debug mode shows stack traces and an interactive
# console, so it is OFF unless you turn it on yourself.
DEBUG = False

# SECURITY: session cookie settings
SESSION_COOKIE_HTTPONLY = True        # JavaScript cannot read the cookie (limits XSS damage)
SESSION_COOKIE_SAMESITE = "Lax"       # cookie is not sent on most cross-site requests
SESSION_COOKIE_SECURE = False         # set to True when the site runs on HTTPS
SESSION_LIFETIME_MINUTES = 30

# SECURITY: reject very large request bodies instead of processing them
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB

# ---- Input limits (Lab 2.2: reject, never silently cut) ----
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 30              # letters, numbers and underscore only
MAX_EMAIL_LENGTH = 254
MAX_NAME_LENGTH = 100
MAX_ADDRESS_LENGTH = 200
MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_LENGTH = 10
MAX_SEARCH_LENGTH = 100
MAX_COUPON_CODE_LENGTH = 32
MAX_PRODUCT_NAME_LENGTH = 100
MAX_PRODUCT_DESCRIPTION_LENGTH = 2000
MAX_QUANTITY_PER_ITEM = 10            # quantity must be 1..10
MAX_CATEGORY_LENGTH = 50
MAX_PRICE_FILTER_CENTS = 100000000    # $1,000,000 - bigger price filters are refused

# ---- Login protection (Lectures 4-5) ----
# A wrong 2FA code counts as a failed login too, so an admin gets at most
# 5 wrong codes per password login before the account is locked.
LOCKOUT_AFTER_FAILURES = 5            # lock the account after 5 failed logins
LOCKOUT_BASE_SECONDS = 60             # 1 min, then 2, 4, 8 ... (doubles each new lock)
LOCKOUT_MAX_SECONDS = 30 * 60         # never more than 30 minutes
TOTP_PENDING_MINUTES = 5              # time allowed between the password step and the code

# ---- New accounts ----
STARTING_CREDIT_CENTS = 10000         # $100.00 store credit for every new account

# ---- Tokens ----
RESET_TOKEN_MINUTES = 15              # password reset link lifetime
CONFIRM_TOKEN_HOURS = 24              # email confirmation link lifetime

# ---- Coupons (Lab 2.1) ----
MAX_DISCOUNT_PERCENT = 30             # percent coupons are 1-30% (fixed coupons: see coupons.py)
COUPON_MAX_FAILURES = 10              # wrong codes allowed per user ...
COUPON_FAILURE_WINDOW_MINUTES = 10    # ... in this many minutes, then coupons are refused
NEWSLETTER_DISCOUNT_PERCENT = 10      # newsletter coupon: 10% off ...
NEWSLETTER_MAX_DISCOUNT_CENTS = 1000  # ... but at most $10
