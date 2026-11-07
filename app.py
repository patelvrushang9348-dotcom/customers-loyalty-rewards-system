"""Customer Loyalty Rewards System: Flask API + static front end."""
import hashlib
import hmac
import re
import secrets
import sqlite3
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import config
import db

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 symbols, no I/O/0/1 to avoid misreads
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIERS = [("Bronze", 0), ("Silver", 500), ("Gold", 1500)]


class Fail(Exception):
    def __init__(self, message, status=400, **extra):
        self.message, self.status, self.extra = message, status, extra


# ---------- code helpers ----------
def normalize(code):
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def code_hash(code):
    return hmac.new(config.CODE_PEPPER.encode(), normalize(code).encode(), hashlib.sha256).hexdigest()


def new_code():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))  # 32^12 = 60 bits
    return "-".join(raw[i:i + 4] for i in (0, 4, 8))


def tier_info(lifetime):
    name, idx = TIERS[0][0], 0
    for i, (n, floor) in enumerate(TIERS):
        if lifetime >= floor:
            name, idx = n, i
    nxt = TIERS[idx + 1] if idx + 1 < len(TIERS) else None
    return {"name": name, "next": nxt[0] if nxt else None,
            "to_next": (nxt[1] - lifetime) if nxt else 0,
            "floor": TIERS[idx][1], "ceiling": nxt[1] if nxt else None}


def public_user(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"],
            "points": u["points_balance"], "lifetime": u["lifetime_points"],
            "tier": tier_info(u["lifetime_points"])}


def audit(action, detail=""):
    actor = g.user["id"] if getattr(g, "user", None) else None
    db.get().execute("INSERT INTO audit(actor_id, action, detail) VALUES (?,?,?)", (actor, action, detail))


def record_attempt(user_id, outcome, chash=None):
    db.get().execute("INSERT INTO attempts(user_id, ip, outcome, code_hash) VALUES (?,?,?,?)",
                     (user_id, request.remote_addr or "?", outcome, chash))


# ---------- decorators ----------
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not g.user:
            raise Fail("Sign in to continue.", 401)
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if g.user["role"] != "admin":
            raise Fail("Factory owner access only.", 403)
        return fn(*a, **kw)
    return wrapper


def create_app(db_path=None):
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config.update(SECRET_KEY=config.SECRET_KEY, DB_PATH=db_path or config.DB_PATH,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=config.COOKIE_SECURE)
    db.init_db(app.config["DB_PATH"])
    app.teardown_appcontext(db.close)
    ensure_admin(app)

    @app.before_request
    def load_user():
        g.user = None
        if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            # CSRF defence: browsers cannot add this header cross-site without CORS approval
            if request.headers.get("X-Requested-With") != "fetch":
                raise Fail("Missing request header.", 403)
        uid = session.get("uid")
        if uid:
            u = db.row(db.get(), "SELECT * FROM users WHERE id=?", uid)
            if u and not u["blocked"]:
                g.user = u
            else:
                session.clear()

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(Fail)
    def on_fail(e):
        return jsonify(error=e.message, **e.extra), e.status

    @app.errorhandler(404)
    def on_404(_):
        return (jsonify(error="Not found."), 404) if request.path.startswith("/api/") else send_from_directory("static", "index.html")

    @app.errorhandler(405)
    def on_405(_):
        return jsonify(error="Method not allowed."), 405

    @app.errorhandler(500)
    def on_500(_):
        return jsonify(error="Unexpected server error."), 500

    @app.get("/")
    def index():
        return send_from_directory("static", "index.html")

    @app.get("/api/health")
    def health():
        db.scalar(db.get(), "SELECT 1")
        return jsonify(status="ok")

    register_auth(app)
    register_customer(app)
    register_admin(app)
    return app


