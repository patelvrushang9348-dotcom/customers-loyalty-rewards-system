from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, now_str, transaction
from .security import (hash_code, is_well_formed, log_event, login_locked, normalize,
                       redeem_locked)
from .utils import EMAIL_RE, client_ip, customer_required, err, json_body

bp = Blueprint("customer", __name__, url_prefix="/api")


def _public(c):
    return {"id": c["id"], "email": c["email"], "name": c["name"],
            "points_balance": c["points_balance"], "status": c["status"]}


# ---------------------------------------------------------------- auth

@bp.post("/register")
def register():
    d = json_body()
    if d is None:
        return err("JSON body required.")
    email = str(d.get("email", "")).strip().lower()
    name = str(d.get("name", "")).strip()
    password = str(d.get("password", ""))
    if not EMAIL_RE.match(email) or len(email) > 254:
        return err("Enter a valid email address.")
    if not (1 <= len(name) <= 80):
        return err("Enter your name (max 80 characters).")
    if len(password) < 8 or len(password) > 128:
        return err("Password must be 8 to 128 characters.")
    db = get_db()
    if db.execute("SELECT 1 FROM customers WHERE email=?", (email,)).fetchone():
        return err("An account with this email already exists.", 409)
    cur = db.execute(
        "INSERT INTO customers (email, name, password_hash, created_at) VALUES (?,?,?,?)",
        (email, name, generate_password_hash(password), now_str()))
    session.clear()
    session["customer_id"] = cur.lastrowid
    row = db.execute("SELECT * FROM customers WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(_public(row)), 201


@bp.post("/login")
def login():
    d = json_body()
    if d is None:
        return err("JSON body required.")
    db, cfg, ip = get_db(), current_app.config, client_ip()
    if login_locked(db, cfg, ip):
        return err("Too many failed logins. Try again later.", 429)
    email = str(d.get("email", "")).strip().lower()
    row = db.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], str(d.get("password", ""))):
        log_event(db, "login_fail", row["id"] if row else None, ip, f"customer:{email[:80]}")
        return err("Wrong email or password.", 401)
    session.clear()
    session["customer_id"] = row["id"]
    return jsonify(_public(row))


@bp.post("/logout")
def logout():
    session.pop("customer_id", None)
    return jsonify({"ok": True})


@bp.get("/me")
@customer_required
def me():
    return jsonify(_public(g.customer))


# ---------------------------------------------------------------- redeem

def _fail(db, kind, status, message, cust, ip, detail=None):
    log_event(db, kind, cust["id"], ip, detail)
    return err(message, status)


