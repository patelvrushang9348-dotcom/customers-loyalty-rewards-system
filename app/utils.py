import re
from functools import wraps

from flask import jsonify, request, session, g

from .db import get_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def err(message, status=400, **extra):
    return jsonify({"error": message, **extra}), status


def client_ip():
    return request.remote_addr or ""


def json_body():
    """Return the JSON object body, or None. Requiring JSON also blocks
    cross-site form posts (a cheap CSRF defence on top of SameSite cookies)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def customer_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        cid = session.get("customer_id")
        row = get_db().execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone() if cid else None
        if not row:
            return err("Please log in.", 401)
        g.customer = row
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        aid = session.get("admin_id")
        row = get_db().execute("SELECT * FROM admins WHERE id=?", (aid,)).fetchone() if aid else None
        if not row:
            return err("Admin login required.", 401)
        g.admin = row
        return fn(*a, **kw)
    return wrapper
