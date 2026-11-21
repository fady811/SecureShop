# 04 – Attack Evidence

The project brief asks us to *"show that the attack works against a naive
implementation and fails against our own"*. For every topic we run the **same
attack** against:

| App | URL | What it is |
|-----|-----|-----------|
| Naive app | `http://127.0.0.1:5001` | `naive_demo/naive_app.py` – **vulnerable on purpose**, every mistake marked `# VULNERABLE:` |
| SecureShop | `http://127.0.0.1:5000` | our real app |

The scripts are in `attack_scripts/` (one per topic, `run_all.py` runs them all).
The full output of the last run is in [`evidence/attack_results.txt`](evidence/attack_results.txt).

**Last run: 17 attacks – naive app: 17 worked · SecureShop: 17 blocked.**

## How to run

```bash
pip install -r attack_scripts/requirements.txt         # only "requests", for the scripts
python naive_demo/seed_naive.py && python naive_demo/naive_app.py    # terminal 1, port 5001
python seed.py && flask run                                          # terminal 2, port 5000
python attack_scripts/run_all.py                                     # terminal 3
```

> **macOS:** port 5000 is often taken by *AirPlay Receiver*. Then use
> `flask run -p 5050` and `SECURE_URL=http://127.0.0.1:5050 python attack_scripts/run_all.py`.
> (Our evidence run used port 5050 for this reason.)

`run_all.py` re-creates both databases first, so every run starts the same.
It runs the brute-force attack last because that one locks the `victim` account
for 1 minute.

Some scripts read the local database or `outbox/` to **play** something a real
attacker would get another way: a stolen database file (password cracking), a
sniffed 2FA code, an old reset email. Each script says this at the top.

---

## Results per topic

Screenshot names: save them as `docs/evidence/<number>_<naive|secure>.png`.

### 1. SQL injection (Lecture 2) – `01_sql_injection.py`
- **Attack:** search for `' UNION SELECT username, password_md5 FROM users --`
- **Request:** `GET /search?q=<payload>` (naive) · `GET /products/?q=<payload>` (SecureShop)
- **Naive:** WORKED – the result list shows all 3 usernames with their MD5 hashes.
- **SecureShop:** BLOCKED – `?` placeholder, the text is just searched for: "0 found".
- **Screenshot:** paste the payload into both search boxes in the browser; take both result pages.

### 2. Reflected XSS (Lecture 2) – `02_xss.py`
- **Attack:** search for `<script>alert(document.cookie)</script>`
- **Naive:** WORKED – the tag is in the page (`{{ q|safe }}`), the alert pops up.
- **SecureShop:** BLOCKED – Jinja2 autoescaping shows `&lt;script&gt;` as text.
- **Screenshot:** the alert box on the naive app; the plain text "Results for "<script>…"" on SecureShop. Optional: *View source* to show `&lt;script&gt;`.

### 3. Error pages / stack trace (Lecture 3, fail secure) – `03_debug_errors.py`
- **Attack:** send input that crashes the code: `GET /product/abc` (naive), `GET /products/abc`, `?min_price=abc`, a 5000-character `product_id` (SecureShop).
- **Naive:** WORKED – HTTP 500 with the full stack trace, file paths and code lines.
- **SecureShop:** BLOCKED – custom 404/400 pages with one short sentence; `DEBUG = False`.
- **Screenshot:** both error pages in the browser.

### 4. User enumeration (Lecture 5) – `04_user_enumeration.py`
- **Attack:** log in with an unknown username, then with `admin` + a wrong password; compare the messages.
- **Naive:** WORKED – "Unknown username." vs "Wrong password." → `admin` exists.
- **SecureShop:** BLOCKED – both times "Invalid username or password." (also for locked/unconfirmed/disabled accounts; forgot-password always says "If the account exists, a reset link was sent.").
- **Screenshot:** the two SecureShop login errors side by side (and the two different naive messages).

### 5. Password storage (Lecture 4) – `05_password_storage.py`
- **Attack:** with a stolen copy of the database, run a wordlist (`common_passwords.txt`) against the hashes.
- **Naive:** WORKED – unsalted MD5, `shopper:sunshine123` cracked instantly (~2 million MD5 guesses per second on a laptop).
- **SecureShop:** BLOCKED – Argon2id with a random salt: 0 of 103 guesses matched, and only ~35 guesses per second are possible.
- **Screenshot:** `sqlite3 naive_demo/naive.db "select username, password_md5 from users;"` next to `sqlite3 secureshop.db "select username, password_hash from users;"` (shows `$argon2id$v=19$m=65536,t=3,p=4$…`), plus the script output.

