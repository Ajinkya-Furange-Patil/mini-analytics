import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def load_dotenv(dotenv_path=".env"):
    """Lightweight .env loader without requiring external packages."""
    if not os.path.exists(dotenv_path):
        return
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("\"'")
            if k and k not in os.environ:
                os.environ[k] = v


class Config:
    def __init__(self, dotenv_path=".env"):
        load_dotenv(dotenv_path)

        self.SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-replace-in-production-12345")
        self.IP_HMAC_SECRET = os.getenv("IP_HMAC_SECRET", "dev-ip-hmac-secret-replace-in-production-67890")
        self.IP_HMAC_KEY_VERSION = os.getenv("IP_HMAC_KEY_VERSION", "v1")

        self.ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
        self.ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

        self.DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mini_analytics.db"))
        
        default_tz = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
        try:
            ZoneInfo(default_tz)
            self.DEFAULT_TIMEZONE = default_tz
        except ZoneInfoNotFoundError:
            self.DEFAULT_TIMEZONE = "Asia/Kolkata"

        try:
            self.RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))
        except ValueError:
            self.RETENTION_DAYS = 90

        trusted_proxies_str = os.getenv("TRUSTED_PROXIES", "").strip()
        self.TRUSTED_PROXIES = [p.strip() for p in trusted_proxies_str.split(",") if p.strip()]

        self.COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
        self.COOKIE_NAME = "_ma_vid"
        self.COOKIE_MAX_AGE = int(os.getenv("COOKIE_MAX_AGE", str(365 * 24 * 3600)))  # 1 year default

        # Support Botkeep & standard port environment variables
        self.PORT = int(os.getenv("PORT", os.getenv("BOTKEEP_PORT", "5000")))
        self.HOST = os.getenv("HOST", "0.0.0.0")
