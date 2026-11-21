"""Create naive_demo/naive.db for the VULNERABLE demo app (class demo only).

Run:  python naive_demo/seed_naive.py
"""
import hashlib
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(HERE, "naive.db")

SCHEMA = """
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS coupons;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS reset_tokens;
-- VULNERABLE: no CHECK constraints anywhere (credit can go negative, etc.)
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT, password_md5 TEXT,
                    role TEXT, credit_cents INTEGER, twofa_code TEXT);
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price_cents INTEGER);
CREATE TABLE coupons (code TEXT, percent INTEGER);
CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, total_cents INTEGER, status TEXT, items TEXT);
CREATE TABLE reset_tokens (token TEXT, user_id INTEGER);
"""


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def main():
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA)
    # Same usernames as SecureShop. The naive shop has no password rules, so
    # "shopper" chose a weak password here.
    db.executemany("INSERT INTO users (username, email, password_md5, role, credit_cents) VALUES (?, ?, ?, ?, ?)", [
        ("shopper", "user@secureshop.test", md5("sunshine123"), "user", 10000),
        ("admin", "admin@secureshop.test", md5("Admin-Pass-2026!"), "admin", 0),
        ("victim", "victim@secureshop.test", md5("Victim-Pass-2026"), "user", 5000),
    ])
    db.executemany("INSERT INTO products (name, price_cents) VALUES (?, ?)", [
        ("Classic White T-Shirt", 1500), ("Lightweight Leather Jacket", 133700),
        ("Running Shoes", 5999), ("Canvas Backpack", 3450), ("Stainless Water Bottle", 1299),
        ("Wireless Earbuds", 4999), ("USB-C Charger 30W", 1999), ("Notebook (A5, dotted)", 650),
    ])
    db.executemany("INSERT INTO coupons VALUES (?, ?)", [("WELCOME5", 5), ("SAVE20", 20)])
    # One order of the victim, for the IDOR demo
    db.execute("INSERT INTO orders (user_id, total_cents, status, items) "
               "VALUES (3, 1500, 'paid', '1 x Classic White T-Shirt')")
    db.commit()
    db.close()
    print(f"Created {DATABASE}")
    print("Accounts: shopper / sunshine123, admin / Admin-Pass-2026!, victim / Victim-Pass-2026")


if __name__ == "__main__":
    main()
