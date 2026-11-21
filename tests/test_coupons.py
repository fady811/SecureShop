"""Tests for coupons.py (Member 4).  Run: python -m unittest discover tests -v"""
import os
import re
import unittest

from app import app
from base import BaseTestCase
from coupons import check_coupon


class CouponTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.product = self.make_product("Jacket", 10000, stock=20)       # $100.00
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.welcome = self.make_coupon("WELCOME5", value=5)
        self.save20 = self.make_coupon("SAVE20", value=20)
        self.log_in(self.alice)
        self.client.post("/cart/add", data={"product_id": str(self.product), "quantity": "1"})

    def apply(self, code):
        return self.client.post("/coupons/apply", data={"code": code}, follow_redirects=True)

    def mark_used(self, coupon_id, user_id):
        """Pretend user_id already paid an order with this coupon."""
        order_id = self.insert(
            "INSERT INTO orders (public_id, user_id, status, subtotal_cents, discount_cents, "
            "total_cents, coupon_id) VALUES (?, ?, 'paid', 10000, 500, 9500, ?)",
            (f"test-{coupon_id}-{user_id}", user_id, coupon_id))
        self.insert("INSERT INTO coupon_redemptions (coupon_id, user_id, order_id) VALUES (?, ?, ?)",
                    (coupon_id, user_id, order_id))

    # ---- applying ----

    def test_apply_coupon(self):
        page = self.apply("WELCOME5").data
        self.assertIn(b"-$5.00", page)
        self.assertIn(b"$95.00", page)
        self.assertEqual(self.session_value("coupon_code"), "WELCOME5")
        self.assertIn("coupon_applied", self.audit_actions())

    def test_code_is_case_insensitive(self):
        self.apply("welcome5")
        self.assertEqual(self.session_value("coupon_code"), "WELCOME5")

    def test_coupons_do_not_stack(self):
        # Lab 2.1: alternate two codes
        self.apply("WELCOME5")
        self.apply("SAVE20")
        page = self.apply("WELCOME5").data
        self.assertEqual(self.session_value("coupon_code"), "WELCOME5")
        self.assertIn(b"-$5.00", page)
        self.assertIn(b"$95.00", page)          # only 5% off, not 5 + 20 + 5
        # Only the code is in the session - no discount amount
        with self.client.session_transaction() as sess:
            self.assertEqual(set(sess.keys()) - {"_flashes"},
                             {"user_id", "session_version", "mfa_done", "cart", "coupon_code"})

    def test_same_user_cannot_use_coupon_twice(self):
        self.mark_used(self.welcome, self.alice)
        page = self.apply("WELCOME5").data
        self.assertIn(b"You have already used this coupon.", page)
        self.assertIsNone(self.session_value("coupon_code"))
        # bob has not used it, so bob can
        with app.app_context():
            self.assertIsNone(check_coupon(self.bob, "WELCOME5", 10000)[2])

    def test_expired_coupon_rejected(self):
        self.make_coupon("OLD10", expires_at=self.now() - 60)
        self.assertIn(b"This coupon has expired.", self.apply("OLD10").data)
        self.assertIsNone(self.session_value("coupon_code"))

    def test_inactive_unknown_and_other_users_coupon_rejected(self):
        self.make_coupon("OFF", active=0)
        self.make_coupon("BOBS-ONLY", owner=self.bob)
        for code in ["OFF", "NOPE", "BOBS-ONLY"]:
            self.assertIn(b"This coupon code is not valid.", self.apply(code).data, code)
        self.assertIsNone(self.session_value("coupon_code"))
        self.assertIn("coupon_rejected", self.audit_actions())

    def test_max_uses(self):
        coupon = self.make_coupon("ONCE", max_uses=1)
        self.mark_used(coupon, self.bob)
        self.assertIn(b"used up", self.apply("ONCE").data)

    def test_minimum_cart_total(self):
        self.make_coupon("BIG", min_total_cents=20000)
        self.assertIn(b"at least $200.00", self.apply("BIG").data)

    def test_too_long_code_rejected(self):
        page = self.apply("A" * 33).data
        self.assertIn(b"at most 32 characters", page)

    def test_discount_never_above_cart_total(self):
        self.make_coupon("HUGE", discount_type="fixed", value=50000)      # $500 off
        self.make_coupon("CAPPED", value=30, max_discount_cents=700)       # 30%, max $7
        with app.app_context():
            for total in [1, 99, 1500, 10000]:
                coupon, discount, error = check_coupon(self.alice, "HUGE", total)
                self.assertIsNone(error)
                # a $500 fixed coupon on a smaller cart gives exactly the cart total
                self.assertEqual(discount, total)
            self.make_coupon("FIVE", discount_type="fixed", value=500, max_discount_cents=300)
            self.assertEqual(check_coupon(self.alice, "FIVE", 10000)[1], 300)   # coupon's own cap
            self.assertEqual(check_coupon(self.alice, "CAPPED", 10000)[1], 700)
            self.assertIsNotNone(check_coupon(self.alice, "WELCOME5", 0)[2])   # empty cart

    def test_coupon_rechecked_when_cart_changes(self):
        self.make_coupon("MIN50", min_total_cents=5000)
        self.apply("MIN50")
        self.assertEqual(self.session_value("coupon_code"), "MIN50")
        self.client.post("/cart/remove", data={"product_id": str(self.product)})
        page = self.client.get("/cart/").data
        self.assertIn(b"Your coupon was removed", page)
        self.assertIsNone(self.session_value("coupon_code"))

    # ---- guessing ----

    def test_coupon_guessing_blocked_after_10_tries(self):
        for i in range(10):
            self.apply(f"GUESS{i}")
        page = self.apply("WELCOME5").data          # even a correct code is refused now
        self.assertIn(b"Too many wrong coupon codes", page)
        self.assertIsNone(self.session_value("coupon_code"))
        self.assertIn("coupon_guessing_blocked", self.audit_actions())
        # 11 minutes later the old failures no longer count
        self.sql("UPDATE coupon_failed_attempts SET attempted_at = attempted_at - 660")
        self.apply("WELCOME5")
        self.assertEqual(self.session_value("coupon_code"), "WELCOME5")

    def test_guess_limit_is_per_user(self):
        for i in range(10):
            self.apply(f"GUESS{i}")
        self.log_in(self.bob)
        self.client.post("/cart/add", data={"product_id": str(self.product), "quantity": "1"})
        self.apply("WELCOME5")
        self.assertEqual(self.session_value("coupon_code"), "WELCOME5")

    # ---- newsletter ----

    def newsletter_code(self):
        files = os.listdir(self.outbox)
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.outbox, files[0]), encoding="utf-8") as f:
            return re.search(r"NEWS-[0-9A-F]+", f.read()).group(0)

    def test_newsletter_gives_only_one_coupon_per_user(self):
        self.client.post("/newsletter")
        page = self.client.post("/newsletter", follow_redirects=True).data
        self.assertIn(b"already subscribed", page)
        self.assertEqual(self.count("newsletter_subscribers"), 1)
        self.assertEqual(len(self.sql("SELECT id FROM coupons WHERE owner_user_id = ?",
                                      (self.alice,))), 1)
        self.assertIn("newsletter_signup", self.audit_actions())

    def test_newsletter_coupon_is_personal_and_single_use(self):
        self.client.post("/newsletter")
        code = self.newsletter_code()
        coupon = self.sql("SELECT * FROM coupons WHERE code = ?", (code,))[0]
        self.assertEqual((coupon["discount_value"], coupon["max_discount_cents"],
                          coupon["max_uses"], coupon["owner_user_id"]), (10, 1000, 1, self.alice))
        page = self.apply(code).data
        self.assertIn(b"-$10.00", page)             # 10% of $100 = $10 (the cap)
        with app.app_context():
            self.assertEqual(check_coupon(self.bob, code, 10000)[2], "This coupon code is not valid.")

    def test_newsletter_one_signup_per_email(self):
        # Someone else already signed up with alice's email address
        self.insert("INSERT INTO newsletter_subscribers (user_id, email) VALUES (?, ?)",
                    (self.bob, "alice@example.com"))
        self.client.post("/newsletter")
        self.assertEqual(self.count("newsletter_subscribers"), 1)

    def test_newsletter_needs_login_and_confirmed_email(self):
        self.client.post("/auth/logout")
        self.assertEqual(self.client.post("/newsletter").status_code, 302)
        self.assertEqual(self.count("newsletter_subscribers"), 0)
        carol = self.make_user("carol", confirmed=0)
        self.log_in(carol)
        page = self.client.post("/newsletter", follow_redirects=True).data
        self.assertIn(b"confirm your email", page)
        self.assertEqual(self.count("newsletter_subscribers"), 0)


if __name__ == "__main__":
    unittest.main()
