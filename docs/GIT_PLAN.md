# Git plan – who commits what, and in which order

> **Nobody has run these commands yet.** They are a plan for the team to run.
> The project folder is not a git repository today. Read the whole page once
> before the first command.

Goal: every member has **real commits of their own part**, made from their own
machine and their own GitHub account, and the history still makes sense
(nothing is committed before the files it needs).

---

## 0. The one approach we use (and why)

**Member 7 commits the shared base first, with the final `app.py` (all 7
`register_blueprint` lines already in it). Then each member commits only their
own files, in the order below. The full app (and the test suite) runs from the
moment the last feature commit (Member 6) lands.**

Why not "Member 7 starts with an `app.py` that has no blueprints, and each
member adds their own import + `register_blueprint` line"?
Because it would not make the in-between versions runnable anyway:
`templates/base.html` (the menu on every page) calls `url_for('catalog.product_list')`,
`url_for('cart.view_cart')`, `url_for('orders.order_history')`, `url_for('account.profile')`,
`url_for('admin.dashboard')`, `url_for('auth.login')` ..., and `templates/index.html` does the
same. Until all 7 blueprints exist, every page fails with a `BuildError`. Editing
`app.py` 7 times would only add work and merge conflicts in one shared file, for
no benefit. So: one `app.py` commit by its owner, and a clear rule that the app
is only expected to run after step 7 below.

Order follows the real imports in the code:

| File | Imports at the top | So it must come after |
|------|--------------------|-----------------------|
| `app.py` | all 7 blueprints | (runs only at the end – see above) |
| `tests/base.py` | `from app import app` | (tests run only at the end) |
| `auth.py` | `config`, `db`, `security`; reads `common_passwords.txt` at import | base |
| `catalog.py` | `config`, `db` | base |
| `cart.py` | `config`, `db`, `security`; imports `coupons` **inside** `view_cart()` | base |
| `coupons.py` | `from auth import send_email`; imports `cart` **inside** `apply_coupon()` | auth |
| `orders.py` | `from cart import ...`, `from coupons import check_coupon` | cart, coupons |
| `account.py` | `from auth import check_password, ph, validate_password` | auth |
| `admin.py` | `config`, `db`, `security` (+ `pyotp`) | base |

`cart.py` and `coupons.py` import each other only inside functions, so there is
no circular-import problem; they just both have to exist before anyone runs the app.

---

## 1. Setup (each member, once)

Each member uses **their own machine and their own account**, so the commit
author is really them:

```bash
git config --global user.name  "Your Name"
git config --global user.email "the-email-of-your-github-account@example.com"
```

(Use the email of your own GitHub account, otherwise GitHub does not link the
commits to you.)

Ignored files – `.gitignore` already lists them, never force-add them:
`.venv/`, `__pycache__/`, `*.pyc`, `secureshop.db`, `outbox/`, `.env`, `.DS_Store`,
`naive_demo/naive.db`, `naive_demo/outbox/`.

Before **every** commit run `git status` and check that only your files are listed.

---

## 2. Step 1 – Member 7: create the repo and commit the shared base

Member 7 creates an empty repository on GitHub (no README, no .gitignore – we
have our own), adds the other 6 as collaborators.

**Important:** do NOT run `git init` inside the finished project folder. It holds
everybody's files; later `git pull` would refuse to bring in the other members'
commits ("untracked working tree files would be overwritten"). Member 7, like
everyone else, works in a **new empty folder** and copies only the files being
committed (base files now, the step-8 files later) from the finished copy:

```bash
mkdir SecureShop-repo && cd SecureShop-repo
# copy the 14 base files listed in the git add lines below, keeping their paths
git init -b main
git add .gitignore requirements.txt README.md
git commit -m "chore: project skeleton, requirements and gitignore"

git add config.py db.py schema.sql seed.py
git commit -m "feat(db): schema with CHECK constraints, sqlite helpers and seed data"

git add security.py app.py templates/base.html templates/index.html templates/error.html static/style.css tests/base.py
git commit -m "feat(core): app setup, session checks, admin_required, audit log and error pages"

git remote add origin https://github.com/<team>/SecureShop.git
git push -u origin main
```

Every other member then clones:

```bash
git clone https://github.com/<team>/SecureShop.git
cd SecureShop
```

and copies **only their own files** from the finished project (shared zip / folder)
into the same paths inside the clone. Example for Member 5 on macOS/Linux
(`FINISHED` is where the finished copy is; keep the quotes, the path has a space):

```bash
mkdir -p templates/orders tests
cp "FINISHED/orders.py" .
cp "FINISHED/templates/orders/checkout.html" "FINISHED/templates/orders/detail.html" "FINISHED/templates/orders/history.html" templates/orders/
cp "FINISHED/tests/test_orders.py" tests/
```

On Windows just copy the same files in Explorer.

**Before every push:** `git pull --rebase origin main`, then `git push`.
Because every member touches different files, the rebase should never conflict.
If it does, stop and ask Member 7 – do not use `--force`.

---

## 3. Steps 2–7 – each member commits their own part (in this order)

The order matters only for a clean history (see section 0). Wait until the
previous member has pushed, then `git pull --rebase origin main` and commit yours.
If a `docs/team/memberN.md` handover file exists for you, commit it with your part.

### Step 2 – Member 1 (auth)

