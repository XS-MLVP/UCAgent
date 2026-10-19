#!/usr/bin/env python3
"""Deterministic ACT4 asset consistency checks for the non-AI checker layer.

The module deliberately has no skill or UCAgent dependency. It is used by the
standalone skill entry point and the UCAgent checker adapter.

The checker has two layers:

* generic asset checks (existence, encoding, parser/schema, hashes and text
  contracts) driven by an optional manifest; and
* ACT4 checks that connect a suite's Sheet, normative mapping, coverage SVH,
  generator, aggregate includes and CTP entry.

Static parsing is intentionally conservative.  A warning is emitted whenever
the source is valid but a relationship cannot be proven without preprocessing
or executing a generator.
"""

from __future__ import annotations

import argparse
import ast
import csv
import glob
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - reported as a finding at runtime
    yaml = None  # type: ignore[assignment]


SCHEMA_VERSION = 2
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
CANONICAL_SHEET_COLUMNS = {
    "source_items",
    "coverpoint",
    "normative_rules",
    "disposition",
}
WAIVER_PREFIXES = ("NOT COVERED", "OUT-OF-SCOPE", "OUT OF SCOPE")
ASSET_KINDS = {
    "source",
    "external_source",
    "tracked_generated",
    "ignored_validation",
    "vector_generated",
}

# Asset kinds are defined by act4-asset-planner.  A checker profile selects the
# relationships that can be proven for that kind without applying the source
# contract to generated, external, or validation-only files.
CHECKER_PROFILES: dict[str, dict[str, Any]] = {
    "coverage": {
        "asset_kinds": None,
        "norm": False,
        "mapping": False,
        "sheet": False,
        "coverage": True,
        "suite_group": False,
        "generator": False,
        "ctp": False,
    },
    "all": {
        "asset_kinds": None,
        "norm": True,
        "mapping": True,
        "sheet": True,
        "coverage": True,
        "suite_group": False,
        "generator": True,
        "ctp": True,
    },
    "source": {
        "asset_kinds": {"source"},
        "norm": True,
        "mapping": True,
        "sheet": True,
        "coverage": True,
        "suite_group": False,
        "generator": True,
        "ctp": True,
    },
    "external_source": {
        "asset_kinds": {"external_source"},
        "norm": False,
        "mapping": False,
        "sheet": True,
        "coverage": False,
        "suite_group": False,
        "generator": False,
        "ctp": False,
    },
    "tracked_generated": {
        "asset_kinds": {"tracked_generated"},
        "norm": False,
        "mapping": False,
        "sheet": False,
        "coverage": True,
        "suite_group": False,
        "generator": False,
        "ctp": False,
    },
    "ignored_validation": {
        "asset_kinds": {"ignored_validation"},
        "norm": False,
        "mapping": False,
        "sheet": False,
        "coverage": False,
        "suite_group": False,
        "generator": False,
        "ctp": False,
    },
    "vector_generated": {
        "asset_kinds": {"vector_generated"},
        "norm": False,
        "mapping": False,
        "sheet": False,
        "coverage": True,
        # Vector generators may use an aggregate or a differently named
        # covergroup, so exact <suite>_cg ownership is a source-only rule.
        "suite_group": False,
        "generator": False,
        "ctp": False,
    },
}
DEFAULT_ASSET_KIND_BY_COLLECTION = {
    "source_assets": "source",
    "tracked_generated_assets": "tracked_generated",
    "validation_assets": "ignored_validation",
}


class AssetCheckError(Exception):
    """Configuration or input error that prevents a report from being built."""


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _listify(value) if str(item).strip()]


def _resolve_input(root: Path, value: str | Path) -> Path:
    """Resolve an explicit input from root, while accepting cwd-relative CLI paths.

    UCAgent passes paths relative to its workspace; a human invoking the CLI
    commonly passes paths relative to the repository checkout.  Prefer the
    ACT4 root when that candidate exists, then fall back to the process cwd.
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    root_candidate = (root / path).resolve()
    cwd_candidate = (Path.cwd() / path).resolve()
    if root_candidate.exists():
        return root_candidate
    if cwd_candidate.exists():
        return cwd_candidate
    return root_candidate


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _add(
    findings: list[dict[str, Any]],
    severity: str,
    check: str,
    message: str,
    **details: Any,
) -> None:
    findings.append({"severity": severity, "check": check, "message": message, **details})
    #追加severity，check，message


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AssetCheckError(f"{path}: not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise AssetCheckError(f"{path}: cannot read: {exc}") from exc


def _load_structured(path: Path) -> Any:
    text = _read_text(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text)
        if suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise AssetCheckError("PyYAML is required to parse YAML assets")
            return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError if yaml else Exception) as exc:  # type: ignore[misc]
        raise AssetCheckError(f"{path}: invalid {suffix.lstrip('.') or 'structured'} data: {exc}") from exc
    raise AssetCheckError(f"{path}: unsupported structured format")
#按后缀读取 JSON/YAML


def _load_manifest(path: Path) -> dict[str, Any]:
    data = _load_structured(path)
    if not isinstance(data, dict):
        raise AssetCheckError(f"asset manifest must be an object: {path}")
    return data


def _load_generator_target_scope(
    root: Path,
    contract: str | Path | None,
    require_scoped: bool,
    findings: list[dict[str, Any]],
) -> tuple[set[str], set[str], set[str]]:
    """Return targets that are required, blocked, or experimental-only."""
    if not contract:
        if require_scoped:
            _add(
                findings,
                "error",
                "generator_scope_contract",
                "scoped generator targets require a VM/resource contract",
            )
        return set(), set(), set()

    path = _resolve_input(root, contract)
    if not path.is_file():
        _add(
            findings,
            "error" if require_scoped else "warning",
            "generator_scope_contract",
            f"generator scope contract is missing: {path}",
            file=str(path),
        )
        return set(), set(), set()
    try:
        data = _load_structured(path)
    except AssetCheckError as exc:
        _add(findings, "error", "generator_scope_contract", str(exc), file=str(path))
        return set(), set(), set()
    if not isinstance(data, dict):
        _add(findings, "error", "generator_scope_contract", "generator scope contract must be a mapping", file=str(path))
        return set(), set(), set()
    if data.get("decision") == "no_vm":
        return set(), set(), set()

    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        profiles = list(profiles.values())
    if not isinstance(profiles, list):
        _add(findings, "error", "generator_scope_contract", "generator scope contract must contain a profiles list", file=str(path))
        return set(), set(), set()

    allowed_targets: set[str] = set()
    blocked_targets: set[str] = set()
    experimental_targets: set[str] = set()
    profile_ids: dict[str, str] = {}
    profile_targets: dict[str, set[str]] = {}
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("profile_id", "")).strip()
        decision = str(profile.get("decision", "")).strip()
        targets = set(_string_list(profile.get("coverage_targets")))
        if profile_id:
            profile_ids[profile_id] = decision
            profile_targets[profile_id] = targets
        if decision in {"allowed", "allowed_with_limitations"}:
            allowed_targets.update(targets)
        elif decision == "blocked":
            blocked_targets.update(targets)
        elif decision == "experimental":
            experimental_targets.update(targets)
        elif require_scoped:
            _add(
                findings,
                "error",
                "generator_profile_decision",
                f"profile[{index}] must declare decision allowed, allowed_with_limitations, blocked, or experimental",
                file=str(path),
                profile=profile_id or index,
            )

    fully_blocked = blocked_targets - allowed_targets
    experimental_only = experimental_targets - allowed_targets - blocked_targets
    dispositions = data.get("coverage_disposition")
    if require_scoped and not isinstance(dispositions, list):
        _add(findings, "error", "generator_coverage_disposition", "scoped contract must contain coverage_disposition", file=str(path))
        return allowed_targets, fully_blocked, experimental_only

    seen: set[str] = set()
    for index, item in enumerate(dispositions or []):
        if not isinstance(item, dict):
            _add(findings, "error", "generator_coverage_disposition", f"coverage_disposition[{index}] must be a mapping", file=str(path))
            continue
        target = str(item.get("target", "")).strip()
        status = str(item.get("planned_status", "")).strip()
        generated_profiles = set(_string_list(item.get("generated_profiles")))
        blocked_profiles = set(_string_list(item.get("blocked_profiles")))
        blocked_subcases = item.get("blocked_subcases")
        if not target or target in seen:
            _add(findings, "error", "generator_coverage_disposition", "coverage disposition targets must be non-empty and unique", file=str(path), target=target)
            continue
        seen.add(target)
        expected = "partial" if target in allowed_targets and target in blocked_targets else "required" if target in allowed_targets else "blocked" if target in blocked_targets else ""
        if status != expected:
            _add(findings, "error", "generator_coverage_disposition", f"{target} planned_status {status!r} does not match profile decisions ({expected!r})", file=str(path), target=target)
        unknown_profiles = (generated_profiles | blocked_profiles) - set(profile_ids)
        if unknown_profiles:
            _add(findings, "error", "generator_coverage_disposition", f"{target} references unknown profiles: {sorted(unknown_profiles)}", file=str(path), target=target)
        if any(profile_ids.get(name) not in {"allowed", "allowed_with_limitations"} for name in generated_profiles):
            _add(findings, "error", "generator_coverage_disposition", f"{target} generated_profiles contains a non-generatable profile", file=str(path), target=target)
        if any(profile_ids.get(name) != "blocked" for name in blocked_profiles):
            _add(findings, "error", "generator_coverage_disposition", f"{target} blocked_profiles contains a non-blocked profile", file=str(path), target=target)
        unrelated_profiles = {
            name
            for name in generated_profiles | blocked_profiles
            if target not in profile_targets.get(name, set())
        }
        if unrelated_profiles:
            _add(findings, "error", "generator_coverage_disposition", f"{target} references profiles that do not cover it: {sorted(unrelated_profiles)}", file=str(path), target=target)
        if require_scoped and status in {"partial", "blocked"} and (
            not isinstance(blocked_subcases, list) or not blocked_subcases
        ):
            _add(findings, "error", "generator_coverage_disposition", f"{target} must describe non-empty blocked_subcases for {status} status", file=str(path), target=target)
        if require_scoped and status == "required" and blocked_subcases:
            _add(findings, "error", "generator_coverage_disposition", f"{target} cannot declare blocked_subcases with required status", file=str(path), target=target)

    classified = allowed_targets | blocked_targets
    if require_scoped and seen != classified:
        _add(
            findings,
            "error",
            "generator_coverage_disposition",
            "coverage_disposition must classify every target present in profiles exactly once",
            file=str(path),
            missing=sorted(classified - seen),
            extra=sorted(seen - classified),
        )
    return allowed_targets, fully_blocked, experimental_only


def _load_suite_record(path: Path, suite: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load an ACT4 inventory/plan and select exactly one suite record."""
    if not path.is_file():
        raise AssetCheckError(f"{label} is missing: {path}")
    data = _load_structured(path)
    if not isinstance(data, dict) or not isinstance(data.get("suites"), list):
        raise AssetCheckError(f"{label} must contain a suites list: {path}")
    matches = [item for item in data["suites"] if isinstance(item, dict) and str(item.get("suite", "")).strip() == suite]
    if len(matches) != 1:
        raise AssetCheckError(f"{label} must contain exactly one record for suite {suite!r}: {path}")
    return data, matches[0]
#要求 inventory 或 asset plan 的 suites 中恰好有一个目标 suite

def _is_external_or_placeholder_path(value: str) -> bool:
    text = value.strip()
    return not text or "://" in text or text.startswith(("git@", "<", "{"))


def _planned_asset_matches(root: Path, raw_path: str) -> list[Path]:
    """Resolve a plan path or glob only within the declared ACT4 root."""
    path = Path(raw_path).expanduser()
    candidate = path if path.is_absolute() else root / path
    pattern = str(candidate)
    if any(char in raw_path for char in "*?["):
        return sorted(Path(item).resolve() for item in glob.glob(pattern, recursive=True) if Path(item).is_file())
    return [candidate.resolve()] if candidate.is_file() else []