### 6. Weak passwords (Lecture 4) – `06_weak_password.py`
- **Attack:** register with the password `password123`.
- **Naive:** WORKED – account created.
- **SecureShop:** BLOCKED – "This password is too common. Please choose another one." (min 10 chars + common-password list).
- **Screenshot:** the SecureShop registration form with the error.

### 7. Long email → admin (Lab 2.2) – `07_email_truncation.py`
- **Attack:** register with a 268-character email `aaaa…@secureshop.com.attacker.net`; after cutting at 255 it ends in `@secureshop.com`.
- **Naive:** WORKED – the email is cut to 255 characters and the account gets the role `admin`.
- **SecureShop:** BLOCKED – "Email must be at most 254 characters." (rejected, never cut); even a real `@secureshop.com` email gets the role `user`.
- **Screenshot:** Burp Repeater: the register request with the long email and the SecureShop error; `sqlite3 secureshop.db "select username, email, role from users;"`.

### 8. Price tampering (Lab 1) – `08_price_tampering.py`
- **Attack:** add the $1,337.00 jacket with `price=1` (and `total=1`) added to the request, then pay.
- **Request:** `POST /cart/add product_id=2&quantity=1&price=1&total=1`
- **Naive:** WORKED – paid **$0.01** for the jacket.
- **SecureShop:** BLOCKED – the cart shows **$1,337.00** (price from the database); payment refused ("Not enough store credit"), no order created.
- **Screenshot:** Burp Proxy → intercept "Add to cart" on SecureShop, add `&price=1`, forward; then the cart page showing $1,337.00.

### 9. Coupon stacking (Lab 2.1) – `09_coupon_stacking.py`
- **Attack:** with 2 backpacks ($69.00) in the cart apply `WELCOME5`, `SAVE20`, `WELCOME5`, `SAVE20`.
- **Naive:** WORKED – the discounts add up: −$34.50 (50 % off).
- **SecureShop:** BLOCKED – one coupon only; the last code replaces the previous one: `SAVE20` = −$13.80 (20 %). A code can be used once per user (checked again inside `pay()` and by `UNIQUE(coupon_id, user_id)`).
- **Screenshot:** SecureShop cart after the 4 codes, with the message "It replaced WELCOME5 (only one coupon per order)".

### 10. Negative quantity (infinite money) – `10_negative_quantity.py`
- **Attack:** `POST /cart/add product_id=1&quantity=-10`, then pay.
- **Naive:** WORKED – the total is −$150, paying **adds** money: credit went up (e.g. $99.99 → $249.99).
- **SecureShop:** BLOCKED – "Quantity must be a whole number from 1 to 10." Credit unchanged. Same for `0`, `1.5`, `abc`, `99999999999999999999`, and more than the stock.
- **Screenshot:** Burp Repeater with `quantity=-10` and the redirect page showing the error message.

### 11. Skipping the payment step (Lab 2.3) – `11_workflow_skip.py`
- **Attack:** put the jacket in the cart and open the confirmation page without paying.
- **Naive:** WORKED – `GET /order/confirm` created a **paid** $1,337.00 order and charged $0.
- **SecureShop:** BLOCKED – orders are only created inside `pay()` after the credit is taken. `GET /orders/<id>/confirmation` needs an order that is yours **and** `paid` → 404; `GET /checkout/pay` → 405; `POST /checkout/pay` without the one-time checkout token → refused. No order created.
- **Screenshot:** the SecureShop 404 page for a made-up confirmation URL; *My orders* still empty.

### 12. IDOR – other people's orders (Lecture 2) – `12_idor.py`
- **Attack:** log in as `shopper` and open `victim`'s order.
- **Naive:** WORKED – `/order/1` shows the victim's order, name and email.
- **SecureShop:** BLOCKED – orders have a random id (`secrets.token_urlsafe`), and even with the real id `WHERE public_id = ? AND user_id = ?` gives 404 for both the detail and the confirmation page.
- **Screenshot:** log in as victim, buy the notebook, copy the order URL; log in as shopper in a private window and open it → 404.

