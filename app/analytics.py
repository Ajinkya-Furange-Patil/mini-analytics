import sqlite3
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Dict, Any, List, Optional, Tuple


def get_reporting_timezone(tz_name: str):
    """Return ZoneInfo for tz_name, fallback to Asia/Kolkata, or UTC offset if tzdata unavailable."""
    if not tz_name:
        tz_name = "Asia/Kolkata"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        try:
            return ZoneInfo("Asia/Kolkata")
        except Exception:
            # Fallback to standard +05:30 offset if tzdata package is missing on Windows
            return timezone(timedelta(hours=5, minutes=30))


def get_calendar_day_bounds(date_obj, tz: ZoneInfo) -> Tuple[str, str]:
    """
    Given a local date object, return half-open [start_utc_iso, end_utc_iso)
    corresponding to local midnight to next midnight.
    """
    start_local = datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0, tzinfo=tz)
    next_day = date_obj + timedelta(days=1)
    end_local = datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0, tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


def get_calendar_week_bounds(now_dt: datetime, tz: ZoneInfo) -> Tuple[str, str]:
    """
    Return half-open [start_utc_iso, end_utc_iso) for the Monday-to-Sunday
    calendar week containing now_dt in reporting timezone.
    """
    local_dt = now_dt.astimezone(tz)
    monday_date = local_dt.date() - timedelta(days=local_dt.weekday())
    start_local = datetime(monday_date.year, monday_date.month, monday_date.day, 0, 0, 0, tzinfo=tz)
    next_monday_date = monday_date + timedelta(days=7)
    end_local = datetime(next_monday_date.year, next_monday_date.month, next_monday_date.day, 0, 0, 0, tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


def get_calendar_month_bounds(now_dt: datetime, tz: ZoneInfo) -> Tuple[str, str]:
    """
    Return half-open [start_utc_iso, end_utc_iso) for the calendar month
    containing now_dt in reporting timezone.
    """
    local_dt = now_dt.astimezone(tz)
    start_local = datetime(local_dt.year, local_dt.month, 1, 0, 0, 0, tzinfo=tz)
    if local_dt.month == 12:
        end_local = datetime(local_dt.year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        end_local = datetime(local_dt.year, local_dt.month + 1, 1, 0, 0, 0, tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


def query_period_metrics(conn: sqlite3.Connection, site_id: str, start_utc: str, end_utc: str) -> Dict[str, Any]:
    """
    Compute exact unique browsers, unique IPs, page views, new and returning browsers
    for half-open interval [start_utc, end_utc).
    """
    # 1. Total page views
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) 
        FROM events 
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ? AND is_bot = 0
    """, (site_id, start_utc, end_utc))
    page_views = cur.fetchone()[0]

    # 2. Daily/Period unique browsers
    cur.execute("""
        SELECT COUNT(DISTINCT visitor_id) 
        FROM events 
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ? AND is_bot = 0
    """, (site_id, start_utc, end_utc))
    unique_browsers = cur.fetchone()[0]

    # 3. Unique IP addresses (pseudonymized, explicitly separate)
    cur.execute("""
        SELECT COUNT(DISTINCT ip_pseudonym) 
        FROM events 
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ? AND is_bot = 0 AND ip_pseudonym IS NOT NULL
    """, (site_id, start_utc, end_utc))
    unique_ips = cur.fetchone()[0]

    # 4. New browsers: first recorded event is within [start_utc, end_utc)
    cur.execute("""
        SELECT COUNT(DISTINCT v.visitor_id)
        FROM visitor_first_seen v
        JOIN events e ON v.site_id = e.site_id AND v.visitor_id = e.visitor_id
        WHERE e.site_id = ? AND e.received_at_utc >= ? AND e.received_at_utc < ? AND e.is_bot = 0
          AND v.first_seen_at_utc >= ? AND v.first_seen_at_utc < ?
    """, (site_id, start_utc, end_utc, start_utc, end_utc))
    new_browsers = cur.fetchone()[0]

    # 5. Returning browsers: at least one valid event before start_utc AND at least one event during period
    cur.execute("""
        SELECT COUNT(DISTINCT e.visitor_id)
        FROM events e
        JOIN visitor_first_seen v ON e.site_id = v.site_id AND e.visitor_id = v.visitor_id
        WHERE e.site_id = ? AND e.received_at_utc >= ? AND e.received_at_utc < ? AND e.is_bot = 0
          AND v.first_seen_at_utc < ?
    """, (site_id, start_utc, end_utc, start_utc))
    returning_browsers = cur.fetchone()[0]

    # 6. Bot events count
    cur.execute("""
        SELECT COUNT(*), COUNT(DISTINCT ip_pseudonym)
        FROM events
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ? AND is_bot = 1
    """, (site_id, start_utc, end_utc))
    bot_row = cur.fetchone()
    bot_page_views = bot_row[0] if bot_row else 0
    bot_unique_ips = bot_row[1] if bot_row else 0

    return {
        "page_views": page_views,
        "unique_browsers": unique_browsers,
        "unique_ips": unique_ips,
        "new_browsers": new_browsers,
        "returning_browsers": returning_browsers,
        "bot_page_views": bot_page_views,
        "bot_unique_ips": bot_unique_ips,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }


def get_overview_metrics(conn: sqlite3.Connection, site_id: str, tz_name: str, now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Retrieve comprehensive overview metrics for:
    - Today (Partial Period)
    - Current Week (Partial Period)
    - Current Month (Partial Period)
    - Overall active range metrics
    """
    tz = get_reporting_timezone(tz_name)
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    now_local = now_dt.astimezone(tz)
    today_date = now_local.date()

    # Calculate intervals
    today_start_utc, today_end_utc = get_calendar_day_bounds(today_date, tz)
    week_start_utc, week_end_utc = get_calendar_week_bounds(now_dt, tz)
    month_start_utc, month_end_utc = get_calendar_month_bounds(now_dt, tz)

    today_metrics = query_period_metrics(conn, site_id, today_start_utc, today_end_utc)
    week_metrics = query_period_metrics(conn, site_id, week_start_utc, week_end_utc)
    month_metrics = query_period_metrics(conn, site_id, month_start_utc, month_end_utc)

    # Last event received
    cur = conn.cursor()
    cur.execute("SELECT received_at_utc FROM events WHERE site_id = ? ORDER BY id DESC LIMIT 1", (site_id,))
    last_event_row = cur.fetchone()
    last_event_received = last_event_row[0] if last_event_row else None

    # Total all-time page views
    cur.execute("SELECT COUNT(*) FROM events WHERE site_id = ? AND is_bot = 0", (site_id,))
    total_page_views = cur.fetchone()[0]

    return {
        "timezone": tz_name,
        "server_time_utc": now_dt.isoformat(),
        "today": {
            **today_metrics,
            "period_label": f"Today ({today_date.isoformat()})",
            "is_partial": True,
            "partial_notice": "Partial period (active day in progress)",
        },
        "current_week": {
            **week_metrics,
            "period_label": "Current Week (Monday - Sunday)",
            "is_partial": True,
            "partial_notice": "Partial period (active week in progress)",
        },
        "current_month": {
            **month_metrics,
            "period_label": f"Current Month ({now_local.strftime('%B %Y')})",
            "is_partial": True,
            "partial_notice": "Partial period (active month in progress)",
        },
        "total_page_views": total_page_views,
        "last_event_received": last_event_received,
    }


def get_daily_trends(conn: sqlite3.Connection, site_id: str, tz_name: str, days: int = 30, now_dt: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Generate daily time-series data for the past N calendar days in the configured reporting timezone.
    Guarantees that daily unique counts are derived distinctly for each day.
    """
    tz = get_reporting_timezone(tz_name)
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    now_local = now_dt.astimezone(tz)
    today_date = now_local.date()

    # Pre-generate dates list from (today - (days - 1)) up to today
    date_list = [today_date - timedelta(days=i) for i in reversed(range(days))]

    first_day_start_utc, _ = get_calendar_day_bounds(date_list[0], tz)
    _, last_day_end_utc = get_calendar_day_bounds(date_list[-1], tz)

    # Fetch events within the entire 30-day window
    cur = conn.cursor()
    cur.execute("""
        SELECT received_at_utc, visitor_id, ip_pseudonym, is_bot
        FROM events
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ?
    """, (site_id, first_day_start_utc, last_day_end_utc))

    # Buckets for each day
    day_buckets = {
        d.isoformat(): {
            "page_views": 0,
            "visitor_ids": set(),
            "ip_pseudonyms": set(),
            "bot_views": 0,
        }
        for d in date_list
    }

    for row in cur.fetchall():
        rec_utc_str, visitor_id, ip_pseudo, is_bot = row[0], row[1], row[2], row[3]
        try:
            dt_utc = datetime.fromisoformat(rec_utc_str)
            dt_local = dt_utc.astimezone(tz)
            date_key = dt_local.date().isoformat()
            if date_key in day_buckets:
                if is_bot == 1:
                    day_buckets[date_key]["bot_views"] += 1
                else:
                    day_buckets[date_key]["page_views"] += 1
                    day_buckets[date_key]["visitor_ids"].add(visitor_id)
                    if ip_pseudo:
                        day_buckets[date_key]["ip_pseudonyms"].add(ip_pseudo)
        except Exception:
            continue

    trends = []
    for d in date_list:
        d_str = d.isoformat()
        bucket = day_buckets[d_str]
        is_today = (d == today_date)
        trends.append({
            "date": d_str,
            "page_views": bucket["page_views"],
            "unique_browsers": len(bucket["visitor_ids"]),
            "unique_ips": len(bucket["ip_pseudonyms"]),
            "bot_views": bucket["bot_views"],
            "is_partial": is_today,
            "period_label": f"{d_str} (Partial)" if is_today else d_str,
        })

    return trends


def get_top_pages(conn: sqlite3.Connection, site_id: str, start_utc: str, end_utc: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Retrieve top page paths with views and unique browser counts."""
    cur = conn.cursor()
    cur.execute("""
        SELECT page_path, COUNT(*) as views, COUNT(DISTINCT visitor_id) as uniques
        FROM events
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ? AND is_bot = 0
        GROUP BY page_path
        ORDER BY views DESC
        LIMIT ?
    """, (site_id, start_utc, end_utc, limit))
    return [
        {"path": row[0], "views": row[1], "unique_browsers": row[2]}
        for row in cur.fetchall()
    ]


def get_top_referrers(conn: sqlite3.Connection, site_id: str, start_utc: str, end_utc: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Retrieve top referrer origins with views and unique browser counts."""
    cur = conn.cursor()
    cur.execute("""
        SELECT referrer_origin, COUNT(*) as views, COUNT(DISTINCT visitor_id) as uniques
        FROM events
        WHERE site_id = ? AND received_at_utc >= ? AND received_at_utc < ? AND is_bot = 0 
          AND referrer_origin IS NOT NULL AND referrer_origin != ''
        GROUP BY referrer_origin
        ORDER BY views DESC
        LIMIT ?
    """, (site_id, start_utc, end_utc, limit))
    return [
        {"referrer": row[0], "views": row[1], "unique_browsers": row[2]}
        for row in cur.fetchall()
    ]


def purge_old_records(conn: sqlite3.Connection, retention_days: int) -> int:
    """
    Purge events older than retention_days based on received_at_utc.
    Returns number of purged events.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM events WHERE received_at_utc < ?", (cutoff,))
        purged_count = cur.rowcount
    return purged_count