@bp.post("/redeem")
@customer_required
def redeem():
    """Proof of purchase: the customer types the code printed inside the box.

    Order of checks: account active -> not locked out -> well-formed (offline
    checksum) -> hash lookup -> batch active / not expired -> atomic
    'unused -> redeemed' UPDATE. The conditional UPDATE is what makes a code
    single-use even if two requests arrive at the same instant.
    """
    d = json_body()
    if d is None:
        return err("JSON body required.")
    cfg, db, cust, ip = current_app.config, get_db(), g.customer, client_ip()

    if cust["status"] != "active":
        return err("This account is suspended. Please contact the factory.", 403)

    if redeem_locked(db, cfg, cust["id"], ip):
        log_event(db, "redeem_locked", cust["id"], ip)
        return err("Too many failed attempts. Please try again in "
                   f"{cfg['LOCKOUT_WINDOW_MINUTES']} minutes.", 429)

    code = normalize(str(d.get("code", "")))
    if not is_well_formed(code, cfg["CODE_PEPPER"]):
        return _fail(db, "redeem_malformed", 400,
                     "That code doesn't look right. Check for typos.", cust, ip)

    h = hash_code(code, cfg["CODE_PEPPER"])
    outcome = None  # (kind, status, message, detail)
    result = None
    with transaction(db):
        row = db.execute(
            """SELECT c.id, c.status, c.redeemed_by, b.status AS bstatus, b.expires_at,
                      p.points, p.name AS product
               FROM codes c JOIN batches b ON b.id = c.batch_id
                            JOIN products p ON p.id = b.product_id
               WHERE c.code_hash = ?""", (h,)).fetchone()
        if row is None:
            outcome = ("redeem_invalid", 404, "Code not recognised.", None)
        elif row["status"] == "redeemed":
            mine = row["redeemed_by"] == cust["id"]
            outcome = ("redeem_used", 409,
                       "You have already redeemed this code." if mine else "This code has already been used.",
                       f"code_id={row['id']} first_used_by={row['redeemed_by']}")
        elif row["status"] == "voided" or row["bstatus"] == "voided":
            outcome = ("redeem_voided", 410, "This code has been cancelled.", f"code_id={row['id']}")
        elif row["expires_at"] and row["expires_at"] < now_str():
            outcome = ("redeem_expired", 410, "This code has expired.", f"code_id={row['id']}")
        else:
            cur = db.execute(
                "UPDATE codes SET status='redeemed', redeemed_by=?, redeemed_at=? "
                "WHERE id=? AND status='unused'", (cust["id"], now_str(), row["id"]))
            if cur.rowcount != 1:      # lost a race with another request
                outcome = ("redeem_used", 409, "This code has already been used.", f"code_id={row['id']} race")
            else:
                db.execute(
                    "INSERT INTO point_ledger (customer_id, delta, reason, ref_id, note, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (cust["id"], row["points"], "code_redeem", row["id"], row["product"], now_str()))
                db.execute("UPDATE customers SET points_balance = points_balance + ? WHERE id=?",
                           (row["points"], cust["id"]))
                result = {"points_earned": row["points"], "product": row["product"]}

    # Logged after the transaction so failures are recorded even though nothing was written.
    if outcome:
        kind, status, message, detail = outcome
        return _fail(db, kind, status, message, cust, ip, detail)
    log_event(db, "redeem_ok", cust["id"], ip, f"{result['product']} +{result['points_earned']}")
    balance = db.execute("SELECT points_balance FROM customers WHERE id=?", (cust["id"],)).fetchone()[0]
    return jsonify({**result, "points_balance": balance})


# ---------------------------------------------------------------- rewards

@bp.get("/rewards")
@customer_required
def list_rewards():
    rows = get_db().execute(
        "SELECT id, name, description, points_cost, stock FROM rewards WHERE active=1 "
        "ORDER BY points_cost, id").fetchall()
    return jsonify([{**dict(r), "available": r["stock"] is None or r["stock"] > 0} for r in rows])


class _Abort(Exception):
    """Raised inside a transaction to roll everything back and return a response."""
    def __init__(self, message, status):
        self.message, self.status = message, status


@bp.post("/rewards/<int:reward_id>/claim")
@customer_required
def claim_reward(reward_id):
    db, cust = get_db(), g.customer
    if cust["status"] != "active":
        return err("This account is suspended. Please contact the factory.", 403)
    try:
        with transaction(db):
            reward = db.execute("SELECT * FROM rewards WHERE id=? AND active=1", (reward_id,)).fetchone()
            if not reward:
                raise _Abort("Reward not found.", 404)
            # Both guards live in conditional UPDATEs so concurrent claims cannot overspend.
            spent = db.execute(
                "UPDATE customers SET points_balance = points_balance - ? "
                "WHERE id=? AND points_balance >= ?",
                (reward["points_cost"], cust["id"], reward["points_cost"]))
            if spent.rowcount != 1:
                raise _Abort("Not enough points.", 402)
            stocked = db.execute(
                "UPDATE rewards SET stock = CASE WHEN stock IS NULL THEN NULL ELSE stock - 1 END "
                "WHERE id=? AND (stock IS NULL OR stock > 0)", (reward_id,))
            if stocked.rowcount != 1:
                raise _Abort("Sorry, this reward is out of stock.", 409)  # rolls back the deduction
            t = now_str()
            c = db.execute(
                "INSERT INTO claims (customer_id, reward_id, points_spent, created_at, updated_at) "
                "VALUES (?,?,?,?,?)", (cust["id"], reward_id, reward["points_cost"], t, t))
            db.execute(
                "INSERT INTO point_ledger (customer_id, delta, reason, ref_id, note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (cust["id"], -reward["points_cost"], "reward_claim", c.lastrowid, reward["name"], t))
    except _Abort as a:
        return err(a.message, a.status)
    balance = db.execute("SELECT points_balance FROM customers WHERE id=?", (cust["id"],)).fetchone()[0]
    return jsonify({"claim_id": c.lastrowid, "status": "pending", "points_balance": balance}), 201


@bp.get("/history")
@customer_required
def history():
    db, cid = get_db(), g.customer["id"]
    ledger = db.execute(
        "SELECT delta, reason, note, created_at FROM point_ledger WHERE customer_id=? "
        "ORDER BY id DESC LIMIT 50", (cid,)).fetchall()
    claims = db.execute(
        "SELECT c.id, r.name AS reward, c.points_spent, c.status, c.created_at FROM claims c "
        "JOIN rewards r ON r.id=c.reward_id WHERE c.customer_id=? ORDER BY c.id DESC LIMIT 50",
        (cid,)).fetchall()
    return jsonify({"ledger": [dict(r) for r in ledger], "claims": [dict(r) for r in claims]})
