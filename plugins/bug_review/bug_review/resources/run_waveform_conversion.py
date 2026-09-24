#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Sequence


def resolve_fst2vcd() -> str:
    return os.environ.get("BENCHMARK_WAVEFORM_FST2VCD_BIN") or shutil.which("fst2vcd") or ""


def discover_fst_files(inputs: Iterable[str]) -> List[str]:
    fst_files: List[str] = []
    for item in inputs:
        if not item:
            continue
        if os.path.isdir(item):
            for dirpath, _, filenames in os.walk(item):
                for filename in sorted(filenames):
                    if filename.endswith(".fst"):
                        fst_files.append(os.path.join(dirpath, filename))
            continue
        if item.endswith(".fst"):
            fst_files.append(item)
    deduped = []
    seen = set()
    for path in fst_files:
        normalized = os.path.abspath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _normalize_signal_name(name: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", (name or "").strip().lower())


def _format_window(first_time: object, last_time: object) -> str:
    if first_time == last_time:
        return f"time {first_time}"
    return f"time {first_time}-{last_time}"


def _format_pattern(changes: Sequence[Dict[str, object]], max_changes: int = 8) -> str:
    values = [str(item.get("value")) for item in changes[:max_changes] if item.get("value") is not None]
    if not values:
        return "n/a"
    if len(values) == 1:
        return values[0]
    pattern = " -> ".join(values)
    if len(changes) > max_changes:
        pattern += " -> ..."
    return pattern


def _adapt_observation(signal_name: str, backend: str, changes: Sequence[Dict[str, object]], max_changes: int = 8) -> Dict[str, object]:
    if not changes:
        return {}
    first = changes[0]
    last = changes[-1]
    sample_changes = list(changes[:max_changes])
    return {
        "signal": signal_name,
        "backend": backend,
        "change_count": len(changes),
        "first_time": first.get("time"),
        "first_value": first.get("value"),
        "last_time": last.get("time"),
        "last_value": last.get("value"),
        "window": _format_window(first.get("time"), last.get("time")),
        "pattern": _format_pattern(changes, max_changes=max_changes),
        "sample_changes": sample_changes,
    }


def _parse_vcd_with_library(vcd_path: str, signal_hints: Sequence[str] = (), max_changes: int = 8) -> Optional[List[Dict[str, object]]]:
    try:
        from vcdvcd import VCDVCD  # type: ignore
    except Exception:
        return None

    hints = [_normalize_signal_name(item) for item in signal_hints if item]
    if not hints:
        return []

    try:
        vcd = VCDVCD(vcd_path)
    except Exception:
        return None

    observations: List[Dict[str, object]] = []
    for ref in sorted(getattr(vcd, "references_to_ids", {}).keys()):
        normalized_ref = _normalize_signal_name(ref)
        if not any(
            normalized_ref == hint or normalized_ref.endswith("." + hint) or normalized_ref.endswith("_" + hint)
            for hint in hints
        ):
            continue
        try:
            signal = vcd[ref]
        except Exception:
            continue
        tv = list(getattr(signal, "tv", []))
        if not tv:
            continue
        observations.append(
            _adapt_observation(
                normalized_ref,
                "vcdvcd",
                [{"time": time, "value": value} for time, value in tv],
                max_changes=max_changes,
            )
        )
    return observations


def parse_vcd_observations(vcd_path: str, signal_hints: Sequence[str] = (), max_changes: int = 8) -> List[Dict[str, object]]:
    if not os.path.exists(vcd_path):
        return []

    library_observations = _parse_vcd_with_library(vcd_path, signal_hints=signal_hints, max_changes=max_changes)
    if library_observations is not None:
        return library_observations

    hints = [_normalize_signal_name(item) for item in signal_hints if item]
    if not hints:
        return []

    id_to_name: Dict[str, str] = {}
    matched_ids: Dict[str, str] = {}
    current_time = 0
    values: Dict[str, Dict[str, object]] = {}
    in_header = True

    with open(vcd_path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if in_header:
                if line.startswith("$var "):
                    parts = line.split()
                    if len(parts) >= 5:
                        identifier = parts[3]
                        reference = _normalize_signal_name(parts[4])
                        id_to_name[identifier] = reference
                        for hint in hints:
                            if reference == hint or reference.endswith("." + hint) or reference.endswith("_" + hint):
                                matched_ids[identifier] = reference
                                values.setdefault(reference, {"name": reference, "changes": []})
                                break
                    continue
                if line == "$enddefinitions $end":
                    in_header = False
                continue

            if line.startswith("#"):
                try:
                    current_time = int(line[1:])
                except ValueError:
                    continue
                continue

            if line[0] in "01xzXZ":
                identifier = line[1:]
                if identifier not in matched_ids:
                    continue
                signal_name = matched_ids[identifier]
                signal_entry = values.setdefault(signal_name, {"name": signal_name, "changes": []})
                signal_entry["changes"].append({"time": current_time, "value": line[0]})
                continue

            if line[0] in "br":
                space_index = line.find(" ")
                if space_index == -1:
                    continue
                raw_value = line[1:space_index].strip()
                identifier = line[space_index + 1 :].strip()
                if identifier not in matched_ids:
                    continue
                signal_name = matched_ids[identifier]
                signal_entry = values.setdefault(signal_name, {"name": signal_name, "changes": []})
                signal_entry["changes"].append({"time": current_time, "value": raw_value})
                continue

    observations: List[Dict[str, object]] = []
    for signal_name, payload in values.items():
        changes = payload.get("changes", [])
        if not changes:
            continue
        observations.append(
            _adapt_observation(signal_name, "fallback", changes, max_changes=max_changes)
        )
    return observations


def convert_one(
    fst_path: str,
    output_dir: str,
    converter: Optional[str] = None,
    signal_hints: Sequence[str] = (),
) -> Dict[str, object]:
    converter_path = converter or resolve_fst2vcd()
    result = {
        "input_path": os.path.abspath(fst_path),
        "output_path": "",
        "converter": converter_path or "",
        "signal_hints": [item for item in signal_hints if item],
        "waveform_observations": [],
        "status": "missing_tool",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    if not converter_path:
        result["stderr"] = "fst2vcd binary is unavailable"
        return result
    if not os.path.exists(fst_path):
        result["status"] = "missing_input"
        result["stderr"] = "input fst file is missing"
        return result

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir,
        os.path.splitext(os.path.basename(fst_path))[0] + ".vcd",
    )
    completed = subprocess.run(
        [converter_path, "-o", output_path, fst_path],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result.update(
        {
            "output_path": output_path,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "status": "converted" if completed.returncode == 0 else "conversion_failed",
        }
    )
    if completed.returncode == 0 and not os.path.exists(output_path):
        result["status"] = "conversion_missing_output"
        result["stderr"] = result["stderr"] or "converter returned success but output file was not created"
    if completed.returncode == 0 and os.path.exists(output_path):
        result["waveform_observations"] = parse_vcd_observations(output_path, signal_hints=result["signal_hints"])
    return result


def build_report(results: List[Dict[str, object]], output_dir: str) -> Dict[str, object]:
    summary = {
        "total": len(results),
        "converted": sum(1 for item in results if item.get("status") == "converted"),
        "missing_tool": sum(1 for item in results if item.get("status") == "missing_tool"),
        "missing_input": sum(1 for item in results if item.get("status") == "missing_input"),
        "conversion_failed": sum(1 for item in results if item.get("status") == "conversion_failed"),
        "conversion_missing_output": sum(1 for item in results if item.get("status") == "conversion_missing_output"),
        "signal_hint_count": sum(len(item.get("signal_hints", [])) for item in results),
        "observation_count": sum(len(item.get("waveform_observations", [])) for item in results),
    }
    report = {
        "output_dir": os.path.abspath(output_dir),
        "summary": summary,
        "results": results,
    }
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "waveform_conversion.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(output_dir, "waveform_summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(output_dir, "waveform_conversion.md"), "w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    return report


def render_markdown(report: Dict[str, object]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Waveform Conversion Report",
        "",
        f"- Total inputs: `{summary.get('total', 0)}`",
        f"- Converted: `{summary.get('converted', 0)}`",
        f"- Missing tool: `{summary.get('missing_tool', 0)}`",
        f"- Missing input: `{summary.get('missing_input', 0)}`",
        f"- Conversion failed: `{summary.get('conversion_failed', 0)}`",
        f"- Signal hints: `{summary.get('signal_hint_count', 0)}`",
        f"- Observations: `{summary.get('observation_count', 0)}`",
        "",
        "| Input | Status | Output | Converter | Signal Hints | Observations |",
        "|---|---|---|---|---|---|",
    ]
    for item in report.get("results", []):
        lines.append(
            f"| `{item.get('input_path')}` | `{item.get('status')}` | "
            f"`{item.get('output_path') or 'n/a'}` | `{item.get('converter') or 'n/a'}` | "
            f"`{', '.join(item.get('signal_hints', [])) or 'n/a'}` | "
            f"`{len(item.get('waveform_observations', []))}` |"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert FST waveform files to VCD using GTKWave fst2vcd")
    parser.add_argument("--input", action="append", default=[], help="Input FST file or directory; repeatable")
    parser.add_argument("--input-dir", action="append", default=[], help="Input directory containing FST files; repeatable")
    parser.add_argument("--output-dir", required=True, help="Directory to write conversion artifacts")
    parser.add_argument("--converter", default="", help="Optional explicit fst2vcd path")
    parser.add_argument("--signal-hint", action="append", default=[], help="Optional candidate signal hint; repeatable")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    inputs = list(args.input) + list(args.input_dir)
    fst_files = discover_fst_files(inputs)
    results = [
        convert_one(path, args.output_dir, converter=args.converter or None, signal_hints=args.signal_hint)
        for path in fst_files
    ]
    report = build_report(results, args.output_dir)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["converted"] or report["summary"]["total"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
