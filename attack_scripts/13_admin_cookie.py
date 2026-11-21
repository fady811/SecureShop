"""Least privilege: become admin by setting a role cookie (Lab 3 / Lecture 2)."""
import requests

from common import NAIVE, SECURE, report, secure_login


def run():
    r = requests.get(NAIVE + "/admin", cookies={"role": "admin"})     # not even logged in
    naive_worked = r.status_code == 200 and "All users" in r.text

    s = secure_login("shopper")
    s.cookies.set("role", "admin")
    s.cookies.set("is_admin", "1")
    logged_in = s.get(SECURE + "/admin/users", allow_redirects=False).status_code
    anonymous = requests.get(SECURE + "/admin/users", cookies={"role": "admin"},
                             allow_redirects=False).status_code
    blocked = logged_in == 403 and anonymous == 302
    return report("Admin page via role cookie", naive_worked, "cookie role=admin opened the user list",
                  blocked, f"shopper + role=admin cookie -> {logged_in}; no login -> {anonymous} to login")


if __name__ == "__main__":
    run()
