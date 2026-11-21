# Member 6 – صفحة الحساب ولوحة الأدمن (`account.py` + `admin.py`)

إنت مسؤول عن حاجتين:

1. **الحساب**: اليوزر يشوف بياناته، يعدل الاسم والعنوان، ويغير الباسورد.
2. **الأدمن**: اليوزرز، المنتجات، الكوبونات، والـ audit log.

ملفاتك:

- `account.py`، `admin.py`
- `templates/account/profile.html`، `edit.html`، `password.html`
- `templates/admin/_nav.html`، `dashboard.html`، `users.html`، `totp_secret.html`، `products.html`، `product_form.html`، `coupons.html`، `coupon_form.html`، `audit.html`
- `tests/test_account.py`، `tests/test_admin.py`

بتعتمد على: `auth.py` (`check_password`، `ph`، `validate_password`)، `security.py` (`login_required`، `admin_required`، `bump_session_version`، `log_audit`)، `config.py`، `db.py`.

---

## 1. الملفات والدوال اللي بتاعتك

### `account.py` (`url_prefix="/account"`)

| الدالة | الـ route | بتعمل إيه |
|--------|-----------|-----------|
| `config.MAX_ADDRESS_LENGTH = 200` | – | أقصى طول للعنوان (في `config.py` زي باقي الحدود). |
| `profile()` | `GET /account/` | بتعرض بيانات `g.user` (اليوزر اللي في السيشن). |
| `edit_profile()` | `GET/POST /account/edit` | بتعدل `full_name` و `shipping_address` **بس**. |
| `change_password()` | `GET/POST /account/password` | تغيير الباسورد: لازم الباسورد الحالي + قواعد `validate_password()`. |

مفيش أي user id في أي URL أو فورم هنا. الحساب دايمًا `g.user`.

### `admin.py` (`url_prefix="/admin"`) – كل route عليها `@admin_required`

| الدالة | الـ route | بتعمل إيه |
|--------|-----------|-----------|
| `MONEY_PATTERN`، `SIGNED_MONEY_PATTERN`، `WHOLE_NUMBER_PATTERN`، `COUPON_CODE_PATTERN`، `MAX_REASON_LENGTH = 200` | – | regex للتحقق من الأرقام والكود. |
| `dollars_to_cents(text)` | – | `'12.50'` → `1250` (بعد ما النص يعدي على الـ regex). |
| `count_active_admins()` | – | عدد الأدمنز اللي مش disabled. |
| `get_user_or_404(user_id)` | – | يجيب يوزر أو 404. |
| `dashboard()` | `GET /admin/` | أرقام: users، products النشطة، orders الـ paid، coupons النشطة. |
| `manage_users()` | `GET /admin/users?q=` | قايمة وبحث (`LIKE ?`، أقصى 100 حرف `MAX_SEARCH_LENGTH`). |
| `toggle_user_disabled(user_id)` | `POST /admin/users/<id>/toggle-disabled` | disable / enable حساب. |
| `change_role(user_id)` | `POST /admin/users/<id>/role` | `user` ↔ `admin`. |
| `adjust_credit(user_id)` | `POST /admin/users/<id>/credit` | زيادة / نقص الكريدت مع سبب. |
| `read_product_form()` | – | قراءة وتحقق فورم المنتج (بيرجع `values, errors`). |
| `manage_products()` | `GET /admin/products` | كل المنتجات (حتى المخفية). |
| `new_product()` | `GET/POST /admin/products/new` | إضافة منتج. |
| `edit_product(product_id)` | `GET/POST /admin/products/<id>/edit` | تعديل منتج + تسجيل old -> new. |
| `toggle_product(product_id)` | `POST /admin/products/<id>/toggle` | hide / show (**مفيش delete**). |
| `read_coupon_form(is_new)` | – | قراءة وتحقق فورم الكوبون (بيرجع `form, clean, errors`). |
| `manage_coupons()` | `GET /admin/coupons` | الكوبونات + عدد الاستخدام + صاحب الكوبون. |
| `save_coupon_or_error(sql, params)` | – | INSERT/UPDATE، ولو الكود موجود (`IntegrityError`) يرجع `That code already exists (codes are not case-sensitive).` |
| `new_coupon()` | `GET/POST /admin/coupons/new` | كوبون جديد. |
| `edit_coupon(coupon_id)` | `GET/POST /admin/coupons/<id>/edit` | تعديل كوبون. |
| `toggle_coupon(coupon_id)` | `POST /admin/coupons/<id>/toggle` | activate / deactivate. |
| `audit_log()` | `GET /admin/audit?action=` | آخر 200 صف، مع فلتر بالـ action. |

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

