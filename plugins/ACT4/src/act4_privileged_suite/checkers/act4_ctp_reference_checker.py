"""Validate online CTP discovery, suite boundaries, and normative tables."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml


from ucagent.checkers.base import Checker


CTP_URL = "https://riscv.github.io/riscv-arch-test/ctp.html"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
POSITIONAL_SOURCE_ID_RE = re.compile(
    r"^(?:(?:row|column|col|cell)[_-]?\d+(?:_|-|$)|r\d+c\d+(?:_|-|$))",
    re.IGNORECASE,
)
NORMATIVE_COLUMNS = {"normative rule", "rule text", "coverpoints"}
CANONICAL_COLUMNS = {
    "source_items",
    "coverpoint",
    "normative_rules",
    "disposition",
}


def _add(
    findings: list[dict[str, Any]],
    check: str,
    message: str,
    *,
    file: Path | None = None,
) -> None:
    finding: dict[str, Any] = {
        "severity": "error",
        "check": check,
        "message": message,
    }
    if file is not None:
        finding["file"] = str(file)
    findings.append(finding)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read YAML {path}: {exc}") from exc


class _CTPTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._table: dict[str, Any] | None = None
        self._capture: str | None = None
        self._parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "table" and self._table is None:
            self._table = {
                "id": str(attributes.get("id") or ""),
                "caption": "",
                "headers": [],
                "links": [],
            }
        elif self._table is not None and tag in {"caption", "th"}:
            self._capture = tag
            self._parts = []
        elif self._table is not None and tag == "a":
            href = str(attributes.get("href") or "").strip()
            if href:
                self._table["links"].append(href)

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._table is None:
            return
        if tag == self._capture:
            value = " ".join("".join(self._parts).split())
            if tag == "caption":
                self._table["caption"] = value
            elif value:
                self._table["headers"].append(value)
            self._capture = None
            self._parts = []
        elif tag == "table":
            self.tables.append(self._table)
            self._table = None
            self._capture = None
            self._parts = []


def _parse_table_number(caption: str, title: str) -> int | None:
    match = re.fullmatch(rf"Table\s+(\d+)\.\s+{re.escape(title)}", caption)
    return int(match.group(1)) if match else None


def _google_sheet_parts(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    match = re.fullmatch(r"/spreadsheets/d/([^/]+)/edit/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "docs.google.com" or not match:
        return None
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid_values = query.get("gid") or fragment.get("gid") or []
    if len(gid_values) != 1 or not gid_values[0].isdigit():
        return None
    return match.group(1), gid_values[0]


def _metadata_names(data: Any, findings: list[dict[str, Any]], path: Path) -> set[str]:
    definitions = data.get("normative_rule_definitions") if isinstance(data, dict) else None
    if not isinstance(definitions, list):
        _add(
            findings,
            "ctp_metadata_schema",
            "metadata must contain normative_rule_definitions",
            file=path,
        )
        return set()
    names: list[str] = []
    for index, item in enumerate(definitions):
        if not isinstance(item, dict):
            _add(
                findings,
                "ctp_metadata_schema",
                f"normative_rule_definitions[{index}] is not an object",
                file=path,
            )
            continue
        raw = item.get("names", item.get("name", []))
        values = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        item_names = [str(value).strip() for value in values if str(value).strip()]
        if not item_names:
            _add(
                findings,
                "ctp_metadata_schema",
                f"normative_rule_definitions[{index}] has no name/names",
                file=path,
            )
        names.extend(item_names)
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        _add(
            findings,
            "ctp_metadata_duplicate_rule",
            f"metadata contains duplicate rule names: {duplicates}",
            file=path,
        )
    return set(names)


def _split_rules(value: str, *, canonical: bool) -> list[str]:
    if canonical:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []
    return [item.strip() for item in re.split(r"[,;\n]+", value) if item.strip()]


def _sheet_entries(
    path: Path,
    findings: list[dict[str, Any]],
) -> dict[str, set[str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        _add(findings, "ctp_csv_read", f"cannot read CSV: {exc}", file=path)
        return {}
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if CANONICAL_COLUMNS.issubset(
                {str(value).strip() for value in row}
            )
        ),
        None,
    )
    if header_index is None:
        _add(
            findings,
            "ctp_csv_schema",
            f"canonical CSV has no header with {sorted(CANONICAL_COLUMNS)}",
            file=path,
        )
        return {}
    header_map = {
        str(value).strip(): pos for pos, value in enumerate(rows[header_index])
    }
    coverpoint_index = header_map["coverpoint"]
    rule_index = header_map["normative_rules"]
    disposition_index = header_map["disposition"]
    entries: dict[str, set[str]] = {}
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        values = row + [""] * (
            max(coverpoint_index, rule_index, disposition_index)
            + 1
            - len(row)
        )
        if values[disposition_index].strip() != "coverpoint":
            continue
        coverpoint = values[coverpoint_index].strip()
        if not IDENTIFIER_RE.fullmatch(coverpoint):
            continue
        rules = set(
            _split_rules(values[rule_index].strip(), canonical=True)
        )
        if not rules:
            _add(
                findings,
                "ctp_csv_missing_rules",
                f"optimized coverpoint {coverpoint!r} has no normative rule",
                file=path,
            )
        entries.setdefault(coverpoint, set()).update(rules)
    if not entries:
        _add(findings, "ctp_csv_empty", "CSV contains no coverpoint rows", file=path)
    return entries


def _raw_matrix(
    path: Path,
    findings: list[dict[str, Any]],
) -> list[list[str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream, strict=True))
    except (OSError, UnicodeError, csv.Error) as exc:
        _add(findings, "ctp_csv_read", f"cannot read CSV: {exc}", file=path)
        return []
    first_nonempty = next(
        (
            cell.lstrip()
            for row in rows
            for cell in row
            if cell.strip()
        ),
        "",
    )
    if first_nonempty.casefold().startswith(
        ("<!doctype html", "<html", "<!doctype")
    ):
        _add(
            findings,
            "ctp_csv_content",
            "raw Sheet export contains HTML instead of CSV data",
            file=path,
        )
        return []
    if not any(any(cell.strip() for cell in row) for row in rows):
        _add(findings, "ctp_csv_empty", "raw Sheet CSV is empty", file=path)
    return rows


def _request_region_cells(
    boundary: Any,
    rows: list[list[str]],
    findings: list[dict[str, Any]],
    provenance_path: Path,
    *,
    required: bool,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Return request cells and all cells covered by classified regions."""
    regions = boundary.get("request_regions") if isinstance(boundary, dict) else None
    if not isinstance(regions, list) or not regions:
        if required:
            _add(
                findings,
                "ctp_request_regions",
                "testplan.boundary.request_regions must be a non-empty list",
                file=provenance_path,
            )
        return set(), set()

    candidates: set[tuple[int, int]] = set()
    reviewed: set[tuple[int, int]] = set()
    region_ids: set[str] = set()
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            _add(
                findings,
                "ctp_request_regions",
                f"request_regions[{index}] is not an object",
                file=provenance_path,
            )
            continue
        region_id = str(region.get("id", "")).strip()
        if not IDENTIFIER_RE.fullmatch(region_id) or region_id in region_ids:
            _add(
                findings,
                "ctp_request_regions",
                f"request_regions[{index}].id must be a unique identifier",
                file=provenance_path,
            )
        region_ids.add(region_id)
        row_range = region.get("rows")
        column_range = region.get("columns")
        def valid_range(value: Any) -> bool:
            return (
                isinstance(value, list)
                and len(value) == 2
                and all(
                    isinstance(item, int) and not isinstance(item, bool)
                    for item in value
                )
                and 1 <= value[0] <= value[1]
            )

        if not valid_range(row_range) or not valid_range(column_range):
            _add(
                findings,
                "ctp_request_regions",
                f"request region {region_id or index!r} needs inclusive positive rows/columns ranges",
                file=provenance_path,
            )
            continue
        excluded: set[tuple[int, int]] = set()
        exclusions = region.get("exclusions", [])
        if not isinstance(exclusions, list):
            _add(
                findings,
                "ctp_request_regions",
                f"request region {region_id!r} exclusions must be a list",
                file=provenance_path,
            )
            exclusions = []
        for exclusion in exclusions:
            if not isinstance(exclusion, dict):
                _add(
                    findings,
                    "ctp_request_region_exclusion",
                    f"request region {region_id!r} has a malformed exclusion",
                    file=provenance_path,
                )
                continue
            row = exclusion.get("row")
            column = exclusion.get("column")
            reason = str(exclusion.get("reason", "")).strip()
            coordinate = (row, column)
            if (
                not isinstance(row, int)
                or isinstance(row, bool)
                or not isinstance(column, int)
                or isinstance(column, bool)
                or not (row_range[0] <= row <= row_range[1])
                or not (column_range[0] <= column <= column_range[1])
                or not reason
            ):
                _add(
                    findings,
                    "ctp_request_region_exclusion",
                    f"request region {region_id!r} exclusion must be inside the region and explain why",
                    file=provenance_path,
                )
                continue
            excluded.add(coordinate)
        for row in range(row_range[0], row_range[1] + 1):
            for column in range(column_range[0], column_range[1] + 1):
                coordinate = (row, column)
                value = (
                    rows[row - 1][column - 1]
                    if row <= len(rows) and column <= len(rows[row - 1])
                    else ""
                )
                if coordinate not in excluded and value.strip():
                    candidates.add(coordinate)
                reviewed.add(coordinate)

    non_request_regions = boundary.get("non_request_regions", [])
    if not isinstance(non_request_regions, list):
        _add(
            findings,
            "ctp_non_request_regions",
            "testplan.boundary.non_request_regions must be a list",
            file=provenance_path,
        )
        non_request_regions = []
    for index, region in enumerate(non_request_regions):
        if not isinstance(region, dict):
            _add(
                findings,
                "ctp_non_request_regions",
                f"non_request_regions[{index}] is not an object",
                file=provenance_path,
            )
            continue
        region_id = str(region.get("id", "")).strip()
        role = str(region.get("role", "")).strip()
        reason = str(region.get("reason", "")).strip()
        row_range = region.get("rows")
        column_range = region.get("columns")
        if (
            not IDENTIFIER_RE.fullmatch(region_id)
            or region_id in region_ids
            or role not in {"header", "context", "ignored"}
            or not reason
            or not valid_range(row_range)
            or not valid_range(column_range)
        ):
            _add(
                findings,
                "ctp_non_request_regions",
                f"non_request_regions[{index}] needs a unique id, valid role/ranges, and reason",
                file=provenance_path,
            )
            continue
        region_ids.add(region_id)
        coordinates = {
            (row, column)
            for row in range(row_range[0], row_range[1] + 1)
            for column in range(column_range[0], column_range[1] + 1)
        }
        overlap = sorted(coordinates & candidates)
        if overlap:
            _add(
                findings,
                "ctp_boundary_region_overlap",
                f"non-request region {region_id!r} overlaps request cells: {overlap}",
                file=provenance_path,
            )
        reviewed.update(coordinates)
    return candidates, reviewed


