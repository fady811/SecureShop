"""Tests for cart.py (Member 3).  Run: python -m unittest discover tests -v"""
import unittest

from base import BaseTestCase


class CartTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.jacket = self.make_product("Leather Jacket", 133700, stock=5)
        self.shirt = self.make_product("T-Shirt", 1500, stock=50)
        self.hidden = self.make_product("Hidden Thing", 100, active=0)
        self.alice = self.make_user("alice")
        self.log_in(self.alice)

    def add(self, product_id, quantity, **extra):
        data = {"product_id": str(product_id), "quantity": str(quantity)}
        data.update(extra)
        return self.client.post("/cart/add", data=data)

    def test_cart_requires_login(self):
        self.client.post("/auth/logout")
        self.assertEqual(self.client.get("/cart/").status_code, 302)
        self.assertEqual(self.add(self.shirt, 1).status_code, 302)
        self.assertIsNone(self.session_value("cart"))

    def test_cart_changes_need_post(self):
        self.assertEqual(self.client.get("/cart/add").status_code, 405)

    def test_price_field_from_browser_is_ignored(self):
        # Lab 1: Burp adds price=1 and total=1 to the request
        self.add(self.jacket, 1, price="1", price_cents="1", total="1")
        # Only id -> quantity is stored, no price
        self.assertEqual(self.session_value("cart"), {str(self.jacket): 1})
        page = self.client.get("/cart/").data
        self.assertIn(b"$1,337.00", page)
        self.assertNotIn(b"$0.01", page)

    def test_price_comes_from_database_every_time(self):
        self.add(self.shirt, 2)
        self.sql("UPDATE products SET price_cents = 2000 WHERE id = ?", (self.shirt,))
        page = self.client.get("/cart/").data
        self.assertIn(b"$40.00", page)               # 2 x the NEW price

    def test_bad_quantities_rejected(self):
        for bad in ["0", "-1", "-10", "1.5", "abc", "", " 1", "1e1",
                    "99999999999999999999", "11"]:
            response = self.add(self.shirt, bad)
            self.assertEqual(response.status_code, 302, bad)
            self.assertIsNone(self.session_value("cart"), bad)
        response = self.client.get("/cart/")
        self.assertIn(b"Quantity must be a whole number from 1 to 10.", response.data)

    def test_quantity_not_more_than_stock(self):
        self.add(self.jacket, 6)                     # only 5 in stock
        self.assertIsNone(self.session_value("cart"))
        self.add(self.jacket, 5)
        self.assertEqual(self.session_value("cart"), {str(self.jacket): 5})

    def test_adding_twice_cannot_pass_10(self):
        self.add(self.shirt, 8)
        self.add(self.shirt, 3)
        self.assertEqual(self.session_value("cart"), {str(self.shirt): 8})

    def test_unknown_or_inactive_product_rejected(self):
        for product_id in [999, self.hidden, "abc", "-1"]:
            self.add(product_id, 1)
            self.assertIsNone(self.session_value("cart"), product_id)

    def test_inactive_product_removed_from_cart_with_message(self):
        self.add(self.shirt, 1)
        self.sql("UPDATE products SET is_active = 0 WHERE id = ?", (self.shirt,))
        page = self.client.get("/cart/").data
        self.assertIn(b"no longer available", page)
        self.assertEqual(self.session_value("cart"), {})

    def test_update_quantity(self):
        self.add(self.shirt, 1)
        self.client.post("/cart/update", data={"product_id": str(self.shirt), "quantity": "4"})
        self.assertEqual(self.session_value("cart"), {str(self.shirt): 4})
        for bad in ["0", "-3", "2.5", "100"]:
            self.client.post("/cart/update", data={"product_id": str(self.shirt), "quantity": bad})
            self.assertEqual(self.session_value("cart"), {str(self.shirt): 4}, bad)

    def test_remove(self):
        self.add(self.shirt, 1)
        self.add(self.jacket, 1)
        self.client.post("/cart/remove", data={"product_id": str(self.shirt)})
        self.assertEqual(self.session_value("cart"), {str(self.jacket): 1})


if __name__ == "__main__":
    unittest.main()
