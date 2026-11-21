"""Shared helpers for the attack scripts (evidence for docs/04_attack_evidence.md).

Every script runs the SAME attack against:
  - the naive app   (VULNERABLE on purpose)   NAIVE_URL,  default http://127.0.0.1:5001
  - SecureShop      (our real app)            SECURE_URL, default http://127.0.0.1:5000
Change the URLs with environment variables, e.g.  SECURE_URL=http://127.0.0.1:5050

Some scripts read the local databases or outbox folders. That stands for
something a real attacker could get another way (a sniffed 2FA code, a
reset email, a stolen database file) - it is written in each script.
Only run these against your own machine.
"""
import glob
import ipaddress
import os
import re
import sqlite3
from urllib.parse import urlsplit

import requests


def _local_url(name, default):
    value = os.environ.get(name, default)
    parsed = urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{name} must be an HTTP URL on a loopback IP address") from error
    if (parsed.scheme != "http" or not address.is_loopback or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError(f"{name} must be an HTTP URL on a loopback IP address")
    host = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{host}" + (f":{port}" if port is not None else "")


NAIVE = _local_url("NAIVE_URL", "http://127.0.0.1:5001")
SECURE = _local_url("SECURE_URL", "http://127.0.0.1:5000")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECURE_DB = os.path.join(ROOT, "secureshop.db")
SECURE_OUTBOX = os.path.join(ROOT, "outbox")
NAIVE_DB = os.path.join(ROOT, "naive_demo", "naive.db")
NAIVE_OUTBOX = os.path.join(ROOT, "naive_demo", "outbox")
COMMON_PASSWORDS = os.path.join(ROOT, "common_passwords.txt")

# Seed accounts (seed.py / naive_demo/seed_naive.py)
SECURE_PASSWORDS = {"shopper": "Shopper-Pass-2026", "admin": "Admin-Pass-2026!",
                    "victim": "Victim-Pass-2026"}
NAIVE_PASSWORDS = {"shopper": "sunshine123", "admin": "Admin-Pass-2026!",
                   "victim": "Victim-Pass-2026"}


def money(cents):
    return f"${cents / 100:,.2f}"


def report(topic, naive_worked, naive_detail, secure_blocked, secure_detail):
    """Print one result line and return it (run_all.py collects them)."""
    naive = "ATTACK WORKED" if naive_worked else "attack failed (?)"
    secure = "ATTACK BLOCKED" if secure_blocked else "ATTACK WORKED  <-- PROBLEM!"
    line = f"[{topic}] naive: {naive} ({naive_detail})   |   SecureShop: {secure} ({secure_detail})"
    print(line)
    return {"topic": topic, "naive_worked": naive_worked, "secure_blocked": secure_blocked, "line": line}


def db_rows(path, sql, params=()):
    """Read the local database (only to SHOW the result, e.g. a user's credit)."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows


def db_write(path, sql, params=()):
    con = sqlite3.connect(path)
    con.execute(sql, params)
    con.commit()
    con.close()


def newest_email(folder):
    """Text of the newest 'email' in an outbox folder."""
    files = glob.glob(os.path.join(folder, "*.txt"))
    if not files:
        return ""
    with open(max(files, key=os.path.getmtime), encoding="utf-8") as f:
        return f.read()


# ---- SecureShop helpers ----

def secure_login(username, password=None):
    s = requests.Session()
    s.post(SECURE + "/auth/login", allow_redirects=False,
           data={"username": username, "password": password or SECURE_PASSWORDS[username]})
    return s


def secure_admin_login():
    """Admin login with password + current TOTP code (the secret is read from
    the local database - only so the script can play the real admin)."""
    import pyotp
    secret = db_rows(SECURE_DB, "SELECT totp_secret FROM users WHERE username = 'admin'")[0][0]
    s = secure_login("admin")
    s.post(SECURE + "/auth/two-factor", data={"code": pyotp.TOTP(secret).now()}, allow_redirects=False)
    return s


def secure_cart_total(s):
    page = s.get(SECURE + "/cart/").text
    match = re.search(r'cart-total"><td colspan="3">Total</td><td>([^<]+)<', page)
    return match.group(1) if match else "(empty cart)"


def secure_checkout_token(s):
    page = s.get(SECURE + "/checkout").text
    match = re.search(r'name="checkout_token" value="([^"]+)"', page)
    return match.group(1) if match else ""


def secure_user(username):
    return db_rows(SECURE_DB, "SELECT * FROM users WHERE username = ?", (username,))[0]


# ---- naive app helpers ----

def naive_login(username, password=None):
    s = requests.Session()
    s.post(NAIVE + "/login", allow_redirects=False,
           data={"username": username, "password": password or NAIVE_PASSWORDS[username]})
    return s


def naive_user(username):
    return db_rows(NAIVE_DB, "SELECT * FROM users WHERE username = ?", (username,))[0]
