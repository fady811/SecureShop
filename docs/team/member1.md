# Member 1 – التسجيل والدخول والـ 2FA (`auth.py`)

الملفات بتاعتك: `auth.py`، `templates/auth/*`، `tests/test_auth.py`، `common_passwords.txt`.
ملفات بتستخدمها ولازم تفهمها: `security.py`، `config.py`، جدول `users` في `schema.sql`.

---

## 1. الملفات والدوال اللي بتاعتك

### الثوابت في أول `auth.py`

| الاسم | بيعمل إيه |
|------|-----------|
| `ph = PasswordHasher()` | Argon2id بالإعدادات الافتراضية، و salt عشوائي لكل hash |
| `DUMMY_HASH` | hash وهمي بنعمل عليه verify لما الـ username مش موجود (عشان الوقت يبقى واحد) |
| `GENERIC_LOGIN_ERROR` | `"Invalid username or password."` |
| `GENERIC_RESET_MESSAGE` | `"If the account exists, a reset link was sent."` |
| `USERNAME_PATTERN` / `EMAIL_PATTERN` | regex للـ username (حروف وأرقام و `_`) وللإيميل |
| `COMMON_PASSWORDS` | الباسوردات الضعيفة من `common_passwords.txt` (103 سطر)، بتتقري مرة واحدة |

### الدوال المساعدة

| الدالة | بتعمل إيه في سطر |
|--------|------------------|
| `load_common_passwords()` | تقرا `common_passwords.txt` وترجّع set بحروف صغيرة |
| `validate_username(username)` | 3–30 حرف، وبس `[A-Za-z0-9_]`، وإلا ترجّع رسالة خطأ |
| `validate_email(email)` | مش فاضي، ≤ 254 حرف، شكله صح. **الطويل بيترفض، مش بيتقص** |
| `validate_password(password, confirm, username)` | 10–128 حرف، مش في القائمة الضعيفة، مش زي الـ username، والتأكيد مطابق |
| `new_token()` | `secrets.token_urlsafe(32)` وترجّع (التوكن للينك، الـ hash للداتابيز) |
| `hash_token(token)` | SHA-256 للتوكن |
| `send_email(to, subject, body)` | تكتب "الإيميل" كملف `.txt` في `outbox/` (اسم الملف وقت + رقم عشوائي، مفيش input من اليوزر) |
| `record_login_attempt(username, success)` | تسجل كل محاولة دخول في `login_attempts` |
| `register_failure(user, reason)` | تزوّد `failed_login_count`؛ عند 5 تقفل الحساب وتضاعف المدة |
| `check_password(user, password)` | `ph.verify()` + `check_needs_rehash()` |
| `waste_time_like_a_password_check(password)` | verify على `DUMMY_HASH` عشان التوقيت ميفضحش حاجة |
| `finish_login(user, mfa_done=False)` | تصفّر العدادات، `session.clear()`، وتحط `user_id` و `session_version` و `mfa_done` |
| `cancel_pending_login(message)` | تمسح السيشن وترجّعك لصفحة الدخول |
| `find_reset_token(token)` | تجيب توكن الريست لو موجود ومش مستخدم ومش منتهي |

### الـ routes (كلها تحت `/auth`)

| Route | الدالة | بتعمل إيه |
|-------|--------|-----------|
| `GET/POST /auth/register` | `register()` | إنشاء حساب `role='user'` و `is_confirmed=0` |
| `GET /auth/confirm/<token>` | `confirm_email()` | تأكيد الإيميل (مرة واحدة، 24 ساعة) |
| `GET/POST /auth/login` | `login()` | الدخول بالـ **username** |
| `GET/POST /auth/two-factor` | `two_factor()` | كود TOTP للأدمن بس |
| `POST /auth/logout` | `logout()` | خروج + `bump_session_version()` |
| `GET/POST /auth/forgot-password` | `forgot_password()` | يبعت لينك ريست (15 دقيقة) |
| `GET/POST /auth/reset/<token>` | `reset_password()` | يغيّر الباسورد بالتوكن |

