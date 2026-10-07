"""Normalize third-party unitytest case products into bug_review input shape.

The Bug Review plugin reads original reports from
``unity_test/<module>_bug_summary.md`` and ``unity_test/<module>_bug_analysis.md``.
Older case products embed Bug claims in bullets, standalone tag lines, or
higher-level headings, omit the summary table, use short ``<TC-...>`` labels,
or miss the documents entirely. This script rewrites those products in place
(or into ``--output-dir`` copies) so the plugin's own parsers accept them:

- bullets and standalone ``<BG-...>`` lines become six-level ``######`` claim
  headings whose body keeps the original text, tags and TC references;
- ``<BG-...>`` headings at levels 1-5 are demoted to level 6;
- short ``<TC-file.py::node>`` labels gain the ``unity_test/tests/`` prefix
  when the referenced test file exists;
- a missing summary is generated from the converted claim blocks; a summary
  that already matches the analysis identities is kept byte-for-byte;
- missing report documents become explicit empty templates.

The script is deterministic and idempotent: a product already in canonical
shape is left untouched, and a second run over converted products is a no-op.
It never invents Bug conclusions, waveforms, RTL or launch materials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

BG_TAG = re.compile(r"<BG-([A-Za-z0-9_-]+)>")
TC_TAG = re.compile(r"<TC-([^>]+)>")
CK_TAG = re.compile(r"<CK-([A-Za-z0-9_-]+)>")
ANY_TAG = re.compile(r"<(?:BG|TC|CK|FG|FC)-[A-Za-z0-9_./:+=-]*>")
SECTION_HEADING = re.compile(r"^#{1,5}\s")
HEADING_BG = re.compile(r"^(#{1,5})\s+.*<BG-[A-Za-z0-9_-]+>")
BULLET = re.compile(r"^\s*-\s+")
BARE_BG_LINE = re.compile(r"^\s*<BG-[A-Za-z0-9_-]+>\s*$")
IDENTITY_SUFFIX = re.compile(r"-(\d+)$")
SHORT_TC = re.compile(r"<TC-([A-Za-z0-9_./-]+\.py::[A-Za-z0-9_.:+-]+)>")
RTL_REF = re.compile(r"[A-Za-z0-9_./-]+\.(?:sv|v):\d+(?:-\d+)?")
SUMMARY_NAME = re.compile(r"[A-Za-z0-9_-]+")
REF_RANGE = re.compile(r"bug_analysis\.md:(\d+)-(\d+)")
CANONICAL_TC_PREFIX = "unity_test/tests/"
SUMMARY_COLUMNS = ("Name", "Severity", "Alias", "CK", "Analysis", "Locations",
                   "Confidence", "Ref")
COPY_EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "uc_test_report"}
COPY_EXCLUDE_FILE = re.compile(r"^(\.coverage-report-|toffee_tmp_)")
MAX_HEADING_CHARS = 80
MAX_SUMMARY_CHARS = 160


def skill_resource(name: str) -> Path:
    """Resolve one bundled skill resource next to this script."""
    return Path(__file__).resolve().parent.parent / "templates" / name


def load_confidence_pattern() -> re.Pattern:
    """Load the corpus confidence-clause pattern from the bundled resource."""
    pattern = json.loads(skill_resource("patterns.json").read_text(encoding="utf-8"))
    return re.compile(pattern["confidence_clause"])


CONFIDENCE_CLAUSE = load_confidence_pattern()


def eol_join(text: str, lines: list[str]) -> str:
    """Rejoin lines with the file's dominant line ending, preserving EOI newline."""
    eol = "\r\n" if text.count("\r\n") * 2 > text.count("\n") else "\n"
    body = eol.join(lines)
    return body + eol if text.endswith(("\n", "\r")) else body


