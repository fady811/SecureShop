# Member 5 – الطلبات والدفع (`orders.py`)

إنت مسؤول عن أهم حتة في الموقع: **الفلوس**. الـ checkout، الدفع بالـ store credit،
صفحة التأكيد، وسجل الطلبات.

ملفاتك:

- `orders.py`
- `templates/orders/checkout.html`، `templates/orders/detail.html`، `templates/orders/history.html`
- `tests/test_orders.py`

بتعتمد على: `cart.py` (`get_cart()`، `load_cart_lines()`)، `coupons.py` (`check_coupon()`)،
`db.py`، `security.py` (`login_required`، `log_audit`)، و `schema.sql` (جداول `orders`، `order_items`، `coupon_redemptions`).

---

## 1. الملفات والدوال اللي بتاعتك

### `orders.py`

| الدالة / الحاجة | الـ route | بتعمل إيه |
|-----------------|-----------|-----------|
| `PUBLIC_ID_PATTERN` | – | regex `[A-Za-z0-9_-]{10,50}`. أي `public_id` مش شبهه بيرجع 404 على طول. |
| `PaymentError` | – | exception بنرميه جوه `pay()` لما الدفع مينفعش. الرسالة بتاعته بتظهر لليوزر. |
| `format_money(cents)` | – | بتحول السنتات لنص زي `$1,337.00` (للرسايل). |
| `find_my_order(public_id, paid_only=False)` | – | بتجيب الطلب **بشرط إنه بتاع اليوزر اللي عامل login** (`AND user_id = ?`). لو مش موجود أو بتاع حد تاني → `abort(404)`. مع `paid_only=True` بتزود `AND status = 'paid'`. |
| `checkout()` | `GET /checkout` | بتبني الكارت من الداتابيز، تتشيك على الكوبون، تعمل `checkout_token` لو مش موجود، وتعرض صفحة الدفع. |
| `pay()` | `POST /checkout/pay` | الدفع نفسه: transaction واحدة فيها كل الخطوات (تحت بالتفصيل). |
| `order_history()` | `GET /orders` | طلبات اليوزر بس (`WHERE user_id = ?`). |
| `order_detail(public_id)` | `GET /orders/<public_id>` | تفاصيل طلب واحد عن طريق `find_my_order()`. |
| `order_confirmation(public_id)` | `GET /orders/<public_id>/confirmation` | صفحة "شكرًا". **بتقرا بس**، محتاجة طلب بتاعك و `status = 'paid'`. |

كل الـ routes عليها `@login_required`.

### التمبليتس

- `checkout.html`: بيعرض الأسعار اللي اتحسبت في السيرفر. الفورم فيه **حقل واحد بس**: `<input type="hidden" name="checkout_token">`. مفيش أي price أو total في الفورم.
- `detail.html`: نفس التمبليت للتفاصيل والتأكيد (متغير `confirmation=True/False`). بيعرض `unit_price_cents` المحفوظ في `order_items` (السعر وقت الدفع).
- `history.html`: جدول بالطلبات، اللينك بالـ `public_id` مش بالرقم.

### الجداول اللي بتكتب فيها (`schema.sql`)

- `orders`: `public_id TEXT NOT NULL UNIQUE`، `checkout_token TEXT UNIQUE`، `status` (`'pending'`, `'paid'`, `'cancelled'`)،
  و CHECK `total_cents = subtotal_cents - discount_cents` و `discount_cents <= subtotal_cents`.
- `order_items`: `unit_price_cents > 0`، `quantity BETWEEN 1 AND 10`، `UNIQUE (order_id, product_id)`.
- `coupon_redemptions`: `UNIQUE (coupon_id, user_id)` و `order_id ... UNIQUE`.
- `users.store_credit_cents`: CHECK `>= 0`.

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

### أ) `GET /checkout` → `checkout()`