### التمبلتس

`register.html`، `login.html`، `two_factor.html` (مفيهاش أي hidden field للـ user – مقصود)، `forgot_password.html`، `reset_password.html`، `message.html`.

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

### (أ) يوزر عادي بيسجل ويدخل

1. `POST /auth/register` فيه `username`, `email`, `password`, `confirm_password`.
2. `register()` بتعمل `.strip()` بس (والإيميل `.lower()`)، وبتنادي `validate_username` و `validate_email` و `validate_password`.
3. لو الـ username موجود: `"That username is already taken."` وكود 400.
4. لو الإيميل موجود: **مش بنقول للزائر**. بنبعت إيميل للصاحب الحقيقي (`"Someone tried to register with your email"`) ونسجل `register_duplicate_email`، ونعرض نفس رسالة النجاح.
5. لو جديد: `INSERT INTO users ... VALUES (?, ?, ?, 'user', 0, ?)` – الـ role مكتوب ثابت `'user'`، والـ hash من `ph.hash(password)`، والكريدت `config.STARTING_CREDIT_CENTS` (= $100).
6. `new_token()` → بنخزن الـ hash بس في `email_confirm_tokens` وبنكتب اللينك في `outbox/`.
7. اليوزر يفتح `/auth/confirm/<token>` → `confirm_email()` تعمل `UPDATE ... SET used_at = ? WHERE id = ? AND used_at IS NULL` ولو `rowcount == 1` تخلي `is_confirmed = 1`.
8. `POST /auth/login`: `login()` تدور بـ `SELECT * FROM users WHERE username = ?`. الترتيب:
   - مش موجود → `waste_time_like_a_password_check()` → `fail()`.
   - مقفول (`locked_until > now`) → مش بنشيك الباسورد أصلاً → `fail()`.
   - `is_disabled` → `fail()`.
   - باسورد غلط → `register_failure(user, "wrong password")` → `fail()`.
   - مش متأكد (`is_confirmed = 0`) → `fail()`.
   - كل ده نفس الرسالة `Invalid username or password.` وكود 401.
9. كله تمام ومش أدمن → `finish_login(user)` → `session.clear()` ثم `session["user_id"]`, `session["session_version"]`, `session["mfa_done"] = False`، و `session.permanent = True` (30 دقيقة).
10. في كل request بعد كده `security.load_logged_in_user()` بتقرا اليوزر من الداتابيز وتقارن `session_version`؛ لو مختلف أو الحساب disabled → `session.clear()`.

### (ب) الأدمن (باسورد + TOTP)

1. الباسورد صح و `role == "admin"`. لو مفيش `totp_secret` → `fail()` (fail secure).
2. بنصفّر `failed_login_count` (عشان ياخد 5 محاولات للكود) لكن `lock_count` بيفضل.
3. `session.clear()` ثم `session["pending_2fa_user_id"] = user["id"]` و `session["pending_2fa_started"] = now` → redirect لـ `/auth/two-factor`. **لسه مفيش `user_id`** يعني مش داخل.
4. `two_factor()` تاخد اليوزر من `session.get("pending_2fa_user_id")` بس. لو عدّى أكتر من `config.TOTP_PENDING_MINUTES` (5 دقايق) → `cancel_pending_login`.
5. الكود لازم 6 أرقام و `totp.verify(code, valid_window=1)`؛ بعدين بنعرف رقم الـ time step اللي اتطابق.
6. `UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?` – لو `rowcount == 1` الكود اتقبل. ده بيمنع إعادة استخدام نفس الكود.
7. كود غلط → `2fa_failed` في الـ audit + `register_failure(user, "wrong 2FA code")`. بعد 5 → قفل و `cancel_pending_login("Too many wrong codes. Please log in again later.")`.
8. صح → `finish_login(user, mfa_done=True)`. `admin_required` في `security.py` محتاجة `role == "admin"` **و** `session.get("mfa_done") is True`.