def read_text(path: Path) -> str | None:
    """Read one document as UTF-8 text, returning None when it is unreadable."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def parse_claim_blocks(lines: list[str]) -> list[dict]:
    """Mirror the plugin's claim-block reader: level-6 headings carrying <BG-...>."""
    headings = [number for number, line in enumerate(lines, 1)
                if SECTION_HEADING.match(line)
                or (line.startswith("###### ") and BG_TAG.search(line))]
    blocks = []
    for position, start in enumerate(headings):
        if not lines[start - 1].startswith("###### "):
            continue
        label = BG_TAG.search(lines[start - 1])
        if label is None:
            continue
        end = headings[position + 1] - 1 if position + 1 < len(headings) else len(lines)
        text = "\n".join(lines[start - 1:end])
        blocks.append({"start": start, "end": end, "tag": label.group(1),
                       "identity": IDENTITY_SUFFIX.sub("", label.group(1)),
                       "tc_labels": sorted(set(TC_TAG.findall(text))),
                       "ck": sorted(set(CK_TAG.findall(text))),
                       "rtl": sorted(set(RTL_REF.findall(text))),
                       "body_first": next((line for line in lines[start:end]
                                           if line.strip()
                                           and not ANY_TAG.fullmatch(line.strip())), "")})
    return blocks


def strip_tags(text: str) -> str:
    """Remove machine tags, the confidence clause and trailing punctuation."""
    text = CONFIDENCE_CLAUSE.sub("", ANY_TAG.sub("", text))
    text = re.sub(r"\s+", " ", text).strip()
    while text and not text[-1].isalnum():
        text = text[:-1].rstrip()
    return text


def claim_heading(tag: str, description: str) -> str:
    """Build one canonical level-6 claim heading line from a captured BG name."""
    head = description[:MAX_HEADING_CHARS] if description else IDENTITY_SUFFIX.sub("", tag)
    confidence = IDENTITY_SUFFIX.search(tag)
    label = f" ({confidence.group(1)}%)" if confidence and int(confidence.group(1)) <= 100 else ""
    return f"###### {head}{label} <BG-{tag}>"


def needs_conversion(lines: list[str]) -> bool:
    """Report whether any pre-canonical BG shape (bullet, bare line, H1-5) remains."""
    for line in lines:
        if HEADING_BG.match(line) or BARE_BG_LINE.match(line):
            return True
        if BULLET.match(line) and BG_TAG.search(line):
            return True
    return False


