# Member 2 – كتالوج المنتجات (`catalog.py`)

الملفات بتاعتك: `catalog.py`، `templates/catalog/list.html`، `templates/catalog/detail.html`، `tests/test_catalog.py`.
ملفات مرتبطة: `config.py` (الحدود)، جدول `products` في `schema.sql`، `db.py` (`query_all`, `query_one`)، `app.py` (صفحات الخطأ).

---

## 1. الملفات والدوال اللي بتاعتك

| الاسم | بيعمل إيه في سطر |
|------|------------------|
| `bp = Blueprint("catalog", __name__, url_prefix="/products")` | كل الـ routes تحت `/products` |
| `SORT_OPTIONS` | allow-list: كل key ليه (اسم يظهر، نص SQL ثابت). الـ keys: `name`, `price_asc`, `price_desc` |
| `DEFAULT_SORT = "name"` | الترتيب لو الـ key مش معروف |
| `PRICE_PATTERN` | `\d{1,7}(\.\d{1,2})?` – رقم موجب، لحد رقمين بعد العلامة |
| `parse_price(text, label)` | تحوّل `"12.50"` لـ `1250` cents، أو ترجّع رسالة خطأ |
| `escape_like(text)` | تخلي `%` و `_` و `\` حروف عادية في الـ LIKE |
| `product_list()` → `GET /products/` | البحث والفلترة والترتيب |
| `product_detail(product_id)` → `GET /products/<int:product_id>` | صفحة منتج واحد |

التمبلتس:
- `list.html`: فورم GET فيه `q`, `category`, `min_price`, `max_price`, `sort`، وبيعرض `Results for "..."`.
- `detail.html`: فورم "Add to cart" بيبعت `product_id` و `quantity` بس (**مفيش حقل سعر**)، والـ `max` بتاع الكمية = `max_quantity`.

الحدود من `config.py`: `MAX_SEARCH_LENGTH = 100`، `MAX_CATEGORY_LENGTH = 50`، `MAX_PRICE_FILTER_CENTS = 100000000` ($1,000,000)، `MAX_QUANTITY_PER_ITEM = 10`.

---

## 2. الفيتشر بتشتغل إزاي خطوة بخطوة

مثال: `GET /products/?q=jacket&category=Clothing&min_price=20&max_price=2000&sort=price_desc`

1. `product_list()` بتقرا كل parameter بـ `request.args.get(...)` وتعمل `.strip()` (مسافات بس، مفيش قص).
2. `sort`: لو مش موجود في `SORT_OPTIONS` بيبقى `DEFAULT_SORT`. يعني `?sort=price;DROP TABLE users` بيترتب بالاسم عادي.
3. التشييكات، وكل غلطة بتتحط في `errors`:
   - `q` أطول من 100 → `Search text must be at most 100 characters.`
   - `category` أطول من 50 → `Unknown category.`
   - `parse_price(min_text, "Minimum price")` و `parse_price(max_text, "Maximum price")`: فاضي = الفلتر مش مستخدم؛ مش مطابق للـ regex → `... must be a number of 0 or more, like 10 or 9.99.`؛ أكبر من المليون → `... is too large.`
   - min > max → `Minimum price cannot be higher than maximum price.`
4. قايمة الأقسام: `SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category`.
5. لو مفيش أخطاء، بنبني الـ SQL من **حتت ثابتة**، والـ input بيروح في `params` بس:
   ```sql
   SELECT id, name, category, price_cents, stock FROM products WHERE is_active = 1
     AND name LIKE ? ESCAPE '\'      -- params: "%" + escape_like(q) + "%"
     AND category = ?
     AND price_cents >= ?
     AND price_cents <= ?
     ORDER BY price_cents DESC, name ASC   -- النص ده من SORT_OPTIONS، مش من اليوزر
   ```
6. `render_template("catalog/list.html", ...)` بكود 400 لو فيه أخطاء، و 200 لو لأ. `{{ q }}` بيتعمله escape أوتوماتيك.
7. اليوزر بيدوس على منتج → `GET /products/2` → `<int:product_id>` معناها Flask مش هينادي الدالة غير لو رقم صحيح. `/products/abc` → 404 قبل ما الكود بتاعنا يشتغل.
8. `product_detail()`: `SELECT ... FROM products WHERE id = ? AND is_active = 1`. لو `None` (مش موجود **أو** مخفي) → `abort(404)` → صفحة `error.html` برسالة `We could not find that page.`
9. `max_quantity = min(config.MAX_QUANTITY_PER_ITEM, product["stock"])` وبتتبعت للتمبلت.

---

## 3. الحمايات

| # | الحماية | فين بالظبط | بتمنع إيه | المصدر | الإثبات |
|---|---------|-----------|-----------|--------|---------|
| 1 | `?` placeholders في كل query، والـ `%` بيتضاف في Python مش في الـ SQL | `product_list()`, `product_detail()` | SQL injection في البحث (`' UNION SELECT username, password_md5 FROM users --`) | Lecture 2 (SQL injection) | `01_sql_injection.py` (الـ naive سرّب 3 hashes، احنا `0 found`)؛ `test_sql_injection_in_search_returns_no_extra_rows` |
| 2 | `SORT_OPTIONS` allow-list لـ `ORDER BY` | أول `catalog.py` + سطر `sql += " ORDER BY " + SORT_OPTIONS[sort][1]` | SQL injection في `?sort=` (مينفعش فيه `?`) | Lecture 2 (SQLi) – اتلقى وإحنا بنبني، T15 في الـ DREAD = 8.2 | `test_bad_sort_value_is_ignored` (بيبعت `price_cents; DROP TABLE users` والجدول لسه موجود) |
| 3 | `category = ?` | `product_list()` | injection في القسم: `Clothing' OR '1'='1` بيدور على قسم بالاسم ده حرفياً | Lecture 2 | `test_sql_injection_in_category_and_price` |
| 4 | `parse_price()` بـ `PRICE_PATTERN` + حد أقصى + min ≤ max | `parse_price()`, `product_list()` | قيم غريبة: `-5`, `1e3`, `nan`, `abc`, `10.999`, `0 OR 1=1` | Lab 2.2 (unusual input) + Lecture 3 (fail secure) | `test_bad_price_filters_rejected` (بيشيك كمان إن مفيش `Traceback`)، `test_filter_by_price_range` |
| 5 | الطويل بيترفض مش بيتقص (بحث ≤ 100، قسم ≤ 50) | `product_list()` | Lab 2.2: قص بيخلي حاجة تتعامل بشكلين | Lab 2.2 | `test_too_long_search_rejected` (101 → 400، 100 → 200) |
| 6 | `escape_like()` + `ESCAPE '\'` | `escape_like()` | `?q=%` يعرض كل المنتجات (مش injection، بس سلوك غلط) | Lecture 2 (input handling) | `test_like_wildcards_are_plain_text` |
| 7 | Jinja2 autoescape، ومفيش `|safe` | `templates/catalog/list.html` (`Results for "<strong>{{ q }}</strong>"`) | Reflected XSS (`<script>alert(1)</script>`) | Lecture 2 (XSS) | `02_xss.py`؛ `test_script_in_search_is_escaped` |
| 8 | `is_active = 1` في **كل** query، والمخفي والمش موجود نفس الـ 404 | `product_list()`, `product_detail()`، والأقسام كمان | الوصول لمنتج مخفي بتخمين الـ id (زي `Old Coffee Mug`) | Lecture 2 (least privilege / info disclosure) | `test_list_shows_only_active_products`, `test_unknown_hidden_or_bad_id_gives_custom_404` |
| 9 | `<int:product_id>` | decorator بتاع `product_detail()` | `/products/1' OR 1=1` أو `/products/abc` | Lecture 2 + Lecture 3 | `test_unknown_hidden_or_bad_id_gives_custom_404` |
| 10 | صفحات خطأ ودودة، `DEBUG = False`، ومفيش stack trace | `app.py` `render_error()`, `config.DEBUG` (مش ملفك بس بيحمي صفحاتك) | معرفة الكود والمسارات من الـ stack trace | Lecture 3 (fail secure) | `03_debug_errors.py` (بيجرب `/products/abc` و `?min_price=abc`) |
| 11 | فورم المنتج مفيهوش حقل سعر | `templates/catalog/detail.html` | Lab 1 (السعر من المتصفح) – الدفاع الحقيقي في `cart.py` | Lab 1 | `test_product_detail` (`name="price"` مش موجود) |
| 12 | الفلوس integer cents | `parse_price()` (`round(float(text) * 100)`) + `schema.sql` | أخطاء التقريب | Lecture 2 | `test_filter_by_price_range` |

