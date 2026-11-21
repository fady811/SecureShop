"""Tests for account.py (Member 6) and the session_version defense.
Run: python -m unittest discover tests -v"""
import unittest

from argon2 import PasswordHasher

from base import BaseTestCase

ph = PasswordHasher()
PASSWORD = "Correct-Horse-42"


class AccountTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.alice = self.make_user("alice", credit_cents=10000, password_hash=ph.hash(PASSWORD))
        self.bob = self.make_user("bob", credit_cents=500)

    def real_login(self):
        """Log in through the real login form (so the session is made by auth.py)."""
        self.client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
        self.assertEqual(self.client.get("/account/").status_code, 200)

    def user(self, user_id):
        return self.sql("SELECT * FROM users WHERE id = ?", (user_id,))[0]

    # ---- profile ----

    def test_profile_shows_own_data(self):
        self.log_in(self.alice)
        page = self.client.get("/account/").data
        self.assertIn(b"alice@example.com", page)
        self.assertIn(b"$100.00", page)
        self.assertNotIn(b"bob@example.com", page)

    def test_update_profile(self):
        self.log_in(self.alice)
        self.client.post("/account/edit", data={"full_name": "Alice Smith",
                                                "shipping_address": "1 Main St, Cairo"})
        alice = self.user(self.alice)
        self.assertEqual((alice["full_name"], alice["shipping_address"]), ("Alice Smith", "1 Main St, Cairo"))
        self.assertIn("profile_updated", self.audit_actions())

    def test_too_long_fields_rejected_not_cut(self):
        self.log_in(self.alice)
        response = self.client.post("/account/edit", data={"full_name": "a" * 101, "shipping_address": ""})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/account/edit", data={"full_name": "", "shipping_address": "b" * 201})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.user(self.alice)["full_name"], "")
        self.assertEqual(self.user(self.alice)["shipping_address"], "")

    def test_mass_assignment_ignored(self):
        self.log_in(self.alice)
        self.client.post("/account/edit", data={
            "full_name": "Alice", "shipping_address": "",
            # extra fields an attacker adds in Burp:
            "role": "admin", "store_credit_cents": "99999999", "email": "evil@example.com",
            "user_id": str(self.bob), "is_confirmed": "1", "username": "root"})
        alice = self.user(self.alice)
        self.assertEqual(alice["full_name"], "Alice")
        self.assertEqual((alice["role"], alice["store_credit_cents"], alice["email"], alice["username"]),
                         ("user", 10000, "alice@example.com", "alice"))
        self.assertEqual(self.user(self.bob)["full_name"], "")       # bob untouched

    # ---- password change ----

    def test_change_password_needs_current_password(self):
        self.log_in(self.alice)
        response = self.client.post("/account/password", data={
            "current_password": "wrong-password", "new_password": "Brand-New-Pass-77",
            "confirm_password": "Brand-New-Pass-77"})
        self.assertEqual(response.status_code, 400)
        ph.verify(self.user(self.alice)["password_hash"], PASSWORD)  # unchanged

    def test_change_password_uses_password_rules(self):
        self.log_in(self.alice)
        response = self.client.post("/account/password", data={
            "current_password": PASSWORD, "new_password": "password123",
            "confirm_password": "password123"})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"too common", response.data)

    def test_guessing_current_password_locks_the_account(self):
        self.log_in(self.alice)
        data = {"current_password": "wrong-guess", "new_password": "Brand-New-Pass-77",
                "confirm_password": "Brand-New-Pass-77"}
        for _ in range(4):
            self.assertEqual(self.client.post("/account/password", data=data).status_code, 400)
        response = self.client.post("/account/password", data=data)
        self.assertTrue(response.headers["Location"].endswith("/auth/login"))
        self.assertGreater(self.user(self.alice)["locked_until"], 0)
        self.assertEqual(self.client.get("/account/").status_code, 302)     # session ended

    def test_change_password(self):
        self.log_in(self.alice)
        self.client.post("/account/password", data={
            "current_password": PASSWORD, "new_password": "Brand-New-Pass-77",
            "confirm_password": "Brand-New-Pass-77"})
        alice = self.user(self.alice)
        ph.verify(alice["password_hash"], "Brand-New-Pass-77")
        self.assertEqual(alice["session_version"], 1)
        # this browser stays logged in
        self.assertEqual(self.client.get("/account/").status_code, 200)
        self.assertIn("password_changed", self.audit_actions())

    # ---- old session cookies (session_version) ----

    def test_old_cookie_rejected_after_logout(self):
        self.real_login()
        copied_cookie = self.client.get_cookie("session").value      # attacker copies the cookie
        self.client.post("/auth/logout")
        self.client.set_cookie("session", copied_cookie)             # ... and uses it later
        self.assertEqual(self.client.get("/account/").status_code, 302)

    def test_old_cookie_rejected_after_password_change(self):
        self.real_login()
        copied_cookie = self.client.get_cookie("session").value
        self.client.post("/account/password", data={
            "current_password": PASSWORD, "new_password": "Brand-New-Pass-77",
            "confirm_password": "Brand-New-Pass-77"})
        self.assertEqual(self.client.get("/account/").status_code, 200)   # current session OK
        self.client.set_cookie("session", copied_cookie)
        self.assertEqual(self.client.get("/account/").status_code, 302)   # old copy refused

    def test_old_cookie_rejected_after_password_reset(self):
        self.real_login()
        copied_cookie = self.client.get_cookie("session").value
        self.sql("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (self.alice,))
        self.client.set_cookie("session", copied_cookie)
        self.assertEqual(self.client.get("/account/").status_code, 302)

    def test_disabled_user_is_logged_out(self):
        self.log_in(self.alice)
        self.sql("UPDATE users SET is_disabled = 1 WHERE id = ?", (self.alice,))
        self.assertEqual(self.client.get("/account/").status_code, 302)
        # and cannot log in again
        self.client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
        self.assertEqual(self.client.get("/account/").status_code, 302)

    def test_account_pages_need_login(self):
        for url in ["/account/", "/account/edit", "/account/password"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)


if __name__ == "__main__":
    unittest.main()