def convert_analysis(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Rewrite bullets, bare BG lines and H1-5 BG headings into canonical blocks.

    Returns the new lines, performed action names and anomaly notes. The
    original prose, nested bullets and non-BG tags stay in each block body.
    """
    out: list[str] = []
    actions: list[str] = []
    anomalies: list[str] = []

    def emit(line: str) -> None:
        """Append one line, keeping a blank line before every heading."""
        if line.startswith("#") and out and out[-1].strip():
            out.append("")
        out.append(line)

    index = 0
    while index < len(lines):
        line = lines[index]
        if HEADING_BG.match(line):
            emit("###### " + re.sub(r"^#{1,5}\s+", "", line))
            actions.append("demoted_h1_h5_bg_heading")
            index += 1
            continue
        if BARE_BG_LINE.match(line):
            tag = BG_TAG.search(line).group(1)
            prose: list[str] = []
            ahead = index + 1
            while (ahead < len(lines) and not HEADING_BG.match(lines[ahead])
                   and not BARE_BG_LINE.match(lines[ahead])
                   and not (BULLET.match(lines[ahead]) and BG_TAG.search(lines[ahead]))):
                prose.append(lines[ahead])
                ahead += 1
            description = next((strip_tags(item) for item in prose if strip_tags(item)), "")
            emit(claim_heading(tag, description))
            for item in prose:
                emit(item)
            actions.append("converted_bare_bg_line")
            index = ahead
            continue
        if BULLET.match(line) and BG_TAG.search(line):
            tags = BG_TAG.findall(line)
            indent = len(line) - len(line.lstrip(" "))
            body: list[str] = []
            ahead = index + 1
            while ahead < len(lines):
                nested = lines[ahead]
                nested_indent = len(nested) - len(nested.lstrip(" "))
                if nested.strip() and nested_indent <= indent:
                    break
                body.append(nested[indent + 2:] if len(nested) > indent + 2 else nested.lstrip())
                ahead += 1
            if len(tags) > 1:
                anomalies.append(
                    f"line {index + 1}: bullet carries {len(tags)} BG tags "
                    f"({', '.join(tags)}); emitted one heading per tag, body kept under the first")
            description = strip_tags(re.sub(r"^\s*-\s+", "", line))
            remainder = BG_TAG.sub("", line.lstrip()[2:]).rstrip()
            for offset, match in enumerate(BG_TAG.finditer(line)):
                emit(claim_heading(match.group(1), description if offset == 0 else ""))
                if offset == 0:
                    if remainder.strip():
                        emit(remainder)
                    out.extend(body)
            actions.append("converted_bullet_bg")
            index = ahead
            continue
        emit(line)
        index += 1
    return out, actions, anomalies


def expand_short_tc_lines(lines: list[str], tests_dir: Path) -> tuple[list[str], bool, list[str]]:
    """Prefix short ``<TC-file.py::node>`` labels whose test file exists."""
    out: list[str] = []
    changed = False
    anomalies: list[str] = []

    def canonical_label(label: str) -> str | None:
        """Return the canonical ``unity_test/tests/`` label, or None when unresolvable."""
        relative = label.split("::", 1)[0]
        if ".." in relative:
            return None
        if not (tests_dir / relative.removeprefix("tests/")).is_file():
            return None
        return CANONICAL_TC_PREFIX + label.removeprefix("tests/")

    def replace(match: re.Match) -> str:
        label = match.group(1)
        if label.startswith(CANONICAL_TC_PREFIX):
            return match.group(0)
        found = canonical_label(label)
        return f"<TC-{found}>" if found else match.group(0)

    for number, line in enumerate(lines, 1):
        for match in SHORT_TC.finditer(line):
            label = match.group(1)
            if label.startswith(CANONICAL_TC_PREFIX):
                continue
            if canonical_label(label) is None:
                anomalies.append(
                    f"line {number}: short TC label <TC-{label}> left unchanged: "
                    f"no matching file under {tests_dir}")
        expanded = SHORT_TC.sub(replace, line)
        changed = changed or expanded != line
        out.append(expanded)
    return out, changed, anomalies


def parse_summary_rows(text: str) -> tuple[list[dict], list[str]]:
    """Mirror the plugin's summary reader and return its rows and validation issues."""
    rows: list[dict] = []
    issues: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in {"Name", "---"}:
            continue
        if not SUMMARY_NAME.fullmatch(cells[0]):
            issues.append(f"line {number}: invalid Bug name {cells[0]!r}")
            continue
        if any(row["name"] == cells[0] for row in rows):
            issues.append(f"line {number}: duplicate Bug name {cells[0]!r}")
            continue
        rows.append({"name": cells[0], "line": number,
                     "ranges": [(int(a), int(b)) for a, b in REF_RANGE.findall(cells[7])]})
    return rows, issues


def escape_cell(text: str) -> str:
    """Escape text for one summary table cell."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("|", "\\|"))


def generate_summary(module: str, analysis_name: str, blocks: list[dict]) -> str:
    """Render the canonical eight-column summary from converted claim blocks."""
    grouped: dict[str, dict] = {}
    for block in blocks:
        entry = grouped.setdefault(block["identity"], {
            "ranges": [], "ck": set(), "rtl": set(), "body": ""})
        entry["ranges"].append((block["start"], block["end"]))
        entry["ck"].update(block["ck"])
        entry["rtl"].update(block["rtl"])
        if not entry["body"]:
            entry["body"] = strip_tags(block["body_first"]).lstrip("- ")[:MAX_SUMMARY_CHARS]
    rows = []
    for identity, entry in grouped.items():
        confidence = ""
        for block in blocks:
            if block["identity"] == identity:
                match = IDENTITY_SUFFIX.search(block["tag"])
                if match and int(match.group(1)) <= 100:
                    confidence = f"{int(match.group(1)) / 100:.2f}"
                break
        refs = ", ".join(f"unity_test/{analysis_name}:{start}-{end}"
                         for start, end in entry["ranges"])
        locations = "<br>".join(sorted(entry["rtl"]))
        ck = " ".join(f"CK-{name}" for name in entry["ck"])
        rows.append(f"| {identity} |  |  | {escape_cell(ck)} | {escape_cell(entry['body'])} "
                    f"| {escape_cell(locations)} | {confidence} | {refs} |")
    lines_out = [f"# {module} Bug Summary", "", f"Total Bugs: {len(rows)}", "",
                 "| " + " | ".join(SUMMARY_COLUMNS) + " |",
                 "| " + " | ".join("---" for _ in SUMMARY_COLUMNS) + " |", *rows]
    return "\n".join(lines_out) + "\n"


def render_empty_template(kind: str, module: str) -> str:
    """Render one explicit empty-template document for a missing report."""
    return skill_resource(f"bug_{kind}_empty.template.md").read_text(
        encoding="utf-8").replace("{module}", module)


def resolve_report_file(unity_dir: Path, module: str, kind: str) -> tuple[Path | None, list[str]]:
    """Locate ``<module>_bug_<kind>.md``, reporting one drifted sibling when found."""
    canonical = unity_dir / f"{module}_bug_{kind}.md"
    if canonical.is_file():
        return canonical, []
    suffix = f"_bug_{kind}"
    drifted = sorted(path for path in unity_dir.glob(f"*{suffix}.md")
                     if path.stem[: -len(suffix)] != module
                     and not path.stem[: -len(suffix)].endswith("_static"))
    return (drifted[0], [f"renamed {drifted[0].name} -> {canonical.name}"]) if drifted \
        else (None, [])


def launch_materials(module_dir: Path, module: str) -> list[str]:
    """List launch materials whose absence blocks Make/Master compilation."""
    missing = []
    if not (module_dir / "launch.yaml").is_file():
        missing.append("launch.yaml")
    if not any((module_dir / name).is_file() for name in ("filelist.f", "filelist.txt")):
        missing.append("filelist.f")
    if not (module_dir / module).is_dir():
        missing.append(f"{module}/ runtime package")
    return missing


def copy_module(module_dir: Path, dest_dir: Path) -> None:
    """Copy one module for output-dir mode, excluding generated test artifacts."""
    def ignore(directory: str, names: list[str]) -> list[str]:
        return [name for name in names
                if name in COPY_EXCLUDE_DIRS or COPY_EXCLUDE_FILE.match(name)]

    shutil.copytree(module_dir, dest_dir, ignore=ignore, symlinks=True)


def backup_file(path: Path, backup_dir: Path, case_root: Path) -> str:
    """Preserve the original bytes of one file before its first in-place rewrite."""
    if not path.exists():
        return ""
    target = backup_dir / path.relative_to(case_root)
    if target.exists():
        return f"backup kept: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return f"backed up: {target}"


def write_document(path: Path, text: str, opts: argparse.Namespace,
                   case_root: Path, performed: list[str]) -> None:
    """Write one document according to the selected output mode."""
    if opts.dry_run:
        performed.append(f"would write: {path.name}")
        return
    if opts.output_dir is None:
        note = backup_file(path, Path(opts.backup_dir), case_root)
        if note:
            performed.append(note)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    performed.append(f"wrote: {path.name}")


def normalize_analysis(unity_dir: Path, tests_dir: Path, module: str, source: Path,
                       opts: argparse.Namespace, case_root: Path,
                       report: dict) -> tuple[list[dict], str]:
    """Convert or verify one analysis document and return (blocks, final_text)."""
    text = read_text(source)
    if text is None:
        report["anomalies"].append(f"{source.name} is not readable UTF-8; left unchanged")
        return [], ""
    lines = text.splitlines()
    if needs_conversion(lines):
        lines, actions, anomalies = convert_analysis(lines)
        report["analysis"] = "converted"
        report["anomalies"].extend(dict.fromkeys(anomalies))
        for action in dict.fromkeys(actions):
            if action not in report["performed"]:
                report["performed"].append(action)
    else:
        report["analysis"] = "canonical"
    if parse_claim_blocks(lines):
        lines, changed, anomalies = expand_short_tc_lines(lines, tests_dir)
        report["anomalies"].extend(dict.fromkeys(anomalies))
        if changed and "expanded_short_tc_label" not in report["performed"]:
            report["performed"].append("expanded_short_tc_label")
    final_text = eol_join(text, lines)
    if final_text != text:
        write_document(unity_dir / f"{module}_bug_analysis.md", final_text,
                       opts, case_root, report["performed"])
    return parse_claim_blocks(final_text.splitlines()), final_text


def process_module(module_dir: Path, opts: argparse.Namespace,
                   duplicate_of: str | None) -> dict:
    """Normalize one module and return its report entry."""
    module = module_dir.name
    case_root = Path(opts.case_root)
    report: dict = {"module": module, "status": "normalized", "analysis": "kept",
                    "summary": "kept", "bugs": 0, "performed": [], "renames": [],
                    "anomalies": [], "duplicate_of": duplicate_of, "missing_optional": [],
                    "launch_materials_missing": launch_materials(module_dir, module)}
    work_dir = module_dir
    if opts.output_dir is not None and not opts.dry_run:
        work_dir = Path(opts.output_dir) / module
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        copy_module(module_dir, work_dir)
        report["performed"].append(f"copied to {work_dir}")
    if duplicate_of:
        report["status"] = "skipped_duplicate"
        report["anomalies"].append(
            f"AGENTS.md identical to {duplicate_of}; normalized the richer twin only")
        return report
    if not (work_dir / "unity_test" / "tests").is_dir() or \
            not any((work_dir / "unity_test" / "tests").glob("test_*.py")):
        report["status"] = "skipped_no_tests"
        return report
    unity_dir = work_dir / "unity_test"
    tests_dir = unity_dir / "tests"

    sources: dict[str, Path] = {}
    for kind in ("analysis", "summary"):
        drifted, notes = resolve_report_file(unity_dir, module, kind)
        report["renames"].extend(notes)
        if notes:
            canonical = unity_dir / f"{module}_bug_{kind}.md"
            if opts.dry_run:
                report["performed"].append(
                    f"would rename: {drifted.name} -> {canonical.name}")
            else:
                if opts.output_dir is None:
                    report["performed"].append(
                        backup_file(drifted, Path(opts.backup_dir), case_root))
                drifted.rename(canonical)
        sources[kind] = (unity_dir / f"{module}_bug_{kind}.md") if not opts.dry_run or not notes \
            else drifted
    analysis_missing = not sources["analysis"].is_file()
    if analysis_missing:
        report["analysis"] = "created_empty" if not opts.dry_run else "would_create_empty"
        write_document(unity_dir / f"{module}_bug_analysis.md",
                       render_empty_template("analysis", module),
                       opts, case_root, report["performed"])
        blocks, final_text = [], ""
    else:
        blocks, final_text = normalize_analysis(
            unity_dir, tests_dir, module, sources["analysis"], opts, case_root, report)
    report["bugs"] = len({block["identity"] for block in blocks})

    summary_path = unity_dir / f"{module}_bug_summary.md"
    summary_text = read_text(sources["summary"]) if sources["summary"].is_file() else None
    if summary_text is not None:
        rows, issues = parse_summary_rows(summary_text)
        names = {row["name"] for row in rows}
        if issues or names != {block["identity"] for block in blocks}:
            report["anomalies"].append(
                "existing summary does not match analysis identities "
                f"({'; '.join(issues) or 'name sets differ'}); regenerated")
            report["summary"] = "regenerated"
            write_document(summary_path,
                           generate_summary(module, f"{module}_bug_analysis.md", blocks),
                           opts, case_root, report["performed"])
        else:
            report["summary"] = "valid_kept"
    elif report["bugs"]:
        report["summary"] = "generated" if not opts.dry_run else "would_generate"
        write_document(summary_path,
                       generate_summary(module, f"{module}_bug_analysis.md", blocks),
                       opts, case_root, report["performed"])
    elif analysis_missing:
        report["summary"] = "created_empty" if not opts.dry_run else "would_create_empty"
        write_document(summary_path, render_empty_template("summary", module),
                       opts, case_root, report["performed"])
    else:
        report["summary"] = "not_needed"

    for path in sorted(unity_dir.glob("*.md")):
        name = path.name
        if name in {f"{module}_bug_analysis.md", f"{module}_bug_summary.md"}:
            continue
        if re.fullmatch(rf"{re.escape(module)}_\w+\.md", name):
            report["missing_optional"].append(name)
        else:
            report["anomalies"].append(f"stray document not matching module name: {name}")
    return report


def select_modules(opts: argparse.Namespace) -> tuple[list[Path], dict[str, str]]:
    """List module directories and map duplicate AGENTS.md twins to their canonical twin."""
    root = Path(opts.case_root)
    modules = sorted(path for path in root.iterdir()
                     if path.is_dir() and not path.name.startswith(".")
                     and (path / "unity_test").is_dir())
    digests: dict[str, list[Path]] = {}
    for path in modules:
        agents = path / "AGENTS.md"
        if agents.is_file():
            digest = hashlib.sha256(agents.read_bytes()).hexdigest()
            digests.setdefault(digest, []).append(path)
    duplicates: dict[str, str] = {}
    for group in digests.values():
        if len(group) < 2:
            continue
        ranked = sorted(group, key=lambda path: (
            -sum(1 for item in path.rglob("*") if item.is_file()), path.name))
        for path in ranked[1:]:
            duplicates[path.name] = ranked[0].name
    if opts.module:
        chosen = [root / opts.module]
        if not chosen[0].is_dir():
            raise SystemExit(f"module directory not found: {chosen[0]}")
    else:
        chosen = modules
    return chosen, duplicates


def main(argv: list[str] | None = None) -> int:
    """Normalize selected case modules and print the aggregate report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case-root", required=True,
                        help="root directory holding module directories")
    parser.add_argument("--module", help="normalize one module directory name")
    parser.add_argument("--all", action="store_true", help="normalize every module")
    parser.add_argument("--dry-run", action="store_true",
                        help="report planned actions without writing anything")
    parser.add_argument("--output-dir",
                        help="copy each module here and normalize the copy; "
                             "the corpus stays untouched")
    parser.add_argument("--report", help="write the aggregate JSON report to this path")
    parser.add_argument("--backup-dir",
                        help="in-place rewrite backups (default <case-root>/.normalization_backup)")
    opts = parser.parse_args(argv)
    if not opts.module and not opts.all:
        parser.error("select --module <name> or --all")
    if opts.module and opts.all:
        parser.error("--module and --all are mutually exclusive")
    opts.backup_dir = opts.backup_dir or str(Path(opts.case_root) / ".normalization_backup")
    modules, duplicates = select_modules(opts)
    reports = [process_module(module_dir, opts, duplicates.get(module_dir.name))
               for module_dir in modules]
    counts: dict[str, int] = {}
    for report in reports:
        counts[report["status"]] = counts.get(report["status"], 0) + 1
    print(f"modules: {len(reports)}  " +
          "  ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    for report in reports:
        notes = "; ".join(report["performed"] + report["renames"] + report["anomalies"])
        print(f"{report['module']:32s} {report['status']:18s} "
              f"analysis={report['analysis']:18s} summary={report['summary']:14s} "
              f"bugs={report['bugs']}{('  ' + notes) if notes else ''}")
    if opts.report:
        Path(opts.report).write_text(json.dumps(
            {"case_root": str(Path(opts.case_root).resolve()),
             "dry_run": opts.dry_run, "output_dir": opts.output_dir,
             "backup_dir": opts.backup_dir, "modules": reports},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {opts.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
