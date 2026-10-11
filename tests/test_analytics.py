import json
import uuid
import sqlite3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from app import create_app
from app.db import get_connection
from app.security import sign_visitor_id, pseudonymize_ip


def send_collect(client, event_id=None, site_id="default", path="/", referrer="", client_ip="203.0.113.10", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0", extra_headers=None, cookies=None):
    if not event_id:
        event_id = str(uuid.uuid4())
    headers = {
        "User-Agent": user_agent,
    }
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "event_id": event_id,
        "site_id": site_id,
        "page_path": path,
        "referrer_origin": referrer,
        "event_type": "pageview",
        "client_time": datetime.now(timezone.utc).isoformat(),
    }

    if cookies:
        for k, v in cookies.items():
            client.set_cookie(k, v)

    return client.post(
        "/collect",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
        environ_base={"REMOTE_ADDR": client_ip},
    )


# ------------------------------------------------------------------------------------
# 1. First valid visit creates one unique browser
# ------------------------------------------------------------------------------------
def test_01_first_valid_visit_creates_one_unique_browser(app, client, auth_client):
    res = send_collect(client, path="/home")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"

    # Verify cookie was issued
    cookie = client.get_cookie("_ma_vid")
    assert cookie is not None
    assert "." in cookie.value

    # Verify overview metrics
    overview_res = auth_client.get("/api/overview?site_id=default")
    assert overview_res.status_code == 200
    ov = overview_res.get_json()

    assert ov["today"]["page_views"] == 1
    assert ov["today"]["unique_browsers"] == 1
    assert ov["today"]["new_browsers"] == 1
    assert ov["today"]["returning_browsers"] == 0
    assert ov["today"]["is_partial"] is True


# ------------------------------------------------------------------------------------
# 2. Ten page refreshes create ten page views but still one unique browser
# ------------------------------------------------------------------------------------
def test_02_ten_page_refreshes_create_ten_page_views_one_unique_browser(app, client, auth_client):
    # Initial visit
    send_collect(client, path="/article")
    # 9 refreshes (same client/cookie, distinct event IDs)
    for _ in range(9):
        res = send_collect(client, path="/article")
        assert res.status_code == 200

    ov = auth_client.get("/api/overview?site_id=default").get_json()
    assert ov["today"]["page_views"] == 10
    assert ov["today"]["unique_browsers"] == 1
    assert ov["today"]["unique_ips"] == 1


# ------------------------------------------------------------------------------------
# 3. Re-delivering the same event ID creates no duplicate event
# ------------------------------------------------------------------------------------
def test_03_redelivering_same_event_id_creates_no_duplicate_event(app, client, auth_client):
    fixed_event_id = "duplicate-test-uuid-999"
    
    # First delivery
    res1 = send_collect(client, event_id=fixed_event_id, path="/checkout")
    assert res1.status_code == 200
    assert res1.get_json()["status"] == "success"

    # Redelivery of identical event_id
    res2 = send_collect(client, event_id=fixed_event_id, path="/checkout")
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["status"] == "duplicate"
    assert data2["deduplicated"] is True

    # Database check: must contain only 1 event
    conn = get_connection(app.config["DB_PATH"])
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events WHERE event_id = ?", (fixed_event_id,))
    count = cur.fetchone()[0]
    conn.close()

    assert count == 1
    ov = auth_client.get("/api/overview?site_id=default").get_json()
    assert ov["today"]["page_views"] == 1
    assert ov["today"]["unique_browsers"] == 1


# ------------------------------------------------------------------------------------
# 4. Two browsers behind one shared IP count as two unique browsers but one unique IP
# ------------------------------------------------------------------------------------
def test_04_two_browsers_behind_shared_ip_count_two_browsers_one_ip(app, auth_client):
    shared_ip = "198.51.100.50"
    
    # Browser 1
    client1 = app.test_client()
    send_collect(client1, client_ip=shared_ip)

    # Browser 2
    client2 = app.test_client()
    send_collect(client2, client_ip=shared_ip)

    ov = auth_client.get("/api/overview?site_id=default").get_json()
    assert ov["today"]["unique_browsers"] == 2
    assert ov["today"]["unique_ips"] == 1
    assert ov["today"]["page_views"] == 2


