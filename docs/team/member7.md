# Member 7 – الأساس المشترك، الدوكيومنتس، والـ attack demo

إنت الشخص اللي ماسك **الأرضية** اللي كل الناس بتبني عليها، و**الإثبات** إن الحمايات شغالة.

ملفاتك:

- **الأساس المشترك:** `app.py`، `db.py`، `security.py`، `config.py`، `schema.sql`، `seed.py`، `requirements.txt`، `README.md`، `.gitignore`، `templates/base.html`، `templates/index.html`، `templates/error.html`، `static/style.css`، `tests/base.py`
- **الدوكيومنتس:** `docs/01_requirements_and_design.md`، `docs/02_threat_model.md` (STRIDE + DREAD)، `docs/03_security_coverage_matrix.md`، `docs/04_attack_evidence.md`، `docs/evidence/attack_results.txt`
- **الموقع الضعيف عن قصد:** `naive_demo/naive_app.py`، `naive_demo/seed_naive.py`
- **الهجمات:** `attack_scripts/common.py`، `attack_scripts/01_sql_injection.py` ... `17_brute_force.py`، `attack_scripts/run_all.py`، `attack_scripts/requirements.txt`

---

## 1. الملفات والدوال اللي بتاعتك

### `app.py`

| الحاجة | بتعمل إيه |
|--------|-----------|
| `app.config.from_object(config)` + `PERMANENT_SESSION_LIFETIME` | بياخد كل الإعدادات من `config.py`، والسيشن تعيش `SESSION_LIFETIME_MINUTES` (30). |
| `os.makedirs(config.OUTBOX_DIR, exist_ok=True)` | فولدر `outbox/` للإيميلات الوهمية. |
| `app.teardown_appcontext(close_db)` | يقفل الداتابيز بعد كل request. |
| `app.before_request(load_logged_in_user)` | قبل كل request يعرف مين اليوزر. |
| `app.register_blueprint(...)` × 7 | `auth`، `catalog`، `cart`، `coupons`، `orders`، `account`، `admin`. |
| `money(cents)` (template filter) | `{{ 133700|money }}` → `$1,337.00`. |
| `cart_count()` (context processor) | عدد الحاجات في الكارت للمنيو (0 لو مش عامل login). |
| `index()` | `GET /` → `index.html`. |
| `ERROR_MESSAGES` + `render_error(error)` | صفحات error لطيفة لـ 400/403/404/405/413/500، **من غير stack trace**. |

### `db.py`

| الدالة | بتعمل إيه |
|--------|-----------|
| `get_db()` | connection واحدة لكل request في `g.db`، `row_factory = sqlite3.Row`، و `PRAGMA foreign_keys = ON`. |
| `close_db(error=None)` | تقفل الـ connection. |
| `query_one(sql, params=())` | SELECT ويرجع أول صف أو `None`. |
| `query_all(sql, params=())` | SELECT ويرجع كل الصفوف. |

### `security.py`

| الدالة | بتعمل إيه |
|--------|-----------|
| `load_logged_in_user()` | تقرا `session["user_id"]`، تجيب اليوزر من الداتابيز، وتتأكد إن `session["session_version"] == users.session_version` وإنه مش `is_disabled`. غير كده → `session.clear()`. |
| `bump_session_version(user_id)` | `session_version + 1` → كل السيشنز القديمة بتاعة اليوزر تبطل. |
| `login_required(view)` | لو `g.user is None` → `Please log in to continue.` ورجوع لـ `auth.login` (من غير `?next=`). |
| `admin_required(view)` | لازم `g.user["role"] == "admin"` **و** `session.get("mfa_done") is True`، غير كده `log_audit("admin_access_denied", ...)` و `abort(403)`. |
| `client_ip()` | `request.remote_addr` أو `"unknown"`. |
| `log_audit(action, details="", user_id=None)` | صف في `audit_log` (`details[:500]`) وبتعمل `commit`. |

### `config.py` (أهم القيم)

