# Member 4 – الكوبونات والنيوزليتر (`coupons.py`)

الملفات بتاعتك: `coupons.py`، `templates/coupons/newsletter.html`، `tests/test_coupons.py`.
ملفات مرتبطة: جداول `coupons` و `coupon_redemptions` و `newsletter_subscribers` و `coupon_failed_attempts` في `schema.sql`؛ إعدادات الكوبون في `config.py`؛ `cart.py` (`view_cart()`, `load_cart_lines()`)؛ `orders.py` `checkout()` و `pay()` (Member 5) بينادوا `check_coupon()` تاني؛ `auth.send_email()`.

---

## 1. الملفات والدوال اللي بتاعتك

| الاسم | بيعمل إيه في سطر |
|------|------------------|
| `bp = Blueprint("coupons", __name__)` | من غير prefix: `/coupons/...` و `/newsletter` |
| `NOT_VALID` | `"This coupon code is not valid."` – رسالة واحدة للكود المش موجود والمتوقف وبتاع حد تاني. **هي بس اللي بتتحسب تخمينة غلط** |
| `format_money(cents)` | `1000` → `"$10.00"` |
| `check_coupon(user_id, code, cart_total_cents)` | المكان الوحيد اللي فيه كل قواعد الكوبون. بترجّع `(coupon, discount_cents, None)` أو `(None, 0, error)`. **مش بتغير أي حاجة في الداتابيز** |
| `recent_failures(user_id)` | عدد الأكواد الغلط لليوزر ده في آخر 10 دقايق |
| `apply_coupon()` → `POST /coupons/apply` | تطبيق كود |
| `remove_coupon()` → `POST /coupons/remove` | شيل الكوبون من السيشن |
| `newsletter()` → `GET/POST /newsletter` | اشتراك وكوبون شخصي |

الإعدادات (`config.py`): `MAX_COUPON_CODE_LENGTH = 32`، `MAX_DISCOUNT_PERCENT = 30`، `COUPON_MAX_FAILURES = 10`، `COUPON_FAILURE_WINDOW_MINUTES = 10`، `NEWSLETTER_DISCOUNT_PERCENT = 10`، `NEWSLETTER_MAX_DISCOUNT_CENTS = 1000`.

كوبونات الـ seed: `WELCOME5` (5%)، `SAVE20` (20%، أقصى $50، العربة $50+، 30 يوم)، `TENOFF` ($10 ثابت، العربة $30+، 100 استخدام للكل)، `OLD10` (منتهي).

`newsletter.html`: **مفيهاش حقل إيميل** – السيرفر بيستخدم إيميل الحساب.

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

مثال: shopper عربته Canvas Backpack × 2 = $69.00، وبيكتب `SAVE20`.

1. فورم في `cart.html` → `POST /coupons/apply` بـ `code=SAVE20`.
2. `apply_coupon()` (عليها `@login_required`): `user_id = g.user["id"]`.
3. `recent_failures(user_id) >= 10`؟ لو آه → `coupon_guessing_blocked` في الـ audit و `Too many wrong coupon codes. Please try again in a few minutes.` (حتى لو الكود صح).
4. `load_cart_lines()` من `cart.py` → `subtotal = 6900` من الداتابيز.
5. `check_coupon(user_id, "SAVE20", 6900)` بالترتيب ده:
   1. فاضي → `Please enter a coupon code.`؛ أطول من 32 → `Coupon codes are at most 32 characters.`
   2. `SELECT * FROM coupons WHERE code = ?` (العمود `COLLATE NOCASE`، فـ `save20` شغال). مش موجود أو `is_active != 1` → `NOT_VALID`.
   3. `owner_user_id` مش NULL ومش أنا → `NOT_VALID`.
   4. `expires_at <= time.time()` → `This coupon has expired.`
   5. موجود في `coupon_redemptions` لنفس اليوزر → `You have already used this coupon.`
   6. `max_uses` وعدد الاستخدامات وصله → `This coupon has been used up.`
   7. العربة ≤ 0 → `Your cart is empty.`؛ أقل من `min_total_cents` → `This coupon needs a cart total of at least $50.00.`
   8. الحساب: percent → `6900 * 20 // 100 = 1380`؛ fixed → `discount_value`.
   9. الحدود: `min(discount, max_discount_cents)` لو موجود، وبعدين `min(discount, cart_total_cents)`. لو ≤ 0 → `Your cart total is too small for this coupon.`
