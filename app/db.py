import os
import sqlite3
from datetime import datetime, timezone
from flask import g, current_app

SCHEMA_VERSION = 1


def get_connection(db_path):
    """Create a configured SQLite connection with foreign keys and WAL mode."""
    dir_name = os.path.dirname(db_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    
    # Configure SQLite pragmas for performance and data safety
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def get_db():
    """Retrieve or create a database connection for the current Flask request context."""
    if "db" not in g:
        db_path = current_app.config.get("DB_PATH")
        g.db = get_connection(db_path)
    return g.db


def close_db(e=None):
    """Close the database connection at the end of the Flask request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def run_migrations(conn):
    """Run versioned schema migrations sequentially."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at_utc TEXT NOT NULL,
            description TEXT NOT NULL
        );
    """)
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT MAX(version) FROM schema_migrations")
    row = cur.fetchone()
    current_version = row[0] if row and row[0] is not None else 0

    if current_version < 1:
        _apply_migration_v1(conn)


def _apply_migration_v1(conn):
    """Migration V1: Core analytics tables, constraints, and indexes."""
    now_utc = datetime.now(timezone.utc).isoformat()
    
    with conn:
        # 1. Sites table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                allowed_origins TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        # 2. Events table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                site_id TEXT NOT NULL,
                visitor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                page_path TEXT NOT NULL,
                referrer_origin TEXT,
                received_at_utc TEXT NOT NULL,
                ip_pseudonym TEXT,
                schema_version INTEGER NOT NULL DEFAULT 1,
                is_bot INTEGER NOT NULL DEFAULT 0,
                bot_reason TEXT,
                campaign_source TEXT,
                campaign_medium TEXT,
                campaign_campaign TEXT,
                FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
            );
        """)

        # Indexes for query performance and deduplication
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_received_at ON events(received_at_utc);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_site_id ON events(site_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_visitor_id ON events(visitor_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ip_pseudonym ON events(ip_pseudonym);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_site_received ON events(site_id, received_at_utc);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_site_visitor ON events(site_id, visitor_id);")

        # 3. Visitor first seen table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visitor_first_seen (
                site_id TEXT NOT NULL,
                visitor_id TEXT NOT NULL,
                first_seen_at_utc TEXT NOT NULL,
                PRIMARY KEY (site_id, visitor_id),
                FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_first_seen_time ON visitor_first_seen(site_id, first_seen_at_utc);")

        # 4. Settings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
        """)

        # Default settings seed
        conn.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at_utc)
            VALUES 
                ('timezone', 'Asia/Kolkata', ?),
                ('retention_days', '90', ?);
        """, (now_utc, now_utc))

        # Default site seed: 'default'
        conn.execute("""
            INSERT OR IGNORE INTO sites (id, name, allowed_origins, created_at)
            VALUES ('default', 'Primary Website', '*', ?);
        """, (now_utc,))

        # Record migration
        conn.execute("""
            INSERT INTO schema_migrations (version, applied_at_utc, description)
            VALUES (1, ?, 'Initial schema with sites, events, visitor_first_seen, settings');
        """, (now_utc,))


def init_db(db_path):
    """Initialize database and execute all pending migrations."""
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
    finally:
        conn.close()
