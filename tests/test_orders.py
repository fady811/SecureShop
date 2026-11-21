"""Tests for orders.py (Member 5).  Run: python -m unittest discover tests -v"""
import re
import unittest

from base import BaseTestCase


class OrderTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.jacket = self.make_product("Leather Jacket", 133700, stock=5)
        self.shirt = self.make_product("T-Shirt", 1500, stock=50)
        self.alice = self.make_user("alice", credit_cents=10000)        # $100.00
        self.bob = self.make_user("bob", credit_cents=10000)
        self.log_in(self.alice)

    # ---- helpers ----

    def add(self, product_id, quantity):
        self.client.post("/cart/add", data={"product_id": str(product_id), "quantity": str(quantity)})

    def checkout_token(self):
        page = self.client.get("/checkout").data.decode()
        return re.search(r'name="checkout_token" value="([^"]+)"', page).group(1)

    def pay(self, token=None, **extra):
        data = {"checkout_token": token if token is not None else self.checkout_token()}
        data.update(extra)
        return self.client.post("/checkout/pay", data=data)

    def credit(self, user_id):
        return self.sql("SELECT store_credit_cents FROM users WHERE id = ?", (user_id,))[0][0]

    def orders_of(self, user_id):
        return self.sql("SELECT * FROM orders WHERE user_id = ?", (user_id,))

    def make_order(self, user_id, status="paid", public_id="order-public-id-1"):
        return self.insert(
            "INSERT INTO orders (public_id, user_id, status, subtotal_cents, total_cents) "
            "VALUES (?, ?, ?, 1500, 1500)", (public_id, user_id, status))

    # ---- payment ----

    def test_successful_payment(self):
        self.add(self.shirt, 2)
        response = self.pay()
        orders = self.orders_of(self.alice)
        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertTrue(response.headers["Location"].endswith(f"/orders/{order['public_id']}/confirmation"))
        self.assertEqual((order["status"], order["total_cents"]), ("paid", 3000))
        self.assertEqual(self.credit(self.alice), 7000)
        self.assertEqual(self.sql("SELECT stock FROM products WHERE id = ?", (self.shirt,))[0][0], 48)
        item = self.sql("SELECT * FROM order_items WHERE order_id = ?", (order["id"],))[0]
        self.assertEqual((item["unit_price_cents"], item["quantity"]), (1500, 2))
        self.assertIsNone(self.session_value("cart"))                # cart emptied
        self.assertIn("order_placed", self.audit_actions())

    def test_price_tampering_at_checkout_is_ignored(self):
        # Lab 1: Burp adds total=1 / price=1 / user_id=bob to the pay request
        self.add(self.shirt, 2)
        self.pay(total="1", total_cents="1", price="1", user_id=str(self.bob))
        order = self.orders_of(self.alice)[0]
        self.assertEqual(order["total_cents"], 3000)
        self.assertEqual(self.credit(self.alice), 7000)
        self.assertEqual(self.credit(self.bob), 10000)                # bob not charged

    def test_price_change_after_checkout_page_uses_new_price(self):
        self.add(self.shirt, 1)
        token = self.checkout_token()
        self.sql("UPDATE products SET price_cents = 2000 WHERE id = ?", (self.shirt,))
        self.pay(token)
        self.assertEqual(self.orders_of(self.alice)[0]["total_cents"], 2000)

    def test_not_enough_credit(self):
        self.add(self.jacket, 1)                                      # $1,337 > $100
        page = self.client.post("/checkout/pay", data={"checkout_token": self.checkout_token()},
                                follow_redirects=True).data
        self.assertIn(b"Not enough store credit", page)
        self.assertEqual(self.orders_of(self.alice), [])
        self.assertEqual(self.credit(self.alice), 10000)              # never below zero, unchanged
        self.assertEqual(self.sql("SELECT stock FROM products WHERE id = ?", (self.jacket,))[0][0], 5)
        self.assertIn("payment_refused", self.audit_actions())

    def test_stock_checked_again_at_payment(self):
        self.add(self.shirt, 3)
        token = self.checkout_token()
        self.sql("UPDATE products SET stock = 1 WHERE id = ?", (self.shirt,))
        self.pay(token)
        self.assertEqual(self.orders_of(self.alice), [])
        self.assertEqual(self.credit(self.alice), 10000)

    def test_double_payment_charges_once(self):
        self.add(self.shirt, 1)
        token = self.checkout_token()
        # Save the cookie BEFORE paying, to replay exactly the same request
        # (like a double click or Burp Repeater sending it twice).
        old_cookie = self.client.get_cookie("session").value
        self.pay(token)
        self.client.set_cookie("session", old_cookie)
        response = self.pay(token)
        self.assertEqual(len(self.orders_of(self.alice)), 1)
        self.assertEqual(self.credit(self.alice), 8500)               # charged once
        self.assertIn("/confirmation", response.headers["Location"])

    def test_pay_without_valid_token_refused(self):
        self.add(self.shirt, 1)
        self.checkout_token()
        self.pay(token="made-up-token")
        self.assertEqual(self.orders_of(self.alice), [])
        self.assertEqual(self.client.get("/checkout/pay").status_code, 405)

    # ---- coupons at payment ----

    def test_coupon_used_only_once_after_real_order(self):
        self.make_coupon("WELCOME5", value=5)
        self.add(self.shirt, 2)
        self.client.post("/coupons/apply", data={"code": "WELCOME5"})
        self.pay()
        order = self.orders_of(self.alice)[0]
        self.assertEqual((order["discount_cents"], order["total_cents"]), (150, 2850))
        self.assertEqual(self.count("coupon_redemptions"), 1)
        self.assertIn("coupon_redeemed", self.audit_actions())

        self.add(self.shirt, 2)
        page = self.client.post("/coupons/apply", data={"code": "WELCOME5"},
                                follow_redirects=True).data
        self.assertIn(b"You have already used this coupon.", page)

    def test_coupon_rechecked_at_payment(self):
        self.make_coupon("SAVE10", value=10)
        self.add(self.shirt, 2)
        self.client.post("/coupons/apply", data={"code": "SAVE10"})
        token = self.checkout_token()
        self.sql("UPDATE coupons SET is_active = 0")                  # admin switches it off
        page = self.client.post("/checkout/pay", data={"checkout_token": token},
                                follow_redirects=True).data
        self.assertIn(b"coupon can no longer be used", page)
        self.assertEqual(self.orders_of(self.alice), [])
        self.assertEqual(self.count("coupon_redemptions"), 0)

    def test_fixed_coupon_can_make_total_zero_but_not_negative(self):
        self.make_coupon("BIG", discount_type="fixed", value=50000)
        self.add(self.shirt, 1)
        self.client.post("/coupons/apply", data={"code": "BIG"})
        self.pay()
        order = self.orders_of(self.alice)[0]
        self.assertEqual((order["discount_cents"], order["total_cents"]), (1500, 0))
        self.assertEqual(self.credit(self.alice), 10000)

    # ---- confirmation, history, detail ----

    def test_confirmation_needs_paid_order_of_the_user(self):
        self.make_order(self.alice, status="pending", public_id="alice-pending-0001")
        self.make_order(self.bob, status="paid", public_id="bob-paid-order-001")
        self.make_order(self.alice, status="paid", public_id="alice-paid-order-1")
        before = self.count("orders")
        self.assertEqual(self.client.get("/orders/alice-pending-0001/confirmation").status_code, 404)
        self.assertEqual(self.client.get("/orders/bob-paid-order-001/confirmation").status_code, 404)
        self.assertEqual(self.client.get("/orders/does-not-exist-123/confirmation").status_code, 404)
        self.assertEqual(self.client.get("/orders/alice-paid-order-1/confirmation").status_code, 200)
        # Lab 2.3: opening the page never creates or changes an order
        self.assertEqual(self.count("orders"), before)
        self.assertEqual(self.sql("SELECT status FROM orders WHERE public_id = 'alice-pending-0001'")[0][0],
                         "pending")

    def test_other_users_order_is_404(self):
        self.make_order(self.bob, public_id="bob-paid-order-001")
        response = self.client.get("/orders/bob-paid-order-001")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"We could not find that page.", response.data)
        self.assertNotIn(b"bob-paid-order-001", self.client.get("/orders").data)

    def test_number_ids_do_not_work(self):
        self.make_order(self.alice, public_id="alice-paid-order-1")
        self.assertEqual(self.client.get("/orders/1").status_code, 404)

    def test_order_pages_need_login(self):
        self.client.post("/auth/logout")
        for url in ["/checkout", "/orders", "/orders/alice-paid-order-1"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)


if __name__ == "__main__":
    unittest.main()