# ------------------------------------------------------------------------------------
# 5. One browser changing IP counts as one browser and multiple IPs
# ------------------------------------------------------------------------------------
def test_05_one_browser_changing_ip_counts_one_browser_multiple_ips(app, client, auth_client):
    # Visit from IP 1
    send_collect(client, client_ip="203.0.113.1")
    # Visit from IP 2 with same client cookie
    send_collect(client, client_ip="203.0.113.2")
    # Visit from IP 3 with same client cookie
    send_collect(client, client_ip="203.0.113.3")

    ov = auth_client.get("/api/overview?site_id=default").get_json()
    assert ov["today"]["unique_browsers"] == 1
    assert ov["today"]["unique_ips"] == 3
    assert ov["today"]["page_views"] == 3


# ------------------------------------------------------------------------------------
# 6. Different browsers with different cookies count separately
# ------------------------------------------------------------------------------------
def test_06_different_browsers_with_different_cookies_count_separately(app, auth_client):
    cfg = app.config["APP_CONFIG"]
    
    # Browser A
    client_a = app.test_client()
    vid_a = "browser_alpha_unique_id"
    signed_a = sign_visitor_id(vid_a, cfg.SECRET_KEY)
    client_a.set_cookie("_ma_vid", signed_a)
    send_collect(client_a, client_ip="192.0.2.1")

    # Browser B
    client_b = app.test_client()
    vid_b = "browser_beta_unique_id"
    signed_b = sign_visitor_id(vid_b, cfg.SECRET_KEY)
    client_b.set_cookie("_ma_vid", signed_b)
    send_collect(client_b, client_ip="192.0.2.2")

    ov = auth_client.get("/api/overview?site_id=default").get_json()
    assert ov["today"]["unique_browsers"] == 2
    assert ov["today"]["unique_ips"] == 2


# ------------------------------------------------------------------------------------
# 7. Deleting a cookie may create a new browser identity; document this limitation
# ------------------------------------------------------------------------------------
def test_07_deleting_cookie_creates_new_browser_identity(app, client, auth_client):
    # First visit establishes visitor identity A
    send_collect(client)
    cookie_a = client.get_cookie("_ma_vid").value

    # Simulate user clearing browser cookies
    client.delete_cookie("_ma_vid")

    # Next visit receives new visitor identity B
    send_collect(client)
    cookie_b = client.get_cookie("_ma_vid").value

    assert cookie_a != cookie_b
    ov = auth_client.get("/api/overview?site_id=default").get_json()
    # Documented behavior: cookie deletion creates 2 browser identities
    assert ov["today"]["unique_browsers"] == 2
    assert ov["today"]["page_views"] == 2