```bash
git add auth.py common_passwords.txt templates/auth/register.html templates/auth/login.html templates/auth/two_factor.html templates/auth/forgot_password.html templates/auth/reset_password.html templates/auth/message.html
git commit -m "feat(auth): registration with Argon2id and email confirmation, lockout, admin TOTP, reset"
git add tests/test_auth.py docs/team/member1.md
git commit -m "test(auth): lockout, 2FA reuse, generic errors and reset token tests"
git pull --rebase origin main && git push
```

### Step 3 – Member 2 (catalog)

```bash
git add catalog.py templates/catalog/list.html templates/catalog/detail.html
git commit -m "feat(catalog): product list with safe search, filters and sort allow-list"
git add tests/test_catalog.py docs/team/member2.md
git commit -m "test(catalog): SQL injection, XSS and bad filter tests"
git pull --rebase origin main && git push
```

### Step 4 – Member 3 (cart)

```bash
git add cart.py templates/cart/cart.html
git commit -m "feat(cart): session cart with prices from the database and quantity 1-10"
git add tests/test_cart.py docs/team/member3.md
git commit -m "test(cart): price tampering and bad quantity tests"
git pull --rebase origin main && git push
```

### Step 5 – Member 4 (coupons) – needs `auth.py` (step 2)

```bash
git add coupons.py templates/coupons/newsletter.html
git commit -m "feat(coupons): one coupon per cart, per-user single use, newsletter coupon"
git add tests/test_coupons.py docs/team/member4.md
git commit -m "test(coupons): stacking, reuse, expiry and guessing limit tests"
git pull --rebase origin main && git push
```

### Step 6 – Member 5 (orders) – needs `cart.py` and `coupons.py`

```bash
git add orders.py templates/orders/checkout.html templates/orders/detail.html templates/orders/history.html
git commit -m "feat(orders): checkout and pay() in one transaction with one-time checkout token"
git add tests/test_orders.py docs/team/member5.md
git commit -m "test(orders): double payment, workflow skip and IDOR tests"
git pull --rebase origin main && git push
```

### Step 7 – Member 6 (account + admin) – `account.py` needs `auth.py`

```bash
git add account.py templates/account/profile.html templates/account/edit.html templates/account/password.html tests/test_account.py
git commit -m "feat(account): profile edit without mass assignment, password change with session_version"
git add admin.py templates/admin/_nav.html templates/admin/dashboard.html templates/admin/users.html templates/admin/totp_secret.html templates/admin/products.html templates/admin/product_form.html templates/admin/coupons.html templates/admin/coupon_form.html templates/admin/audit.html
git commit -m "feat(admin): users, products, coupons and audit log behind admin_required"
git add tests/test_admin.py docs/team/member6.md
git commit -m "test(admin): access control, last admin, credit and validation tests"
git pull --rebase origin main && git push
```

**Checkpoint (anyone, after step 7):** the app is now complete.

```bash
pip install -r requirements.txt
python -m unittest discover tests -v      # all tests must pass
python seed.py
flask run                                  # macOS: flask run -p 5050 if port 5000 is taken
```

---

## 4. Step 8 – Member 7: docs, naive demo, attack scripts, evidence

In `SecureShop-repo`: `git pull --rebase origin main` first, then copy the
`naive_demo/`, `attack_scripts/` and `docs/` files from the finished copy (not
`naive_demo/naive.db`).

```bash
git add naive_demo/naive_app.py naive_demo/seed_naive.py
git commit -m "feat(demo): naive vulnerable shop for side-by-side attacks (never imported)"

git add attack_scripts/requirements.txt attack_scripts/common.py attack_scripts/run_all.py attack_scripts/01_sql_injection.py attack_scripts/02_xss.py attack_scripts/03_debug_errors.py attack_scripts/04_user_enumeration.py attack_scripts/05_password_storage.py attack_scripts/06_weak_password.py attack_scripts/07_email_truncation.py attack_scripts/08_price_tampering.py attack_scripts/09_coupon_stacking.py attack_scripts/10_negative_quantity.py attack_scripts/11_workflow_skip.py attack_scripts/12_idor.py attack_scripts/13_admin_cookie.py attack_scripts/14_2fa_bypass.py attack_scripts/15_2fa_reuse.py attack_scripts/16_reset_token.py attack_scripts/17_brute_force.py
git commit -m "test(attacks): 17 attack scripts against naive app and SecureShop"

git add docs/01_requirements_and_design.md docs/02_threat_model.md docs/03_security_coverage_matrix.md
git commit -m "docs: requirements, STRIDE/DREAD threat model and coverage matrix"

git add docs/04_attack_evidence.md docs/evidence/attack_results.txt docs/team/member7.md docs/GIT_PLAN.md
git commit -m "docs: attack evidence, team handover notes and git plan"

git pull --rebase origin main && git push
```

(`docs/04_attack_evidence.md` is still being written – commit it when it is final.)

Optional, at the very end: `git tag v1.0 && git push origin v1.0`.

---

## 5. Quick rules

- Commit messages: `type(scope): short summary` – types we use: `feat`, `fix`, `test`, `docs`, `chore`.
- Only `git add` the exact files listed – never `git add .` or `git add -A`.
- Never commit `secureshop.db`, `naive_demo/naive.db`, `outbox/`, `.venv/` or a `.env`.
- Always `git pull --rebase origin main` before `git push`. Never `git push --force` on `main`.
- A later fix to your own file = a new commit by you, e.g. `fix(orders): ...`.
- A change to a shared file (`app.py`, `config.py`, `db.py`, `security.py`, `schema.sql`, `templates/base.html`) is agreed with the team first and committed by Member 7.
