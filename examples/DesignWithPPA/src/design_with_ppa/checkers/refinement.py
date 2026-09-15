"""CK/test refinement batch gates and declared-batch helpers."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
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

from .common import (
    _actionable_checker_failure,
    _is_batch_progress,
)




class DesignTestTemplateBatchChecker(UnityChipCheckerTestTemplate):
    """Validate all discovered templates while retaining batch-oriented guidance."""

    def do_check(self, timeout=0, is_complete=False, **kwargs):
        """Treat CurrentTips as priority and absorb valid templates made early."""

        original_gen = list(self.batch_task.gen_task_list)
        original_tbd = list(self.batch_task.tbd_task_list)
        source = list(self.batch_task.source_task_list)
        if source:
            associated: set[str] = set()
            source_set = set(source)
            for test_file in self._stage_test_files():
                path = Path(test_file)
                if not path.is_absolute():
                    path = Path(self.workspace) / path
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except (OSError, UnicodeError, SyntaxError):
                    continue
                for call in (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "mark_function"
                ):
                    if len(call.args) < 3:
                        continue
                    try:
                        fc_name = ast.literal_eval(call.args[0])
                        ck_value = ast.literal_eval(call.args[2])
                    except (ValueError, TypeError, SyntaxError, MemoryError):
                        continue
                    ck_names = ck_value if isinstance(ck_value, (list, tuple)) else [ck_value]
                    fg_name = None
                    for node in ast.walk(call.func.value):
                        if not isinstance(node, ast.Subscript):
                            continue
                        try:
                            candidate = ast.literal_eval(node.slice)
                        except (ValueError, TypeError, SyntaxError, MemoryError):
                            continue
                        if isinstance(candidate, str) and candidate.startswith("FG-"):
                            fg_name = candidate
                            break
                    if not isinstance(fg_name, str) or not isinstance(fc_name, str):
                        continue
                    for ck_name in ck_names:
                        checkpoint = f"{fg_name}/{fc_name}/{ck_name}"
                        if isinstance(ck_name, str) and checkpoint in source_set:
                            associated.add(checkpoint)
            # The inherited checker executes the complete template collection.
            # Make every statically associated canonical CK provisionally
            # visible so that same run can validate it before it is counted.
            self.batch_task.gen_task_list = list(dict.fromkeys(
                original_gen + [task for task in source if task in associated]
            ))
        result = super().do_check(
            timeout=timeout,
            is_complete=is_complete,
            **kwargs,
        )
        if not result[0]:
            self.batch_task.gen_task_list = original_gen
            self.batch_task.tbd_task_list = original_tbd
            if not _is_batch_progress(result[1]):
                return False, _actionable_checker_failure(
                    result[1],
                    error_code="design_test_template_invalid",
                    error="The shared test-template collection does not satisfy the current CK batch.",
                    next_action=(
                        "Use observed.current_batch and the first reported pytest node. "
                        "Create or repair that exact test template, keep env as its first "
                        "fixture, associate its canonical CK with mark_function, and leave "
                        "the exact assert False, \"Not implemented\" placeholder as the final "
                        "statement; then call Check again."
                    ),
                    artifact=self.test_dir,
                    expected=(
                        "Each current CK has at least one discoverable shared test template "
                        "that reaches only the required Not implemented assertion."
                    ),
                    current_batch=list(self.batch_task.tbd_task_list),
                )
        return result




def _expand_declared_batch(batch_task: Any, payload: Any) -> None:
    """Temporarily include canonical payload keys so a Checker can validate them."""

    if not isinstance(payload, dict):
        return
    requested = {
        str(key).strip()
        for key in payload
        if key is not None and str(key).strip()
    }
    current = set(batch_task.tbd_task_list)
    for task in batch_task.source_task_list:
        if task in requested and task not in current:
            batch_task.tbd_task_list.append(task)
            current.add(task)




def _normalize_declared_batch(batch_task: Any) -> None:
    """Restore the next batch from source-derived completion after one Check."""

    if batch_task.checkpoint_error is not None:
        return
    batch_task.tbd_task_list = []
    batch_task.cmp_task_list = []
    batch_task.update_current_tbd()
    batch_task.savepoint_file()




class DesignLabelStructureRefineChecker(UnityChipCheckerLabelStructureRefine):
    """Accept valid CK review records beyond the currently suggested batch."""

    accepted_stage_args = ("refined",)


    def do_check(self, timeout=0, is_complete=False, refined=None, **kwargs):
        """Validate submitted canonical CKs together, then rebuild remaining work."""

        _expand_declared_batch(self.batch_task, refined)
        try:
            passed, result = super().do_check(
                timeout=timeout,
                is_complete=is_complete,
                refined=refined,
                **kwargs,
            )
            if passed or _is_batch_progress(result):
                return passed, result
            return False, _actionable_checker_failure(
                result,
                error_code="design_label_refinement_invalid",
                error="The submitted functional-contract refinement is incomplete or invalid.",
                next_action=(
                    "Use observed.current_batch and repair each submitted CK in "
                    f"{self.doc_file}: keep the canonical FG/FC/CK path, make its trigger "
                    "and public observation independently testable, and submit one decision "
                    "for every listed CK; then call Check again."
                ),
                artifact=self.doc_file,
                expected=(
                    "Every submitted canonical CK has one valid refinement decision and "
                    "the document remains a parseable unique FG/FC/CK hierarchy."
                ),
                current_batch=list(self.batch_task.tbd_task_list),
            )
        finally:
            _normalize_declared_batch(self.batch_task)




class DesignRefineTestCasesChecker(UnityChipCheckerRefineTestCases):
    """Accept valid test-review records beyond the currently suggested CK batch."""

    accepted_stage_args = ("refined",)


    def do_check(self, timeout=0, is_complete=False, refined=None, **kwargs):
        """Validate submitted canonical CKs together, then rebuild remaining work."""

        _expand_declared_batch(self.batch_task, refined)
        try:
            passed, result = super().do_check(
                timeout=timeout,
                is_complete=is_complete,
                refined=refined,
                **kwargs,
            )
            if passed or _is_batch_progress(result):
                return passed, result
            return False, _actionable_checker_failure(
                result,
                error_code="design_test_refinement_invalid",
                error="The submitted shared-test review is incomplete or inconsistent with its CKs.",
                next_action=(
                    "Use observed.current_batch and the listed related tests. For every "
                    "submitted CK, verify directed, boundary, reset, invalid, sequence, and "
                    "combination coverage as applicable; add or correct the missing shared "
                    "test and mark_function association, then call Check again."
                ),
                artifact=self.test_dir,
                expected=(
                    "Each submitted CK has one valid review record backed by discoverable "
                    "shared tests and canonical mark_function associations."
                ),
                current_batch=list(self.batch_task.tbd_task_list),
            )
        finally:
            _normalize_declared_batch(self.batch_task)