### (ج) نسيت الباسورد

1. `POST /auth/forgot-password` فيه `email` → بنشيك الشكل بس.
2. لو الإيميل موجود: توكن جديد في `password_reset_tokens` (hash بس، 15 دقيقة) وإيميل في `outbox/`.
3. في الحالتين نفس الرسالة `If the account exists, a reset link was sent.`
4. `/auth/reset/<token>` → `find_reset_token()` → باسورد جديد بـ `validate_password()` → `used_at` بشرط `used_at IS NULL` → نمسح باقي توكنات اليوزر → hash جديد + تصفير العدادات + `session_version = session_version + 1`.

---

## 3. الحمايات

| # | الحماية | فين بالظبط | بتمنع إيه | المصدر | الإثبات |
|---|---------|-----------|-----------|--------|---------|
| 1 | Argon2id مع salt، والمقارنة بـ `ph.verify()` مش `==`، و `check_needs_rehash()` | `auth.py`: `ph`, `check_password()`, `register()`, `reset_password()` | سرقة الداتابيز وكسر الباسوردات (MD5 بيتكسر في ثانية) | Lecture 4 (password storage) | سكريبت `05_password_storage.py` (Argon2 ~35 تخمينة/ثانية مقابل ملايين لـ MD5)؛ تست `test_register_always_creates_unconfirmed_normal_user` بيشيك `$argon2id$` |
| 2 | باسورد 10–128، مش من `common_passwords.txt`، مش زي الـ username | `validate_password()` | باسوردات ضعيفة زي `password123` | Lecture 4 (weak passwords) | `06_weak_password.py`؛ `test_weak_password_rejected`, `test_short_password_rejected`, `test_reset_rejects_weak_password` |
| 3 | قفل بعد 5 غلطات: دقيقة، وبتتضاعف مع كل قفل جديد (`lock_count`) لحد 30 دقيقة (`LOCKOUT_MAX_SECONDS`). وقت القفل الباسورد مش بيتشيك أصلاً | `register_failure()`, `login()`; `config.LOCKOUT_AFTER_FAILURES`, `LOCKOUT_BASE_SECONDS` | Brute force (Burp Intruder) | Lecture 4 + Lab 3 (brute force) | `17_brute_force.py` (التخمينة الـ 21 الصح اترفضت)؛ `test_account_locked_after_5_failures`, `test_lock_time_doubles`, `test_lock_time_has_a_maximum` |
| 4 | رسالة واحدة لكل فشل دخول (مش موجود / غلط / مقفول / مش متأكد / disabled)، ورسالة واحدة في forgot-password، والإيميل المكرر في التسجيل مش بيبان | `login()` (`fail()`), `forgot_password()`, `register()` | User enumeration | Lecture 5 (generic error messages) | `04_user_enumeration.py`؛ `test_generic_login_error`, `test_unconfirmed_account_cannot_log_in`, `test_forgot_password_same_message` |
| 5 | نفس وقت الرد للـ username المش موجود | `waste_time_like_a_password_check()`, `DUMMY_HASH` | Timing enumeration | Lecture 5 | (مفيش تست توقيت، الكود بس) |
| 6 | الهوية بين خطوة الباسورد وخطوة الكود في `session["pending_2fa_user_id"]` (سيشن موقّع)، وأي `user`/`username`/`user_id` في الفورم بيتجاهل | `login()`, `two_factor()`; شرح التوقيع في `config.py` فوق `SECRET_KEY` | Lab 3 "2FA broken logic" (تغيير cookie `verify` لحساب تاني) | Lab 3 | `14_2fa_bypass.py` (50/50 محاولة رجعت للوجين، `/admin/` → 403)؛ `test_2fa_page_needs_password_step`, `test_admin_needs_2fa` |
| 7 | TOTP بـ `pyotp`، `valid_window=1`، ومنع إعادة الكود بـ `totp_last_step` في UPDATE ذري | `two_factor()` | Replay لكود اتسرق | Lecture 5 (MFA/TOTP) | `15_2fa_reuse.py`؛ `test_totp_code_cannot_be_reused` |
| 8 | الكود الغلط = فشل دخول، 5 غلطات → قفل ومسح الـ pending login؛ والـ pending بينتهي بعد 5 دقايق | `two_factor()` + `register_failure()`; `config.TOTP_PENDING_MINUTES` | تخمين 000000–999999 | Lab 3 + Lecture 5 | `test_5_wrong_codes_cancel_the_login` |
| 9 | أدمن من غير `totp_secret` مش بيدخل | `login()` | دخول أدمن بباسورد بس | Lecture 3 (fail secure) | الكود (`"admin has no 2FA secret"` في الـ audit) |
| 10 | `session.clear()` قبل ما نحط `user_id`، والسيشن فيه ids بس (مش role) | `finish_login()` | Session fixation، وبقايا `pending_2fa_user_id` | Lab 3 (cookie tampering) + Lecture 2 (least privilege) | `test_login_success_stores_only_user_id` |
| 11 | `session_version`: بيزيد مع logout وتغيير/ريست الباسورد وتغيير الـ role، فالكوكي القديمة المنسوخة تبطل | `logout()` → `bump_session_version()`; `reset_password()`; المقارنة في `security.load_logged_in_user()` | استخدام كوكي مسروقة بعد الخروج | Lab 3 (cookie) | في `tests/test_account.py`: `test_old_cookie_rejected_after_logout`, `test_old_cookie_rejected_after_password_reset` |
| 12 | توكن الريست/التأكيد: `secrets.token_urlsafe(32)`، hash بس في الداتابيز، مدة (15 دقيقة / 24 ساعة)، مرة واحدة بـ `AND used_at IS NULL`، وبعد الريست باقي التوكنات بتتمسح. ومفيش security questions | `new_token()`, `hash_token()`, `confirm_email()`, `find_reset_token()`, `reset_password()` | تخمين أو إعادة لينك الريست | Lecture 5 (account recovery) | `16_reset_token.py`؛ `test_reset_token_is_single_use`, `test_reset_token_expires`, `test_confirm_link_works_once`, `test_confirm_link_expires` |
| 13 | الطويل بيترفض مش بيتقص (email ≤ 254، username ≤ 30)، والـ role دايماً `'user'` ومش بيتاخد من الإيميل ولا من الفورم | `validate_email()`, `validate_username()`, `register()` | Lab 2.2: إيميل طويل يتقص لـ 255 ويخلص بـ `@secureshop.com` فيبقى admin | Lab 2.2 | `07_email_truncation.py`؛ `test_too_long_username_rejected_not_cut`, `test_too_long_email_rejected`, `test_register_always_creates_unconfirmed_normal_user` (بيبعت `role=admin` وبيتجاهل) |
| 14 | الحساب مش بيدخل قبل تأكيد الإيميل | `login()` | حسابات بإيميلات وهمية | Lecture 5 | `test_unconfirmed_account_cannot_log_in` |
| 15 | logout بـ POST بس | `logout()` (`methods=["POST"]`) | موقع تاني يطلعك بصورة أو لينك | Lecture 2 | `test_logout_is_post_only_and_clears_session` (GET → 405) |
| 16 | كل query بـ `?` | كل `auth.py` | SQL injection في الدخول (`' OR '1'='1`) | Lecture 2 | `grep 'execute(f'` مش بيلاقي حاجة |
| 17 | Audit log: `register`, `register_duplicate_email`, `email_confirmed`, `login_success`, `login_failed`, `account_locked`, `2fa_failed`, `logout`, `password_reset_requested`, `password_reset`. ومفيش باسورد أو توكن أو كود في الـ details | `log_audit()` من `security.py` | الإنكار، وإن الهجوم يعدي من غير ما حد يلاحظ | Lecture 2 (audit log) | التستات بتشيك `audit_actions()` |
| 18 | الـ input بيرجع للصفحة عن طريق Jinja2 autoescape | `templates/auth/*` | XSS في رسايل الخطأ | Lecture 2 | `test_bad_username_characters_rejected` |

