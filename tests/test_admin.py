"""Tests for admin.py (Member 6).  Run: python -m unittest discover tests -v"""
import re
import unittest

from app import app
from base import BaseTestCase


def all_admin_urls():
    """Every admin route in the app, found automatically (so a new route
    without @admin_required would make the test fail)."""
    urls = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("admin."):
            url = re.sub(r"<int:\w+>", "1", rule.rule)
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                urls.append((method, url))
    return urls


class AdminTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.boss = self.make_user("boss", role="admin")
        self.alice = self.make_user("alice", credit_cents=1000)          # $10.00
        self.product = self.make_product("Jacket", 10000)
        self.coupon = self.make_coupon("WELCOME5", value=5)
        self.log_in(self.boss, mfa_done=True)

    def user(self, user_id):
        return self.sql("SELECT * FROM users WHERE id = ?", (user_id,))[0]

    def post(self, url, **data):
        return self.client.post(url, data=data, follow_redirects=True)

    # ---- access control ----

    def test_normal_user_cannot_open_any_admin_page(self):
        urls = all_admin_urls()
        self.assertGreater(len(urls), 10)
        self.log_in(self.alice)
        for method, url in urls:
            response = self.client.open(url, method=method)
            self.assertEqual(response.status_code, 403, f"{method} {url}")
        self.assertIn("admin_access_denied", self.audit_actions())

    def test_anonymous_is_sent_to_login(self):
        self.client.post("/auth/logout")
        for method, url in all_admin_urls():
            response = self.client.open(url, method=method)
            self.assertEqual(response.status_code, 302, f"{method} {url}")

    def test_admin_without_2fa_in_session_is_refused(self):
        self.log_in(self.boss, mfa_done=False)
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_admin_pages_open_for_admin(self):
        for url in ["/admin/", "/admin/users", "/admin/products", "/admin/coupons",
                    "/admin/audit", "/admin/products/new", "/admin/coupons/new",
                    f"/admin/products/{self.product}/edit", f"/admin/coupons/{self.coupon}/edit"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_changes_need_post(self):
        self.assertEqual(self.client.get(f"/admin/users/{self.alice}/role").status_code, 405)

    # ---- users ----

    def test_admin_cannot_demote_or_disable_themselves(self):
        page = self.post(f"/admin/users/{self.boss}/role", role="user").data
        self.assertIn(b"You cannot change your own role.", page)
        page = self.post(f"/admin/users/{self.boss}/toggle-disabled").data
        self.assertIn(b"You cannot disable your own account.", page)
        boss = self.user(self.boss)
        self.assertEqual((boss["role"], boss["is_disabled"]), ("admin", 0))

    def test_make_admin_gives_totp_secret_and_ends_old_session(self):
        version_before = self.user(self.alice)["session_version"]
        response = self.client.post(f"/admin/users/{self.alice}/role", data={"role": "admin"})
        alice = self.user(self.alice)
        self.assertEqual(alice["role"], "admin")
        self.assertIsNotNone(alice["totp_secret"])
        self.assertIn(alice["totp_secret"].encode(), response.data)        # shown once on the page
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(alice["session_version"], version_before + 1)
        self.assertIn("admin_role_changed", self.audit_actions())
        details = self.sql("SELECT details FROM audit_log WHERE action = 'admin_role_changed'")[0][0]
        self.assertIn("user -> admin", details)
        self.assertNotIn(alice["totp_secret"], details)                     # secret not logged

    def test_unknown_role_refused(self):
        self.post(f"/admin/users/{self.alice}/role", role="superadmin")
        self.assertEqual(self.user(self.alice)["role"], "user")

    def test_demote_other_admin(self):
        other = self.make_user("other_admin", role="admin")
        self.post(f"/admin/users/{other}/role", role="user")
        self.assertEqual(self.user(other)["role"], "user")
        self.assertIsNone(self.user(other)["totp_secret"])

    def test_disable_and_enable_user(self):
        self.post(f"/admin/users/{self.alice}/toggle-disabled")
        self.assertEqual(self.user(self.alice)["is_disabled"], 1)
        self.post(f"/admin/users/{self.alice}/toggle-disabled")
        self.assertEqual(self.user(self.alice)["is_disabled"], 0)

    def test_credit_cannot_go_negative(self):
        page = self.post(f"/admin/users/{self.alice}/credit", amount="-20", reason="test").data
        self.assertIn(b"negative", page)
        self.assertEqual(self.user(self.alice)["store_credit_cents"], 1000)
        self.post(f"/admin/users/{self.alice}/credit", amount="-5", reason="refund mistake")
        self.assertEqual(self.user(self.alice)["store_credit_cents"], 500)
        self.post(f"/admin/users/{self.alice}/credit", amount="+12.50", reason="birthday gift")
        self.assertEqual(self.user(self.alice)["store_credit_cents"], 1750)
        details = self.sql("SELECT details FROM audit_log WHERE action = 'admin_credit_adjusted' "
                           "ORDER BY id DESC")[0][0]
        self.assertIn("500 -> 1750", details)
        self.assertIn("birthday gift", details)

    def test_admin_cannot_change_own_credit(self):
        page = self.post(f"/admin/users/{self.boss}/credit", amount="+500", reason="bonus for me").data
        self.assertIn(b"You cannot change your own store credit.", page)
        self.assertEqual(self.user(self.boss)["store_credit_cents"], 0)

    def test_user_search_wildcards_are_plain_text(self):
        page = self.client.get("/admin/users", query_string={"q": "%"}).data
        self.assertIn(b"No users found.", page)

    def test_credit_needs_reason_and_valid_amount(self):
        self.post(f"/admin/users/{self.alice}/credit", amount="10", reason="")
        for bad in ["abc", "0", "1e3", "--5", "10.999"]:
            self.post(f"/admin/users/{self.alice}/credit", amount=bad, reason="test")
        self.assertEqual(self.user(self.alice)["store_credit_cents"], 1000)

    def test_user_search_is_safe(self):
        page = self.client.get("/admin/users", query_string={"q": "' OR '1'='1"}).data
        self.assertIn(b"No users found.", page)

    # ---- products ----

    def test_product_validation(self):
        good = {"name": "Hat", "description": "", "category": "Clothing", "price": "9.99", "stock": "3"}
        for field, bad in [("price", "0"), ("price", "-1"), ("price", "abc"), ("stock", "-1"),
                           ("stock", "1.5"), ("name", ""), ("name", "n" * 101)]:
            data = dict(good, **{field: bad})
            response = self.client.post("/admin/products/new", data=data)
            self.assertEqual(response.status_code, 400, f"{field}={bad}")
        self.assertEqual(self.count("products"), 1)
        self.client.post("/admin/products/new", data=good)
        self.assertEqual(self.count("products"), 2)
        self.assertIn("admin_product_created", self.audit_actions())

    def test_edit_product_logs_old_and_new(self):
        self.client.post(f"/admin/products/{self.product}/edit", data={
            "name": "Jacket", "description": "", "category": "Clothing", "price": "80", "stock": "20"})
        details = self.sql("SELECT details FROM audit_log WHERE action = 'admin_product_updated'")[0][0]
        self.assertIn("price_cents: 10000 -> 8000", details)

    def test_hide_product(self):
        self.post(f"/admin/products/{self.product}/toggle")
        self.assertEqual(self.sql("SELECT is_active FROM products")[0][0], 0)
        self.assertEqual(self.client.get(f"/products/{self.product}").status_code, 404)

    # ---- coupons ----

    def test_coupon_validation(self):
        good = {"code": "SPRING10", "discount_type": "percent", "discount_value": "10",
                "max_discount": "", "min_total": "", "max_uses": "", "expires": ""}
        for field, bad in [("code", "AB"), ("code", "HAS SPACE"), ("code", "X" * 33),
                           ("discount_type", "free"), ("discount_value", "31"),
                           ("discount_value", "0"), ("discount_value", "-5"),
                           ("max_uses", "0"), ("expires", "2026-13-45"), ("expires", "2000-01-01"),
                           ("code", "welcome5")]:                     # already exists
            response = self.client.post("/admin/coupons/new", data=dict(good, **{field: bad}))
            self.assertEqual(response.status_code, 400, f"{field}={bad}")
        self.assertEqual(self.count("coupons"), 1)
        self.client.post("/admin/coupons/new", data=good)
        self.client.post("/admin/coupons/new", data=dict(good, code="FIVEOFF", discount_type="fixed",
                                                         discount_value="5"))
        rows = self.sql("SELECT code, discount_type, discount_value FROM coupons ORDER BY id")
        self.assertEqual([tuple(r) for r in rows[1:]],
                         [("SPRING10", "percent", 10), ("FIVEOFF", "fixed", 500)])

    def test_deactivate_coupon(self):
        self.post(f"/admin/coupons/{self.coupon}/toggle")
        self.assertEqual(self.sql("SELECT is_active FROM coupons")[0][0], 0)
        self.assertIn("admin_coupon_deactivated", self.audit_actions())

    # ---- audit log page ----

    def test_audit_log_page_and_filter(self):
        self.post(f"/admin/coupons/{self.coupon}/toggle")
        page = self.client.get("/admin/audit", query_string={"action": "admin_coupon_deactivated"}).data
        self.assertIn(b"is_active: 1 -&gt; 0", page)
        # unknown filter value is ignored, not an error
        self.assertEqual(self.client.get("/admin/audit?action=' OR 1=1 --").status_code, 200)


if __name__ == "__main__":
    unittest.main()