**STRIDE (F2 في `docs/02_threat_model.md`):** T/I = SQL injection في `q` و `category` و `sort`؛ T = XSS؛ I = المنتجات المخفية؛ D = بحث طويل جداً (100 حرف + `MAX_CONTENT_LENGTH` = 1 MB).

---

## 4. ديمو في دقيقتين

التحضير: `python seed.py` ثم `flask run`. مش محتاج تسجيل دخول. أرقام المنتجات بعد الـ seed: 1 T-Shirt، 2 Leather Jacket ($1,337.00)، 3 Running Shoes … 8 Notebook، و **9 = Old Coffee Mug (مخفي)**.

1. **(30 ثانية) SQL injection.** في خانة البحث على `/products/` اكتب `' OR 1=1 --` واعمل Search → `Results for "' OR 1=1 --": 0 found`. "النص اتدور عليه كاسم منتج، مش اتنفذ كـ SQL."
2. **(25 ثانية) ORDER BY + Burp.** اختار "Price (high to low)" واعمل Search. في Burp Repeater غيّر `sort=price_desc` لـ `sort=price_cents;DROP TABLE users` → 200 والمنتجات مترتبة بالاسم. اعمل Refresh عادي → كل حاجة لسه شغالة.
3. **(20 ثانية) XSS.** ابحث عن `<script>alert(1)</script>` → مفيش alert، النص بيظهر زي ما هو. اعمل View Source → `&lt;script&gt;`.
4. **(20 ثانية) أسعار غريبة.** في Min price اكتب `-5` → `Minimum price must be a number of 0 or more, like 10 or 9.99.` جرّب `1e3` → نفس الرسالة. Min `50` و Max `10` → `Minimum price cannot be higher than maximum price.`
5. **(15 ثانية) `%`.** ابحث عن `%` → `0 found` (مش كل المنتجات).
6. **(20 ثانية) المخفي والـ id الغلط.** افتح `/products/9` → `We could not find that page.` افتح `/products/abc` → نفس الصفحة. افتح `/products/2` → الجاكيت بـ `$1,337.00`، وفي الـ View Source الفورم فيه `product_id` و `quantity` بس.

