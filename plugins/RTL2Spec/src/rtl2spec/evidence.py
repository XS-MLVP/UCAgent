"""Verify tool receipts against current source, elaborated RTL, and parsed ports."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

PORT_RE = re.compile(
    r"^\s*(input|output|inout)\s+(?:wire\s+|logic\s+|reg\s+)?"
    r"(?:\[\s*([^\]]+)\s*\]\s+)?([A-Za-z_][A-Za-z0-9_$]*)\s*,?\s*$"
)


def parse_ports(text: str, module: str) -> list[dict[str, object]]:
    """Parse firtool ANSI ports, including comments."""
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    match = re.search(rf"\bmodule\s+{re.escape(module)}\s*\((.*?)\s*\);", text, re.S)
    if not match:
        raise ValueError(f"module header not found: {module}")
    ports: list[dict[str, object]] = []
    for line in match.group(1).split(","):
        port_match = PORT_RE.match(line)
        if not port_match:
            if line.strip():
                raise ValueError(
                    f"unsupported port declaration in {module}: {line.strip()}"
                )
            continue
        direction, bit_range, name = port_match.groups()
        width = 1
        if bit_range is not None:
            bounds = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", bit_range)
            if bounds is None:
                raise ValueError(f"unresolved elaborated port width: {bit_range}")
            width = abs(int(bounds.group(1)) - int(bounds.group(2))) + 1
        ports.append(
            {
                "index": len(ports),
                "direction": direction,
                "name": name,
                "range": bit_range or "",
                "width": width,
            }
        )
    if len({port["name"] for port in ports}) != len(ports):
        raise ValueError(f"duplicate ports in {module}")
    return ports


def local_path(root: Path, path: str | Path) -> Path:
    """Resolve an artifact without permitting a workspace escape."""
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes workspace: {path}")
    return resolved


def read_json(path: Path) -> dict:
    """Read one JSON object, reporting its artifact on malformed input."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def digest(path: Path) -> str:
    """Hash an artifact using SHA-256."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def receipt(root: Path, value: dict, *, sign: bool = False) -> dict:
    """Sign tool-owned evidence, or verify it without creating missing keys."""
    key_file = local_path(root, ".ucagent/.rtl2spec_receipt_key")
    if sign and not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(secrets.token_bytes(32))
    try:
        key = key_file.read_bytes()
    except OSError as exc:
        raise ValueError(
            "tool receipt key missing; regenerate evidence with RTL2SpecCommand"
        ) from exc
    if len(key) != 32:
        raise ValueError(
            "invalid tool receipt key; restore the workspace runtime state"
        )
    payload = {k: v for k, v in value.items() if k != "signature"}
    signature = hmac.new(
        key,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    if not sign and not hmac.compare_digest(signature, str(value.get("signature", ""))):
        raise ValueError(
            "invalid tool receipt; regenerate the affected evidence with RTL2SpecCommand"
        )
    return {**payload, "signature": signature}


def source_state(root: Path) -> dict:
    """Identify a clean XiangShan checkout, including all initialized submodules."""
    source = local_path(root, "third_party/XiangShan")
    if not (source / ".git").exists():
        raise ValueError(
            "third_party/XiangShan: initialize the XiangShan Git checkout and submodules"
        )
    values = []
    for args in (
        ["rev-parse", "HEAD"],
        ["status", "--porcelain"],
        ["submodule", "status", "--recursive"],
    ):
        result = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise ValueError(
                f"third_party/XiangShan: git {' '.join(args)} failed: {result.stderr[-500:]}"
            )
        values.append(result.stdout.rstrip())
    commit, dirty, submodules = values
    if dirty or any(line[:1] in {"-", "+", "U"} for line in submodules.splitlines()):
        raise ValueError(
            "third_party/XiangShan: source is dirty or submodules do not match; restore the intended clean source before generating evidence"
        )
    return {"commit": commit, "submodules": submodules}


def validate_evidence(
    root: Path, module: str, version: str, config: str
) -> tuple[dict, list[dict]]:
    """Recompute source identity, RTL hash, and ports instead of trusting authored text."""
    folder = local_path(root, f"evidence/{module}/{version}")
    manifest = read_json(local_path(root, folder / "manifest.json"))
    receipt(root, manifest)
    if (
        manifest.get("schema_version"),
        manifest.get("module"),
        manifest.get("config"),
    ) != (2, module, config):
        raise ValueError(
            f"{folder}/manifest.json: expected schema 2, module {module}, config {config}"
        )
    state = source_state(root)
    if (
        manifest.get("source_state") != state
        or manifest.get("xiangshan_commit") != state["commit"]
    ):
        raise ValueError(
            f"{folder}/manifest.json: source identity changed; generate evidence for the current source in a new version"
        )
    rtl = local_path(root, folder / f"{module}.sv")
    if not rtl.is_file() or digest(rtl) != manifest.get("rtl_sha256"):
        raise ValueError(
            f"{rtl}: actual RTL is missing or its hash changed; regenerate evidence"
        )
    ports = parse_ports(rtl.read_text(encoding="utf-8"), module)
    if not ports:
        raise ValueError(f"{rtl}: no elaborated ports found")
    csv_path = local_path(root, folder / "ports.csv")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = [{key: str(value) for key, value in row.items()} for row in ports]
    counts = {
        direction: sum(row["direction"] == direction for row in ports)
        for direction in ("input", "output", "inout")
    }
    if (
        rows != expected
        or manifest.get("port_count") != len(ports)
        or manifest.get("port_counts") != counts
    ):
        raise ValueError(
            f"{csv_path}: ports differ from actual RTL; regenerate evidence"
        )
    if manifest.get("generation_status") not in {"success", "partial"}:
        raise ValueError(
            f"{folder}/manifest.json: RTL generation did not produce usable module evidence"
        )
    return manifest, ports
