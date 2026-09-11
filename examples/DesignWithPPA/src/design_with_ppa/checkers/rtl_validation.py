"""RTL build, line-coverage, and source-evidence gates."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import fnmatch
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from ucagent.checkers.base import Checker
from ucagent.checkers.unity_test import (
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerCoverageGroup,
    UnityChipCheckerCoverageGroupBatchImplementation,
    UnityChipCheckerBatchTestsImplementation,
    UnityChipCheckerDutApi,
    UnityChipCheckerLabelStructureRefine,
    UnityChipCheckerLabelStructure,
    UnityChipCheckerMarkdownFileFormat,
    UnityChipCheckerRefineTestCases,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
    UnityChipCheckerTestTemplate,
    UnityChipCheckerTestMustPass,
)
from ucagent.checkers.toffee_report import check_line_coverage
import ucagent.util.functions as uc_functions
from ..contracts import (
    atomic_json,
    atomic_text,
    diagnostic,
    load_fenced_yaml,
    load_json,
    resolve_workspace_path,
    resolved_output,
)
from ..python_dut import (
    _RTL_DUT_CLASS_ENV,
    _RTL_DUT_MODULE_ENV,
)
from ..rtl import (
    RTLPreparationRequest,
    _generated_python_dut_identity,
    discover_rtl_libraries,
    discover_rtl_sources,
    resolve_rtl_config,
    validate_prepared_rtl,
)

from .common import (
    _inline_reason,
    _PYTHON_IDENTIFIER_RE,
    _VERILOG_IDENTIFIER_RE,
    _cfg_dut,
    _contract_identity,
    _exception_contract_diagnostic,
    _hash_rows,
    _line_ranges_text,
    _validated_input_identity,
)
from .coverage_model import (
    _cleanup_transient_coverage_data,
    _coverage_artifact_state,
    _coverage_fixture_lifecycle_violations,
    _coverage_pipeline_status,
)
from .evidence import (
    _public_evidence_error,
    _redact_backend_output,
    _rtl_regression_failure_evidence,
    _verilog_synthesis_hazard_evidence,
    _yosys_width_warning_evidence,
    tool_error_lines,
)
from .runtime import (
    _probe_python_dut_subprocess,
    _validate_python_dut_tree,
)
from .test_quality import (
    _api_assertion_quality_violations,
)
from . import runtime  # qualified so tests patch one runtime module


class RTLLineCoverageChecker(UnityChipCheckerTestCaseWithLineCoverage):
    """Run the authored RTL line-coverage gate with the selected language backend."""

    def __init__(
        self,
        rtl_architecture_file: str,
        rtl_manifest_file: str,
        cfg: Any,
        input_manifest_file: str | None = None,
        contract_files: list[str] | None = None,
        rtl_regression_file: str | None = None,
        timeout: int = 600,
        **kwargs: Any,
    ) -> None:
        """Store private-backend provenance needed before the core coverage run."""

        super().__init__(cfg=cfg, timeout=timeout, **kwargs)
        if not isinstance(rtl_architecture_file, str) or not rtl_architecture_file:
            raise ValueError("rtl_architecture_file must be a non-empty string")
        if not isinstance(rtl_manifest_file, str) or not rtl_manifest_file:
            raise ValueError("rtl_manifest_file must be a non-empty string")
        if contract_files is not None and (
            not isinstance(contract_files, list)
            or any(not isinstance(value, str) or not value for value in contract_files)
        ):
            raise ValueError("contract_files must be a list of non-empty strings")
        self.cfg = cfg
        self.rtl_architecture_file = rtl_architecture_file
        self.rtl_manifest_file = rtl_manifest_file
        self.input_manifest_file = input_manifest_file
        self.contract_files = list(contract_files or [])
        self.rtl_regression_file = rtl_regression_file

    def on_init(self):
        """Initialize the stage as pending until a current coverage run succeeds."""

        result = super().on_init()
        # The core checker uses 0.0 as its pre-run sentinel.  Zero is a valid
        # measured result, so expose an explicit pending state instead of
        # presenting an unmeasured value as real coverage in the stage title.
        self.cur_line_coverage = None
        return result

    def get_template_data(self) -> dict[str, str]:
        """Expose measured coverage or an explicit pending value to the stage UI."""

        if self.cur_line_coverage is None:
            return {
                "COVERAGE_COMPLETE": (
                    f"pending/{self.min_line_coverage * 100.0:.2f}% minimum"
                )
            }
        return {
            "COVERAGE_COMPLETE": (
                f"{self.cur_line_coverage * 100.0:.2f}/"
                f"{self.min_line_coverage * 100.0:.2f}"
            )
        }

    def do_check(self, timeout: int = 0, **kwargs: Any):
        """Validate authored RTL coverage without exposing generated build inputs."""

        workspace = Path(self.workspace).resolve()
        assertion_violations: list[dict[str, Any]] = []
        relative_source = self.test_dir
        try:
            for raw_path in self._stage_test_files():
                source_path = Path(raw_path)
                if not source_path.is_absolute():
                    source_path = workspace / source_path
                source_path = source_path.resolve(strict=True)
                relative_source = source_path.relative_to(workspace).as_posix()
                assertion_violations.extend(
                    {
                        "file": relative_source,
                        **violation,
                    }
                    for violation in _api_assertion_quality_violations(
                        source_path,
                        _cfg_dut(self.cfg),
                        self._ignored_test_prefixes(),
                    )
                )
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            return False, diagnostic(
                "rtl_line_coverage_test_contract_invalid",
                (
                    "The shared RTL coverage test contract could not be inspected. "
                    "Coverage must be measured from the same readable Python tests "
                    "that define the functional behavior; a missing file, invalid "
                    "path, or syntax error blocks the run before RTL execution."
                ),
                (
                    "1. Open the artifact path and location reported below.\n"
                    "2. Restore the file under the configured test directory, keep it "
                    "workspace-local, and fix the Python syntax/encoding error.\n"
                    "3. Run the shared tests with RunTestCases (Python reference), "
                    "then call Check to regenerate RTL coverage."
                ),
                artifact=self.test_dir,
                location=(
                    f"{relative_source}:{exc.lineno}"
                    if isinstance(exc, SyntaxError) and exc.lineno
                    else self.test_dir
                ),
                observed={"exception": _redact_backend_output(str(exc), 3000, (workspace,))},
                expected="Readable shared Python tests contained within the workspace.",
            )
        if assertion_violations:
            return False, diagnostic(
                "rtl_line_coverage_weak_api_assertion",
                (
                    "One or more shared tests do not provide an independent behavioral "
                    "check. Weak assertions can make both "
                    "backends appear healthy without proving that the RTL result matches "
                    "the executable specification."
                ),
                (
                    "1. Fix every violation listed in observed.violations.\n"
                    "2. Drive each transaction through the imported api_{DUT}_* function; "
                    "derive the expected result independently and compare normal return "
                    "values with exact ==. Use pytest.raises only for the documented error "
                    "contract.\n"
                    "3. Do not use result == result, result != 0, truthiness, or "
                    "is-not-None as a functional assertion.\n"
                    "4. Run the corrected tests in the Python backend, then call Check "
                    "for the complete RTL coverage run."
                ),
                artifact=self.test_dir,
                location=(
                    f"{assertion_violations[0]['file']}:"
                    f"{assertion_violations[0].get('line', 1)}"
                ),
                observed={
                    "violations": assertion_violations[:20],
                    "truncated": len(assertion_violations) > 20,
                },
                expected="Every non-error api_{DUT}_* value result has an independent exact equality assertion.",
            )
        fixture_path = resolve_workspace_path(workspace, self.test_dir) / "conftest.py"
        if fixture_path.is_file() and not fixture_path.is_symlink():
            try:
                lifecycle_violations = _coverage_fixture_lifecycle_violations(
                    fixture_path
                )
            except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
                return False, diagnostic(
                    "rtl_line_coverage_fixture_invalid",
                    (
                        "The shared pytest env fixture could not be parsed, so coverage "
                        "setup and DUT cleanup cannot be proven. This is a test-runtime "
                        "contract failure, not an RTL coverage percentage."
                    ),
                    (
                        "1. Fix the syntax/encoding or path problem reported in observed.\n"
                        "2. Rebuild the env fixture from Guide_Doc/rtl_backend.md and "
                        "Guide_Doc/rtl_line_coverage.md: configure coverage before reset, "
                        "call set_func_coverage(), finish the adapter, then register the "
                        "finalized coverage file.\n"
                        "3. Run the Python tests, then call Check for a fresh RTL run."
                    ),
                    artifact=str(fixture_path.relative_to(workspace).as_posix()),
                    location=(
                        f"{fixture_path.relative_to(workspace).as_posix()}:{exc.lineno}"
                        if isinstance(exc, SyntaxError) and exc.lineno
                        else fixture_path.relative_to(workspace).as_posix()
                    ),
                    observed={"exception": _redact_backend_output(str(exc), 3000, (workspace,))},
                    expected="The env fixture configures coverage before reset and registers finalized coverage after adapter.finish().",
                )
            if lifecycle_violations:
                return False, diagnostic(
                    "rtl_line_coverage_fixture_invalid",
                    (
                        "The env fixture uses an invalid coverage lifecycle. Toffee can "
                        "only report authored RTL lines when coverage is bound before "
                        "the first reset/Step and the native dat file is finalized after "
                        "the test. The reported ordering would otherwise produce a "
                        "missing or zero line-coverage artifact."
                    ),
                    (
                        "1. In the listed fixture, configure coverage before reset/Step.\n"
                        "2. During teardown call set_func_coverage(request, groups), then "
                        "adapter.finish() (or Finish()), then set_line_coverage(request, "
                        "the_same_dat_path).\n"
                        "3. Keep FlushWaveform() before sidecar writing for performance "
                        "tests, but do not register line coverage before finish().\n"
                        "4. Run the Python suite, call Check for the complete RTL suite, "
                        "and verify code_coverage.json plus merged.info are recreated."
                    ),
                    artifact=str(fixture_path.relative_to(workspace).as_posix()),
                    location=(
                        f"{fixture_path.relative_to(workspace).as_posix()}:"
                        f"{lifecycle_violations[0].get('line', 1)}"
                        if isinstance(lifecycle_violations[0], dict)
                        else fixture_path.relative_to(workspace).as_posix()
                    ),
                    observed={"violations": lifecycle_violations},
                    coverage_pipeline=_coverage_pipeline_status("instrumentation_setup"),
                    expected="set_func_coverage() < adapter.finish() < set_line_coverage()",
                )
        ignore_path = resolve_workspace_path(workspace, self.coverage_ignore)
        raw_ignore_ranges: list[tuple[str, set[int]]] = []
        ignore_patterns: list[str] = []
        if ignore_path.exists():
            if not ignore_path.is_file() or ignore_path.is_symlink():
                return False, diagnostic(
                    "rtl_line_coverage_ignore_invalid",
                    (
                        "The line-coverage ignore artifact is not a regular file. Toffee "
                        "cannot safely parse a directory, symlink, or other special file "
                        "as authored-source exclusions."
                    ),
                    (
                        "1. Replace the artifact with a regular UTF-8 text file inside the "
                        "workspace.\n"
                        "2. Put only raw */path/to/source.v:start-end ranges and standalone "
                        "# comments in it; put explanations in the analysis Markdown.\n"
                        "3. Call Check again before changing RTL tests."
                    ),
                    artifact=self.coverage_ignore,
                    location=self.coverage_ignore,
                    observed={"kind": "non_regular_file"},
                    expected="Raw */path:positive-start-end patterns and separate comment lines.",
                )
            try:
                ignore_lines = ignore_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError) as exc:
                return False, diagnostic(
                    "rtl_line_coverage_ignore_invalid",
                    (
                        "The line-coverage ignore artifact cannot be read as UTF-8 text, "
                        "so its exclusions cannot be matched to current uncovered lines."
                    ),
                    (
                        "1. Rewrite the named artifact as UTF-8 plain text.\n"
                        "2. Keep one raw */path/to/source.v:start-end pattern per line and "
                        "move all prose/reasoning to the analysis Markdown.\n"
                        "3. Call Check again and use its current uncovered-line evidence."
                    ),
                    artifact=self.coverage_ignore,
                    location=self.coverage_ignore,
                    observed={"exception": _redact_backend_output(str(exc), 3000, (workspace,))},
                    expected="A readable UTF-8 text file.",
                )
            invalid_lines: list[dict[str, Any]] = []
            for line_number, source_line in enumerate(ignore_lines, start=1):
                pattern = source_line.strip()
                if not pattern or pattern.startswith("#"):
                    continue
                reason = ""
                path_pattern = ""
                ranges = ""
                if "<LINE_IGNORE>" in pattern or "</LINE_IGNORE>" in pattern:
                    reason = "LINE_IGNORE tags belong only in the analysis Markdown"
                elif any(character in pattern for character in ('"', "'", "<", ">")):
                    reason = "quotes and markup are not valid raw ignore syntax"
                elif "#" in pattern:
                    reason = "comments must occupy their own line"
                elif any(character.isspace() for character in pattern):
                    reason = "raw patterns cannot contain whitespace or prose"
                elif pattern in ignore_patterns:
                    reason = "duplicate raw ignore patterns are prohibited"
                elif pattern.count(":") > 1:
                    reason = "a raw pattern may contain exactly one range delimiter"
                else:
                    path_pattern, separator, ranges = pattern.partition(":")
                    if not path_pattern.startswith("*/"):
                        reason = "the source glob must start with */"
                    elif path_pattern == "*/" or not re.fullmatch(
                        r"\*/[^\s:#<>\"']+", path_pattern
                    ):
                        reason = "the source glob must name a file after */"
                    elif not separator:
                        reason = "excluding a complete authored source file is prohibited"
                    elif not re.fullmatch(
                        r"[1-9][0-9]*-[1-9][0-9]*(?:,[1-9][0-9]*-[1-9][0-9]*)*",
                        ranges,
                    ):
                        reason = "ranges must use positive start-end pairs separated by commas"
                    else:
                        for line_range in ranges.split(","):
                            start_text, end_text = line_range.split("-", 1)
                            if int(start_text) > int(end_text):
                                reason = "range start must not exceed range end"
                                break
                if reason:
                    invalid_lines.append(
                        {
                            "line": line_number,
                            "text": source_line[:240],
                            "reason": reason,
                        }
                    )
                    if len(invalid_lines) == 20:
                        break
                else:
                    ignored_lines: set[int] = set()
                    for line_range in ranges.split(","):
                        start_text, end_text = line_range.split("-", 1)
                        ignored_lines.update(
                            range(int(start_text), int(end_text) + 1)
                        )
                    raw_ignore_ranges.append((path_pattern, ignored_lines))
                    ignore_patterns.append(pattern)
            if invalid_lines:
                first_line = invalid_lines[0]["line"]
                return False, diagnostic(
                    "rtl_line_coverage_ignore_invalid",
                    "The raw line-coverage ignore file contains invalid syntax.",
                    (
                        f"1. Fix {self.coverage_ignore}:{first_line} using only an exact "
                        "*/path/to/source.v:start-end range or a standalone # comment.\n"
                        f"2. Put the matching proof in {self.coverage_analysis}; do not put "
                        "LINE_IGNORE tags, quotes, or prose in the raw file.\n"
                        "3. Read Guide_Doc/rtl_line_coverage.md, then call Check again to "
                        "validate the exclusion against current LCOV data."
                    ),
                    artifact=self.coverage_ignore,
                    location=f"{self.coverage_ignore}:{first_line}",
                    observed=invalid_lines,
                    expected=[
                        "*/path/to/source.v:10-20,30-30",
                        "# comment on a separate line",
                    ],
                )

        analysis_path = resolve_workspace_path(workspace, self.coverage_analysis)
        if ignore_patterns:
            if not analysis_path.is_file() or analysis_path.is_symlink():
                return False, diagnostic(
                    "rtl_line_coverage_proof_invalid",
                    (
                        "The raw ignore file contains exclusions, but the corresponding "
                        "analysis Markdown is missing or is not a regular file. Without "
                        "one proof per exclusion, an uncovered authored line could be "
                        "silently hidden."
                    ),
                    (
                        "1. Create or restore the named analysis Markdown.\n"
                        "2. Add exactly one canonical <LINE_IGNORE> entry for every raw "
                        "pattern, with proof kind, evidence path and a precise rationale.\n"
                        "3. If a line is reachable or merely untested, remove the ignore "
                        "and add a real test instead. Read Guide_Doc/rtl_line_coverage.md "
                        "and call Check again."
                    ),
                    artifact=self.coverage_analysis,
                    location=self.coverage_analysis,
                    observed={"ignore_patterns": ignore_patterns[:20]},
                    expected="One proof entry for every raw ignore pattern.",
                )
            try:
                analysis_lines = analysis_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError) as exc:
                return False, diagnostic(
                    "rtl_line_coverage_proof_invalid",
                    (
                        "The line-coverage proof Markdown cannot be read as UTF-8, so "
                        "the exclusion evidence is unverifiable."
                    ),
                    (
                        "1. Rewrite the named artifact as UTF-8 Markdown without changing "
                        "the raw ignore ranges.\n"
                        "2. Restore one canonical proof/evidence line per raw pattern, or "
                        "remove the exclusion and add a test.\n"
                        "3. Call Check again."
                    ),
                    artifact=self.coverage_analysis,
                    location=self.coverage_analysis,
                    observed={"exception": _redact_backend_output(str(exc), 3000, (workspace,))},
                    expected="Readable UTF-8 Markdown with one proof for each raw ignore pattern.",
                )
            proof_entries: dict[str, list[dict[str, Any]]] = {}
            invalid_proofs: list[dict[str, Any]] = []
            raw_ranges_by_pattern = dict(raw_ignore_ranges)
            proof_pattern = re.compile(
                r"\s*<LINE_IGNORE>([^<>]+)</LINE_IGNORE>:\s*"
                r"\[proof=(parameter_unreachable|state_unreachable|non_executable_structure);\s*"
                r"evidence=([^\]\r\n]+)\]\s+(.+?)\s*"
            )
            invalid_reason_pattern = re.compile(
                r"\b(?:reachable|untested|not tested|not exercised|not triggered|"
                r"not reached|test coverage|coverage gap|current tests?|current vectors?|"
                r"implementation (?:bug|error|defect)|rtl (?:bug|error|defect)|"
                r"outside (?:the )?scope)\b",
                re.IGNORECASE,
            )
            output_dir = resolved_output(self.cfg)
            dut = _cfg_dut(self.cfg)
            requirement_files = {
                f"{dut}/README.md",
                f"{output_dir}/{dut}_architecture.md",
            }
            for line_number, source_line in enumerate(analysis_lines, start=1):
                if "<LINE_IGNORE>" not in source_line and "</LINE_IGNORE>" not in source_line:
                    continue
                match = proof_pattern.fullmatch(source_line)
                if match is None:
                    invalid_proofs.append(
                        {
                            "line": line_number,
                            "reason": "entry must contain canonical proof and evidence fields",
                            "text": source_line[:240],
                        }
                    )
                    continue
                ignore_pattern, proof_kind, evidence, rationale = match.groups()
                proof_entries.setdefault(ignore_pattern, []).append(
                    {"line": line_number, "proof": proof_kind, "evidence": evidence}
                )
                contradiction = invalid_reason_pattern.search(rationale)
                if contradiction is not None:
                    invalid_proofs.append(
                        {
                            "line": line_number,
                            "reason": "reason admits reachable behavior, missing tests, a design defect, or scope avoidance",
                            "observed": contradiction.group(0),
                        }
                    )
                    continue
                evidence_match = re.fullmatch(
                    r"(.+):([1-9][0-9]*)(?:-([1-9][0-9]*))?", evidence
                )
                if evidence_match is None:
                    invalid_proofs.append(
                        {
                            "line": line_number,
                            "reason": "evidence must use workspace/path:start-end",
                            "observed": evidence[:240],
                        }
                    )
                    continue
                evidence_relative = evidence_match.group(1)
                evidence_start = int(evidence_match.group(2))
                evidence_end = int(evidence_match.group(3) or evidence_start)
                if evidence_start > evidence_end:
                    invalid_proofs.append(
                        {
                            "line": line_number,
                            "reason": "evidence range start exceeds its end",
                            "observed": evidence[:240],
                        }
                    )
                    continue
                is_requirement_evidence = (
                    evidence_relative in requirement_files
                    or evidence_relative.startswith(f"{dut}/spec/")
                )
                is_source_evidence = evidence_relative.startswith(
                    f"{output_dir}/rtl/"
                )
                if proof_kind == "non_executable_structure":
                    allowed_evidence = is_source_evidence
                else:
                    allowed_evidence = is_requirement_evidence
                if not allowed_evidence:
                    invalid_proofs.append(
                        {
                            "line": line_number,
                            "reason": "proof kind and evidence artifact are incompatible",
                            "observed": {
                                "proof": proof_kind,
                                "evidence": evidence_relative,
                            },
                        }
                    )
                    continue
                if proof_kind == "non_executable_structure":
                    target_lines = raw_ranges_by_pattern.get(ignore_pattern)
                    path_pattern = ignore_pattern.split(":", 1)[0]
                    if target_lines is not None and (
                        not fnmatch.fnmatch(evidence_relative, path_pattern)
                        or not target_lines.issubset(
                            set(range(evidence_start, evidence_end + 1))
                        )
                    ):
                        invalid_proofs.append(
                            {
                                "line": line_number,
                                "reason": (
                                    "non-executable evidence must cover the excluded "
                                    "range in the same authored source"
                                ),
                                "observed": {
                                    "pattern": ignore_pattern,
                                    "evidence": evidence,
                                },
                            }
                        )
                        continue
                try:
                    evidence_path = resolve_workspace_path(
                        workspace, evidence_relative, must_exist=True
                    )
                    if not evidence_path.is_file() or evidence_path.is_symlink():
                        raise ValueError("evidence artifact is not a regular file")
                    evidence_lines = evidence_path.read_text(encoding="utf-8").splitlines()
                    evidence_line_count = len(evidence_lines)
                    if evidence_end > evidence_line_count:
                        raise ValueError(
                            f"evidence line {evidence_end} exceeds file length {evidence_line_count}"
                        )
                    if not any(
                        line.strip()
                        for line in evidence_lines[evidence_start - 1 : evidence_end]
                    ):
                        raise ValueError("evidence range contains no substantive text")
                except (OSError, UnicodeError, ValueError, FileNotFoundError) as exc:
                    invalid_proofs.append(
                        {
                            "line": line_number,
                            "reason": str(exc),
                            "observed": evidence[:240],
                        }
                    )
            for pattern in ignore_patterns:
                entries = proof_entries.get(pattern, [])
                if len(entries) != 1:
                    invalid_proofs.append(
                        {
                            "line": entries[0]["line"] if entries else 0,
                            "reason": "raw pattern must have exactly one matching proof entry",
                            "observed": {"pattern": pattern, "proof_count": len(entries)},
                        }
                    )
            for pattern, entries in proof_entries.items():
                if pattern not in ignore_patterns:
                    invalid_proofs.append(
                        {
                            "line": entries[0]["line"],
                            "reason": "proof entry has no matching raw ignore pattern",
                            "observed": pattern,
                        }
                    )
            if invalid_proofs:
                invalid_proofs = invalid_proofs[:20]
                first_line = invalid_proofs[0]["line"]
                return False, diagnostic(
                    "rtl_line_coverage_proof_invalid",
                    (
                        "The line-coverage exclusion proof is incomplete, mismatched with "
                        "the raw ignore file, or contradicts the design evidence. An "
                        "ignore is accepted only when the exact range is currently "
                        "uncovered and its non-reachability/non-executable status is "
                        "traceable to a real workspace artifact."
                    ),
                    (
                        f"1. Fix {self.coverage_analysis}:{first_line} and every item in "
                        "observed so the tag exactly equals one raw pattern.\n"
                        "2. Use parameter_unreachable/state_unreachable evidence from README, "
                        "Spec, or architecture, or non_executable_structure evidence from "
                        "the same authored RTL source; ensure the evidence line exists and "
                        "covers the claimed range.\n"
                        "3. If the behavior is reachable, remove both the raw exclusion and "
                        "proof and add a meaningful test.\n"
                        "4. Call Check again to compare the proof with current LCOV data."
                    ),
                    artifact=self.coverage_analysis,
                    location=(
                        f"{self.coverage_analysis}:{first_line}"
                        if first_line > 0
                        else self.coverage_analysis
                    ),
                    observed=invalid_proofs,
                    expected=(
                        "<LINE_IGNORE>*/source.v:10-20</LINE_IGNORE>: "
                        "[proof=parameter_unreachable; evidence=spec/path.md:12-14] precise proof"
                    ),
                )
        try:
            build_checker = RTLBackendBuildChecker(
                architecture_file=self.rtl_architecture_file,
                manifest_file=self.rtl_manifest_file,
                timeout=self.timeout,
                cfg=self.cfg,
                input_manifest_file=self.input_manifest_file,
                contract_files=self.contract_files,
            ).set_workspace(self.workspace)
            build_passed, build_result = build_checker.do_check()
            if not build_passed:
                return False, build_result
            manifest = load_json(
                resolve_workspace_path(
                    workspace, self.rtl_manifest_file, must_exist=True
                )
            )
            module_name, class_name = runtime._validate_workspace_python_dut(
                workspace, manifest
            )
            # The stage manager merges the plugin import roots into
            # run_test.extra_python_paths when it attaches; replacing the list
            # here would drop them and the shared conftest could no longer
            # import design_with_ppa.  Keep the DUT root first (it must shadow
            # same-named modules) and retain every previously configured root.
            python_dut_root = str(runtime._workspace_python_dut_root(workspace))
            retained_roots = [
                path
                for path in (getattr(self.run_test, "extra_python_paths", []) or [])
                if isinstance(path, str) and path != python_dut_root
            ]
            self.run_test.set_extra_python_paths(
                [python_dut_root, *retained_roots]
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, diagnostic(
                "rtl_line_coverage_backend_invalid",
                (
                    "The selected RTL implementation could not be prepared or its public "
                    "test runtime could not be validated. Coverage cannot be attributed "
                    "to authored sources until the architecture, source manifest and "
                    "adapter are consistent."
                ),
                (
                    "1. Read the reported artifact and operation in observed; fix the "
                    "top-module/ports in architecture, the authored RTL source set, or "
                    "the shared adapter/runtime named by the diagnostic.\n"
                    "2. Keep all RTL sources and configured libraries workspace-local and "
                    "regenerate the managed test runtime through Check.\n"
                    "3. After preparation succeeds, rerun the complete RTL regression; do "
                    "not hand-edit generated runtime files or coverage JSON."
                ),
                artifact=self.rtl_manifest_file,
                location=self.rtl_manifest_file,
                observed={"exception": _public_evidence_error(str(exc))},
                expected="Current architecture, RTL source manifest, and importable RTL test runtime.",
            )
        try:
            pytest_ex_env = dict(kwargs.pop("pytest_ex_env", {}) or {})
            pytest_ex_env[_RTL_DUT_MODULE_ENV] = module_name
            pytest_ex_env[_RTL_DUT_CLASS_ENV] = class_name
            # This gate runs through the core test runner, so select the RTL
            # implementation here instead of exposing backend choice to the
            # stage-running agent.
            pytest_args = list(kwargs.pop("pytest_args", []) or [])
            if not any(
                argument == "--design-backend=rtl"
                or argument == "--design-backend"
                for argument in pytest_args
            ):
                pytest_args.append("--design-backend=rtl")
            kwargs["pytest_args"] = pytest_args
            if self.doc_bug_analysis is None:
                # Design delivery has no Bug-analysis document.  Reuse the core
                # test runner and assertion checks, but bypass the verification
                # checker path whose contract intentionally accepts confirmed DUT
                # failures and requires a dynamic Bug document.
                passed, result = self._run_design_regression(
                    timeout=timeout,
                    pytest_ex_env=pytest_ex_env,
                    **kwargs,
                )
            else:
                passed, result = UnityChipCheckerTestCase.do_check(
                    self,
                    timeout=timeout,
                    pytest_ex_env=pytest_ex_env,
                    **kwargs,
                )
        finally:
            test_dir = resolve_workspace_path(workspace, self.test_dir)
            _cleanup_transient_coverage_data(test_dir)
        if not passed:
            return passed, result

        coverage_path = resolve_workspace_path(workspace, self.coverage_json)
        lcov_path = coverage_path.with_name("merged.info")
        coverage_usable = (
            coverage_path.is_file()
            and not coverage_path.is_symlink()
            and coverage_path.stat().st_size > 0
        )
        lcov_usable = (
            lcov_path.is_file()
            and not lcov_path.is_symlink()
            and lcov_path.stat().st_size > 0
        )
        if not coverage_usable or not lcov_usable:
            report_path = coverage_path.parent.parent / "toffee_report.json"
            artifact_paths = {
                "coverage_json": coverage_path,
                "lcov": lcov_path,
                "toffee_report": report_path,
                "coverage_data_dir": coverage_path.parent,
            }
            if self.rtl_regression_file:
                try:
                    artifact_paths["rtl_regression"] = resolve_workspace_path(
                        workspace, self.rtl_regression_file
                    )
                except ValueError:
                    artifact_paths["rtl_regression"] = workspace / "invalid-path"
            evidence = _coverage_artifact_state(workspace, artifact_paths)
            evidence["pytest"] = {
                "returncode": (
                    getattr(self.run_test, "last_execution", {}) or {}
                ).get("pytest_returncode"),
                "diagnostic_code": (
                    getattr(self.run_test, "last_execution", {}) or {}
                ).get("diagnostic_code"),
            }
            stdout = getattr(self.run_test, "_last_process_stdout", "") or ""
            stderr = getattr(self.run_test, "_last_process_stderr", "") or ""
            if self.ret_std_out and stdout:
                evidence["stdout_tail"] = _redact_backend_output(
                    stdout, 2000, (workspace,)
                )
            if self.ret_std_error and stderr:
                evidence["stderr_tail"] = _redact_backend_output(
                    stderr, 3000, (workspace,)
                )
            if report_path.is_file() and not report_path.is_symlink():
                try:
                    report = load_json(report_path)
                except (OSError, ValueError):
                    report = {}
                line_report = (
                    report.get("coverages", {}).get("line", {})
                    if isinstance(report, dict)
                    and isinstance(report.get("coverages"), dict)
                    else {}
                )
                line_error = (
                    line_report.get("error") if isinstance(line_report, dict) else None
                )
                if isinstance(line_error, str) and line_error.strip():
                    relative_report = report_path.relative_to(workspace).as_posix()
                    evidence["coverage_pipeline"] = _coverage_pipeline_status(
                        "toffee_artifacts"
                    )
                    return False, diagnostic(
                        "rtl_line_coverage_generation_failed",
                        (
                            "The RTL regression report recorded a line-coverage generation "
                            "error. Functional execution may have completed, but Toffee "
                            "could not convert the registered native coverage data into "
                            "the required authored-source artifacts."
                        ),
                        (
                            f"1. Read {relative_report}:coverages.line.error and the bounded "
                            "artifact_state below to identify the first failed conversion.\n"
                            "2. For ignore errors, keep only raw ranges in "
                            f"{self.coverage_ignore} and put proof in {self.coverage_analysis}; "
                            "for missing data, repair fixture coverage setup and finalize "
                            "the adapter before set_line_coverage().\n"
                            "3. Rerun the complete current RTL TC set so Toffee creates a "
                            "fresh code_coverage.json and merged.info, then call Check again."
                        ),
                        artifact=relative_report,
                        location="coverages.line.error",
                        expected=(
                            f"A generated {self.coverage_json} file with no line-coverage "
                            "error in the test report."
                        ),
                        observed=line_error.strip()[:1000],
                        artifact_state=evidence,
                    )
                if isinstance(line_report, dict) and line_report:
                    evidence["toffee_line_coverage"] = {
                        key: line_report.get(key)
                        for key in ("total", "hints", "grate", "error")
                        if key in line_report
                    }
            evidence["coverage_pipeline"] = _coverage_pipeline_status(
                "toffee_artifacts"
            )
            return False, diagnostic(
                "rtl_line_coverage_generation_failed",
                (
                    "The complete RTL functional regression passed, but it did not produce "
                    "a usable authored-source line-coverage result. This is an instrumentation "
                    "or artifact-lifecycle failure, not evidence that coverage is zero."
                ),
                (
                    "1. Read artifact_state and toffee_line_coverage to distinguish a missing "
                    "file, an empty file, and a Toffee conversion error.\n"
                    "2. Read Guide_Doc/rtl_line_coverage.md and Guide_Doc/rtl_backend.md. In "
                    "the env fixture, bind coverage before reset/Step, call set_func_coverage(), "
                    "call adapter.finish()/Finish() to write the native dat file, and only "
                    "then call set_line_coverage() with that same path.\n"
                    "3. Do not manufacture code_coverage.json, copy an old report, or treat "
                    "line.total=0 from a failed test run as measured coverage.\n"
                    "4. Rerun the complete RTL regression and call Check; proceed to the "
                    "threshold gate only when current code_coverage.json and merged.info exist."
                ),
                artifact=self.coverage_json,
                location=self.coverage_json,
                observed=evidence,
                expected={
                    "coverage_json": "regular non-empty current file",
                    "merged_info": "regular current LCOV file",
                    "toffee_report.coverages.line.error": "empty",
                    "pytest": "returncode 0 with all shared tests passed",
                },
            )

        try:
            authored_rows = manifest.get("rtl_sources")
            if not isinstance(authored_rows, list) or not authored_rows:
                raise ValueError("RTL manifest does not contain authored rtl_sources")
            authored_paths: list[str] = []
            authored_line_counts: dict[str, int] = {}
            for index, row in enumerate(authored_rows):
                path = row.get("path") if isinstance(row, dict) else None
                if not isinstance(path, str) or not path:
                    raise ValueError(f"rtl_sources[{index}].path is invalid")
                source_path = resolve_workspace_path(workspace, path, must_exist=True)
                if source_path.is_symlink() or not source_path.is_file():
                    raise ValueError(f"authored RTL source {path!r} is not a regular file")
                authored_line_counts[path] = len(
                    source_path.read_text(encoding="utf-8").splitlines()
                )
                authored_paths.append(path)
            basenames = [Path(path).name for path in authored_paths]
            if len(set(basenames)) != len(basenames):
                raise ValueError("authored RTL source basenames must be unique for coverage mapping")

            ignored_by_source = {path: set() for path in authored_paths}
            for path_pattern, ignored_lines in raw_ignore_ranges:
                matched_sources = [
                    path
                    for path in authored_paths
                    if fnmatch.fnmatch(path, path_pattern)
                ]
                if len(matched_sources) != 1:
                    raise ValueError(
                        f"ignore source pattern {path_pattern!r} matched "
                        f"{len(matched_sources)} authored source files"
                    )
                matched_source = matched_sources[0]
                overlap = ignored_by_source[matched_source] & ignored_lines
                if overlap:
                    raise ValueError(
                        f"ignore source pattern {path_pattern!r} overlaps another "
                        f"exclusion at lines {min(overlap)}-{max(overlap)}"
                    )
                ignored_by_source[matched_source].update(ignored_lines)

            raw_coverage = load_json(coverage_path)
            uncovered = raw_coverage.get("uncovered")
            raw_data = uncovered.get("data") if isinstance(uncovered, dict) else None
            if not isinstance(raw_data, dict) or not raw_data:
                raise ValueError("coverage JSON does not contain uncovered.data")
            if lcov_path.is_symlink() or not lcov_path.is_file():
                raise ValueError("current RTL regression did not produce merged.info")
            lcov_records: list[tuple[str, dict[int, int]]] = []
            current_lcov_source: str | None = None
            current_lcov_lines: dict[int, int] = {}
            for lcov_line_number, raw_lcov_line in enumerate(
                lcov_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if raw_lcov_line.startswith("SF:"):
                    if current_lcov_source is not None:
                        raise ValueError(
                            "LCOV source record is missing end_of_record before "
                            f"line {lcov_line_number}"
                        )
                    current_lcov_source = raw_lcov_line[3:]
                    current_lcov_lines = {}
                elif raw_lcov_line.startswith("DA:"):
                    if current_lcov_source is None:
                        raise ValueError(
                            f"LCOV DA record at line {lcov_line_number} has no source"
                        )
                    da_match = re.fullmatch(
                        r"DA:([1-9][0-9]*),([0-9]+)(?:,[^,\r\n]+)?",
                        raw_lcov_line,
                    )
                    if da_match is None:
                        raise ValueError(
                            f"LCOV DA record at line {lcov_line_number} is invalid"
                        )
                    source_line = int(da_match.group(1))
                    if source_line in current_lcov_lines:
                        raise ValueError(
                            f"LCOV DA record at line {lcov_line_number} duplicates "
                            f"source line {source_line}"
                        )
                    current_lcov_lines[source_line] = int(da_match.group(2))
                elif raw_lcov_line == "end_of_record":
                    if current_lcov_source is None:
                        raise ValueError(
                            f"LCOV end_of_record at line {lcov_line_number} has no source"
                        )
                    lcov_records.append((current_lcov_source, current_lcov_lines))
                    current_lcov_source = None
                    current_lcov_lines = {}
            if current_lcov_source is not None:
                raise ValueError("LCOV final source record is missing end_of_record")

            public_data: dict[str, Any] = {}
            aggregate_total: dict[str, int] = {}
            aggregate_miss: dict[str, int] = {}
            for authored_path in authored_paths:
                basename = Path(authored_path).name
                matching_entries = [
                    (raw_path, entry)
                    for raw_path, entry in raw_data.items()
                    if isinstance(raw_path, str) and Path(raw_path).name == basename
                ]
                if len(matching_entries) != 1:
                    raise ValueError(
                        f"coverage data for authored source {authored_path!r} matched "
                        f"{len(matching_entries)} generated entries"
                    )
                matching_lcov_records = [
                    line_counts
                    for raw_path, line_counts in lcov_records
                    if Path(raw_path).name == basename
                ]
                if len(matching_lcov_records) != 1:
                    raise ValueError(
                        f"LCOV data for authored source {authored_path!r} matched "
                        f"{len(matching_lcov_records)} generated records"
                    )
                lcov_line_counts = matching_lcov_records[0]
                if not lcov_line_counts:
                    raise ValueError(
                        f"LCOV data for authored source {authored_path!r} has no lines"
                    )
                if max(lcov_line_counts) > authored_line_counts[authored_path]:
                    raise ValueError(
                        f"LCOV data for authored source {authored_path!r} exceeds its "
                        "current line count"
                    )
                exact_missed_lines = {
                    source_line
                    for source_line, count in lcov_line_counts.items()
                    if count == 0
                }
                _raw_path, raw_entry = matching_entries[0]
                if not isinstance(raw_entry, dict):
                    raise ValueError(f"coverage entry for {authored_path!r} is invalid")
                public_entry = copy.deepcopy(raw_entry)
                for metric_group, expected_line_count in (
                    ("total", len(lcov_line_counts)),
                    ("miss", len(exact_missed_lines)),
                ):
                    raw_metrics = public_entry.get(metric_group)
                    if (
                        not isinstance(raw_metrics, dict)
                        or isinstance(raw_metrics.get("line"), bool)
                        or raw_metrics.get("line") != expected_line_count
                    ):
                        raise ValueError(
                            f"coverage entry {authored_path!r}.{metric_group}.line "
                            "disagrees with current LCOV data"
                        )
                modules = public_entry.get("modules")
                if not isinstance(modules, dict) or not modules:
                    raise ValueError(f"coverage entry for {authored_path!r} has no modules")
                excluded_file_lines: set[int] = set()
                missed_file_lines: set[int] = set()
                for module, module_data in modules.items():
                    if not isinstance(module_data, dict):
                        raise ValueError(
                            f"coverage module {module!r} in {authored_path!r} is invalid"
                        )
                    raw_line_ranges = module_data.get("line")
                    if not isinstance(raw_line_ranges, list) or any(
                        not isinstance(value, str) for value in raw_line_ranges
                    ):
                        raise ValueError(
                            f"{authored_path}:{module}.line must be a list of start-end strings"
                        )
                    displayed_lines: set[int] = set()
                    for value in raw_line_ranges:
                        range_match = re.fullmatch(
                            r"([1-9][0-9]*)-([1-9][0-9]*)", value
                        )
                        if range_match is None:
                            raise ValueError(
                                f"{authored_path}:{module}.line contains an invalid "
                                f"line range: {value!r}"
                            )
                        range_start, range_end = (
                            int(range_match.group(1)),
                            int(range_match.group(2)),
                        )
                        if range_start > range_end:
                            raise ValueError(
                                f"{authored_path}:{module}.line contains a reversed "
                                f"line range: {value!r}"
                            )
                        displayed_lines.update(range(range_start, range_end + 1))
                    if (
                        displayed_lines
                        and max(displayed_lines) > authored_line_counts[authored_path]
                    ):
                        raise ValueError(
                            f"coverage for authored source {authored_path!r} exceeds its "
                            "current line count"
                        )
                    missed_lines = exact_missed_lines & displayed_lines
                    module_miss = module_data.get("miss")
                    if (
                        not isinstance(module_miss, dict)
                        or isinstance(module_miss.get("line"), bool)
                        or module_miss.get("line") != len(missed_lines)
                    ):
                        raise ValueError(
                            f"coverage module {module!r}.miss.line disagrees with "
                            "current LCOV data"
                        )
                    missed_file_lines.update(missed_lines)
                    excluded_lines = missed_lines & ignored_by_source[authored_path]
                    excluded_file_lines.update(excluded_lines)
                    retained_lines = sorted(missed_lines - excluded_lines)
                    retained_ranges: list[str] = []
                    retained_index = 0
                    while retained_index < len(retained_lines):
                        retained_start = retained_lines[retained_index]
                        retained_end = retained_start
                        retained_index += 1
                        while (
                            retained_index < len(retained_lines)
                            and retained_lines[retained_index] == retained_end + 1
                        ):
                            retained_end = retained_lines[retained_index]
                            retained_index += 1
                        retained_ranges.append(f"{retained_start}-{retained_end}")
                    module_data["line"] = retained_ranges
                    for metric_group in ("total", "miss"):
                        metrics = module_data.get(metric_group)
                        if not isinstance(metrics, dict):
                            raise ValueError(
                                f"coverage module {module!r}.{metric_group} is invalid"
                            )
                        line_value = metrics.get("line")
                        if (
                            isinstance(line_value, bool)
                            or not isinstance(line_value, int)
                            or line_value < len(excluded_lines)
                        ):
                            raise ValueError(
                                f"coverage module {module!r}.{metric_group}.line is invalid"
                            )
                        metrics["line"] = line_value - len(excluded_lines)
                if missed_file_lines != exact_missed_lines:
                    raise ValueError(
                        f"coverage modules for authored source {authored_path!r} do not "
                        "contain every current LCOV miss"
                    )
                unmatched_ignored_lines = ignored_by_source[authored_path] - exact_missed_lines
                if unmatched_ignored_lines:
                    raise ValueError(
                        f"ignore ranges for authored source {authored_path!r} include "
                        "lines that are not currently uncovered: "
                        f"{_line_ranges_text(unmatched_ignored_lines)}"
                    )
                for metric_group in ("total", "miss"):
                    metrics = public_entry.get(metric_group)
                    if not isinstance(metrics, dict):
                        raise ValueError(
                            f"coverage entry {authored_path!r}.{metric_group} is invalid"
                        )
                    line_value = metrics.get("line")
                    if (
                        isinstance(line_value, bool)
                        or not isinstance(line_value, int)
                        or line_value < len(excluded_file_lines)
                    ):
                        raise ValueError(
                            f"coverage entry {authored_path!r}.{metric_group}.line is invalid"
                        )
                    metrics["line"] = line_value - len(excluded_file_lines)
                    aggregate = (
                        aggregate_total if metric_group == "total" else aggregate_miss
                    )
                    for metric, value in metrics.items():
                        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                            raise ValueError(
                                f"coverage metric {authored_path!r}.{metric_group}.{metric} is invalid"
                            )
                        aggregate[metric] = aggregate.get(metric, 0) + value
                public_data[authored_path] = public_entry
            total_lines = aggregate_total.get("line", 0)
            missed_lines = aggregate_miss.get("line", 0)
            if total_lines <= 0 or missed_lines > total_lines:
                raise ValueError("authored line-coverage totals are invalid")
            atomic_json(
                coverage_path,
                {
                    "desc": "Authored RTL source coverage.",
                    "sim": raw_coverage.get("sim", "verilator"),
                    "overview": {
                        "total": aggregate_total,
                        "miss": aggregate_miss,
                    },
                    "uncovered": {
                        "schema": uncovered.get("schema"),
                        "data": public_data,
                    },
                },
            )
        except (OSError, UnicodeError, ValueError, FileNotFoundError) as exc:
            return False, diagnostic(
                "rtl_line_coverage_authored_scope_invalid",
                (
                    "The generated coverage artifacts cannot be mapped one-to-one to "
                    "the current authored RTL source manifest. Accepting this result "
                    "could count generated wrappers or stale line numbers as design "
                    "coverage."
                ),
                (
                    "1. Read the exact mapping error in observed and compare the current "
                    "RTL manifest, authored source paths, and merged.info records.\n"
                    "2. Regenerate coverage from the current source hashes; do not hand "
                    "edit code_coverage.json or copy generated wrapper entries into the "
                    "authored manifest.\n"
                    "3. If the error names an ignore range, remove that range and its proof "
                    "until Check reports the current exact uncovered lines.\n"
                    "4. Call Check again, then address the real threshold result."
                ),
                artifact=self.coverage_json,
                location=self.coverage_json,
                observed={"exception": _redact_backend_output(str(exc), 3000, (workspace,))},
                coverage_pipeline=_coverage_pipeline_status(
                    "authored_source_mapping"
                ),
                expected="Coverage data mapped one-to-one to current authored selected-language RTL sources.",
            )

        coverage_passed, coverage_result, self.cur_line_coverage = check_line_coverage(
            str(workspace),
            self.coverage_json,
            self.coverage_ignore,
            self.coverage_analysis,
            self.min_line_coverage,
        )
        if not coverage_passed:
            if isinstance(coverage_result, dict) and isinstance(
                coverage_result.get("uncoverage_info"), dict
            ):
                uncovered_info = coverage_result["uncoverage_info"]
                return False, diagnostic(
                    "rtl_line_coverage_below_threshold",
                    (
                        f"Authored RTL line coverage is "
                        f"{self.cur_line_coverage * 100.0:.2f}%, below the required "
                        f"{self.min_line_coverage * 100.0:.2f}%."
                    ),
                    (
                        "1. Use observed.uncovered to identify the exact authored source and "
                        "line ranges, then classify each range: irrelevant/dead RTL code, "
                        "reachable-but-untested behavior, or necessary shared glue.\n"
                        "2. Delete irrelevant or unreachable RTL code outright (removing it "
                        "from the denominator is the most direct improvement); first confirm "
                        "the architecture and FG/FC/CK contract do not reference it, then "
                        "rerun the full RTL regression to prove no behavior regressed.\n"
                        "3. For reachable behavior, add a meaningful shared directed, boundary, "
                        "reset, sequence, or deterministic random test with an exact API result "
                        "assertion; run it in Python first.\n"
                        "4. For necessary shared/infrastructure glue or base-library wrapper "
                        "lines that cannot be individually triggered, add the exact range to "
                        "the raw ignore file and one traced proof in the analysis Markdown as "
                        "specified by Guide_Doc/rtl_line_coverage.md.\n"
                        "5. Mix the three methods by classification instead of relying on new "
                        "tests alone; call Check to rerun the complete RTL suite and "
                        "regenerate current coverage; do not copy displayed spans, weaken "
                        "assertions, or ignore reachable behavior to inflate the number."
                    ),
                    artifact=self.coverage_json,
                    location=self.coverage_json,
                    observed={
                        "coverage": self.cur_line_coverage,
                        "uncovered": uncovered_info.get("uncoverage_detail", [])[:20],
                    },
                    coverage_pipeline=_coverage_pipeline_status(
                        "coverage_threshold"
                    ),
                    expected={"minimum_coverage": self.min_line_coverage},
                )
            return False, diagnostic(
                "rtl_line_coverage_contract_invalid",
                (
                    "The line-coverage report failed contract validation after RTL tests "
                    "completed. The result is not a valid authored-source percentage: the "
                    "machine schema, LCOV data, ignore ranges, or analysis Markdown is "
                    "malformed or inconsistent."
                ),
                (
                    "1. Read observed and inspect the named report/analysis artifact.\n"
                    "2. Regenerate code_coverage.json and merged.info from the current "
                    "complete RTL regression; do not hand-edit machine coverage data.\n"
                    "3. Keep raw exclusions and proof entries synchronized and ensure all "
                    "paths/line ranges refer to current authored sources.\n"
                    "4. Call Check again. Only a finite, non-empty, source-mapped report can "
                    "reach the percentage threshold gate."
                ),
                artifact=self.coverage_analysis,
                location=self.coverage_analysis,
                observed={"report_error": str(coverage_result)[:2000]},
                expected={
                    "coverage_json": "valid authored-source schema",
                    "merged_info": "valid LCOV for the same source set",
                    "coverage": "finite percentage from current RTL regression",
                },
            )

        if coverage_passed:
            ignore_text = (
                ignore_path.read_text(encoding="utf-8")
                if ignore_path.is_file() and not ignore_path.is_symlink()
                else ""
            )
            has_ignore_patterns = any(
                line.strip() and not line.lstrip().startswith("#")
                for line in ignore_text.splitlines()
            )
            if not has_ignore_patterns:
                atomic_text(
                    analysis_path,
                    (
                        f"\n# {_cfg_dut(self.cfg)} RTL Line Coverage\n\n"
                        "## Result\n\n"
                        f"- Coverage: `{self.cur_line_coverage * 100.0:.2f}%`\n"
                        f"- Required minimum: `{self.min_line_coverage * 100.0:.2f}%`\n"
                        "- Excluded authored lines: `None`\n\n"
                        "## Evidence\n\n"
                        f"- Machine coverage: `{self.coverage_json}`\n"
                        "- Shared RTL regression: `Pass`\n"
                    ),
                )
        return True, coverage_result


    def _run_design_regression(self, timeout: int, **kwargs: Any):
        """Run shared RTL tests under the all-pass design-delivery contract."""

        # Request Toffee phase details so a failed node includes its concrete
        # exception in the checker diagnostic.  This does not execute workspace
        # Python in the checker process; the test runner serializes the report.
        kwargs.setdefault("return_test_details", True)
        report, stdout, stderr = BaseUnityChipCheckerTestCase.do_check(
            self,
            timeout=timeout,
            **kwargs,
        )
        passed, message = uc_functions.is_run_report_pass(report, stdout, stderr)
        if not passed:
            workspace = Path(self.workspace).resolve()
            execution = getattr(self.run_test, "last_execution", {}) or {}
            evidence = _rtl_regression_failure_evidence(
                report,
                stdout,
                stderr,
                execution.get("pytest_returncode"),
                workspace=Path(self.workspace).resolve(),
                ret_std_out=self.ret_std_out,
                ret_std_error=self.ret_std_error,
            )
            try:
                coverage_json = resolve_workspace_path(workspace, self.coverage_json)
                toffee_report = coverage_json.parent.parent / "toffee_report.json"
                evidence["coverage_artifacts"] = _coverage_artifact_state(
                    workspace,
                    {
                        "code_coverage_json": coverage_json,
                        "merged_info": coverage_json.with_name("merged.info"),
                        "toffee_report": toffee_report,
                    },
                )
                evidence["coverage_interpretation"] = (
                    "not accepted: failed RTL tests must be fixed before line coverage "
                    "is interpreted; a zero Toffee line total at this point is not a "
                    "measured zero-coverage result"
                )
                evidence["coverage_pipeline"] = _coverage_pipeline_status(
                    "shared_rtl_regression"
                )
            except (OSError, ValueError):
                # The regression failure is already actionable; do not mask it if a
                # malformed coverage path prevents collecting supplemental evidence.
                pass
            if isinstance(message, dict):
                evidence["run_report"] = {
                    key: _redact_backend_output(str(value), 2000, (Path(self.workspace).resolve(),))
                    for key, value in message.items()
                    if key in {"error", "message"} and value is not None
                }
            return False, diagnostic(
                "rtl_design_regression_failed",
                (
                    "The shared RTL regression did not complete successfully. The "
                    "Python executable-spec run is the reference gate; this result "
                    "means the RTL run, its test runtime, or its report generation "
                    "failed before a valid coverage result could be accepted."
                ),
                (
                    "1. Read observed.failed_cases or pytest.failed_nodes and start "
                    "with the first failing node.\n"
                    "2. If the node is a collection/import/runtime error, repair the "
                    "shared API, env fixture, adapter, simulator setup, or RTL source "
                    "named by the evidence; if it is an assertion, compare the same "
                    "inputs and cycle/refresh sequence in both implementations.\n"
                    "3. Do not change expected values, skip the test, or create a Bug "
                    "record for a final-design failure.\n"
                    "4. Re-run that exact node with Check stage_args.test_target, then "
                    "run the complete RTL regression with Check. Coverage analysis is "
                    "valid only after every shared test passes."
                ),
                artifact=self.test_dir,
                location=(
                    (evidence.get("failed_nodes") or [self.test_dir])[0]
                    if isinstance(evidence, dict)
                    else self.test_dir
                ),
                observed=evidence,
                expected={
                    "run_test_success": True,
                    "test_cases": "every collected shared node has status PASSED",
                    "report": "complete Toffee report with no execution error",
                },
            )
        tests = report.get("tests", {}).get("test_cases", {})
        if not isinstance(tests, dict) or not tests:
            return False, diagnostic(
                "rtl_design_regression_empty",
                (
                    "The RTL command returned without a test-case mapping. No shared "
                    "test was proven to execute, so neither functional correctness "
                    "nor line coverage can be accepted."
                ),
                (
                    "1. Inspect the configured test directory and pytest collection "
                    "output for import, naming, or path errors.\n"
                    "2. Restore at least one discoverable shared functional test and "
                    "a valid env fixture/API import.\n"
                    "3. Re-run Check and confirm the report lists concrete node IDs "
                    "before calling Complete."
                ),
                artifact=self.test_dir,
                location=self.test_dir,
                observed={
                    "tests": tests,
                    "pytest_returncode": (
                        (getattr(self.run_test, "last_execution", {}) or {}).get(
                            "pytest_returncode"
                        )
                    ),
                },
                expected="At least one collected shared test case.",
            )
        failed = sorted(
            str(node) for node, status in tests.items() if status != "PASSED"
        )
        if failed:
            execution = getattr(self.run_test, "last_execution", {}) or {}
            evidence = _rtl_regression_failure_evidence(
                report,
                stdout,
                stderr,
                execution.get("pytest_returncode"),
                workspace=Path(self.workspace).resolve(),
                ret_std_out=self.ret_std_out,
                ret_std_error=self.ret_std_error,
            )
            return False, diagnostic(
                "rtl_design_test_failed",
                (
                    "The Python reference run passed, but the current RTL implementation "
                    "failed one or more of the same shared tests. This is a design or "
                    "RTL-adapter mismatch, not a line-coverage deficit; the coverage "
                    "gate must remain blocked until the behavior agrees."
                ),
                (
                    "1. Use observed.failed_cases (including the phase exception and "
                    "CKs) and observed.pytest.failed_nodes to select the first failure.\n"
                    "2. Re-run only that node with Check stage_args.test_target and "
                    "compare the Python and RTL transaction trace: pin widths/signedness, "
                    "packing/decoding, reset, RefreshComb/Step ordering, latency, "
                    "handshake, rounding and saturation are common divergence points.\n"
                    "3. Reconcile the failing vector with README/Spec first: repair "
                    "the reference or shared test only when it contradicts those "
                    "authorities and rerun the Python gate before comparing RTL; "
                    "otherwise fix the selected RTL or shared adapter/runtime and "
                    "keep requirements-derived assertions unchanged.\n"
                    "4. Run the full shared RTL suite with Check. Only after all nodes "
                    "pass should you investigate uncovered authored lines and call Complete."
                ),
                artifact=self.test_dir,
                location=(
                    (evidence.get("failed_nodes") or failed)[0]
                    if isinstance(evidence, dict)
                    else failed[0]
                ),
                observed=evidence,
                expected="All collected test cases have status PASSED.",
            )
        assertion_pass, assertion_message = uc_functions.check_has_assert_in_tc(
            self.workspace, report
        )
        if not assertion_pass:
            return False, diagnostic(
                "rtl_design_test_assertion_missing",
                (
                    "A collected shared test has no executable assertion. A test that "
                    "only drives pins or waits can pass without checking RTL behavior, "
                    "so it cannot serve as functional or coverage evidence."
                ),
                (
                    "1. Read the named test in observed and add an exact assertion for "
                    "the specified output, state, exception, or protocol event.\n"
                    "2. Derive the expected value independently; do not use truthiness, "
                    "self-comparison, or a placeholder assertion.\n"
                    "3. Run the Python reference suite with RunTestCases, then run the "
                    "same test and the complete RTL suite with Check."
                ),
                artifact=self.test_dir,
                location=self.test_dir,
                observed=assertion_message,
                expected="Every shared test case contains assert or pytest.raises.",
            )
        unhit_checkpoints = report.get("unhit_check_point_list", [])
        if unhit_checkpoints:
            associations = report.get("test_case_with_check_point_list", {})
            checkpoint_tests = {
                str(checkpoint): [
                    str(node)
                    for node, checkpoints in associations.items()
                    if isinstance(checkpoints, list) and checkpoint in checkpoints
                ][:20]
                for checkpoint in unhit_checkpoints[:20]
            } if isinstance(associations, dict) else {}
            return False, diagnostic(
                "rtl_design_checkpoint_not_hit",
                (
                    "The RTL regression passed every test, but one or more functional "
                    "checkpoints were never hit. A passing pytest status alone is "
                    "therefore insufficient evidence for the design contract."
                ),
                (
                    "1. Start with the first checkpoint in observed.unhit_checkpoints "
                    "and its associated tests.\n"
                    "2. Check that the test calls the public API, marks the intended CK, "
                    "and drives the specified stimulus/transaction sequence.\n"
                    "3. If the checkpoint is reachable, fix the RTL or test/coverage "
                    "instrumentation while preserving the expected behavior; do not "
                    "remove the CK or weaken its assertion.\n"
                    "4. Re-run the complete shared RTL suite with Check and verify that "
                    "the report contains no unhit checkpoints."
                ),
                artifact=self.doc_func_check,
                location=str(unhit_checkpoints[0]),
                observed={
                    "unhit_checkpoints": [str(value) for value in unhit_checkpoints[:20]],
                    "checkpoint_tests": checkpoint_tests,
                    "truncated": len(unhit_checkpoints) > 20,
                },
                expected="Every functional checkpoint is hit at least once.",
            )
        result: dict[str, Any] = {
            "success": "All shared RTL tests passed under the design delivery contract.",
            "test_case_count": len(tests),
        }
        if self.ret_std_out:
            result["STDOUT"] = stdout
        if self.ret_std_error:
            result["STDERR"] = stderr
        return True, result


class RTLSourceEvidenceChecker(Checker):
    """Bind authored RTL sources to isolated build and all-pass evidence."""

    def __init__(
        self,
        test_dir: str,
        coverage_analysis: str,
        coverage_ignore: str,
        cfg: Any,
        rtl_manifest_file: str,
        rtl_regression_file: str,
        **kwargs: Any,
    ) -> None:
        """Store public evidence paths without scanning the workspace."""

        super().__init__()
        del kwargs
        self.cfg = cfg
        self.test_dir = test_dir
        self.coverage_analysis = coverage_analysis
        self.coverage_ignore = coverage_ignore
        self.rtl_manifest_file = rtl_manifest_file
        self.rtl_regression_file = rtl_regression_file
        self._validated = False

    def get_template_data(self) -> dict[str, str]:
        """Expose only the latest cached evidence state."""

        return {"COVERAGE_COMPLETE": "validated" if self._validated else "pending"}

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require current authored-source hashes to match trusted RTL receipts."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        source_artifact = self.coverage_analysis
        try:
            rtl_config, backend = resolve_rtl_config(self.cfg)
            source_artifact = rtl_config.source_glob
            rtl_files = list(discover_rtl_sources(workspace, rtl_config, backend))
            rtl_rows = _hash_rows(workspace, rtl_files)
            _, library_rows = discover_rtl_libraries(
                workspace, rtl_config, backend
            )
            manifest = load_json(
                resolve_workspace_path(
                    workspace, self.rtl_manifest_file, must_exist=True
                )
            )
            builder = manifest.get("python_dut_builder")
            if (
                manifest.get("schema_version") != "1.4"
                or manifest.get("rtl_language") != rtl_config.language
                or manifest.get("rtl_config") != rtl_config.identity()
                or manifest.get("rtl_sources") != rtl_rows
                or manifest.get("rtl_libraries") != list(library_rows)
                or manifest.get("synthesis_smoke") != "pass"
                or not isinstance(builder, dict)
                or builder.get("coverage") is not True
                or builder.get("waveform_format") != "vcd"
            ):
                raise ValueError(
                    "current authored sources do not match the isolated RTL build receipt"
                )
            runtime._validate_workspace_python_dut(workspace, manifest)
            regression = load_json(
                resolve_workspace_path(
                    workspace, self.rtl_regression_file, must_exist=True
                )
            )
            if regression.get("backend") != "rtl" or regression.get("status") != "pass":
                raise ValueError("the current RTL all-pass regression receipt is invalid")
            test_dir = resolve_workspace_path(workspace, self.test_dir, must_exist=True)
            current_sources = sorted(
                {
                    *rtl_files,
                    *(
                        path.resolve()
                        for path in test_dir.rglob("*.py")
                        if path.is_file()
                        and not path.is_symlink()
                        and "__pycache__" not in path.parts
                    ),
                },
                key=lambda path: path.as_posix(),
            )
            if regression.get("sources") != _hash_rows(workspace, current_sources):
                raise ValueError(
                    "authored RTL or Python test sources changed after the all-pass regression"
                )
            if regression.get("rtl_libraries") != list(library_rows):
                raise ValueError(
                    "configured RTL libraries changed after the all-pass regression"
                )
            analysis_path = resolve_workspace_path(workspace, self.coverage_analysis)
            ignore_path = resolve_workspace_path(workspace, self.coverage_ignore)
            atomic_text(ignore_path, "")
            atomic_text(
                analysis_path,
                (
                    f"\n# {_cfg_dut(self.cfg)} {backend.display_name} Source Validation\n\n"
                    "## Result\n\n"
                    f"- Authored language: `{backend.display_name}`\n"
                    "- Isolated preparation and synthesis smoke: `Pass`\n"
                    "- Shared RTL functional regression: `Pass`\n"
                    f"- Bound authored source files: `{len(rtl_rows)}`\n"
                    f"- Bound library source files: `{len(library_rows)}`\n\n"
                    "## Coverage Interpretation\n\n"
                    "Feature coverage and the shared Python/RTL regression are the "
                    "acceptance evidence. Generated implementation line coverage is "
                    f"not projected onto authored {backend.display_name} source and is "
                    "not exposed as an authored-source metric.\n"
                ),
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            self._validated = False
            return False, _exception_contract_diagnostic(
                error_code="rtl_source_evidence_invalid",
                error="The authored RTL sources are not bound to current build and all-pass regression evidence.",
                exc=exc,
                artifact=source_artifact,
                guide="Guide_Doc/rtl_backend.md",
                expected=(
                    "Current authored RTL, configured libraries, shared Python tests, "
                    "automatic RTL validation receipt, and full RTL all-pass receipt all "
                    "have matching hashes."
                ),
            )
        self._validated = True
        return True, {
            "message": "Authored RTL sources match isolated build and all-pass evidence.",
            "source_files": [row["path"] for row in rtl_rows],
            "report": analysis_path.relative_to(workspace).as_posix(),
        }


class RTLBackendBuildChecker(Checker):
    """Prepare isolated RTL validation for the selected source language."""

    def __init__(
        self,
        architecture_file: str,
        manifest_file: str,
        timeout: int,
        cfg: Any,
        input_manifest_file: str | None = None,
        contract_files: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Store backend build paths and validate the configured timeout."""

        super().__init__()
        del kwargs
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("timeout must be a positive integer")
        if contract_files is not None and (
            not isinstance(contract_files, list)
            or any(not isinstance(value, str) or not value for value in contract_files)
        ):
            raise ValueError("contract_files must be a list of non-empty strings")
        self.cfg = cfg
        self.rtl_config, self.rtl_language_backend = resolve_rtl_config(cfg)
        self.architecture_file = architecture_file
        self.manifest_file = manifest_file
        self.timeout = timeout
        self.input_manifest_file = input_manifest_file
        self.contract_files = list(contract_files or [])

    def get_template_data(self) -> dict[str, str]:
        """Expose only the selected source-language contract to the active stage."""

        return {
            "RTL_LANGUAGE": self.rtl_language_backend.display_name,
            "RTL_SOURCE_GLOB": self.rtl_config.source_glob,
            "RTL_SOURCE_TEMPLATE": self.rtl_config.source_template,
        }

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Normalize RTL, run synthesis smoke, and synchronize by source hash."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        active_operation = "input_validation"
        build_root: Path | None = None
        language_build_root: Path | None = None
        target: Path | None = None
        picker_completed: subprocess.CompletedProcess[str] | None = None
        try:
            architecture = load_fenced_yaml(
                resolve_workspace_path(
                    workspace, self.architecture_file, must_exist=True
                ),
                "architecture",
            )
            top = architecture.get("top_module")
            if not isinstance(top, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(top):
                raise ValueError("architecture top_module is invalid")
            rtl_files = list(
                discover_rtl_sources(
                    workspace, self.rtl_config, self.rtl_language_backend
                )
            )
            library_files, library_rows = discover_rtl_libraries(
                workspace, self.rtl_config, self.rtl_language_backend
            )
            package_name = _cfg_dut(self.cfg)
            if not _PYTHON_IDENTIFIER_RE.fullmatch(package_name):
                raise ValueError("DUT must be a portable Python package identifier")
            runtime_root = runtime._workspace_python_dut_root(workspace)
            candidate = runtime_root
            while candidate != workspace:
                if candidate.exists() and candidate.is_symlink():
                    raise ValueError(
                        "generated Python-DUT runtime must not traverse symbolic links"
                    )
                candidate = candidate.parent
            if not runtime_root.resolve().is_relative_to(workspace):
                raise ValueError("generated Python-DUT runtime escaped the workspace")
            runtime_root.mkdir(parents=True, exist_ok=True)
            target = runtime_root / package_name
            if target.is_symlink():
                raise ValueError("generated Python-DUT target must not be a symlink")
            if target.exists() and not target.is_dir():
                raise ValueError("generated Python-DUT target must be a directory")
            rtl_rows = _hash_rows(workspace, rtl_files)
            design_inputs = (
                _validated_input_identity(workspace, self.input_manifest_file)
                if self.input_manifest_file is not None
                else None
            )
            contracts = (
                _contract_identity(workspace, self.contract_files)
                if self.contract_files
                else None
            )
            manifest_path = resolve_workspace_path(workspace, self.manifest_file)
            if manifest_path.is_file() and not manifest_path.is_symlink():
                try:
                    current_manifest = load_json(manifest_path)
                    generated_content = current_manifest.get("generated_content")
                    prepared_content = current_manifest.get("prepared_content")
                    if (
                        current_manifest.get("schema_version") == "1.4"
                        and current_manifest.get("top_module") == top
                        and current_manifest.get("rtl_language")
                        == self.rtl_config.language
                        and current_manifest.get("rtl_config")
                        == self.rtl_config.identity()
                        and current_manifest.get("rtl_sources") == rtl_rows
                        and current_manifest.get("rtl_libraries")
                        == list(library_rows)
                        and current_manifest.get("design_inputs") == design_inputs
                        and current_manifest.get("contracts") == contracts
                        and isinstance(prepared_content, dict)
                        and set(prepared_content) == {"analysis", "python_dut"}
                        and current_manifest.get("python_dut_import")
                        == {
                            "module": package_name,
                            "class": f"DUT{top}",
                        }
                        and isinstance(generated_content, dict)
                        and isinstance(
                            current_manifest.get("python_dut_builder"), dict
                        )
                        and current_manifest["python_dut_builder"].get("coverage")
                        is True
                        and current_manifest["python_dut_builder"].get(
                            "waveform_format"
                        )
                        == "vcd"
                    ):
                        runtime._validate_workspace_python_dut(workspace, current_manifest)
                        return True, {
                            "message": "RTL validation already matches the current source hashes.",
                            "top_module": top,
                            "rtl_language": self.rtl_config.language,
                            "source_files": [row["path"] for row in rtl_rows],
                            "library_source_count": len(library_rows),
                        }
                except (OSError, ValueError, FileNotFoundError, subprocess.TimeoutExpired):
                    pass
            language_build_root = Path(
                tempfile.mkdtemp(prefix="ucagent-design-with-ppa-rtl-")
            )
            language_build_dir = language_build_root / self.rtl_config.language
            language_build_dir.mkdir(parents=True)
            active_operation = "rtl_language_prepare"
            preparation_request = RTLPreparationRequest(
                workspace=workspace,
                language=self.rtl_config.language,
                top_module=top,
                source_files=tuple(rtl_files),
                library_files=library_files,
                build_dir=language_build_dir,
                language_options=self.rtl_config.language_options,
                python_dut_options=self.rtl_config.python_dut_options,
                timeout=self.timeout,
            )
            prepared = validate_prepared_rtl(
                workspace,
                preparation_request,
                self.rtl_language_backend.prepare(preparation_request),
            )
            analysis_files = list(prepared.analysis_verilog_files)
            python_dut_files = list(prepared.python_dut_files)
            private_analysis_files = tuple(
                path for path in analysis_files if path not in rtl_files
            )
            prepared_content = prepared.content_identity()
            yosys = shutil.which("yosys")
            if yosys is None:
                raise ValueError("yosys command was not found in PATH")
            yosys_sources = " ".join(
                '"' + str(path).replace('"', '\\"') + '"'
                for path in analysis_files
            )
            yosys_script = (
                f"read_verilog {yosys_sources}; "
                f"hierarchy -check -top {top}; proc; check"
            )
            active_operation = "yosys_smoke"
            yosys_result = subprocess.run(
                [yosys, "-q", "-p", yosys_script],
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
            if yosys_result.returncode != 0:
                hazard_evidence = (
                    _verilog_synthesis_hazard_evidence(workspace, rtl_files)
                    if self.rtl_config.language == "verilog"
                    else []
                )
                parser_output = _redact_backend_output(
                    f"{yosys_result.stdout}\n{yosys_result.stderr}",
                    6000,
                    (workspace,),
                ).strip()
                if hazard_evidence:
                    error_text = (
                        "The synthesis smoke check rejected the current RTL. "
                        "The source contains constructs that are normally simulation-only "
                        "or outside the selected synthesizable language subset."
                    )
                    repair_steps = (
                        "1. Repair every item in observed.synthesis_hazards, starting with "
                        "the lowest source line; these are hints derived from authored "
                        "source, while the Yosys message remains authoritative.\n"
                        "2. Keep the architecture and Python test expectations unchanged. "
                        "Use fixed-width integer/fixed-point logic, case/lookup thresholds, "
                        "clocked registers, and explicit handshake state instead of the "
                        "reported simulation construct.\n"
                        "3. Re-read Guide_Doc/coding_standard_verilog.md, then call Check. "
                        "Do not hand-edit generated Python-DUT files or coverage artifacts.\n"
                        "4. After synthesis passes, fix any first RTL shared-test failure; "
                        "only a complete all-pass RTL run can generate valid coverage."
                    )
                else:
                    error_text = (
                        "The synthesis smoke check rejected the current RTL or top-module "
                        "contract before RTL tests and coverage could run."
                    )
                    repair_steps = (
                        "1. Read observed.tool_output and identify the first source, line, "
                        "module, port, or hierarchy error.\n"
                        "2. Repair the selected-language source using the documented "
                        "synthesizable subset; keep architecture and test expectations "
                        "unchanged.\n"
                        "3. Call Check to rerun synthesis and then the managed RTL build. "
                        "Do not hand-edit generated wrappers or reports.\n"
                        "4. Once synthesis passes, fix the first shared RTL test failure "
                        "before investigating line coverage."
                    )
                observed = (
                    {"returncode": yosys_result.returncode}
                    if private_analysis_files
                    else {
                        "returncode": yosys_result.returncode,
                        "stdout_tail": _redact_backend_output(
                            yosys_result.stdout, 6000, (workspace,)
                        ),
                        "stderr_tail": _redact_backend_output(
                            yosys_result.stderr, 6000, (workspace,)
                        ),
                        "tool_output": parser_output,
                        "tool_errors": tool_error_lines(
                            f"{yosys_result.stdout}\n{yosys_result.stderr}"
                        ),
                        "synthesis_hazards": hazard_evidence,
                        "tests_not_run": "RTL regression, line coverage, and PPA were not run because synthesis failed",
                        "coverage_pipeline": _coverage_pipeline_status("synthesis"),
                    }
                )
                return False, diagnostic(
                    "rtl_synthesis_failed",
                    error_text,
                    repair_steps,
                    artifact=self.rtl_config.source_glob,
                    location=(
                        f"{hazard_evidence[0]['path']}:{hazard_evidence[0]['line']}"
                        if hazard_evidence
                        else self.rtl_config.source_glob
                    ),
                    observed=observed,
                    expected=(
                        "A top-module hierarchy accepted by synthesis using the selected "
                        "RTL language's synthesizable subset; no simulation-only arithmetic, "
                        "timing controls, or system tasks in authored sources."
                    ),
                )
            width_warnings = (
                _yosys_width_warning_evidence(
                    workspace,
                    f"{yosys_result.stdout}\n{yosys_result.stderr}",
                    rtl_files,
                )
                if self.rtl_config.language == "verilog"
                and not private_analysis_files
                else []
            )
            if width_warnings:
                return False, diagnostic(
                    "rtl_synthesis_width_warning",
                    (
                        "Synthesis completed, but the authored Verilog contains literal "
                        "values that are narrower than the values they encode. The tool "
                        "will truncate those constants, so numerical behavior is not a "
                        "trustworthy RTL implementation even though parsing succeeded."
                    ),
                    (
                        "1. Fix every item in observed.width_warnings, starting with the "
                        "first source line; make the literal/intermediate width large "
                        "enough for the intended value and preserve signedness explicitly.\n"
                        "2. If truncation is intentional, replace the narrow literal with "
                        "an explicitly sized intermediate and a documented part-select; "
                        "do not silence the warning by deleting the value or changing tests.\n"
                        "3. Re-read Guide_Doc/coding_standard_verilog.md sections on "
                        "width/constants and signed arithmetic, then call Check.\n"
                        "4. RTL regression, coverage, and PPA have not run for this source; "
                        "after warnings are resolved, fix the first shared test failure "
                        "before analyzing coverage."
                    ),
                    artifact=self.rtl_config.source_glob,
                    location=(
                        f"{width_warnings[0]['path']}:{width_warnings[0]['line']}"
                    ),
                    observed={
                        "returncode": yosys_result.returncode,
                        "width_warnings": width_warnings,
                        "tests_not_run": "RTL regression, line coverage, and PPA were not run because authored literal-width warnings are unresolved",
                        "coverage_pipeline": _coverage_pipeline_status("synthesis"),
                    },
                    expected="No authored literal is narrower than its encoded value; intentional truncation uses an explicitly wide intermediate and part-select.",
                )
            picker = shutil.which("picker")
            if picker is None:
                raise ValueError("the RTL validation environment is unavailable")
            active_operation = "picker_version"
            version_result = subprocess.run(
                [picker, "--version"],
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            picker_version = (version_result.stdout or version_result.stderr).strip()
            if version_result.returncode != 0 or not picker_version:
                return False, diagnostic(
                    "rtl_validation_environment_invalid",
                    "The RTL validation environment did not return a usable version.",
                    "Do not change RTL to work around this infrastructure failure. Repair the workflow installation so its automatic RTL validation command returns a version and supports export, then call Check again.",
                    artifact="workflow RTL validation dependency",
                    location="workflow installation",
                    observed={
                        "returncode": version_result.returncode,
                        "stdout_tail": _redact_backend_output(version_result.stdout, 2000),
                        "stderr_tail": _redact_backend_output(version_result.stderr, 2000),
                    },
                    expected="The automatic RTL validation dependency returns success and a non-empty version string.",
                )
            build_root = Path(tempfile.mkdtemp(prefix=".build-", dir=runtime_root))
            build_target = build_root / target.name
            # Picker's positional ``file`` arguments are parsed as a single
            # source bundle by some releases.  With multiple authored files
            # and read-only library files that mode can overwrite a basename
            # and include the same library twice.  The documented ``--fs``
            # file-list path preserves the complete ordered source set.
            picker_filelist = build_root / "rtl_sources.f"
            picker_filelist.write_text(
                "\n".join(str(path) for path in python_dut_files) + "\n",
                encoding="utf-8",
            )
            command = [
                picker,
                "export",
                "--fs",
                str(picker_filelist),
                "--lang",
                "python",
                "--sname",
                top,
                "--coverage",
                "--wave_file_name",
                "ucagent.vcd",
                "--tdir",
                str(build_target),
            ]
            active_operation = "picker_export"
            picker_completed = subprocess.run(
                command,
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
            if picker_completed.returncode != 0:
                return False, diagnostic(
                    "rtl_validation_prepare_failed",
                    "RTL validation preparation rejected the current design.",
                    "Read the first source/module/port error in observed. Repair the selected-language source, declared top hierarchy, configured libraries, or language options named there, then call Check again; do not edit generated test-runtime files.",
                    artifact=self.rtl_config.source_glob,
                    location=self.rtl_config.source_glob,
                    observed=(
                        {"returncode": picker_completed.returncode}
                        if private_analysis_files
                        else {
                            "returncode": picker_completed.returncode,
                            "tool_errors": tool_error_lines(
                                f"{picker_completed.stdout}\n{picker_completed.stderr}"
                            ),
                            "stdout_tail": _redact_backend_output(
                                picker_completed.stdout,
                                6000,
                                (build_root, target),
                            ),
                            "stderr_tail": _redact_backend_output(
                                picker_completed.stderr,
                                6000,
                                (build_root, target),
                            ),
                        }
                    ),
                    expected="The complete authored source/library set elaborates the architecture top and can be converted into an isolated test runtime.",
                )
            generated_files = sorted(
                path.resolve()
                for path in build_target.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
            python_files = [path for path in generated_files if path.suffix == ".py"]
            if not python_files:
                return False, diagnostic(
                    "rtl_validation_prepare_empty",
                    "Automatic RTL validation completed without producing a usable test runtime.",
                    "Read observed.stdout_tail and stderr_tail. Repair the selected-language source/top hierarchy when they name a design error; otherwise repair the workflow RTL validation installation. Then call Check again and do not create or edit generated runtime files manually.",
                    artifact=self.rtl_config.source_glob,
                    location=self.rtl_config.source_glob,
                    observed={
                        "operation": "rtl_validation_export",
                        "generated_file_count": len(generated_files),
                        "generated_files": [
                            path.name
                            for path in generated_files[:50]
                        ],
                        "generated_files_truncated": len(generated_files) > 50,
                        "stdout_tail": _redact_backend_output(
                            picker_completed.stdout if picker_completed else "",
                            6000,
                            (build_root, target),
                        ),
                        "stderr_tail": _redact_backend_output(
                            picker_completed.stderr if picker_completed else "",
                            6000,
                            (build_root, target),
                        ),
                    },
                    expected="Automatic RTL validation creates a non-empty, importable workspace test runtime for the declared top module.",
                )
            class_name = f"DUT{top}"
            _validate_python_dut_tree(build_target, class_name)
            active_operation = "rtl_runtime_probe"
            _probe_python_dut_subprocess(
                build_target.parent,
                package_name,
                class_name,
                self.timeout,
            )
            backup: Path | None = None
            if target.exists():
                fd, backup_name = tempfile.mkstemp(
                    prefix=f".{target.name}.previous-", dir=target.parent
                )
                os.close(fd)
                os.unlink(backup_name)
                backup = Path(backup_name)
                os.replace(target, backup)
            try:
                os.replace(build_target, target)
            except Exception:
                if backup is not None and backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
            if backup is not None and backup.exists():
                shutil.rmtree(backup)
            generated_content = _generated_python_dut_identity(target)
            manifest = {
                "schema_version": "1.4",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rtl_language": self.rtl_config.language,
                "rtl_config": self.rtl_config.identity(),
                "prepared_content": prepared_content,
                "synthesis_smoke": "pass",
                "python_dut_builder": {
                    "status": "pass",
                    "version_sha256": hashlib.sha256(
                        picker_version.encode("utf-8")
                    ).hexdigest(),
                    "coverage": True,
                    "waveform_format": "vcd",
                },
                "top_module": top,
                "backend": "python",
                "python_dut_import": {
                    "module": package_name,
                    "class": class_name,
                },
                "rtl_sources": rtl_rows,
                "rtl_libraries": list(library_rows),
                "generated_content": generated_content,
                "design_inputs": design_inputs,
                "contracts": contracts,
            }
            atomic_json(manifest_path, manifest)
        except subprocess.TimeoutExpired as exc:
            timeout_observed = {
                "operation": active_operation,
                "timeout_seconds": 30 if active_operation == "picker_version" else self.timeout,
                "reason": _redact_backend_output(str(exc), 2000),
                "partial_stdout_tail": _redact_backend_output(
                    runtime.timeout_stream_fragment(exc.stdout), 2000, (workspace,)
                ),
                "partial_stderr_tail": _redact_backend_output(
                    runtime.timeout_stream_fragment(exc.stderr), 2000, (workspace,)
                ),
            }
            if active_operation == "yosys_smoke":
                return False, diagnostic(
                    "yosys_smoke_timeout",
                    f"Yosys smoke exceeded {self.timeout} seconds.",
                    "Reduce accidental elaboration complexity or repair a recursive/invalid authored hierarchy, then call Check. Increase the configured timeout only after the same finite source set is known to synthesize normally.",
                    artifact=self.rtl_config.source_glob,
                    location=self.rtl_config.source_glob,
                    observed=timeout_observed,
                    expected=f"The complete authored hierarchy passes synthesis smoke within {self.timeout} seconds.",
                )
            if active_operation == "picker_version":
                return False, diagnostic(
                    "rtl_validation_environment_timeout",
                    "The RTL validation environment check exceeded 30 seconds.",
                    "Do not alter RTL for this dependency failure. Repair the workflow RTL validation installation so its version check terminates, then call Check again.",
                    artifact="workflow RTL validation dependency",
                    location="workflow installation",
                    observed=timeout_observed,
                    expected="The automatic RTL validation dependency reports its version within 30 seconds.",
                )
            if active_operation == "rtl_language_prepare":
                return False, diagnostic(
                    "rtl_language_prepare_timeout",
                    f"The {self.rtl_config.language} source preparation exceeded {self.timeout} seconds.",
                    "Inspect the authored hierarchy and selected-language build inputs for recursion, unbounded generation, or stalled dependency resolution. Repair that source/configuration issue, then call Check; increase the timeout only for a known finite build.",
                    artifact=self.rtl_config.source_glob,
                    location=self.rtl_config.source_glob,
                    observed=timeout_observed,
                    expected=f"Selected-language preparation terminates within {self.timeout} seconds.",
                )
            if active_operation == "rtl_runtime_probe":
                return False, diagnostic(
                    "rtl_validation_runtime_timeout",
                    "The generated RTL test runtime did not initialize in time.",
                    "Check the declared top/ports and authored static initialization for a startup stall. If those match architecture, repair the workflow RTL validation installation. Call Check again; do not import or edit the generated runtime manually.",
                    artifact=self.rtl_config.source_glob,
                    location=self.rtl_config.source_glob,
                    observed=timeout_observed,
                    expected=f"The isolated RTL test runtime initializes within {self.timeout} seconds.",
                )
            return False, diagnostic(
                "rtl_validation_prepare_timeout",
                f"RTL validation preparation exceeded {self.timeout} seconds.",
                "Use observed.operation to identify the stalled validation step. Repair the selected-language source/configuration when it is a design build; otherwise repair the workflow dependency, then call Check again.",
                artifact=self.rtl_config.source_glob,
                location=self.rtl_config.source_glob,
                observed=timeout_observed,
                expected=f"Every automatic RTL validation step terminates within {self.timeout} seconds.",
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            observed: dict[str, Any] = {"operation": "rtl_validation_prepare"}
            if picker_completed is not None:
                observed.update(
                    {
                        "returncode": picker_completed.returncode,
                        "stdout_tail": _redact_backend_output(
                            picker_completed.stdout,
                            6000,
                            (build_root, target),
                        ),
                        "stderr_tail": _redact_backend_output(
                            picker_completed.stderr,
                            6000,
                            (build_root, target),
                        ),
                    }
                )
            reason = _redact_backend_output(
                str(exc),
                4000,
                tuple(
                    path
                    for path in (
                        language_build_root,
                        build_root,
                        target,
                    )
                    if path is not None
                ),
            )
            return False, diagnostic(
                "rtl_validation_prepare_invalid",
                (
                    "Automatic RTL validation could not prepare the current authored "
                    f"design. First problem: {_inline_reason(reason)}"
                ),
                (
                    "Use observed.reason and observed.operation to distinguish an authored "
                    "architecture/source/library problem from a missing workflow dependency. "
                    "Repair only the named source or configuration, then call Check again; "
                    "do not import, create, or modify generated test-runtime files."
                ),
                artifact=self.rtl_config.source_glob,
                location=self.rtl_config.source_glob,
                observed={
                    **observed,
                    "reason": reason,
                },
                expected="A current architecture-consistent authored source/library set and an available automatic RTL validation dependency.",
            )
        finally:
            if build_root is not None and build_root.exists():
                shutil.rmtree(build_root, ignore_errors=True)
            if language_build_root is not None and language_build_root.exists():
                shutil.rmtree(language_build_root, ignore_errors=True)
        return True, {
            "message": "RTL validation is ready for the current source hashes.",
            "top_module": top,
            "rtl_language": self.rtl_config.language,
            "source_files": [row["path"] for row in rtl_rows],
            "library_source_count": len(library_rows),
        }