1. `load_cart_lines()` (من `cart.py`) بتبني الكارت من جدول `products` **دلوقتي**: السعر، الستوك، والمنتجات المخفية بتتشال.
2. لو الكارت فاضي → flash `Your cart is empty.` ورجوع لـ `cart.view_cart`.
3. لو فيه `session["coupon_code"]` → `check_coupon(g.user["id"], coupon_code, subtotal)`. لو فيه error الكوبون بيتشال من السيشن وتظهر `Your coupon was removed: ...`.
4. لو مفيش `session["checkout_token"]` → `secrets.token_urlsafe(16)` ويتحط في السيشن.
5. بنعرض `checkout.html` ومعاه `checkout_token` في hidden field.

### ب) `POST /checkout/pay` → `pay()` (أهم دالة)

**قبل الـ transaction:**

1. بنقرا من الفورم `checkout_token` **بس**. ونقارنه بـ `session["checkout_token"]` بـ `hmac.compare_digest`.
   لو غلط أو مش موجود → `This checkout page is out of date. Please check your order and try again.` ورجوع لـ `/checkout`.
2. `cart = get_cart()`، `coupon_code = session.get("coupon_code")`، و `db.commit()` عشان نتأكد إن مفيش transaction قديمة مفتوحة.

**جوه الـ transaction (`try`):**

3. `db.execute("BEGIN IMMEDIATE")` → بيقفل الداتابيز للكتابة. لو اتنين دفعوا في نفس اللحظة، واحد يستنى التاني.
4. **double payment check:** `SELECT public_id FROM orders WHERE checkout_token = ?`.
   لو لقينا طلب بنفس التوكن → `rollback`، نفضي الكارت والكوبون والتوكن من السيشن، ورسالة
   `This order was already paid. You were charged only once.` ونروح لصفحة التأكيد بتاعة الطلب القديم.
5. لو الكارت فاضي → `PaymentError("Your cart is empty.")`.
6. **(خطوة 1 في الكود) نحسب كل حاجة تاني** جوه الـ transaction: لكل منتج `SELECT id, name, price_cents, stock, is_active FROM products WHERE id = ?`.
   - منتج مش موجود أو `is_active != 1` → `A product in your cart is no longer available.`
   - الكمية أكبر من الستوك → `Not enough stock for ...`
   - `subtotal += price_cents * quantity` (السعر من الداتابيز).
7. **(خطوة 2) الكوبون تاني:** `check_coupon(user_id, coupon_code, subtotal)`. لو فيه error → `Your coupon can no longer be used: ...`. بعدين `total = subtotal - discount`.
8. **(خطوة 3) خصم الكريدت:**
   ```sql
   UPDATE users SET store_credit_cents = store_credit_cents - ? WHERE id = ? AND store_credit_cents >= ?
   ```
   لو `cur.rowcount != 1` يبقى الفلوس مش كفاية → `Not enough store credit. This order costs $...`.
9. **(خطوة 4) نقلل الستوك:** `UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?` + نفس فكرة `rowcount`.
10. **(خطوة 5) نعمل الطلب** وهو `'paid'` على طول (لأن الفلوس اتخصمت فوق):
    `public_id = secrets.token_urlsafe(12)`، و INSERT فيه `checkout_token` و `paid_at = CURRENT_TIMESTAMP`.
11. **(خطوة 6) `order_items`:** لكل منتج بنحفظ `product_name` و `unit_price_cents` **نسخة** من الداتابيز دلوقتي (عشان لو الأدمن غير السعر بعدين، الطلب القديم يفضل صح).
12. **(خطوة 7) لو فيه كوبون:** `INSERT INTO coupon_redemptions (coupon_id, user_id, order_id)`.
13. `db.commit()`.

**لو حصل مشكلة:**

- `except PaymentError` → `db.rollback()` (مفيش حاجة نصها اتعمل)، `log_audit("payment_refused", str(error))`، flash، ورجوع لـ `/checkout`.
- `except sqlite3.IntegrityError` (CHECK أو UNIQUE رفض) → `rollback`، `log_audit("payment_refused", "database rule refused the order")`، ورسالة `The payment could not be completed. Nothing was charged.`

**بعد الـ commit بس:**

14. `log_audit("order_placed", "order=... total_cents=... discount_cents=...")` ولو فيه كوبون `log_audit("coupon_redeemed", ...)`.
15. نشيل `cart` و `coupon_code` و `checkout_token` من السيشن.
16. flash `Thank you! Your order is paid.` و redirect لـ `/orders/<public_id>/confirmation`.