def _check_asset_plan_completeness(
    root: Path,
    suite: str,
    inventory: str | Path | None,
    asset_plan: str | Path | None,
    completeness: str,
    asset_kinds: set[str] | None,
    findings: list[dict[str, Any]],
    checks: dict[str, Any],
) -> dict[str, Any]:
    """Verify planned, required filesystem assets for the requested workflow phase."""
    result: dict[str, Any] = {
        "mode": completeness,
        "inventory": None,
        "asset_plan": None,
        "required": 0,
        "checked": 0,
        "present": 0,
        "missing": 0,
        "conditional_skipped": 0,
        "external_skipped": 0,
        "phase_skipped": 0,
        "kind_skipped": 0,
    }
    inventory_record: dict[str, Any] | None = None
    if inventory:
        inventory_path = _resolve_input(root, inventory)
        result["inventory"] = str(inventory_path)
        try:
            _, inventory_record = _load_suite_record(inventory_path, suite, "suite inventory")
        except AssetCheckError as exc:
            _add(findings, "error", "inventory_schema", str(exc), file=str(inventory_path))
        else:
            checks["inventory_suite"] = "present"

    if not asset_plan:
        if completeness != "none":
            _add(findings, "error", "asset_plan_exists", "asset completeness requires --asset-plan")
        checks["asset_plan_status"] = "not_provided"
        return result

    plan_path = _resolve_input(root, asset_plan)
    result["asset_plan"] = str(plan_path)
    try:
        _, plan_suite = _load_suite_record(plan_path, suite, "asset plan")
    except AssetCheckError as exc:
        _add(findings, "error", "asset_plan_schema", str(exc), file=str(plan_path))
        checks["asset_plan_status"] = "invalid"
        return result

    checks["asset_plan_status"] = "present"
    if inventory_record and str(inventory_record.get("workflow", "")) != str(plan_suite.get("workflow", "")):
        _add(
            findings,
            "error",
            "asset_plan_inventory_mismatch",
            "asset plan workflow does not match suite inventory",
            inventory_workflow=inventory_record.get("workflow"),
            asset_plan_workflow=plan_suite.get("workflow"),
        )

    collections = ["source_assets"]
    if completeness == "full":
        collections.extend(["tracked_generated_assets", "validation_assets"])
    for collection in ("source_assets", "tracked_generated_assets", "validation_assets"):
        entries = plan_suite.get(collection, [])
        if not isinstance(entries, list):
            _add(findings, "error", "asset_plan_schema", f"{collection} must be a list", file=str(plan_path))
            continue
        if collection not in collections:
            result["phase_skipped"] += len(entries)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                _add(findings, "error", "asset_plan_schema", f"{collection} entry is not an object", file=str(plan_path))
                continue
            entry_kind = str(
                entry.get("kind", DEFAULT_ASSET_KIND_BY_COLLECTION[collection])
            ).strip().lower()
            if entry_kind not in ASSET_KINDS:
                _add(
                    findings,
                    "error",
                    "asset_plan_schema",
                    f"{collection} entry has unsupported asset kind {entry_kind!r}",
                    file=str(plan_path),
                )
                continue
            if asset_kinds is not None and entry_kind not in asset_kinds:
                result["kind_skipped"] += 1
                continue
            required = str(entry.get("required", "")).strip().lower()
            if required == "conditional":
                result["conditional_skipped"] += 1
                continue
            if required not in {"yes", "true", "required"}:
                continue
            result["required"] += 1
            raw_path = str(entry.get("path", "")).strip()
            if _is_external_or_placeholder_path(raw_path):
                result["external_skipped"] += 1
                continue
            result["checked"] += 1
            matches = _planned_asset_matches(root, raw_path)
            if matches:
                result["present"] += 1
                continue
            result["missing"] += 1
            reported_present = str(entry.get("status", "")).strip().lower() == "present"
            check = "asset_plan_stale" if reported_present else "asset_plan_missing"
            _add(
                findings,
                "error",
                check,
                f"required {collection} asset is missing from ACT4 root: {raw_path}",
                path=raw_path,
                collection=collection,
                planned_status=entry.get("status"),
                role=entry.get("role"),
            )
    checks["asset_plan_required"] = result["required"]
    checks["asset_plan_checked"] = result["checked"]
    checks["asset_plan_present"] = result["present"]
    checks["asset_plan_missing"] = result["missing"]
    checks["asset_plan_kind_skipped"] = result["kind_skipped"]
    return result
#inventory 与 asset plan，确认两者都能找到唯一 suite record，不能则报inventory mismatch

def _split_top_level(value: str, delimiter: str = ",") -> list[str]:
    """Split a mapping expression without splitting braces or parentheses."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote:
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char in "{[(":
            depth += 1
            current.append(char)
        elif char in "}])":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == delimiter and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _expand_braced(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        return [item.strip() for item in _split_top_level(value[1:-1]) if item.strip()]
    return [value]


def parse_mapping_targets(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Return normalized ``group/coverpoint[/bin]`` targets and waivers."""
    values = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    targets: list[dict[str, Any]] = []
    waivers: list[str] = []
    for value in values:
        text = str(value).strip().strip("\"'")
        if not text:
            continue
        if text.upper().startswith(WAIVER_PREFIXES):
            waivers.append(text)
            continue
        # Existing ACT4 files occasionally keep prose after a real symbol.
        text = re.split(r"\s+(?:TODO|Cases such as|but only|and tests for)\b", text, maxsplit=1)[0].strip()
        for segment in _split_top_level(text):
            if not segment:
                continue
            if "/" not in segment:
                targets.append(
                    {"raw": segment, "covergroup": None, "coverpoint": segment, "bin": None}
                )
                continue
            group_expr, cp_expr = segment.split("/", 1)
            path_parts = cp_expr.strip().split("/")
            cp_expr = path_parts[0]
            bin_name = "/".join(path_parts[1:]) or None
            for group in _expand_braced(group_expr):
                for coverpoint in _expand_braced(cp_expr):
                    targets.append(
                        {
                            "raw": segment,
                            "covergroup": group.strip(),
                            "coverpoint": coverpoint.strip(),
                            "bin": bin_name,
                        }
                    )
    return targets, waivers
#将 YAML 内的 coverpoint 表达式正规化成：covergroup / coverpoint / optional-bin
# For example, Suite_cg/cp_field/bin_value is split into its three components.