### أ) تعديل البروفايل – `POST /account/edit` → `edit_profile()`

1. قبل أي route: `load_logged_in_user()` (في `security.py`) بتحط اليوزر في `g.user` من السيشن، و `@login_required` بيتأكد إنه مش `None`.
2. بنقرا **حقلين بس**: `full_name` و `shipping_address` (مع `.strip()`).
3. التحقق: الاسم أكتر من `config.MAX_NAME_LENGTH` (100) أو العنوان أكتر من `config.MAX_ADDRESS_LENGTH` (200) → نرجع الفورم برسالة و **400**. **مش بنقص النص.**
4. `UPDATE users SET full_name = ?, shipping_address = ? WHERE id = ?` بـ `g.user["id"]`. العمودين دول بس مكتوبين في الـ SQL.
5. `log_audit("profile_updated", "full_name: 'old' -> 'new'; address: ... -> ...")`.
6. flash `Your profile was updated.` ورجوع لـ `/account/`.

أي حقل زيادة في Burp (`role`، `store_credit_cents`، `email`، `user_id`، `username`) **مش بيتقري خالص**.

### ب) تغيير الباسورد – `POST /account/password` → `change_password()`

1. بنقرا `current_password`، `new_password`، `confirm_password`.
2. بنجيب اليوزر من الداتابيز (`SELECT * FROM users WHERE id = ?`).
3. الباسورد الحالي أطول من 128 أو غلط (`check_password()` من `auth.py`، Argon2 `ph.verify`) →
   `log_audit("password_change_failed", "wrong current password")` ورسالة `Your current password is not correct.` (400).
   وكمان الباسورد الغلط بيتحسب كـ failed login عن طريق `register_failure()` من `auth.py`: بعد 5 مرات الأكونت بيتقفل والسيشن بتتمسح (`session.clear()`)، فاللي سرق السيشن ميقدرش يخمن الباسورد هنا من غير حد (`test_guessing_current_password_locks_the_account`).
4. `validate_password(new, confirm, user["username"])` من `auth.py`: 10–128 حرف، مش في `common_passwords.txt`، مش زي اليوزرنيم، والتأكيد مطابق.
5. `UPDATE users SET password_hash = ?, session_version = session_version + 1` بـ `ph.hash(new)` (Argon2id).
6. `session["session_version"] = user["session_version"] + 1` → **البراوزر ده يفضل logged in**، وأي نسخة تانية من الكوكي (مسروقة مثلًا) تبطل.
7. `log_audit("password_changed")` ورسالة `Your password was changed. Other devices have been logged out.`

### ج) تغيير الدور (role) – `POST /admin/users/<id>/role` → `change_role()`

1. `@admin_required` (في `security.py`): لازم `g.user["role"] == "admin"` **من الداتابيز** و `session["mfa_done"] is True`. غير كده → `log_audit("admin_access_denied", "path=...")` و **403**. ومش عامل login أصلًا → redirect للـ login.
2. `get_user_or_404(user_id)`.
3. `role` من الفورم لازم يكون `"user"` أو `"admin"` (allow-list) وإلا `Unknown role.`
4. نفس الدور الحالي → `... already has the role ...`.
5. نفسك → `You cannot change your own role.`
6. آخر أدمن نشط → `You cannot remove the last admin.`
7. لو بقى admin: `pyotp.random_base32()` → `UPDATE users SET role = 'admin', totp_secret = ?, totp_last_step = 0`.
   لو بقى user: `UPDATE users SET role = 'user', totp_secret = NULL`.
8. `bump_session_version(user["id"])` → السيشن الحالية بتاعته بتقفل، ولازم يعمل login من جديد (والأدمن الجديد لازم بالـ 2FA).
9. `log_audit("admin_role_changed", "user=alice role: user -> admin")` (السيكريت **مش** بيتسجل).
10. لو أدمن جديد: صفحة `admin/totp_secret.html` فيها السيكريت والـ `provisioning_uri` **مرة واحدة**، مع `Cache-Control: no-store`. مش في flash (لأن الـ flash بيتخزن في كوكي السيشن).

### د) باقي الأدمن باختصار