### ج) `GET /orders/<public_id>/confirmation` → `order_confirmation()`

`find_my_order(public_id, paid_only=True)` → يعني الـ SQL:
`SELECT * FROM orders WHERE public_id = ? AND user_id = ? AND status = 'paid'`.
مفيش ولا INSERT ولا UPDATE هنا. لو فتحتها 100 مرة مفيش حاجة بتتغير.

---

## 3. الحمايات

| الحماية | فين بالظبط | بتوقف إيه | المحاضرة / اللاب |
|---------|------------|-----------|------------------|
| السعر والـ total من الداتابيز، مرتين (في `checkout()` عن طريق `load_cart_lines()`، وتاني جوه `pay()`). الفورم بيبعت `checkout_token` بس، وأي `total`/`price`/`user_id` زيادة مش بيتقري | `orders.py` `checkout()`، `pay()`؛ `templates/orders/checkout.html` | تعديل السعر في Burp | **Lab 1** (client-side prices) |
| الكوبون بيتشيك تاني جوه الـ transaction بـ `check_coupon()`، والـ redemption بيتسجل بس لما الدفع ينجح | `pay()` خطوة 2 و 7؛ `UNIQUE (coupon_id, user_id)` | استعمال كوبون اتلغى/خلص/اتستعمل قبل كده، أو نفس الكوبون مرتين | **Lab 2.1** (coupon stacking) |
| الطلب بيتعمل **جوه `pay()` بس** وهو `'paid'`. صفحة التأكيد بتقرا بس ومحتاجة `status = 'paid'` | `pay()` خطوة 5؛ `order_confirmation()`؛ `find_my_order(paid_only=True)` | فتح صفحة التأكيد من غير ما تدفع | **Lab 2.3** (skipping workflow steps) |
| `checkout_token` مرة واحدة: في السيشن + hidden field + `orders.checkout_token UNIQUE` | `checkout()`، `pay()` خطوة 4؛ `schema.sql` | double click، تابين، Burp Repeater يبعت نفس الطلب مرتين → بيتخصم مرة واحدة. كمان موقع تاني ميقدرش يبعت فورم الدفع (مش عارف التوكن) | Lab 2.3 / race condition |
| `BEGIN IMMEDIATE` | `pay()` خطوة 3 | دفعتين في نفس اللحظة يتلخبطوا ويصرفوا أكتر من الكريدت | Lab 2 (infinite money) |
| `... AND store_credit_cents >= ?` + `rowcount` + CHECK `store_credit_cents >= 0` | `pay()` خطوة 3؛ `schema.sql` | الكريدت يبقى سالب ("فلوس بلا نهاية") | Lab 2 / business logic |
| `... AND stock >= ?` + CHECK `stock >= 0` | `pay()` خطوة 4 | بيع أكتر من الموجود | business logic |
| rollback على أي `PaymentError` أو `IntegrityError` | `pay()` `except` | حالة نص-نص (فلوس اتخصمت ومفيش طلب) | **Lecture 3** (fail secure) |
| `AND user_id = ?` في كل lookup، وطلب حد تاني = نفس 404 بتاع طلب مش موجود | `find_my_order()`، `order_history()` | **IDOR**: تشوف طلبات غيرك | **Lecture 2** (IDOR) |
| `public_id = secrets.token_urlsafe(12)` بدل 1، 2، 3 + `PUBLIC_ID_PATTERN` | `pay()`، `find_my_order()` | تخمين أرقام الطلبات | Lecture 2 (IDOR) |
| `?` placeholders في كل SQL | كل `orders.py` | SQL injection | Lecture 2 |
| Jinja2 autoescape، مفيش `|safe` | `templates/orders/*` | XSS في اسم المنتج | Lecture 2 |
| `log_audit` لـ `order_placed`، `coupon_redeemed`، `payment_refused` (بعد الـ commit بس للنجاح) | `pay()` | اليوزر يقول "أنا مطلبتش" (repudiation) | Lecture 2 (audit log) |
| `/checkout/pay` POST بس | `@bp.route(..., methods=["POST"])` | GET من لينك يدفع | – |

