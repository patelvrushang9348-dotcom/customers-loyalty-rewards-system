import sqlite3

from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash

from .db import get_db, now_str, transaction
from .security import REDEEM_FAIL_KINDS, format_code, generate_code, hash_code, log_event, login_locked
from .utils import admin_required, client_ip, err, json_body

bp = Blueprint("admin", __name__, url_prefix="/api/admin")
MAX_BATCH = 10000


def _int(v, lo, hi):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


# ---------------------------------------------------------------- auth

@bp.post("/login")
def login():
    d = json_body()
    if d is None:
        return err("JSON body required.")
    db, cfg, ip = get_db(), current_app.config, client_ip()
    if login_locked(db, cfg, ip):
        return err("Too many failed logins. Try again later.", 429)
    username = str(d.get("username", "")).strip()
    row = db.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], str(d.get("password", ""))):
        log_event(db, "login_fail", None, ip, f"admin:{username[:80]}")
        return err("Wrong username or password.", 401)
    session.clear()
    session["admin_id"] = row["id"]
    return jsonify({"username": row["username"]})


@bp.post("/logout")
def logout():
    session.pop("admin_id", None)
    return jsonify({"ok": True})


@bp.get("/me")
@admin_required
def me():
    return jsonify({"username": g.admin["username"]})


# ---------------------------------------------------------------- dashboard

@bp.get("/stats")
@admin_required
def stats():
    db = get_db()
    q = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    total = q("SELECT COUNT(*) FROM codes")
    redeemed = q("SELECT COUNT(*) FROM codes WHERE status='redeemed'")
    since24 = now_str(offset_minutes=-24 * 60)
    since14d = now_str(offset_days=-14)
    marks = ",".join("?" * len(REDEEM_FAIL_KINDS))
    per_product = db.execute(
        """SELECT p.name, COUNT(c.id) AS generated,
                  SUM(c.status='redeemed') AS redeemed, SUM(c.status='voided') AS voided
           FROM products p LEFT JOIN batches b ON b.product_id=p.id
                           LEFT JOIN codes c ON c.batch_id=b.id
           GROUP BY p.id ORDER BY p.name""").fetchall()
    daily = db.execute(
        "SELECT date(redeemed_at) AS day, COUNT(*) AS n FROM codes "
        "WHERE status='redeemed' AND redeemed_at >= ? GROUP BY day ORDER BY day", (since14d,)).fetchall()
    return jsonify({
        "codes_generated": total,
        "codes_redeemed": redeemed,
        "redemption_rate": round(redeemed / total, 4) if total else 0,
        "customers": q("SELECT COUNT(*) FROM customers"),
        "suspended_customers": q("SELECT COUNT(*) FROM customers WHERE status='suspended'"),
        "points_issued": q("SELECT COALESCE(SUM(delta),0) FROM point_ledger WHERE reason='code_redeem'"),
        "points_outstanding": q("SELECT COALESCE(SUM(points_balance),0) FROM customers"),
        "pending_claims": q("SELECT COUNT(*) FROM claims WHERE status='pending'"),
        "failed_attempts_24h": db.execute(
            f"SELECT COUNT(*) FROM security_events WHERE kind IN ({marks}) AND created_at >= ?",
            (*REDEEM_FAIL_KINDS, since24)).fetchone()[0],
        "lockouts_24h": q("SELECT COUNT(*) FROM security_events WHERE kind='redeem_locked' AND created_at >= ?", since24),
        "per_product": [{"name": r["name"], "generated": r["generated"], "redeemed": r["redeemed"] or 0,
                         "voided": r["voided"] or 0} for r in per_product],
        "daily_redemptions": [dict(r) for r in daily],
    })


# ---------------------------------------------------------------- products

@bp.get("/products")
@admin_required
def list_products():
    rows = get_db().execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/products")
@admin_required
def create_product():
    d = json_body()
    if d is None:
        return err("JSON body required.")
    name, sku = str(d.get("name", "")).strip(), str(d.get("sku", "")).strip()
    points = _int(d.get("points"), 1, 100000)
    if not name or not sku or points is None:
        return err("Name, SKU and points (1-100000) are required.")
    try:
        cur = get_db().execute("INSERT INTO products (name, sku, points, created_at) VALUES (?,?,?,?)",
                               (name[:120], sku[:60], points, now_str()))
    except sqlite3.IntegrityError:
        return err("A product with this SKU already exists.", 409)
    return jsonify({"id": cur.lastrowid}), 201


