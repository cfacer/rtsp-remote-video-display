"""Shared utilities."""
import re
from urllib.parse import urlparse, urlunparse


def redact_url(url: str) -> str:
    """Return the URL with credentials replaced by '***' for safe logging/publishing."""
    try:
        p = urlparse(url)
        if p.username or p.password:
            host_part = p.hostname or ""
            if p.port:
                host_part += f":{p.port}"
            redacted = p._replace(netloc=f"***:***@{host_part}")
            return urlunparse(redacted)
    except Exception:
        pass
    return url


def redact_credentials(text: str) -> str:
    """Redact inline credentials from an arbitrary string (e.g. ffplay stderr, MQTT payloads)."""
    return re.sub(r"://[^:@/\s]+:[^@/\s]+@", "://***:***@", text)