### التستات اللي بتثبت ده (`tests/test_orders.py`)

- `test_successful_payment` – الطلب `paid`، الكريدت 100 → 70، الستوك 50 → 48، الكارت اتفضى، `order_placed` في الـ audit.
- `test_price_tampering_at_checkout_is_ignored` – Burp بيزود `total=1`، `price=1`، `user_id=bob` → مفيش تأثير.
- `test_price_change_after_checkout_page_uses_new_price` – السعر اتغير بعد صفحة الـ checkout → الدفع بالسعر الجديد.
- `test_not_enough_credit` – جاكيت $1,337 بـ $100 → `Not enough store credit`، مفيش طلب، `payment_refused`.
- `test_stock_checked_again_at_payment`
- `test_double_payment_charges_once` – نفس الكوكي القديمة + نفس التوكن مرتين → طلب واحد.
- `test_pay_without_valid_token_refused` – توكن مضروب → مفيش طلب؛ `GET /checkout/pay` → 405.
- `test_coupon_used_only_once_after_real_order`، `test_coupon_rechecked_at_payment`، `test_fixed_coupon_can_make_total_zero_but_not_negative`
- `test_confirmation_needs_paid_order_of_the_user`، `test_other_users_order_is_404`، `test_number_ids_do_not_work`، `test_order_pages_need_login`

### الـ attack scripts بتاعتك

- `attack_scripts/08_price_tampering.py` – Lab 1: naive دفع $0.01 للجاكيت؛ SecureShop السعر $1,337.00 والدفع اترفض.
- `attack_scripts/11_workflow_skip.py` – Lab 2.3: naive `/order/confirm` عمل طلب paid بـ $0؛ SecureShop: confirmation=404، `GET pay`=405، `POST` من غير توكن = 302 ومفيش طلب.
- `attack_scripts/12_idor.py` – shopper بيفتح طلب victim حتى لو عارف الـ `public_id` → 404 / 404.
- (`09_coupon_stacking.py` و `10_negative_quantity.py` بتاعة Member 4 و 3، بس الدفع بتاعك هو آخر خط دفاع.)

---

## 4. ديمو في دقيقتين

**التحضير:** `python seed.py` ثم `flask run` (لو بورت 5000 مشغول على الماك: `flask run -p 5050`).
افتح Burp وخلي البراوزر يعدي عليه.

1. **(20 ثانية) دفع عادي:** login بـ `shopper` / `Shopper-Pass-2026` (معاه $100).
   افتح `/products/1` (Classic White T-Shirt، $15)، Add to cart بكمية 2، روح `/cart/` وبعدين **Checkout** → `/checkout`.
   دوس **Pay $30.00 with store credit** → صفحة "Thank you! Your order is confirmed." والـ URL فيه `public_id` عشوائي (مش 1).
   افتح `/account/` → الكريدت بقى $70.00.
2. **(30 ثانية) Lab 1 في Burp:** حط الجاكيت `/products/2` ($1,337) في الكارت، روح `/checkout`، شغل Intercept ودوس Pay.
   في الـ request زود `&total=1&price=1`. Forward → رسالة `Not enough store credit. This order costs $1,337.00.`
   الجمهور يشوف إن السيرفر تجاهل الأرقام بتاعتنا.
3. **(20 ثانية) Double payment:** بعد ما تشيل الجاكيت وتحط حاجة رخيصة، ابعت الـ `POST /checkout/pay` لـ Repeater قبل ما تعمله Forward.
   بعد ما ينجح، ابعته تاني من Repeater بنفس الكوكي → redirect لنفس صفحة التأكيد مع `This order was already paid. You were charged only once.` والكريدت اتخصم مرة واحدة.
4. **(20 ثانية) Lab 2.3 + IDOR:** انسخ URL صفحة التأكيد. اعمل logout، login بـ `victim` / `Victim-Pass-2026`، والصق الـ URL →
   **404** `We could not find that page.` (نفس رسالة طلب مش موجود). جرب كمان `/orders/1` → 404.