# ------------------------------------------------------------------------------------
# 8. Events around midnight fall into the correct reporting day
# ------------------------------------------------------------------------------------
def test_08_events_around_midnight_fall_into_correct_reporting_day(app, auth_client):
    tz = ZoneInfo("Asia/Kolkata")  # UTC+05:30
    
    # 2026-05-10 00:00:00 in Asia/Kolkata corresponds to 2026-05-09 18:30:00 UTC
    # 1 second before midnight: 2026-05-09 18:29:59 UTC -> belongs to 2026-05-09 local
    dt_before_midnight = datetime(2026, 5, 9, 18, 29, 59, tzinfo=timezone.utc)
    # 1 second after midnight: 2026-05-09 18:30:01 UTC -> belongs to 2026-05-10 local
    dt_after_midnight = datetime(2026, 5, 9, 18, 30, 1, tzinfo=timezone.utc)

    # Event 1 before midnight
    app.config["OVERRIDE_NOW_UTC"] = dt_before_midnight
    c1 = app.test_client()
    send_collect(c1, path="/page-day-9")

    # Event 2 after midnight
    app.config["OVERRIDE_NOW_UTC"] = dt_after_midnight
    c2 = app.test_client()
    send_collect(c2, path="/page-day-10")

    # When query for 2026-05-09 (at dt_before_midnight)
    app.config["OVERRIDE_NOW_UTC"] = dt_before_midnight
    ov9 = auth_client.get("/api/overview?site_id=default&timezone=Asia/Kolkata").get_json()
    assert ov9["today"]["page_views"] == 1
    assert "2026-05-09" in ov9["today"]["period_label"]

    # When query for 2026-05-10 (at dt_after_midnight)
    app.config["OVERRIDE_NOW_UTC"] = dt_after_midnight
    ov10 = auth_client.get("/api/overview?site_id=default&timezone=Asia/Kolkata").get_json()
    assert ov10["today"]["page_views"] == 1
    assert "2026-05-10" in ov10["today"]["period_label"]


# ------------------------------------------------------------------------------------
# 9. Events at Monday/Sunday and month boundaries are assigned correctly
# ------------------------------------------------------------------------------------
def test_09_events_at_week_and_month_boundaries_assigned_correctly(app, auth_client):
    tz = ZoneInfo("Asia/Kolkata")
    
    # 2026-05-31 is Sunday (last day of month and last day of week)
    # 2026-05-31 23:59:59 Kolkata = 2026-05-31 18:29:59 UTC
    dt_sunday_end_of_month = datetime(2026, 5, 31, 18, 29, 59, tzinfo=timezone.utc)
    
    # 2026-06-01 is Monday (new month and new week)
    # 2026-06-01 00:00:01 Kolkata = 2026-05-31 18:30:01 UTC
    dt_monday_new_month = datetime(2026, 5, 31, 18, 30, 1, tzinfo=timezone.utc)

    # Sunday event
    app.config["OVERRIDE_NOW_UTC"] = dt_sunday_end_of_month
    c_sun = app.test_client()
    send_collect(c_sun, path="/sunday-page")

    # Monday event
    app.config["OVERRIDE_NOW_UTC"] = dt_monday_new_month
    c_mon = app.test_client()
    send_collect(c_mon, path="/monday-page")

    # Overview on Sunday
    app.config["OVERRIDE_NOW_UTC"] = dt_sunday_end_of_month
    ov_sun = auth_client.get("/api/overview?site_id=default&timezone=Asia/Kolkata").get_json()
    assert ov_sun["today"]["page_views"] == 1
    assert ov_sun["current_week"]["page_views"] == 1
    assert ov_sun["current_month"]["page_views"] == 1

    # Overview on Monday
    app.config["OVERRIDE_NOW_UTC"] = dt_monday_new_month
    ov_mon = auth_client.get("/api/overview?site_id=default&timezone=Asia/Kolkata").get_json()
    assert ov_mon["today"]["page_views"] == 1
    assert ov_mon["current_week"]["page_views"] == 1
    assert ov_mon["current_month"]["page_views"] == 1


