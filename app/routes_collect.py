import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, make_response, current_app

from app.db import get_db
from app.security import (
    generate_visitor_id,
    sign_visitor_id,
    verify_visitor_id,
    get_client_ip,
    pseudonymize_ip,
    SimpleRateLimiter,
)
from app.bot_detector import classify_traffic

collect_bp = Blueprint("collect", __name__)

# Conservative rate limiter: max 120 events per minute per IP
event_rate_limiter = SimpleRateLimiter(max_requests=120, window_seconds=60)

ALLOWED_EVENT_TYPES = {"pageview", "custom"}
MAX_PAYLOAD_BYTES = 16384  # 16 KB


def is_origin_allowed(origin: str, allowed_origins_str: str) -> bool:
    """Validate if request origin is authorized by site configuration."""
    if not allowed_origins_str or allowed_origins_str.strip() == "*":
        return True
    if not origin:
        return True  # Direct same-origin or tool request
    allowed_list = [o.strip().rstrip("/") for o in allowed_origins_str.split(",") if o.strip()]
    norm_origin = origin.strip().rstrip("/")
    return norm_origin in allowed_list


def sanitize_path(path: str) -> str:
    """Strip query strings and hashes, bound length, and normalize page path."""
    if not path:
        return "/"
    # Remove query string or fragments if client passed them
    path = path.split("?")[0].split("#")[0].strip()
    if not path.startswith("/"):
        path = "/" + path
    return path[:500]


def sanitize_referrer(referrer: str) -> str:
    """Extract origin or clean host from referrer."""
    if not referrer:
        return ""
    try:
        parsed = urlparse(referrer.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"[:255]
        return referrer.strip()[:255]
    except Exception:
        return ""


@collect_bp.route("/collect", methods=["OPTIONS", "POST"])
def collect_event():
    # Handle CORS preflight
    origin = request.headers.get("Origin", "")
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Requested-With"
        return resp

    # 1. Enforce payload size constraint
    content_length = request.content_length or 0
    if content_length > MAX_PAYLOAD_BYTES:
        return jsonify({"error": "Payload exceeds 16KB limit"}), 413

    # Parse JSON payload
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    # 2. Extract and validate required fields
    event_id = str(data.get("event_id", "")).strip()
    if not event_id or len(event_id) > 64 or not re.match(r"^[a-zA-Z0-9_-]+$", event_id):
        return jsonify({"error": "Invalid event_id; alphanumeric UUID required"}), 400

    site_id = str(data.get("site_id", "default")).strip()
    if not site_id or len(site_id) > 64:
        site_id = "default"

    event_type = str(data.get("event_type", "pageview")).strip()
    if event_type not in ALLOWED_EVENT_TYPES:
        return jsonify({"error": f"Unsupported event_type '{event_type}'"}), 400

    raw_path = str(data.get("page_path", "/"))
    page_path = sanitize_path(raw_path)

    raw_referrer = str(data.get("referrer_origin", ""))
    referrer_origin = sanitize_referrer(raw_referrer)

    # Allowlisted campaign parameters
    campaign_source = str(data.get("utm_source", ""))[:100] or None
    campaign_medium = str(data.get("utm_medium", ""))[:100] or None
    campaign_campaign = str(data.get("utm_campaign", ""))[:100] or None

    # 3. Verify site and origin permissions
    db = get_db()
    site_row = db.execute("SELECT id, allowed_origins FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not site_row:
        return jsonify({"error": f"Site '{site_id}' not found"}), 404

    allowed_origins = site_row["allowed_origins"]
    req_origin = origin or request.headers.get("Referer", "")
    if req_origin:
        try:
            req_origin = urlparse(req_origin).origin
        except Exception:
            pass
        if not is_origin_allowed(req_origin, allowed_origins):
            return jsonify({"error": "Origin not allowed by site configuration"}), 403

    # 4. Extract IP securely and check rate limiting
    cfg = current_app.config["APP_CONFIG"]
    client_ip = get_client_ip(request, cfg.TRUSTED_PROXIES)
    
    if not event_rate_limiter.is_allowed(client_ip):
        return jsonify({"error": "Rate limit exceeded"}), 429

    ip_pseudo = pseudonymize_ip(client_ip, cfg.IP_HMAC_SECRET, cfg.IP_HMAC_KEY_VERSION)

    # 5. Visitor ID from signed cookie or generate new
    cookie_name = cfg.COOKIE_NAME
    raw_cookie_val = request.cookies.get(cookie_name)
    visitor_id = verify_visitor_id(raw_cookie_val, cfg.SECRET_KEY)
    cookie_to_set = False

    if not visitor_id:
        visitor_id = generate_visitor_id()
        cookie_to_set = True

    # 6. Authoritative server receipt timestamp (supports controllable test clock)
    override_now = current_app.config.get("OVERRIDE_NOW_UTC")
    if override_now:
        received_at_utc = override_now.isoformat()
    else:
        received_at_utc = datetime.now(timezone.utc).isoformat()

    # 7. Traffic classification / bot detection
    user_agent = request.headers.get("User-Agent", "")
    is_bot, bot_reason = classify_traffic(user_agent)
    is_bot_int = 1 if is_bot else 0

    # 8. Event-level Idempotency Check & Transactional Insertion
    try:
        # Check if event_id already exists in events
        existing = db.execute("SELECT id FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if existing:
            # Idempotent re-delivery success
            resp_body = {
                "status": "duplicate",
                "deduplicated": True,
                "event_id": event_id,
            }
            resp = make_response(jsonify(resp_body), 200)
            if origin:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp

        # Insert new event
        with db:
            db.execute("""
                INSERT INTO events (
                    event_id, site_id, visitor_id, event_type,
                    page_path, referrer_origin, received_at_utc,
                    ip_pseudonym, schema_version, is_bot, bot_reason,
                    campaign_source, campaign_medium, campaign_campaign
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, (
                event_id, site_id, visitor_id, event_type,
                page_path, referrer_origin, received_at_utc,
                ip_pseudo, is_bot_int, bot_reason,
                campaign_source, campaign_medium, campaign_campaign
            ))

            # Record visitor first seen transactionally (only on non-bot events or first valid event)
            if not is_bot:
                db.execute("""
                    INSERT OR IGNORE INTO visitor_first_seen (site_id, visitor_id, first_seen_at_utc)
                    VALUES (?, ?, ?)
                """, (site_id, visitor_id, received_at_utc))

    except Exception as e:
        # Check if error was a unique constraint race condition
        if "UNIQUE constraint failed: events.event_id" in str(e):
            return jsonify({"status": "duplicate", "deduplicated": True, "event_id": event_id}), 200
        return jsonify({"error": "Failed to record event"}), 500

    resp = make_response(jsonify({
        "status": "success",
        "event_id": event_id,
        "is_bot": is_bot,
    }), 200)

    # Always ensure valid signed cookie is present
    signed_cookie_val = sign_visitor_id(visitor_id, cfg.SECRET_KEY)
    is_secure = cfg.COOKIE_SECURE or request.is_secure or (request.headers.get("X-Forwarded-Proto") == "https")
    resp.set_cookie(
        key=cookie_name,
        value=signed_cookie_val,
        max_age=cfg.COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=is_secure,
        path="/",
    )

    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"

    return resp
