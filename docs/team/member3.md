# Member 3 – عربة التسوق (`cart.py`)

الملفات بتاعتك: `cart.py`، `templates/cart/cart.html`، `tests/test_cart.py`.
ملفات مرتبطة: `config.MAX_QUANTITY_PER_ITEM` (= 10)، جدول `products`، `orders.py` (بيستخدم `get_cart()` و `load_cart_lines()`)، `coupons.py` (`check_coupon()`)، `templates/catalog/detail.html` (فورم الإضافة).

---

## 1. الملفات والدوال اللي بتاعتك

| الاسم | بيعمل إيه في سطر |
|------|------------------|
| `bp = Blueprint("cart", __name__, url_prefix="/cart")` | كل الـ routes تحت `/cart` |
| `QUANTITY_PATTERN = re.compile(r"\d{1,2}")` | الكمية أرقام بس (رقم أو رقمين) |
| `PRODUCT_ID_PATTERN = re.compile(r"\d{1,9}")` | الـ id أرقام بس |
| `QUANTITY_ERROR` | `"Quantity must be a whole number from 1 to 10."` |
| `parse_quantity(text)` | regex + من 1 لـ 10، وترجّع `(quantity, None)` أو `(None, error)` |
| `find_active_product(text)` | تجيب المنتج لو الـ id أرقام والمنتج `is_active = 1` |
| `get_cart()` | نسخة من `session["cart"]` = `{"product_id": quantity}` |
| `save_cart(cart)` | ترجّع العربة للسيشن |
| `load_cart_lines()` | تبني العربة **من الداتابيز**: السعر والمخزون والمخفي، وترجّع `(lines, subtotal_cents)` |
| `view_cart()` → `GET /cart/` | تعرض العربة، وتعيد حساب الكوبون |
| `add_to_cart()` → `POST /cart/add` | تضيف منتج |
| `update_quantity()` → `POST /cart/update` | تغيّر الكمية |
| `remove_from_cart()` → `POST /cart/remove` | تشيل منتج |

كل الـ routes عليها `@login_required`. والتعديل كله POST بس.

`cart.html`: كل الأسعار والمجاميع اتحسبت على السيرفر. الفورمز بتبعت `product_id` و `quantity` بس. وفيها كمان فورم الكوبون (`coupons.apply_coupon`) وزرار `Remove coupon`.

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

مثال: shopper بيضيف الجاكيت (id 2، $1,337.00، stock 5).

1. صفحة `/products/2` فيها فورم `POST /cart/add` بـ `product_id=2&quantity=1`.
2. `add_to_cart()` بتقرا **بس** `product_id` و `quantity`. أي `price` أو `total` اتزوّد في Burp عمره ما بيتقري.
3. `find_active_product("2")`: `PRODUCT_ID_PATTERN.fullmatch` ثم `SELECT id, name, price_cents, stock FROM products WHERE id = ? AND is_active = 1`. لو `None` → `That product does not exist.`
4. `parse_quantity("1")`: لازم يطابق `\d{1,2}` كله، وبعدين `1 ≤ q ≤ 10`. أي حاجة تانية (`-1`, `0`, `1.5`, `" 1"`, `1e1`, `11`) → `QUANTITY_ERROR`.
5. `new_quantity = cart.get("2", 0) + quantity`. لو أكبر من 10 → `You can have at most 10 of one product in your cart.` ولو أكبر من الـ stock → `Sorry, only 5 in stock.`
6. `cart["2"] = new_quantity` → `save_cart(cart)`. السيشن دلوقتي `{"2": 1}`، **مفيش سعر**.
7. redirect لـ `GET /cart/` → `view_cart()` → `load_cart_lines()`:
   - لكل `product_id`: `SELECT id, name, price_cents, stock, is_active FROM products WHERE id = ?`.
   - مش موجود أو مخفي → يتشال، ورسالة `... is no longer available and was removed from your cart.`
   - الكمية أكبر من المخزون → تنزل للمخزون (`Only N of ... left - your quantity was changed.`)، أو تتشال لو المخزون 0.
   - `line_total = price_cents * quantity`، و `subtotal += line_total`.
8. لو فيه `session["coupon_code"]`: `check_coupon(g.user["id"], coupon_code, subtotal)` بتتنادى من جديد. لو فيه خطأ، الكوبون بيتشال: `Your coupon was removed: ...`.
9. التمبلت بيعرض `subtotal` و `discount` و `total = subtotal - discount`.
10. وقت الدفع (`orders.py`، Member 5): `checkout()` بتنادي `load_cart_lines()` تاني، و `pay()` بتعيد السعر والمخزون **جوه** `BEGIN IMMEDIATE`. يعني العربة عمرها ما هي مصدر الحقيقة للفلوس.

