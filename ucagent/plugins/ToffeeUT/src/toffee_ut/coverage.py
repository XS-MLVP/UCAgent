"""Inspect native counters and reconcile exact or compact zero-point reviews."""

from pathlib import Path
import re
import reprlib

from .paths import digest, local_path


_DIAGNOSTIC_REPR = reprlib.Repr()
_DIAGNOSTIC_REPR.maxlevel = 1


def _preview(value):
    """Bound diagnostic identities without changing any value used for exact matching."""
    if isinstance(value, str):
        return value if len(value) <= 160 else value[:160] + f"... ({len(value)} chars)"
    return _DIAGNOSTIC_REPR.repr(value)[:160]


def _unreviewed(locations, reviewed):
    """Count remaining zero points with at most four exact location examples per metric."""
    counts = dict.fromkeys(("line", "branch", "toggle"), 0)
    examples, sampled = [], dict.fromkeys(counts, 0)
    for (metric, build, source, line), keys in locations.items():
        remaining = sum(not reviewed[key] for key in keys)
        counts[metric] += remaining
        if remaining and sampled[metric] < 4:
            examples.append({"metric": metric, "build": _preview(build), "source": _preview(source),
                             "line": line, "zero_points": remaining})
            sampled[metric] += 1
    return {"unreviewed_total": sum(counts.values()), "unreviewed_by_metric": counts,
            "unreviewed": examples}


def native_points(workspace, project, dut, checked):
    """Read raw native counters without relying on an editable coverage review."""
    from .layout import project_layout

    if checked["record"]["dut"] != dut:
        raise ValueError("Current run belongs to another DUT")
    expected = "DUT" + project_layout(workspace, dut, project)["export_name"]
    artifacts = checked["manifest"].get("artifacts", [])
    builds = {Path(row["path"]).parent: row for row in artifacts
              if row["kind"] == "native" and row["build"]["name"] == expected}
    points = {metric: [] for metric in ("line", "branch", "toggle")}
    paths = []
    for parent, artifact in builds.items():
        path = Path(artifact["path"])
        paths.append(str(path))
        # LCOV supplies physical lines; DAT retains branch/toggle points that
        # must never be reinterpreted as physical line hits.
        with path.open("rb") as stream:
            if stream.readline() != b"# SystemC::Coverage-3\n":
                raise ValueError(f"Invalid native coverage header: {path}")
            seen = set()
            for raw in stream:
                match = re.fullmatch(rb"C '(.*)' ([0-9]+)\n?", raw)
                if match is None or match[1] in seen:
                    raise ValueError(f"Malformed or duplicated native coverage point: {path}")
                seen.add(match[1])
                fields = dict(part.split(b"\x02", 1) for part in match[1].split(b"\x01") if b"\x02" in part)
                page = fields.get(b"page", b"").decode()
                metric = next((name for name in ("branch", "toggle") if page.startswith("v_" + name)), None)
                if metric:
                    points[metric].append({"build": artifact["build"]["build_id"],
                        "source": fields.get(b"f", b"").decode(), "line": int(fields.get(b"l", b"0")),
                        "point": match[1].decode(), "count": int(match[2])})
        del seen
        counts = {}
        for row in artifacts:
            if row["kind"] != "lcov" or Path(row["path"]).parent != parent:
                continue
            paths.append(row["path"])
            source = None
            for raw in Path(row["path"]).read_text().splitlines():
                if raw.startswith("SF:"):
                    source = raw[3:]
                    if not source:
                        raise ValueError("LCOV has an empty source path")
                elif raw.startswith("DA:"):
                    fields = raw[3:].split(",")
                    if source is None or len(fields) < 2:
                        raise ValueError("LCOV line count has no source or count")
                    line, count = int(fields[0]), int(fields[1])
                    if line < 1 or count < 0:
                        raise ValueError("LCOV line numbers must be positive and counts nonnegative")
                    counts[source, line] = counts.get((source, line), 0) + count
                elif raw == "end_of_record":
                    source = None
        points["line"].extend({"build": artifact["build"]["build_id"], "source": source,
                               "line": line, "count": count} for (source, line), count in sorted(counts.items()))
    return points, paths, builds