def _parse_json_array(value: Any, *, field: str, row: int, item_type: type) -> list[Any]:
    try:
        parsed = json.loads(str(value or ""))
    except json.JSONDecodeError as exc:
        raise AssetCheckError(f"CSV row {row} field {field} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list) or any(isinstance(item, bool) or not isinstance(item, item_type) for item in parsed):
        raise AssetCheckError(f"CSV row {row} field {field} must be a JSON {item_type.__name__} array")
    return parsed


def parse_canonical_sheet(path: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse and validate the finalized semantic Sheet CSV."""
    #做严格结构和语义检查
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            rows = list(reader)
            headers = set(reader.fieldnames or [])
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        _add(findings, "error", "sheet_read", f"cannot read canonical Sheet CSV: {exc}", file=str(path))
        return {"rows": [], "coverpoints": {}, "rules": set(), "headers": []}

    missing = sorted(CANONICAL_SHEET_COLUMNS - headers)
    if missing:
        _add(findings, "error", "sheet_schema", f"Sheet CSV is missing columns: {missing}", file=str(path))
    records: list[dict[str, Any]] = []
    source_items: list[str] = []
    coverpoints: dict[str, dict[str, Any]] = {}
    rules: set[str] = set()
    for row_number, raw in enumerate(rows, start=2):
        row = {str(key): str(value or "").strip() for key, value in raw.items()}
        disposition = row.get("disposition", "")
        try:
            row_sources = _parse_json_array(
                row.get("source_items", ""),
                field="source_items",
                row=row_number,
                item_type=str,
            )
        except AssetCheckError as exc:
            _add(findings, "error", "sheet_schema", str(exc), file=str(path))
            row_sources = []
        invalid_source_items = [
            value
            for value in row_sources
            if not IDENTIFIER_RE.fullmatch(value)
        ]
        if invalid_source_items:
            _add(
                findings,
                "error",
                "sheet_source_reference",
                f"row {row_number} has invalid source item IDs: "
                f"{invalid_source_items}",
                file=str(path),
            )
        try:
            row_rules = _parse_json_array(row.get("normative_rules", ""), field="normative_rules", row=row_number, item_type=str)
        except AssetCheckError as exc:
            _add(findings, "error", "sheet_schema", str(exc), file=str(path))
            row_rules = []
        source_items.extend(row_sources)
        if disposition not in {"coverpoint", "removed"}:
            _add(
                findings,
                "error",
                "sheet_semantics",
                f"row {row_number} has unsupported disposition {disposition!r}",
                file=str(path),
            )
            continue
        if disposition == "removed":
            if row.get("coverpoint") or row_rules:
                _add(
                    findings,
                    "error",
                    "sheet_semantics",
                    f"non-coverpoint row {row_number} must not contain coverpoint/rules",
                    file=str(path),
                )
            continue
        name = row.get("coverpoint", "")
        if not IDENTIFIER_RE.fullmatch(name):
            _add(findings, "error", "sheet_coverpoint_identifier", f"invalid coverpoint identifier {name!r}", row=row_number)
        if name in coverpoints:
            _add(findings, "error", "sheet_duplicate_coverpoint", f"duplicate Sheet coverpoint {name!r}", row=row_number)
        coverpoints[name] = {
            "row": row_number,
            "source_items": row_sources,
            "rules": row_rules,
        }
        for rule in row_rules:
            rule_name = str(rule).strip()
            if not rule_name:
                _add(findings, "error", "sheet_rule_identifier", f"blank normative rule at row {row_number}")
            rules.add(rule_name)
        records.append(
            {
                **row,
                "row_number": row_number,
                "source_items_parsed": row_sources,
                "rules_parsed": row_rules,
            }
        )

    duplicates = sorted(
        item for item, count in Counter(source_items).items() if count > 1
    )
    if duplicates:
        _add(
            findings,
            "error",
            "sheet_duplicate_source_ref",
            f"source references consumed more than once: {duplicates}",
            file=str(path),
        )
    return {
        "path": str(path),
        "rows": records,
        "coverpoints": coverpoints,
        "rules": rules,
        "headers": sorted(headers),
        "row_count": len(rows),
    }


def _strip_sv_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*", "", text)


def scan_systemverilog(files: Iterable[Path], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Scan coverage SVH files and retain source/line information."""
    #一个静态扫描器，
    groups: dict[str, dict[str, Any]] = {}
    group_occurrences: defaultdict[str, list[str]] = defaultdict(list)
    source_files: list[str] = []
    for path in sorted(set(files)):
        if not path.is_file():
            _add(findings, "error", "coverage_file", f"coverage file does not exist: {path}", file=str(path))
            continue
        try:
            raw = _read_text(path)
        except AssetCheckError as exc:
            _add(findings, "error", "coverage_encoding", str(exc), file=str(path))
            continue
        source_files.append(str(path))
        text = _strip_sv_comments(raw)
        current_group: str | None = None
        current_cp: str | None = None
        conditional_stack: list[str] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            directive = re.match(r"\s*`(ifdef|ifndef|elsif|else|endif)\b(.*)", line)
            if directive:
                command, expression = directive.groups()
                expression = expression.strip() or "<anonymous>"
                if command in {"ifdef", "ifndef"}:
                    conditional_stack.append(f"{command}:{expression}")
                elif command == "elsif":
                    if conditional_stack:
                        conditional_stack[-1] = f"elsif:{expression}"
                elif command == "else":
                    if conditional_stack:
                        conditional_stack[-1] = f"else:{conditional_stack[-1]}"
                elif command == "endif" and conditional_stack:
                    conditional_stack.pop()
            condition = tuple(conditional_stack)
            for match in re.finditer(r"\bcovergroup\s+([A-Za-z_][\w$]*)\b", line):
                group = match.group(1)
                group_occurrences[group].append(str(path))
                if group in groups:
                    if condition == groups[group].get("condition"):
                        _add(
                            findings,
                            "error",
                            "duplicate_covergroup",
                            f"covergroup {group} is declared more than once",
                            group=group,
                            file=str(path),
                            line=line_number,
                        )
                else:
                    groups[group] = {
                        "coverpoints": {},
                        "bins": {},
                        "files": [],
                        "start_line": line_number,
                        "closed": False,
                        "condition": condition,
                    }
                groups[group]["files"].append(str(path))
                current_group = group
                current_cp = None

            cp_match = re.match(r"\s*([A-Za-z_][\w$]*)\s*:\s*(coverpoint|cross)\b", line)
            if cp_match:
                cp_name, cp_kind = cp_match.groups()
                declaration = line[cp_match.end() :].strip()
                expression = declaration.split("{", 1)[0].rstrip(" ;").strip()
                cross_members = (
                    [item.strip() for item in expression.split(",") if item.strip()]
                    if cp_kind == "cross"
                    else []
                )
                if current_group is None:
                    # ACT4 also stores reusable coverpoint fragments that are
                    # included into a covergroup by generated aggregate code.
                    # Their standalone source has no enclosing covergroup, so
                    # absence of a group here is not itself invalid.
                    continue
                else:
                    coverpoints = groups[current_group]["coverpoints"]
                    previous = coverpoints.get(cp_name)
                    if previous and previous.get("condition") == condition:
                        _add(
                            findings,
                            "error",
                            "duplicate_coverpoint",
                            f"duplicate {cp_kind} {current_group}/{cp_name}",
                            group=current_group,
                            coverpoint=cp_name,
                            file=str(path),
                            line=line_number,
                        )
                    coverpoints[cp_name] = {
                        "kind": cp_kind,
                        "file": str(path),
                        "line": line_number,
                        "condition": condition,
                        "expression": expression,
                        "cross_members": cross_members,
                        "has_default_bin": False,
                        "has_array_bin": False,
                    }
                    groups[current_group]["bins"].setdefault(cp_name, {})
                    current_cp = cp_name

            bin_matches = re.finditer(
                r"\b(?:(?:wildcard\s+)?bins|illegal_bins|ignore_bins)\s+([A-Za-z_][\w$]*)",
                line,
            )
            for bin_match in bin_matches:
                if not current_group or not current_cp:
                    continue
                bin_name = bin_match.group(1)
                bins = groups[current_group]["bins"].setdefault(current_cp, {})
                previous = bins.get(bin_name)
                if previous and previous.get("condition") == condition:
                    _add(
                        findings,
                        "error",
                        "duplicate_bin",
                        f"duplicate bin {current_group}/{current_cp}/{bin_name}",
                        group=current_group,
                        coverpoint=current_cp,
                        bin=bin_name,
                        file=str(path),
                        line=line_number,
                    )
                bins[bin_name] = {"file": str(path), "line": line_number, "condition": condition}
                detail = groups[current_group]["coverpoints"].get(current_cp)
                if detail:
                    tail = line[bin_match.end() :]
                    detail["has_array_bin"] = bool(
                        detail["has_array_bin"]
                        or re.match(r"\s*\[\s*\]", tail)
                    )
                    detail["has_default_bin"] = bool(
                        detail["has_default_bin"]
                        or re.search(r"=\s*default\b", tail)
                    )

            if re.search(r"\bendgroup\b", line):
                if current_group:
                    groups[current_group]["closed"] = True
                current_group = None
                current_cp = None

        if current_group is not None:
            _add(
                findings,
                "error",
                "coverage_syntax",
                f"covergroup {current_group} is missing endgroup",
                file=str(path),
                line=groups[current_group].get("start_line"),
            )

    for group, occurrences in group_occurrences.items():
        if len(occurrences) > 1:
            # The declaration check above reports each duplicate, but retain a
            # compact ownership record for downstream comparisons.
            groups[group]["duplicate_files"] = sorted(set(occurrences))
    normalized: dict[str, Any] = {}
    for group, data in sorted(groups.items()):
        normalized[group] = {
            "coverpoints": sorted(data["coverpoints"]),
            "coverpoint_details": data["coverpoints"],
            "bins": {
                cp: sorted(bin_map)
                for cp, bin_map in sorted(data["bins"].items())
            },
            "bin_details": data["bins"],
            "files": sorted(set(data["files"])),
            "closed": bool(data["closed"]),
            "start_line": data.get("start_line"),
            "condition": data.get("condition", ()),
            "duplicate_files": data.get("duplicate_files", []),
        }
    return {"files": sorted(source_files), "groups": normalized}


def _validate_priv_coverage_semantics(
    coverage: dict[str, Any], findings: list[dict[str, Any]]
) -> None:
    """Reject coverage constructs whose false-hit risk is structurally provable."""
    for group_name, group in coverage.get("groups", {}).items():
        details = group.get("coverpoint_details", {})
        cross_inputs = {
            str(member)
            for detail in details.values()
            if detail.get("kind") == "cross"
            for member in detail.get("cross_members", [])
        }
        for name, detail in details.items():
            if detail.get("has_default_bin") and name in cross_inputs:
                _add(
                    findings,
                    "error",
                    "coverage_default_bin",
                    f"cross input must use explicit bins: {group_name}/{name}",
                    file=detail.get("file"),
                    line=detail.get("line"),
                )
            expression = str(detail.get("expression") or "").lower()
            if (
                detail.get("kind") == "coverpoint"
                and "$onehot" in expression
                and not detail.get("has_array_bin")
            ):
                _add(
                    findings,
                    "error",
                    "coverage_bitwalk_bins",
                    f"bit-walk coverpoint needs a per-position bins[] array: {group_name}/{name}",
                    file=detail.get("file"),
                    line=detail.get("line"),
                )


def _validate_coverage_intent(
    coverage: dict[str, Any],
    intent_path: Path,
    suite: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate suite-declared semantic dimensions without hard-coding a suite."""
    if not intent_path.is_file():
        _add(
            findings,
            "error",
            "coverage_intent_exists",
            f"coverage intent contract is missing: {intent_path}",
            file=str(intent_path),
        )
        return {"path": str(intent_path), "targets": 0}
    try:
        intent = _load_manifest(intent_path)
    except AssetCheckError as exc:
        _add(findings, "error", "coverage_intent_parse", str(exc), file=str(intent_path))
        return {"path": str(intent_path), "targets": 0}

    if intent.get("schema_version") != 1:
        _add(
            findings,
            "error",
            "coverage_intent_schema",
            "coverage intent schema_version must be 1",
            file=str(intent_path),
        )
    declared_suite = str(intent.get("suite", "")).strip()
    if suite and declared_suite != suite:
        _add(
            findings,
            "error",
            "coverage_intent_suite",
            f"coverage intent suite must be {suite!r}, got {declared_suite!r}",
            file=str(intent_path),
        )
    supported_xlens = intent.get("supported_xlens")
    if not isinstance(supported_xlens, list) or not supported_xlens or any(
        value not in {32, 64} for value in supported_xlens
    ):
        _add(
            findings,
            "error",
            "coverage_intent_xlen",
            "supported_xlens must be a non-empty list containing only 32 and/or 64",
            file=str(intent_path),
        )

    targets = intent.get("targets")
    if not isinstance(targets, dict) or not targets:
        _add(
            findings,
            "error",
            "coverage_intent_schema",
            "coverage intent targets must be a non-empty mapping",
            file=str(intent_path),
        )
        return {"path": str(intent_path), "targets": 0}

    checked = 0
    for target_name, target_intent in targets.items():
        if not isinstance(target_intent, dict):
            _add(
                findings,
                "error",
                "coverage_intent_schema",
                f"intent target {target_name!r} must be a mapping",
                file=str(intent_path),
            )
            continue
        target = str(target_name).strip()
        declared_group = str(target_intent.get("covergroup", "")).strip()
        if "/" in target:
            path_group, target = target.split("/", 1)
            declared_group = declared_group or path_group
        group_name = declared_group or (f"{suite}_cg" if suite else "")
        group = coverage.get("groups", {}).get(group_name)
        detail = (
            group.get("coverpoint_details", {}).get(target)
            if isinstance(group, dict)
            else None
        )
        if not isinstance(detail, dict):
            _add(
                findings,
                "error",
                "coverage_intent_target",
                f"declared coverage target is missing: {group_name}/{target}",
                file=str(intent_path),
            )
            continue
        checked += 1
        target_kind = str(target_intent.get("target_kind", "")).strip()
        if target_kind and target_kind not in {"coverpoint", "cross"}:
            _add(
                findings,
                "error",
                "coverage_intent_schema",
                f"intent target {target_name!r} has invalid target_kind {target_kind!r}",
                file=str(intent_path),
            )
        elif target_kind and detail.get("kind") != target_kind:
            _add(
                findings,
                "error",
                "coverage_intent_kind",
                f"coverage target kind differs from intent: {group_name}/{target}",
                file=detail.get("file"),
                line=detail.get("line"),
                expected=target_kind,
                actual=detail.get("kind"),
            )
        required_members = _string_list(target_intent.get("required_cross_members"))
        required_conditions = _string_list(target_intent.get("required_conditions"))
        required_bins = _string_list(target_intent.get("required_bins"))
        expression_terms = _string_list(
            target_intent.get("required_expression_terms")
        )
        if not any(
            (required_members, required_conditions, required_bins, expression_terms)
        ):
            _add(
                findings,
                "error",
                "coverage_intent_schema",
                f"intent target {target_name!r} must declare at least one verifiable requirement",
                file=str(intent_path),
            )
            continue
        if required_members:
            if detail.get("kind") != "cross":
                _add(
                    findings,
                    "error",
                    "coverage_intent_cross",
                    f"target requiring cross members is not a cross: {group_name}/{target}",
                    file=detail.get("file"),
                    line=detail.get("line"),
                )
            actual_members = {str(value) for value in detail.get("cross_members", [])}
            missing_members = set(required_members) - actual_members
            if missing_members:
                _add(
                    findings,
                    "error",
                    "coverage_intent_cross_members",
                    f"coverage target is missing required semantic dimensions: {group_name}/{target}",
                    file=detail.get("file"),
                    line=detail.get("line"),
                    missing=sorted(missing_members),
                    actual=sorted(actual_members),
                )
            if target_intent.get("exact_cross_members") is True and actual_members != set(required_members):
                _add(
                    findings,
                    "error",
                    "coverage_intent_cross_members",
                    f"coverage target cross dimensions differ from its exact intent: {group_name}/{target}",
                    file=detail.get("file"),
                    line=detail.get("line"),
                    missing=sorted(set(required_members) - actual_members),
                    extra=sorted(actual_members - set(required_members)),
                )
        actual_conditions = {str(value) for value in detail.get("condition", [])}
        missing_conditions = set(required_conditions) - actual_conditions
        if missing_conditions:
            _add(
                findings,
                "error",
                "coverage_intent_condition",
                f"coverage target is missing required preprocessor guards: {group_name}/{target}",
                file=detail.get("file"),
                line=detail.get("line"),
                missing=sorted(missing_conditions),
                actual=sorted(actual_conditions),
            )
        actual_bins = set(
            (group.get("bins", {}) if isinstance(group, dict) else {}).get(
                target, []
            )
        )
        missing_bins = set(required_bins) - actual_bins
        if missing_bins:
            _add(
                findings,
                "error",
                "coverage_intent_bins",
                f"coverage target is missing required bins: {group_name}/{target}",
                file=detail.get("file"),
                line=detail.get("line"),
                missing=sorted(missing_bins),
                actual=sorted(actual_bins),
            )
        expression = str(detail.get("expression", ""))
        missing_terms = [term for term in expression_terms if term not in expression]
        if missing_terms:
            _add(
                findings,
                "error",
                "coverage_intent_expression",
                f"coverage target expression is missing required terms: {group_name}/{target}",
                file=detail.get("file"),
                line=detail.get("line"),
                missing=missing_terms,
                actual=expression,
            )
    return {"path": str(intent_path), "targets": checked}


def _resolve_string(node: ast.AST, env: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                resolved = _resolve_string(value.value, env)
                if resolved is None:
                    return None
                parts.append(resolved)
                continue
            return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_string(node.left, env)
        right = _resolve_string(node.right, env)
        if left is not None and right is not None:
            return left + right
    return None


def _resolve_positive_int(node: ast.AST, env: dict[str, int]) -> int | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and node.value > 0
    ):
        return node.value
    return env.get(node.id) if isinstance(node, ast.Name) else None


def _resolve_symbolic_string(
    node: ast.AST | None,
    parameters: set[str],
    env: dict[str, str],
) -> tuple[str, str] | None:
    if node is None:
        return None
    value = _resolve_string(node, env)
    if value is not None:
        return ("literal", value)
    if isinstance(node, ast.Name) and node.id in parameters:
        return ("parameter", node.id)
    return None


def _bind_symbolic_string(
    symbolic: tuple[str, str] | None,
    call: ast.Call,
    callee: ast.FunctionDef | ast.AsyncFunctionDef,
    caller_parameters: set[str],
    env: dict[str, str],
) -> tuple[str, str] | None:
    if symbolic is None or symbolic[0] == "literal":
        return symbolic
    parameter = symbolic[1]
    positional = [argument.arg for argument in callee.args.args]
    actual: ast.AST | None = None
    if parameter in positional:
        index = positional.index(parameter)
        if index < len(call.args):
            actual = call.args[index]
    if actual is None:
        actual = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == parameter
            ),
            None,
        )
    return _resolve_symbolic_string(actual, caller_parameters, env)


def _inferred_testcase_records(
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    env: dict[str, str],
) -> list[dict[str, Any]]:
    """Propagate literal testcase metadata through simple local helpers."""
    templates: dict[
        str,
        set[
            tuple[
                tuple[str, str] | None,
                tuple[str, str] | None,
                tuple[str, str] | None,
            ]
        ],
    ] = {name: set() for name in functions}

    for name, function in functions.items():
        parameters = {argument.arg for argument in function.args.args}
        for node in ast.walk(function):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_testcase"
            ):
                continue
            values = tuple(
                _resolve_symbolic_string(
                    node.args[index] if index < len(node.args) else None,
                    parameters,
                    env,
                )
                for index in range(3)
            )
            templates[name].add(values)

    changed = True
    while changed:
        changed = False
        for caller_name, caller in functions.items():
            caller_parameters = {argument.arg for argument in caller.args.args}
            for call in (
                node for node in ast.walk(caller) if isinstance(node, ast.Call)
            ):
                if not isinstance(call.func, ast.Name) or call.func.id not in functions:
                    continue
                callee_name = call.func.id
                callee = functions[callee_name]
                for template in tuple(templates[callee_name]):
                    bound = tuple(
                        _bind_symbolic_string(
                            value,
                            call,
                            callee,
                            caller_parameters,
                            env,
                        )
                        for value in template
                    )
                    if bound not in templates[caller_name]:
                        templates[caller_name].add(bound)
                        changed = True

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for function_templates in templates.values():
        for template in function_templates:
            if not all(
                value and value[0] == "literal" for value in template[1:]
            ):
                continue
            bin_name = (
                template[0][1]
                if template[0] and template[0][0] == "literal"
                else "<dynamic>"
            )
            key = (bin_name, template[1][1], template[2][1])
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "bin": key[0],
                    "coverpoint": key[1],
                    "covergroup": key[2],
                    "line": None,
                    "inferred_through_helper": True,
                }
            )
    return records


def is_itgen_private_path(value: str) -> bool:
    """Recognize private inputs only when used as dependencies, not prose."""
    return bool(re.search(
        r"(?:^|[/\\])(?:unity_test|itgen|ucagent|act4_privileged_suite|\.ucagent)(?:[/\\]|$)"
        r"|(?:^|[/\\])[^/\\]*_(?:vm_resource_contract|generator_contract|"
        r"coverage_intent|ai_review|switch_capability_audit|file_manifest)\.(?:yaml|yml|json)$",
        value,
        re.IGNORECASE,
    ))


def _generator_workspace_dependencies(
    tree: ast.Module, *, path_is_local: Callable[[str], bool] | None = None,
    module_is_local: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Find explicit private imports and file probes, without banning native I/O.

    Resolve simple local path assignments only. This is not a general Python
    dependency proof; clean-checkout generation remains part of the review.
    """
    aliases: dict[str, str] = {}
    dependencies: list[dict[str, Any]] = []

    def record(node: ast.AST, kind: str, references: set[str]) -> None:
        if references:
            dependencies.append({"line": node.lineno, "kind": kind, "references": sorted(references)})

    def private_module(name: str) -> bool:
        return (
            name.split(".", 1)[0].lower() in {
                "itgen", "ucagent", "unity_test", "act4_privileged_suite"
            }
            or bool(module_is_local and module_is_local(name))
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
                if private_module(item.name):
                    record(node, "import", {item.name})
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for item in node.names:
                aliases[item.asname or item.name] = f"{module}.{item.name}"
            if private_module(module):
                record(node, "import", {module})
            for item in node.names:
                member = f"{module}{'' if module.endswith('.') else '.'}{item.name}"
                if private_module(member):
                    record(node, "import", {member})

    def callee(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{callee(node.value)}.{node.attr}"
        return ""

    def refs(node: ast.AST, env: dict[str, set[str]]) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value} if (
                is_itgen_private_path(node.value)
                or (path_is_local and path_is_local(node.value))
            ) else set()
        if isinstance(node, ast.Name):
            return env.get(node.id, set())
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            return refs(node.value, env)
        if isinstance(node, (ast.BinOp, ast.JoinedStr, ast.FormattedValue, ast.List, ast.Tuple)):
            return set().union(*(refs(child, env) for child in ast.iter_child_nodes(node)))
        if isinstance(node, ast.Call):
            name = callee(node.func)
            if name in {"Path", "pathlib.Path", "str", "os.path.join"} or name.rsplit(".", 1)[-1] in {
                "resolve", "absolute", "expanduser", "joinpath", "with_name", "format",
            }:
                return set().union(refs(node.func, env), *(refs(arg, env) for arg in node.args))
        return set()

    def scope_nodes(scope: ast.AST):
        for child in ast.iter_child_nodes(scope):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            yield child
            yield from scope_nodes(child)

    global_env: dict[str, set[str]] = {}
    scopes = [tree] + [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        env = global_env if scope is tree else dict(global_env)
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in ast.walk(scope.args):
                if isinstance(argument, ast.arg):
                    env.pop(argument.arg, None)
        for node in scope_nodes(scope):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = refs(node.value, env)
                for target in targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = value
            if (
                isinstance(node, ast.Subscript) and callee(node.value) == "os.environ"
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
                and (
                    node.slice.value.upper().startswith(("ITGEN_", "UCAGENT_"))
                    or node.slice.value.upper() == "ACT4_MANUAL_ROOT"
                )
            ):
                record(node, "environment", {node.slice.value})
            if not isinstance(node, ast.Call):
                continue
            name = callee(node.func)
            if name in {"os.getenv", "os.environ.get"} and node.args:
                argument = node.args[0]
                if (
                    isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                    and (
                        argument.value.upper().startswith(("ITGEN_", "UCAGENT_"))
                        or argument.value.upper() == "ACT4_MANUAL_ROOT"
                    )
                ):
                    record(node, "environment", {argument.value})
            if name in {"sys.path.insert", "sys.path.append", "sys.path.extend"}:
                record(node, "import_path", set().union(*(refs(arg, env) for arg in node.args)))
            if name in {"__import__", "importlib.import_module"} and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and private_module(argument.value):
                    record(node, "import", {argument.value})
            if name in {"open", "builtins.open", "io.open", "os.path.exists", "os.path.isfile", "os.path.isdir"}:
                arguments = node.args[:1] + [kw.value for kw in node.keywords if kw.arg in {"file", "path"}]
                record(node, "file_access", set().union(*(refs(arg, env) for arg in arguments)))
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {
                "open", "read_text", "read_bytes", "exists", "is_file", "is_dir", "stat", "glob", "rglob", "iterdir",
            }:
                record(node, "file_access", refs(node.func.value, env))
    return dependencies


def scan_python_generator(path: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": str(path),
        "testcases": [],
        "dynamic": [],
        "registrations": [],
        "literal_strings": [],
        "syntax_ok": False,
        "priv_generators": [],
        "discarded_assembly_calls": [],
    }
    try:
        text = _read_text(path)
        tree = ast.parse(text, filename=str(path))
    except (AssetCheckError, SyntaxError) as exc:
        _add(findings, "error", "generator_parse", str(exc), file=str(path))
        result["error"] = str(exc)
        return result
    result["syntax_ok"] = True
    result["workspace_dependencies"] = _generator_workspace_dependencies(tree)
    result["literal_strings"] = sorted(
        {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    )
    env: dict[str, str] = {}
    int_env: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                value = _resolve_string(node.value, env)
                if value is not None:
                    env[node.targets[0].id] = value
                int_value = _resolve_positive_int(node.value, int_env)
                if int_value is not None:
                    int_env[node.targets[0].id] = int_value
            elif (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Tuple)
                and isinstance(node.value, ast.Tuple)
            ):
                names = [
                    item.id
                    for item in node.targets[0].elts
                    if isinstance(item, ast.Name)
                ]
                values = [_resolve_string(item, env) for item in node.value.elts]
                for name, value in zip(names, values):
                    if value is not None:
                        env[name] = value

    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    functions = {
        node.name: node
        for node in function_nodes
    }
    for name, count in Counter(node.name for node in function_nodes).items():
        if count > 1:
            _add(
                findings,
                "error",
                "generator_duplicate_function",
                f"generator defines function {name!r} {count} times",
                file=str(path),
                lines=[node.lineno for node in function_nodes if node.name == name],
            )
    for function in function_nodes:
        for node in ast.walk(function):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            callee = node.value.func
            call_name = (
                callee.id
                if isinstance(callee, ast.Name)
                else callee.attr
                if isinstance(callee, ast.Attribute)
                else ""
            )
            if re.fullmatch(
                r"(?:_csr[rswc]+|gen_csr_(?:read|write)_sigupd|write_sigupd|_goto_mode)",
                call_name,
            ):
                result["discarded_assembly_calls"].append(
                    {
                        "function": function.name,
                        "helper": call_name,
                        "line": node.lineno,
                    }
                )
        for decorator in function.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "add_priv_test_generator"
            ):
                continue
            suite_name = (
                _resolve_string(decorator.args[0], env) if decorator.args else None
            )
            threshold_node = next(
                (
                    keyword.value
                    for keyword in decorator.keywords
                    if keyword.arg == "testcases_per_file"
                ),
                None,
            )
            threshold = (
                _resolve_positive_int(threshold_node, int_env)
                if threshold_node is not None
                else None
            )
            reachable = {function.name}
            pending = [function.name]
            while pending:
                current = functions[pending.pop()]
                for call in (
                    node for node in ast.walk(current) if isinstance(node, ast.Call)
                ):
                    if (
                        isinstance(call.func, ast.Name)
                        and call.func.id in functions
                        and call.func.id not in reachable
                    ):
                        reachable.add(call.func.id)
                        pending.append(call.func.id)
            reachable_functions = [functions[name] for name in sorted(reachable)]
            calls = [
                node
                for reachable_function in reachable_functions
                for node in ast.walk(reachable_function)
                if isinstance(node, ast.Call)
            ]
            start_calls = [
                call
                for call in calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr in {"begin_test_chunk", "new_test_chunk"}
            ]
            end_calls = [
                call
                for call in calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "end_test_chunk"
            ]
            loop_has_chunk_start = any(
                isinstance(loop, (ast.For, ast.AsyncFor, ast.While))
                and any(
                    isinstance(item, ast.Call)
                    and isinstance(item.func, ast.Attribute)
                    and item.func.attr in {"begin_test_chunk", "new_test_chunk"}
                    for item in ast.walk(loop)
                )
                for reachable_function in reachable_functions
                for loop in ast.walk(reachable_function)
            )
            delegated_return_calls = sorted(
                {
                    returned.value.func.id
                    for returned in ast.walk(function)
                    if isinstance(returned, ast.Return)
                    and isinstance(returned.value, ast.Call)
                    and isinstance(returned.value.func, ast.Name)
                    and returned.value.func.id not in functions
                }
            )
            result["priv_generators"].append(
                {
                    "suite": suite_name,
                    "function": function.name,
                    "line": function.lineno,
                    "return_annotation": ast.unparse(function.returns)
                    if function.returns
                    else None,
                    "testcases_per_file": threshold,
                    "explicit_testcases_per_file": threshold_node is not None,
                    "chunk_start_calls": len(start_calls),
                    "chunk_end_calls": len(end_calls),
                    "loop_has_chunk_start": loop_has_chunk_start,
                    "delegated_return_calls": delegated_return_calls,
                }
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_testcase":
            values = [_resolve_string(arg, env) if index < 3 else None for index, arg in enumerate(node.args[:3])]
            record = {
                "bin": values[0] if len(values) > 0 else None,
                "coverpoint": values[1] if len(values) > 1 else None,
                "covergroup": values[2] if len(values) > 2 else None,
                "line": getattr(node, "lineno", None),
            }
            if record["coverpoint"] is None or record["covergroup"] is None:
                result["dynamic"].append(record)
            else:
                result["testcases"].append(record)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
            "add_priv_test_generator",
            "add_coverpoint_generator",
            "add_instruction_formatter",
        }:
            if node.args:
                value = _resolve_string(node.args[0], env)
                if value is not None:
                    result["registrations"].append(value)
    known_testcases = {
        (record.get("bin"), record.get("coverpoint"), record.get("covergroup"))
        for record in result["testcases"]
    }
    for record in _inferred_testcase_records(functions, env):
        key = (record["bin"], record["coverpoint"], record["covergroup"])
        if key not in known_testcases:
            result["testcases"].append(record)
            known_testcases.add(key)
    result["registrations"] = sorted(set(result["registrations"]))
    return result


def _validate_priv_generator_api(
    result: dict[str, Any],
    suite: str,
    findings: list[dict[str, Any]],
    *,
    require_testchunk_api: bool,
    require_auto_split: bool,
    max_testcases_per_file: int | None,
) -> None:
    """Validate the privileged generator API introduced by current ACT4."""
    if not (require_testchunk_api or require_auto_split):
        return
    for discarded in result.get("discarded_assembly_calls", []):
        _add(
            findings,
            "error",
            "generator_discarded_assembly",
            "assembly-producing helper return value is discarded instead of being appended to a TestChunk",
            file=result.get("file"),
            **discarded,
        )
    entries = [
        entry
        for entry in result.get("priv_generators", [])
        if not suite or entry.get("suite") == suite
    ]
    if not entries:
        _add(
            findings,
            "error",
            "generator_priv_api",
            f"no @add_priv_test_generator registration was statically resolved for {suite or 'the suite'}",
            file=result.get("file"),
        )
        return
    # Native registry supports multiple entries with independent metadata.
    for entry in entries:
        details = {
            "file": result.get("file"),
            "function": entry.get("function"),
            "line": entry.get("line"),
        }
        annotation = re.sub(r"\s+", "", str(entry.get("return_annotation") or "")).strip("'\"")
        annotation = re.sub(r"\b(?:typing|collections\.abc)\.", "", annotation)
        typed_testchunk_sequence = bool(re.fullmatch(
            r"(?:list|Sequence|tuple)\[(?:[A-Za-z_]\w*\.)*TestChunk(?:,\.\.\.)?\]", annotation
        ))
        if require_testchunk_api and not typed_testchunk_sequence:
            known_wrong = not annotation or bool(re.fullmatch(
                r"(?:str|int|None|(?:list|Sequence|tuple)\[(?:str|int|float|bool)(?:,\.\.\.)?\]|(?:Iterable|Iterator)\[.*\])", annotation
            ))
            _add(
                findings,
                "error" if known_wrong else "warning",
                "generator_testchunk_return" if known_wrong else "generator_testchunk_return_unverified",
                "generator must return Sequence[TestChunk]; unresolved type aliases require source/API review",
                return_annotation=entry.get("return_annotation"),
                **details,
            )
        start_count = int(entry.get("chunk_start_calls") or 0)
        end_count = int(entry.get("chunk_end_calls") or 0)
        delegated_calls = entry.get("delegated_return_calls") or []
        if require_testchunk_api and typed_testchunk_sequence:
            if bool(start_count) != bool(end_count):
                _add(
                    findings,
                    "warning",
                    "generator_testchunk_lifecycle_unverified",
                    "only part of the TestChunk lifecycle is statically visible; verify helper calls and native generation",
                    chunk_start_calls=start_count,
                    chunk_end_calls=end_count,
                    **details,
                )
            elif not start_count:
                _add(
                    findings,
                    "warning",
                    "generator_testchunk_lifecycle_unverified",
                    (
                        "TestChunk construction is delegated to an imported helper; verify the helper and generated files"
                        if delegated_calls
                        else "registered generator has no statically visible TestChunk construction"
                    ),
                    delegated_return_calls=delegated_calls,
                    **details,
                )
        if require_auto_split:
            if (
                not entry.get("explicit_testcases_per_file")
                or entry.get("testcases_per_file") is None
            ):
                _add(
                    findings,
                    "error",
                    "generator_auto_split_threshold",
                    "automatic .S splitting requires an explicit positive integer testcases_per_file",
                    testcases_per_file=entry.get("testcases_per_file"),
                    **details,
                )
            elif (
                max_testcases_per_file is not None
                and int(entry["testcases_per_file"]) > max_testcases_per_file
            ):
                _add(
                    findings,
                    "error",
                    "generator_auto_split_threshold",
                    "testcases_per_file exceeds TESTCASES_PER_PRIV_FILE from the checked ACT4 source",
                    testcases_per_file=entry.get("testcases_per_file"),
                    max_testcases_per_file=max_testcases_per_file,
                    **details,
                )


def _read_priv_testcase_limit(
    root: Path,
    findings: list[dict[str, Any]],
    *,
    required: bool,
) -> int | None:
    """Read the current ACT4 privileged split limit from its source tree."""
    if not required:
        return None
    path = root / "generators/testgen/src/testgen/constants.py"
    try:
        tree = ast.parse(_read_text(path), filename=str(path))
    except (AssetCheckError, SyntaxError) as exc:
        _add(
            findings,
            "error",
            "generator_auto_split_limit",
            f"cannot read TESTCASES_PER_PRIV_FILE from current ACT4: {exc}",
            file=str(path),
        )
        return None
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TESTCASES_PER_PRIV_FILE"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "TESTCASES_PER_PRIV_FILE"
        ):
            value = node.value
        if (
            isinstance(value, ast.Constant)
            and isinstance(value.value, int)
            and value.value > 0
        ):
            return value.value
    _add(
        findings,
        "error",
        "generator_auto_split_limit",
        "current ACT4 does not expose TESTCASES_PER_PRIV_FILE as a positive integer constant",
        file=str(path),
    )
    return None


def _validate_required_keys(
    data: Any, keys: Iterable[str], findings: list[dict[str, Any]], label: str
) -> None:
    if not isinstance(data, dict):
        _add(findings, "error", "asset_schema", f"{label} must be an object")
        return
    for key in keys:
        if key not in data:
            _add(findings, "error", "asset_schema", f"{label} is missing required key {key!r}")


def _check_generic_asset(
    root: Path,
    spec: dict[str, Any],
    findings: list[dict[str, Any]],
    checked: list[dict[str, Any]],
) -> None:
    raw_path = spec.get("path", spec.get("file"))
    if not raw_path:
        _add(findings, "error", "asset_manifest", "asset entry has no path", asset=spec)
        return
    path = _resolve_input(root, str(raw_path))
    required = bool(spec.get("required", True))
    paths: list[Path]
    if any(char in str(raw_path) for char in "*?["):
        matches = sorted(root.glob(str(raw_path)))
        if not matches:
            matches = sorted(Path.cwd().glob(str(raw_path)))
        paths = [Path(item).resolve() for item in matches]
        if not paths and required:
            _add(findings, "error", "asset_exists", f"required asset pattern matched no files: {raw_path}")
            return
        if not paths:
            return
    else:
        paths = [path]
    for path in paths:
        entry = {"path": str(path), "kind": spec.get("kind", "auto"), "required": required}
        checked.append(entry)
        if not path.is_file():
            if required:
                _add(findings, "error", "asset_exists", f"required asset is missing: {_relative(path, root)}", file=str(path))
            else:
                _add(findings, "warning", "asset_exists", f"optional asset is missing: {_relative(path, root)}", file=str(path))
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            _add(findings, "error", "asset_encoding", f"asset is not UTF-8: {exc}", file=str(path))
            continue
        except OSError as exc:
            _add(findings, "error", "asset_read", f"cannot read asset: {exc}", file=str(path))
            continue
        expected_hash = str(spec.get("sha256", "")).strip().lower()
        if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
            _add(findings, "error", "asset_hash", "asset SHA-256 does not match manifest", file=str(path))
        baseline_value = spec.get("baseline")
        if baseline_value:
            baseline = _resolve_input(root, str(baseline_value))
            if not baseline.is_file():
                _add(findings, "error", "asset_baseline", f"baseline asset is missing: {baseline}", file=str(path))
            else:
                try:
                    comparison = str(spec.get("comparison", "exact")).lower()
                    if comparison == "structured" and path.suffix.lower() in {".json", ".yaml", ".yml"}:
                        matches_baseline = _load_structured(path) == _load_structured(baseline)
                    else:
                        matches_baseline = raw == baseline.read_bytes()
                    if not matches_baseline:
                        _add(
                            findings,
                            "error",
                            "asset_baseline",
                            f"asset differs from baseline ({comparison} comparison)",
                            file=str(path),
                            baseline=str(baseline),
                        )
                except (AssetCheckError, OSError) as exc:
                    _add(findings, "error", "asset_baseline", f"cannot compare baseline: {exc}", file=str(path))
        for needle in _string_list(spec.get("required_text")):
            if needle not in text:
                _add(findings, "error", "asset_required_text", f"required text is absent: {needle!r}", file=str(path))
        for needle in _string_list(spec.get("forbidden_text")):
            if needle in text:
                _add(findings, "error", "asset_forbidden_text", f"forbidden text is present: {needle!r}", file=str(path))
        kind = str(spec.get("kind", "auto")).lower()
        suffix = path.suffix.lower()
        if kind in {"auto", "json"} and suffix == ".json":
            try:
                data = json.loads(text)
                _validate_required_keys(data, _string_list(spec.get("required_keys")), findings, str(path))
            except json.JSONDecodeError as exc:
                _add(findings, "error", "asset_json_schema", f"invalid JSON: {exc}", file=str(path))
        elif kind in {"auto", "yaml", "yml"} and suffix in {".yaml", ".yml"}:
            if yaml is None:
                _add(findings, "error", "asset_yaml_schema", "PyYAML is not installed", file=str(path))
            else:
                try:
                    data = yaml.safe_load(text)
                    _validate_required_keys(data, _string_list(spec.get("required_keys")), findings, str(path))
                except yaml.YAMLError as exc:
                    _add(findings, "error", "asset_yaml_schema", f"invalid YAML: {exc}", file=str(path))
        elif kind in {"auto", "csv"} and suffix == ".csv":
            try:
                reader = csv.DictReader(io.StringIO(text))
                headers = set(reader.fieldnames or [])
                for key in _string_list(spec.get("required_columns")):
                    if key not in headers:
                        _add(findings, "error", "asset_csv_schema", f"missing CSV column {key!r}", file=str(path))
                if spec.get("non_empty", False) and not any(reader):
                    _add(findings, "error", "asset_csv_schema", "CSV has no data rows", file=str(path))
            except csv.Error as exc:
                _add(findings, "error", "asset_csv_schema", f"invalid CSV: {exc}", file=str(path))
        elif kind in {"auto", "python", "py"} and suffix == ".py":
            try:
                ast.parse(text, filename=str(path))
            except SyntaxError as exc:
                _add(findings, "error", "asset_python_syntax", f"invalid Python: {exc}", file=str(path))
        elif kind in {"systemverilog", "sv", "svh"} or suffix in {".sv", ".svh"}:
            # Full preprocessing requires the target simulator.  These cheap
            # checks still catch common truncation and duplicate delimiters.
            if text.count("(") != text.count(")"):
                _add(findings, "error", "asset_sv_balance", "unbalanced parentheses", file=str(path))
            if text.count("{") != text.count("}"):
                _add(findings, "error", "asset_sv_balance", "unbalanced braces", file=str(path))


def _discover_paths(root: Path, explicit: Any, patterns: Any, default_patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in _string_list(explicit):
        path = _resolve_input(root, value)
        if any(char in value for char in "*?["):
            root_matches = sorted(root.glob(value))
            if root_matches:
                paths.extend(Path(item).resolve() for item in root_matches)
            else:
                paths.extend(Path(item).resolve() for item in sorted(Path.cwd().glob(value)))
        elif path.is_file():
            paths.append(path)
    selected_patterns = _string_list(patterns) or default_patterns
    if not explicit:
        for pattern in selected_patterns:
            paths.extend(Path(item).resolve() for item in sorted(root.glob(pattern)))
    return sorted(set(paths))


def _norm_rule_names_from_defs(
    norm_data: Any,
    findings: list[dict[str, Any]],
    path: Path | None,
) -> set[str]:
    """Read canonical rule names from an ISA manual rule-definition YAML."""
    if not isinstance(norm_data, dict) or not isinstance(
        norm_data.get("normative_rule_definitions"), list
    ):
        _add(
            findings,
            "error",
            "norm_schema",
            "normative metadata must contain a normative_rule_definitions list",
            file=str(path) if path else None,
        )
        return set()
    names: list[str] = []
    for index, item in enumerate(norm_data["normative_rule_definitions"]):
        if not isinstance(item, dict):
            _add(
                findings,
                "error",
                "norm_schema",
                f"normative_rule_definitions[{index}] is not an object",
                file=str(path) if path else None,
            )
            continue
        raw_names = item.get("names", item.get("name", []))
        if isinstance(raw_names, str):
            item_names = [raw_names.strip()] if raw_names.strip() else []
        elif isinstance(raw_names, list):
            item_names = [
                str(name).strip() for name in raw_names if str(name).strip()
            ]
        else:
            item_names = []
        if not item_names:
            _add(
                findings,
                "error",
                "norm_schema",
                f"normative_rule_definitions[{index}] has no non-empty name/names",
                file=str(path) if path else None,
            )
        names.extend(item_names)
    for name, count in Counter(names).items():
        if count > 1:
            _add(
                findings,
                "error",
                "norm_duplicate_rule",
                f"normative metadata defines {name!r} {count} times",
                file=str(path) if path else None,
            )
    return set(names)


def _mapping_entries(
    mapping_data: Any,
    known_rules: set[str],
    findings: list[dict[str, Any]],
    path: Path,
) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    if not isinstance(mapping_data, dict) or not isinstance(mapping_data.get("normative_rule_definitions"), list):
        _add(findings, "error", "mapping_schema", "mapping must contain normative_rule_definitions list", file=str(path))
        return [], set(), []
    entries = mapping_data["normative_rule_definitions"]
    normalized: list[dict[str, Any]] = []
    mapped_rules: list[str] = []
    targets: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            _add(findings, "error", "mapping_schema", f"mapping entry {index} is not an object", file=str(path))
            continue
        names = entry.get("names", entry.get("name", []))
        if isinstance(names, str):
            names = [part.strip() for part in names.split(",") if part.strip()]
        elif isinstance(names, list):
            expanded: list[str] = []
            for item in names:
                expanded.extend(part.strip() for part in str(item).split(",") if part.strip())
            names = expanded
        else:
            names = []
        names = [str(name).strip() for name in names if str(name).strip()]
        if not names:
            _add(findings, "error", "mapping_schema", f"mapping entry {index} has no rule name", file=str(path))
        coverpoint_value = entry.get("coverpoint")
        parsed_targets, waivers = parse_mapping_targets(coverpoint_value)
        if not parsed_targets and not waivers:
            _add(findings, "error", "mapping_empty_target", f"mapping entry {index} has no coverpoint target or waiver", file=str(path), rule_names=names)
        for name in names:
            mapped_rules.append(name)
            if known_rules and name not in known_rules:
                _add(findings, "error", "mapping_rule_exists", f"mapping rule is absent from the configured normative-rule source: {name}", rule=name, file=str(path))
        for target in parsed_targets:
            targets.append({**target, "rule_names": names, "entry": index})
        normalized.append({"index": index, "names": names, "targets": parsed_targets, "waivers": waivers})
    for name, count in Counter(mapped_rules).items():
        if count > 1:
            _add(findings, "error", "mapping_duplicate_rule", f"mapping defines rule {name!r} {count} times", rule=name, file=str(path))
    return normalized, set(mapped_rules), targets


def _scan_ctp(root: Path, suite: str, files: Any) -> dict[str, Any]:
    paths = _discover_paths(root, files, None, ["docs/ctp/src/*.adoc"])
    result = {"files": [str(path) for path in paths], "matches": [], "status": "missing"}
    if not suite:
        return result
    anchor = re.compile(rf"\[\[t-{re.escape(suite)}-coverpoints\]\]")
    includes = [
        re.compile(rf"include::norm/{re.escape(suite)}_norm_rules\.adoc\[\]"),
        re.compile(rf"include::norm/{re.escape(suite)}\.adoc\[\]"),
    ]
    for path in paths:
        try:
            text = _read_text(path)
        except AssetCheckError:
            continue
        if anchor.search(text) or any(pattern.search(text) for pattern in includes):
            result["matches"].append(
                {
                    "file": str(path),
                    "anchor": bool(anchor.search(text)),
                    "norm_include": any(pattern.search(text) for pattern in includes),
                }
            )
    result["status"] = "present" if result["matches"] else "missing"
    return result


def _check_generated_ctp_norm_table(
    root: Path,
    suite: str,
    findings: list[dict[str, Any]],
) -> Path | None:
    if not suite:
        return None
    path = root / "docs/ctp/build/generated/norm" / f"{suite}_norm_rules.adoc"
    if not path.is_file():
        _add(
            findings,
            "error",
            "ctp_norm_table_exists",
            f"generated CTP normative-rule table is missing: {_relative(path, root)}",
            file=str(path),
        )
        return None
    try:
        text = _read_text(path)
    except AssetCheckError as exc:
        _add(findings, "error", "ctp_norm_table_read", str(exc), file=str(path))
        return None
    if f"[[t-{suite}-normative-rules]]" not in text:
        _add(
            findings,
            "error",
            "ctp_norm_table_anchor",
            f"generated CTP normative-rule table has no suite anchor for {suite}",
            file=str(path),
        )
    return path


def _format_report_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# ACT4 Asset Consistency Report",
        "",
        f"- Suite: `{report.get('suite') or '(manifest-only)'}`",
        f"- Checker type: `{report.get('checker_type', 'all')}`",
        f"- Status: `{report.get('status')}`",
        f"- Errors: {summary.get('errors', 0)}",
        f"- Warnings: {summary.get('warnings', 0)}",
        "",
        "## Checks",
        "",
    ]
    for key, value in (report.get("checks") or {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Findings", ""])
    findings = report.get("findings") or []
    if not findings:
        lines.append("No findings.")
    else:
        for item in findings:
            location = ""
            if item.get("file"):
                location = f" (`{item['file']}`"
                if item.get("line"):
                    location += f":{item['line']}"
                location += ")"
            lines.append(f"- **{item.get('severity')} / {item.get('check')}**: {item.get('message')}{location}")
    lines.extend(
        [
            "",
            "## Static limitations",
            "",
            "- SystemVerilog preprocessing and simulator coverage databases are not executed.",
            "- Dynamic generator expressions are reported as warnings unless their literals are visible.",
            "- Semantic equivalence between Sheet prose and RTL expressions still requires review.",
            "",
        ]
    )
    return "\n".join(lines)


def run_asset_checks(
    *,
    suite: str = "",
    act4_root: str | Path = ".",
    mapping: str | Path | None = None,
    sheet_csv: str | Path | None = None,
    normative_metadata: str | Path | None = None,
    coverage_files: Any = None,
    coverage_patterns: Any = None,
    generator_files: Any = None,
    generator_patterns: Any = None,
    ctp_files: Any = None,
    assets: Any = None,
    manifest: str | Path | dict[str, Any] | None = None,
    inventory: str | Path | None = None,
    asset_plan: str | Path | None = None,
    completeness: str = "none",
    checker_type: str = "all",
    check_format: bool = True,
    check_consistency: bool = True,
    require_norm_metadata: bool = False,
    require_ctp: bool = False,
    exact_sheet_coverpoints: bool = False,
    exact_sheet_rules: bool = False,
    coverage_comparison_mode: str = "all",
    coverage_symbol_kinds: Any = None,
    compare_source_mapping: bool = True,
    strict_ownership: bool = False,
    require_suite_group: bool = False,
    require_ctp_norm_table: bool = False,
    allow_cross_suite_groups: Any = None,
    fail_on_warning: bool = False,
    require_generator_mapping_coverage: bool = False,
    generator_scope_contract: str | Path | None = None,
    require_scoped_generator_targets: bool = False,
    require_priv_testchunk_api: bool = False,
    require_generator_auto_split: bool = False,
    require_standalone_generator: bool = False,
    require_priv_coverage_semantics: bool = False,
    coverage_intent_contract: str | Path | None = None,
    max_findings: int = 500,
) -> dict[str, Any]:
    """Run all configured checks and return a JSON-serializable report."""
    root = Path(act4_root).expanduser().resolve()
    if not root.is_dir():
        raise AssetCheckError(f"ACT4 root is not a directory: {root}")

    config: dict[str, Any] = {}
    if manifest:
        if isinstance(manifest, dict):
            config = dict(manifest)
        else:
            config = _load_manifest(_resolve_input(root, str(manifest)))
    suite = str(config.get("suite", suite) or "").strip()
    mapping = config.get("mapping", mapping)
    sheet_csv = config.get("sheet_csv", sheet_csv)
    normative_metadata = config.get("normative_metadata", normative_metadata)
    coverage_files = config.get("coverage_files", coverage_files)
    coverage_patterns = config.get("coverage_patterns", coverage_patterns)
    generator_files = config.get("generator_files", generator_files)
    generator_patterns = config.get("generator_patterns", generator_patterns)
    ctp_files = config.get("ctp_files", ctp_files)
    assets = config.get("assets", assets)
    inventory = config.get("inventory", inventory)
    asset_plan = config.get("asset_plan", asset_plan)
    completeness = str(config.get("completeness", completeness) or "none").strip().lower()
    checker_type = str(config.get("checker_type", checker_type) or "all").strip().lower()
    require_norm_metadata = bool(
        config.get("require_norm_metadata", require_norm_metadata)
    )
    require_ctp = bool(config.get("require_ctp", require_ctp))
    require_ctp_norm_table = bool(config.get("require_ctp_norm_table", require_ctp_norm_table))
    check_format = bool(config.get("check_format", check_format))
    check_consistency = bool(config.get("check_consistency", check_consistency))
    exact_sheet_coverpoints = bool(config.get("exact_sheet_coverpoints", exact_sheet_coverpoints))
    exact_sheet_rules = bool(config.get("exact_sheet_rules", exact_sheet_rules))
    coverage_comparison_mode = str(
        config.get("coverage_comparison_mode", coverage_comparison_mode)
    ).strip().lower()
    coverage_symbol_kinds = _string_list(config.get("coverage_symbol_kinds", coverage_symbol_kinds))
    compare_source_mapping = bool(config.get("compare_source_mapping", compare_source_mapping))
    strict_ownership = bool(config.get("strict_ownership", strict_ownership))
    require_suite_group = bool(config.get("require_suite_group", require_suite_group))
    allow_cross_suite_groups = _string_list(config.get("allow_cross_suite_groups", allow_cross_suite_groups))
    fail_on_warning = bool(config.get("fail_on_warning", fail_on_warning))
    require_generator_mapping_coverage = bool(
        config.get(
            "require_generator_mapping_coverage", require_generator_mapping_coverage
        )
    )
    generator_scope_contract = config.get(
        "generator_scope_contract", generator_scope_contract
    )
    require_scoped_generator_targets = bool(
        config.get(
            "require_scoped_generator_targets", require_scoped_generator_targets
        )
    )
    require_priv_testchunk_api = bool(
        config.get("require_priv_testchunk_api", require_priv_testchunk_api)
    )
    require_generator_auto_split = bool(
        config.get("require_generator_auto_split", require_generator_auto_split)
    )
    require_standalone_generator = bool(
        config.get("require_standalone_generator", require_standalone_generator)
    )
    require_priv_coverage_semantics = bool(
        config.get("require_priv_coverage_semantics", require_priv_coverage_semantics)
    )
    coverage_intent_contract = config.get(
        "coverage_intent_contract", coverage_intent_contract
    )
    max_findings = int(config.get("max_findings", max_findings))
    if completeness not in {"none", "source", "full"}:
        raise AssetCheckError("completeness must be one of: none, source, full")
    if coverage_comparison_mode not in {"all", "mapping_targets"}:
        raise AssetCheckError("coverage_comparison_mode must be one of: all, mapping_targets")
    if checker_type not in CHECKER_PROFILES:
        raise AssetCheckError(
            f"checker_type must be one of: {', '.join(sorted(CHECKER_PROFILES))}"
        )
    if completeness != "none" and not suite:
        raise AssetCheckError("asset completeness requires --suite")
    profile = CHECKER_PROFILES[checker_type]
    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    checked_assets: list[dict[str, Any]] = []
    checks["checker_type"] = checker_type
    priv_testcase_limit = _read_priv_testcase_limit(
        root,
        findings,
        required=require_generator_auto_split,
    )
    checks["act4_testcases_per_priv_file"] = priv_testcase_limit
    (
        contract_required_targets,
        contract_blocked_targets,
        contract_experimental_targets,
    ) = _load_generator_target_scope(
        root,
        generator_scope_contract,
        require_scoped_generator_targets,
        findings,
    )

    completeness_result = _check_asset_plan_completeness(
        root,
        suite,
        inventory,
        asset_plan,
        completeness,
        profile["asset_kinds"],
        findings,
        checks,
    ) if completeness != "none" else {"mode": "none"}

    for spec in _listify(assets):
        if isinstance(spec, str):
            spec = {"path": spec}
        if not isinstance(spec, dict):
            _add(findings, "error", "asset_manifest", "asset entry must be a path or object")
            continue
        _check_generic_asset(root, spec, findings, checked_assets)
    checks["generic_assets"] = len(checked_assets)

    norm_metadata_path: Path | None = None
    known_rules: set[str] = set()
    if profile["norm"] and (require_norm_metadata or normative_metadata) and check_consistency:
        if normative_metadata:
            candidate_path = _resolve_input(root, normative_metadata)
            if candidate_path.is_file():
                norm_metadata_path = candidate_path
                try:
                    metadata_data = _load_structured(norm_metadata_path)
                    known_rules = _norm_rule_names_from_defs(
                        metadata_data, findings, norm_metadata_path
                    )
                except AssetCheckError as exc:
                    _add(
                        findings,
                        "error",
                        "norm_parse",
                        str(exc),
                        file=str(norm_metadata_path),
                    )
            elif require_norm_metadata:
                _add(
                    findings,
                    "error",
                    "norm_metadata_exists",
                    "canonical normative-rule metadata YAML is required",
                    file=str(candidate_path),
                )
        elif require_norm_metadata:
            _add(
                findings,
                "error",
                "norm_metadata_exists",
                "canonical normative-rule metadata YAML is required",
            )
    checks["normative_metadata"] = (
        str(norm_metadata_path) if norm_metadata_path else None
    )

    mapping_path: Path | None = None
    mapping_entries: list[dict[str, Any]] = []
    mapping_rules: set[str] = set()
    mapping_targets: list[dict[str, Any]] = []
    if profile["mapping"] and check_consistency and (mapping or suite):
        mapping_path = _resolve_input(root, mapping or f"coverpoints/norm/{suite}.yaml")
        if not mapping_path.is_file():
            _add(findings, "error", "mapping_exists", f"mapping file is missing: {_relative(mapping_path, root)}", file=str(mapping_path))
        else:
            try:
                mapping_data = _load_structured(mapping_path)
                mapping_entries, mapping_rules, mapping_targets = _mapping_entries(
                    mapping_data,
                    known_rules,
                    findings,
                    mapping_path,
                )
            except AssetCheckError as exc:
                _add(findings, "error", "mapping_parse", str(exc), file=str(mapping_path))

    source_mapping_path = root / "coverpoints/norm" / f"{suite}.yaml" if suite else None
    if (
        profile["mapping"]
        and compare_source_mapping
        and mapping_path
        and mapping_path.is_file()
        and source_mapping_path
        and source_mapping_path.is_file()
        and mapping_path.resolve() != source_mapping_path.resolve()
    ):
        try:
            source_data = _load_structured(source_mapping_path)
            source_findings: list[dict[str, Any]] = []
            source_entries, _, _ = _mapping_entries(
                source_data,
                known_rules,
                source_findings,
                source_mapping_path,
            )
            findings.extend(source_findings)

            def canonical(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
                result: defaultdict[str, list[str]] = defaultdict(list)
                for entry in entries:
                    values = [
                        "/".join(
                            part
                            for part in (
                                str(target.get("covergroup") or ""),
                                str(target.get("coverpoint") or ""),
                                str(target.get("bin") or ""),
                            )
                            if part
                        )
                        for target in entry.get("targets", [])
                    ]
                    values.extend(f"WAIVER:{item}" for item in entry.get("waivers", []))
                    for name in entry.get("names", []):
                        result[str(name)].extend(values)
                return {name: sorted(set(values)) for name, values in sorted(result.items())}

            staged_map = canonical(mapping_entries)
            source_map = canonical(source_entries)
            if staged_map != source_map:
                changed_rules = sorted(
                    name
                    for name in set(staged_map) | set(source_map)
                    if staged_map.get(name) != source_map.get(name)
                )
                _add(
                    findings,
                    "error",
                    "source_mapping_mismatch",
                    f"staged mapping differs from source mapping for {len(changed_rules)} rules",
                    staged=str(mapping_path),
                    source=str(source_mapping_path),
                    changed_rules=changed_rules,
                )
        except AssetCheckError as exc:
            _add(findings, "error", "source_mapping_parse", str(exc), file=str(source_mapping_path))

    sheet: dict[str, Any] = {"coverpoints": {}, "rules": set(), "rows": []}
    sheet_path: Path | None = None
    if profile["sheet"] and check_consistency and sheet_csv:
        sheet_path = _resolve_input(root, sheet_csv)
        if not sheet_path.is_file():
            _add(findings, "error", "sheet_exists", f"canonical Sheet CSV is missing: {_relative(sheet_path, root)}", file=str(sheet_path))
        else:
            sheet = parse_canonical_sheet(sheet_path, findings)
    elif profile["sheet"] and check_consistency and suite and config.get("require_sheet", False):
        _add(findings, "error", "sheet_exists", "canonical Sheet CSV is required but was not provided")

    coverage_paths = (
        _discover_paths(
            root,
            coverage_files,
            coverage_patterns,
            ["coverpoints/unpriv/*_coverage*.svh", "coverpoints/priv/*_coverage*.svh"],
        )
        if profile["coverage"]
        else []
    )
    coverage = (
        scan_systemverilog(coverage_paths, findings)
        if profile["coverage"] and (check_format or check_consistency)
        else {"files": [], "groups": {}}
    )
    if require_priv_coverage_semantics:
        _validate_priv_coverage_semantics(coverage, findings)
    coverage_intent_summary: dict[str, Any] | None = None
    if coverage_intent_contract:
        coverage_intent_summary = _validate_coverage_intent(
            coverage,
            _resolve_input(root, str(coverage_intent_contract)),
            suite,
            findings,
        )
    checks["coverage_files"] = len(coverage.get("files", []))
    checks["coverage_groups"] = len(coverage.get("groups", {}))
    checks["coverage_symbols"] = sum(len(item.get("coverpoints", [])) for item in coverage.get("groups", {}).values())
    checks["priv_coverage_semantics_required"] = require_priv_coverage_semantics
    checks["coverage_intent"] = coverage_intent_summary

    expected_group = f"{suite}_cg" if suite else ""
    if profile["suite_group"] and require_suite_group and check_consistency and suite and expected_group not in coverage.get("groups", {}):
        _add(findings, "error", "suite_covergroup_exists", f"suite covergroup is missing: {expected_group}")

    # Mapping -> coverage and ownership checks.
    for target in (mapping_targets if profile["mapping"] else []):
        group = target.get("covergroup")
        cp = target.get("coverpoint")
        rule_names = target.get("rule_names", [])
        if group is None:
            matches = [
                group_name
                for group_name, group_data in coverage.get("groups", {}).items()
                if cp in group_data.get("coverpoints", [])
            ]
            if not matches:
                _add(
                    findings,
                    "error",
                    "mapping_coverpoint_exists",
                    f"coverage symbol does not exist: {cp}",
                    target=target.get("raw"),
                    rule_names=rule_names,
                )
                continue
            severity = "error" if strict_ownership else "warning"
            _add(
                findings,
                severity,
                "mapping_qualified_target",
                f"mapping target is not qualified: {target.get('raw')!r}; found in {matches}",
                target=target.get("raw"),
                rule_names=rule_names,
                matching_groups=matches,
            )
            continue
        resolved_group = group
        suite_owned = bool(suite and (resolved_group == expected_group or resolved_group.startswith(f"{suite}_")))
        if strict_ownership and expected_group and not suite_owned and resolved_group not in allow_cross_suite_groups:
            _add(findings, "error", "mapping_suite_ownership", f"mapping target belongs to {group}, expected a {suite}_* covergroup", target=target.get("raw"), rule_names=rule_names)
        group_data = coverage.get("groups", {}).get(resolved_group)
        if group_data is None:
            _add(findings, "error", "mapping_group_exists", f"coverage group does not exist: {group}", target=target.get("raw"), rule_names=rule_names)
            continue
        if cp not in group_data.get("coverpoints", []):
            _add(findings, "error", "mapping_coverpoint_exists", f"coverage symbol does not exist: {resolved_group}/{cp}", target=target.get("raw"), rule_names=rule_names)
            continue
        bin_name = target.get("bin")
        if bin_name:
            bins = group_data.get("bins", {}).get(cp, [])
            if bin_name not in bins:
                cp_kind = (group_data.get("coverpoint_details", {}).get(cp) or {}).get("kind")
                severity = "warning" if cp_kind == "cross" or not bins else "error"
                check = "mapping_bin_unverified" if severity == "warning" else "mapping_bin_exists"
                _add(
                    findings,
                    severity,
                    check,
                    f"coverage bin {'cannot be proven statically' if severity == 'warning' else 'does not exist'}: {resolved_group}/{cp}/{bin_name}",
                    target=target.get("raw"),
                    rule_names=rule_names,
                )

    # Sheet -> coverage and bidirectional rule/cp comparisons.
    sheet_cps = set(sheet.get("coverpoints", {}))
    sheet_rules = set(sheet.get("rules", set()))
    if coverage_comparison_mode == "mapping_targets" and mapping_targets:
        suite_cps = {str(target.get("coverpoint")) for target in mapping_targets if target.get("coverpoint")}
    elif expected_group and expected_group in coverage.get("groups", {}) and require_suite_group:
        suite_group = coverage["groups"][expected_group]
        if coverage_symbol_kinds:
            suite_cps = {
                name
                for name in suite_group.get("coverpoints", [])
                if (suite_group.get("coverpoint_details", {}).get(name) or {}).get("kind")
                in set(coverage_symbol_kinds)
            }
        else:
            suite_cps = set(suite_group.get("coverpoints", []))
    elif not require_suite_group:
        suite_cps = set()
        if coverage_comparison_mode == "mapping_targets":
            suite_cps = {
                str(target.get("coverpoint"))
                for target in mapping_targets
                if target.get("coverpoint")
            }
        else:
            for group_data in coverage.get("groups", {}).values():
                if coverage_symbol_kinds:
                    suite_cps.update(
                        name
                        for name in group_data.get("coverpoints", [])
                        if (group_data.get("coverpoint_details", {}).get(name) or {}).get("kind")
                        in set(coverage_symbol_kinds)
                    )
                else:
                    suite_cps.update(group_data.get("coverpoints", []))
    else:
        suite_cps = set()
    if profile["mapping"] and profile["coverage"] and sheet_path:
        for cp in sorted(sheet_cps - suite_cps):
            _add(findings, "error", "sheet_coverpoint_exists", f"Sheet coverpoint is absent from {expected_group}: {cp}", coverpoint=cp)
        extras = sorted(suite_cps - sheet_cps)
        if extras:
            severity = "error" if exact_sheet_coverpoints else "warning"
            _add(
                findings,
                severity,
                "coverage_extra_coverpoints",
                f"coverage has {len(extras)} comparison symbols not named by Sheet",
                coverpoints=extras[:100],
                omitted=max(0, len(extras) - 100),
                kinds=coverage_symbol_kinds or ["coverpoint", "cross"],
            )
        if sheet_rules - mapping_rules:
            _add(findings, "error", "sheet_rule_missing_mapping", f"Sheet rules absent from mapping: {sorted(sheet_rules - mapping_rules)}")
        if exact_sheet_rules and mapping_rules - sheet_rules:
            _add(findings, "error", "mapping_extra_rule", f"mapping rules absent from Sheet: {sorted(mapping_rules - sheet_rules)}")
    checks["sheet_coverpoints"] = len(sheet_cps)
    checks["sheet_rules"] = len(sheet_rules)
    checks["mapping_rules"] = len(mapping_rules)
    checks["mapping_targets"] = len(mapping_targets)
    checks["coverage_comparison_symbols"] = len(suite_cps)
    checks["coverage_comparison_kinds"] = coverage_symbol_kinds or ["coverpoint", "cross"]

    # Generator checks.  Literal strings are used as a conservative fallback
    # for loops/helpers that an AST-only symbol resolver cannot evaluate.
    generator_paths = (
        _discover_paths(root, generator_files, generator_patterns, [])
        if profile["generator"]
        else []
    )
    generator_results: list[dict[str, Any]] = []
    generator_cps: set[str] = set()
    generator_literal_cps: set[str] = set()
    if generator_paths:
        for path in generator_paths:
            result = scan_python_generator(path, findings)
            generator_results.append(result)
            if require_standalone_generator and result.get("workspace_dependencies"):
                _add(
                    findings, "error", "generator_workspace_dependency",
                    "ACT4 generator imports or probes ITGen workspace assets; keep contract/review checks in ITGen",
                    file=str(path), dependencies=result["workspace_dependencies"],
                )
            _validate_priv_generator_api(
                result,
                suite,
                findings,
                require_testchunk_api=require_priv_testchunk_api,
                require_auto_split=require_generator_auto_split,
                max_testcases_per_file=priv_testcase_limit,
            )
            for record in result.get("testcases", []):
                if record.get("coverpoint"):
                    generator_cps.add(str(record["coverpoint"]))
            # Literal constants are useful diagnostic hints, but never prove a
            # testcase relationship in strict mode: a coverpoint name can occur
            # in a tuple, comment, or helper declaration without an
            # `add_testcase()` call.
            literal_strings = set(result.get("literal_strings", []))
            for cp in suite_cps:
                if cp in literal_strings:
                    generator_literal_cps.add(cp)
                    if not require_generator_mapping_coverage:
                        generator_cps.add(cp)
            if check_consistency and suite and suite not in set(result.get("registrations", [])):
                # A generator may be a helper rather than the suite registry;
                # only report this when its filename clearly belongs to suite.
                if suite.lower() in path.stem.lower():
                    _add(findings, "error", "generator_registration", f"generator is not registered for {suite}", file=str(path))
            if not result.get("testcases") and result.get("dynamic"):
                _add(findings, "warning", "generator_dynamic_reference", "generator testcase references cannot be resolved statically", file=str(path), count=len(result["dynamic"]))
    required_generator_cps = set(mapping_targets and suite_cps or sheet_cps)
    if generator_paths:
        missing_generator_cps = sorted(required_generator_cps - generator_cps)
        for cp in missing_generator_cps:
            contract_blocked = cp in contract_blocked_targets and cp not in contract_required_targets
            contract_experimental = cp in contract_experimental_targets
            dynamic_evidence = cp in generator_literal_cps
            severity = (
                "error"
                if require_generator_mapping_coverage
                and not contract_blocked
                and not contract_experimental
                and not dynamic_evidence
                else "warning"
            )
            if contract_blocked:
                check = "generator_contract_blocked"
                message = f"generator omits contract-blocked mapped coverpoint: {cp}"
            elif contract_experimental:
                check = "generator_contract_experimental"
                message = f"main generator omits isolated experimental coverpoint: {cp}"
            elif dynamic_evidence:
                check = "generator_dynamic_mapping_link"
                message = f"generator only has dynamic/literal evidence for mapped coverpoint: {cp}; AI or generated-source review is required"
            else:
                check = "generator_mapping_link"
                message = f"generator has no statically visible testcase reference to mapped coverpoint: {cp}"
            _add(findings, severity, check, message, coverpoint=cp)
        checks["generator_coverpoints"] = len(generator_cps)
        checks["generator_required_coverpoints"] = len(required_generator_cps)
        checks["generator_missing_coverpoints"] = missing_generator_cps
        checks["generator_dynamic_coverpoints"] = sorted(
            set(missing_generator_cps) & generator_literal_cps
        )
        checks["generator_contract_required_coverpoints"] = sorted(contract_required_targets)
        checks["generator_contract_blocked_coverpoints"] = sorted(contract_blocked_targets)
        checks["generator_contract_experimental_coverpoints"] = sorted(
            contract_experimental_targets
        )
    elif require_generator_mapping_coverage and required_generator_cps:
        _add(findings, "error", "generator_exists", "mapped coverpoint coverage requires a registered generator file")
    checks["generator_files"] = len(generator_paths)
    checks["generator_testcases"] = sum(
        len(item.get("testcases", [])) for item in generator_results
    )
    checks["priv_generator_entries"] = sum(
        len(item.get("priv_generators", [])) for item in generator_results
    )
    checks["priv_testchunk_api_required"] = require_priv_testchunk_api
    checks["generator_auto_split_required"] = require_generator_auto_split
    checks["standalone_generator_required"] = require_standalone_generator

    ctp = (
        _scan_ctp(root, suite, ctp_files)
        if profile["ctp"] and check_consistency and suite
        else {"status": "not_requested", "files": [], "matches": []}
    )
    ctp_norm_table: Path | None = None
    checks["ctp_status"] = ctp.get("status")
    if profile["ctp"] and require_ctp and check_consistency and suite:
        if ctp.get("status") != "present":
            _add(findings, "error", "ctp_entry_exists", f"no CTP anchor/include found for {suite}")
        else:
            if not any(item.get("anchor") for item in ctp.get("matches", [])):
                _add(findings, "error", "ctp_anchor", f"CTP has no [[t-{suite}-coverpoints]] anchor")
            if mapping_path and not any(item.get("norm_include") for item in ctp.get("matches", [])):
                _add(findings, "error", "ctp_norm_include", f"CTP has no norm include for {suite}")
    if profile["ctp"] and require_ctp_norm_table and check_consistency and suite:
        ctp_norm_table = _check_generated_ctp_norm_table(root, suite, findings)

    # Limit report size while preserving a deterministic truncation finding.
    total_before = len(findings)
    if len(findings) > max_findings:
        omitted = len(findings) - max_findings
        findings = findings[:max_findings]
        _add(findings, "error", "report_truncated", f"report truncated; {omitted} findings omitted", omitted=omitted)
    errors = sum(item.get("severity") == "error" for item in findings)
    warnings = sum(item.get("severity") == "warning" for item in findings)
    status = "failed" if errors or (fail_on_warning and warnings) else ("review_required" if warnings else "complete")
    coverage_file_list = list(coverage.get("files", []))
    suite_group_data = coverage.get("groups", {}).get(expected_group) if expected_group else None
    compact_generators = [
        {
            "file": item.get("file"),
            "syntax_ok": item.get("syntax_ok", False),
            "registrations": item.get("registrations", []),
            "testcase_count": len(item.get("testcases", [])),
            "dynamic_reference_count": len(item.get("dynamic", [])),
        }
        for item in generator_results
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "act4_root": str(root),
        "checker_type": checker_type,
        "status": status,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "findings_before_truncation": total_before,
        },
        "checks": checks,
        "mapping": str(mapping_path) if mapping_path else None,
        "sheet_csv": str(sheet_path) if sheet_path else None,
        "normative_metadata": (
            str(norm_metadata_path) if norm_metadata_path else None
        ),
        "completeness": completeness_result,
        "coverage": {
            "file_count": len(coverage_file_list),
            "files": coverage_file_list[:200],
            "files_omitted": max(0, len(coverage_file_list) - 200),
            "group_count": checks["coverage_groups"],
            "symbol_count": checks["coverage_symbols"],
            "suite_group": suite_group_data,
            "comparison_kinds": coverage_symbol_kinds,
        },
        "generators": compact_generators,
        "ctp": ctp,
        "ctp_norm_table": str(ctp_norm_table) if ctp_norm_table else None,
        "assets": checked_assets,
        "findings": findings,
        "static_limitations": [
            "SystemVerilog preprocessing and simulator coverage databases are not executed.",
            "Dynamic generator expressions may remain warnings.",
            "Sheet prose to RTL semantic equivalence requires review.",
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check ACT4 assets, formats, and cross-asset consistency")
    parser.add_argument("--suite", default="")
    parser.add_argument("--act4-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--sheet-csv", type=Path)
    parser.add_argument("--normative-metadata", type=Path)
    parser.add_argument("--inventory", type=Path, help="suite_inventory.json used to confirm plan ownership")
    parser.add_argument("--asset-plan", type=Path, help="asset_plan.json used for required asset completeness")
    parser.add_argument(
        "--checker-type",
        choices=sorted(CHECKER_PROFILES),
        default="all",
        help="asset-plan kind profile; all keeps the full canonical ACT4 gate",
    )
    parser.add_argument(
        "--completeness",
        choices=["source", "full"],
        default="source",
        help="source checks required source assets; full also checks generated and validation assets",
    )
    parser.add_argument("--coverage-file", action="append", default=[])
    parser.add_argument(
        "--coverage-symbol-kind",
        action="append",
        default=[],
        choices=["coverpoint", "cross"],
        help="coverage symbol kinds used for Sheet/generator comparisons",
    )
    parser.add_argument("--coverage-pattern", action="append", default=[])
    parser.add_argument("--generator", action="append", default=[])
    parser.add_argument("--generator-pattern", action="append", default=[])
    parser.add_argument("--require-priv-testchunk-api", action="store_true")
    parser.add_argument("--require-generator-auto-split", action="store_true")
    parser.add_argument("--require-standalone-generator", action="store_true")
    parser.add_argument("--ctp-file", action="append", default=[])
    parser.add_argument("--asset", action="append", default=[], help="Generic asset path; use --manifest for schema/hash rules")
    parser.add_argument("--require-norm-metadata", action="store_true")
    parser.add_argument("--no-require-ctp", action="store_true")
    parser.add_argument("--exact-sheet-coverpoints", action="store_true")
    parser.add_argument(
        "--coverage-comparison-mode",
        choices=["all", "mapping_targets"],
        default="all",
    )
    parser.add_argument("--allow-extra-sheet-rules", action="store_true")
    parser.add_argument("--no-compare-source-mapping", action="store_true")
    parser.add_argument("--allow-cross-suite-group", action="append", default=[])
    parser.add_argument("--no-strict-ownership", action="store_true")
    parser.add_argument("--no-require-suite-group", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--stdout", action="store_true")
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = run_asset_checks(
            suite=args.suite,
            act4_root=args.act4_root,
            mapping=args.mapping,
            sheet_csv=args.sheet_csv,
            normative_metadata=args.normative_metadata,
            inventory=args.inventory,
            asset_plan=args.asset_plan,
            completeness=args.completeness if args.asset_plan else "none",
            checker_type=args.checker_type,
            coverage_files=args.coverage_file,
            coverage_symbol_kinds=args.coverage_symbol_kind,
            coverage_patterns=args.coverage_pattern,
            generator_files=args.generator,
            generator_patterns=args.generator_pattern,
            require_priv_testchunk_api=args.require_priv_testchunk_api,
            require_generator_auto_split=args.require_generator_auto_split,
            require_standalone_generator=args.require_standalone_generator,
            ctp_files=args.ctp_file,
            assets=args.asset,
            manifest=args.manifest,
            require_norm_metadata=args.require_norm_metadata,
            require_ctp=not args.no_require_ctp,
            exact_sheet_coverpoints=args.exact_sheet_coverpoints,
            coverage_comparison_mode=args.coverage_comparison_mode,
            exact_sheet_rules=not args.allow_extra_sheet_rules,
            compare_source_mapping=not args.no_compare_source_mapping,
            strict_ownership=not args.no_strict_ownership,
            require_suite_group=not args.no_require_suite_group,
            allow_cross_suite_groups=args.allow_cross_suite_group,
            fail_on_warning=args.fail_on_warning,
        )
    except AssetCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output_dir = (args.output_dir or Path(os.environ.get("OUT", "output")) / "act4_asset_check").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.suite or 'manifest'}.asset-consistency.json"
    md_path = output_dir / f"{args.suite or 'manifest'}.asset-consistency.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_format_report_markdown(report), encoding="utf-8")
    if args.stdout:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {report['status']}")
        print(f"Errors: {report['summary']['errors']}; warnings: {report['summary']['warnings']}")
        print(f"JSON: {json_path}")
        print(f"Markdown: {md_path}")
    if report["summary"]["errors"] or (args.fail_on_warning and report["summary"]["warnings"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
