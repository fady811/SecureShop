"""Lab 2.1: alternate two coupon codes so the discounts add up."""
import re

from common import NAIVE, SECURE, naive_login, report, secure_login

BACKPACK = 4    # $34.50, x2 = $69.00
CODES = ["WELCOME5", "SAVE20", "WELCOME5", "SAVE20"]


def run():
    s = naive_login("shopper")
    s.post(NAIVE + "/cart/add", data={"product_id": BACKPACK, "quantity": 2, "price": 3450})
    for code in CODES:
        s.post(NAIVE + "/coupon/apply", data={"code": code})
    discount = int(re.search(r"Discount: (-?\d+)", s.get(NAIVE + "/cart").text).group(1))
    naive_worked = discount > 6900 * 20 // 100

    s = secure_login("shopper")
    s.post(SECURE + "/cart/add", data={"product_id": BACKPACK, "quantity": 2})
    for code in CODES:
        s.post(SECURE + "/coupons/apply", data={"code": code})
    page = s.get(SECURE + "/cart/").text
    coupon_lines = re.findall(r"Coupon <strong>(\w+)</strong></td><td>-([^<]+)<", page)
    s.post(SECURE + "/cart/remove", data={"product_id": BACKPACK})
    blocked = len(coupon_lines) == 1 and coupon_lines[0] == ("SAVE20", "$13.80")
    secure_detail = (f"one coupon only: {coupon_lines[0][0]} = -{coupon_lines[0][1]} (20%)"
                     if coupon_lines else "no coupon")
    return report("Coupon stacking (Lab 2.1)", naive_worked,
                  f"4 codes applied: -${discount / 100:.2f} ({discount * 100 // 6900}% off)",
                  blocked, secure_detail)


if __name__ == "__main__":
    run()