- **Disable:** مينفعش نفسك (`You cannot disable your own account.`) ولا آخر أدمن (`You cannot disable the last admin.`). لما يتعمل disable → `bump_session_version()` فبيخرج فورًا.
- **Credit:** `amount` لازم يطابق `[+-]?\d{1,6}(\.\d{1,2})?` ومش صفر، و `reason` من 3 لـ 200 حرف. الـ SQL:
  `UPDATE users SET store_credit_cents = store_credit_cents + ? WHERE id = ? AND store_credit_cents + ? >= 0`.
  لو `rowcount != 1` → `That would make the credit negative. Nothing was changed.` التسجيل: `credit_cents: 500 -> 1750 reason=...`.
- **Products:** السعر `> 0` (`\d{1,7}(\.\d{1,2})?`)، الستوك رقم صحيح `>= 0`، الاسم 1–100، الوصف ≤ 2000، الكاتيجوري 1–50. **مفيش delete** لأن `order_items` بيشاور على المنتج؛ في hide/show بـ `is_active`.
- **Coupons:** الكود `[A-Za-z0-9_-]{3,32}` (بيتحفظ uppercase)، النوع `percent` أو `fixed`، percent من 1 لـ `config.MAX_DISCOUNT_PERCENT` (30)، fixed `> 0`، `max_uses >= 1`، التاريخ `YYYY-MM-DD` حقيقي، وكوبون جديد ميبقاش تاريخه فات.
- **Audit:** الفلتر لازم يكون action موجودة فعلًا في الجدول، غير كده بيتجاهل. `ORDER BY a.id DESC LIMIT 200`.

---

## 3. الحمايات

| الحماية | فين بالظبط | بتوقف إيه | المحاضرة / اللاب |
|---------|------------|-----------|------------------|
| **Mass assignment:** حقلين بس بيتقروا وبيتكتبوا | `account.py` `edit_profile()` | `role=admin` أو `store_credit_cents=99999` في Burp | **Lecture 2** (least privilege) |
| رفض النص الطويل بدل قصه (100 / 200) + CHECK في `schema.sql` | `edit_profile()`، `read_product_form()`، `read_coupon_form()` | مشكلة Lab 2.2 (قص في مكان واستعمال كامل في مكان تاني) | **Lab 2.2** |
| مفيش user id في URL؛ دايمًا `g.user` | `account.py` كله | **IDOR** على البروفايل | Lecture 2 |
| الباسورد الحالي مطلوب | `change_password()` | حد على جهاز مفتوح أو معاه كوكي مسروقة ياخد الحساب | **Lecture 5** (account recovery / takeover) |
| `validate_password()` + Argon2id `ph.hash()` | `change_password()` | باسورد ضعيف زي `password123` | **Lecture 4** (weak passwords, hashing) |
| `session_version + 1` عند تغيير الباسورد، الـ role، أو disable؛ ومقارنتها في كل request | `change_password()`، `change_role()`، `toggle_user_disabled()`؛ `security.py` `load_logged_in_user()` | كوكي قديمة متنسخة تفضل شغالة | **Lab 3** (cookie tampering / session) |
| يوزر disabled بيتشال من السيشن فورًا | `load_logged_in_user()` (`is_disabled == 1` → `session.clear()`) | حساب اتقفل يفضل شغال | Lecture 2 |
| `@admin_required`: الدور من **الداتابيز** + `mfa_done` + 403 + `admin_access_denied` | `security.py` `admin_required()`؛ على كل route في `admin.py` | يوزر عادي يكتب `/admin/users`، أو كوكي `role=admin`، أو أدمن عدى الباسورد بس من غير الكود | **Lecture 2** (least privilege)، **Lab 3**، **Lecture 5** (MFA) |
| أدمن جديد = TOTP secret جديد، بيظهر مرة واحدة، `no-store`، مش في flash ولا في الـ audit | `change_role()`؛ `templates/admin/totp_secret.html` | أدمن من غير 2FA، أو السيكريت يتسرب من الكاش/الكوكي/اللوج | **Lecture 5** (MFA/TOTP) |
| allow-list للأدوار، مينفعش تغير نفسك، آخر أدمن محمي | `change_role()`، `toggle_user_disabled()`، `count_active_admins()` | `role=superadmin`، أو الشوب يفضل من غير أدمن | Lecture 2 / **Lecture 3** (fail secure) |
| الكريدت عمره ما يبقى سالب (`AND store_credit_cents + ? >= 0` + CHECK) والسبب إجباري، والأدمن ميقدرش يغير كريدت نفسه (separation of duties) | `adjust_credit()` | "infinite money" أو خطأ من الأدمن، والإنكار | Lab 2 / Lecture 2 (audit) |
| سعر `> 0`، percent 1–30% (+ CHECK في `schema.sql`) | `read_product_form()`، `read_coupon_form()` | أدمن يحط سعر 0 أو كوبون 90% | Lab 1 / **Lab 2.1** |
| hide بدل delete | `toggle_product()` | تبويظ سجل الطلبات القديمة | – |
| كل تغيير POST بس، ومسجل بـ old -> new | كل `admin.py` | GET من لينك يغير حاجة؛ أدمن ينكر إنه غير سعر | **Lecture 2** (audit log, repudiation) |
| `?` placeholders (حتى البحث والفلتر) + الفلتر لازم من قايمة موجودة | `manage_users()`، `audit_log()` | SQL injection | Lecture 2 |
| Jinja2 autoescape في كل تمبليتس الأدمن | `templates/admin/users.html` إلخ | **Stored XSS**: يوزر اسمه `<script>` يتنفذ عند الأدمن | Lecture 2 |

