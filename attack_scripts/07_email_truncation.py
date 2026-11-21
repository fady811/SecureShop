"""Lab 2.2: a long email is cut to 255 characters and becomes an admin email."""
import secrets

import requests

from common import NAIVE, NAIVE_DB, SECURE, SECURE_DB, db_rows, report


def run():
    # After cutting at 255 characters this ends in "@secureshop.com".
    email = "a" * (255 - len("@secureshop.com")) + "@secureshop.com" + ".attacker.net"
    name = "long_" + secrets.token_hex(3)
    data = {"username": name, "email": email, "password": "Long-Email-Pass-99",
            "confirm_password": "Long-Email-Pass-99"}

    requests.post(NAIVE + "/register", data=data)
    rows = db_rows(NAIVE_DB, "SELECT role FROM users WHERE username = ?", (name,))
    naive_worked = bool(rows) and rows[0]["role"] == "admin"

    r = requests.post(SECURE + "/auth/register", data=data)
    rows = db_rows(SECURE_DB, "SELECT role FROM users WHERE username = ?", (name,))
    # Even a SHORT @secureshop.com email never gives admin in SecureShop:
    short = "short_" + secrets.token_hex(3)
    requests.post(SECURE + "/auth/register", data=dict(data, username=short, email=f"{short}@secureshop.com"))
    short_role = db_rows(SECURE_DB, "SELECT role FROM users WHERE username = ?", (short,))[0]["role"]
    blocked = not rows and "at most 254" in r.text and short_role == "user"
    return report("Long email -> admin (Lab 2.2)", naive_worked,
                  f"{len(email)}-char email cut to 255, account got role 'admin'",
                  blocked, f"rejected 'Email must be at most 254 characters'; @secureshop.com gives role '{short_role}'")


if __name__ == "__main__":
    run()