`SECRET_KEY` (من الـ environment أو `secrets.token_hex(32)`)، `DEBUG = False`، `SESSION_COOKIE_HTTPONLY = True`، `SESSION_COOKIE_SAMESITE = "Lax"`، `SESSION_COOKIE_SECURE = False`، `SESSION_LIFETIME_MINUTES = 30`، `MAX_CONTENT_LENGTH = 1 MB`،
حدود الإدخال (`MAX_USERNAME_LENGTH = 30`، `MAX_EMAIL_LENGTH = 254`، `MAX_NAME_LENGTH = 100`، `MIN_PASSWORD_LENGTH = 10`، `MAX_PASSWORD_LENGTH = 128`، `MAX_QUANTITY_PER_ITEM = 10`، ...)،
`LOCKOUT_AFTER_FAILURES = 5`، `LOCKOUT_BASE_SECONDS = 60`، `LOCKOUT_MAX_SECONDS = 1800`، `TOTP_PENDING_MINUTES = 5`، `RESET_TOKEN_MINUTES = 15`، `CONFIRM_TOKEN_HOURS = 24`، `MAX_DISCOUNT_PERCENT = 30`، `STARTING_CREDIT_CENTS = 10000`.

### `schema.sql`، `seed.py`، `tests/base.py`

- `schema.sql`: 12 جدول. الفلوس **سنتات INTEGER**. CHECK constraints كخط دفاع تاني (مثلًا `store_credit_cents >= 0`، `price_cents > 0`، `quantity BETWEEN 1 AND 10`، percent 1–30، `total_cents = subtotal_cents - discount_cents`). `session_version`، `totp_last_step`، `checkout_token UNIQUE`، `UNIQUE (coupon_id, user_id)`، والتوكنز متخزنة SHA-256.
- `seed.py`: `main()` بيمسح ويعمل `secureshop.db`: 3 يوزرز (Argon2id بـ `PasswordHasher()`)، 8 منتجات + 1 مخفي، 4 كوبونات (`WELCOME5`، `SAVE20`، `TENOFF`، `OLD10` منتهي). بيطبع `Admin TOTP secret` وأمر `python -c "import pyotp; ..."`.
- `tests/base.py`: `BaseTestCase` – داتابيز مؤقتة لكل تست (`setUp` / `tearDown`)، وهيلبرز: `sql`، `insert`، `make_user`، `log_in(user_id, mfa_done=False)`، `make_product`، `make_coupon`، `session_value`، `audit_actions`، `count`، `now`.

### `naive_demo/` و `attack_scripts/`

- `naive_app.py`: نسخة **VULNERABLE ON PURPOSE** على `127.0.0.1:5001`. كل غلطة عليها `# VULNERABLE:`. **SecureShop عمره ما بيعمل import ليها.**
- `seed_naive.py`: بيعمل `naive_demo/naive.db` (MD5 من غير salt، ومفيش CHECK). الحسابات: `shopper / sunshine123`، `admin / Admin-Pass-2026!`، `victim / Victim-Pass-2026`، وطلب واحد لـ victim (id 1) لديمو الـ IDOR.
- `common.py`: `NAIVE` و `SECURE` (من `NAIVE_URL` / `SECURE_URL`)، `report()`، `db_rows()`، `db_write()`، `newest_email()`، `secure_login()`، `secure_admin_login()`، `secure_cart_total()`، `secure_checkout_token()`، `secure_user()`، `naive_login()`، `naive_user()`.
- `01`–`17`: كل سكريبت فيه `run()` بيعمل **نفس الهجمة** على الاتنين وبيرجع `report(...)`.
- `run_all.py`: `check_running()` ثم `main()`.

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

### أ) request واحد من أوله لآخره: shopper بيفتح `GET /orders/<public_id>`