@bp.put("/products/<int:pid>")
@admin_required
def update_product(pid):
    d = json_body() or {}
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        return err("Not found.", 404)
    points = _int(d.get("points", row["points"]), 1, 100000)
    if points is None:
        return err("Points must be 1-100000.")
    db.execute("UPDATE products SET name=?, points=?, active=? WHERE id=?",
               (str(d.get("name", row["name"])).strip()[:120] or row["name"], points,
                1 if d.get("active", row["active"]) else 0, pid))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- batches & codes

@bp.post("/batches")
@admin_required
def create_batch():
    """Generate N unique codes. The plaintext codes are returned ONCE in this
    response (for printing); only their hashes are stored."""
    d = json_body()
    if d is None:
        return err("JSON body required.")
    cfg, db = current_app.config, get_db()
    qty = _int(d.get("quantity"), 1, MAX_BATCH)
    pid = _int(d.get("product_id"), 1, 10**9)
    days = _int(d.get("valid_days", cfg["CODE_VALID_DAYS"]), 1, 3650)
    if qty is None or pid is None or days is None:
        return err(f"product_id, quantity (1-{MAX_BATCH}) and valid_days are required.")
    product = db.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    if not product:
        return err("Active product not found.", 404)

    plain = []
    with transaction(db):
        b = db.execute(
            "INSERT INTO batches (product_id, quantity, note, expires_at, created_by, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (pid, qty, str(d.get("note", ""))[:200], now_str(offset_days=days), g.admin["id"], now_str()))
        for _ in range(qty):
            for _attempt in range(5):           # collisions are astronomically unlikely; retry anyway
                code = generate_code(cfg["CODE_PEPPER"])
                try:
                    db.execute("INSERT INTO codes (batch_id, code_hash) VALUES (?,?)",
                               (b.lastrowid, hash_code(code, cfg["CODE_PEPPER"])))
                    plain.append(format_code(code))
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise RuntimeError("Could not generate a unique code")
    return jsonify({"batch_id": b.lastrowid, "product": product["name"], "points": product["points"],
                    "codes": plain}), 201


@bp.get("/batches")
@admin_required
def list_batches():
    rows = get_db().execute(
        """SELECT b.id, b.status, b.quantity, b.note, b.expires_at, b.created_at, p.name AS product,
                  p.points, SUM(c.status='redeemed') AS redeemed, SUM(c.status='voided') AS voided
           FROM batches b JOIN products p ON p.id=b.product_id LEFT JOIN codes c ON c.batch_id=b.id
           GROUP BY b.id ORDER BY b.id DESC""").fetchall()
    return jsonify([{**dict(r), "redeemed": r["redeemed"] or 0, "voided": r["voided"] or 0} for r in rows])


@bp.post("/batches/<int:bid>/void")
@admin_required
def void_batch(bid):
    """Recall a batch (e.g. a printing error or a stolen pallet of labels).
    Unused codes become unusable immediately; already-redeemed ones are untouched."""
    db = get_db()
    with transaction(db):
        if db.execute("UPDATE batches SET status='voided' WHERE id=? AND status='active'", (bid,)).rowcount != 1:
            return err("Active batch not found.", 404)
        n = db.execute("UPDATE codes SET status='voided' WHERE batch_id=? AND status='unused'", (bid,)).rowcount
    return jsonify({"voided_codes": n})


# ---------------------------------------------------------------- rewards catalogue

def _reward_fields(d, row=None):
    name = str(d.get("name", row["name"] if row else "")).strip()
    cost = _int(d.get("points_cost", row["points_cost"] if row else None), 1, 10**7)
    stock_raw = d.get("stock", row["stock"] if row else None)
    stock = None if stock_raw in (None, "") else _int(stock_raw, 0, 10**7)
    if not name or cost is None or (stock_raw not in (None, "") and stock is None):
        return None
    return name[:120], str(d.get("description", row["description"] if row else ""))[:500], cost, stock


@bp.get("/rewards")
@admin_required
def list_rewards():
    return jsonify([dict(r) for r in get_db().execute("SELECT * FROM rewards ORDER BY id DESC")])


@bp.post("/rewards")
@admin_required
def create_reward():
    d = json_body()
    f = _reward_fields(d or {})
    if not d or not f:
        return err("Name and a points cost are required; stock must be blank (unlimited) or a number.")
    cur = get_db().execute(
        "INSERT INTO rewards (name, description, points_cost, stock, created_at) VALUES (?,?,?,?,?)",
        (*f, now_str()))
    return jsonify({"id": cur.lastrowid}), 201


@bp.put("/rewards/<int:rid>")
@admin_required
def update_reward(rid):
    db = get_db()
    row = db.execute("SELECT * FROM rewards WHERE id=?", (rid,)).fetchone()
    d = json_body() or {}
    if not row:
        return err("Not found.", 404)
    f = _reward_fields(d, row)
    if not f:
        return err("Invalid reward values.")
    db.execute("UPDATE rewards SET name=?, description=?, points_cost=?, stock=?, active=? WHERE id=?",
               (*f, 1 if d.get("active", row["active"]) else 0, rid))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- claims

@bp.get("/claims")
@admin_required
def list_claims():
    status = request.args.get("status")
    sql = ("SELECT c.id, c.status, c.points_spent, c.created_at, c.updated_at, r.name AS reward, "
           "u.name AS customer, u.email FROM claims c JOIN rewards r ON r.id=c.reward_id "
           "JOIN customers u ON u.id=c.customer_id")
    args = []
    if status in ("pending", "fulfilled", "cancelled"):
        sql += " WHERE c.status=?"
        args.append(status)
    rows = get_db().execute(sql + " ORDER BY c.id DESC LIMIT 200", args).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/claims/<int:cid>/status")
@admin_required
def set_claim_status(cid):
    d = json_body() or {}
    new = d.get("status")
    if new not in ("fulfilled", "cancelled"):
        return err("status must be 'fulfilled' or 'cancelled'.")
    db = get_db()
    with transaction(db):
        claim = db.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
        if not claim:
            return err("Not found.", 404)
        if claim["status"] != "pending":
            return err(f"Claim is already {claim['status']}.", 409)
        db.execute("UPDATE claims SET status=?, updated_at=? WHERE id=?", (new, now_str(), cid))
        if new == "cancelled":      # refund points and return the item to stock
            db.execute("UPDATE customers SET points_balance = points_balance + ? WHERE id=?",
                       (claim["points_spent"], claim["customer_id"]))
            db.execute("UPDATE rewards SET stock = stock + 1 WHERE id=? AND stock IS NOT NULL",
                       (claim["reward_id"],))
            db.execute(
                "INSERT INTO point_ledger (customer_id, delta, reason, ref_id, note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (claim["customer_id"], claim["points_spent"], "claim_refund", cid, "Claim cancelled", now_str()))
    return jsonify({"ok": True, "status": new})


# ---------------------------------------------------------------- customers & fraud monitoring

@bp.get("/customers")
@admin_required
def list_customers():
    since = now_str(offset_days=-7)
    marks = ",".join("?" * len(REDEEM_FAIL_KINDS))
    rows = get_db().execute(
        f"""SELECT u.id, u.name, u.email, u.points_balance, u.status, u.created_at,
                   (SELECT COUNT(*) FROM codes c WHERE c.redeemed_by=u.id) AS codes_redeemed,
                   (SELECT COUNT(*) FROM security_events e WHERE e.customer_id=u.id
                      AND e.kind IN ({marks}) AND e.created_at >= ?) AS failures_7d
            FROM customers u ORDER BY failures_7d DESC, u.id DESC LIMIT 500""",
        (*REDEEM_FAIL_KINDS, since)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/customers/<int:uid>/status")
@admin_required
def set_customer_status(uid):
    d = json_body() or {}
    if d.get("status") not in ("active", "suspended"):
        return err("status must be 'active' or 'suspended'.")
    if get_db().execute("UPDATE customers SET status=? WHERE id=?", (d["status"], uid)).rowcount != 1:
        return err("Not found.", 404)
    return jsonify({"ok": True})


@bp.get("/events")
@admin_required
def list_events():
    kind = request.args.get("kind")
    sql = ("SELECT e.id, e.kind, e.ip, e.detail, e.created_at, u.email AS customer "
           "FROM security_events e LEFT JOIN customers u ON u.id=e.customer_id")
    args = []
    if kind:
        sql += " WHERE e.kind=?"
        args.append(kind)
    rows = get_db().execute(sql + " ORDER BY e.id DESC LIMIT 200", args).fetchall()
    return jsonify([dict(r) for r in rows])