**STRIDE (من `docs/02_threat_model.md` – F1):** S = brute force، 2FA bypass، reuse للكود واللينك؛ T = `role=admin` في الفورم؛ E = الإيميل الطويل؛ I = enumeration والباسوردات المسروقة؛ R = audit log؛ D = القفل مؤقت مش دايم. في الـ DREAD: T9 brute force = 8.2، T13 2FA = 7.0، T14 reset token = 6.4.

---

## 4. ديمو في دقيقتين

التحضير: `python seed.py` ثم `flask run` (على الماك لو بورت 5000 مشغول: `flask run -p 5050`). احتفظ بسطر الـ TOTP اللي `seed.py` بيطبعه:
`python -c "import pyotp; print(pyotp.TOTP('<SECRET>').now())"`

1. **(20 ثانية) رسالة واحدة.** افتح `/auth/login`. ادخل `nobody` / أي باسورد → `Invalid username or password.` ادخل `victim` / `wrong-pass-123` → نفس الرسالة بالظبط. "مينفعش نعرف مين موجود."
2. **(30 ثانية) القفل.** كمّل لحد 5 غلطات على `victim`. بعدين ادخل الباسورد الصح `Victim-Pass-2026` → برضه `Invalid username or password.` "الحساب مقفول دقيقة، والباسورد الصح نفسه مش بيتشيك." (بعد دقيقة هيدخل عادي.)
3. **(15 ثانية) باسورد ضعيف + Lab 2.2.** افتح `/auth/register`، جرّب `password123` → `This password is too common. Please choose another one.` جرّب إيميل أطول من 254 → `Email must be at most 254 characters.`
4. **(40 ثانية) 2FA للأدمن + Burp.** ادخل `admin` / `Admin-Pass-2026!` → بيوديك `/auth/two-factor`. افتح `/admin/` في تاب تاني → بيرجعك للوجين (لسه مش داخل). في Burp اعمل intercept على `POST /auth/two-factor` وزوّد `&user_id=1&username=shopper` → بيتجاهلهم. أو غيّر حرف في كوكي `session` → التوقيع بيبوظ والسيشن بيتمسح وبترجع للوجين. بعدين ادخل الكود الصح من سطر الـ `python -c` → داخل، و `/admin/` بيفتح.
5. **(15 ثانية) إعادة الكود.** اعمل Log out، ادخل admin تاني، واكتب **نفس الكود** في نفس الـ 30 ثانية → `Invalid code. Please try again.`
6. **(اختياري) الريست.** `/auth/forgot-password` بـ `victim@secureshop.test` وبـ إيميل مش موجود → نفس الرسالة. افتح أحدث ملف في `outbox/`، استخدم اللينك مرة → شغال، مرة تانية → `This reset link is invalid, already used or expired. Please ask for a new one.`

