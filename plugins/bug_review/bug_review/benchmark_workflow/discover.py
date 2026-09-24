"""Discover for the Bug Review workflow."""
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from typing import Dict, List, Optional, Tuple

from .models import ArtifactManifest
from .line_coverage_refresh import load_line_coverage_snapshot
from .rtl_refs import discover_rtl_files
from .utils import get_logger, sha256_file, sha256_text, slugify

logger = get_logger(__name__)

_ALL_COMPLETED_RE = re.compile(rb"all_completed:\s*(true|false)", re.IGNORECASE)
_TERMINAL_COMPLETION_RE = re.compile(
    rb"(?:"
    rb"^\s*\[[^\r\n]*\]\s*DONE\s+stage\s*=\s*28\s*$"
    rb"|message:\s*All stages completed\.\s*Exiting the mission\."
    # Some UCAgent versions finish the 28-stage supervisor with a successful
    # Complete tool result but do not emit the legacy DONE/Exit wording.
    # Require all three fields in one bounded record so an intermediate
    # ``complete: false`` cannot be mistaken for a terminal success.
    rb"|ToolComplete\s*:\s*.{0,512}?complete:\s*true.{0,512}?"
    rb"message:\s*['\"]?All stages completed successfully\."
    # Newer/specialized runners can report the final successful transition
    # through ToolExit instead of ToolComplete.  Keep the ToolExit and
    # ``complete: true`` requirements so a normal intermediate
    # ``Stage N completed successfully`` message is never sufficient alone.
    rb"|ToolExit\s*:\s*.{0,512}?complete:\s*true.{0,512}?"
    rb"message:\s*['\"]?(?:All stages completed(?: successfully)?|"
    rb"Stage\s+\d+\s+completed successfully)\."
    rb")",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _read_ucagent_completion(workspace_root: str) -> Tuple[Optional[bool], Optional[str]]:
    """Read UCAgent's persisted mission state when detached logs are absent.

    Exported workspaces do not always retain their sibling ``run_1/logs``
    directory, but ``.ucagent/ucagent_info.json`` is part of the workspace and
    carries the authoritative boolean completion state.  Only a real JSON
    boolean is accepted; strings and inferred stage counts are deliberately
    rejected.
    """
    status_path = os.path.join(workspace_root, ".ucagent", "ucagent_info.json")
    try:
        with open(status_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None, None
    except (OSError, json.JSONDecodeError):
        logger.warning("failed to read UCAgent completion state: %s", status_path, exc_info=True)
        return None, None
    if not isinstance(payload, dict) or not isinstance(payload.get("all_completed"), bool):
        return None, None
    return payload["all_completed"], status_path


def _log_contains_terminal_completion(log_path: str) -> bool:
    """Return whether a log contains an authoritative successful run terminus.

    ``all_completed: false`` is emitted by intermediate Status tool calls and
    can remain the last Status snapshot even after the workflow exits normally.
    Supervisor completion and the successful Exit message are terminal events,
    so they take precedence over those intermediate snapshots.
    """
    chunk_size = 1024 * 1024
    overlap = b""
    try:
        with open(log_path, "rb") as handle:
            position = handle.seek(0, os.SEEK_END)
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size) + overlap
                if _TERMINAL_COMPLETION_RE.search(chunk):
                    return True
                overlap = chunk[:256]
    except OSError:
        logger.warning("failed to read run completion evidence: %s", log_path, exc_info=True)
    return False


def _read_last_all_completed(log_path: str) -> Optional[bool]:
    """Read the last UCAgent completion marker without loading a large log."""
    chunk_size = 1024 * 1024
    overlap = b""
    try:
        with open(log_path, "rb") as handle:
            position = handle.seek(0, os.SEEK_END)
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size) + overlap
                matches = list(_ALL_COMPLETED_RE.finditer(chunk))
                if matches:
                    return matches[-1].group(1).lower() == b"true"
                # Preserve enough bytes to recognize a marker split at a chunk
                # boundary while walking backwards through the file.
                overlap = chunk[:64]
    except OSError:
        logger.warning("failed to read run completion status: %s", log_path, exc_info=True)
    return None


