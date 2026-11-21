"""Weak passwords allowed at registration? (Lecture 4)"""
import secrets

import requests

from common import NAIVE, NAIVE_DB, SECURE, SECURE_DB, db_rows, report


def run():
    name = "weak_" + secrets.token_hex(3)
    data = {"username": name, "email": f"{name}@example.com", "password": "password123",
            "confirm_password": "password123"}

    requests.post(NAIVE + "/register", data=data)
    naive_worked = bool(db_rows(NAIVE_DB, "SELECT id FROM users WHERE username = ?", (name,)))

    r = requests.post(SECURE + "/auth/register", data=data)
    created = db_rows(SECURE_DB, "SELECT id FROM users WHERE username = ?", (name,))
    blocked = not created and "too common" in r.text
    return report("Weak password", naive_worked, "account created with 'password123'",
                  blocked, "refused: 'This password is too common'")


if __name__ == "__main__":
    run()