### التستات

- `tests/test_account.py`: `test_profile_shows_own_data`، `test_update_profile`، `test_too_long_fields_rejected_not_cut`، `test_mass_assignment_ignored`، `test_change_password_needs_current_password`، `test_change_password_uses_password_rules`، `test_change_password`، `test_old_cookie_rejected_after_logout`، `test_old_cookie_rejected_after_password_change`، `test_old_cookie_rejected_after_password_reset`، `test_disabled_user_is_logged_out`، `test_account_pages_need_login`.
- `tests/test_admin.py`: `test_normal_user_cannot_open_any_admin_page` (بيلف على **كل** route في `app.url_map` اللي بتبدأ بـ `admin.`، فلو حد نسي `@admin_required` في route جديدة التست يقع)، `test_anonymous_is_sent_to_login`، `test_admin_without_2fa_in_session_is_refused`، `test_admin_pages_open_for_admin`، `test_changes_need_post`، `test_admin_cannot_demote_or_disable_themselves`، `test_make_admin_gives_totp_secret_and_ends_old_session`، `test_unknown_role_refused`، `test_demote_other_admin`، `test_disable_and_enable_user`، `test_credit_cannot_go_negative`، `test_credit_needs_reason_and_valid_amount`، `test_user_search_is_safe`، `test_product_validation`، `test_edit_product_logs_old_and_new`، `test_hide_product`، `test_coupon_validation`، `test_deactivate_coupon`، `test_audit_log_page_and_filter`.

### الـ attack scripts

- `attack_scripts/13_admin_cookie.py` – naive: كوكي `role=admin` فتحت قايمة اليوزرز؛ SecureShop: shopper + كوكي `role=admin` → **403**، ومن غير login → **302** للـ login.
- `attack_scripts/14_2fa_bypass.py` – بعد الـ 50 محاولة `/admin/` → 403 (لأن `mfa_done` مش True).
- (مفيش سكريبت لـ mass assignment؛ الإثبات هو `test_mass_assignment_ignored` + ديمو Burp تحت.)

---

## 4. ديمو في دقيقتين

**التحضير:** `python seed.py` (هيطبع `Admin TOTP secret` وأمر زي
`python -c "import pyotp; print(pyotp.TOTP('...').now())"`) ثم `flask run`. Burp شغال.

1. **(30 ثانية) Mass assignment في Burp:** login بـ `shopper` / `Shopper-Pass-2026`، افتح `/account/edit`، اكتب اسم، وشغل Intercept ودوس Save.
   زود في الـ body: `&role=admin&store_credit_cents=99999999&email=evil@example.com`. Forward.
   افتح `/account/` → الاسم اتغير، بس Role لسه `user` والكريدت لسه $100.00.
2. **(20 ثانية) Lab 2.2:** في نفس الصفحة امسح `maxlength` من الـ HTML (Inspect) أو عدل في Burp وابعت اسم 101 حرف → رسالة `Full name must be at most 100 characters.` والاسم القديم زي ما هو.
3. **(20 ثانية) Least privilege:** وإنت لسه shopper افتح `/admin/users` → **403** `You do not have permission to open this page.`
4. **(20 ثانية) تغيير الباسورد:** `/account/password` بباسورد حالي غلط → `Your current password is not correct.`؛ بباسورد جديد `password123` → `This password is too common. Please choose another one.`
5. **(30 ثانية) الأدمن:** logout، login بـ `admin` / `Admin-Pass-2026!`، شغل أمر الـ pyotp في التيرمنال وحط الكود في `/auth/two-factor`.
   روح `/admin/users` → دوس **Make admin** جنب `victim` → صفحة `victim is now an admin` فيها السيكريت مرة واحدة (لو عملت Refresh والبراوزر بعت الـ POST تاني هتظهر `victim already has the role admin.` ومش هيظهر السيكريت تاني).
   بعدين اكتب `-1000` في Adjust credit لـ shopper بسبب `test` → `That would make the credit negative. Nothing was changed.`
   افتح `/admin/audit` واختار `admin_role_changed` → `user=victim role: user -> admin`، و `admin_access_denied` → محاولة الـ shopper من خطوة 3.

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **إيه هو mass assignment وإزاي منعته؟**
   إن السيرفر ياخد كل حقول الفورم ويحطها في الداتابيز، فاليوزر يزود `role=admin`. إحنا بنقرا `full_name` و `shipping_address` بالاسم، والـ UPDATE فيه العمودين دول بس. التست: `test_mass_assignment_ignored`.