def _discover_completion_status(workspace_root: str) -> Tuple[Optional[bool], Optional[str]]:
    candidates: List[str] = []
    search_roots = [workspace_root]
    # Archive-based runs commonly use ``run_1/ucagent_work`` as the artifact
    # workspace while keeping completion logs in the sibling ``run_1/logs``.
    if os.path.basename(os.path.normpath(workspace_root)) == "ucagent_work":
        search_roots.append(os.path.dirname(os.path.normpath(workspace_root)))
    for root in search_roots:
        for pattern in ("run*.log", "logs/ucagent*.log", "logs/supervisor.log"):
            candidates.extend(glob.glob(os.path.join(root, pattern)))
    candidates = sorted(set(candidates), key=lambda path: (-os.path.getmtime(path), path))

    # A terminal success event is stronger than any earlier Status snapshot.
    # Check every run log before consulting all_completed markers so that an
    # intermediate ``false`` cannot hide a later supervisor/Exit completion.
    for path in candidates:
        if _log_contains_terminal_completion(path):
            return True, path

    persisted_status, persisted_evidence = _read_ucagent_completion(workspace_root)
    if persisted_status is True:
        return True, persisted_evidence

    marker_statuses = [(path, _read_last_all_completed(path)) for path in candidates]
    for path, status in marker_statuses:
        if status is True:
            return True, path
    for path, status in marker_statuses:
        if status is False:
            return False, path
    if persisted_status is False:
        return False, persisted_evidence
    return None, None


