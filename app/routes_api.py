from functools import wraps
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, session, current_app

from app.db import get_db
from app.analytics import (
    get_overview_metrics,
    get_daily_trends,
    get_top_pages,
    get_top_referrers,
    get_calendar_day_bounds,
    get_reporting_timezone,
)

api_bp = Blueprint("api", __name__)


def require_auth(f):
    """Decorator to enforce session authentication on protected API endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized. Please log in to access this endpoint."}), 401
        return f(*args, **kwargs)
    return decorated_function


def get_site_timezone(db, site_id: str) -> str:
    """Retrieve configured reporting timezone from settings or default."""
    row = db.execute("SELECT value FROM settings WHERE key = 'timezone'").fetchone()
    if row and row["value"]:
        return row["value"]
    cfg = current_app.config.get("APP_CONFIG")
    return cfg.DEFAULT_TIMEZONE if cfg else "Asia/Kolkata"


@api_bp.route("/health", methods=["GET"])
def health():
    """Basic health check endpoint exposing operational state without sensitive details."""
    db_connected = False
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT 1")
        if cur.fetchone()[0] == 1:
            db_connected = True
    except Exception:
        db_connected = False

    status = "ok" if db_connected else "degraded"
    status_code = 200 if db_connected else 503
    return jsonify({
        "status": status,
        "service": "Mini Analytics",
        "version": "1.0.0",
        "storage": "sqlite",
        "database_connected": db_connected,
    }), status_code


@api_bp.route("/api/overview", methods=["GET"])
@require_auth
def api_overview():
    """Retrieve aggregated overview metrics for Today, Current Week, and Current Month."""
    site_id = request.args.get("site_id", "default").strip()
    db = get_db()
    
    # Verify site exists
    site = db.execute("SELECT id, name FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not site:
        return jsonify({"error": f"Site '{site_id}' not found"}), 404

    tz_name = request.args.get("timezone", "").strip() or get_site_timezone(db, site_id)
    override_now = current_app.config.get("OVERRIDE_NOW_UTC")

    metrics = get_overview_metrics(db, site_id, tz_name, now_dt=override_now)
    metrics["site"] = {"id": site["id"], "name": site["name"]}
    return jsonify(metrics)


@api_bp.route("/api/trends", methods=["GET"])
@require_auth
def api_trends():
    """Retrieve daily time-series analytics for the last N calendar days."""
    site_id = request.args.get("site_id", "default").strip()
    try:
        days = min(max(int(request.args.get("days", 30)), 1), 90)
    except ValueError:
        days = 30

    db = get_db()
    tz_name = request.args.get("timezone", "").strip() or get_site_timezone(db, site_id)
    override_now = current_app.config.get("OVERRIDE_NOW_UTC")

    trends = get_daily_trends(db, site_id, tz_name, days=days, now_dt=override_now)
    return jsonify({
        "site_id": site_id,
        "timezone": tz_name,
        "days": days,
        "trends": trends,
    })


@api_bp.route("/api/pages", methods=["GET"])
@require_auth
def api_pages():
    """Retrieve top page paths within the selected time window."""
    site_id = request.args.get("site_id", "default").strip()
    range_param = request.args.get("range", "30d").lower()
    try:
        limit = min(max(int(request.args.get("limit", 15)), 1), 100)
    except ValueError:
        limit = 15

    db = get_db()
    tz_name = request.args.get("timezone", "").strip() or get_site_timezone(db, site_id)
    tz = get_reporting_timezone(tz_name)

    override_now = current_app.config.get("OVERRIDE_NOW_UTC")
    now_dt = override_now if override_now else datetime.now(timezone.utc)
    now_local = now_dt.astimezone(tz)

    if range_param == "today":
        start_utc, end_utc = get_calendar_day_bounds(now_local.date(), tz)
    elif range_param == "7d":
        start_date = now_local.date() - timedelta(days=6)
        start_utc, _ = get_calendar_day_bounds(start_date, tz)
        _, end_utc = get_calendar_day_bounds(now_local.date(), tz)
    else:  # Default 30d
        start_date = now_local.date() - timedelta(days=29)
        start_utc, _ = get_calendar_day_bounds(start_date, tz)
        _, end_utc = get_calendar_day_bounds(now_local.date(), tz)

    pages = get_top_pages(db, site_id, start_utc, end_utc, limit=limit)
    return jsonify({
        "site_id": site_id,
        "range": range_param,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "pages": pages,
    })


@api_bp.route("/api/referrers", methods=["GET"])
@require_auth
def api_referrers():
    """Retrieve top referrer origins within the selected time window."""
    site_id = request.args.get("site_id", "default").strip()
    range_param = request.args.get("range", "30d").lower()
    try:
        limit = min(max(int(request.args.get("limit", 15)), 1), 100)
    except ValueError:
        limit = 15

    db = get_db()
    tz_name = request.args.get("timezone", "").strip() or get_site_timezone(db, site_id)
    tz = get_reporting_timezone(tz_name)

    override_now = current_app.config.get("OVERRIDE_NOW_UTC")
    now_dt = override_now if override_now else datetime.now(timezone.utc)
    now_local = now_dt.astimezone(tz)

    if range_param == "today":
        start_utc, end_utc = get_calendar_day_bounds(now_local.date(), tz)
    elif range_param == "7d":
        start_date = now_local.date() - timedelta(days=6)
        start_utc, _ = get_calendar_day_bounds(start_date, tz)
        _, end_utc = get_calendar_day_bounds(now_local.date(), tz)
    else:
        start_date = now_local.date() - timedelta(days=29)
        start_utc, _ = get_calendar_day_bounds(start_date, tz)
        _, end_utc = get_calendar_day_bounds(now_local.date(), tz)

    referrers = get_top_referrers(db, site_id, start_utc, end_utc, limit=limit)
    return jsonify({
        "site_id": site_id,
        "range": range_param,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "referrers": referrers,
    })
