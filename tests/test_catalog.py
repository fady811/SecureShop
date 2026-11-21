"""Tests for catalog.py (Member 2).  Run: python -m unittest discover tests -v"""
import unittest

from base import BaseTestCase


class CatalogTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.make_product("Running Shoes", 5999, category="Shoes")
        self.make_product("Leather Jacket", 133700, category="Clothing")
        self.make_product("T-Shirt", 1500, category="Clothing")
        self.make_product("Secret Prototype", 100, category="Clothing", active=0)
        self.make_user("alice")

    def get(self, **params):
        return self.client.get("/products/", query_string=params)

    # ---- list, search, filter ----

    def test_list_shows_only_active_products(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Running Shoes", response.data)
        self.assertNotIn(b"Secret Prototype", response.data)

    def test_search_by_name(self):
        response = self.get(q="jacket")
        self.assertIn(b"Leather Jacket", response.data)
        self.assertNotIn(b"Running Shoes", response.data)

    def test_sql_injection_in_search_returns_no_extra_rows(self):
        for payload in ["' OR '1'='1", "' OR 1=1 --",
                        "' UNION SELECT id, email, password_hash, 1, 1 FROM users --"]:
            response = self.get(q=payload)
            self.assertEqual(response.status_code, 200, payload)
            self.assertIn(b"0 found", response.data, payload)
            self.assertNotIn(b"alice@example.com", response.data)
            self.assertNotIn(b"Secret Prototype", response.data)

    def test_sql_injection_in_category_and_price(self):
        response = self.get(category="Clothing' OR '1'='1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Leather Jacket", response.data)
        response = self.get(min_price="0 OR 1=1")
        self.assertEqual(response.status_code, 400)

    def test_like_wildcards_are_plain_text(self):
        response = self.get(q="%")
        self.assertIn(b"0 found", response.data)

    def test_script_in_search_is_escaped(self):
        response = self.get(q="<script>alert(1)</script>")
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)

    def test_too_long_search_rejected(self):
        response = self.get(q="a" * 101)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"at most 100 characters", response.data)
        self.assertEqual(self.get(q="a" * 100).status_code, 200)

    def test_filter_by_category(self):
        response = self.get(category="Shoes")
        self.assertIn(b"Running Shoes", response.data)
        self.assertNotIn(b"T-Shirt", response.data)

    def test_filter_by_price_range(self):
        response = self.get(min_price="20", max_price="100.50")
        self.assertIn(b"Running Shoes", response.data)        # $59.99
        self.assertNotIn(b"T-Shirt", response.data)           # $15.00 - too cheap
        self.assertNotIn(b"Leather Jacket", response.data)    # $1,337.00 - too expensive

    def test_bad_price_filters_rejected(self):
        for bad in ["-5", "abc", "1e3", "nan", "10.999", "99999999"]:
            response = self.get(min_price=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertNotIn(b"Traceback", response.data)
        response = self.get(min_price="50", max_price="10")
        self.assertIn(b"cannot be higher", response.data)

    # ---- sorting ----

    def names_in_order(self, response):
        html = response.data.decode()
        names = ["Running Shoes", "Leather Jacket", "T-Shirt"]
        return sorted(names, key=html.index)

    def test_sort_by_price(self):
        self.assertEqual(self.names_in_order(self.get(sort="price_asc")),
                         ["T-Shirt", "Running Shoes", "Leather Jacket"])
        self.assertEqual(self.names_in_order(self.get(sort="price_desc")),
                         ["Leather Jacket", "Running Shoes", "T-Shirt"])

    def test_bad_sort_value_is_ignored(self):
        for bad in ["price_cents; DROP TABLE users", "(SELECT password_hash FROM users)", "id DESC"]:
            response = self.get(sort=bad)
            self.assertEqual(response.status_code, 200, bad)
            # falls back to sorting by name
            self.assertEqual(self.names_in_order(response),
                             ["Leather Jacket", "Running Shoes", "T-Shirt"])
        self.assertEqual(self.count("users"), 1)              # table still there

    # ---- detail page ----

    def test_product_detail(self):
        response = self.client.get("/products/2")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"$1,337.00", response.data)
        # The add-to-cart form has no price field
        self.assertNotIn(b'name="price"', response.data)

    def test_unknown_hidden_or_bad_id_gives_custom_404(self):
        for url in ["/products/999", "/products/4", "/products/abc", "/products/1%27%20OR%201=1"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)
            self.assertIn(b"We could not find that page.", response.data)


if __name__ == "__main__":
    unittest.main()
