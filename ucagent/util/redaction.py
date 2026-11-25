"""Project configuration for operator display without exposing credential values."""

from collections.abc import Mapping
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REDACTED = "[redacted]"


def secret_field(name):
    """Recognize credential fields without hiding ordinary keys, paths or token limits."""
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name)).lower().replace("-", "_")
    parts = normalized.split("_")
    return (any(part in {"password", "passwd", "secret", "credential", "credentials"} for part in parts)
            or normalized in {"authorization", "proxy_authorization", "cookie", "set_cookie", "token"}
            or normalized.endswith(("_api_key", "_access_key", "_private_key", "_token"))
            or normalized in {"api_key", "access_key", "private_key"})


def redact_config(value, path=()):
    """Detach nested config data, masking explicit secret selections and credential URLs."""
    if any(secret_field(part) for part in path):
        return REDACTED if value not in (None, "") else value
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if isinstance(value, Mapping):
        return {key: redact_config(item, (*path, str(key))) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [redact_config(item, path) for item in value]
    if isinstance(value, str):
        name, separator, contents = value.partition("=")
        if separator and secret_field(name):
            return name + "=" + (REDACTED if contents else "")
        if "://" in value:
            try:
                url = urlsplit(value)
                authority = url.netloc
                if "@" in authority:
                    authority = REDACTED + "@" + authority.rsplit("@", 1)[1]
                pairs = parse_qsl(url.query, keep_blank_values=True)
                query = urlencode([(key, REDACTED if secret_field(key) else item) for key, item in pairs])
                if authority != url.netloc or any(secret_field(key) for key, _ in pairs):
                    return urlunsplit((url.scheme, authority, url.path, query, url.fragment))
            except ValueError:
                return REDACTED
    return value
