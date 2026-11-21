"""Database helpers. We use Python's built-in sqlite3 - no ORM.

SECURITY: always pass user input as "?" parameters, never build SQL with
string formatting or +.

    GOOD: db.execute("SELECT * FROM users WHERE email = ?", (email,))
    BAD:  db.execute("SELECT * FROM users WHERE email = '" + email + "'")
"""
import sqlite3

from flask import current_app, g


def get_db():
    """Return one database connection per request."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row          # rows behave like dicts: row["email"]
        # SECURITY: SQLite ignores foreign keys unless we switch them on
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    """Close the connection at the end of the request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_one(sql, params=()):
    """Run a SELECT and return the first row (or None)."""
    return get_db().execute(sql, params).fetchone()


def query_all(sql, params=()):
    """Run a SELECT and return all rows."""
    return get_db().execute(sql, params).fetchall()