1. Flask بيقرا كوكي `session` ويتأكد من التوقيع بـ `SECRET_KEY`. لو حد عدل فيها (مثلًا `user_id` 1 → 2) التوقيع بيبوظ والسيشن بتتشال (ده الحل لـ Lab 3 `verify=carlos`).
2. `before_request` → `load_logged_in_user()`:
   - `user_id = session.get("user_id")`. (لاحظ: `pending_2fa_user_id` **مش** login.)
   - `query_one("SELECT id, username, ..., session_version FROM users WHERE id = ?", (user_id,))`
   - `query_one` بينادي `get_db()` → أول مرة في الـ request بيفتح connection، يحط `row_factory`، ويشغل `PRAGMA foreign_keys = ON`.
   - لو اليوزر مش موجود أو `is_disabled == 1` أو `session_version` مختلف → `session.clear()` و `g.user = None`. غير كده `g.user = user`.
3. الـ view عليها `@login_required` → `g.user` موجود فنكمل.
4. `orders.find_my_order()` → `query_one("... WHERE public_id = ? AND user_id = ?", ...)` (`?` placeholders زي ما `db.py` بيقول).
5. `render_template` → `base.html` بيستعمل `cart_count` (context processor) و `|money` (filter)، وكل حاجة autoescaped.
6. لو حصل 404/403/500 → `render_error()` بيرجع `error.html` برسالة من `ERROR_MESSAGES` بس.
7. `teardown_appcontext` → `close_db()`.

لو الطلب كان لصفحة أدمن: بعد خطوة 2 بيشتغل `admin_required` → الدور من `g.user` (يعني من الداتابيز) + `mfa_done`، وإلا `admin_access_denied` في `audit_log` و 403.

### ب) `naive_demo` بيشتغل إزاي

- `python naive_demo/seed_naive.py` ثم `python naive_demo/naive_app.py` → `http://127.0.0.1:5001`.
- أمثلة للغلطات المقصودة (كلها في `naive_app.py`):
  - `current_user()`: اليوزر من كوكي `user_id` عادية ومتلزقة في الـ SQL.
  - `register()`: `email[:255]` والـ role من `@secureshop.com` (Lab 2.2).
  - `login()`: رسالتين مختلفتين `Unknown username.` / `Wrong password.`، ومفيش lockout.
  - `login2()`: كوكي `verify` بالـ username، وكود 4 أرقام بـ `random.randint`، والكود مش بيتمسح (Lab 3).
  - `search()`: SQL بالـ `+` و `{{ q|safe }}` (SQLi + XSS).
  - `cart_add()`: السعر من hidden field (Lab 1) والكمية مش متشيكة.
  - `coupon_apply()`: الكوبونات بتتجمع في list (Lab 2.1).
  - `order_confirm()`: فتح الصفحة **بيعمل** طلب paid (Lab 2.3).
  - `order()`: من غير `AND user_id = ?` (IDOR). `admin()`: بيصدق كوكي `role`.
  - `show_error()`: بيطبع `traceback.format_exc()` (عكس fail secure).

### ج) `run_all.py` بيشتغل إزاي

1. `check_running()` على `NAIVE` و `SECURE` (لو واحد مش شغال بيقف ويقولك تشغله).
2. لو مفيش `--no-reseed`: بيشغل `seed.py` و `seed_naive.py` من جديد (output مخفي) عشان كل run تبدأ من نفس الحالة.
3. بيعمل `importlib.import_module(name).run()` لكل سكريبت في `SCRIPTS` بالترتيب (`17_brute_force` آخر واحد لأنه بيقفل `victim` دقيقة).
4. لو سكريبت وقع: بيكتب `SCRIPT ERROR` ويكمل.
5. بيطبع Summary ويكتب كله في `docs/evidence/attack_results.txt`. آخر run: `17 attacks - naive app: 17 worked; SecureShop: 17 blocked.`

بعض السكريبتات بتقرا الداتابيز أو `outbox/` محليًا (مثلًا `secure_admin_login()` بيقرا الـ TOTP secret). ده بيمثل حاجة المهاجم ممكن يجيبها بطريقة تانية (كود متسرق، إيميل reset)، ومكتوب في كل سكريبت.

