import hmac
import hashlib
import ipaddress
import secrets
import time
from typing import Optional, List


def generate_visitor_id() -> str:
    """Generate a cryptographically random, first-party visitor identifier."""
    return secrets.token_urlsafe(24)


def sign_visitor_id(visitor_id: str, secret: str) -> str:
    """Create a tamper-resistant signed visitor cookie value: <id>.<hmac>."""
    signature = hmac.new(secret.encode("utf-8"), visitor_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{visitor_id}.{signature}"


def verify_visitor_id(cookie_value: Optional[str], secret: str) -> Optional[str]:
    """
    Verify tamper-resistant visitor cookie.
    Returns the valid raw visitor ID if verified, or None if tampered/invalid.
    """
    if not cookie_value or "." not in cookie_value:
        return None
    parts = cookie_value.split(".", 1)
    if len(parts) != 2:
        return None
    raw_id, signature = parts
    expected_sig = hmac.new(secret.encode("utf-8"), raw_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if hmac.compare_digest(signature, expected_sig):
        return raw_id
    return None


def normalize_ip(ip_str: Optional[str]) -> str:
    """Normalize IPv4 or IPv6 address string, stripping whitespace and port if present."""
    if not ip_str:
        return "127.0.0.1"
    ip_str = ip_str.strip()
    if ":" in ip_str and not ip_str.startswith("[") and ip_str.count(":") == 1:
        # IPv4 with port, e.g., "192.168.1.1:8080"
        ip_str = ip_str.split(":", 1)[0]
    try:
        parsed = ipaddress.ip_address(ip_str)
        return parsed.exploded
    except ValueError:
        return ip_str.lower()


def pseudonymize_ip(ip_str: Optional[str], secret: str, key_version: str = "v1") -> str:
    """
    Keyed HMAC pseudonymization of normalized IP address.
    Raw IP is never stored in analytics event records.
    Key versioning allows tracking rotation boundaries.
    """
    norm = normalize_ip(ip_str)
    digest = hmac.new(secret.encode("utf-8"), norm.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{key_version}:{digest}"


def is_ip_trusted(remote_addr: str, trusted_list: List[str]) -> bool:
    """Check if remote_addr matches any entry in trusted_list (IP or CIDR network)."""
    if not remote_addr or not trusted_list:
        return False
    try:
        addr = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False

    for trusted in trusted_list:
        trusted = trusted.strip()
        if not trusted:
            continue
        if trusted == "*":
            return True
        try:
            if "/" in trusted:
                net = ipaddress.ip_network(trusted, strict=False)
                if addr in net:
                    return True
            else:
                if addr == ipaddress.ip_address(trusted):
                    return True
        except ValueError:
            continue
    return False


def get_client_ip(request, trusted_proxies: List[str]) -> str:
    """
    Extract client IP securely.
    Default to request.remote_addr (peer IP).
    Inspect X-Forwarded-For ONLY when request.remote_addr is confirmed trusted.
    Never blindly trust X-Forwarded-For.
    """
    remote_addr = request.remote_addr or "127.0.0.1"
    if trusted_proxies and is_ip_trusted(remote_addr, trusted_proxies):
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            # Client IP is the first entry in X-Forwarded-For
            forwarded_ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
            if forwarded_ips:
                return forwarded_ips[0]
    return remote_addr


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 200,000 iterations and salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200000)
    return f"pbkdf2_sha256$200000${salt}${dk.hex()}"


def check_password(password: str, password_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    try:
        parts = password_hash.split("$")
        if len(parts) != 4:
            return False
        algorithm, iterations_str, salt, target_hash = parts
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(dk.hex(), target_hash)
    except Exception:
        return False


class SimpleRateLimiter:
    """In-memory rate limiter for login brute force and event spam prevention."""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.records = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        # Clean expired
        history = [ts for ts in self.records.get(key, []) if now - ts < self.window_seconds]
        if len(history) >= self.max_requests:
            self.records[key] = history
            return False
        history.append(now)
        self.records[key] = history
        return True

    def reset(self, key: str):
        if key in self.records:
            del self.records[key]
