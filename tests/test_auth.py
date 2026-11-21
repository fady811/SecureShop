"""Tests for auth.py (Member 1).

Run from the SecureShop folder:
    python -m unittest discover tests -v

Every test uses its own empty database and outbox in a temporary folder,
so secureshop.db is never touched.
"""
import os
import re
import shutil
import sqlite3
import tempfile
import time
import unittest

import pyotp
from argon2 import PasswordHasher

import config
from app import app

ph = PasswordHasher()
GOOD_PASSWORD = "Correct-Horse-42"


class AuthTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.outbox = os.path.join(self.tmp, "outbox")
        app.config["DATABASE"] = self.db_path
        app.config["OUTBOX_DIR"] = self.outbox
        app.config["TESTING"] = True
        with open(config.SCHEMA_FILE, encoding="utf-8") as f:
            self.sql(f.read(), script=True)
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    # ---- helpers ----

    def sql(self, query, params=(), script=False):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        if script:
            db.executescript(query)
            rows = []
        else:
            rows = db.execute(query, params).fetchall()
        db.commit()
        db.close()
        return rows

    def make_user(self, username="alice", role="user", confirmed=1, totp_secret=None):
        self.sql("INSERT INTO users (username, email, password_hash, role, is_confirmed, totp_secret) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (username, f"{username}@example.com", ph.hash(GOOD_PASSWORD), role, confirmed,
                  totp_secret))
        return self.sql("SELECT * FROM users WHERE username = ?", (username,))[0]

    def user(self, username):
        rows = self.sql("SELECT * FROM users WHERE username = ?", (username,))
        return rows[0] if rows else None

    def register(self, username="bob", email="bob@example.com", password=GOOD_PASSWORD,
                 confirm=None, **extra):
        data = {"username": username, "email": email, "password": password,
                "confirm_password": password if confirm is None else confirm}
        data.update(extra)
        return self.client.post("/auth/register", data=data)

    def login(self, username="alice", password=GOOD_PASSWORD):
        return self.client.post("/auth/login", data={"username": username, "password": password})

    def link_from_outbox(self, kind):
        """Return the path of the newest confirm/reset link in the outbox."""
        files = sorted(os.listdir(self.outbox))
        for name in reversed(files):
            with open(os.path.join(self.outbox, name), encoding="utf-8") as f:
                match = re.search(r"(/auth/" + kind + r"/\S+)", f.read())
            if match:
                return match.group(1)
        self.fail("no link found in outbox")

    def audit_actions(self):
        return [row["action"] for row in self.sql("SELECT action FROM audit_log ORDER BY id")]

    def logged_in_user_id(self):
        with self.client.session_transaction() as sess:
            return sess.get("user_id")

    # ---- 1. Registration ----

    def test_weak_password_rejected(self):
        response = self.register(password="password123")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"too common", response.data)
        self.assertIsNone(self.user("bob"))

    def test_short_password_rejected(self):
        response = self.register(password="Short-1")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"at least 10 characters", response.data)
        self.assertIsNone(self.user("bob"))

    def test_too_long_username_rejected_not_cut(self):
        long_name = "a" * 31
        response = self.register(username=long_name)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"3-30 characters", response.data)
        # Not saved, and also not saved cut down to 30 characters
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM users")[0]["n"], 0)

    def test_too_long_email_rejected(self):
        email = "a" * 250 + "@example.com"
        response = self.register(email=email)
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.user("bob"))

    def test_bad_username_characters_rejected(self):
        response = self.register(username="bob<script>")
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.user("bob<script>"))

    def test_register_always_creates_unconfirmed_normal_user(self):
        # Extra "role" field is ignored (no mass assignment)
        response = self.register(role="admin", is_confirmed="1")
        self.assertEqual(response.status_code, 302)
        bob = self.user("bob")
        self.assertEqual(bob["role"], "user")
        self.assertEqual(bob["is_confirmed"], 0)
        self.assertEqual(bob["store_credit_cents"], config.STARTING_CREDIT_CENTS)
        self.assertTrue(bob["password_hash"].startswith("$argon2id$"))
        self.assertIn("register", self.audit_actions())

    # ---- 2. Email confirmation ----

    def test_confirm_link_works_once(self):
        self.register()
        link = self.link_from_outbox("confirm")
        self.assertEqual(self.client.get(link).status_code, 200)
        self.assertEqual(self.user("bob")["is_confirmed"], 1)
        self.assertEqual(self.client.get(link).status_code, 400)      # second time refused
        self.assertIn("email_confirmed", self.audit_actions())

    def test_confirm_link_expires(self):
        self.register()
        link = self.link_from_outbox("confirm")
        self.sql("UPDATE email_confirm_tokens SET expires_at = ?", (int(time.time()) - 1,))
        self.assertEqual(self.client.get(link).status_code, 400)
        self.assertEqual(self.user("bob")["is_confirmed"], 0)

    # ---- 3. Login ----

    def test_generic_login_error(self):
        self.make_user("alice")
        unknown = self.login("nobody", GOOD_PASSWORD)
        wrong = self.login("alice", "Wrong-Password-1")
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertIn(b"Invalid username or password.", unknown.data)
        self.assertIn(b"Invalid username or password.", wrong.data)

    def test_login_success_stores_only_user_id(self):
        alice = self.make_user("alice")
        response = self.login()
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            # Keys starting with "_" belong to Flask (flash messages, lifetime)
            our_keys = {k: v for k, v in sess.items() if not k.startswith("_")}
            # Only ids and flags - no role, no username, no password
            self.assertEqual(our_keys, {"user_id": alice["id"], "session_version": 0,
                                        "mfa_done": False})
        self.assertIn("login_success", self.audit_actions())

    def test_account_locked_after_5_failures(self):
        self.make_user("alice")
        for _ in range(5):
            self.login("alice", "Wrong-Password-1")
        alice = self.user("alice")
        self.assertGreater(alice["locked_until"], time.time())
        self.assertIn("account_locked", self.audit_actions())

        # Even the correct password does not work while locked, same message
        response = self.login()
        self.assertIn(b"Invalid username or password.", response.data)
        self.assertIsNone(self.logged_in_user_id())

        # When the lock is over, the correct password works and counters reset
        self.sql("UPDATE users SET locked_until = ?", (int(time.time()) - 1,))
        self.login()
        self.assertEqual(self.logged_in_user_id(), alice["id"])
        alice = self.user("alice")
        self.assertEqual((alice["failed_login_count"], alice["lock_count"]), (0, 0))

    def test_lock_time_doubles(self):
        self.make_user("alice")
        for _ in range(5):
            self.login("alice", "Wrong-Password-1")
        first = self.user("alice")["locked_until"] - time.time()
        self.sql("UPDATE users SET locked_until = 0")          # pretend the lock ended
        for _ in range(5):
            self.login("alice", "Wrong-Password-1")
        second = self.user("alice")["locked_until"] - time.time()
        self.assertAlmostEqual(first, 60, delta=5)
        self.assertAlmostEqual(second, 120, delta=5)

    def test_lock_time_has_a_maximum(self):
        self.make_user("alice")
        self.sql("UPDATE users SET lock_count = 20")
        for _ in range(5):
            self.login("alice", "Wrong-Password-1")
        self.assertLessEqual(self.user("alice")["locked_until"] - time.time(), 30 * 60)

    def test_unconfirmed_account_cannot_log_in(self):
        self.make_user("alice", confirmed=0)
        response = self.login()
        self.assertIn(b"Invalid username or password.", response.data)
        self.assertIsNone(self.logged_in_user_id())

    # ---- 4. Admin 2FA ----

    def make_admin(self):
        secret = pyotp.random_base32()
        admin = self.make_user("boss", role="admin", totp_secret=secret)
        return admin, pyotp.TOTP(secret)

    def test_admin_needs_2fa(self):
        admin, totp = self.make_admin()
        response = self.login("boss")
        self.assertTrue(response.headers["Location"].endswith("/auth/two-factor"))
        # Password alone is not a login: no user_id, admin pages refused
        self.assertIsNone(self.logged_in_user_id())
        self.assertEqual(self.client.get("/admin/").status_code, 302)

        response = self.client.post("/auth/two-factor", data={"code": totp.now()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.logged_in_user_id(), admin["id"])
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_2fa_page_needs_password_step(self):
        self.make_admin()
        response = self.client.post("/auth/two-factor", data={"code": "123456", "user_id": "1"})
        self.assertTrue(response.headers["Location"].endswith("/auth/login"))
        self.assertIsNone(self.logged_in_user_id())

    def test_totp_code_cannot_be_reused(self):
        admin, totp = self.make_admin()
        code = totp.now()
        self.login("boss")
        self.client.post("/auth/two-factor", data={"code": code})
        self.assertEqual(self.logged_in_user_id(), admin["id"])
        self.client.post("/auth/logout")

        self.login("boss")
        response = self.client.post("/auth/two-factor", data={"code": code})
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(self.logged_in_user_id())
        self.assertIn("2fa_failed", self.audit_actions())

    def test_5_wrong_codes_cancel_the_login(self):
        self.make_admin()
        self.login("boss")
        for _ in range(4):
            self.assertEqual(self.client.post("/auth/two-factor", data={"code": "000000"}).status_code, 401)
        response = self.client.post("/auth/two-factor", data={"code": "000000"})
        self.assertTrue(response.headers["Location"].endswith("/auth/login"))
        with self.client.session_transaction() as sess:
            self.assertNotIn("pending_2fa_user_id", sess)
        self.assertGreater(self.user("boss")["locked_until"], time.time())

    # ---- 5. Logout ----

    def test_logout_is_post_only_and_clears_session(self):
        self.make_user("alice")
        self.login()
        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        self.assertIsNotNone(self.logged_in_user_id())
        self.client.post("/auth/logout")
        self.assertIsNone(self.logged_in_user_id())
        self.assertIn("logout", self.audit_actions())

    # ---- 6. Forgot / reset password ----

    def test_forgot_password_same_message(self):
        self.make_user("alice")
        known = self.client.post("/auth/forgot-password", data={"email": "alice@example.com"},
                                 follow_redirects=True)
        unknown = self.client.post("/auth/forgot-password", data={"email": "ghost@example.com"},
                                   follow_redirects=True)
        self.assertIn(b"If the account exists, a reset link was sent.", known.data)
        self.assertIn(b"If the account exists, a reset link was sent.", unknown.data)
        self.assertEqual(len(os.listdir(self.outbox)), 1)       # only the real account got mail

    def test_reset_token_is_single_use(self):
        self.make_user("alice")
        self.sql("UPDATE users SET failed_login_count = 3")
        self.client.post("/auth/forgot-password", data={"email": "alice@example.com"})
        first_link = self.link_from_outbox("reset")
        time.sleep(1.1)        # new outbox file name
        self.client.post("/auth/forgot-password", data={"email": "alice@example.com"})
        link = self.link_from_outbox("reset")
        self.assertNotEqual(first_link, link)

        new_password = "Brand-New-Pass-77"
        data = {"password": new_password, "confirm_password": new_password}
        self.assertEqual(self.client.post(link, data=data).status_code, 302)
        alice = self.user("alice")
        ph.verify(alice["password_hash"], new_password)
        self.assertEqual(alice["failed_login_count"], 0)
        self.assertIn("password_reset", self.audit_actions())

        # Same link again: refused. The older link was deleted: refused.
        self.assertEqual(self.client.post(link, data=data).status_code, 400)
        self.assertEqual(self.client.get(first_link).status_code, 400)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM password_reset_tokens")[0]["n"], 1)

    def test_reset_token_expires(self):
        self.make_user("alice")
        self.client.post("/auth/forgot-password", data={"email": "alice@example.com"})
        link = self.link_from_outbox("reset")
        self.sql("UPDATE password_reset_tokens SET expires_at = ?", (int(time.time()) - 1,))
        response = self.client.post(link, data={"password": "Brand-New-Pass-77",
                                                "confirm_password": "Brand-New-Pass-77"})
        self.assertEqual(response.status_code, 400)
        ph.verify(self.user("alice")["password_hash"], GOOD_PASSWORD)    # unchanged

    def test_reset_rejects_weak_password(self):
        self.make_user("alice")
        self.client.post("/auth/forgot-password", data={"email": "alice@example.com"})
        link = self.link_from_outbox("reset")
        response = self.client.post(link, data={"password": "qwertyuiop",
                                                "confirm_password": "qwertyuiop"})
        self.assertEqual(response.status_code, 400)
        # The token is still unused, so the user can try again
        self.assertEqual(self.client.get(link).status_code, 200)


if __name__ == "__main__":
    unittest.main()
