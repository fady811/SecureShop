"""Online brute force on the login form (Lecture 4, Lab 3 - Burp Intruder style).

Runs LAST in run_all.py: it locks the 'victim' account in SecureShop for 1 minute.
"""
import time

import requests

from common import COMMON_PASSWORDS, NAIVE, SECURE, report, secure_user


def run():
    with open(COMMON_PASSWORDS, encoding="utf-8") as f:
        guesses = [line.strip() for line in f if line.strip()][:20]
    guesses.append("Victim-Pass-2026")              # the attacker's 21st guess is right

    naive_tries = None
    for number, password in enumerate(guesses, start=1):
        r = requests.post(NAIVE + "/login", data={"username": "victim", "password": password},
                          allow_redirects=False)
        if r.status_code == 302:
            naive_tries = number
            break

    secure_in = False
    for password in guesses:
        r = requests.post(SECURE + "/auth/login", data={"username": "victim", "password": password},
                          allow_redirects=False)
        if r.status_code == 302:
            secure_in = True
            break
    locked = secure_user("victim")["locked_until"] > time.time()
    blocked = not secure_in and locked and "Invalid username or password." in r.text
    return report("Brute force login", naive_tries is not None,
                  f"logged in as victim on guess {naive_tries}, no lockout",
                  blocked, "locked after 5 wrong tries - the correct 21st guess was refused too")


if __name__ == "__main__":
    run()
