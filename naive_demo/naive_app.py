"""
###########################################################################
#                                                                         #
#   VULNERABLE ON PURPOSE - FOR CLASS DEMO ONLY                           #
#                                                                         #
#   This is the "naive implementation" from the project brief. Every     #
#   mistake here is deliberate and marked "# VULNERABLE:". It exists so   #
#   attack_scripts/ can show each attack WORKING here and FAILING on the  #
#   real SecureShop.                                                      #
#                                                                         #
#   - NEVER import this file from SecureShop.                             #
#   - NEVER copy code from here into SecureShop.                          #
#   - Run it only on your own machine: it listens on 127.0.0.1:5001.      #
#                                                                         #
###########################################################################

Run:  python naive_demo/seed_naive.py   then   python naive_demo/naive_app.py
"""
import hashlib
import os
import random
import secrets
import sqlite3
import traceback

from flask import Flask, g, redirect, render_template_string, request, session
from werkzeug.exceptions import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(HERE, "naive.db")
OUTBOX = os.path.join(HERE, "outbox")

app = Flask(__name__)
# VULNERABLE: a short secret key written in the code (anyone with the code can forge sessions).
app.secret_key = "naive"

PAGE = """<!doctype html><title>NaiveShop</title>
<p><b>NaiveShop</b> (vulnerable demo) | <a href="/">home</a> | <a href="/search">search</a> |
<a href="/cart">cart</a> | <a href="/login">login</a> | <a href="/register">register</a> |
<a href="/admin">admin</a></p><hr>{{ body|safe }}"""


def page(body):
    return render_template_string(PAGE, body=body)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close(error=None):
    if "db" in g:
        g.db.close()


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def current_user():
    # VULNERABLE: who you are comes from a PLAIN cookie that you can edit
    # (Lab 3). Change user_id=1 to user_id=2 and you are someone else.
    # VULNERABLE: and the cookie is glued into the SQL (SQL injection again).
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    return db().execute("SELECT * FROM users WHERE id = " + user_id).fetchone()


def send_email(text):
    os.makedirs(OUTBOX, exist_ok=True)
    with open(os.path.join(OUTBOX, f"{secrets.token_hex(4)}.txt"), "w") as f:
        f.write(text)


def logged_in(response, user):
    response.set_cookie("user_id", str(user["id"]))
    # VULNERABLE: the role is kept in a plain cookie too.
    response.set_cookie("role", user["role"])
    return response


# VULNERABLE: debug-style error page - shows the full stack trace, file
# paths and code to anyone (Lecture 3 "fail secure"). debug=True would be
# even worse: it also gives an interactive Python console.
@app.errorhandler(Exception)
def show_error(error):
    if isinstance(error, HTTPException):
        return error
    return "<h1>Internal error</h1><pre>" + traceback.format_exc() + "</pre>", 500


@app.route("/")
def index():
    user = current_user()
    who = f"Logged in as {user['username']} (credit ${user['credit_cents'] / 100:.2f})" if user else "Not logged in"
    return page(f"<p>{who}</p><p>Products: " + ", ".join(
        f'<a href="/product/{p["id"]}">{p["name"]}</a>'
        for p in db().execute("SELECT * FROM products")) + "</p>")


# ---------------- registration (Lab 2.2) ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return page('<form method="post">username <input name="username"> email <input name="email"> '
                    'password <input name="password"> <button>Register</button></form>')
    # VULNERABLE (Lab 2.2): the email is silently CUT to 255 characters ...
    email = request.form["email"][:255]
    # VULNERABLE (Lab 2.2): ... and the role is decided from the email domain.
    role = "admin" if email.endswith("@secureshop.com") else "user"
    # VULNERABLE: no password rules at all ("123" is fine), and MD5 without salt.
    db().execute("INSERT INTO users (username, email, password_md5, role, credit_cents) "
                 "VALUES (?, ?, ?, ?, 10000)",
                 (request.form["username"], email, md5(request.form["password"]), role))
    db().commit()
    return page(f"<p>Account created with role {role}.</p>")


# ---------------- login (L4-L5, Lab 3) ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return page('<form method="post">username <input name="username"> password '
                    '<input name="password" type="password"> <button>Log in</button></form>'
                    '<p><a href="/forgot">Forgot password?</a></p>')
    user = db().execute("SELECT * FROM users WHERE username = ?", (request.form["username"],)).fetchone()
    # VULNERABLE: two different messages tell the attacker which usernames exist.
    if user is None:
        return page("<p>Unknown username.</p>"), 401
    # VULNERABLE: no lockout and no counter - try a million passwords if you like.
    if user["password_md5"] != md5(request.form["password"]):
        return page("<p>Wrong password.</p>"), 401
    if user["role"] == "admin":
        # VULNERABLE (Lab 3): the 2FA step remembers WHO you are in a plain cookie.
        response = redirect("/login2")
        response.set_cookie("verify", user["username"])
        return response
    return logged_in(redirect("/"), user)


