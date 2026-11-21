"""Reflected XSS through the search text (Lecture 2)."""
import requests

from common import NAIVE, SECURE, report

PAYLOAD = "<script>alert(document.cookie)</script>"


def run():
    naive_page = requests.get(NAIVE + "/search", params={"q": PAYLOAD}).text
    naive_worked = PAYLOAD in naive_page

    secure_page = requests.get(SECURE + "/products/", params={"q": PAYLOAD}).text
    blocked = PAYLOAD not in secure_page and "&lt;script&gt;" in secure_page
    return report("XSS (search text)", naive_worked, "<script> tag is in the page and would run",
                  blocked, "shown as &lt;script&gt; text, does not run")


if __name__ == "__main__":
    run()
