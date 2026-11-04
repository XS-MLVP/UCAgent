"""Atomically replace one canonical Spec line-map block from structured items."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any

from ucagent.util.config import load_runtime_config


_TAG = r"[A-Za-z0-9._-]+"
_FUNCTION_PATH = re.compile(rf"^FG-{_TAG}/FC-{_TAG}/CK-{_TAG}$")
_IGNORE_PATH = re.compile(rf"^IGNORE/FC-{_TAG}/CK-{_TAG}$")
_ENTRY_PATTERN = re.compile(
    rf"^(?P<target>(?:FG-{_TAG}|IGNORE)/FC-{_TAG}/CK-{_TAG}):\s*"
    r"(?P<ranges>[0-9]+-[0-9]+(?:\s*,\s*[0-9]+-[0-9]+)*)"
    r"(?:\s*#\s*(?P<reason>.+))?$"
)


def _parse_args() -> argparse.Namespace:
    """Parse the exact current line block and its structured mappings."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-SOURCE", required=True)
    parser.add_argument("-START", required=True, type=int)
    parser.add_argument("-END", required=True, type=int)
    parser.add_argument("-MAP-FILE", required=True)
    parser.add_argument("-ITEMS", required=True)
    return parser.parse_args()


def _inside(workspace: Path, value: str, boundary: Path, *, must_exist: bool = False) -> Path:
    """Resolve one path and require it to remain below a trusted boundary."""

    raw = Path(value)
    if raw.is_absolute():
        raise ValueError(f"Path must be workspace-relative: {value}")
    candidate = (workspace / raw).resolve()
    if not candidate.is_relative_to(boundary.resolve()):
        raise ValueError(f"Path escapes the permitted boundary: {value}")
    if must_exist and (not candidate.is_file() or candidate.is_symlink()):
        raise FileNotFoundError(f"Required regular file is missing or unsafe: {value}")
    return candidate


def _parse_contract(path: Path) -> set[str]:
    """Return all canonical sequential FG/FC/CK paths from the contract."""

    marker = re.compile(rf"^\s*<(FG|FC|CK)-({_TAG})>\s*$")
    current_fg: str | None = None
    current_fc: str | None = None
    result: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = marker.fullmatch(line)
        if match is None:
            continue
        kind, suffix = match.groups()
        tag = f"{kind}-{suffix}"
        if kind == "FG":
            current_fg = tag
            current_fc = None
        elif kind == "FC":
            if current_fg is None:
                raise ValueError(f"FC without FG at {path}:{line_number}")
            current_fc = tag
        else:
            if current_fg is None or current_fc is None:
                raise ValueError(f"CK without FG/FC at {path}:{line_number}")
            result.add(f"{current_fg}/{current_fc}/{tag}")
    if not result:
        raise ValueError(f"Functional contract has no CK paths: {path}")
    return result


def _parse_ranges(value: Any, index: int) -> list[tuple[int, int]]:
    """Validate one item's inclusive integer range list."""

    if not isinstance(value, list) or not value or len(value) > 100:
        raise ValueError(f"ITEMS[{index}].ranges must be a non-empty list of at most 100 pairs")
    result: list[tuple[int, int]] = []
    for range_index, item in enumerate(value):
        if (
            not isinstance(item, list)
            or len(item) != 2
            or type(item[0]) is not int
            or type(item[1]) is not int
        ):
            raise ValueError(f"ITEMS[{index}].ranges[{range_index}] must be [integer, integer]")
        start, end = item
        if start < 1 or end < start:
            raise ValueError(f"ITEMS[{index}].ranges[{range_index}] is invalid: {item}")
        result.append((start, end))
    return result


def _load_items(
    raw: str,
    known_paths: set[str],
    block_start: int,
    block_end: int,
    source_lines: list[str],
) -> list[tuple[str, list[tuple[int, int]], str | None]]:
    """Decode mappings and prove they exactly cover current nonblank source lines."""

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"-ITEMS must be valid JSON: {exc}") from exc
    if not isinstance(value, list) or not value or len(value) > 200:
        raise ValueError("-ITEMS must be a non-empty JSON list of at most 200 mappings")
    result: list[tuple[str, list[tuple[int, int]], str | None]] = []
    covered: set[int] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"ITEMS[{index}] must be an object")
        target = item.get("target")
        if not isinstance(target, str):
            raise ValueError(f"ITEMS[{index}].target must be a string")
        is_ignore = _IGNORE_PATH.fullmatch(target) is not None
        allowed_keys = {"target", "ranges", "reason"} if is_ignore else {"target", "ranges"}
        if set(item) != allowed_keys:
            raise ValueError(f"ITEMS[{index}] must contain exactly {sorted(allowed_keys)}")
        if not is_ignore:
            if _FUNCTION_PATH.fullmatch(target) is None:
                raise ValueError(f"ITEMS[{index}].target is not canonical: {target}")
            if target not in known_paths:
                raise ValueError(f"ITEMS[{index}].target is not declared in the functional contract: {target}")
        reason = item.get("reason")
        if is_ignore and (not isinstance(reason, str) or len(reason.strip()) < 12):
            raise ValueError(f"ITEMS[{index}].reason must concretely explain the non-functional content")
        ranges = _parse_ranges(item.get("ranges"), index)
        for start, end in ranges:
            if start < block_start or end > block_end:
                raise ValueError(
                    f"ITEMS[{index}] range {start}-{end} escapes current block {block_start}-{block_end}"
                )
            if end > len(source_lines):
                raise ValueError(f"ITEMS[{index}] range {start}-{end} exceeds source length {len(source_lines)}")
            covered.update(range(start, end + 1))
        result.append((target, ranges, reason.strip() if isinstance(reason, str) else None))
    required = {
        line_number
        for line_number in range(block_start, block_end + 1)
        if source_lines[line_number - 1].strip()
    }
    missing = sorted(required - covered)
    if missing:
        raise ValueError(f"Mappings do not cover current nonblank physical lines: {missing[:50]}")
    return result