# ------------------------------------------------------------------------------------
# 10. Daily unique counts are not summed to produce weekly or monthly uniques
# ------------------------------------------------------------------------------------
def test_10_daily_unique_counts_not_summed_to_produce_weekly_or_monthly_uniques(app, auth_client):
    tz = ZoneInfo("Asia/Kolkata")
    
    # Fixed visitor cookie
    cfg = app.config["APP_CONFIG"]
    vid = "same_visitor_multiday"
    signed_vid = sign_visitor_id(vid, cfg.SECRET_KEY)

    client = app.test_client()
    client.set_cookie("_ma_vid", signed_vid)

    # Monday 2026-06-01 10:00 Kolkata = 04:30 UTC
    app.config["OVERRIDE_NOW_UTC"] = datetime(2026, 6, 1, 4, 30, 0, tzinfo=timezone.utc)
    send_collect(client, path="/mon")

    # Tuesday 2026-06-02 10:00 Kolkata = 04:30 UTC
    app.config["OVERRIDE_NOW_UTC"] = datetime(2026, 6, 2, 4, 30, 0, tzinfo=timezone.utc)
    send_collect(client, path="/tue")

    # Wednesday 2026-06-03 10:00 Kolkata = 04:30 UTC
    app.config["OVERRIDE_NOW_UTC"] = datetime(2026, 6, 3, 4, 30, 0, tzinfo=timezone.utc)
    send_collect(client, path="/wed")

    # Query overview on Wednesday
    ov = auth_client.get("/api/overview?site_id=default&timezone=Asia/Kolkata").get_json()
    
    # Daily unique for Wednesday is 1
    assert ov["today"]["unique_browsers"] == 1
    # Total page views in the week is 3
    assert ov["current_week"]["page_views"] == 3
    # CRITICAL: Weekly unique browser count is 1, NOT 1 + 1 + 1 = 3!
    assert ov["current_week"]["unique_browsers"] == 1
    assert ov["current_month"]["unique_browsers"] == 1


# ------------------------------------------------------------------------------------
# 11. Invalid timestamps cannot alter server-authoritative event times
# ------------------------------------------------------------------------------------
def test_11_invalid_timestamps_cannot_alter_server_authoritative_event_times(app, client):
    server_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
    app.config["OVERRIDE_NOW_UTC"] = server_time

    # Client passes spoofed ancient and future timestamps
    payload = {
        "event_id": str(uuid.uuid4()),
        "site_id": "default",
        "page_path": "/fake-time",
        "client_time": "1970-01-01T00:00:00Z",  # Bogus client time
        "event_type": "pageview",
    }
    client.post("/collect", data=json.dumps(payload), content_type="application/json")

    conn = get_connection(app.config["DB_PATH"])
    cur = conn.cursor()
    cur.execute("SELECT received_at_utc FROM events WHERE event_id = ?", (payload["event_id"],))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    # Must equal server authoritative time, not client time
    assert row[0] == server_time.isoformat()


# ------------------------------------------------------------------------------------
# 12. Spoofed forwarded IP headers are ignored unless the proxy is trusted
# ------------------------------------------------------------------------------------
def test_12_spoofed_forwarded_ip_headers_ignored_unless_proxy_is_trusted(app):
    cfg = app.config["APP_CONFIG"]
    
    # Case A: TRUSTED_PROXIES is empty -> X-Forwarded-For must be ignored
    cfg.TRUSTED_PROXIES = []
    c1 = app.test_client()
    send_collect(
        c1,
        client_ip="198.51.100.99",  # Direct peer IP
        extra_headers={"X-Forwarded-For": "203.0.113.88"},  # Spoofed
    )

    expected_peer_pseudo = pseudonymize_ip("198.51.100.99", cfg.IP_HMAC_SECRET, cfg.IP_HMAC_KEY_VERSION)
    conn = get_connection(app.config["DB_PATH"])
    cur = conn.cursor()
    cur.execute("SELECT ip_pseudonym FROM events ORDER BY id DESC LIMIT 1")
    stored_pseudo = cur.fetchone()[0]
    conn.close()

    assert stored_pseudo == expected_peer_pseudo

    # Case B: Peer is in TRUSTED_PROXIES -> X-Forwarded-For is trusted
    cfg.TRUSTED_PROXIES = ["198.51.100.99"]
    c2 = app.test_client()
    send_collect(
        c2,
        client_ip="198.51.100.99",  # Trusted proxy peer
        extra_headers={"X-Forwarded-For": "203.0.113.88, 10.0.0.1"},
    )

    expected_forwarded_pseudo = pseudonymize_ip("203.0.113.88", cfg.IP_HMAC_SECRET, cfg.IP_HMAC_KEY_VERSION)
    conn = get_connection(app.config["DB_PATH"])
    cur = conn.cursor()
    cur.execute("SELECT ip_pseudonym FROM events ORDER BY id DESC LIMIT 1")
    stored_forwarded_pseudo = cur.fetchone()[0]
    conn.close()

    assert stored_forwarded_pseudo == expected_forwarded_pseudo