def ensure_admin(app):
    if not (config.ADMIN_EMAIL and config.ADMIN_PASSWORD):
        return
    conn = db.connect(app.config["DB_PATH"])
    if not db.row(conn, "SELECT id FROM users WHERE email=?", config.ADMIN_EMAIL):
        conn.execute("INSERT INTO users(email,name,password_hash,role) VALUES (?,?,?,'admin')",
                     (config.ADMIN_EMAIL, "Factory Owner", generate_password_hash(config.ADMIN_PASSWORD)))
    conn.close()


# ---------- auth ----------
def register_auth(app):
    @app.post("/api/register")
    def register():
        d = request.get_json(silent=True) or {}
        email, name, pw = str(d.get("email", "")).strip(), str(d.get("name", "")).strip(), str(d.get("password", ""))
        if not EMAIL_RE.match(email):
            raise Fail("Enter a valid email address.")
        if not 1 <= len(name) <= 80:
            raise Fail("Enter your name.")
        if len(pw) < 8:
            raise Fail("Password must be at least 8 characters.")
        try:
            cur = db.get().execute("INSERT INTO users(email,name,password_hash) VALUES (?,?,?)",
                                   (email, name, generate_password_hash(pw)))
        except sqlite3.IntegrityError:
            raise Fail("An account with this email already exists.", 409)
        session.clear()
        session["uid"] = cur.lastrowid
        return jsonify(user=public_user(db.row(db.get(), "SELECT * FROM users WHERE id=?", cur.lastrowid))), 201

    @app.post("/api/login")
    def login():
        conn, d = db.get(), request.get_json(silent=True) or {}
        recent = db.scalar(conn, "SELECT COUNT(*) FROM attempts WHERE outcome='login_failed' AND ip=? "
                                 "AND created_at >= datetime('now','-15 minutes')", request.remote_addr or "?")
        if recent >= config.MAX_LOGIN_FAILS_PER_IP:
            raise Fail("Too many failed sign-ins. Try again in 15 minutes.", 429)
        u = db.row(conn, "SELECT * FROM users WHERE email=?", str(d.get("email", "")).strip())
        if not u or u["blocked"] or not check_password_hash(u["password_hash"], str(d.get("password", ""))):
            record_attempt(None, "login_failed")
            raise Fail("Email or password is incorrect.", 401)
        session.clear()
        session["uid"] = u["id"]
        return jsonify(user=public_user(u))

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    def me():
        return jsonify(user=public_user(g.user) if g.user else None)