لو عايز الدليل كله مرة واحدة: `docs/evidence/attack_results.txt` (17 هجوم، كلهم BLOCKED في SecureShop).

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **ليه `session.clear()` قبل ما نحط `user_id`؟**
   عشان أي حاجة قديمة في السيشن تتشال: لو المهاجم ثبّت سيشن قبل الدخول (session fixation)، أو فاضل `pending_2fa_user_id` من محاولة أدمن. السيشن الجديد فيه بس `user_id` و `session_version` و `mfa_done`.

2. **ليه بنخزن hash التوكن بس؟ وليه SHA-256 مش Argon2 للتوكن؟**
   لو الداتابيز اتسرقت، الـ hash مش بيفتح لينك شغال؛ التوكن الحقيقي في الإيميل بس. SHA-256 كفاية لأن التوكن `secrets.token_urlsafe(32)` عشوائي وطويل جداً، مفيش قاموس يتخمن منه، بعكس الباسورد اللي الناس بتختاره.

3. **ليه Argon2id ومش SHA-256 للباسورد؟**
   Argon2id بطيء ومحتاج memory، وفيه salt عشوائي لكل hash، فنفس الباسورد بيطلع hash مختلف. في `05_password_storage.py` كان MD5 بيعمل ملايين التخمينات في الثانية، و Argon2 حوالي 35 بس.

