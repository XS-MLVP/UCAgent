"""Early design-contract gates: inputs, labels, API, all-pass smoke."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
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
from ..contracts import (
    atomic_json,
    diagnostic,
    resolve_workspace_path,
)

from .common import (
    _DESIGN_LABEL_IDENTIFIER_RE,
    _PROCESS_ONLY_CK_TERM_RE,
    _actionable_checker_failure,
    _exception_contract_diagnostic,
    _hash_rows,
)




class DesignMarkdownFileFormatChecker(UnityChipCheckerMarkdownFileFormat):
    """Expose actionable Markdown diagnostics for DesignWithPPA artifacts."""

    def do_check(self, timeout: int = 0, **kwargs: Any):
        """Identify the exact Markdown artifact and repair before retrying."""

        passed, result = super().do_check(timeout=timeout, **kwargs)
        if passed:
            return passed, result
        artifact = self.markdown_file_list[0] if self.markdown_file_list else "<markdown>"
        return False, _actionable_checker_failure(
            result,
            error_code="design_markdown_invalid",
            error="A required DesignWithPPA Markdown artifact is missing or malformed.",
            next_action=(
                "Open the artifact named in observed.checker_result, create it when "
                "missing, replace literal '\\n' text with real line breaks, preserve "
                "blank lines "
                "around every heading, then call Check again."
            ),
            artifact=artifact,
            expected=(
                "Every configured Markdown artifact is a readable workspace file with "
                "real line breaks and canonical heading spacing."
            ),
        )




class DesignLabelStructureChecker(UnityChipCheckerLabelStructure):
    """Expose bounded FG/FC/CK hierarchy failures with a concrete repair path."""

    def do_check(self, timeout: int = 0, **kwargs: Any):
        """Validate the label tree and normalize inherited failure details."""

        passed, result = super().do_check(timeout=timeout, **kwargs)
        if passed:
            return passed, result
        return False, _actionable_checker_failure(
            result,
            error_code="design_label_structure_invalid",
            error="The FG/FC/CK hierarchy cannot be used as the functional contract.",
            next_action=(
                f"Open {self.doc_file}, repair the first file, tag, duplicate ID, or "
                "hierarchy error reported in observed.checker_result using "
                "Guide_Doc/design_ut_contract.md, then call Check again."
            ),
            artifact=self.doc_file,
            expected=(
                f"A parseable FG -> FC -> {self.leaf_node} hierarchy with at least "
                f"{self.min_count} in-scope {self.leaf_node} tag(s) and unique IDs."
            ),
        )




class DesignDutApiChecker(UnityChipCheckerDutApi):
    """Bind public API failures to the DesignWithPPA shared-test contract."""

    def do_check(self, timeout: int = 0, **kwargs: Any):
        """Validate API source and add canonical guidance to inherited failures."""

        passed, result = super().do_check(timeout=timeout, **kwargs)
        if passed:
            return passed, result
        return False, _actionable_checker_failure(
            result,
            error_code="design_public_api_invalid",
            error="The shared public test API does not satisfy its source contract.",
            next_action=(
                f"Open {self.target_file} at the reported location. Repair the named "
                f"api_* function so its first argument is env, any bounded wait uses a "
                "final max_cycles default, and its docstring contains Args: and Returns:. "
                "Do not access private DUT state, private event/transaction helpers, or "
                "assign normalized event evidence; then call Check again. See "
                "Guide_Doc/python_dut_interface.md."
            ),
            artifact=self.target_file,
            expected=(
                f"At least {self.min_apis} documented public function(s) beginning with "
                f"{self.api_prefix}, without private DUT/state access or evidence "
                "manipulation."
            ),
        )




class DesignPythonAllPassChecker(UnityChipCheckerTestMustPass):
    """Require the selected Python-reference tests to pass with actionable evidence."""

    def do_check(self, timeout: int = 0, **kwargs: Any):
        """Run the reference gate and normalize collection, assertion, and test failures."""

        passed, result = super().do_check(timeout=timeout, **kwargs)
        if passed:
            return passed, result
        return False, _actionable_checker_failure(
            result,
            error_code="design_python_all_pass_failed",
            error="The selected shared tests did not prove the Python executable specification.",
            next_action=(
                "Start with the first failed node or collection error in "
                "observed.checker_result. Compare it with README, Spec, architecture, "
                "and FG/FC/CK: repair the reference and affected shared artifacts when "
                "the reference contradicts those sources; otherwise repair the test, API, "
                "adapter, fixture, or independently derived expected value. Rerun the "
                "exact node with RunTestCases, then call Check again. Do not skip the test, "
                "weaken its assertion, or preserve the failure as a DUT Bug."
            ),
            artifact=", ".join(self.target_file_list),
            location=self.test_dir,
            expected=(
                "Every selected shared test is collected, contains an executable exact "
                "assertion, and passes against the requirements-conformant Python reference."
            ),
        )




class DesignInputContractChecker(Checker):
    """Validate immutable README/Spec inputs and persist their current source hashes."""

    def __init__(
        self,
        readme_file: str,
        spec_glob: str,
        manifest_file: str,
        cfg: Any,
        **kwargs: Any,
    ) -> None:
        """Store source patterns without scanning the workspace during construction."""

        super().__init__()
        del kwargs
        self.cfg = cfg
        self.readme_file = readme_file
        self.spec_glob = spec_glob
        self.manifest_file = manifest_file
        self._cached_input_count = 0

    def get_template_data(self) -> dict[str, int]:
        """Expose only the most recently checked source count."""

        return {"DESIGN_INPUT_FILE_COUNT": self._cached_input_count}

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require a non-empty README and at least one stable sorted Markdown Spec."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            readme = resolve_workspace_path(workspace, self.readme_file, must_exist=True)
        except (ValueError, FileNotFoundError) as exc:
            return False, diagnostic(
                "design_readme_missing",
                "The required design README cannot be read.",
                f"Create a non-empty design README at {self.readme_file}, then call Check.",
                artifact=self.readme_file,
                location=self.readme_file,
                observed={"reason": str(exc), "exists": False},
                expected="One readable, non-symlink, non-empty Markdown requirements file.",
            )
        if readme.is_symlink() or not readme.is_file() or not readme.read_text(
            encoding="utf-8"
        ).strip():
            return False, diagnostic(
                "design_readme_empty",
                "The design README is absent, non-regular, or empty.",
                f"Provide the design requirements in {self.readme_file}, then call Check.",
                artifact=self.readme_file,
                location=self.readme_file,
                observed={
                    "is_file": readme.is_file(),
                    "is_symlink": readme.is_symlink(),
                    "nonempty": bool(readme.read_text(encoding="utf-8").strip()),
                },
                expected="A regular, non-symlink Markdown file containing normative design requirements.",
            )
        spec_pattern = Path(self.spec_glob)
        if spec_pattern.is_absolute() or ".." in spec_pattern.parts:
            return False, diagnostic(
                "design_spec_pattern_invalid",
                "The Spec glob must remain workspace-relative.",
                "Stop editing generated artifacts. Change spec_glob to a workspace-relative pattern without '..', restart the workflow, and call Check again.",
                artifact="spec_glob",
                location="workflow configuration: spec_glob",
                observed=self.spec_glob,
                expected="A workspace-relative glob such as DUT/spec/**/*.md.",
            )
        specs = sorted(
            (
                path.resolve()
                for path in workspace.glob(self.spec_glob)
                if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".md"
            ),
            key=lambda item: item.relative_to(workspace).as_posix(),
        )
        if not specs:
            return False, diagnostic(
                "design_spec_set_empty",
                "No Markdown design Spec files matched the configured source set.",
                f"Add at least one non-empty Markdown file matching {self.spec_glob}, then call Check.",
                artifact=self.spec_glob,
                location=self.spec_glob,
                observed={"matched_markdown_files": 0},
                expected="At least one regular, non-symlink, non-empty Markdown Spec file.",
            )
        empty = [
            path.relative_to(workspace).as_posix()
            for path in specs
            if not path.read_text(encoding="utf-8").strip()
        ]
        if empty:
            return False, diagnostic(
                "design_spec_empty",
                "One or more design Spec files are empty.",
                "Add normative content to every listed Spec, then call Check.",
                artifact=self.spec_glob,
                location=empty[0],
                observed={
                    "empty_files": empty[:20],
                    "truncated": len(empty) > 20,
                },
                expected="Every matched Markdown Spec contains normative design content.",
            )
        rows = _hash_rows(workspace, [readme, *specs])
        manifest = {
            "schema_version": "1.0",
            "readme": rows[0],
            "spec_files": rows[1:],
            "source_set_sha256": hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        destination = resolve_workspace_path(workspace, self.manifest_file)
        atomic_json(destination, manifest)
        self._cached_input_count = len(rows)
        return True, {
            "message": "Design input contract is complete.",
            "manifest": destination.relative_to(workspace).as_posix(),
            "source_set_sha256": manifest["source_set_sha256"],
            "input_files": len(rows),
        }




class DesignFunctionalContractChecker(Checker):
    """Require portable, unique FG/FC/CK machine identifiers in a design contract."""

    def __init__(self, doc_file: str, **kwargs: Any) -> None:
        """Store the generated functional-contract path for live validation."""

        super().__init__()
        del kwargs
        self.doc_file = doc_file

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Reject descriptive text, whitespace, separators, and duplicate tag IDs."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            source = resolve_workspace_path(workspace, self.doc_file, must_exist=True)
            lines = source.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_function_contract_missing",
                error="The functional-contract document is missing or unreadable.",
                exc=exc,
                artifact=self.doc_file,
                guide="Guide_Doc/design_ut_contract.md",
                expected="One readable Markdown document containing the canonical FG -> FC -> CK hierarchy.",
            )
        identifiers: list[tuple[int, str]] = []
        invalid: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            for match in re.finditer(r"<((?:FG|FC|CK)-[^<>\r\n]+)>", line):
                identifier = match.group(1)
                identifiers.append((line_number, identifier))
                if not _DESIGN_LABEL_IDENTIFIER_RE.fullmatch(identifier):
                    invalid.append({"line": line_number, "identifier": identifier})
        if invalid:
            return False, diagnostic(
                "design_label_identifier_invalid",
                "One or more FG/FC/CK machine tags contain descriptive or non-portable text.",
                "Keep the readable title in its Markdown heading and replace each tag with only a portable FG-*, FC-*, or CK-* identifier, then call Check.",
                artifact=self.doc_file,
                location=self.doc_file,
                observed={
                    "invalid": invalid[:20],
                    "truncated": len(invalid) > 20,
                },
                expected=(
                    "Machine tags use only letters, digits, dots, underscores, and "
                    "hyphens after the FG-/FC-/CK- prefix."
                ),
            )
        counts: dict[str, list[int]] = {}
        for line_number, identifier in identifiers:
            counts.setdefault(identifier, []).append(line_number)
        duplicates = [
            {"identifier": identifier, "lines": line_numbers[:20]}
            for identifier, line_numbers in sorted(counts.items())
            if len(line_numbers) > 1
        ]
        if duplicates:
            return False, diagnostic(
                "design_label_identifier_duplicate",
                "One or more FG/FC/CK machine identifiers are repeated.",
                "Give every FG, FC, and CK a document-wide unique machine identifier, update its references, then call Check.",
                artifact=self.doc_file,
                location=self.doc_file,
                observed={
                    "duplicates": duplicates[:20],
                    "truncated": len(duplicates) > 20,
                },
                expected="Every FG/FC/CK machine identifier appears exactly once.",
            )
        current_group: str | None = None
        current_feature: str | None = None
        active_checkpoint: dict[str, Any] | None = None
        checkpoint_sections: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            tag = re.fullmatch(
                r"\s*<((?:FG|FC|CK)-[A-Za-z0-9][A-Za-z0-9_.-]*)>\s*",
                line,
            )
            if tag is not None:
                identifier = tag.group(1)
                if identifier.startswith("FG-"):
                    current_group = identifier
                    current_feature = None
                    active_checkpoint = None
                elif identifier.startswith("FC-"):
                    current_feature = identifier
                    active_checkpoint = None
                else:
                    active_checkpoint = {
                        "checkpoint": "/".join(
                            part
                            for part in (current_group, current_feature, identifier)
                            if part is not None
                        ),
                        "group": current_group,
                        "line": line_number,
                        "body": [],
                    }
                    checkpoint_sections.append(active_checkpoint)
                continue
            if active_checkpoint is not None:
                active_checkpoint["body"].append((line_number, line))

        process_only: list[dict[str, Any]] = []
        for section in checkpoint_sections:
            group = section["group"]
            if isinstance(group, str) and (
                group == "FG-PPA" or group.startswith("FG-PPA-")
            ):
                continue
            matches: dict[str, int] = {}
            for line_number, line in section["body"]:
                prose = re.sub(r"`[^`]*`", "", line)
                for match in _PROCESS_ONLY_CK_TERM_RE.finditer(prose):
                    matches.setdefault(match.group(0).lower(), line_number)
            if matches:
                process_only.append(
                    {
                        "checkpoint": section["checkpoint"],
                        "line": section["line"],
                        "terms": [
                            {"term": term, "line": line_number}
                            for term, line_number in sorted(matches.items())
                        ][:10],
                    }
                )
        if process_only:
            return False, diagnostic(
                "design_function_ck_describes_verification_process",
                "One or more ordinary CK sections describe verification machinery instead of observable DUT behavior.",
                "Move API/test/fixture/coverage/report process requirements to the design plan, map their Spec lines with a reasoned IGNORE, and keep only CKs with public DUT observations, then call Check.",
                artifact=self.doc_file,
                location=self.doc_file,
                observed={
                    "checkpoints": process_only[:20],
                    "truncated": len(process_only) > 20,
                },
                expected=(
                    "Every ordinary CK describes a predicate over public DUT pins, "
                    "transactions, or backend-neutral events; FG-PPA remains separate."
                ),
            )
        if not identifiers:
            return False, diagnostic(
                "design_label_identifier_missing",
                "The functional contract contains no FG/FC/CK machine tags.",
                "Create the complete FG -> FC -> CK hierarchy using Guide_Doc/design_ut_contract.md, then call Check.",
                artifact=self.doc_file,
                location=self.doc_file,
                observed={"machine_tag_count": 0},
                expected="At least one unique FG/FC/CK hierarchy.",
            )
        return True, {
            "message": "Design functional-contract identifiers are portable and unique.",
            "identifier_count": len(identifiers),
        }