---

## 3. الحمايات

| الحماية | فين بالظبط | بتوقف إيه | المحاضرة / اللاب |
|---------|------------|-----------|------------------|
| السيشن موقعة بـ `SECRET_KEY` عشوائي، وفيها `user_id` بس | `config.py`؛ `auth.finish_login()` | تعديل الكوكي (`verify=carlos`، `user_id=2`، `role=admin`) | **Lab 3** (cookie tampering) |
| `session_version` بيتقارن في كل request + يوزر disabled يتطرد | `security.py` `load_logged_in_user()`، `bump_session_version()`؛ `schema.sql` | كوكي قديمة متسرقة بعد logout / تغيير باسورد / تغيير دور | Lab 3 / **Lecture 5** |
| الدور بيتقري من الداتابيز كل request | `load_logged_in_user()` | أدمن اتشال منه الدور يفضل أدمن | **Lecture 2** (least privilege) |
| `admin_required`: role + `mfa_done` + 403 + `admin_access_denied` | `security.py` | يوزر عادي في `/admin`، أو أدمن من غير كود 2FA | Lecture 2، **Lecture 5** (MFA)، Lab 3 |
| `login_required` من غير `?next=` | `security.py` | open redirect | – |
| `?` placeholders + `PRAGMA foreign_keys = ON` | `db.py` | **SQL injection**، صفوف يتيمة | **Lecture 2** |
| CHECK constraints (سنتات، `>= 0`، 1–30%، أطوال) | `schema.sql` | لو حد نسي check في الكود (infinite money، سعر 0، كوبون 90%) | Lab 1 / **Lab 2.1** / **Lab 2.2** |
| `UNIQUE (coupon_id, user_id)`، `orders.checkout_token UNIQUE`، `public_id UNIQUE` | `schema.sql` | كوبون مرتين، دفع مرتين، IDOR بأرقام متسلسلة | Lab 2.1 / Lab 2.3 / Lecture 2 |
| `DEBUG = False` + `render_error()` + `error.html` | `config.py`، `app.py` | stack trace وكونسول Werkzeug | **Lecture 3** (fail secure) |
| `MAX_CONTENT_LENGTH = 1 MB` (413) | `config.py` | body ضخم (DoS) | Lecture 3 |
| `HttpOnly`، `SameSite=Lax`، 30 دقيقة | `config.py`، `app.py` | سرقة الكوكي بـ XSS، والطلبات من مواقع تانية | Lecture 2 (XSS) |
| حدود الإدخال في مكان واحد | `config.py` | Lab 2.2 (كل ملف يستعمل نفس الحد) | **Lab 2.2** |
| `log_audit()` + جدول `audit_log` | `security.py`، `schema.sql` | الإنكار (repudiation)، brute force ميتشافش | **Lecture 2** (audit log) |
| Argon2id في `seed.py` + admin عنده `totp_secret` | `seed.py` | باسوردات الـ seed تبقى مكشوفة لو الداتابيز اتسرقت | **Lecture 4** (hashing) |
| Threat model: STRIDE لكل feature (F1–F7) + DREAD (T1–T16) + data flow diagram | `docs/02_threat_model.md` | – (design) | **Lecture 2** (threat modelling) |
| Jinja2 autoescape + تعليق "never use `|safe`" | `templates/base.html` | XSS | Lecture 2 |

### كل الهجمات (`docs/evidence/attack_results.txt`)