def coverage_data(workspace, project, dut, checked, *, directory=None):
    """Read counters/review; optionally project a directory (metric, exact filters, offset, limit)."""
    points, paths, builds = native_points(workspace, project, dut, checked)
    result = {"artifacts": paths, "builds": len(builds)}
    reviewed, locations = {}, {}
    for metric, rows in points.items():
        found, hit = len(rows), sum(row["count"] > 0 for row in rows)
        result[metric] = {"state": "collected" if found else "not_collected", "found": found, "hit": hit,
                          "coverage": hit * 100.0 / found if found else None,
                          "uncovered": [row for row in rows if not row["count"]]}
        for row in result[metric]["uncovered"]:
            position = (metric, row["build"], row["source"], row["line"])
            key = (*position, row.get("point"))
            if key in reviewed:
                raise ValueError(f"Duplicated native zero-point identity: {position}")
            reviewed[key] = False
            locations.setdefault(position, []).append(key)
    if directory is not None:
        # Audit indexes cover every metric; only this requested projection is sorted.
        metric, filters, offset, limit = directory
        positions = sorted(position for position in locations if position[0] == metric
            and ("build" not in filters or position[1] == filters["build"])
            and ("source" not in filters or position[2] == filters["source"])
            and ("line" not in filters or position[3] == filters["line"]))
        page = {"groups_total": len(positions), "uncovered_total": sum(len(locations[pos]) for pos in positions),
                "next_offset": offset + limit if offset + limit < len(positions) else None, "groups": []}
        for position in positions[offset:offset + limit]:
            metric, build, source, line = position
            selector = {"metric": metric, "build": build, "source": source, "line": line}
            if metric != "line":
                selector["group"] = {"scope": "source-line"}
            page["groups"].append({"metric": metric, "build": build, "source": source, "line": line,
                "zero_points": len(locations[position]), "selector": selector if source and line > 0 else None})
        result["directory"] = page
    result["review"] = {"state": "missing", "gaps": [], "issue_kind": "review_missing",
                        "error": "Record a line_coverage review for this run"}
    review_path = local_path(workspace, (Path(project) / f"docs/reviews/{dut}-stage-evidence.md").as_posix())
    if not review_path.is_file():
        result["review"].update(_unreviewed(locations, reviewed))
        return result
    from .audit import read_spec
    issue_kind, location = "review_invalid", None
    try:
        entry = read_spec(review_path, "stage_evidence", dut).get("reviews", {}).get("line_coverage")
        if not isinstance(entry, dict) or entry.get("run") != checked["record"]["run"]:
            issue_kind = "review_stale" if isinstance(entry, dict) else "review_missing"
            raise ValueError("line_coverage review must identify the exact current run")
        for key in ("source", "observation", "next_action"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"line_coverage review needs {key}")
        source = local_path(workspace, entry["source"].split("#", 1)[0])
        if source.resolve() == review_path.resolve() or not source.is_file() or digest(source) != entry.get("sha256"):
            raise ValueError("line_coverage review source is missing or stale")
        if result["line"]["state"] != "collected":
            raise ValueError("No current signed native LCOV physical line counts; do not claim full coverage")
        dispositions = entry.get("uncovered")
        if not isinstance(dispositions, list):
            raise ValueError("Review every collected metric's zero points in uncovered")
        build_ids = {artifact["build"]["build_id"] for artifact in builds.values()}
        if len(build_ids) != len(builds):
            raise ValueError("Native coverage builds need distinct build IDs for review")
        gaps, gap_points = [], 0
        for row in dispositions:
            if not isinstance(row, dict):
                raise ValueError("Each zero-point disposition must be a selector mapping")
            metric, source, line = row.get("metric", "line"), row.get("source"), row.get("line")
            build = row.get("build", next(iter(build_ids)) if len(build_ids) == 1 else None)
            label = f"metric={_preview(metric)} build={_preview(build)} source={_preview(source)} line={_preview(line)}"
            if "point" in row:
                label += f" point={_preview(row['point'])!r}"
            if (not isinstance(row.get("status"), str) or row["status"] not in {"gap", "justified"} or not isinstance(row.get("reason"), str)
                    or not row["reason"].strip()):
                raise ValueError(f"Each zero-point disposition needs gap/justified and an independent reason: {label}")
            if set(row) - {"metric", "build", "source", "line", "point", "group", "status", "reason", "count"}:
                raise ValueError(f"Unknown zero-point selector fields: {label}")
            if (not isinstance(metric, str) or metric not in points or not isinstance(source, str) or not source
                    or type(line) is not int or line < 0):
                raise ValueError(f"Invalid zero-point location: {label}")
            if len(build_ids) > 1 and "build" not in row:
                raise ValueError(f"Multiple native builds require an explicit build on each selector: {label}; "
                                 f"available={[_preview(value) for value in sorted(build_ids)[:8]]}")
            if not isinstance(build, str) or not build or build not in build_ids:
                raise ValueError(f"Unknown native build in zero-point selector: {label}")
            if "count" in row and (type(row["count"]) is not int or row["count"] != 0):
                raise ValueError(f"A zero-point selector cannot change the native count: {label}")
            position = (metric, build, source, line)
            if "group" in row:
                if (metric == "line" or line < 1 or row["group"] != {"scope": "source-line"}
                        or "point" in row):
                    raise ValueError(f"Group requires branch/toggle, positive source line, scope=source-line and no point: {label}")
                matches = locations.get(position, ())
            else:
                point = row.get("point")
                if (metric == "line" and point is not None or metric != "line"
                        and (not isinstance(point, str) or not point)):
                    raise ValueError(f"Use an exact native point for branch/toggle or an explicit group: {label}")
                key = (*position, point)
                matches = (key,) if key in reviewed else ()
            if not matches:
                issue_kind, location = "selector_mismatch", label
                raise ValueError(f"Selector matches no actual zero points: {label}")
            if any(reviewed[key] for key in matches):
                raise ValueError(f"Overlapping or duplicate zero-point review: {label}")
            for key in matches:
                reviewed[key] = True
            if row["status"] == "gap":
                gaps.append({**row, "metric": metric, "build": build})
                gap_points += len(matches)
        remaining = _unreviewed(locations, reviewed)
        if remaining["unreviewed_total"]:
            issue_kind = "review_incomplete"
            raise ValueError(f"Unreviewed native zero points: {remaining['unreviewed_total']}; "
                             f"by metric={remaining['unreviewed_by_metric']}; locations={remaining['unreviewed']}")
        result["review"] = {"state": "gaps" if gaps else "complete", "gaps": gaps,
                            "gap_points": gap_points, **remaining}
        if gaps:
            first = gaps[0]
            result["review"]["issue_kind"] = "coverage_gaps"
            result["review"]["location"] = f"{_preview(first.get('metric'))}:{_preview(first.get('source'))}:{_preview(first.get('line'))}"
            result["review"]["error"] = (f"Native coverage review has {len(gaps)} gap dispositions ({gap_points} zero points); "
                f"metric={_preview(first.get('metric', 'line'))} build={_preview(first.get('build'))} "
                f"source={_preview(first.get('source'))} line={_preview(first.get('line'))}")
    except (ValueError, KeyError, TypeError, OSError) as error:
        result["review"] = {"state": "invalid", "gaps": [], "issue_kind": issue_kind,
                            "error": str(error)[:1800], **_unreviewed(locations, reviewed)}
        if location:
            result["review"]["location"] = location
    return result