4. **إزاي ثغرة Lab 3 (cookie `verify=carlos`) مقفولة هنا؟**
   مفيش cookie بنقرا منها اسم اليوزر. بعد الباسورد بنحط `pending_2fa_user_id` جوه سيشن Flask، وده موقّع بـ `SECRET_KEY`. لو اتعدل، التوقيع بيبوظ والسيشن كله بيتشال. و `two_factor()` بتتجاهل أي `user` في الفورم. وبعد الباسورد مفيش `user_id`، فـ `g.user` بيفضل `None`.

5. **إيه اللي بيمنع حد يخمن الكود من 000000 لـ 999999؟**
   كل كود غلط بينادي `register_failure()`، فبعد 5 غلطات الحساب بيتقفل والـ pending login بيتمسح. والـ pending نفسه بينتهي بعد 5 دقايق. فبدل مليون تخمينة، المهاجم ياخد 5 وبعدين قفل بيطول كل مرة.

6. **إيه فايدة `totp_last_step`؟**
   بنخزن رقم الـ 30-second step بتاع آخر كود اتقبل. الـ UPDATE بشرط `totp_last_step < ?`، فنفس الكود أو كود أقدم بيترفض، حتى لو اتبعت مرتين في نفس اللحظة. ده بيمنع replay لكود اتسرق.

7. **ليه رسالة واحدة لكل الحالات؟ طيب صفحة التسجيل بتقول `That username is already taken.`!**
   الرسالة الواحدة بتمنع user enumeration من صفحة الدخول وصفحة forgot-password. صفحة التسجيل لازم تقول إن الاسم محجوز وإلا اليوزر مش هيعرف يختار اسم، وده trade-off معروف. الإيميل (وهو البيانات الشخصية) محمي: التسجيل بإيميل موجود بيعرض رسالة النجاح العادية، والإيميل الحقيقي بيوصله تحذير.

8. **ليه `waste_time_like_a_password_check()`؟**
   من غيرها الـ username المش موجود هيرد بسرعة (مفيش Argon2)، والموجود هيرد أبطأ، فالمهاجم يعرف الأسماء من الوقت بس. كده الاتنين بياخدوا نفس الشغل.

9. **إيه هو `session_version`؟**
   رقم في جدول `users` بيتنسخ في السيشن وقت الدخول. `load_logged_in_user()` بتقارنهم في كل request. بيزيد مع logout وتغيير الباسورد والريست وتغيير الـ role، فأي كوكي قديمة اتنسخت بتبطل على طول. ده مهم لأن Flask session كوكي، والسيرفر لوحده مش هيقدر يمسحها من عند المهاجم.

10. **ليه القفل مؤقت ومش دايم؟ وليه بيتضاعف؟**
    القفل الدايم بيخلي أي حد يقفل حساب أي حد تاني (DoS). المؤقت (1، 2، 4، 8 دقايق… لحد 30) بيبطّأ الـ brute force جداً ومش بيضر صاحب الحساب كتير. العدادات بتتصفر بس بعد دخول ناجح كامل (`finish_login()`) أو ريست.