| # | السكريبت | الموضوع | النتيجة في SecureShop |
|---|----------|---------|-----------------------|
| 01 | `01_sql_injection.py` | SQLi في البحث (L2) | 0 found، مفيش hashes |
| 02 | `02_xss.py` | XSS في البحث (L2) | `&lt;script&gt;` نص |
| 03 | `03_debug_errors.py` | stack trace (L3) | صفحات لطيفة بس |
| 04 | `04_user_enumeration.py` | رسايل login (L5) | `Invalid username or password.` |
| 05 | `05_password_storage.py` | تخزين الباسورد (L4) | Argon2id: 0/103، ~35 تخمين/ث مقابل ~2.2 مليون لـ MD5 |
| 06 | `06_weak_password.py` | باسورد ضعيف (L4) | `This password is too common` |
| 07 | `07_email_truncation.py` | Lab 2.2 | `Email must be at most 254 characters` |
| 08 | `08_price_tampering.py` | Lab 1 | السعر $1,337.00 والدفع اترفض |
| 09 | `09_coupon_stacking.py` | Lab 2.1 | كوبون واحد بس |
| 10 | `10_negative_quantity.py` | كمية سالبة | `Quantity must be a whole number from 1 to 10.` |
| 11 | `11_workflow_skip.py` | Lab 2.3 | 404 / 405 / مفيش طلب |
| 12 | `12_idor.py` | IDOR (L2) | 404 / 404 |
| 13 | `13_admin_cookie.py` | كوكي `role=admin` | 403 / 302 |
| 14 | `14_2fa_bypass.py` | Lab 3 كوكي `verify` | رجوع للـ login، `/admin/` 403 |
| 15 | `15_2fa_reuse.py` | إعادة كود TOTP (L5) | `Invalid code` |
| 16 | `16_reset_token.py` | reset link (L4–L5) | reuse → 400، بعد 15 دقيقة → 400 |
| 17 | `17_brute_force.py` | brute force (L4، Lab 3) | lock بعد 5 محاولات |

الـ tests بتاعتك بشكل غير مباشر: `tests/base.py` بيستعمله كل `tests/test_*.py`. شغلها كلها بـ `python -m unittest discover tests -v`.

---

## 4. ديمو في دقيقتين

**التحضير (قبل ما تقف قدامهم):**

```bash
pip install -r requirements.txt
pip install -r attack_scripts/requirements.txt
python seed.py
flask run -p 5050                       # تيرمنال 1 (على الماك 5000 ممكن يكون AirPlay)
python naive_demo/seed_naive.py
python naive_demo/naive_app.py          # تيرمنال 2 (port 5001)
```

1. **(30 ثانية) نفس الهجمة، موقعين:** افتح `http://127.0.0.1:5001/search?q=<script>alert(1)</script>` → الـ alert بيشتغل في الـ naive.
   افتح `http://127.0.0.1:5050/products/?q=<script>alert(1)</script>` → بيظهر كنص.
2. **(20 ثانية) Fail secure:** `http://127.0.0.1:5001/product/abc` → stack trace كامل بالمسارات.
   `http://127.0.0.1:5050/products/abc` → `We could not find that page.`
3. **(30 ثانية) Lab 3 كوكي في Burp:** في الـ naive افتح `/admin` في Burp وزود `Cookie: role=admin` → قايمة كل اليوزرز وهاشات MD5.
   في SecureShop اعمل login بـ `shopper` / `Shopper-Pass-2026`، افتح `/admin/users` وزود نفس الكوكي → **403**. وجرب تغير حرف في كوكي `session` → بتبقى مش عامل login.
4. **(40 ثانية) كل الهجمات مرة واحدة** (تيرمنال 3):
   ```bash
   SECURE_URL=http://127.0.0.1:5050 python attack_scripts/run_all.py
   ```
   الجمهور يشوف 17 سطر، كل سطر `naive: ATTACK WORKED | SecureShop: ATTACK BLOCKED`، وفي الآخر `17 worked; ... 17 blocked`.
   افتح `docs/evidence/attack_results.txt` → نفس النتيجة متسجلة.

