"""Atomic PPA report storage, integrity checks, and bounded cache retention."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import json
import os
import re
import tempfile
import threading

from .common import _sha256_file, _json_safe
from .models import _REPORT_ID_RE

_PPA_CACHE_LOCK = threading.Lock()


class ReportStore:
    """Persist immutable reports within one workspace and enforce retention."""

    def __init__(self, workspace: str, cache_limit: int) -> None:
        """Bind storage to the validated workspace and retention limit."""

        self.workspace = workspace
        self.cache_limit = cache_limit

    def _write_report(self, destination: Path, report: dict[str, Any]) -> None:
        """Atomically persist strict UTF-8 JSON without NaN or Infinity."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                json.dump(
                    _json_safe(report),
                    file_obj,
                    indent=2,
                    ensure_ascii=True,
                    allow_nan=False,
                )
                file_obj.write("\n")
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _cache_root(self, *, create: bool) -> Path:
        """Resolve the internal cache root without following workspace symlinks."""

        workspace = Path(self.workspace).resolve()
        state_root = workspace / ".ucagent"
        cache_root = state_root / "ppa_reports"
        for candidate in (state_root, cache_root):
            if candidate.is_symlink():
                raise ValueError(
                    f"internal PPA cache path must not be a symbolic link: {candidate}"
                )
        if create:
            cache_root.mkdir(parents=True, exist_ok=True)
        if cache_root.exists() and not cache_root.is_dir():
            raise ValueError(f"internal PPA cache path is not a directory: {cache_root}")
        return cache_root

    def _new_report_id(self) -> str:
        """Generate a unique report identifier not currently present in this workspace."""

        cache_root = self._cache_root(create=False)
        for _attempt in range(10):
            report_id = f"ppa-{uuid4().hex}"
            if not (cache_root / f"{report_id}.json").exists():
                return report_id
        raise RuntimeError("could not allocate a unique PPA report_id")

    def _load_cache_index(self, cache_root: Path) -> dict[str, Any]:
        """Load and validate the current canonical PPA cache index."""

        index_path = cache_root / "index.json"
        if not index_path.exists():
            return {"schema_version": "1.0", "reports": []}
        if index_path.is_symlink() or not index_path.is_file():
            raise ValueError("internal PPA cache index must be a regular file")
        try:
            with index_path.open("r", encoding="utf-8") as file_obj:
                index = json.load(file_obj)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"internal PPA cache index is unreadable: {exc}") from exc
        if not isinstance(index, dict) or index.get("schema_version") != "1.0":
            raise ValueError("internal PPA cache index schema_version must be 1.0")
        entries = index.get("reports")
        if not isinstance(entries, list):
            raise ValueError("internal PPA cache index reports must be a list")
        seen = set()
        for entry in entries:
            report_id = entry.get("report_id") if isinstance(entry, dict) else None
            if not isinstance(report_id, str) or not _REPORT_ID_RE.fullmatch(report_id):
                raise ValueError("internal PPA cache index contains an invalid report_id")
            report_sha256 = entry.get("sha256")
            if not isinstance(report_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", report_sha256
            ):
                raise ValueError(
                    "internal PPA cache index contains an invalid report SHA-256"
                )
            if report_id in seen:
                raise ValueError("internal PPA cache index contains duplicate report_id values")
            seen.add(report_id)
        return index

    def _available_report_ids(self, limit: int = 20) -> list[str]:
        """Return the newest bounded baseline candidates from the internal index."""

        cache_root = self._cache_root(create=False)
        if not cache_root.exists():
            return []
        index = self._load_cache_index(cache_root)
        return [
            entry["report_id"]
            for entry in reversed(index["reports"][-limit:])
        ]

    def _load_cached_report(self, report_id: str) -> dict[str, Any]:
        """Load one exact cached report by its validated immutable identifier."""

        if not _REPORT_ID_RE.fullmatch(report_id):
            raise ValueError("baseline_report_id has an invalid format")
        cache_root = self._cache_root(create=False)
        if not cache_root.exists():
            raise FileNotFoundError(f"cached PPA report was not found: {report_id}")
        index = self._load_cache_index(cache_root)
        matching_entries = [
            entry for entry in index["reports"] if entry["report_id"] == report_id
        ]
        if not matching_entries:
            raise FileNotFoundError(
                f"cached PPA report is not retained in the internal index: {report_id}"
            )
        report_path = cache_root / f"{report_id}.json"
        if report_path.is_symlink():
            raise ValueError(f"cached PPA report must not be a symbolic link: {report_id}")
        if not report_path.is_file():
            raise FileNotFoundError(f"cached PPA report was not found: {report_id}")
        if _sha256_file(report_path) != matching_entries[0]["sha256"]:
            raise ValueError(f"cached PPA report hash does not match: {report_id}")
        try:
            with report_path.open("r", encoding="utf-8") as file_obj:
                report = json.load(file_obj)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cached PPA report is unreadable: {report_id}: {exc}") from exc
        if not isinstance(report, dict) or report.get("report_id") != report_id:
            raise ValueError(f"cached PPA report identity does not match: {report_id}")
        return report

    def _store_cached_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Atomically cache one report, index it, and evict entries beyond the limit."""

        report_id = report.get("report_id")
        if not isinstance(report_id, str) or not _REPORT_ID_RE.fullmatch(report_id):
            raise ValueError("report has no valid report_id for caching")
        with _PPA_CACHE_LOCK:
            cache_root = self._cache_root(create=True)
            report_path = cache_root / f"{report_id}.json"
            if report_path.exists():
                raise ValueError(f"report_id collision in internal cache: {report_id}")
            index = self._load_cache_index(cache_root)
            entries = list(index["reports"])
            if any(entry["report_id"] == report_id for entry in entries):
                raise ValueError(f"report_id already exists in internal index: {report_id}")
            entries.append(
                {
                    "report_id": report_id,
                    "sha256": None,
                    "created_at": report.get("created_at"),
                    "top_module": report.get("provenance", {}).get("top_module"),
                    "status": report.get("status"),
                    "report_path": report.get("report_path"),
                }
            )
            pruned = entries[:-self.cache_limit]
            retained = entries[-self.cache_limit :]
            cache_info = {
                "stored": True,
                "limit": self.cache_limit,
                "retained_reports": len(retained),
                "relative_path": f".ucagent/ppa_reports/{report_id}.json",
            }
            report["cache"] = cache_info
            try:
                self._write_report(report_path, report)
                entries[-1]["sha256"] = _sha256_file(report_path)
                self._write_report(
                    cache_root / "index.json",
                    {
                        "schema_version": "1.0",
                        "cache_limit": self.cache_limit,
                        "reports": retained,
                    },
                )
            except Exception:
                try:
                    report_path.unlink()
                except FileNotFoundError:
                    pass
                raise
            for entry in pruned:
                old_report_id = entry["report_id"]
                if not _REPORT_ID_RE.fullmatch(old_report_id):
                    continue
                try:
                    (cache_root / f"{old_report_id}.json").unlink()
                except FileNotFoundError:
                    pass
            return cache_info
