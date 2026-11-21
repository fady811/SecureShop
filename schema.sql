-- SecureShop database schema (SQLite)
--
-- Money is stored as whole CENTS (INTEGER), never as floating point:
-- 1337.00 is stored as 133700. This avoids rounding tricks.
-- Expiry times are stored as Unix seconds (INTEGER) so they are easy to compare.
--
-- SECURITY: the CHECK constraints are a second line of defense. The Python
-- code must validate first; the database refuses bad values even if a check
-- in the code is forgotten.

DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS coupon_failed_attempts;
DROP TABLE IF EXISTS login_attempts;
DROP TABLE IF EXISTS email_confirm_tokens;
DROP TABLE IF EXISTS password_reset_tokens;
DROP TABLE IF EXISTS newsletter_subscribers;
DROP TABLE IF EXISTS coupon_redemptions;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS coupons;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    NOT NULL UNIQUE COLLATE NOCASE
                                CHECK (length(username) BETWEEN 3 AND 30),
    email               TEXT    NOT NULL UNIQUE COLLATE NOCASE
                                CHECK (length(email) BETWEEN 3 AND 254),
    full_name           TEXT    NOT NULL DEFAULT '' CHECK (length(full_name) <= 100),
    shipping_address    TEXT    NOT NULL DEFAULT '' CHECK (length(shipping_address) <= 200),
    password_hash       TEXT    NOT NULL,              -- Argon2id hash, never the password
    -- SECURITY: role is set explicitly (register = 'user'; only an admin can change it)
    role                TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_confirmed        INTEGER NOT NULL DEFAULT 0 CHECK (is_confirmed IN (0, 1)),
    -- SECURITY: credit can never go below zero (no "infinite money")
    store_credit_cents  INTEGER NOT NULL DEFAULT 0 CHECK (store_credit_cents >= 0),
    totp_secret         TEXT,                          -- NULL = 2FA not set up yet
    totp_last_step      INTEGER NOT NULL DEFAULT 0,    -- last used TOTP time step (no replay)
    failed_login_count  INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until        INTEGER NOT NULL DEFAULT 0,    -- Unix time; 0 = not locked
    -- how many times the account has been locked; each new lock is twice as long
    lock_count          INTEGER NOT NULL DEFAULT 0 CHECK (lock_count >= 0),
    -- SECURITY: an admin can disable an account; disabled users cannot log in
    is_disabled         INTEGER NOT NULL DEFAULT 0 CHECK (is_disabled IN (0, 1)),
    -- SECURITY: copied into the session at login and compared on every request.
    -- Increased on logout, password change and role change, so an old
    -- (copied) session cookie stops working.
    session_version     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    description  TEXT    NOT NULL DEFAULT '' CHECK (length(description) <= 2000),
    category     TEXT    NOT NULL CHECK (length(category) BETWEEN 1 AND 50),
    price_cents  INTEGER NOT NULL CHECK (price_cents > 0),
    stock        INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE coupons (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT    NOT NULL UNIQUE COLLATE NOCASE      -- compared case-insensitively
                                CHECK (length(code) BETWEEN 3 AND 32),
    -- 'percent' = discount_value is a percent; 'fixed' = discount_value is in cents
    discount_type       TEXT    NOT NULL CHECK (discount_type IN ('percent', 'fixed')),
    -- SECURITY: a percent coupon can never be more than 30% (config.MAX_DISCOUNT_PERCENT)
    discount_value      INTEGER NOT NULL CHECK (
                            (discount_type = 'percent' AND discount_value BETWEEN 1 AND 30)
                         OR (discount_type = 'fixed'   AND discount_value > 0)),
    max_discount_cents  INTEGER CHECK (max_discount_cents > 0),     -- NULL = no extra cap
    min_total_cents     INTEGER NOT NULL DEFAULT 0 CHECK (min_total_cents >= 0),
    max_uses            INTEGER CHECK (max_uses > 0),               -- NULL = unlimited (all users together)
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    expires_at          INTEGER,                                    -- Unix time; NULL = never expires
    -- NULL = anyone can use it; otherwise only this user (newsletter coupons)
    owner_user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- SECURITY: random id used in every URL instead of 1, 2, 3 ... (no guessing)
    public_id       TEXT    NOT NULL UNIQUE,
    -- SECURITY: one checkout = at most one order (double click / two tabs)
    checkout_token  TEXT    UNIQUE,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    -- SECURITY: the server tracks the workflow state of every order
    status          TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'paid', 'cancelled')),
    subtotal_cents  INTEGER NOT NULL CHECK (subtotal_cents > 0),
    discount_cents  INTEGER NOT NULL DEFAULT 0
                            CHECK (discount_cents >= 0 AND discount_cents <= subtotal_cents),
    total_cents     INTEGER NOT NULL CHECK (total_cents >= 0),
    -- SECURITY: ONE coupon per order (a single column, not a list)
    coupon_id       INTEGER REFERENCES coupons(id),
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at         TEXT,
    CHECK (total_cents = subtotal_cents - discount_cents)
);

CREATE TABLE order_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id          INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id        INTEGER NOT NULL REFERENCES products(id),
    product_name      TEXT    NOT NULL,                -- copy, so history survives renames
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents > 0),  -- price from the DB at payment time
    quantity          INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 10),
    UNIQUE (order_id, product_id)
);

CREATE TABLE coupon_redemptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id    INTEGER NOT NULL REFERENCES coupons(id),
    user_id      INTEGER NOT NULL REFERENCES users(id),
    order_id     INTEGER NOT NULL UNIQUE REFERENCES orders(id),  -- one coupon per order
    redeemed_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- SECURITY: each user can use a coupon code only once
    UNIQUE (coupon_id, user_id)
);

CREATE TABLE newsletter_subscribers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,  -- one signup per account
    -- SECURITY: also one signup per email address
    email          TEXT    NOT NULL UNIQUE COLLATE NOCASE CHECK (length(email) BETWEEN 3 AND 254),
    coupon_id      INTEGER REFERENCES coupons(id),     -- the personal coupon we issued
    subscribed_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- SECURITY: tokens are stored as a SHA-256 hash, so a stolen database
-- does not give working reset/confirm links. The real token is only in the email.
CREATE TABLE password_reset_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT    NOT NULL UNIQUE,
    expires_at  INTEGER NOT NULL,                      -- created + 15 minutes
    used_at     INTEGER,                               -- NULL = not used yet (single use)
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE email_confirm_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT    NOT NULL UNIQUE,
    expires_at  INTEGER NOT NULL,                      -- created + 24 hours
    used_at     INTEGER,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Every login try (also for usernames that do not exist), for brute-force detection
CREATE TABLE login_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL,
    ip_address    TEXT    NOT NULL,
    success       INTEGER NOT NULL CHECK (success IN (0, 1)),
    attempted_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- SECURITY: wrong coupon codes per user, to stop people guessing codes
-- (max 10 wrong codes in 10 minutes, see coupons.py)
CREATE TABLE coupon_failed_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    attempted_at  INTEGER NOT NULL                     -- Unix time
);

-- SECURITY: accountability - who did what, and when
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- NULL = anonymous
    action      TEXT    NOT NULL,                      -- e.g. login_failed, order_paid
    details     TEXT    NOT NULL DEFAULT '',
    ip_address  TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_login_attempts_username ON login_attempts(username);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);
CREATE INDEX idx_coupon_failed_user ON coupon_failed_attempts(user_id, attempted_at);
