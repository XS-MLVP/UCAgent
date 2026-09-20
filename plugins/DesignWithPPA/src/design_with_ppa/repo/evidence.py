"""Authenticated records for managed repository imports, measurements, and delivery."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets

from ..contracts import canonical_json_sha256, load_json
from .common import RepoPaths


def seal(paths: RepoPaths, payload: dict) -> dict:
    """Authenticate evidence produced by managed operations, not authored progress markers."""

    key_path = paths.state / "receipt.key"
    paths.state.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    signature = hmac.new(key_path.read_bytes(), canonical_json_sha256(payload).encode(), hashlib.sha256).hexdigest()
    return {"payload": payload, "signature": signature}


def unseal(paths: RepoPaths, artifact: Path) -> dict:
    """Reject forged or edited managed records before they can count as completed work."""

    record = load_json(artifact)
    payload = record.get("payload")
    key = paths.state / "receipt.key"
    if not isinstance(payload, dict) or not key.is_file():
        raise ValueError(f"Missing managed evidence: {artifact}")
    expected = hmac.new(key.read_bytes(), canonical_json_sha256(payload).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(record.get("signature", ""))):
        raise ValueError(f"Evidence changed outside managed operations: {artifact}")
    return payload
