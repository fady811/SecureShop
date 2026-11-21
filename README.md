# SecureShop

A small online shop built for **CET431 Software Security**, made to resist the
attacks taught in the course. Python + Flask + SQLite, team of 7.

- Allowed libraries: **Flask, argon2-cffi, pyotp** + the Python standard library (no ORM).
- `requests` is used **only** by the attack scripts (`attack_scripts/requirements.txt`).

## 1. Setup

You need Python 3.10 or newer.

**macOS / Linux**

```bash
cd SecureShop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r attack_scripts/requirements.txt    # only for the attack scripts
```

**Windows (PowerShell)**

```powershell
cd SecureShop
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r attack_scripts/requirements.txt
```

## 2. Run SecureShop

```bash
python seed.py      # deletes and re-creates secureshop.db, prints the accounts
flask run           # http://127.0.0.1:5000
```

- **macOS:** if port 5000 is busy (AirPlay Receiver uses it), run `flask run -p 5050` and open <http://127.0.0.1:5050>.
- Debug mode is **off** on purpose (fail secure). Only on your own machine while developing: `flask run --debug`.
- For a real deployment set a fixed key: `export SECRET_KEY=<long random string>`. Without it a new random key is made at every start (everyone is logged out on restart).

### Test accounts (created by `seed.py`)

| Role | Username | Password | Store credit |
|------|----------|----------|--------------|
| user | `shopper` | `Shopper-Pass-2026` | $100.00 |
| user | `victim` | `Victim-Pass-2026` | $50.00 (used by the attack scripts) |
| admin | `admin` | `Admin-Pass-2026!` | $0.00 |

You log in with the **username**. The admin also needs a 6‑digit **2FA code**:
`seed.py` prints the admin's TOTP secret (a new one every run) and this command,
which prints the current code:

```bash
python -c "import pyotp; print(pyotp.TOTP('<SECRET FROM seed.py>').now())"
```

You can also type the secret into an authenticator app (manual entry). A code
works once; for the next login wait for the next code (30 seconds).

Test coupons: `WELCOME5` (5 %), `SAVE20` (20 %, max $50, cart $50+, 30 days),
`TENOFF` ($10 off, cart $30+), `OLD10` (expired). Product id 9 is hidden.

**Fake emails:** there is no mail server. Confirmation links, reset links and
newsletter coupons are written as `.txt` files into `outbox/`.

## 3. Run the tests

```bash
python -m unittest discover tests -v      # 113 tests, uses a temporary database
```

## 4. The naive (vulnerable) demo app

`naive_demo/naive_app.py` is **VULNERABLE ON PURPOSE – for the class demo only**.
It has the naive version of every feature (price from the form, stacking coupons,
SQL injection, MD5 passwords, …), each mistake marked `# VULNERABLE:`. SecureShop
never imports it. It only listens on 127.0.0.1.

```bash
python naive_demo/seed_naive.py     # creates naive_demo/naive.db
python naive_demo/naive_app.py      # http://127.0.0.1:5001
```

## 5. Run the attack scripts

With **both** apps running:

```bash
python attack_scripts/run_all.py
# if SecureShop runs on another port:
SECURE_URL=http://127.0.0.1:5050 python attack_scripts/run_all.py
```

For safety, the attack scripts accept only HTTP URLs with a loopback IP address
(`127.0.0.1` or `::1`); they cannot be pointed at remote systems.

Each script runs the same attack against both apps and prints e.g.

```
[Price tampering (Lab 1)] naive: ATTACK WORKED (paid $0.01 for the jacket)   |   SecureShop: ATTACK BLOCKED (price from database: $1,337.00, ...)
```

`run_all.py` re-creates both databases first and saves the output to
`docs/evidence/attack_results.txt`. Last run: **17 attacks – naive 17 worked,
SecureShop 17 blocked.** One script can be run alone, e.g.
`python attack_scripts/08_price_tampering.py`.

## 6. Architecture (one page)

```
Browser ── HTTP + signed session cookie ──►  Flask app (app.py)
                                              │
                                              ├─ security.py   before every request:
                                              │     session → g.user (role + session_version from the DB),
                                              │     login_required / admin_required (role + 2FA), log_audit
                                              │
                                              ├─ blueprints (one file per member)
                                              │     auth.py     register, confirm, login, lockout, TOTP, reset
                                              │     catalog.py  list, search, filter, allow-listed sort
                                              │     cart.py     session cart {product_id: qty}, prices from DB
                                              │     coupons.py  check_coupon(), one code, guess limit, newsletter
                                              │     orders.py   BEGIN IMMEDIATE payment, public order ids
                                              │     account.py  profile (2 fields only), password change
                                              │     admin.py    users, products, coupons, audit log
                                              │
                                              ├─ templates/ (Jinja2, autoescape, no |safe)
                                              │
                                              ├─ db.py ── sqlite3, "?" placeholders only ──► secureshop.db
                                              │                                          (CHECK + UNIQUE rules)
                                              └─ outbox/  fake emails (.txt)
```

**Main security ideas:**

1. **Never trust the browser.** Prices, totals, roles and user ids come from the database, never from a form, URL or cookie. Extra fields are ignored.
2. **Check again where it matters.** The cart, the coupon, stock and credit are checked again inside the payment transaction.
3. **Reject, never "fix".** Too long, empty or wrong input gets a clear error. Nothing is cut silently.
4. **Defense in depth.** The Python check comes first, and a CHECK/UNIQUE constraint in `schema.sql` is the safety net.
5. **Same answer for different failures.** Login, forgot password and other people's orders do not reveal what exists.
6. **Fail secure + accountability.** No stack traces, everything rolls back on error, and every security event goes into `audit_log`.

More detail: see the documents below.

## 7. Project structure

```
SecureShop/
├── app.py  config.py  db.py  security.py           shared (Member 7)
├── auth.py                                          Member 1
├── catalog.py                                       Member 2
├── cart.py                                          Member 3
├── coupons.py                                       Member 4
├── orders.py                                        Member 5
├── account.py  admin.py                             Member 6
├── schema.sql  seed.py  common_passwords.txt  requirements.txt
├── templates/   base.html, index.html, error.html, auth/, catalog/, cart/, coupons/, orders/, account/, admin/
├── static/style.css
├── tests/       base.py + test_auth, test_catalog, test_cart, test_coupons, test_orders, test_account, test_admin
├── naive_demo/  naive_app.py, seed_naive.py          VULNERABLE ON PURPOSE
├── attack_scripts/  common.py, 01..17_*.py, run_all.py, requirements.txt
├── outbox/      fake emails (created automatically, not in git)
└── docs/
    ├── 01_requirements_and_design.md
    ├── 02_threat_model.md
    ├── 03_security_coverage_matrix.md
    ├── 04_attack_evidence.md
    ├── evidence/attack_results.txt
    ├── team/member1.md … member7.md   (Arabic, one per member)
    └── GIT_PLAN.md
```

## 8. Team rules

- Each member works in **their own files** (see `docs/01_requirements_and_design.md` section 5). Talk to the team before changing shared files.
- Every SQL query uses `?` placeholders. Never use `|safe` on user data.
- Mark security code with a `# SECURITY:` comment.
- Run all tests before every commit. Commit order: `docs/GIT_PLAN.md`.

## Documents

- [Requirements and design](docs/01_requirements_and_design.md)
- [Threat model (STRIDE + DREAD)](docs/02_threat_model.md)
- [Security coverage matrix](docs/03_security_coverage_matrix.md)
- [Attack evidence](docs/04_attack_evidence.md)
- [Git plan](docs/GIT_PLAN.md) · [Team files](docs/team/)
