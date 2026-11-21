"""Password reset link: can it be used again / after it should have expired? (Lectures 4-5)

The attacker got an old reset link (e.g. from the victim's mailbox). We read
the newest email in the outbox folder to play that.
"""
import re
import time

import requests

from common import (NAIVE, NAIVE_OUTBOX, SECURE, SECURE_DB, SECURE_OUTBOX, db_write, newest_email,
                    report)

PASSWORD = "Victim-Pass-2026"       # set back to the same password, so other scripts still work


def run():
    requests.post(NAIVE + "/forgot", data={"username": "victim"})
    token = re.search(r"token=(\w+)", newest_email(NAIVE_OUTBOX)).group(1)
    first = requests.post(NAIVE + "/reset", data={"token": token, "password": PASSWORD})
    again = requests.post(NAIVE + "/reset", data={"token": token, "password": PASSWORD})
    naive_worked = "Password changed" in first.text and "Password changed" in again.text

    requests.post(SECURE + "/auth/forgot-password", data={"email": "victim@secureshop.test"})
    link = re.search(r"(/auth/reset/\S+)", newest_email(SECURE_OUTBOX)).group(1)
    data = {"password": PASSWORD, "confirm_password": PASSWORD}
    first = requests.post(SECURE + link, data=data, allow_redirects=False)
    reuse = requests.post(SECURE + link, data=data, allow_redirects=False)

    time.sleep(1.1)       # so the next email is the newest file
    requests.post(SECURE + "/auth/forgot-password", data={"email": "victim@secureshop.test"})
    link2 = re.search(r"(/auth/reset/\S+)", newest_email(SECURE_OUTBOX)).group(1)
    # "Time travel": make the new link 16 minutes old instead of waiting.
    db_write(SECURE_DB, "UPDATE password_reset_tokens SET expires_at = ?", (int(time.time()) - 60,))
    expired = requests.post(SECURE + link2, data=data, allow_redirects=False)
    blocked = first.status_code == 302 and reuse.status_code == 400 and expired.status_code == 400
    return report("Reset link reuse / expiry", naive_worked, "the same reset link worked twice (never expires)",
                  blocked, f"first use OK; reused -> {reuse.status_code}; after 15 min -> {expired.status_code}")


if __name__ == "__main__":
    run()
