"""IDOR: open another customer's order by changing the id in the URL (Lecture 2)."""
from common import NAIVE, SECURE, naive_login, report, secure_checkout_token, secure_login

NOTEBOOK = 8    # $6.50


def run():
    s = naive_login("shopper")
    page = s.get(NAIVE + "/order/1").text            # order 1 belongs to "victim"
    naive_worked = "victim" in page

    # The victim buys something in SecureShop ...
    victim = secure_login("victim")
    victim.post(SECURE + "/cart/add", data={"product_id": NOTEBOOK, "quantity": 1})
    r = victim.post(SECURE + "/checkout/pay", data={"checkout_token": secure_checkout_token(victim)},
                    allow_redirects=False)
    public_id = r.headers.get("Location", "").split("/orders/")[-1].split("/")[0]
    # ... and the attacker even knows the random order id (worst case).
    attacker = secure_login("shopper")
    detail = attacker.get(f"{SECURE}/orders/{public_id}").status_code
    confirm = attacker.get(f"{SECURE}/orders/{public_id}/confirmation").status_code
    blocked = bool(public_id) and detail == 404 and confirm == 404
    return report("IDOR (other people's orders)", naive_worked, "shopper read victim's order /order/1",
                  blocked, f"victim's order {public_id[:8]}... -> {detail} / {confirm} for shopper")


if __name__ == "__main__":
    run()