6. خطأ؟ لو هو `NOT_VALID` بس → `INSERT INTO coupon_failed_attempts`. وفي كل الأحوال `coupon_rejected` في الـ audit ورسالة.
7. نجاح: `session["coupon_code"] = coupon["code"]` – **الكود بس، من غير مبلغ**. لو كان فيه كود قديم مختلف: `Coupon SAVE20 applied. It replaced WELCOME5 (only one coupon per order).`
8. `view_cart()` في `cart.py` بتنادي `check_coupon()` تاني بالـ subtotal الحالي كل مرة بتتعرض. الخصم = `-$13.80`.
9. الدفع (`orders.pay()`، Member 5): جوه `BEGIN IMMEDIATE` بتنادي `check_coupon()` **تالت مرة**. لو فيه خطأ: `Your coupon can no longer be used: ...`. بعد ما الكريدت يتخصم والأوردر يتعمل بس، بيتعمل `INSERT INTO coupon_redemptions` و `coupon_redeemed` في الـ audit.

### النيوزليتر

1. `GET /newsletter` → لو مشترك (`WHERE user_id = ? OR email = ?`) بيقولك كده.
2. `POST /newsletter`: لازم `is_confirmed` (وإلا `Please confirm your email address first.`)؛ لو مشترك → `You are already subscribed. Each account gets only one newsletter coupon.`
3. `code = "NEWS-" + secrets.token_hex(5).upper()` (10 حروف hex = 40 bit).
4. `INSERT INTO coupons` بـ `'percent'`، 10%، `max_discount_cents = 1000`، `max_uses = 1`، `owner_user_id = user["id"]`. وبعدين `INSERT INTO newsletter_subscribers` بإيميل **الحساب**.
5. `sqlite3.IntegrityError` (طلبين في نفس اللحظة) → `db.rollback()` ونفس رسالة "already subscribed".
6. `send_email()` → الكود في ملف جوه `outbox/`، و `newsletter_signup` في الـ audit.

---

## 3. الحمايات

| # | الحماية | فين بالظبط | بتمنع إيه | المصدر | الإثبات |
|---|---------|-----------|-----------|--------|---------|
| 1 | كود **واحد** في `session["coupon_code"]`، والجديد بيحل محل القديم، ومفيش مبلغ خصم متخزن | `apply_coupon()` | Lab 2.1: تبديل `WELCOME5` و `SAVE20` لحد ما الخصومات تتجمع | Lab 2.1 (coupon stacking) | `09_coupon_stacking.py` (الـ naive خصم 50%، احنا `SAVE20 = -$13.80` بس)؛ `test_coupons_do_not_stack` |
| 2 | في الداتابيز: `orders.coupon_id` عمود واحد، و `coupon_redemptions.order_id UNIQUE` | `schema.sql` | أكتر من كوبون على أوردر واحد | Lab 2.1 | الـ constraints |
| 3 | مرة واحدة لكل يوزر: تشييك في `check_coupon()` + `UNIQUE (coupon_id, user_id)` | `check_coupon()`, `schema.sql` | نفس الكود على أوردر تاني | Lab 2.1 | `test_same_user_cannot_use_coupon_twice`؛ (في `tests/test_orders.py`) `test_coupon_used_only_once_after_real_order` |
| 4 | كل القواعد في مكان واحد: active، الصاحب، الانتهاء، max_uses، الحد الأدنى | `check_coupon()` | كوبون منتهي أو متوقف أو مستنفد | Lab 2.1 | `test_expired_coupon_rejected`, `test_max_uses`, `test_minimum_cart_total`, `test_inactive_unknown_and_other_users_coupon_rejected` |
| 5 | حدود الخصم: percent من 1 لـ 30% (CHECK في `schema.sql` + `admin.py`)؛ وأي خصم ≤ `max_discount_cents` و ≤ الـ cart total. الـ fixed **مش محدود بـ 30%**، محدود بالـ max والـ total بس | `check_coupon()`, `schema.sql` `coupons.discount_value` CHECK | total سالب أو خصم أكبر من 100% | Lab 2.1 + Lecture 3 (fail secure) | `test_discount_never_above_cart_total`؛ (في `test_orders.py`) `test_fixed_coupon_can_make_total_zero_but_not_negative` |
| 6 | إعادة الحساب: في كل عرض للعربة، في `checkout()`، وجوه `pay()`. والـ redemption بتتسجل بعد الدفع بس | `view_cart()` (cart.py)، `orders.checkout()` و `pay()` | خصم قديم بعد ما العربة صغرت، أو كوبون انتهى/اتستخدم في تاب تاني | Lab 2.1 + Lab 2.3 (workflow) | `test_coupon_rechecked_when_cart_changes`؛ (في `test_orders.py`) `test_coupon_rechecked_at_payment` |
| 7 | الكود الطويل بيترفض مش بيتقص (≤ 32) | `check_coupon()` | Lab 2.2 | Lab 2.2 | `test_too_long_code_rejected` |
| 8 | حد للتخمين: 10 أكواد غلط لكل يوزر في 10 دقايق، وبعدها **كل** الأكواد بتترفض | `recent_failures()`, `apply_coupon()`, جدول `coupon_failed_attempts` | Burp Intruder على `NEWS-xxxxxxxxxx` | Lecture 4 (brute force) – T16 في الـ DREAD | `test_coupon_guessing_blocked_after_10_tries`, `test_guess_limit_is_per_user` |
| 9 | رسالة واحدة `NOT_VALID` للمش موجود والمتوقف وبتاع حد تاني | `check_coupon()` | معرفة إن كوبون شخصي بتاع حد تاني موجود | Lecture 5 (generic error messages) | `test_inactive_unknown_and_other_users_coupon_rejected` |
| 10 | كوبون النيوزليتر: عشوائي بـ `secrets`، 10% أقصى $10، استخدام واحد، لصاحبه بس | `newsletter()`، `owner_user_id` في `check_coupon()` | تخمين أو استخدام كوبون حد تاني | Lecture 2 (IDOR-like) | `test_newsletter_coupon_is_personal_and_single_use` (bob بياخد `This coupon code is not valid.`) |
| 11 | نيوزليتر: حسابات متأكدة بس، اشتراك واحد لكل يوزر **ولكل إيميل** (`UNIQUE` على `user_id` و `email`)، والإيميل من الحساب مش من الفورم | `newsletter()`, `schema.sql` `newsletter_subscribers` | Coupon farming | Lab 2.1 | `test_newsletter_gives_only_one_coupon_per_user`, `test_newsletter_one_signup_per_email`, `test_newsletter_needs_login_and_confirmed_email` |
| 12 | `IntegrityError` → rollback ورسالة عادية | `newsletter()` | race condition (اشتراكين في نفس اللحظة) | Lecture 3 (fail secure) | الكود + الـ UNIQUE constraints |
| 13 | Audit: `coupon_applied`, `coupon_rejected` (بالسبب), `coupon_guessing_blocked`, `newsletter_signup` (و `coupon_redeemed` في `orders.py`) | `apply_coupon()`, `newsletter()` | الإنكار، والتخمين اللي محدش يلاحظه | Lecture 2 (audit log) | `test_apply_coupon`, `test_coupon_guessing_blocked_after_10_tries` |
| 14 | `@login_required` و POST بس، و `?` placeholders | كل الـ routes | استخدام من غير حساب، CSRF بـ GET، SQLi | Lecture 2 | `test_newsletter_needs_login_and_confirmed_email` |