`update_quantity()`: نفس التشييكات، والمنتج لازم يكون في العربة أصلاً (`That product is not in your cart.`).
`remove_from_cart()`: بتمسح الـ key بس لو موجود في العربة، مفيش أي تأثير تاني.

---

## 3. الحمايات

| # | الحماية | فين بالظبط | بتمنع إيه | المصدر | الإثبات |
|---|---------|-----------|-----------|--------|---------|
| 1 | العربة `{"product_id": quantity}` بس، مفيش سعر أو total في السيشن | `get_cart()`, `save_cart()`, `add_to_cart()` | Lab 1: `price=1` في Burp | Lab 1 (trusting client-side prices) | `08_price_tampering.py` (الـ naive دفع $0.01، احنا `$1,337.00` والدفع اترفض: مفيش كريدت كفاية)؛ `test_price_field_from_browser_is_ignored` |
| 2 | السعر بيتجاب من `products` **كل مرة** بنعرض العربة | `load_cart_lines()` | سعر قديم أو مزيف | Lab 1 | `test_price_comes_from_database_every_time` |
| 3 | الكمية: `\d{1,2}` و 1–10 | `parse_quantity()`, `QUANTITY_PATTERN` | كمية سالبة → total سالب → الكريدت يزيد ("infinite money")؛ و `0`, `1.5`, `1e1`, أرقام ضخمة | Lab 2.2 (unusual input) + Lab 1 | `10_negative_quantity.py` (الـ naive الكريدت زاد من $99.99 لـ $249.99، احنا فضل $100.00)؛ `test_bad_quantities_rejected` |
| 4 | الكمية ≤ المخزون، والإضافة مرتين متعديش 10 | `add_to_cart()`, `update_quantity()` | طلب أكتر من الموجود، وتعدي الحد بإضافات صغيرة | Lab 2.2 | `test_quantity_not_more_than_stock`, `test_adding_twice_cannot_pass_10`, `test_update_quantity` |
| 5 | منتج مش موجود أو مخفي مش بيدخل العربة، ولو اتخفى بعد الإضافة بيتشال برسالة | `find_active_product()`, `load_cart_lines()` | شراء منتج مخفي بتخمين الـ id | Lecture 2 | `test_unknown_or_inactive_product_rejected`, `test_inactive_product_removed_from_cart_with_message` |
| 6 | الكوبون بيتعاد حسابه كل عرض للعربة، والسيشن فيه الكود بس | `view_cart()` → `check_coupon()` | خصم قديم بعد ما العربة صغرت | Lab 2.1 | (في `tests/test_coupons.py`) `test_coupon_rechecked_when_cart_changes` |
| 7 | `@login_required` على كل route | `security.login_required` | استخدام العربة من غير حساب | Lecture 2 (least privilege) | `test_cart_requires_login` |
| 8 | التعديل POST بس | `methods=["POST"]` | لينك أو صورة على موقع تاني تعدل عربتك | Lecture 2 | `test_cart_changes_need_post` (GET → 405) |
| 9 | السيشن موقّع بـ `SECRET_KEY` | `config.py` | تعديل العربة من الكوكي نفسها | Lab 3 (cookie tampering) | شرح الكومنت في `config.py` |
| 10 | `?` placeholders، و `int(...)` بعد الـ regex | `find_active_product()`, `load_cart_lines()` | SQL injection في `product_id` | Lecture 2 | `03_debug_errors.py` بيبعت `product_id` = 5000 حرف → صفحة عادية من غير stack trace |
| 11 | الحماية الأخيرة في الداتابيز: `CHECK (quantity BETWEEN 1 AND 10)` في `order_items`، و `price_cents > 0` و `stock >= 0` | `schema.sql` | لو تشييك في الكود اتنسى | Lecture 3 (fail secure / defense in depth) | الـ CHECKs نفسها |

**STRIDE (F3):** كله T (Tampering): السعر، الكمية الغريبة، id مش موجود، تعديل الكوكي، المخزون. في الـ DREAD: T1 price tampering = **9.4** (أعلى واحد في المشروع)، T4 negative quantity = 9.0.

---

## 4. ديمو في دقيقتين

التحضير: `python seed.py` ثم `flask run`. Burp شغال كـ proxy. ادخل بـ `shopper` / `Shopper-Pass-2026` (معاه $100).

