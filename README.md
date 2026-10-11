# Mini Analytics — Accurate, Self-Hosted Website Visitor Analytics

Mini Analytics is a lightweight, privacy-respecting, production-conscious website analytics engine built with Python, Flask, SQLite, and vanilla JavaScript. It is designed to run efficiently on low-resource cloud servers (such as a Botkeep shared instance with 1.5 shared vCPU, 2 GB RAM, and 2 GB disk) without Redis, PostgreSQL, external SaaS dependencies, or complex client frameworks.

---

## 1. Non-Negotiable Counting Principles

Mini Analytics avoids inaccurate claims of identifying physical human beings. Instead, it measures verifiable technical identifiers and explicitly reports two distinct metrics:

### A. Unique Browsers
- **Identity Mechanism**: Identified via a cryptographically random, server-side generated visitor ID (`secrets.token_urlsafe(24)`).
- **Integrity**: Preserved in a tamper-resistant cookie formatted as `<visitor_id>.<hmac_signature>` using the server's `SECRET_KEY`.
- **Cookie Security**: Configured with `HttpOnly`, `SameSite=Lax`, `Secure` (when HTTPS is enabled), and a configurable retention period (`COOKIE_MAX_AGE`, default 1 year).
- **IP Protection**: Raw IP addresses are **never** used as permanent visitor identities.

### B. Unique IP Addresses
- **Identity Mechanism**: Calculated as an explicitly separated, distinct metric for normalized IP addresses observed in a reporting period.
- **Privacy & Pseudonymization**: IPs are **never** stored in raw form in event records. Instead, they are pseudonymized using server-held keyed HMAC-SHA256 with a key version prefix (`v1:<digest>`).
- **Context & Caveat**: Shared Wi-Fi, NAT (Carrier-Grade NAT), mobile networks, VPNs, and dynamic IP pools mean IP counts differ substantially from browser or human counts. Rotating the server HMAC secret invalidates deduplication history unless migrated.
- **Clear Demarcation**: The dashboard clearly distinguishes between unique browsers and unique IPs; they are **never** combined into a single metric.

---

## 2. Exact Metric Definitions

- **Storage Timezone**: All event records store UTC ISO 8601 timestamps (`received_at_utc`).
- **Display Timezone**: Configurable per deployment (default: `Asia/Kolkata`). Calendar days, calendar weeks (Monday–Sunday), and calendar months are partitioned in local time, converted to half-open UTC intervals `[start_utc, end_utc)`.
- **Daily Unique Browsers**: `COUNT(DISTINCT visitor_id)` for valid events in the local calendar day.
- **Weekly Unique Browsers**: `COUNT(DISTINCT visitor_id)` across the current Monday-to-Sunday calendar week.
- **Monthly Unique Browsers**: `COUNT(DISTINCT visitor_id)` across the current calendar month.
- **Non-Additive Guarantee**: Weekly uniques are **never** calculated by adding daily uniques. Monthly uniques are **never** calculated by adding weekly totals. Visitors who visit on multiple days are counted exactly once for the multi-day period.
- **Partial Period Demarcation**: The current day, current week, and current month are actively in progress and explicitly labelled as **Partial Period**.
- **First-Time vs Returning**:
  - *New Browser*: A visitor ID whose first valid event (`visitor_first_seen.first_seen_at_utc`) falls within the reporting period.
  - *Returning Browser*: A visitor ID with at least one valid event recorded prior to the reporting period and at least one event during the period.

---

## 3. Database & Concurrency Architecture

Mini Analytics uses SQLite configured for high reliability and concurrency:
- **Foreign Keys**: Enabled (`PRAGMA foreign_keys = ON;`)
- **Write-Ahead Logging**: Enabled (`PRAGMA journal_mode = WAL;`) for concurrent read access without blocking writes.
- **Busy Timeout**: Configured to `5000ms` (`PRAGMA busy_timeout = 5000;`) to handle burst concurrency.
- **Parameterized Queries**: 100% of SQL queries use parameter placeholders to eliminate SQL injection vulnerabilities.
- **Transactional Consistency**: Event insertion and `visitor_first_seen` recording execute within single atomic transactions.
- **Event-Level Idempotency**: `events.event_id` is constrained `UNIQUE`. Re-delivering or retrying an event produces an HTTP 200 `{ "status": "duplicate", "deduplicated": true }` response without creating duplicates.
- **Performance Indexes**:
  - `idx_events_received_at` on `events(received_at_utc)`
  - `idx_events_site_id` on `events(site_id)`
  - `idx_events_visitor_id` on `events(visitor_id)`
  - `idx_events_ip_pseudonym` on `events(ip_pseudonym)`
  - `idx_events_site_received` on `events(site_id, received_at_utc)`
  - `idx_first_seen_time` on `visitor_first_seen(site_id, first_seen_at_utc)`

