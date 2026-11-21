"""Create (or re-create) the SecureShop database with test data.

Run:  python seed.py

WARNING: this deletes all existing data in secureshop.db.
"""
import sqlite3
import time

import pyotp
from argon2 import PasswordHasher

import config

# SECURITY: Argon2id with argon2-cffi's default (OWASP-recommended) settings.
# Each hash gets its own random salt automatically.
ph = PasswordHasher()

# SECURITY: every admin must have a TOTP secret (auth.py refuses an admin
# without one). A new random secret is made each time seed.py runs.
ADMIN_TOTP_SECRET = pyotp.random_base32()

TEST_USER = {"username": "shopper", "email": "user@secureshop.test",
             "password": "Shopper-Pass-2026", "name": "Test User", "role": "user",
             "credit_cents": 10000, "totp_secret": None}                       # $100.00
# Used by attack_scripts/ (brute force, IDOR ...) so the attacks never lock
# or change the two accounts above.
TEST_VICTIM = {"username": "victim", "email": "victim@secureshop.test",
               "password": "Victim-Pass-2026", "name": "Vic Tim", "role": "user",
               "credit_cents": 5000, "totp_secret": None}                      # $50.00
TEST_ADMIN = {"username": "admin", "email": "admin@secureshop.test",
              "password": "Admin-Pass-2026!", "name": "Test Admin", "role": "admin",
              "credit_cents": 0, "totp_secret": ADMIN_TOTP_SECRET}

# (name, description, category, price in cents, stock)
PRODUCTS = [
    ("Classic White T-Shirt", "100% cotton, regular fit.", "Clothing", 1500, 50),
    ("Lightweight Leather Jacket", "Premium leather jacket. Very expensive on purpose.", "Clothing", 133700, 5),
    ("Running Shoes", "Light shoes for daily running.", "Shoes", 5999, 20),
    ("Canvas Backpack", "20 litre backpack with laptop pocket.", "Bags", 3450, 30),
    ("Stainless Water Bottle", "Keeps drinks cold for 24 hours.", "Accessories", 1299, 100),
    ("Wireless Earbuds", "Bluetooth earbuds with charging case.", "Electronics", 4999, 25),
    ("USB-C Charger 30W", "Fast charger for phones and tablets.", "Electronics", 1999, 40),
    ("Notebook (A5, dotted)", "120 pages, hard cover.", "Stationery", 650, 200),
]

# Hidden product (is_active = 0) - for testing that it is never shown or sold
INACTIVE_PRODUCT = ("Old Coffee Mug", "No longer sold.", "Accessories", 900, 10)

DAY = 24 * 60 * 60
now = int(time.time())

# (code, type, value, max discount cents, min cart total cents, max uses, active, expires_at)
# For 'percent' the value is a percent; for 'fixed' it is in cents.
COUPONS = [
    ("WELCOME5", "percent", 5, None, 0, None, 1, None),             # 5%, never expires
    ("SAVE20", "percent", 20, 5000, 5000, None, 1, now + 30 * DAY),  # 20% (max $50) on $50+, 30 days
    ("TENOFF", "fixed", 1000, None, 3000, 100, 1, None),            # $10 off on $30+, 100 uses in total
    ("OLD10", "percent", 10, None, 0, None, 1, now - DAY),          # already expired - for testing
]


def main():
    print(f"Creating database at {config.DATABASE} (old data is deleted) ...")
    db = sqlite3.connect(config.DATABASE)
    db.execute("PRAGMA foreign_keys = ON")

    with open(config.SCHEMA_FILE, encoding="utf-8") as f:
        db.executescript(f.read())

    for account in (TEST_USER, TEST_ADMIN, TEST_VICTIM):
        db.execute(
            "INSERT INTO users (username, email, full_name, password_hash, role, is_confirmed, "
            "store_credit_cents, totp_secret) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (account["username"], account["email"], account["name"], ph.hash(account["password"]),
             account["role"], account["credit_cents"], account["totp_secret"]),
        )

    db.executemany(
        "INSERT INTO products (name, description, category, price_cents, stock) VALUES (?, ?, ?, ?, ?)",
        PRODUCTS,
    )
    db.execute(
        "INSERT INTO products (name, description, category, price_cents, stock, is_active) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        INACTIVE_PRODUCT,
    )
    db.executemany(
        "INSERT INTO coupons (code, discount_type, discount_value, max_discount_cents, "
        "min_total_cents, max_uses, is_active, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        COUPONS,
    )
    db.commit()
    db.close()

    print(f"Inserted 3 users, {len(PRODUCTS)} products (+1 hidden), {len(COUPONS)} coupons.\n")
    print("Test accounts (for development only):")
    for account in (TEST_USER, TEST_ADMIN, TEST_VICTIM):
        print(f"  {account['role']:5}  username: {account['username']:8}  "
              f"email: {account['email']:22}  password: {account['password']:18}  "
              f"credit: ${account['credit_cents'] / 100:.2f}")
    print(f"\nAdmin TOTP secret: {ADMIN_TOTP_SECRET}")
    print("  Add it to an authenticator app (manual entry), or get the current code with:")
    print(f"  python -c \"import pyotp; print(pyotp.TOTP('{ADMIN_TOTP_SECRET}').now())\"")
    print("Coupons: WELCOME5 (5%), SAVE20 (20%, max $50, cart $50+), "
          "TENOFF ($10 off, cart $30+), OLD10 (expired)")


if __name__ == "__main__":
    main()
