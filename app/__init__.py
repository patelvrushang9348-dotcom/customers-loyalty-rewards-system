import os

from flask import Flask, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from . import db as dbmod
from .config import Config, validate_secrets


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(Config().as_dict())
    if overrides:
        app.config.update(overrides)
    validate_secrets(app.config)

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app.config.get("COOKIE_SECURE", False),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if app.config.get("NUM_PROXIES", 0) > 0:
        n = app.config["NUM_PROXIES"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n)

    dbmod.init_db(app.config["DATABASE_PATH"])
    _bootstrap_admin(app)
    app.teardown_appcontext(dbmod.close_db)

    from .routes_admin import bp as admin_bp
    from .routes_customer import bp as customer_bp
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:")
        if resp.mimetype == "application/json":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def customer_page():
        return send_from_directory(app.static_folder, "customer.html")

    @app.get("/admin")
    def admin_page():
        return send_from_directory(app.static_folder, "admin.html")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "Not found."}), 404

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify({"error": "Request too large."}), 413

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify({"error": "Something went wrong on our side."}), 500

    return app


def _bootstrap_admin(app: Flask):
    """Create the first admin from env vars if no admin exists yet."""
    user, pw = app.config.get("ADMIN_USERNAME"), app.config.get("ADMIN_PASSWORD")
    if not user or not pw:
        return
    conn = dbmod.connect(app.config["DATABASE_PATH"])
    try:
        if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            if pw.startswith("change-me") and not app.config.get("TESTING"):
                raise RuntimeError("ADMIN_PASSWORD is still the placeholder; set a real password in .env")
            conn.execute("INSERT INTO admins (username, password_hash, created_at) VALUES (?,?,?)",
                         (user, generate_password_hash(pw), dbmod.now_str()))
    finally:
        conn.close()
