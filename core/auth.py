"""Student accounts: sign up, log in, password rules and a simple lockout.

Passwords are never stored as plain text. Werkzeug stores a salted hash,
which ships with Flask, so nothing extra to install.
"""
import re
import sqlite3
import time

from werkzeug.security import check_password_hash, generate_password_hash

from . import store

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Used when the username does not exist, so a failed login takes about as long
# as a real one. This stops people guessing which accounts exist.
_DUMMY_HASH = generate_password_hash("not-a-real-password")

MAX_FAILURES = 5
LOCK_WINDOW_SECONDS = 15 * 60
_failures = {}  # "login|ip" -> list of failure times (kept in memory)


def password_problems(password):
    """Return a list of rules the password breaks. Empty list means it is fine."""
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        problems.append("1 uppercase letter")
    if not re.search(r"\d", password):
        problems.append("1 number")
    return problems


def validate_signup(full_name, username, email, password):
    """Return a message for the first problem found, or None if all is well."""
    if not full_name:
        return "Please enter your full name."
    if not USERNAME_RE.match(username):
        return "Username must be 3 to 30 letters, numbers or underscores."
    if not EMAIL_RE.match(email):
        return "Please enter a valid email address."
    problems = password_problems(password)
    if problems:
        return "Password needs: " + ", ".join(problems) + "."
    return None


def create_user(full_name, username, email, password):
    """Save a new student. Returns (True, None) or (False, message)."""
    try:
        with store.connect() as con:
            con.execute(
                "INSERT INTO users(full_name, username, email, password_hash, created) "
                "VALUES(?,?,?,?,?)",
                (full_name, username, email, generate_password_hash(password), time.time()),
            )
        return True, None
    except sqlite3.IntegrityError:
        return False, "That username or email already has an account. Try logging in."


def verify_login(login_name, password):
    """Check a username or email plus password. Returns the user dict or None."""
    with store.connect() as con:
        row = con.execute(
            "SELECT * FROM users WHERE username=? OR email=?", (login_name, login_name)
        ).fetchone()
    if row is None:
        check_password_hash(_DUMMY_HASH, password)  # same work as a real check
        return None
    if check_password_hash(row["password_hash"], password):
        return dict(row)
    return None


def too_many_attempts(key):
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < LOCK_WINDOW_SECONDS]
    _failures[key] = recent
    return len(recent) >= MAX_FAILURES


def record_failure(key):
    _failures.setdefault(key, []).append(time.time())


def clear_failures(key):
    _failures.pop(key, None)