5. **(30 ثانية) الإثبات:** login كـ admin (`admin` / `Admin-Pass-2026!` + كود الـ TOTP من الأمر اللي `seed.py` طبعه)، افتح `/admin/audit`
   واختار `payment_refused` ثم `order_placed` → تشوف الصفوف بالـ total.
   (بديل سريع من التيرمنال: `python attack_scripts/run_all.py` واقرا سطور 08 و 11 و 12.)

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **لو غيرت الـ total في Burp هيحصل إيه؟**
   ولا حاجة. `pay()` بيقرا `checkout_token` بس من الفورم، وبيحسب الـ subtotal من جدول `products` جوه الـ transaction. التست: `test_price_tampering_at_checkout_is_ignored`.

2. **ليه بتحسب السعر مرتين؟ مرة في `checkout()` ومرة في `pay()`؟**
   لأن ممكن الأدمن يغير السعر أو الستوك أو يوقف الكوبون بين الصفحتين. الحساب اللي بيتخصم بيه هو اللي جوه الـ transaction. التست: `test_price_change_after_checkout_page_uses_new_price`.

3. **إيه فايدة `BEGIN IMMEDIATE`؟**
   بيقفل الداتابيز للكتابة من أول الـ transaction، فدفعتين في نفس الوقت بيتنفذوا ورا بعض. من غيره ممكن الاتنين يشوفوا نفس الكريدت ويصرفوه مرتين.

4. **إزاي الكريدت ميبقاش سالب؟**
   الـ UPDATE فيه `AND store_credit_cents >= ?`؛ لو الفلوس مش كفاية مفيش صف بيتغير و `rowcount != 1` → `PaymentError`. وكمان CHECK `store_credit_cents >= 0` في `schema.sql` كخط دفاع تاني (هيطلع `IntegrityError` وبنعمل rollback).

5. **الـ `checkout_token` بيعمل إيه؟**
   توكن مرة واحدة (`secrets.token_urlsafe(16)`) في السيشن وفي hidden field. كل طلب بيتحفظ بالتوكن بتاعه و `orders.checkout_token` عليه UNIQUE، فنفس الـ checkout ميعملش غير طلب واحد. ولو حد بعته تاني بنوديه لنفس الطلب القديم من غير ما نخصم. التست: `test_double_payment_charges_once`.

6. **إزاي منعت Lab 2.3 (فتح صفحة التأكيد من غير دفع)؟**
   الطلب مش بيتعمل غير جوه `pay()` بعد ما الفلوس تتخصم، وبيتعمل `'paid'` على طول. `order_confirmation()` بتقرا بس وبتطلب `status = 'paid'` و `user_id` بتاعك. التست: `test_confirmation_needs_paid_order_of_the_user`.

7. **إيه هو الـ IDOR وإزاي اتمنع هنا؟**
   إنك تغير الـ id في الـ URL وتشوف بيانات غيرك. عندنا كل query فيها `AND user_id = ?` بـ `g.user["id"]` من السيشن، والـ id في الـ URL عشوائي (`public_id`). وطلب حد تاني بيدي 404 مش 403 عشان ميعرفش إن الطلب موجود أصلًا. التستات: `test_other_users_order_is_404`، `test_number_ids_do_not_work`.

8. **ليه بتحفظ `unit_price_cents` و `product_name` في `order_items`؟**
   عشان الفاتورة القديمة تفضل زي ما اتدفعت حتى لو الأدمن غير السعر أو الاسم بعدين. ده السعر من الداتابيز وقت الدفع، مش من البراوزر.

9. **لو حصل error في النص، الفلوس بتتخصم؟**
   لأ. أي `PaymentError` أو `sqlite3.IntegrityError` → `db.rollback()` فكل اللي حصل جوه الـ transaction بيترجع. ده **fail secure** (Lecture 3). وبنسجل `payment_refused` في الـ audit log.

10. **ليه `log_audit("order_placed")` بعد الـ commit مش قبله؟**
    لأن `log_audit()` نفسها بتعمل `commit`. لو نادينها جوه الـ transaction كانت هتعمل commit لحاجات نصها خلصت. وكمان منسجلش "اتدفع" إلا لما يكون فعلًا اتدفع.
