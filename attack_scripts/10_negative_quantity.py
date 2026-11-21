"""Negative quantity: make the total negative so paying ADDS money."""
from common import NAIVE, SECURE, money, naive_login, naive_user, report, secure_login, secure_user

SHIRT = 1       # $15.00


def run():
    before = naive_user("shopper")["credit_cents"]
    s = naive_login("shopper")
    s.post(NAIVE + "/cart/add", data={"product_id": SHIRT, "quantity": -10, "price": 1500})
    s.post(NAIVE + "/checkout/pay")
    after = naive_user("shopper")["credit_cents"]
    naive_worked = after > before

    before_s = secure_user("shopper")["store_credit_cents"]
    s = secure_login("shopper")
    # requests follows the redirect, so the error message is on the page we land on
    answer = s.post(SECURE + "/cart/add", data={"product_id": SHIRT, "quantity": -10}).text
    cart = s.get(SECURE + "/cart/").text
    after_s = secure_user("shopper")["store_credit_cents"]
    blocked = ("Quantity must be a whole number from 1 to 10." in answer and "Your cart is empty" in cart
               and after_s == before_s)
    return report("Negative quantity", naive_worked, f"credit went UP {money(before)} -> {money(after)}",
                  blocked, f"rejected 'Quantity must be a whole number from 1 to 10.', credit stays {money(after_s)}")


if __name__ == "__main__":
    run()
