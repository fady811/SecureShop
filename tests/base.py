"""Shared setup for the catalog, cart, coupon, order, account and admin tests.

Each test gets its own empty database and outbox in a temporary folder,
so secureshop.db is never touched.
"""
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import config
from app import app


class BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.outbox = os.path.join(self.tmp, "outbox")
        app.config["DATABASE"] = self.db_path
        app.config["OUTBOX_DIR"] = self.outbox
        app.config["TESTING"] = True
        with open(config.SCHEMA_FILE, encoding="utf-8") as f:
            db = sqlite3.connect(self.db_path)
            db.executescript(f.read())
            db.close()
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sql(self, query, params=()):
        """Run one query on the test database and return all rows."""
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        rows = db.execute(query, params).fetchall()
        db.commit()
        db.close()
        return rows

    def insert(self, query, params=()):
        """Run one INSERT and return the new row id."""
        db = sqlite3.connect(self.db_path)
        new_id = db.execute(query, params).lastrowid
        db.commit()
        db.close()
        return new_id

    def make_user(self, username="alice", confirmed=1, role="user", credit_cents=0,
                  password_hash="not-used"):
        # Most tests log in through the session, so the hash is often not needed.
        return self.insert("INSERT INTO users (username, email, password_hash, is_confirmed, "
                           "role, store_credit_cents) VALUES (?, ?, ?, ?, ?, ?)",
                           (username, f"{username}@example.com", password_hash, confirmed,
                            role, credit_cents))

    def log_in(self, user_id, mfa_done=False):
        """Pretend the user logged in (auth.py is tested in test_auth.py).
        Sets the same session keys as auth.finish_login()."""
        version = self.sql("SELECT session_version FROM users WHERE id = ?", (user_id,))[0][0]
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = user_id
            sess["session_version"] = version
            sess["mfa_done"] = mfa_done

    def make_product(self, name="Jacket", price_cents=10000, stock=20, category="Clothing",
                     active=1):
        return self.insert("INSERT INTO products (name, category, price_cents, stock, is_active) "
                        "VALUES (?, ?, ?, ?, ?)", (name, category, price_cents, stock, active))

    def make_coupon(self, code, discount_type="percent", value=10, max_discount_cents=None,
                    min_total_cents=0, max_uses=None, active=1, expires_at=None, owner=None):
        return self.insert(
            "INSERT INTO coupons (code, discount_type, discount_value, max_discount_cents, "
            "min_total_cents, max_uses, is_active, expires_at, owner_user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (code, discount_type, value, max_discount_cents, min_total_cents, max_uses,
             active, expires_at, owner))

    def session_value(self, key):
        with self.client.session_transaction() as sess:
            return sess.get(key)

    def audit_actions(self):
        return [row["action"] for row in self.sql("SELECT action FROM audit_log ORDER BY id")]

    def count(self, table):
        # table is a fixed name written in the test, never user input
        return self.sql("SELECT COUNT(*) AS n FROM " + table)[0]["n"]

    def now(self):
        return int(time.time())
