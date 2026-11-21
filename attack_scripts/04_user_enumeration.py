"""User enumeration through different login messages (Lecture 5)."""
import re

import requests

from common import NAIVE, SECURE, report


def message(html):
    match = re.search(r'flash-error">([^<]+)<', html) or re.search(r"<p>([^<]+)</p>", html.split("<hr>")[-1])
    return match.group(1).strip() if match else html[-80:]


def run():
    unknown = message(requests.post(NAIVE + "/login", data={"username": "nobody_here", "password": "x"}).text)
    wrong = message(requests.post(NAIVE + "/login", data={"username": "admin", "password": "x"}).text)
    naive_worked = unknown != wrong

    s_unknown = message(requests.post(SECURE + "/auth/login", data={"username": "nobody_here", "password": "x"}).text)
    s_wrong = message(requests.post(SECURE + "/auth/login", data={"username": "admin", "password": "x"}).text)
    blocked = s_unknown == s_wrong
    return report("User enumeration", naive_worked, f"'{unknown}' vs '{wrong}' -> 'admin' exists",
                  blocked, f"same message both times: '{s_wrong}'")


if __name__ == "__main__":
    run()