2. **ليه بترفض الاسم الطويل بدل ما تقصه؟**
   ده Lab 2.2: القص في مكان واحد بيخلي القيمة المتخزنة غير اللي اتشيك عليها. الرفض بيخلي القيمة واحدة في كل مكان. والـ CHECK `length(full_name) <= 100` في `schema.sql` خط دفاع تاني. التست: `test_too_long_fields_rejected_not_cut`.

3. **ليه تغيير الباسورد محتاج الباسورد القديم؟**
   عشان لو حد قعد على جهاز مفتوح أو سرق الكوكي ميقدرش يقفل الحساب على صاحبه. التست: `test_change_password_needs_current_password`.

4. **إيه فكرة `session_version`؟**
   رقم في جدول `users` بيتنسخ في السيشن عند الـ login. `load_logged_in_user()` بتقارنهم في كل request. لما الباسورد أو الدور يتغير أو الحساب يتعمل disable أو logout الرقم بيزيد، فأي كوكي قديمة بتبطل. في تغيير الباسورد بنحط الرقم الجديد في سيشن البراوزر الحالي فبيفضل داخل. التست: `test_old_cookie_rejected_after_password_change`.

5. **لو يوزر عادي كتب `/admin/users` في البراوزر؟**
   `@admin_required` بيرجع 403 ويسجل `admin_access_denied`. إخفاء لينك Admin من المنيو مش حماية؛ الحماية في السيرفر. التست `test_normal_user_cannot_open_any_admin_page` بيجرب كل admin route أوتوماتيك.

6. **لو أنا أدمن بس دخلت بالباسورد ومدخلتش كود الـ 2FA؟**
   `finish_login()` بتحط `mfa_done=True` بس بعد كود صح. `admin_required` بيطلب `session.get("mfa_done") is True`، فمن غيره 403. التست: `test_admin_without_2fa_in_session_is_refused`.

7. **الدور بيتقري منين؟ ولو غيرت الكوكي؟**
   من الداتابيز في كل request (`load_logged_in_user()`)، مش من الكوكي. السيشن نفسها موقعة بـ `SECRET_KEY`، فلو عدلت فيها التوقيع بيبوظ وفلاسك بيرميها. كوكي زي `role=admin` ملهاش أي معنى عندنا (`13_admin_cookie.py`).

8. **ليه الأدمن مينفعش يغير دوره أو يعمل disable لنفسه؟**
   عشان ميقفلش على نفسه بالغلط، وعشان الشوب ميفضلش من غير أدمن. وكمان في check لآخر أدمن نشط (`count_active_admins()`) كـ safety net تاني (fail secure).

9. **لما حد يبقى أدمن، الـ TOTP secret بيتعامل إزاي؟**
   بنعمل واحد جديد بـ `pyotp.random_base32()` ونعرضه مرة واحدة في صفحة فيها `Cache-Control: no-store`. مش بنحطه في flash (الـ flash بيتخزن في كوكي السيشن) ولا في `audit_log`. وبنعمل `bump_session_version()` عشان يعمل login من جديد بالكود. التست: `test_make_admin_gives_totp_secret_and_ends_old_session`.

10. **إزاي تعرف مين عمل إيه في لوحة الأدمن؟**
    كل تغيير بيعمل `log_audit()` بالقيمة القديمة والجديدة، زي `price_cents: 10000 -> 8000` أو `credit_cents: 500 -> 1750 reason=birthday gift`، ومعاه `user_id` و `ip_address` والوقت. وصفحة `/admin/audit` بتعرض آخر 200 مع فلتر. ده accountability / non-repudiation من Lecture 2. التستات: `test_edit_product_logs_old_and_new`، `test_audit_log_page_and_filter`.