@app.route("/login2", methods=["GET", "POST"])
def login2():
    # VULNERABLE (Lab 3): the user comes from the "verify" cookie - change it
    # to another username and you are entering THEIR code.
    user = db().execute("SELECT * FROM users WHERE username = ?",
                        (request.cookies.get("verify", ""),)).fetchone()
    if user is None:
        return redirect("/login")
    if request.method == "GET":
        if not user["twofa_code"]:
            # VULNERABLE: a 4-digit code (only 10,000 possibilities), and
            # random.randint instead of secrets.
            code = f"{random.randint(0, 9999):04d}"
            db().execute("UPDATE users SET twofa_code = ? WHERE id = ?", (code, user["id"]))
            db().commit()
            send_email(f"To: {user['email']}\nYour login code: {code}\n")
        return page('<form method="post">code <input name="code"> <button>Verify</button></form>')
    # VULNERABLE: no attempt limit, and the code is never cleared after use,
    # so the same code works again and again (no reuse protection).
    if request.form.get("code") == user["twofa_code"]:
        return logged_in(redirect("/admin"), user)
    return page("<p>Wrong code.</p>"), 401


@app.route("/logout")
def logout():
    # VULNERABLE: GET logout, and the cookies are just deleted in this browser.
    response = redirect("/")
    response.delete_cookie("user_id")
    response.delete_cookie("role")
    return response


# ---------------- password reset ----------------
@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "GET":
        return page('<form method="post">username <input name="username"> <button>Send link</button></form>')
    user = db().execute("SELECT * FROM users WHERE username = ?", (request.form["username"],)).fetchone()
    if user is None:
        return page("<p>No such user.</p>")             # VULNERABLE: user enumeration again
    token = secrets.token_hex(8)
    # VULNERABLE: the token is stored in plain text, never expires and is never deleted.
    db().execute("INSERT INTO reset_tokens (token, user_id) VALUES (?, ?)", (token, user["id"]))
    db().commit()
    send_email(f"To: {user['email']}\nReset link: /reset?token={token}\n")
    return page("<p>Reset link sent.</p>")


@app.route("/reset", methods=["GET", "POST"])
def reset():
    token = request.values.get("token", "")
    row = db().execute("SELECT * FROM reset_tokens WHERE token = ?", (token,)).fetchone()
    if row is None:
        return page("<p>Bad token.</p>"), 400
    if request.method == "GET":
        return page(f'<form method="post"><input type="hidden" name="token" value="{token}">'
                    'new password <input name="password"> <button>Save</button></form>')
    db().execute("UPDATE users SET password_md5 = ? WHERE id = ?",
                 (md5(request.form["password"]), row["user_id"]))
    db().commit()
    # VULNERABLE: the token is NOT marked used - the same link works forever.
    return page("<p>Password changed.</p>")


# ---------------- catalogue (L2: SQL injection, XSS) ----------------
@app.route("/search")
def search():
    q = request.args.get("q", "")
    # VULNERABLE (SQL injection): the search text is glued into the SQL.
    sql = "SELECT name, price_cents FROM products WHERE name LIKE '%" + q + "%'"
    rows = db().execute(sql).fetchall()
    # VULNERABLE (XSS): the search text is put into the page without escaping (|safe).
    return render_template_string(
        '<p><a href="/">home</a></p><form>search <input name="q"> <button>Go</button></form>'
        "<p>Results for {{ q|safe }}:</p><ul>{% for r in rows %}<li>{{ r[0] }} - {{ r[1] }}</li>{% endfor %}</ul>",
        q=q, rows=rows)


@app.route("/product/<product_id>")
def product(product_id):
    # VULNERABLE: int() on user input without a check - "abc" crashes and
    # the error page above shows the stack trace.
    p = db().execute("SELECT * FROM products WHERE id = ?", (int(product_id),)).fetchone()
    return page(f'<h2>{p["name"]}</h2><p>${p["price_cents"] / 100:.2f}</p>'
                f'<form method="post" action="/cart/add"><input type="hidden" name="product_id" value="{p["id"]}">'
                f'<input type="hidden" name="price" value="{p["price_cents"]}">'
                'quantity <input name="quantity" value="1"> <button>Add to cart</button></form>')