**STRIDE (F4):** T = stacking، إعادة الاستخدام، منتهي/بتاع حد تاني، خصم > 100%، fixed كبير على عربة صغيرة؛ S = farming وتخمين الأكواد؛ R = `coupon_redeemed` + `coupon_redemptions`. الـ DREAD: T3 stacking = 9.0 (High)، T16 guessing = 6.4.

---

## 4. ديمو في دقيقتين

التحضير: `python seed.py` ثم `flask run`. ادخل `shopper` / `Shopper-Pass-2026`. افتح `/products/4` (Canvas Backpack $34.50) وضيف كمية 2 → العربة $69.00.

1. **(40 ثانية) Lab 2.1.** في خانة Coupon code اكتب `WELCOME5` → `-$3.45`. بعدين `SAVE20` → `Coupon SAVE20 applied. It replaced WELCOME5 (only one coupon per order).` والخصم `-$13.80` بس. اكتب `WELCOME5` تاني → الخصم بيرجع `-$3.45`. "دايماً كوبون واحد في العربة."
2. **(15 ثانية) Burp.** اعمل intercept على `POST /coupons/apply` وزوّد `&discount=6900` → بيتجاهل، مفيش حقل خصم بيتقري خالص.
3. **(15 ثانية) القواعد.** `OLD10` → `This coupon has expired.` طبّق `SAVE20` تاني، وبعدين غيّر كمية الشنطة لـ 1 بزرار Update (الإجمالي يبقى $34.50) → `Your coupon was removed: This coupon needs a cart total of at least $50.00.`
4. **(30 ثانية) النيوزليتر.** افتح `/newsletter` ودوس "Sign me up". افتح أحدث ملف `.txt` في `outbox/` → `NEWS-XXXXXXXXXX`. دوس تاني → `already subscribed`. اعمل Log out، ادخل `victim` / `Victim-Pass-2026`، ضيف أي منتج، واكتب كود shopper → `This coupon code is not valid.`
5. **(20 ثانية) التخمين.** وانت لسه `victim`، اكتب 10 أكواد غلط (أو في Burp Intruder على `code=NEWS-§0000000000§`)، وبعدين `WELCOME5` → `Too many wrong coupon codes. Please try again in a few minutes.` (اعمل ده آخر حاجة، الحساب هيفضل ممنوع من الكوبونات 10 دقايق.)

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **ليه الخصم بيتعاد حسابه وقت الدفع، مع إننا شيكناه وقت التطبيق؟**
   بين التطبيق والدفع حاجات كتير ممكن تتغير: الكوبون ينتهي، الأدمن يوقفه، `max_uses` يخلص، اليوزر يستخدمه في تاب تاني، أو العربة تصغر تحت `min_total_cents`. علشان كده `orders.pay()` بتنادي `check_coupon()` جوه `BEGIN IMMEDIATE`، بالـ subtotal اللي اتحسب من الداتابيز في نفس اللحظة.