# ------------------------------------------------------------------------------------
# 13. Invalid origins and malformed payloads are rejected
# ------------------------------------------------------------------------------------
def test_13_invalid_origins_and_malformed_payloads_rejected(app, client):
    # 1. Invalid payload: missing event_id
    res1 = client.post("/collect", data=json.dumps({"site_id": "default"}), content_type="application/json")
    assert res1.status_code == 400

    # 2. Unsupported event_type
    res2 = client.post("/collect", data=json.dumps({
        "event_id": str(uuid.uuid4()),
        "event_type": "malicious_exploit",
    }), content_type="application/json")
    assert res2.status_code == 400

    # 3. Payload size exceeding 16KB
    huge_data = {"event_id": str(uuid.uuid4()), "page_path": "/x" * 20000}
    res3 = client.post("/collect", data=json.dumps(huge_data), content_type="application/json")
    assert res3.status_code == 413

    # 4. Origin rejection
    # Create restricted site
    conn = get_connection(app.config["DB_PATH"])
    conn.execute("INSERT INTO sites (id, name, allowed_origins, created_at) VALUES ('restricted', 'Restricted', 'https://allowed.com', '2026-01-01T00:00:00Z')")
    conn.commit()
    conn.close()

    # Reject disallowed origin
    res4 = client.post("/collect", data=json.dumps({
        "event_id": str(uuid.uuid4()),
        "site_id": "restricted",
    }), content_type="application/json", headers={"Origin": "https://evil-attacker.com"})
    assert res4.status_code == 403

    # Accept allowed origin
    res5 = client.post("/collect", data=json.dumps({
        "event_id": str(uuid.uuid4()),
        "site_id": "restricted",
    }), content_type="application/json", headers={"Origin": "https://allowed.com"})
    assert res5.status_code == 200


# ------------------------------------------------------------------------------------
# 14. Concurrent duplicate event submissions do not create duplicates
# ------------------------------------------------------------------------------------
def test_14_concurrent_duplicate_event_submissions_do_not_create_duplicates(app):
    concurrent_event_id = f"concurrent-{uuid.uuid4()}"

    def send_one():
        c = app.test_client()
        return send_collect(c, event_id=concurrent_event_id, path="/concurrency-test")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(send_one) for _ in range(8)]
        results = [f.result() for f in futures]

    # Every request should succeed (either primary 200 or deduplicated 200)
    for res in results:
        assert res.status_code == 200

    # Exactly one record must be inserted in the database
    conn = get_connection(app.config["DB_PATH"])
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events WHERE event_id = ?", (concurrent_event_id,))
    count = cur.fetchone()[0]
    conn.close()

    assert count == 1


# ------------------------------------------------------------------------------------
# 15. Restarting the application preserves records when persistent storage is configured
# ------------------------------------------------------------------------------------
def test_15_restarting_application_preserves_records_with_persistent_storage(temp_db):
    test_config = {
        "TESTING": True,
        "DB_PATH": temp_db,
        "SECRET_KEY": "persistent-secret-key",
        "IP_HMAC_SECRET": "persistent-hmac-secret",
    }

    # App Instance 1: Insert events
    app1 = create_app(test_config)
    client1 = app1.test_client()
    send_collect(client1, path="/persistent-test")

    # "Restart": Tear down app1 and instantiate App Instance 2 pointing to same DB_PATH
    del app1
    app2 = create_app(test_config)
    
    with app2.test_client().session_transaction() as sess:
        sess["logged_in"] = True
        sess["csrf_token"] = "token"

    auth_client2 = app2.test_client()
    with auth_client2.session_transaction() as sess:
        sess["logged_in"] = True
    
    ov = auth_client2.get("/api/overview?site_id=default").get_json()
    assert ov["today"]["page_views"] == 1
    assert ov["today"]["unique_browsers"] == 1