### 13. Admin page via a role cookie (least privilege, Lecture 2 / Lab 3) – `13_admin_cookie.py`
- **Attack:** add the cookie `role=admin` (and `is_admin=1`) and open the admin page.
- **Naive:** WORKED – the cookie alone opened the list of all users and hashes, without even logging in.
- **SecureShop:** BLOCKED – logged-in shopper + `role=admin` cookie → **403** and an `admin_access_denied` row in the audit log; not logged in → redirect to login. The role is read from the database and the 2FA step must be done.
- **Screenshot:** browser dev tools → add cookie `role=admin` → `/admin/users` shows the 403 page; then the audit log row (as admin).

### 14. 2FA bypass with a "verify" cookie (Lab 3) – `14_2fa_bypass.py`
- **Attack:** set the cookie `verify=admin` (never knowing admin's password) and brute-force the code.
- **Naive:** WORKED – the 4-digit code of admin was found after a few thousand guesses (e.g. 4721) → full admin access.
- **SecureShop:** BLOCKED – logged in as shopper with `verify=admin` and extra `user=admin`, `user_id=2` fields: all 50 code tries are sent back to login (there is no pending login in the signed session), `/admin/` → 403. The real code page reads the user **only** from `session["pending_2fa_user_id"]`; TOTP codes have 6 digits and 5 wrong codes lock the account.
- **Screenshot:** Burp Repeater: `POST /auth/two-factor` with `code=123456&user=admin` and cookie `verify=admin` → `302 Location: /auth/login`.

### 15. 2FA code reuse (Lecture 5) – `15_2fa_reuse.py`
- **Attack:** log in as admin with a code, log out, log in again and replay the same (sniffed) code.
- **Naive:** WORKED – the same code logged in twice (codes are never cleared).
- **SecureShop:** BLOCKED – first use OK; same code again → 401 "Invalid code" (`totp_last_step` must be newer).
- **Screenshot:** run `python -c "import pyotp; print(pyotp.TOTP('<secret>').now())"`, log in, log out, log in again with the same code within 30 s → "Invalid code. Please try again."

### 16. Reset link reuse / expiry (Lectures 4–5) – `16_reset_token.py`
- **Attack:** use a password-reset link twice, and use one after it should have expired.
- **Naive:** WORKED – the same link worked twice; it never expires.
- **SecureShop:** BLOCKED – first use OK; reused → 400 "invalid, already used or expired"; a link older than 15 minutes → 400. (The script makes the link "old" by changing `expires_at` in the database instead of waiting 15 minutes.)
- **Screenshot:** open the reset link from `outbox/` twice; the second time shows "Link not valid".

### 17. Online brute force (Lecture 4, Lab 3) – `17_brute_force.py`
- **Attack:** try 20 common passwords for `victim`, then the right one (Burp Intruder style).
- **Naive:** WORKED – logged in on guess 21, no lockout.
- **SecureShop:** BLOCKED – locked after 5 wrong tries (1 minute, doubling up to 30 minutes); the correct 21st guess was refused too, with the same generic message. `login_failed` and `account_locked` rows in `audit_log`.
- **Screenshot:** Burp Intruder results table (same response length for every try), then the admin *Audit log* page filtered by `account_locked`.

---

## Defenses that the unit tests prove (no separate script)

| Defense | Test(s) |
|---------|---------|
| Double payment charges once | `tests/test_orders.py` `test_double_payment_charges_once` |
| Coupon used only once after a real order | `test_coupon_used_only_once_after_real_order` |
| Old session cookie rejected after logout / password change | `tests/test_account.py` `test_old_cookie_rejected_after_logout`, `test_old_cookie_rejected_after_password_change` |
| Mass assignment ignored (`role=admin` in the profile form) | `test_mass_assignment_ignored` |
| Every admin route refuses a normal user | `tests/test_admin.py` `test_normal_user_cannot_open_any_admin_page` (finds all admin routes automatically) |
| Admin cannot demote / disable themselves; credit never negative | `test_admin_cannot_demote_or_disable_themselves`, `test_credit_cannot_go_negative` |

Run them with `python -m unittest discover tests -v` (113 tests).