# ---------- customer ----------
def register_customer(app):
    @app.post("/api/codes/redeem")
    @login_required
    def redeem():
        conn, uid = db.get(), g.user["id"]
        fails_user = db.scalar(conn, "SELECT COUNT(*) FROM attempts WHERE user_id=? AND outcome IN ('invalid','reused','voided') "
                                     "AND created_at >= datetime('now','-15 minutes')", uid)
        fails_ip = db.scalar(conn, "SELECT COUNT(*) FROM attempts WHERE ip=? AND outcome IN ('invalid','reused','voided') "
                                   "AND created_at >= datetime('now','-1 hour')", request.remote_addr or "?")
        if fails_user >= config.MAX_CODE_FAILS_PER_USER or fails_ip >= config.MAX_CODE_FAILS_PER_IP:
            record_attempt(uid, "rate_limited")
            raise Fail("Too many wrong codes. Wait 15 minutes and try again.", 429)

        raw = (request.get_json(silent=True) or {}).get("code", "")
        if len(normalize(raw)) != 12:
            record_attempt(uid, "invalid")
            raise Fail("Codes have 12 letters and numbers, like ABCD-EFGH-JKLM.", 400)
        chash = code_hash(raw)
        c = db.row(conn, "SELECT c.*, b.status AS batch_status, p.points, p.name AS product FROM codes c "
                         "JOIN batches b ON b.id=c.batch_id JOIN products p ON p.id=b.product_id WHERE c.code_hash=?", chash)
        if not c:
            record_attempt(uid, "invalid", chash)
            raise Fail("That code doesn't match any box. Check it and try again.", 404)
        if c["status"] == "voided" or c["batch_status"] == "voided":
            record_attempt(uid, "voided", chash)
            raise Fail("This code has been cancelled. Contact the factory if you think this is a mistake.", 410)
        if c["status"] == "redeemed":
            record_attempt(uid, "reused", chash)
            own = c["redeemed_by"] == uid
            raise Fail("You already claimed this code." if own else "This code has already been used.", 409)

        with db.tx(conn):
            # Atomic claim: only one caller can flip unused -> redeemed
            n = conn.execute("UPDATE codes SET status='redeemed', redeemed_by=?, redeemed_at=datetime('now') "
                             "WHERE id=? AND status='unused'", (uid, c["id"])).rowcount
            if n != 1:
                raise Fail("This code has already been used.", 409)
            conn.execute("UPDATE users SET points_balance=points_balance+?, lifetime_points=lifetime_points+? WHERE id=?",
                         (c["points"], c["points"], uid))
            conn.execute("INSERT INTO ledger(user_id,delta,reason,ref) VALUES (?,?,?,?)",
                         (uid, c["points"], f"Bought {c['product']}", c["serial"]))
        record_attempt(uid, "success", chash)
        user = db.row(conn, "SELECT * FROM users WHERE id=?", uid)
        return jsonify(points_added=c["points"], product=c["product"], serial=c["serial"], user=public_user(user))

    @app.get("/api/history")
    @login_required
    def history():
        return jsonify(items=db.rows(db.get(), "SELECT delta, reason, ref, created_at FROM ledger WHERE user_id=? "
                                               "ORDER BY id DESC LIMIT 50", g.user["id"]))

    @app.get("/api/rewards")
    def rewards():
        return jsonify(items=db.rows(db.get(), "SELECT id,name,description,cost,stock FROM rewards WHERE active=1 ORDER BY cost"))

    @app.post("/api/rewards/<int:rid>/claim")
    @login_required
    def claim(rid):
        conn, uid = db.get(), g.user["id"]
        with db.tx(conn):
            r = db.row(conn, "SELECT * FROM rewards WHERE id=? AND active=1", rid)
            if not r:
                raise Fail("This reward is no longer available.", 404)
            if conn.execute("UPDATE rewards SET stock=stock-1 WHERE id=? AND stock>0", (rid,)).rowcount != 1:
                raise Fail("This reward is out of stock.", 409)
            if conn.execute("UPDATE users SET points_balance=points_balance-? WHERE id=? AND points_balance>=?",
                            (r["cost"], uid, r["cost"])).rowcount != 1:
                raise Fail("You don't have enough points for this reward.", 409)
            cur = conn.execute("INSERT INTO claims(user_id,reward_id,cost) VALUES (?,?,?)", (uid, rid, r["cost"]))
            conn.execute("INSERT INTO ledger(user_id,delta,reason,ref) VALUES (?,?,?,?)",
                         (uid, -r["cost"], f"Claimed {r['name']}", f"claim-{cur.lastrowid}"))
        return jsonify(claim_id=cur.lastrowid, user=public_user(db.row(conn, "SELECT * FROM users WHERE id=?", uid))), 201

    @app.get("/api/claims")
    @login_required
    def my_claims():
        return jsonify(items=db.rows(db.get(), "SELECT c.id,c.status,c.cost,c.created_at,r.name FROM claims c "
                                               "JOIN rewards r ON r.id=c.reward_id WHERE c.user_id=? ORDER BY c.id DESC", g.user["id"]))