# ------------------------------------------------------------------------------------
# 16. Unauthorized users cannot access dashboard APIs
# ------------------------------------------------------------------------------------
def test_16_unauthorized_users_cannot_access_dashboard_apis(client):
    endpoints = [
        "/api/overview",
        "/api/trends",
        "/api/pages",
        "/api/referrers",
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 401
        data = res.get_json()
        assert "error" in data


# ------------------------------------------------------------------------------------
# 17. Retention cleanup removes only eligible records
# ------------------------------------------------------------------------------------
def test_17_retention_cleanup_removes_only_eligible_records(app, auth_client):
    conn = get_connection(app.config["DB_PATH"])
    
    # 100 days ago (eligible for 90-day purge)
    old_time = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    # 10 days ago (must NOT be purged)
    recent_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    conn.execute("""
        INSERT INTO events (event_id, site_id, visitor_id, event_type, page_path, received_at_utc, schema_version)
        VALUES ('old-event-100d', 'default', 'vid-old', 'pageview', '/old', ?, 1)
    """, (old_time,))

    conn.execute("""
        INSERT INTO events (event_id, site_id, visitor_id, event_type, page_path, received_at_utc, schema_version)
        VALUES ('recent-event-10d', 'default', 'vid-recent', 'pageview', '/recent', ?, 1)
    """, (recent_time,))
    conn.commit()
    conn.close()

    # Trigger retention purge via admin endpoint (retention_days = 90)
    res = auth_client.post(
        "/admin/purge",
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["purged_records"] >= 1

    # Check remaining records in DB
    conn = get_connection(app.config["DB_PATH"])
    cur = conn.cursor()
    cur.execute("SELECT event_id FROM events WHERE event_id IN ('old-event-100d', 'recent-event-10d')")
    remaining_ids = [row[0] for row in cur.fetchall()]
    conn.close()

    assert "old-event-100d" not in remaining_ids
    assert "recent-event-10d" in remaining_ids


# ------------------------------------------------------------------------------------
# 18. Empty databases produce correct zero-value metrics
# ------------------------------------------------------------------------------------
def test_18_empty_databases_produce_correct_zero_value_metrics(auth_client):
    ov = auth_client.get("/api/overview?site_id=default").get_json()
    
    assert ov["today"]["page_views"] == 0
    assert ov["today"]["unique_browsers"] == 0
    assert ov["today"]["unique_ips"] == 0
    assert ov["today"]["new_browsers"] == 0
    assert ov["today"]["returning_browsers"] == 0
    assert ov["total_page_views"] == 0
    assert ov["last_event_received"] is None

    # Trends on empty DB
    trends_res = auth_client.get("/api/trends?site_id=default").get_json()
    assert "trends" in trends_res
    assert len(trends_res["trends"]) == 30
    assert all(t["page_views"] == 0 and t["unique_browsers"] == 0 for t in trends_res["trends"])

    # Pages & Referrers on empty DB
    pages_res = auth_client.get("/api/pages?site_id=default").get_json()
    assert pages_res["pages"] == []

    referrers_res = auth_client.get("/api/referrers?site_id=default").get_json()
    assert referrers_res["referrers"] == []


# ------------------------------------------------------------------------------------
# Extra: Bot detection flags automated crawlers without inflating human metrics
# ------------------------------------------------------------------------------------
def test_bot_detection_flags_crawlers_without_inflating_human_metrics(client, auth_client):
    # Googlebot visit
    send_collect(
        client,
        path="/google-crawl",
        user_agent="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    )

    ov = auth_client.get("/api/overview?site_id=default").get_json()
    # Human counts must remain 0
    assert ov["today"]["page_views"] == 0
    assert ov["today"]["unique_browsers"] == 0
    # Bot count recorded
    assert ov["today"]["bot_page_views"] == 1