**تحذير:** `run_all.py` بيعمل reseed للداتابيز، فالـ admin TOTP secret **بيتغير** ومش بيتطبع. لو هتعمل ديمو أدمن بعدها: شغل `python seed.py` تاني وخد السيكريت الجديد، أو استعمل `--no-reseed`. و `victim` بيبقى locked دقيقة بعد `17_brute_force.py`.

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **إيه اللي بيحصل لو اليوزر عدل كوكي السيشن؟**
   السيشن بتاعة Flask موقعة بـ `SECRET_KEY`. أي تعديل بيبوظ التوقيع وFlask بيرمي السيشن كلها. ده عكس Lab 3 اللي كان بيصدق `verify=carlos`. وإحنا مش بنحط في السيشن غير `user_id` و `session_version` و `mfa_done` (من غير أسرار).

2. **لو حد سرق الكوكي، وبعدين صاحب الحساب عمل logout؟**
   logout وتغيير الباسورد وتغيير الدور بيزودوا `users.session_version`. `load_logged_in_user()` بيقارن الرقم في كل request، فالكوكي القديمة بتبطل. التستات: `test_old_cookie_rejected_after_logout`، `test_old_cookie_rejected_after_password_change`.

3. **ليه CHECK constraints في `schema.sql` لو الكود بيتشيك أصلًا؟**
   defense in depth: لو حد نسي check في Python، الداتابيز ترفض (`IntegrityError`) بدل ما الكريدت يبقى سالب أو الكوبون 90%. ده كمان fail secure.

4. **إزاي ضمنت إن مفيش SQL injection في المشروع كله؟**
   `db.py` بيفرض `?` placeholders، وكل الـ queries ماشية عليه. الـ `ORDER BY` في الكاتالوج من allow-list (`SORT_OPTIONS`). الإثبات: `01_sql_injection.py` (0 found) و `test_sql_injection_in_search_returns_no_extra_rows`.

5. **إيه معنى fail secure في مشروعكم؟**
   `DEBUG = False`، و `render_error()` بيرجع رسالة قصيرة من `ERROR_MESSAGES` مش stack trace، والـ transactions بتعمل rollback، والأدمن من غير TOTP secret مش بيدخل. `03_debug_errors.py` بيقارن ده بالـ naive اللي بيطبع `traceback`.

6. **ليه الفلوس integer سنتات؟**
   عشان الـ float فيه rounding (0.1 + 0.2). `133700` يعني $1,337.00، والعرض بس بيتحول بالـ filter `money`.

7. **عملتوا threat modelling إزاي؟**
   في `docs/02_threat_model.md`: الأصول، نقط الدخول، أنواع المهاجمين، data flow diagram بالـ trust boundaries، STRIDE لكل feature (F1–F7)، و DREAD لأهم 16 تهديد (أعلاها T1 price tampering = 9.4). DREAD subjective فاستعملناه للترتيب بس.

8. **الـ naive app ده خطر على المشروع؟**
   لأ. هو ملف منفصل في `naive_demo/`، SecureShop عمره ما بيعمل import ليه، وبيسمع على `127.0.0.1:5001` بس، وداتابيزه `naive_demo/naive.db` منفصلة وفي `.gitignore`. فايدته إنه يثبت إن نفس الهجمة بتنجح هناك وبتفشل عندنا.

9. **ليه السكريبتات بتقرا الداتابيز؟ مش ده غش؟**
   بتقرا عشان **تعرض** النتيجة (مثلًا الكريدت قبل وبعد) أو عشان تلعب دور حاجة المهاجم ممكن يحصلها (كود 2FA متسرق في `15_2fa_reuse.py`، رابط reset قديم في `16_reset_token.py`). الهجمة نفسها بتتبعت كـ HTTP عادي بـ `requests`. وده مكتوب في `common.py` وفي كل سكريبت.

10. **إيه اللي بيتسجل في الـ audit log وإيه اللي لأ؟**
    `log_audit()` بتسجل `user_id`، `action`، `details`، `ip_address`، والوقت: login، lockout، 2FA، الطلبات، الكوبونات، كل تغيير أدمن (old -> new)، و `admin_access_denied`. **مش** بنسجل باسوردات ولا توكنز ولا أكواد TOTP (مكتوب في الـ docstring). ده accountability من Lecture 2.