# ---------- admin ----------
def register_admin(app):
    @app.get("/api/admin/stats")
    @admin_required
    def stats():
        c = db.get()
        series = {r["d"]: r["n"] for r in db.rows(c, "SELECT date(redeemed_at) d, COUNT(*) n FROM codes WHERE status='redeemed' "
                                                     "AND redeemed_at >= date('now','-13 days') GROUP BY d")}
        days = [r["d"] for r in db.rows(c, "WITH RECURSIVE x(i) AS (SELECT 0 UNION ALL SELECT i+1 FROM x WHERE i<13) "
                                           "SELECT date('now', '-'||(13-i)||' days') d FROM x")]
        total = db.scalar(c, "SELECT COUNT(*) FROM codes WHERE status!='voided'")
        used = db.scalar(c, "SELECT COUNT(*) FROM codes WHERE status='redeemed'")
        return jsonify(
            customers=db.scalar(c, "SELECT COUNT(*) FROM users WHERE role='customer'"),
            codes_total=total, codes_redeemed=used, redeem_rate=round(100 * used / total, 1) if total else 0,
            points_issued=db.scalar(c, "SELECT COALESCE(SUM(delta),0) FROM ledger WHERE delta>0"),
            points_spent=-db.scalar(c, "SELECT COALESCE(SUM(delta),0) FROM ledger WHERE delta<0"),
            pending_claims=db.scalar(c, "SELECT COUNT(*) FROM claims WHERE status='pending'"),
            failed_24h=db.scalar(c, "SELECT COUNT(*) FROM attempts WHERE outcome IN ('invalid','reused','voided') "
                                    "AND created_at >= datetime('now','-1 day')"),
            daily=[{"day": d, "count": series.get(d, 0)} for d in days],
            top_products=db.rows(c, "SELECT p.name, COUNT(*) n FROM codes c JOIN batches b ON b.id=c.batch_id "
                                    "JOIN products p ON p.id=b.product_id WHERE c.status='redeemed' GROUP BY p.id ORDER BY n DESC LIMIT 5"))

    @app.get("/api/admin/products")
    @admin_required
    def products():
        return jsonify(items=db.rows(db.get(), "SELECT * FROM products ORDER BY id"))

    @app.post("/api/admin/products")
    @admin_required
    def add_product():
        d = request.get_json(silent=True) or {}
        sku, name = re.sub(r"[^A-Z0-9]", "", str(d.get("sku", "")).upper())[:8], str(d.get("name", "")).strip()
        pts = _int(d.get("points"), 1, 100000, "Points per box must be between 1 and 100000.")
        if not sku or not name:
            raise Fail("Enter a SKU and a product name.")
        try:
            db.get().execute("INSERT INTO products(sku,name,points) VALUES (?,?,?)", (sku, name, pts))
        except sqlite3.IntegrityError:
            raise Fail("That SKU already exists.", 409)
        audit("product.add", f"{sku} {name} {pts}pts")
        return jsonify(ok=True), 201

    @app.post("/api/admin/batches")
    @admin_required
    def make_batch():
        conn, d = db.get(), request.get_json(silent=True) or {}
        qty = _int(d.get("quantity"), 1, config.MAX_BATCH_SIZE, f"Quantity must be between 1 and {config.MAX_BATCH_SIZE}.")
        p = db.row(conn, "SELECT * FROM products WHERE id=? AND active=1", d.get("product_id"))
        if not p:
            raise Fail("Choose a product.", 404)
        out = []
        with db.tx(conn):
            bid = conn.execute("INSERT INTO batches(product_id,quantity,note,created_by) VALUES (?,?,?,?)",
                               (p["id"], qty, str(d.get("note", ""))[:200], g.user["id"])).lastrowid
            for i in range(1, qty + 1):
                serial = f"{p['sku']}-{bid:04d}-{i:05d}"
                while True:
                    code = new_code()
                    try:
                        conn.execute("INSERT INTO codes(batch_id,serial,code_hash) VALUES (?,?,?)", (bid, serial, code_hash(code)))
                        break
                    except sqlite3.IntegrityError:
                        continue  # astronomically rare hash collision: draw a new code
                out.append({"serial": serial, "code": code})
        audit("batch.create", f"batch {bid}: {qty} x {p['sku']}")
        return jsonify(batch_id=bid, product=p["name"], codes=out), 201  # plain codes are returned ONCE, never stored

    @app.get("/api/admin/batches")
    @admin_required
    def batches():
        return jsonify(items=db.rows(db.get(), """
            SELECT b.id, b.quantity, b.status, b.note, b.created_at, p.name AS product, p.sku,
                   SUM(c.status='redeemed') AS redeemed, SUM(c.status='voided') AS voided
            FROM batches b JOIN products p ON p.id=b.product_id JOIN codes c ON c.batch_id=b.id
            GROUP BY b.id ORDER BY b.id DESC"""))

    @app.post("/api/admin/batches/<int:bid>/void")
    @admin_required
    def void_batch(bid):
        conn = db.get()
        with db.tx(conn):
            if not db.row(conn, "SELECT id FROM batches WHERE id=?", bid):
                raise Fail("Batch not found.", 404)
            conn.execute("UPDATE batches SET status='voided' WHERE id=?", (bid,))
            n = conn.execute("UPDATE codes SET status='voided' WHERE batch_id=? AND status='unused'", (bid,)).rowcount
            audit("batch.void", f"batch {bid}: {n} unused codes cancelled")
        return jsonify(cancelled=n)

    @app.get("/api/admin/codes")
    @admin_required
    def find_codes():
        q = re.sub(r"[^A-Za-z0-9-]", "", request.args.get("q", ""))
        return jsonify(items=db.rows(db.get(), "SELECT c.serial, c.status, c.redeemed_at, u.email AS redeemed_by FROM codes c "
                                               "LEFT JOIN users u ON u.id=c.redeemed_by WHERE c.serial LIKE ? ORDER BY c.id LIMIT 50",
                                     f"%{q.upper()}%"))

    @app.get("/api/admin/rewards")
    @admin_required
    def admin_rewards():
        return jsonify(items=db.rows(db.get(), "SELECT * FROM rewards ORDER BY id DESC"))

    @app.post("/api/admin/rewards")
    @admin_required
    def add_reward():
        d, name = request.get_json(silent=True) or {}, ""
        name = str(d.get("name", "")).strip()
        if not name:
            raise Fail("Enter a reward name.")
        cost = _int(d.get("cost"), 1, 10_000_000, "Cost must be a positive number of points.")
        stock = _int(d.get("stock"), 0, 1_000_000, "Stock must be 0 or more.")
        db.get().execute("INSERT INTO rewards(name,description,cost,stock) VALUES (?,?,?,?)",
                         (name, str(d.get("description", ""))[:300], cost, stock))
        audit("reward.add", f"{name} {cost}pts x{stock}")
        return jsonify(ok=True), 201

    @app.put("/api/admin/rewards/<int:rid>")
    @admin_required
    def edit_reward(rid):
        d, conn = request.get_json(silent=True) or {}, db.get()
        r = db.row(conn, "SELECT * FROM rewards WHERE id=?", rid)
        if not r:
            raise Fail("Reward not found.", 404)
        cost = _int(d.get("cost", r["cost"]), 1, 10_000_000, "Cost must be a positive number of points.")
        stock = _int(d.get("stock", r["stock"]), 0, 1_000_000, "Stock must be 0 or more.")
        conn.execute("UPDATE rewards SET name=?, description=?, cost=?, stock=?, active=? WHERE id=?",
                     (str(d.get("name", r["name"])).strip() or r["name"], str(d.get("description", r["description"]))[:300],
                      cost, stock, 1 if d.get("active", r["active"]) else 0, rid))
        audit("reward.edit", f"#{rid}")
        return jsonify(ok=True)

    @app.get("/api/admin/claims")
    @admin_required
    def admin_claims():
        return jsonify(items=db.rows(db.get(), "SELECT c.id,c.status,c.cost,c.created_at,r.name AS reward,u.email,u.name AS customer "
                                               "FROM claims c JOIN rewards r ON r.id=c.reward_id JOIN users u ON u.id=c.user_id "
                                               "ORDER BY (c.status='pending') DESC, c.id DESC LIMIT 100"))

    @app.post("/api/admin/claims/<int:cid>")
    @admin_required
    def update_claim(cid):
        status, conn = (request.get_json(silent=True) or {}).get("status"), db.get()
        if status not in ("fulfilled", "rejected"):
            raise Fail("Status must be fulfilled or rejected.")
        with db.tx(conn):
            cl = db.row(conn, "SELECT * FROM claims WHERE id=?", cid)
            if not cl:
                raise Fail("Claim not found.", 404)
            if cl["status"] != "pending":
                raise Fail("This claim has already been handled.", 409)
            conn.execute("UPDATE claims SET status=?, updated_at=datetime('now') WHERE id=?", (status, cid))
            if status == "rejected":  # refund points and return stock
                conn.execute("UPDATE users SET points_balance=points_balance+? WHERE id=?", (cl["cost"], cl["user_id"]))
                conn.execute("UPDATE rewards SET stock=stock+1 WHERE id=?", (cl["reward_id"],))
                conn.execute("INSERT INTO ledger(user_id,delta,reason,ref) VALUES (?,?,?,?)",
                             (cl["user_id"], cl["cost"], "Refund: claim rejected", f"claim-{cid}"))
            audit(f"claim.{status}", f"claim {cid}")
        return jsonify(ok=True)

    @app.get("/api/admin/customers")
    @admin_required
    def customers():
        return jsonify(items=db.rows(db.get(), """
            SELECT u.id,u.name,u.email,u.points_balance,u.lifetime_points,u.blocked,u.created_at,
                   (SELECT COUNT(*) FROM codes WHERE redeemed_by=u.id) AS boxes,
                   (SELECT COUNT(*) FROM attempts a WHERE a.user_id=u.id AND a.outcome IN ('invalid','reused','voided')) AS fails
            FROM users u WHERE u.role='customer' ORDER BY u.lifetime_points DESC LIMIT 200"""))

    @app.post("/api/admin/customers/<int:uid>/block")
    @admin_required
    def block(uid):
        blocked = 1 if (request.get_json(silent=True) or {}).get("blocked") else 0
        n = db.get().execute("UPDATE users SET blocked=? WHERE id=? AND role='customer'", (blocked, uid)).rowcount
        if not n:
            raise Fail("Customer not found.", 404)
        audit("customer.block" if blocked else "customer.unblock", f"user {uid}")
        return jsonify(ok=True)

    @app.get("/api/admin/alerts")
    @admin_required
    def alerts():
        c, bad = db.get(), "outcome IN ('invalid','reused','voided')"
        return jsonify(
            users=db.rows(c, f"SELECT u.id,u.email,u.blocked,COUNT(*) n,MAX(a.created_at) last FROM attempts a JOIN users u ON u.id=a.user_id "
                             f"WHERE a.{bad} AND a.created_at >= datetime('now','-1 day') GROUP BY u.id HAVING n>=3 ORDER BY n DESC"),
            ips=db.rows(c, f"SELECT ip,COUNT(*) n,COUNT(DISTINCT user_id) accounts FROM attempts WHERE {bad} "
                           f"AND created_at >= datetime('now','-1 day') GROUP BY ip HAVING n>=5 ORDER BY n DESC"),
            shared_codes=db.rows(c, "SELECT c.serial, COUNT(*) tries, COUNT(DISTINCT a.user_id) accounts FROM attempts a "
                                    "JOIN codes c ON c.code_hash=a.code_hash WHERE a.outcome='reused' GROUP BY c.id HAVING tries>=2 ORDER BY tries DESC LIMIT 20"),
            audit=db.rows(c, "SELECT a.action,a.detail,a.created_at,u.email actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id "
                             "ORDER BY a.id DESC LIMIT 30"))


def _int(v, lo, hi, msg):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise Fail(msg)
    if not lo <= n <= hi:
        raise Fail(msg)
    return n


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