2. **ليه بنخزن الكود بس في السيشن ومش مبلغ الخصم؟**
   لو خزّنا المبلغ، هيفضل ثابت حتى لو العربة اتغيرت، وده بالظبط اللي بيخلي الـ stacking يشتغل. الكود بس معناه إن الخصم بيتحسب من جديد كل مرة من الداتابيز، ومفيش غير كوبون واحد.

3. **إزاي الـ stacking مستحيل حتى لو حد لعب في الـ requests؟**
   فيه 3 طبقات. السيشن فيه key واحد `coupon_code` والكود الجديد بيكتب فوق القديم. `orders.coupon_id` عمود واحد مش قايمة. و `coupon_redemptions` فيه `order_id UNIQUE` و `UNIQUE (coupon_id, user_id)`.

4. **ليه الـ redemption بتتسجل بعد الدفع بس؟**
   لو اتسجلت وقت التطبيق، يوزر يطبّق الكوبون ومايشتريش فيخسره. ولو `check_coupon()` كانت بتكتب في الداتابيز، كانت هتبقى خطيرة إننا نناديها كذا مرة. فهي read-only، والـ `INSERT INTO coupon_redemptions` بيحصل جوه نفس الـ transaction بتاعة الدفع، فيا إما الاتنين يحصلوا يا ولا واحد.

5. **ليه الكوبون الـ fixed مش محدود بـ 30%؟**
   الـ 30% قاعدة للـ percent بس (CHECK في `schema.sql`: `discount_type = 'percent' AND discount_value BETWEEN 1 AND 30`). الـ fixed محدود بـ `max_discount_cents` لو موجود، وبعدين بالـ cart total، فالـ total ممكن يوصل $0 بس عمره ما يبقى سالب (`test_fixed_coupon_can_make_total_zero_but_not_negative`). مثلاً `TENOFF` شرطه عربة $30+.

6. **ليه نفس الرسالة للكود المش موجود والمتوقف وبتاع حد تاني؟**
   عشان المهاجم اللي بيخمن ميعرفش إنه لقى كود `NEWS-...` حقيقي بتاع حد تاني. والرسالة دي بالذات (`NOT_VALID`) هي اللي بتتحسب في `coupon_failed_attempts`.

7. **ليه بعد 10 غلطات حتى الكود الصح بيترفض؟**
   لو الكود الصح يعدي، Intruder هيفضل يجرب وأول ما يلاقي الكود الصح هينجح. لما **كل** الأكواد تترفض، مفيش أي رد يفرق بين الصح والغلط، فالتخمين ملوش فايدة. الحد لكل يوزر (`test_guess_limit_is_per_user`)، وبيرجع عادي بعد 10 دقايق.

8. **ليه `secrets` ومش `random` لكود النيوزليتر؟**
   `random` مش cryptographic، وممكن تتوقع القيم الجاية لو عرفت كام قيمة قبلها. `secrets.token_hex(5)` = 40 bit عشوائي (حوالي تريليون احتمال)، ومع حد الـ 10 تخمينات كل 10 دقايق التخمين مستحيل عملياً. وكمان الكود شغال لصاحبه بس.

9. **ليه النيوزليتر مفيهوش حقل إيميل؟**
   لو الإيميل جاي من الفورم، أي حد يقدر يشترك بإيميلات كتير ويجمع كوبونات، أو يشترك بإيميل حد تاني. فبناخد `user["email"]` من الداتابيز، والحساب لازم يكون متأكد، و `UNIQUE` على `user_id` وعلى `email`.

10. **إيه اللي يحصل لو اتبعت طلبين اشتراك في نفس اللحظة؟ أو اتنين دفعوا بكوبون `max_uses` بتاعه فاضل فيه استخدام واحد؟**
    في النيوزليتر، الـ UNIQUE constraints بتمنع الطلب التاني، فيحصل `sqlite3.IntegrityError` والكود بيعمل `db.rollback()` ويعرض رسالة "already subscribed". وفي الدفع، `BEGIN IMMEDIATE` في `pay()` بيخلي الدفعتين يمشوا واحدة ورا التانية، فالتانية بتلاقي العدد خلص وتاخد `This coupon has been used up.`
