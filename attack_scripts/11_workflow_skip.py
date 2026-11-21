"""Lab 2.3: skip the payment step and open the confirmation page directly."""
import secrets

from common import (NAIVE, NAIVE_DB, SECURE, SECURE_DB, db_rows, naive_login, naive_user, report,
                    secure_login, secure_user)

JACKET = 2


def run():
    credit_before = naive_user("shopper")["credit_cents"]
    s = naive_login("shopper")
    s.post(NAIVE + "/cart/add", data={"product_id": JACKET, "quantity": 1, "price": 133700})
    s.get(NAIVE + "/order/confirm")                  # never pressed "Pay"
    order = db_rows(NAIVE_DB, "SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    naive_worked = (order["status"] == "paid" and order["total_cents"] == 133700
                    and naive_user("shopper")["credit_cents"] == credit_before)

    s = secure_login("shopper")
    s.post(SECURE + "/cart/add", data={"product_id": JACKET, "quantity": 1})
    orders_before = len(db_rows(SECURE_DB, "SELECT id FROM orders"))
    credit_s = secure_user("shopper")["store_credit_cents"]
    codes = [s.get(f"{SECURE}/orders/{secrets.token_urlsafe(12)}/confirmation").status_code,
             s.get(SECURE + "/checkout/pay").status_code,
             s.post(SECURE + "/checkout/pay", data={}, allow_redirects=False).status_code]
    orders_after = len(db_rows(SECURE_DB, "SELECT id FROM orders"))
    s.post(SECURE + "/cart/remove", data={"product_id": JACKET})
    blocked = (orders_after == orders_before and codes[0] == 404 and codes[1] == 405
               and secure_user("shopper")["store_credit_cents"] == credit_s)
    return report("Skip payment step (Lab 2.3)", naive_worked,
                  "visiting /order/confirm created a PAID $1,337.00 order, $0 charged",
                  blocked, f"confirmation=404, GET pay=405, POST pay without token={codes[2]} -> no order created")


if __name__ == "__main__":
    run()