1. **(40 ثانية) Lab 1 بـ Burp.** افتح `/products/2` (Leather Jacket، `$1,337.00`). شغّل Intercept ودوس "Add to cart". في الـ request `product_id=2&quantity=1` زوّد `&price=1&total=1` واعمل Forward. صفحة العربة بتقول `$1,337.00`. "السيرفر مقراش الـ price خالص."
2. **(20 ثانية) الدفع.** دوس "Go to checkout" ثم Pay → `Not enough store credit. This order costs $1,337.00.` (المعاه $100 بس).
3. **(30 ثانية) كمية سالبة.** في Burp Repeater ابعت `POST /cart/add` بـ `product_id=1&quantity=-10` → `Quantity must be a whole number from 1 to 10.` جرّب `quantity=11` و `quantity=1.5` → نفس الرسالة. "في الـ naive app الكمية السالبة زوّدت الكريدت."
4. **(15 ثانية) الإضافة مرتين.** أضف T-Shirt (`/products/1`) بكمية 8، وبعدين 3 → `You can have at most 10 of one product in your cart.`
5. **(15 ثانية) المنتج المخفي.** في Repeater ابعت `product_id=9` (Old Coffee Mug المخفي) → `That product does not exist.`
6. **(اختياري)** امسح الجاكيت بـ Remove عشان الديمو اللي بعدك.

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **السيشن موقّع ومحدش يقدر يعدله. ليه مانخزنش السعر فيه؟**
   التوقيع بيمنع التعديل، بس مش بيخلي الرقم صح. السعر ممكن يتغير بعد ما اليوزر يضيف المنتج، أو المنتج يتخفى. والقاعدة من Lab 1: الداتابيز هي مصدر الحقيقة الوحيد للفلوس. فـ `load_cart_lines()` بتقرا السعر من جديد كل مرة، و `pay()` بتقراه تاني جوه الـ transaction.

2. **ليه regex للكمية ومش `int()` وخلاص؟**
   `int()` بيقبل `"-1"` و `" 1"` و `"+5"` و `"1_0"` (= 10) وأرقام ضخمة جداً. الـ regex `\d{1,2}` بيقبل رقمين بالكتير ومفيش علامة، وبعدين بنشيك من 1 لـ 10.

3. **إيه هو هجوم "infinite money" وإزاي بيتمنع؟**
   كمية `-10` تخلي الـ total سالب، فالدفع يزوّد الكريدت بدل ما ينقصه. هنا `parse_quantity()` بترفض السالب والصفر، و `schema.sql` فيه `CHECK (quantity BETWEEN 1 AND 10)` و `store_credit_cents >= 0`. السكريبت `10_negative_quantity.py` بيثبت إن الكريدت فضل $100.00.

4. **لو السعر اتغير بعد ما ضفت المنتج، هتدفع أنهي سعر؟**
   السعر الجديد. `load_cart_lines()` بتجيب `price_cents` كل مرة. التست `test_price_comes_from_database_every_time` بيغير السعر لـ $20 وبيلاقي $40.00 لقطعتين.

5. **لو المنتج اتخفى أو المخزون خلص وهو في العربة؟**
   `load_cart_lines()` بتشيله (`is_active != 1` أو stock = 0) أو بتنزّل الكمية للمخزون، وبتعرض رسالة، وبتحفظ العربة الجديدة. والدفع نفسه بيعيد التشييك ويرفض لو الحال اتغير (`Not enough stock for ...`).

6. **هل التشييكات في `cart.py` كفاية لوحدها؟**
   لأ، ودي defense in depth. `orders.pay()` بتعيد كل حاجة جوه `BEGIN IMMEDIATE`: السعر والمخزون والكوبون، والكريدت بـ `... AND store_credit_cents >= ?`. وجدول `schema.sql` فيه CHECK constraints كخط دفاع أخير.

7. **ليه add و update و remove بـ POST بس؟**
   الـ GET ممكن يحصل من `<img src="...">` على أي موقع، فيعدل عربتك من غير ما تعرف. مع POST و `SESSION_COOKIE_SAMESITE = "Lax"` الكوكي مش بتتبعت في POST جاي من موقع تاني.

8. **ليه `remove_from_cart()` مفيهاش regex على الـ `product_id`؟**
   لأنها بتعمل حاجة واحدة بس: `if product_id in cart: del cart[product_id]`. مفيش داتابيز ولا SQL. أي قيمة مش موجودة في العربة بتدي `That product is not in your cart.` ومفيش أي تأثير.

9. **ليه الـ keys في العربة نصوص (`"2"`) مش أرقام؟**
   سيشن Flask بيتخزن JSON، وفي JSON الـ keys لازم تبقى نصوص. علشان كده الكود بيستخدم `str(product["id"])` وهو بيكتب، و `int(product_id)` وهو بيقرا من الداتابيز.

10. **ليه `from coupons import check_coupon` جوه `view_cart()` مش فوق؟**
    عشان `coupons.py` بيعمل import لـ `cart.py` (`from cart import load_cart_lines` جوه `apply_coupon()`). لو الاتنين عملوا import في أول الملف هيحصل circular import. فالـ import بيحصل وقت ما الدالة تشتغل.