---

## 4. Bot & Invalid Traffic Classification

Mini Analytics includes a documented regex and token classification layer:
- **Known Bots**: Identifies search engine crawlers (Googlebot, Bingbot, Baiduspider, Yandex), SEO scrapers (Ahrefs, Semrush), social media link preview bots (Facebook, Twitter, Slack, Discord), and automated HTTP clients (curl, wget, python-requests, Puppeteer, HeadlessChrome).
- **Separation**: Bot events are recorded with `is_bot = 1` and `bot_reason = ...`, allowing audit logs while keeping human analytics cards completely clean.
- **Refreshes**: Legitimate rapid browser refreshes are **not** treated as bot traffic.
- **Honest Disclosure**: User-Agent matching catches standard bots, but stealth or targeted scrapers cannot be detected solely via headers.

---

## 5. Security & Privacy

- **No Invasive Fingerprinting**: No canvas fingerprinting, WebGL hashes, font enumeration, or audio API profiling.
- **Trusted Reverse Proxy Configuration**: `X-Forwarded-For` is **only** inspected if the request peer IP matches `TRUSTED_PROXIES`. Blind trust of forwarded headers is prevented.
- **CSRF & Brute Force Protection**: Dashboard authentication features an in-memory rate limiter locking out repeat failures, and state-changing forms require valid CSRF tokens.
- **Strict Headers**: Includes Content-Security-Policy (CSP), `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy`.
- **GDPR Notice**: HMAC-pseudonymized IP addresses remain pseudonymized data under certain regulatory definitions. A data purge procedure (`POST /admin/purge` and automatic retention limit) ensures compliance.

---

## 6. Local Setup and Quickstart

### Prerequisites
- Python 3.10+ (Standard Library contains `sqlite3`, `hashlib`, `hmac`, `zoneinfo`)
- Virtual environment (recommended)

### Installation
```bash
# 1. Clone repository and navigate to folder
cd /path/to/visitorCounter

# 2. Create virtual environment & activate
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Install minimal requirements
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your secrets and credentials
```

### Running Locally
```bash
python run.py
```
The application will launch on `http://127.0.0.1:5000`.

- **Dashboard**: Open `http://127.0.0.1:5000/` (Sign in with credentials configured in `.env`, default: `admin` / `admin123`).
- **Live Demo Site**: Open `http://127.0.0.1:5000/demo` to simulate live tracking, refreshes, and cookie resets.
- **Health Check**: Open `http://127.0.0.1:5000/health`.

---

## 7. Embedding Tracker Snippet

Embed the lightweight tracking snippet before the closing `</body>` tag on your website:

```html
<script 
    src="https://your-mini-analytics-domain.com/tracker.js" 
    data-site-id="default" 
    data-endpoint="/collect" 
    defer>
</script>
```

---

## 8. Botkeep Cloud Deployment

Botkeep (`botkeep.cloud`) is a developer cloud host for bots, web applications, and background services.

### Resource Allocation
- 1.5 shared vCPU
- 2 GB shared RAM
- 2 GB shared storage