# ---------------- cart, coupons, checkout (Labs 1, 2.1, 2.3) ----------------
@app.route("/cart/add", methods=["POST"])
def cart_add():
    cart = session.get("cart", [])
    cart.append({
        "product_id": request.form["product_id"],
        # VULNERABLE (Lab 1): the PRICE comes from the browser (hidden field).
        "price": int(request.form["price"]),
        # VULNERABLE: quantity is not checked - 0, -10 or 99999 are all fine.
        "quantity": int(request.form["quantity"]),
    })
    session["cart"] = cart
    return redirect("/cart")


def cart_total():
    subtotal = sum(item["price"] * item["quantity"] for item in session.get("cart", []))
    # VULNERABLE (Lab 2.1): every applied coupon is ADDED - they stack.
    percent = sum(session.get("coupons", []))
    return subtotal, subtotal * percent // 100, subtotal - subtotal * percent // 100


@app.route("/cart")
def cart():
    subtotal, discount, total = cart_total()
    return page(f"<p>Items: {session.get('cart', [])}</p><p>Coupons: {session.get('coupons', [])}</p>"
                f"<p>Subtotal: {subtotal}</p><p>Discount: {discount}</p><p>TOTAL: {total}</p>"
                '<form method="post" action="/coupon/apply">code <input name="code"> <button>Apply</button></form>'
                '<form method="post" action="/checkout/pay"><button>Pay</button></form>'
                '<p><a href="/order/confirm">Confirm order</a></p>')


@app.route("/coupon/apply", methods=["POST"])
def coupon_apply():
    row = db().execute("SELECT * FROM coupons WHERE code = ?", (request.form["code"],)).fetchone()
    if row:
        # VULNERABLE (Lab 2.1): the code is added to a LIST - no "one coupon"
        # rule, no "once per user" rule, no maximum.
        session["coupons"] = session.get("coupons", []) + [row["percent"]]
    return redirect("/cart")


def create_order(user, total, status):
    items = ", ".join(f"{i['quantity']} x product {i['product_id']}" for i in session.get("cart", []))
    cur = db().execute("INSERT INTO orders (user_id, total_cents, status, items) VALUES (?, ?, ?, ?)",
                       (user["id"], total, status, items))
    db().commit()
    session.pop("cart", None)
    session.pop("coupons", None)
    return cur.lastrowid


@app.route("/checkout/pay", methods=["POST"])
def pay():
    user = current_user()
    subtotal, discount, total = cart_total()
    # VULNERABLE: no "credit >= total" check and no transaction - a negative
    # total ADDS money, and two quick clicks can both be charged.
    db().execute("UPDATE users SET credit_cents = credit_cents - ? WHERE id = ?", (total, user["id"]))
    order_id = create_order(user, total, "paid")
    return redirect(f"/order/{order_id}")


@app.route("/order/confirm")
def order_confirm():
    # VULNERABLE (Lab 2.3): visiting the confirmation page CREATES a paid
    # order from the cart - without taking any money.
    user = current_user()
    subtotal, discount, total = cart_total()
    order_id = create_order(user, total, "paid")
    return page(f"<p>Thank you! Order {order_id} is confirmed.</p>")


@app.route("/order/<int:order_id>")
def order(order_id):
    # VULNERABLE (IDOR): no "AND user_id = ?" - change the number to see anyone's order.
    row = db().execute("SELECT o.*, u.username, u.email FROM orders o JOIN users u ON u.id = o.user_id "
                       "WHERE o.id = ?", (order_id,)).fetchone()
    if row is None:
        return page("<p>No such order.</p>"), 404
    return page(f"<p>Order {row['id']} of {row['username']} ({row['email']}): {row['items']}, "
                f"total {row['total_cents']} cents, status {row['status']}</p>")


# ---------------- admin (least privilege) ----------------
@app.route("/admin")
def admin():
    # VULNERABLE: the admin check reads a cookie the user can set themselves.
    if request.cookies.get("role") != "admin":
        return page("<p>Admins only.</p>"), 403
    rows = db().execute("SELECT id, username, email, role, password_md5, credit_cents FROM users").fetchall()
    return page("<h2>All users</h2><ul>" + "".join(
        f"<li>{r['id']} {r['username']} {r['email']} {r['role']} {r['password_md5']} {r['credit_cents']}</li>"
        for r in rows) + "</ul>")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