def _entry_ranges(line: str, line_number: int) -> list[tuple[int, int]]:
    """Parse one existing canonical map entry's ranges."""

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return []
    match = _ENTRY_PATTERN.fullmatch(stripped)
    if match is None:
        raise ValueError(f"Existing mapping line {line_number} is not canonical: {stripped}")
    return [
        tuple(int(value) for value in item.split("-", 1))
        for item in match.group("ranges").split(",")
    ]


def main() -> None:
    """Replace the requested block and print a bounded integrity summary."""

    args = _parse_args()
    workspace = Path(os.getcwd()).resolve()
    runtime = load_runtime_config(str(workspace))
    output = _inside(workspace, runtime["OUT"], workspace)
    spec_root = _inside(workspace, f"{runtime['DUT']}/spec", workspace)
    source = _inside(workspace, args.SOURCE, spec_root, must_exist=True)
    contract = output / f"{runtime['DUT']}_functions_and_checks.md"
    if not contract.is_file() or contract.is_symlink():
        raise FileNotFoundError(f"Functional contract is missing or unsafe: {contract}")
    if args.START < 1 or args.END < args.START or args.END - args.START + 1 > 100:
        raise ValueError("Current block must satisfy 1 <= START <= END and contain at most 100 lines")
    source_lines = source.read_text(encoding="utf-8").splitlines()
    if args.END > len(source_lines):
        raise ValueError(f"Current block end {args.END} exceeds source length {len(source_lines)}")

    source_relative = source.relative_to(workspace).as_posix()
    canonical_name = source_relative.replace("/", "_").replace(".", "_") + "_line_func_map.txt"
    canonical_relative = (
        output.relative_to(workspace) / "line_map" / canonical_name
    ).as_posix()
    if Path(args.MAP_FILE).as_posix() != canonical_relative:
        raise ValueError(
            f"-MAP-FILE must be the canonical path for this source: {canonical_relative}"
        )
    map_file = _inside(workspace, args.MAP_FILE, output)
    items = _load_items(
        args.ITEMS,
        _parse_contract(contract),
        args.START,
        args.END,
        source_lines,
    )

    preserved: list[str] = []
    if map_file.exists():
        if map_file.is_symlink() or not map_file.is_file():
            raise ValueError(f"Mapping target is not a regular file: {map_file}")
        for line_number, line in enumerate(map_file.read_text(encoding="utf-8").splitlines(), 1):
            ranges = _entry_ranges(line, line_number)
            overlaps = [
                (start, end)
                for start, end in ranges
                if start <= args.END and end >= args.START
            ]
            if overlaps and (
                len(overlaps) != len(ranges)
                or any(start < args.START or end > args.END for start, end in overlaps)
            ):
                raise ValueError(
                    f"Existing mapping line {line_number} partially crosses current block: {overlaps}"
                )
            if not overlaps and line.strip() and not line.lstrip().startswith("#"):
                preserved.append(line.strip())

    generated = [
        f"{target}: {', '.join(f'{start}-{end}' for start, end in ranges)}"
        + (f" # {reason}" if reason else "")
        for target, ranges, reason in items
    ]
    content = "\n".join(
        [
            f"# Target: {source_relative}",
            f"# Canonical map_file: {canonical_relative}",
            "",
            *preserved,
            *([""] if preserved else []),
            *generated,
        ]
    )
    map_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = map_file.with_name(map_file.name + ".tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, map_file)
    print(
        json.dumps(
            {
                "source": source_relative,
                "map_file": canonical_relative,
                "replaced_block": [args.START, args.END],
                "mapping_count": len(items),
                "next_action": "Call Check for this exact line-map batch, then call CurrentTips for the next block.",
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
