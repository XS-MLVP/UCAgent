"""Shared diagnostics, hashing, and label helpers for design checkers."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Sequence
from ..contracts import (
    diagnostic,
    load_json,
    resolve_workspace_path,
    sha256_file,
)





def excluded_test_paths(workspace: Path, patterns: Sequence[str]) -> set[Path]:
    """Resolve workspace-relative exclude_test_globs into concrete file paths.

    Every consumer that binds or runs the shared test suite must apply the
    same exclusion, otherwise receipt hash sets and current hash sets cover
    different files and the binding can never match.
    """

    excluded: set[Path] = set()
    for pattern in patterns:
        pattern_path = Path(pattern)
        if pattern_path.is_absolute() or ".." in pattern_path.parts:
            raise ValueError("exclude_test_globs must remain workspace-relative")
        excluded.update(
            path.resolve()
            for path in workspace.glob(pattern)
            if path.is_file() and not path.is_symlink()
        )
    return excluded





_VERILOG_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


_PYTHON_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


_DESIGN_LABEL_IDENTIFIER_RE = re.compile(
    r"^(?:FG|FC|CK)-[A-Za-z0-9][A-Za-z0-9_.-]*$"
)


_PROCESS_ONLY_CK_TERM_RE = re.compile(
    r"(?:\b(?:pytest|tests?|testing|fixture|covgroup|coverage|mark_function|"
    r"seeds?|seeded|sidecars?|reports?|dashboards?|workflow)\b|"
    r"\btest_[A-Za-z0-9_]+)",
    re.IGNORECASE,
)


_PLACEHOLDER = 'assert False, "Not implemented"'


# This module lives at <plugin-src>/design_with_ppa/checkers/common.py; the
# plugin import root is the directory containing the ``design_with_ppa`` package.
_PLUGIN_PYTHON_IMPORT_ROOT = Path(__file__).resolve().parents[2]


_DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES = ("FG-PPA/", "FG-PPA-")


_TOFFEE_NODE_RE = re.compile(
    r"<TestReport\s+['\"](?P<node>[^'\"]+?)['\"]\s+when="
)




def _redact_backend_output(
    value: str,
    limit: int,
    sensitive_paths: tuple[Path, ...] = (),
) -> str:
    """Bound RTL validation output while hiding private implementation identities."""

    redacted = re.sub(r"picker", "RTL validation", value, flags=re.IGNORECASE)
    for pattern in (
        r"generated Python-DUT runtime",
        r"Python-DUT",
        r"generated-content",
        r"prepared-content",
        r"prepared RTL",
        r"RTL backend builder",
        r"RTL backend",
        r"backend package",
    ):
        redacted = re.sub(pattern, "RTL validation", redacted, flags=re.IGNORECASE)
    for path in sorted(sensitive_paths, key=lambda item: len(str(item)), reverse=True):
        for token in {str(path), path.as_posix(), path.name}:
            if token:
                redacted = redacted.replace(token, "<rtl-validation-input>")
    return redacted[-limit:]


def _bounded_checker_value(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded public projection of one inherited Checker result."""

    if depth >= 4:
        return "<nested diagnostic omitted>"
    if isinstance(value, str):
        return value[-4000:]
    if isinstance(value, dict):
        items = list(value.items())
        return {
            str(key): _bounded_checker_value(item, depth=depth + 1)
            for key, item in items[:20]
        } | ({"truncated": True} if len(items) > 20 else {})
    if isinstance(value, (list, tuple)):
        return [
            _bounded_checker_value(item, depth=depth + 1)
            for item in list(value)[:20]
        ] + (["<additional items omitted>"] if len(value) > 20 else [])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[-1000:]




