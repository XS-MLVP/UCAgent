"""Resolve workflow targets against the bundled ACT progress-sheet snapshot."""

import csv
import difflib
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from ucagent.plugins import PluginError
from ucagent.util.log import info


CATALOG_ROOT = Path(__file__).resolve().parent / "data"
STATUS_COLUMNS = {
    "Norm Rules/YAML": ("Norm Rules", "YAML"),
    "Testplan/Written": ("Testplan", "Written"),
    "CTP/Written": ("Certification Test Plan (CTP)", "Written"),
    "Norm Rule Map": ("Certification Test Plan (CTP)", "Norm Rule to Coverpoint Map"),
    "Coverpoints/Written": ("Coverpoints", "Written"),
    "Sail/Supported": ("Sail", "Extension Supported"),
    "Tests/Written": ("Tests", "Written"),
}


def load_suite_catalog(root: Path = CATALOG_ROOT) -> dict[str, Any]:
    """Load exact suite identities and all source rows, failing on snapshot drift."""
    try:
        metadata = json.loads((root / "test_suites.json").read_text(encoding="utf-8"))
        payload = (root / "test_suites.csv").read_bytes()
        if metadata["schema_version"] != 1 or hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
            raise ValueError("catalog schema or CSV digest mismatch")
        date.fromisoformat(metadata["retrieved_on"])
        if not isinstance(metadata["source_url"], str) or not metadata["source_url"].startswith("https://"):
            raise ValueError("missing catalog source URL")
        exclusions = metadata["non_targets"]
        if not isinstance(exclusions, dict) or any(
            not isinstance(name, str) or not name or not isinstance(reason, str) or not reason
            for name, reason in exclusions.items()
        ):
            raise ValueError("non_targets must map sheet labels to exclusion reasons")
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
        if len(rows) < 4 or rows[0][1:5] != ["Test Suite", "Description", "Owner", "Notes"]:
            raise ValueError("expected Test Suite/Description/Owner/Notes columns")
        columns = {}
        heading = ""
        for index, title in enumerate(rows[0]):
            if title.strip():
                heading = " ".join(title.split())
            columns[(heading, rows[2][index].strip())] = index
        status_indices = {label: columns[key] for label, key in STATUS_COLUMNS.items()}
        targets = {}
        excluded = {}
        group = "Not specified"
        record_count = 0
        for row_number, cells in enumerate(rows[3:], 4):
            if len(cells) != len(rows[0]):
                raise ValueError(f"row {row_number}: column count mismatch")
            if cells[0].strip():
                group = cells[0].strip()
            name = cells[1].strip()
            if not name:
                continue
            record_count += 1
            if name in exclusions:
                excluded.setdefault(name, {"reason": exclusions[name], "rows": []})["rows"].append(row_number)
                group = name
                continue
            target = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
            if not target or (target in targets and targets[target]["test_suite"] != name):
                raise ValueError(f"ambiguous or empty CLI target for {name!r}")
            entry = targets.setdefault(target, {"target": target, "test_suite": name, "rows": []})
            entry["rows"].append({
                "row": row_number,
                "group": group,
                "description": cells[2].strip(),
                "owner": cells[3].strip(),
                "notes": cells[4].strip(),
                "status": {label: cells[index].strip() for label, index in status_indices.items()},
            })
        if not targets or set(excluded) != set(exclusions):
            raise ValueError("empty target list or non_targets absent from the snapshot")
        return {**metadata, "targets": targets, "excluded": excluded, "record_count": record_count}
    except (OSError, UnicodeError, ValueError, KeyError, IndexError, TypeError, csv.Error) as error:
        raise PluginError(
            f"Cannot load ACT4 Test Suite catalog: {error}. "
            "Restore the plugin's data/test_suites.csv and test_suites.json together; "
            "see plugins/ACT4/docs/development.md."
        ) from error


def validate_suite_target(target: Any, *, announce: bool = True) -> dict[str, str]:
    """Reject unknown targets before resource preparation and print source metadata."""
    catalog = load_suite_catalog()
    targets = catalog["targets"]
    if not isinstance(target, str) or target not in targets:
        choices = []
        reason = "Target is not in the bundled Test Suite list."
        if isinstance(target, str):
            for name, entry in catalog["excluded"].items():
                if target in {name, re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")}:
                    reason = f"{name!r} is not an executable suite: {entry['reason']}."
                    break
            choices = [name for name, entry in targets.items() if entry["test_suite"] == target]
            if not choices:
                choices = difflib.get_close_matches(target, targets, n=5, cutoff=0.5)
        suggestions = f" Candidate CLI targets: {', '.join(choices)}." if choices else ""
        raise PluginError(
            f"Invalid ACT4 Test Suite target {target!r}. {reason}{suggestions} "
            "Use the exact, case-sensitive CLI target in plugins/ACT4/docs/test-suites.md "
            f"(catalog snapshot {catalog['retrieved_on']}). No resources have been prepared."
        )
    entry = targets[target]
    summary = [
        f"ACT4 Test Suite: {entry['test_suite']} | CLI target: {target}",
        f"Catalog snapshot: {catalog['retrieved_on']} | source: {catalog['source_url']}",
    ]
    for row in entry["rows"]:
        summary.extend([
            f"  Sheet row {row['row']} | group: {row['group']}",
            f"  Description: {row['description'] or 'Not specified in sheet'} | owner: {row['owner'] or 'Not specified'}",
            "  Sheet status: " + "; ".join(f"{label}={value or 'Not specified'}" for label, value in row["status"].items()),
        ])
        if row["notes"]:
            summary.append(f"  Sheet notes: {row['notes']}")
    summary.append("Sheet status is historical context, not evidence of local assets, coverage, or validation.")
    if announce:
        info("\n".join(summary))
    scope = {
        "target": target,
        "test_suite": entry["test_suite"],
        "source_url": catalog["source_url"],
        "retrieved_on": catalog["retrieved_on"],
        "rows": [{key: row[key] for key in ("row", "group", "description")} for row in entry["rows"]],
    }
    return {"ACT4_SUITE_SCOPE": json.dumps(scope, ensure_ascii=True)}