def _declared_source_items(
    boundary: Any,
    rows: list[list[str]],
    findings: list[dict[str, Any]],
    provenance_path: Path,
    *,
    require_request_regions: bool = False,
    require_full_boundary_review: bool = False,
) -> set[str]:
    items = boundary.get("source_items") if isinstance(boundary, dict) else None
    if not isinstance(items, list) or not items:
        _add(
            findings,
            "ctp_source_items",
            "testplan.boundary.source_items must be a non-empty list",
            file=provenance_path,
        )
        return set()
    item_ids: set[str] = set()
    declared_cells: set[tuple[int, int]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            _add(findings, "ctp_source_items", f"source_items[{index}] is not an object")
            continue
        item_id = str(item.get("id", "")).strip()
        cells = item.get("cells")
        if not IDENTIFIER_RE.fullmatch(item_id):
            _add(findings, "ctp_source_items", f"source_items[{index}].id is invalid")
            continue
        if POSITIONAL_SOURCE_ID_RE.match(item_id):
            _add(
                findings,
                "ctp_source_item_semantic_id",
                f"source item {item_id!r} encodes a spreadsheet position; use a semantic ID",
                file=provenance_path,
            )
        if item_id in item_ids:
            _add(findings, "ctp_source_items", f"duplicate source item id {item_id!r}")
        item_ids.add(item_id)
        if not isinstance(cells, list) or not cells:
            _add(findings, "ctp_source_items", f"source item {item_id!r} has no cells")
            continue
        for cell_index, cell in enumerate(cells):
            if not isinstance(cell, dict):
                _add(
                    findings,
                    "ctp_source_cell",
                    f"source item {item_id!r} cells[{cell_index}] is not an object",
                )
                continue
            row = cell.get("row")
            column = cell.get("column")
            value = cell.get("value")
            if (
                isinstance(row, bool)
                or isinstance(column, bool)
                or not isinstance(row, int)
                or not isinstance(column, int)
                or row < 1
                or column < 1
                or not isinstance(value, str)
                or not value.strip()
            ):
                _add(
                    findings,
                    "ctp_source_cell",
                    f"source item {item_id!r} has an invalid cell record",
                )
                continue
            coordinate = (row, column)
            declared_cells.add(coordinate)
            actual = (
                rows[row - 1][column - 1]
                if row <= len(rows) and column <= len(rows[row - 1])
                else None
            )
            if actual != value:
                _add(
                    findings,
                    "ctp_source_cell",
                    f"source item {item_id!r} cell {coordinate} does not match raw CSV",
                    file=provenance_path,
                )
    if not isinstance(boundary, dict) or not str(boundary.get("layout", "")).strip():
        _add(
            findings,
            "ctp_source_layout",
            "testplan.boundary.layout is required",
            file=provenance_path,
        )
    request_cells, reviewed_cells = _request_region_cells(
        boundary,
        rows,
        findings,
        provenance_path,
        required=require_request_regions,
    )
    missing_request_cells = sorted(request_cells - declared_cells)
    if missing_request_cells:
        _add(
            findings,
            "ctp_request_region_coverage",
            f"request-region cells are absent from source_items: {missing_request_cells}",
            file=provenance_path,
        )
    if require_full_boundary_review:
        nonempty_cells = {
            (row_index, column_index)
            for row_index, row in enumerate(rows, start=1)
            for column_index, value in enumerate(row, start=1)
            if value.strip()
        }
        unreviewed_cells = sorted(nonempty_cells - reviewed_cells)
        if unreviewed_cells:
            _add(
                findings,
                "ctp_boundary_review_coverage",
                f"non-empty raw CSV cells are outside classified regions: {unreviewed_cells}",
                file=provenance_path,
            )
    return item_ids


def _optimized_source_contract(
    path: Path,
    findings: list[dict[str, Any]],
) -> tuple[dict[str, str], set[str], set[str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            fields = {
                str(field or "").strip() for field in reader.fieldnames or []
            }
    except (OSError, UnicodeError, csv.Error) as exc:
        _add(findings, "ctp_csv_read", f"cannot read CSV: {exc}", file=path)
        return {}, set(), set()
    required = CANONICAL_COLUMNS
    missing = sorted(required - fields)
    if missing:
        _add(
            findings,
            "ctp_boundary_schema",
            f"optimized CSV must use canonical source-row schema; missing {missing}",
            file=path,
        )
        return {}, set(), set()
    consumed: dict[str, str] = {}
    added: set[str] = set()
    removed: set[str] = set()
    seen_coverpoints: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        disposition = str(row.get("disposition") or "").strip()
        if disposition not in {"coverpoint", "removed"}:
            _add(
                findings,
                "ctp_boundary_schema",
                f"row {row_number} disposition must be coverpoint or removed",
                file=path,
            )
            continue
        coverpoint = str(row.get("coverpoint") or "").strip()
        try:
            source_items = json.loads(str(row.get("source_items") or ""))
        except json.JSONDecodeError as exc:
            _add(
                findings,
                "ctp_boundary_schema",
                f"row {row_number} source_items is not JSON: {exc}",
                file=path,
            )
            continue
        if not isinstance(source_items, list) or any(
            not isinstance(item, str) or not IDENTIFIER_RE.fullmatch(item)
            for item in source_items
        ):
            _add(
                findings,
                "ctp_boundary_schema",
                f"row {row_number} source_items must be an identifier array",
                file=path,
            )
            continue
        source_set = set(source_items)
        if len(source_set) != len(source_items):
            _add(
                findings,
                "ctp_boundary_duplicate_source_ref",
                f"row {row_number} repeats a source item",
                file=path,
            )
        if disposition == "removed":
            rules = _split_rules(
                str(row.get("normative_rules") or ""), canonical=True
            )
            if coverpoint or rules:
                _add(
                    findings,
                    "ctp_boundary_schema",
                    f"removed row {row_number} must leave coverpoint and rules empty",
                    file=path,
                )
            if not source_items:
                _add(
                    findings,
                    "ctp_boundary_schema",
                    f"removed row {row_number} must identify source_items",
                    file=path,
                )
            for source_item in source_set:
                if source_item in removed or source_item in consumed:
                    _add(
                        findings,
                        "ctp_boundary_duplicate_source_ref",
                        f"raw source item {source_item!r} is classified more than once",
                        file=path,
                    )
                removed.add(source_item)
            continue
        if not IDENTIFIER_RE.fullmatch(coverpoint):
            _add(
                findings,
                "ctp_boundary_schema",
                f"row {row_number} has an invalid coverpoint identifier",
                file=path,
            )
            continue
        if coverpoint in seen_coverpoints:
            _add(
                findings,
                "ctp_boundary_duplicate_coverpoint",
                f"optimized CSV repeats coverpoint {coverpoint!r}",
                file=path,
            )
        seen_coverpoints.add(coverpoint)
        if not source_items:
            added.add(coverpoint)
        for source_item in source_set:
            if source_item in consumed or source_item in removed:
                _add(
                    findings,
                    "ctp_boundary_duplicate_source_ref",
                    f"raw source item {source_item!r} is classified more than once",
                    file=path,
                )
            consumed[source_item] = coverpoint
    return consumed, added, removed


def _markdown_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [
        cell.strip().replace(r"\|", "|")
        for cell in re.split(r"(?<!\\)\|", stripped[1:-1])
    ]


def _human_testplan_contract(
    path: Path,
    suite: str,
    expected_entries: dict[str, set[str]],
    findings: list[dict[str, Any]],
) -> int:
    """Validate the human view against the canonical machine CSV."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        _add(findings, "ctp_human_testplan_read", str(exc), file=path)
        return 0

    title = f"# {suite} Human-Readable Test Plan"
    if not any(line.strip() == title for line in lines):
        _add(
            findings,
            "ctp_human_testplan_title",
            f"human-readable testplan must contain the title {title!r}",
            file=path,
        )

    required_columns = {
        "coverpoint",
        "source request",
        "normative rules",
        "disposition",
    }
    header_index = -1
    columns: list[str] = []
    for index, line in enumerate(lines):
        candidate = [cell.casefold() for cell in _markdown_cells(line)]
        if required_columns.issubset(candidate):
            header_index = index
            columns = candidate
            break
    if header_index < 0:
        _add(
            findings,
            "ctp_human_testplan_schema",
            "human-readable testplan needs a Markdown table with Coverpoint, Source request, Normative rules, and Disposition columns",
            file=path,
        )
        return 0

    indexes = {name: columns.index(name) for name in required_columns}
    seen: set[str] = set()
    for line in lines[header_index + 1 :]:
        cells = _markdown_cells(line)
        if not cells:
            if seen:
                break
            continue
        if len(cells) != len(columns):
            _add(
                findings,
                "ctp_human_testplan_schema",
                "human-readable testplan table row has the wrong number of columns",
                file=path,
            )
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        disposition = cells[indexes["disposition"]].strip().casefold()
        coverpoint = cells[indexes["coverpoint"]].strip().strip("`")
        if disposition != "coverpoint":
            _add(
                findings,
                "ctp_human_testplan_disposition",
                "the primary human-readable table may only contain coverpoint rows",
                file=path,
            )
            continue
        if coverpoint in seen:
            _add(
                findings,
                "ctp_human_testplan_duplicate",
                f"human-readable testplan repeats coverpoint {coverpoint!r}",
                file=path,
            )
        seen.add(coverpoint)
        if coverpoint not in expected_entries:
            _add(
                findings,
                "ctp_human_testplan_coverpoint",
                f"human-readable testplan contains unknown coverpoint {coverpoint!r}",
                file=path,
            )
            continue
        if not cells[indexes["source request"]].strip():
            _add(
                findings,
                "ctp_human_testplan_source",
                f"human-readable testplan lacks source request text for {coverpoint}",
                file=path,
            )
        declared_rules = set(
            re.findall(r"`([^`]+)`", cells[indexes["normative rules"]])
        )
        if declared_rules != expected_entries[coverpoint]:
            _add(
                findings,
                "ctp_human_testplan_rules",
                f"human-readable testplan rule set differs for {coverpoint}",
                file=path,
            )

    missing = sorted(set(expected_entries) - seen)
    if missing:
        _add(
            findings,
            "ctp_human_testplan_coverpoint",
            f"human-readable testplan omits coverpoints: {missing}",
            file=path,
        )
    required_details = (
        "Functional description",
        "Interface / instruction",
        "Privilege / preconditions",
        "Expected result",
        "Timing / state restoration",
        "Test notes",
    )
    document = "\n".join(lines)
    headings = list(re.finditer(r"(?m)^##\s+`([^`]+)`\s*$", document))
    detail_blocks = {
        match.group(1): document[
            match.end() : headings[index + 1].start()
            if index + 1 < len(headings)
            else len(document)
        ]
        for index, match in enumerate(headings)
    }
    for coverpoint in sorted(expected_entries):
        block = detail_blocks.get(coverpoint)
        if block is None:
            _add(
                findings,
                "ctp_human_testplan_details",
                f"human-readable testplan lacks a structured detail section for {coverpoint}",
                file=path,
            )
            continue
        for field in required_details:
            if not re.search(
                rf"(?m)^- \*\*{re.escape(field)}:\*\*\s+\S",
                block,
            ):
                _add(
                    findings,
                    "ctp_human_testplan_details",
                    f"{coverpoint} detail section lacks non-empty {field!r}",
                    file=path,
                )
    return len(seen)


def _normative_table(
    path: Path,
    findings: list[dict[str, Any]],
) -> tuple[set[str], str]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            fields = [str(field or "").strip() for field in reader.fieldnames or []]
    except (OSError, UnicodeError, csv.Error) as exc:
        _add(findings, "ctp_norm_table_read", f"cannot read CSV: {exc}", file=path)
        return set(), ""
    normalized = {field.casefold(): field for field in fields}
    missing = sorted(NORMATIVE_COLUMNS - set(normalized))
    if missing:
        _add(
            findings,
            "ctp_norm_table_schema",
            f"Normative Rules table is missing columns: {missing}",
            file=path,
        )
        return set(), ""
    rule_field = normalized["normative rule"]
    text_field = normalized["rule text"]
    coverpoints_field = normalized["coverpoints"]
    names: list[str] = []
    coverpoint_text: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        rules = _split_rules(str(row.get(rule_field) or ""), canonical=False)
        text = str(row.get(text_field) or "").strip()
        targets = str(row.get(coverpoints_field) or "").strip()
        if not rules or not text or not targets:
            _add(
                findings,
                "ctp_norm_table_row",
                f"row {row_number} requires rule, rule text, and coverpoints",
                file=path,
            )
        names.extend(rules)
        coverpoint_text.append(targets)
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        _add(
            findings,
            "ctp_norm_table_duplicate_rule",
            f"Normative Rules table repeats rule IDs: {duplicates}",
            file=path,
        )
    return set(names), "\n".join(coverpoint_text)


class ACT4CTPReferenceChecker(Checker):
    """Check CTP discovery, downloaded Sheet scope, and rebuilt rule assets."""

    def __init__(
        self,
        suite: str,
        ctp_snapshot: str,
        provenance_file: str,
        raw_testplan: str,
        optimized_testplan: str,
        human_readable_testplan: str,
        normative_table: str,
        normative_metadata: str,
        ctp_url: str = CTP_URL,
        require_request_regions: bool = False,
        require_full_boundary_review: bool = False,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4CTPReferenceChecker arguments: {sorted(kwargs)}"
            )
        self.suite = suite
        self.ctp_snapshot = ctp_snapshot
        self.provenance_file = provenance_file
        self.raw_testplan = raw_testplan
        self.optimized_testplan = optimized_testplan
        self.human_readable_testplan = human_readable_testplan
        self.normative_table = normative_table
        self.normative_metadata = normative_metadata
        self.ctp_url = ctp_url
        self.require_request_regions = bool(require_request_regions)
        self.require_full_boundary_review = bool(require_full_boundary_review)
        if hasattr(self, "set_human_check_needed"):
            self.set_human_check_needed(need_human_check)

    def _workspace(self) -> Path:
        return Path(getattr(self, "workspace", None) or os.getcwd()).resolve()

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self._workspace() / path).resolve()

    def _check_declared_file(
        self,
        section: Any,
        path: Path,
        key: str,
        findings: list[dict[str, Any]],
    ) -> None:
        if not isinstance(section, dict):
            _add(findings, "ctp_provenance_schema", f"{key} must be an object")
            return
        declared_path = section.get("path") or section.get("snapshot_path")
        if not declared_path or self._resolve(str(declared_path)) != path:
            _add(
                findings,
                "ctp_provenance_path",
                f"{key} path does not match configured file",
                file=path,
            )
        if section.get("sha256") != _sha256(path):
            _add(
                findings,
                "ctp_provenance_hash",
                f"{key} SHA-256 does not match",
                file=path,
            )

    def do_check(
        self, timeout=0, is_complete=False, **kwargs: Any
    ) -> tuple[bool, object]:
        """Validate CTP discovery, suite scope, and normative reference assets."""
        findings: list[dict[str, Any]] = []
        ctp_path = self._resolve(self.ctp_snapshot)
        provenance_path = self._resolve(self.provenance_file)
        raw_path = self._resolve(self.raw_testplan)
        optimized_path = self._resolve(self.optimized_testplan)
        human_path = self._resolve(self.human_readable_testplan)
        norm_table_path = self._resolve(self.normative_table)
        metadata_path = self._resolve(self.normative_metadata)
        inputs = (
            (ctp_path, "CTP snapshot"),
            (provenance_path, "CTP provenance"),
            (raw_path, "raw testplan"),
            (optimized_path, "optimized testplan"),
            (norm_table_path, "Normative Rules table"),
            (metadata_path, "normative metadata"),
        ) + ((human_path, "human-readable testplan"),)
        for path, label in inputs:
            if not path.is_file():
                _add(findings, "ctp_input_exists", f"{label} is missing", file=path)
        if findings:
            return False, {
                "summary": {"errors": len(findings), "warnings": 0},
                "findings": findings,
            }

        try:
            provenance = _load_yaml(provenance_path)
        except ValueError as exc:
            _add(findings, "ctp_provenance_parse", str(exc), file=provenance_path)
            provenance = {}
        if not isinstance(provenance, dict):
            _add(
                findings,
                "ctp_provenance_schema",
                "provenance must be a YAML object",
                file=provenance_path,
            )
            provenance = {}
        if provenance.get("schema_version") != 1 or provenance.get("suite") != self.suite:
            _add(
                findings,
                "ctp_provenance_schema",
                "provenance requires schema_version=1 and the configured suite",
                file=provenance_path,
            )

        ctp = provenance.get("ctp", {})
        if not isinstance(ctp, dict) or ctp.get("url") != self.ctp_url:
            _add(
                findings,
                "ctp_source_url",
                f"CTP URL must be {self.ctp_url}",
                file=provenance_path,
            )
        if not isinstance(ctp, dict) or not str(ctp.get("fetched_at", "")).strip():
            _add(findings, "ctp_fetched_at", "ctp.fetched_at is required")
        self._check_declared_file(ctp, ctp_path, "ctp", findings)

        parser = _CTPTableParser()
        try:
            parser.feed(ctp_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            _add(findings, "ctp_html_read", f"cannot parse CTP HTML: {exc}", file=ctp_path)
        table_id = f"t-{self.suite}-coverpoints"
        title = f"{self.suite} Coverpoints"
        matching_tables = [
            table for table in parser.tables if str(table["id"]) == table_id
        ]
        selected = matching_tables[0] if len(matching_tables) == 1 else None
        table_number = None
        sheet_url = ""
        expected_export_url = ""
        sheet_parts: tuple[str, str] | None = None
        if not matching_tables:
            _add(
                findings,
                "ctp_suite_table",
                f"CTP has no table with id {table_id!r}",
                file=ctp_path,
            )
        elif len(matching_tables) != 1:
            _add(
                findings,
                "ctp_suite_table",
                f"CTP contains {len(matching_tables)} tables with id {table_id!r}",
                file=ctp_path,
            )
        else:
            table_number = _parse_table_number(str(selected["caption"]), title)
            if table_number is None:
                _add(
                    findings,
                    "ctp_suite_table",
                    f"table {table_id!r} caption is not 'Table N. {title}'",
                    file=ctp_path,
                )
            google_targets = {
                parts: link
                for link in selected["links"]
                if (parts := _google_sheet_parts(link)) is not None
            }
            if len(google_targets) != 1:
                _add(
                    findings,
                    "ctp_sheet_link",
                    f"suite {self.suite!r} is not supported by this workflow: "
                    f"table {table_id!r} must identify exactly one Google Sheet tab",
                    file=ctp_path,
                )
            else:
                sheet_parts, sheet_url = next(iter(google_targets.items()))

        declared_table = ctp.get("coverpoints_table", {}) if isinstance(ctp, dict) else {}
        if sheet_parts is not None:
            spreadsheet_id, gid = sheet_parts
            export_url = (
                f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/"
                f"export?format=csv&gid={gid}"
            )
            expected_export_url = export_url
            expected_table = {
                "id": table_id,
                "title": title,
                "number": table_number,
                "sheet_url": sheet_url,
                "spreadsheet_id": spreadsheet_id,
                "gid": gid,
                "export_url": export_url,
            }
            for key, value in expected_table.items():
                if not isinstance(declared_table, dict) or declared_table.get(key) != value:
                    _add(
                        findings,
                        "ctp_table_provenance",
                        f"ctp.coverpoints_table.{key} does not match the HTML",
                        file=provenance_path,
                    )

        testplan = provenance.get("testplan", {})
        raw_section = testplan.get("raw", {}) if isinstance(testplan, dict) else {}
        optimized_section = (
            testplan.get("optimized", {}) if isinstance(testplan, dict) else {}
        )
        self._check_declared_file(raw_section, raw_path, "testplan.raw", findings)
        if expected_export_url and raw_section.get("source_url") != expected_export_url:
            _add(
                findings,
                "ctp_raw_source_url",
                "testplan.raw.source_url does not match the CTP-derived export URL",
                file=provenance_path,
            )
        self._check_declared_file(
            optimized_section, optimized_path, "testplan.optimized", findings
        )
        optimized_entries = _sheet_entries(optimized_path, findings)
        human_section = (
            testplan.get("human_readable", {}) if isinstance(testplan, dict) else {}
        )
        self._check_declared_file(
            human_section,
            human_path,
            "testplan.human_readable",
            findings,
        )
        human_rows = _human_testplan_contract(
            human_path,
            self.suite,
            optimized_entries,
            findings,
        )
        boundary = testplan.get("boundary", {}) if isinstance(testplan, dict) else {}
        raw_rows = _raw_matrix(raw_path, findings)
        declared_source_items = _declared_source_items(
            boundary,
            raw_rows,
            findings,
            provenance_path,
            require_request_regions=self.require_request_regions,
            require_full_boundary_review=self.require_full_boundary_review,
        )
        (
            consumed_source_items,
            added_coverpoints,
            removed_source_items,
        ) = _optimized_source_contract(optimized_path, findings)
        optimized = set(optimized_entries)
        contract_coverpoints = set(consumed_source_items.values()) | added_coverpoints
        if contract_coverpoints != optimized:
            _add(
                findings,
                "ctp_boundary_schema",
                "optimized coverpoints do not match canonical source-item records",
                file=optimized_path,
            )
        classified_source_items = set(consumed_source_items) | removed_source_items
        unknown_source_items = sorted(
            classified_source_items - declared_source_items
        )
        if unknown_source_items:
            _add(
                findings,
                "ctp_boundary_unknown_source_item",
                f"optimized CSV references unknown source items: {unknown_source_items}",
                file=optimized_path,
            )
        unclassified_source_items = sorted(
            declared_source_items - classified_source_items
        )
        if unclassified_source_items:
            _add(
                findings,
                "ctp_boundary_unclassified_source_item",
                f"source items are not classified: {unclassified_source_items}",
                file=optimized_path,
            )
        if not isinstance(boundary, dict) or not boundary.get("selection_basis"):
            _add(
                findings,
                "ctp_suite_boundary",
                "testplan.boundary.selection_basis is required",
                file=provenance_path,
            )
        changes = boundary.get("changes", []) if isinstance(boundary, dict) else []
        added_disclosures = {
            str(change.get("coverpoint")): change
            for change in changes
            if isinstance(change, dict) and change.get("action") == "added"
        }
        item_disclosures = {
            (str(change.get("action")), str(change.get("source_item"))): change
            for change in changes
            if isinstance(change, dict)
        }
        required_changes: list[tuple[str, str, dict[str, Any]]] = []
        for coverpoint in sorted(added_coverpoints):
            required_changes.append(
                ("added coverpoint", coverpoint, added_disclosures.get(coverpoint, {}))
            )
        for source_item in sorted(removed_source_items):
            required_changes.append(
                (
                    "removed source item",
                    source_item,
                    item_disclosures.get(("removed", source_item), {}),
                )
            )
        for kind, identifier, change in required_changes:
            if not str(change.get("rationale", "")).strip() or not change.get("evidence"):
                _add(
                    findings,
                    "ctp_boundary_change_disclosure",
                    f"{kind} {identifier!r} needs action, rationale, and evidence",
                    file=provenance_path,
                )

        try:
            metadata = _load_yaml(metadata_path)
        except ValueError as exc:
            _add(findings, "ctp_metadata_parse", str(exc), file=metadata_path)
            metadata = {}
        known_rules = _metadata_names(metadata, findings, metadata_path)
        optimized_rules = set().union(*optimized_entries.values()) if optimized_entries else set()
        invalid_rules = sorted(optimized_rules - known_rules)
        if invalid_rules:
            _add(
                findings,
                "ctp_testplan_rule_registry",
                f"optimized CSV uses rule IDs absent from manual metadata: {invalid_rules}",
                file=optimized_path,
            )
        table_rules, table_coverpoint_text = _normative_table(norm_table_path, findings)
        if table_rules != optimized_rules:
            _add(
                findings,
                "ctp_norm_table_rule_set",
                "Normative Rules table rule set must exactly match optimized CSV",
                file=norm_table_path,
            )
        missing_table_coverpoints = sorted(
            coverpoint
            for coverpoint in optimized
            if not re.search(
                rf"(?<![A-Za-z0-9_$]){re.escape(coverpoint)}(?![A-Za-z0-9_$])",
                table_coverpoint_text,
            )
        )
        if missing_table_coverpoints:
            _add(
                findings,
                "ctp_norm_table_coverpoints",
                f"Normative Rules table omits coverpoints: {missing_table_coverpoints}",
                file=norm_table_path,
            )
        norm_section = provenance.get("normative_rules_table", {})
        self._check_declared_file(
            norm_section, norm_table_path, "normative_rules_table", findings
        )

        error_count = len(findings)
        report = {
            "summary": {"errors": error_count, "warnings": 0},
            "findings": findings,
            "checks": {
                "ctp_table_id": table_id,
                "ctp_table_number": table_number,
                "source_items": len(declared_source_items),
                "optimized_coverpoints": len(optimized),
                "optimized_rules": len(optimized_rules),
                "human_testplan_coverpoints": human_rows,
                "normative_table_rules": len(table_rules),
            },
        }
        if error_count:
            return False, report
        return True, {"message": "ACT4 CTP reference check passed", **report}


__all__ = ["ACT4CTPReferenceChecker"]
