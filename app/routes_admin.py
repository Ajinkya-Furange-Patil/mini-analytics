import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    session,
    jsonify,
    current_app,
)

from app.db import get_db
from app.security import SimpleRateLimiter, get_client_ip
from app.analytics import purge_old_records

admin_bp = Blueprint("admin", __name__)

# Brute force login limiter: 5 attempts per 5 minutes per IP
login_limiter = SimpleRateLimiter(max_requests=5, window_seconds=300)


def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)
    return session["csrf_token"]


def verify_csrf(req) -> bool:
    token = req.headers.get("X-CSRF-Token") or req.form.get("csrf_token")
    expected = session.get("csrf_token")
    return bool(token and expected and secrets.compare_digest(token, expected))


@admin_bp.route("/", methods=["GET"])
def index():
    """Root route: renders analytics dashboard if authenticated, else redirects to login."""
    if not session.get("logged_in"):
        return redirect(url_for("admin.login_page"))
    
    db = get_db()
    sites = db.execute("SELECT id, name FROM sites ORDER BY created_at ASC").fetchall()
    
    # Get current settings
    settings_rows = db.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in settings_rows}

    csrf_token = generate_csrf_token()

    return render_template(
        "dashboard.html",
        sites=sites,
        settings=settings,
        csrf_token=csrf_token,
        username=session.get("username", "admin"),
    )


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login_page():
    """Dashboard admin login with brute-force rate limiting and credential verification."""
    cfg = current_app.config["APP_CONFIG"]
    client_ip = get_client_ip(request, cfg.TRUSTED_PROXIES)

    if request.method == "GET":
        if session.get("logged_in"):
            return redirect(url_for("admin.index"))
        return render_template("login.html", error=None)

    # POST - Handle login submission
    if not login_limiter.is_allowed(client_ip):
        return render_template(
            "login.html",
            error="Too many failed login attempts. Please wait 5 minutes before trying again."
        ), 429

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    expected_user = cfg.ADMIN_USERNAME
    expected_pass = cfg.ADMIN_PASSWORD

    # Constant time comparison to prevent timing attacks
    user_ok = secrets.compare_digest(username, expected_user)
    pass_ok = secrets.compare_digest(password, expected_pass)

    if user_ok and pass_ok:
        login_limiter.reset(client_ip)
        session.clear()
        session["logged_in"] = True
        session["username"] = username
        generate_csrf_token()
        return redirect(url_for("admin.index"))

    return render_template("login.html", error="Invalid username or password."), 401


@admin_bp.route("/admin/logout", methods=["POST", "GET"])
def logout():
    """Log out admin session."""
    session.clear()
    return redirect(url_for("admin.login_page"))


@admin_bp.route("/admin/settings", methods=["POST"])
def update_settings():
    """Update analytics settings (timezone, data retention, site origins)."""
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not verify_csrf(request):
        return jsonify({"error": "Invalid or missing CSRF token"}), 403

    db = get_db()
    now_utc = datetime.now(timezone.utc).isoformat()

    # Timezone update
    new_tz = request.form.get("timezone", "").strip()
    if new_tz:
        try:
            ZoneInfo(new_tz)
            db.execute("""
                INSERT INTO settings (key, value, updated_at_utc) VALUES ('timezone', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at_utc = excluded.updated_at_utc
            """, (new_tz, now_utc))
        except (ZoneInfoNotFoundError, ValueError):
            return jsonify({"error": f"Invalid timezone '{new_tz}'"}), 400

    # Retention days update
    retention_days_str = request.form.get("retention_days", "").strip()
    if retention_days_str:
        try:
            days = int(retention_days_str)
            if days < 1 or days > 3650:
                return jsonify({"error": "Retention period must be between 1 and 3650 days"}), 400
            db.execute("""
                INSERT INTO settings (key, value, updated_at_utc) VALUES ('retention_days', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at_utc = excluded.updated_at_utc
            """, (str(days), now_utc))
        except ValueError:
            return jsonify({"error": "Invalid retention days value"}), 400

    # Site origins update (if provided)
    site_id = request.form.get("site_id", "").strip()
    allowed_origins = request.form.get("allowed_origins", "").strip()
    if site_id and allowed_origins:
        db.execute("UPDATE sites SET allowed_origins = ? WHERE id = ?", (allowed_origins, site_id))

    db.commit()
    return jsonify({"status": "success", "message": "Settings updated successfully."})


@admin_bp.route("/admin/purge", methods=["POST"])
def purge_data():
    """Manually invoke data retention cleanup to purge events older than retention period."""
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not verify_csrf(request):
        return jsonify({"error": "Invalid or missing CSRF token"}), 403

    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = 'retention_days'").fetchone()
    retention_days = int(row["value"]) if row and row["value"] else 90

    purged = purge_old_records(db, retention_days)
    return jsonify({
        "status": "success",
        "purged_records": purged,
        "retention_days": retention_days,
        "message": f"Successfully purged {purged} event records older than {retention_days} days.",
    })


@admin_bp.route("/demo", methods=["GET"])
def demo_page():
    """Interactive demo test page showcasing the client tracker snippet."""
    return render_template("demo.html")