### Environment Variables
Configure the following in the Botkeep project dashboard under **Environment**:
| Variable | Value / Description |
|---|---|
| `PORT` | Set automatically by Botkeep (or default 5000/8000) |
| `SECRET_KEY` | 64-char random hex string (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `IP_HMAC_SECRET` | 64-char random hex string for keyed HMAC IP pseudonymization |
| `IP_HMAC_KEY_VERSION` | `v1` |
| `ADMIN_USERNAME` | Strong admin username |
| `ADMIN_PASSWORD` | Strong admin password |
| `DB_PATH` | `/app/data/mini_analytics.db` (or mounted persistent volume) |
| `DEFAULT_TIMEZONE` | `Asia/Kolkata` (or your preferred IANA timezone) |
| `RETENTION_DAYS` | `90` |
| `TRUSTED_PROXIES` | Botkeep edge IP or CIDR (if behind Botkeep reverse proxy) |
| `COOKIE_SECURE` | `true` (when HTTPS domain is active) |

### Filesystem Persistence Warning
> [!WARNING]
> Botkeep containers can have ephemeral root filesystems across redeployments or rebuilds. To avoid losing analytics records, mount a persistent storage directory or volume and point `DB_PATH` to it (e.g., `/data/mini_analytics.db`).

### Backup and Restore Procedure
**Backup:**
Using SQLite's online safe backup API or command line:
```bash
sqlite3 data/mini_analytics.db ".backup 'data/backup_$(date +%Y%m%d).db'"
```
**Restore:**
```bash
cp data/backup_20261012.db data/mini_analytics.db
```

---

## 9. Automated Test Suite

Run the full automated test suite covering all 18 mandatory verification scenarios:

```bash
python -m pytest tests -v
```

### Verified Test Matrix:
- `test_01_first_valid_visit_creates_one_unique_browser` — PASSED
- `test_02_ten_page_refreshes_create_ten_page_views_one_unique_browser` — PASSED
- `test_03_redelivering_same_event_id_creates_no_duplicate_event` — PASSED
- `test_04_two_browsers_behind_shared_ip_count_two_browsers_one_ip` — PASSED
- `test_05_one_browser_changing_ip_counts_one_browser_multiple_ips` — PASSED
- `test_06_different_browsers_with_different_cookies_count_separately` — PASSED
- `test_07_deleting_cookie_creates_new_browser_identity` — PASSED
- `test_08_events_around_midnight_fall_into_correct_reporting_day` — PASSED
- `test_09_events_at_week_and_month_boundaries_assigned_correctly` — PASSED
- `test_10_daily_unique_counts_not_summed_to_produce_weekly_or_monthly_uniques` — PASSED
- `test_11_invalid_timestamps_cannot_alter_server_authoritative_event_times` — PASSED
- `test_12_spoofed_forwarded_ip_headers_ignored_unless_proxy_is_trusted` — PASSED
- `test_13_invalid_origins_and_malformed_payloads_rejected` — PASSED
- `test_14_concurrent_duplicate_event_submissions_do_not_create_duplicates` — PASSED
- `test_15_restarting_application_preserves_records_with_persistent_storage` — PASSED
- `test_16_unauthorized_users_cannot_access_dashboard_apis` — PASSED
- `test_17_retention_cleanup_removes_only_eligible_records` — PASSED
- `test_18_empty_databases_produce_correct_zero_value_metrics` — PASSED
- `test_bot_detection_flags_crawlers_without_inflating_human_metrics` — PASSED
- `test_admin_login_success_and_logout` — PASSED
- `test_admin_login_invalid_credentials` — PASSED
- `test_tracker_js_served` — PASSED
- `test_health_endpoint` — PASSED

**Result:** 23 passed in ~1.4s.

---

## 10. Manual Verification Checklist

1. **Clean Installation**: Run `python -m pytest` -> ensure all 23 tests pass.
2. **App Startup**: Run `python run.py`.
3. **Health Check**: Visit `http://localhost:5000/health` -> verify JSON response.
4. **Dashboard Sign-In**: Visit `http://localhost:5000/` -> redirected to login; enter `admin` / `admin123`.
5. **Interactive Demo**: Navigate to `http://localhost:5000/demo`. Click "Simulate Page Refresh" multiple times.
6. **Dashboard Verification**: Return to `http://localhost:5000/`. Notice:
   - Page Views increased with every refresh.
   - Unique Browsers remained 1.
   - Unique IP addresses remained 1.
7. **Cookie Deletion Test**: In `/demo`, click "Clear Visitor Cookie". Refresh the page. Return to dashboard:
   - Unique Browsers increments to 2.
   - Unique IP addresses remains 1.
8. **Settings & Purge**: Update retention period or timezone and verify instant update without server restart.

---

## 11. Known Limitations

- **Browser Storage Restrictions**: When users use aggressive content blockers, clear cookies upon browser close, or use Private/Incognito windows, each new session generates a new browser identifier.
- **Multiple Devices / Browsers**: The same person browsing on their mobile phone and laptop is counted as two distinct unique browser identities.
- **Network Aggregation**: Multiple distinct people sharing a university, office, or mobile carrier network share IP pseudonyms.
- **Stealth Bot Limits**: Standard bots announcing crawler User-Agents are classified and segregated; custom stealth bots masquerading with real browser headers cannot be detected without invasive fingerprinting (which Mini Analytics deliberately avoids).
