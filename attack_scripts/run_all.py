"""Run every attack against the naive app and SecureShop, and save the results.

1. Start both apps (two terminals):
       python naive_demo/seed_naive.py && python naive_demo/naive_app.py      (port 5001)
       python seed.py && flask run                                             (port 5000)
2. Run:  python attack_scripts/run_all.py
   (on macOS port 5000 may be used by AirPlay - then start SecureShop with
    `flask run -p 5050` and run  SECURE_URL=http://127.0.0.1:5050 python attack_scripts/run_all.py)

By default both databases are re-created first (seed scripts), so every run
starts from the same state. Use --no-reseed to keep the current data.
The output is also written to docs/evidence/attack_results.txt.
"""
import importlib
import os
import subprocess
import sys
import time
from datetime import datetime

import requests

from common import NAIVE, ROOT, SECURE

SCRIPTS = [
    "01_sql_injection", "02_xss", "03_debug_errors", "04_user_enumeration",
    "05_password_storage", "06_weak_password", "07_email_truncation",
    "08_price_tampering", "09_coupon_stacking", "10_negative_quantity",
    "11_workflow_skip", "12_idor", "13_admin_cookie", "14_2fa_bypass",
    "15_2fa_reuse", "16_reset_token", "17_brute_force",          # brute force last (it locks 'victim')
]
RESULTS_FILE = os.path.join(ROOT, "docs", "evidence", "attack_results.txt")


def check_running(name, url):
    try:
        requests.get(url, timeout=3)
        return True
    except requests.ConnectionError:
        print(f"{name} is not running at {url} - start it first (see the top of this file).")
        return False


def main():
    if not (check_running("Naive app", NAIVE) and check_running("SecureShop", SECURE)):
        sys.exit(1)
    if "--no-reseed" not in sys.argv:
        subprocess.run([sys.executable, os.path.join(ROOT, "seed.py")], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, os.path.join(ROOT, "naive_demo", "seed_naive.py")], cwd=ROOT,
                       check=True, stdout=subprocess.DEVNULL)
        print("NOTE: both databases were re-created. The admin has a NEW TOTP secret now -")
        print("      run `python seed.py` again before a browser demo to see the secret.\n")

    header = [f"Attack results - {datetime.now():%Y-%m-%d %H:%M}",
              f"Naive app:  {NAIVE}   (VULNERABLE on purpose)",
              f"SecureShop: {SECURE}", ""]
    print("\n".join(header))
    results = []
    start = time.time()
    for name in SCRIPTS:
        try:
            results.append(importlib.import_module(name).run())
        except Exception as error:                 # keep going, but show it clearly
            line = f"[{name}] SCRIPT ERROR: {error!r}"
            print(line)
            results.append({"topic": name, "naive_worked": False, "secure_blocked": False, "line": line})

    worked = sum(r["naive_worked"] for r in results)
    blocked = sum(r["secure_blocked"] for r in results)
    summary = ["", f"Summary: {len(results)} attacks - naive app: {worked} worked; "
               f"SecureShop: {blocked} blocked. ({time.time() - start:.0f}s)"]
    print("\n".join(summary))

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(header + [r["line"] for r in results] + summary) + "\n")
    print(f"Saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