def _extract_archive(input_path: str) -> Tuple[str, str, List[str]]:
    tempdir = tempfile.mkdtemp(prefix="benchmark_workflow_")
    problems: List[str] = []
    lower = input_path.lower()
    if lower.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(input_path, "r:*") as archive:
            archive.extractall(tempdir)
        return tempdir, "archive_tar", problems
    if lower.endswith(".7z"):
        seven_zip = shutil.which("7z")
        if not seven_zip:
            problems.append("7z archive support requested but 7z binary is unavailable")
            logger.warning("7z binary not found in PATH, archive extraction may fail: %s", input_path)
            return tempdir, "archive_7z", problems
        subprocess.run(
            [seven_zip, "x", input_path, f"-o{tempdir}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return tempdir, "archive_7z", problems
    raise ValueError(f"unsupported input format: {input_path}")


def _materialise_input(input_path: str) -> Tuple[str, str, List[str]]:
    if os.path.isdir(input_path):
        return input_path, "workspace_dir", []
    return _extract_archive(input_path)


def _find_all_workspace_roots(*search_roots: str, native_ucagent: bool = False) -> List[str]:
    candidates = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if native_ucagent and os.path.isfile(os.path.join(dirpath, ".ucagent", "ucagent_info.json")) and "unity_test" in dirnames:
                candidates.append(dirpath)
            # A workspace launched directly through UnityTest can be a valid
            # analysis input before UCAgent has written ucagent_info.json or a
            # toffee report. Runtime configuration plus an actual test suite
            # and DUT build/RTL directory is sufficient to admit it as an
            # incomplete native run; later stages will execute the tests and
            # record any missing report as evidence, not as "no run".
            if native_ucagent and os.path.isfile(os.path.join(dirpath, ".ucagent", "runtime_config.json")) and "unity_test" in dirnames:
                unity_tests = os.path.join(dirpath, "unity_test", "tests")
                dut_dirs = [name for name in dirnames if name not in {"unity_test", "Guide_Doc"}]
                if os.path.isdir(unity_tests) and dut_dirs:
                    candidates.append(dirpath)
            if "toffee_report.json" in filenames and os.path.basename(dirpath) == "uc_test_report":
                candidates.append(os.path.dirname(dirpath))
            # Failed/incomplete exports frequently stop before producing
            # ``uc_test_report/toffee_report.json``.  They are still real run
            # workspaces and must reach the completion gate so reports can say
            # "found but incomplete" instead of "no recognizable run".
            # Requiring run_info plus UCAgent/work-product structure avoids
            # treating arbitrary metadata directories as benchmark runs.
            if "run_info.json" in filenames and (
                ".ucagent" in dirnames
                or "unity_test" in dirnames
                or any(name.startswith("run") and name.endswith(".log") for name in filenames)
            ):
                candidates.append(dirpath)
            if native_ucagent:
                dirnames[:] = [name for name in dirnames if name not in {".git", ".ucagent", "__pycache__"}]
    seen: Dict[str, bool] = {}
    unique: List[str] = []
    for c in candidates:
        if c not in seen:
            seen[c] = True
            unique.append(c)
    return unique


def _extract_archives_in_tree(base_root: str, temp_root: str, dut_filter: Optional[List[str]] = None) -> List[str]:
    extracted: List[str] = []
    for dirpath, _, filenames in os.walk(base_root):
        for fname in filenames:
            if not (fname.endswith((".tar.gz", ".tgz", ".tar")) or fname.endswith(".7z")):
                continue
            if dut_filter:
                fname_lower = fname.lower()
                if not any(dut.lower() in fname_lower for dut in dut_filter):
                    continue
            archive_path = os.path.join(dirpath, fname)
            rel_dir = os.path.relpath(dirpath, base_root)
            stem = fname
            for ext in (".tar.gz", ".tgz", ".tar", ".7z"):
                if stem.endswith(ext):
                    stem = stem[: -len(ext)]
                    break
            extract_dir = os.path.join(temp_root, rel_dir, stem)
            os.makedirs(extract_dir, exist_ok=True)
            try:
                if fname.endswith(".7z"):
                    seven_zip = shutil.which("7z")
                    if not seven_zip:
                        logger.warning("7z not available, skipping: %s", fname)
                        continue
                    subprocess.run(
                        [seven_zip, "x", archive_path, f"-o{extract_dir}"],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                else:
                    with tarfile.open(archive_path, "r:*") as archive:
                        archive.extractall(extract_dir)
                extracted.append(extract_dir)
            except Exception as exc:
                logger.warning("failed to extract %s: %s", archive_path, exc)
    return extracted


def _workspace_may_match_dut_filter(
    workspace_root: str, dut_filter: Optional[List[str]],
) -> bool:
    """Cheap, conservative filter before expensive artifact discovery.

    Unknown/generic layouts remain included.  A workspace is skipped only when
    a nearby run_info.json explicitly names another DUT; path tokens can admit
    a target immediately, including extracted archive ancestors.
    """
    if not dut_filter:
        return True
    wanted = {str(dut).strip().lower() for dut in dut_filter if str(dut).strip()}
    lowered_path = os.path.abspath(workspace_root).lower().replace("\\", "/")
    if any(dut in lowered_path for dut in wanted):
        return True
    current = os.path.abspath(workspace_root)
    for _depth in range(4):
        run_info_path = os.path.join(current, "run_info.json")
        if os.path.isfile(run_info_path):
            try:
                with open(run_info_path, "r", encoding="utf-8", errors="ignore") as handle:
                    value = json.load(handle)
                declared = str(value.get("dut") or "").strip().lower()
                if declared:
                    return declared in wanted
            except (OSError, ValueError, json.JSONDecodeError):
                return True
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return True


def _read_line_coverage_rate(workspace_root: str) -> float:
    snapshot = load_line_coverage_snapshot(workspace_root)
    total = int(snapshot.get("total", 0))
    hit = int(snapshot.get("hit", 0))
    if total > 0:
        return hit / total
    return -1.0


def _first_match(root: str, pattern: str) -> Optional[str]:
    matches = sorted(glob.glob(os.path.join(root, pattern), recursive=True))
    return matches[0] if matches else None


def _discover_rtl_root(workspace_root: str) -> Optional[str]:
    candidate_dirs: Dict[str, int] = {}
    for rtl_path in discover_rtl_files(workspace_root):
        parent = os.path.dirname(rtl_path)
        candidate_dirs[parent] = candidate_dirs.get(parent, 0) + 1
    if not candidate_dirs:
        return None
    ranked = sorted(candidate_dirs.items(), key=lambda item: (-item[1], item[0]))
    return ranked[0][0]


def _discover_dut_readme(workspace_root: str, rtl_root: Optional[str], dut: str) -> Optional[str]:
    # 优先精确命中直系目录，毫秒级返回
    if rtl_root and os.path.isfile(os.path.join(rtl_root, "README.md")):
        return os.path.join(rtl_root, "README.md")
    if os.path.isfile(os.path.join(workspace_root, "README.md")):
        return os.path.join(workspace_root, "README.md")
    parent_ws = os.path.dirname(os.path.normpath(workspace_root))
    if os.path.isfile(os.path.join(parent_ws, "README.md")):
        return os.path.join(parent_ws, "README.md")

    from .paths import repository_root
    repo_root = str(repository_root())
    search_roots = [workspace_root]
    # 如果要搜 repo_root，仅搜 inputs 目录，绝不全盘扫 external 等数万文件目录
    inputs_root = os.path.join(repo_root, "inputs")
    if os.path.isdir(inputs_root):
        search_roots.append(inputs_root)
    verification_modules_root = os.path.join(os.path.dirname(repo_root), "verification-benchmark", "modules")
    if os.path.isdir(verification_modules_root):
        search_roots.append(verification_modules_root)

    candidates = []
    seen_paths = set()
    ignored_dirs = {"external", ".git", "outputs", "build", "node_modules", "runtime-rootfs"}
    for root in search_roots:
        for current_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            if "README.md" in files:
                path = os.path.join(current_dir, "README.md")
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                lowered = path.lower()
                if ".pytest_cache" in lowered or "/history/" in lowered or "\\history\\" in lowered:
                    continue
                score = 0
                parent = os.path.basename(os.path.dirname(path)).lower()
                grandparent = os.path.basename(os.path.dirname(os.path.dirname(path))).lower()
                if root == workspace_root:
                    score += 10
                if rtl_root and os.path.dirname(path) == rtl_root:
                    score += 10
                if verification_modules_root in path:
                    score += 6
                if parent == dut.lower():
                    score += 5
                if grandparent == dut.lower():
                    score += 3
                if f"/{dut.lower()}/" in lowered.replace("\\", "/"):
                    score += 2
                candidates.append((score, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def _detect_underlying_llm_model(workspace_root: str, found_files: Dict[str, str]) -> str:
    """Detect the underlying LLM model for an agent harness (e.g. ucagent -> gpt-5.5)."""
    # 1. Search for test_summary.md or basic_info.md in workspace_root / unity_test
    summary_candidates = []
    for pattern in ("unity_test/*_test_summary.md", "unity_test/*_basic_info.md", "*_test_summary.md"):
        matches = glob.glob(os.path.join(workspace_root, pattern))
        summary_candidates.extend(matches)

    model_regex = re.compile(r"(?:使用模型|使用的\s*AI\s*模型|AI\s*模型|模型|Model)\s*[:：*`\s]*([^\n\r*`]+)", re.I)
    for path in summary_candidates:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(8192)
            m = model_regex.search(content)
            if m:
                text = m.group(1).lower()
                if "5.5" in text or "gpt-5.5" in text or "gpt5.5" in text:
                    return "gpt-5.5"
                if "gpt-5" in text or "gpt5" in text or "codex" in text:
                    return "gpt-5.5"
                if "gpt-4" in text or "gpt4" in text:
                    return "gpt-4"
                if "qwen" in text:
                    return "qwen"
                if "claude" in text:
                    return "claude"
        except OSError:
            pass

    lowered = workspace_root.lower()
    if "xiangshan" in lowered or "bosc" in lowered:
        return "gpt-5.5"
    return "gpt-5.5"


def _infer_dut_and_model(workspace_root: str, found_files: Dict[str, str]) -> Tuple[str, str]:
    dut = slugify(os.path.basename(workspace_root))
    model = "unknown_model"
    run_info_path = found_files.get("run_info")
    if run_info_path and os.path.exists(run_info_path):
        with open(run_info_path, "r", encoding="utf-8", errors="ignore") as handle:
            run_info = json.load(handle)
        dut = run_info.get("dut", dut)
        raw_model = run_info.get("model", model)
        if raw_model == "ucagent":
            model = _detect_underlying_llm_model(workspace_root, found_files)
        else:
            model = raw_model
        return dut, model


    workspace_name = os.path.basename(os.path.normpath(workspace_root))
    if workspace_name.startswith("workspace_") and len(workspace_name) > len("workspace_"):
        dut = workspace_name[len("workspace_"):]

    lowered = workspace_root.lower()
    if "gpt" in lowered:
        model = "gpt"
    elif "qwen" in lowered:
        model = "qwen"
    elif "agentworld" in lowered or "agentw" in lowered:
        model = "agentworld"

    parent = os.path.basename(os.path.dirname(workspace_root))
    if dut in {"run_1", "ucagent_work", "duts"} and parent and parent not in {"duts", "run_1", "ucagent_work", "input_runs"}:
        dut = parent
    if dut in {"run_1", "ucagent_work", "duts"}:
        bug_analysis_path = found_files.get("bug_analysis")
        if bug_analysis_path:
            bug_basename = os.path.basename(bug_analysis_path)
            if bug_basename.endswith("_bug_analysis.md"):
                dut = slugify(bug_basename[: -len("_bug_analysis.md")])
        if dut in {"run_1", "ucagent_work", "duts"}:
            signals_path = found_files.get("signals_json")
            if signals_path:
                signals_parent = os.path.basename(os.path.dirname(signals_path))
                if signals_parent and signals_parent not in {"run_1", "ucagent_work", "duts"}:
                    dut = slugify(signals_parent)
    return dut, model


def _looks_like_compact_sample(
    found_files: Dict[str, str],
    tests_root: Optional[str],
    rtl_root: Optional[str],
) -> bool:
    return bool(
        found_files.get("bug_analysis")
        and found_files.get("coverage_merged_dat")
        and not tests_root
        and not found_files.get("functions_and_checks")
        and not rtl_root
    )


def _build_manifest(
    workspace_root: str,
    input_path: str,
    source_type: str,
    materialise_problems: List[str],
    model_label: Optional[str] = None,
    native_ucagent: bool = False,
) -> ArtifactManifest:
    found_files = {
        "toffee_report": _first_match(workspace_root, "uc_test_report/toffee_report.json"),
        "bug_analysis": _first_match(workspace_root, "unity_test/*_bug_analysis.md"),
        "functions_and_checks": _first_match(workspace_root, "unity_test/*_functions_and_checks.md"),
        "static_bug_analysis": _first_match(workspace_root, "unity_test/*_static_bug_analysis.md"),
        "line_coverage_analysis": _first_match(workspace_root, "unity_test/*_line_coverage_analysis.md"),
        "run_info": _first_match(workspace_root, "run_info.json"),
        "coverage_summary": _first_match(workspace_root, "uc_test_report/line_dat/code_coverage.json"),
        "coverage_merged_dat": _first_match(workspace_root, "uc_test_report/line_dat/merged.dat"),
        "coverage_def": _first_match(workspace_root, "unity_test/tests/*_function_coverage_def.py"),
        "signals_json": _first_match(workspace_root, "**/signals.json"),
    }

    dut, model = _infer_dut_and_model(workspace_root, found_files)
    if native_ucagent:
        info_path = os.path.join(workspace_root, ".ucagent", "ucagent_info.json")
        if os.path.isfile(info_path):
            found_files["ucagent_info"] = info_path
    if native_ucagent and not found_files.get("run_info"):
        info_path = os.path.join(workspace_root, ".ucagent", "ucagent_info.json")
        if os.path.isfile(info_path):
            with open(info_path, encoding="utf-8") as handle:
                info = json.load(handle)
            identity = info.get("dut_name") or info.get("DUT")
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError(f"missing DUT identity in {info_path}")
            dut = identity.strip()
    all_completed, completion_evidence = _discover_completion_status(workspace_root)
    if model_label:
        model = model_label

    unity_test_root = _first_match(workspace_root, "unity_test")
    tests_root = _first_match(workspace_root, "unity_test/tests")
    data_root = _first_match(workspace_root, "unity_test/tests/data")
    guide_doc_root = _first_match(workspace_root, "Guide_Doc")
    rtl_root = _discover_rtl_root(workspace_root)
    found_files["dut_readme"] = _discover_dut_readme(workspace_root, rtl_root, dut)
    missing_files = [name for name, path in found_files.items() if not path]
    if missing_files:
        logger.info("missing artifacts in %s: %s", workspace_root, ", ".join(missing_files))
    for name in missing_files:
        if name == "toffee_report":
            logger.warning("toffee_report.json not found — test execution data unavailable")
        elif name == "bug_analysis":
            logger.warning("bug analysis markdown not found — claim extraction disabled")
        elif name == "tests_root":
            logger.info("unity_test/tests not found — AST analysis disabled")

    fingerprints = {}
    for name, path in found_files.items():
        if path and os.path.isfile(path):
            fingerprints[name] = sha256_file(path)

    # Identity must survive archive extraction into a fresh random /tmp path.
    # The selected evidence content, DUT, and model define a run; physical
    # storage paths are provenance fields but must not perturb candidate IDs.
    run_key_seed = "\n".join(
        [dut, model]
        + [f"{name}:{fingerprints[name]}" for name in sorted(fingerprints)]
    )
    run_key = sha256_text(run_key_seed)[:16]

    problems = list(materialise_problems)
    if not found_files["toffee_report"]:
        problems.append("missing toffee_report.json; test execution reconstruction unavailable")
    if not found_files["bug_analysis"]:
        problems.append("missing bug analysis markdown; claim extraction unavailable")
    if not found_files["functions_and_checks"]:
        problems.append("missing functions_and_checks markdown; CK descriptions limited")
    if not tests_root:
        problems.append("missing unity_test/tests directory; AST-based assertion reconstruction unavailable")
    if not rtl_root:
        problems.append("missing discoverable RTL root; heuristic signal driver mapping unavailable")
    if not found_files["dut_readme"]:
        problems.append("missing DUT README/spec markdown; spec-property extraction will rely on generated docs only")
    if _looks_like_compact_sample(found_files, tests_root, rtl_root):
        problems.append(
            "compact extracted sample detected; suitable for structure/regression checks, but prefer the original archive/workspace for single-test evidence comparison"
        )

    return ArtifactManifest(
        input_path=input_path,
        workspace_root=workspace_root,
        source_type=source_type,
        run_key=run_key,
        dut=dut,
        model=model,
        found_files={key: value for key, value in found_files.items() if value},
        missing_files=missing_files,
        fingerprints=fingerprints,
        problems=problems,
        unity_test_root=unity_test_root,
        tests_root=tests_root,
        data_root=data_root,
        guide_doc_root=guide_doc_root,
        rtl_root=rtl_root,
        all_completed=all_completed,
        completion_evidence=completion_evidence,
    )


def discover_run_artifacts(input_path: str, model_label: Optional[str] = None) -> ArtifactManifest:
    """Discover a single run. For multi-workspace inputs use discover_all_runs."""
    materialised_root, source_type, materialise_problems = _materialise_input(input_path)
    roots = _find_all_workspace_roots(materialised_root)
    workspace_root = roots[0] if roots else materialised_root
    return _build_manifest(workspace_root, input_path, source_type, materialise_problems, model_label)


def discover_all_runs(input_path: str, model_label: Optional[str] = None, dut_filter: Optional[List[str]] = None, *, native_ucagent: bool = False) -> List[ArtifactManifest]:
    """Discover ALL runs in the input tree, auto-extracting archives as needed.

    When dut_filter is provided, only archives whose filename contains a target DUT
    name are extracted, and only workspaces whose inferred DUT matches are kept.
    """
    materialised_root, source_type, materialise_problems = _materialise_input(input_path)
    temp_root = tempfile.mkdtemp(prefix="benchmark_extract_")
    archive_roots = _extract_archives_in_tree(materialised_root, temp_root, dut_filter=dut_filter)
    workspace_roots = _find_all_workspace_roots(materialised_root, *archive_roots, native_ucagent=native_ucagent)

    if not workspace_roots:
        workspace_roots = [materialised_root]

    manifests = []
    for ws_root in workspace_roots:
        if not _workspace_may_match_dut_filter(ws_root, dut_filter):
            continue
        manifest = _build_manifest(ws_root, input_path, source_type, materialise_problems, model_label, native_ucagent=native_ucagent)
        if dut_filter and manifest.dut not in dut_filter:
            continue
        manifests.append(manifest)
    return manifests