---

## 5. 10 أسئلة متوقعة من الدكتور

1. **ليه `ORDER BY` مينفعش ياخد `?` placeholder؟**
   الـ placeholder بيربط **قيمة** (value)، مش اسم عمود ولا كلمة SQL زي `ASC`/`DESC`. لو كتبنا `ORDER BY ?` وبعتنا `"price_cents"`، SQLite هيرتب بالنص الثابت `'price_cents'`، يعني نفس القيمة لكل صف، فمفيش ترتيب أصلاً. علشان كده اليوزر بيبعت key، وإحنا بنجيب نص الـ SQL من `SORT_OPTIONS`.

2. **لو `?` بيمنع الـ SQL injection، ليه محتاجين `escape_like()`؟**
   `escape_like()` مش للـ injection. الـ `%` و `_` جوه قيمة الـ LIKE بيبقوا wildcards حتى لو جايين كـ parameter. من غيرها البحث عن `%` هيرجّع كل المنتجات. بنحوّلهم لحروف عادية ونكتب `ESCAPE '\'`.

3. **ليه regex للسعر ومش `float(text)` وخلاص؟**
   `float()` بيقبل `"nan"` و `"inf"` و `"1e3"` و `"-5"`. الـ `nan` بالذات بيبوظ المقارنات. الـ regex `\d{1,7}(\.\d{1,2})?` بيقبل رقم موجب عادي بس، وبعده بنشيك `MAX_PRICE_FILTER_CENTS`.

4. **ليه المنتج المخفي بيدي 404 مش 403؟**
   الـ 403 معناها "موجود بس مش مسموحلك"، يعني بيقول للمهاجم إن الـ id ده موجود. بالـ 404 المخفي والمش موجود شكلهم واحد (`abort(404)` في الحالتين).

5. **إيه اللي بيعمله `<int:product_id>`؟**
   الـ URL converter في Flask بيقبل أرقام صحيحة بس. `/products/abc` أو `/products/1' OR 1=1` بيدوا 404 قبل ما الدالة تشتغل، فالـ `product_id` جوه الدالة دايماً `int`. وبرضه بنمرّره بـ `?`.

6. **إزاي بتمنع XSS في "Results for ..."؟**
   Jinja2 autoescape شغال على ملفات `.html` في Flask بشكل افتراضي، فـ `<` بتبقى `&lt;`. القاعدة: مفيش `|safe` ولا `Markup()` على أي داتا من اليوزر. والكوكي `HttpOnly` كمان، فلو حصل XSS، الـ JavaScript مش هيقدر يقرا الكوكي.

7. **ليه البحث الطويل بيترفض بدل ما يتقص لـ 100؟**
   ده درس Lab 2.2: لو قصّينا في مكان واستخدمنا النص كامل في مكان تاني، النظام بيتعامل مع نفس الـ input بشكلين. القاعدة في المشروع كله: حد أقصى واحد لكل حقل في `config.py`، والأطول بيترفض برسالة.

8. **الـ `sort` الغلط بيتجاهل ومفيش رسالة، والسعر الغلط بيدي رسالة. ليه الفرق؟**
   الـ `sort` جاي من dropdown، يعني اليوزر العادي عمره ما هيبعت قيمة غلط، واللي بيبعت غلط غالباً بيجرب injection. فالـ default آمن ومش بيضر حد. السعر بقى اليوزر بيكتبه بإيده، فلازم نقوله إيه الغلط.

9. **ليه الأسعار بالـ cents (integer)؟**
   الـ float مش دقيق (`0.1 + 0.2 != 0.3`)، وأخطاء التقريب الصغيرة ممكن تتستغل. `133700` = $1,337.00. والفلتر بيتحوّل بـ `round(float(text) * 100)` بعد ما الـ regex يضمن إن الرقم فيه رقمين عشريين بالكتير.

10. **إيه الـ threat model لجزءك؟**
    في STRIDE (F2): Tampering/Information disclosure = SQLi في `q` و `category` و `sort`؛ Tampering = reflected XSS؛ Information disclosure = المنتجات المخفية؛ DoS = البحث الطويل جداً. في الـ DREAD، الـ SQL injection (T2) = 9.0 وفي الـ `sort` (T15) = 8.2، يعني High.
