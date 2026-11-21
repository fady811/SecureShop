"""Fail secure: does an error page leak a stack trace? (Lecture 3)"""
import requests

from common import NAIVE, SECURE, report


def run():
    r = requests.get(NAIVE + "/product/abc")
    naive_worked = "Traceback" in r.text
    # show the leaked line that points into our own code (without the home folder)
    leaked_line = next((line.strip() for line in r.text.splitlines() if "naive_app.py" in line), "")
    leaked_line = leaked_line[leaked_line.find("naive_demo"):] if "naive_demo" in leaked_line else leaked_line

    pages = [requests.get(SECURE + "/products/abc"),
             requests.get(SECURE + "/products/?min_price=abc"),
             requests.post(SECURE + "/cart/add", data={"product_id": "x" * 5000})]
    blocked = all("Traceback" not in p.text and 'File "' not in p.text for p in pages)
    codes = ", ".join(str(p.status_code) for p in pages)
    return report("Error pages / stack trace", naive_worked,
                  f"HTTP {r.status_code} with stack trace: {leaked_line}",
                  blocked, f"friendly pages only (HTTP {codes}), no stack trace")


if __name__ == "__main__":
    run()