def _failure_text(value: Any, fallback: str) -> str:
    """Extract one concise error sentence without discarding structured evidence."""

    if isinstance(value, str) and value.strip():
        return value.strip()[-2000:]
    if isinstance(value, dict):
        for key in ("error", "message", "details"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[-2000:]
            if isinstance(candidate, dict):
                nested = candidate.get("error")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()[-2000:]
    if isinstance(value, (list, tuple)):
        candidate = next(
            (item.strip() for item in value if isinstance(item, str) and item.strip()),
            None,
        )
        if candidate is not None:
            return candidate[-2000:]
    return fallback




def _is_batch_progress(value: Any) -> bool:
    """Distinguish an unfinished successful batch from a validation failure."""

    return (
        isinstance(value, dict)
        and "success" in value
        and "error" not in value
        and "error_code" not in value
        and "diagnostic" not in value
    )




def _actionable_checker_failure(
    value: Any,
    *,
    error_code: str,
    error: str,
    next_action: str,
    artifact: str,
    location: str | None = None,
    expected: Any,
    current_batch: list[str] | None = None,
) -> Any:
    """Normalize inherited failures while preserving explicit plugin diagnostics."""

    if _is_batch_progress(value):
        return value
    if isinstance(value, dict) and isinstance(value.get("diagnostic"), dict):
        result = dict(value)
        result["diagnostic"] = _actionable_checker_failure(
            value["diagnostic"],
            error_code=error_code,
            error=error,
            next_action=next_action,
            artifact=artifact,
            location=location,
            expected=expected,
            current_batch=current_batch,
        )
        return result
    if isinstance(value, dict) and all(
        isinstance(value.get(key), str) and value.get(key)
        for key in ("error_code", "error", "next_action")
    ):
        result = dict(value)
        result.setdefault("artifact", artifact)
        result.setdefault("location", location or artifact)
        result.setdefault("observed", {"reason": value["error"]})
        result.setdefault("expected", expected)
        if current_batch:
            result.setdefault(
                "current_batch",
                {
                    "items": current_batch[:20],
                    "count": len(current_batch),
                    "truncated": len(current_batch) > 20,
                },
            )
        return result
    observed: dict[str, Any] = {"checker_result": _bounded_checker_value(value)}
    if current_batch:
        observed["current_batch"] = current_batch[:20]
        observed["current_batch_count"] = len(current_batch)
        observed["current_batch_truncated"] = len(current_batch) > 20
    return diagnostic(
        error_code,
        _failure_text(value, error),
        next_action,
        artifact=artifact,
        location=location or artifact,
        observed=observed,
        expected=expected,
    )




def _inline_reason(reason: str, limit: int = 1200) -> str:
    """Return one tail-aligned inline excerpt of a bounded reason string.

    Exception chains carry their root cause at the end (traceback tail,
    embedded child output), so inline excerpts crop from the tail instead
    of dropping the decisive last lines.
    """

    if len(reason) <= limit:
        return reason
    return f"...{reason[-limit:]}"


def _exception_contract_diagnostic(
    *,
    error_code: str,
    error: str,
    exc: Exception,
    artifact: str,
    guide: str,
    expected: Any,
    retry_tool: str = "Check",
) -> dict[str, Any]:
    """Turn one exact contract exception into a location-oriented repair task."""

    location = artifact
    line = getattr(exc, "lineno", None)
    if isinstance(line, int) and line > 0:
        location = f"{artifact}:{line}"
    reason = _redact_backend_output(str(exc), 4000)
    return diagnostic(
        error_code,
        f"{error} First problem: {_inline_reason(reason)}",
        (
            f"Open {location} and use observed.reason to locate the first invalid "
            f"field, declaration, or reference. Correct that item to the canonical "
            f"contract in {guide}, preserve already valid entries, then call "
            f"{retry_tool} again."
        ),
        artifact=artifact,
        location=location,
        observed={"reason": reason},
        expected=expected,
    )




def _checkpoint_prefixes(value: Any) -> tuple[str, ...]:
    """Normalize configured checkpoint exclusions to stable non-empty prefixes."""

    values = [value] if isinstance(value, str) else value
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise ValueError("ignore_ck_prefix must be a string or list of non-empty strings")
    return tuple(dict.fromkeys(values))




def _functional_checkpoints(
    checkpoints: list[str],
    ignored_prefixes: tuple[str, ...],
) -> list[str]:
    """Return functional CK paths while excluding performance-analysis contracts."""

    return [
        checkpoint
        for checkpoint in checkpoints
        if not any(checkpoint.startswith(prefix) for prefix in ignored_prefixes)
    ]




def _contains_non_default_literal(
    node: ast.AST,
    assignments: dict[str, ast.AST],
    seen: set[str] | None = None,
) -> bool:
    """Return whether an expression contains statically verifiable active data."""

    if seen is None:
        seen = set()
    if isinstance(node, ast.Name) and node.id in assignments and node.id not in seen:
        return _contains_non_default_literal(
            assignments[node.id], assignments, {*seen, node.id}
        )
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False

    def active(item: Any) -> bool:
        """Classify zero-like literal containers as reset-neutral data."""

        if item is None or item is False:
            return False
        if isinstance(item, (int, float, complex)) and not isinstance(item, bool):
            return item != 0
        if isinstance(item, (str, bytes)):
            return bool(item)
        if isinstance(item, dict):
            return any(active(entry) for entry in item.values())
        if isinstance(item, (list, tuple, set, frozenset)):
            return any(active(entry) for entry in item)
        return True

    return active(value)




def _line_ranges_text(lines: set[int], limit: int = 20) -> str:
    """Return bounded, exact inclusive ranges for a set of source lines."""

    if not lines:
        return ""
    ordered = sorted(lines)
    ranges: list[str] = []
    start = ordered[0]
    end = start
    for line in ordered[1:]:
        if line == end + 1:
            end = line
            continue
        ranges.append(f"{start}-{end}")
        start = end = line
    ranges.append(f"{start}-{end}")
    displayed = ranges[:limit]
    suffix = f",... ({len(ranges)} ranges total)" if len(ranges) > limit else ""
    return ",".join(displayed) + suffix




def _cfg_dut(cfg: Any) -> str:
    """Return the resolved DUT identifier from the checker configuration."""

    values = cfg.get_value("_temp_cfg", {})
    dut = values.get("DUT") if isinstance(values, dict) else None
    if not isinstance(dut, str) or not dut.strip():
        raise ValueError("resolved configuration DUT must be a non-empty string")
    return dut




def _hash_rows(workspace: Path, paths: list[Path]) -> list[dict[str, str]]:
    """Build stable path/hash rows for files inside one workspace."""

    return [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(paths, key=lambda item: item.as_posix())
    ]




def _rows_sha256(rows: list[dict[str, str]]) -> str:
    """Hash one ordered file provenance list."""

    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()




def _validated_file_rows(
    workspace: Path,
    rows: Any,
    field: str,
) -> list[Path]:
    """Resolve and verify one persisted ordered file provenance list."""

    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{field} must be a non-empty file provenance list")
    files = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError(f"{field}[{index}] is invalid")
        path = resolve_workspace_path(workspace, row["path"], must_exist=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{field}[{index}] is not a regular file")
        if sha256_file(path) != row.get("sha256"):
            raise ValueError(f"{field}[{index}] hash changed: {row['path']}")
        files.append(path)
    if files != sorted(set(files), key=lambda item: item.as_posix()):
        raise ValueError(f"{field} must be unique and path-sorted")
    return files




def _validated_input_identity(workspace: Path, manifest_file: str) -> dict[str, Any]:
    """Load an input manifest and prove every README/Spec hash is still current."""

    manifest_path = resolve_workspace_path(workspace, manifest_file, must_exist=True)
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != "1.0":
        raise ValueError("design input manifest schema_version is invalid")
    readme = manifest.get("readme")
    specs = manifest.get("spec_files")
    if not isinstance(readme, dict) or not isinstance(specs, list) or not specs:
        raise ValueError("design input manifest source set is invalid")
    rows = [readme, *specs]
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("design input manifest contains an invalid source row")
        source = resolve_workspace_path(workspace, row["path"], must_exist=True)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"design input source is not a regular file: {row['path']}")
        if sha256_file(source) != row.get("sha256"):
            raise ValueError(f"design input source changed: {row['path']}")
    source_set_sha256 = _rows_sha256(rows)
    if source_set_sha256 != manifest.get("source_set_sha256"):
        raise ValueError("design input manifest aggregate hash is invalid")
    return {
        "manifest": manifest_path.relative_to(workspace).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "source_set_sha256": source_set_sha256,
        "sources": rows,
    }




def _contract_identity(workspace: Path, contract_files: list[str]) -> dict[str, Any]:
    """Return stable hashes for generated contracts consumed by a later gate."""

    paths = [
        resolve_workspace_path(workspace, value, must_exist=True)
        for value in contract_files
    ]
    rows = _hash_rows(workspace, paths)
    return {"files": rows, "sha256": _rows_sha256(rows)}




def _test_source_rows(
    workspace: Path,
    test_dir: Path,
) -> list[dict[str, str]]:
    """Hash stable handwritten test/API/reference sources."""

    sources = sorted(
        path.resolve()
        for path in test_dir.rglob("*.py")
        if (
            path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
        )
    )
    if not sources:
        raise ValueError("test/API/reference source set is empty")
    return _hash_rows(workspace, sources)
