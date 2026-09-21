"""Spec line-map batch and reference gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from ucagent.checkers.base import Checker
from ucagent.checkers.file_linemap import (
    UnityChipBatchCheckerFileLineMap,
    _line_block_base,
    line_map_check_one_file,
)
import ucagent.util.functions as uc_functions
from ..contracts import (
    resolve_workspace_path,
)

from .common import (
    _actionable_checker_failure,
    _exception_contract_diagnostic,
    _is_batch_progress,
)




class DesignLineMapReferenceChecker(Checker):
    """Revalidate every Spec line-map reference after FG/FC/CK refinement."""

    def __init__(
        self,
        file_list: str | list[str],
        func_check_file: str,
        map_location: str,
        map_suffix: str = "_line_func_map.txt",
        max_block_lines: int = 100,
        **kwargs: Any,
    ) -> None:
        """Store source globs and strict line-map limits without scanning files."""

        super().__init__()
        del kwargs
        self.file_list = [file_list] if isinstance(file_list, str) else list(file_list)
        if not self.file_list or any(
            not isinstance(value, str) or not value for value in self.file_list
        ):
            raise ValueError("file_list must contain non-empty workspace-relative globs")
        if isinstance(max_block_lines, bool) or not isinstance(max_block_lines, int) or max_block_lines < 1:
            raise ValueError("max_block_lines must be a positive integer")
        self.func_check_file = func_check_file
        self.map_location = map_location
        self.map_suffix = map_suffix
        self.max_block_lines = max_block_lines

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require all current mapping entries to reference the refined CK set exactly."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            ck_list = uc_functions.get_unity_chip_doc_marks(
                str(
                    resolve_workspace_path(
                        workspace, self.func_check_file, must_exist=True
                    )
                ),
                "CK",
                1,
            )
            if not ck_list:
                raise ValueError("the refined function contract contains no CK paths")
            source_files: list[Path] = []
            for pattern in self.file_list:
                pattern_path = Path(pattern)
                if pattern_path.is_absolute() or ".." in pattern_path.parts:
                    raise ValueError("Spec source globs must remain workspace-relative")
                source_files.extend(
                    path.resolve()
                    for path in workspace.glob(pattern)
                    if path.is_file() and not path.is_symlink()
                )
            source_files = sorted(set(source_files))
            if not source_files:
                raise ValueError(f"no Spec files matched {self.file_list}")
            for source in source_files:
                source_relative = source.relative_to(workspace).as_posix()
                map_name = source_relative.replace("/", "_").replace(".", "_")
                map_relative = (
                    Path(self.map_location) / f"{map_name}{self.map_suffix}"
                ).as_posix()
                passed, result = line_map_check_one_file(
                    str(workspace),
                    source_relative,
                    map_relative,
                    ck_list,
                    self.func_check_file,
                    self.map_suffix,
                    self.map_location,
                    20,
                    True,
                    max_block_lines=self.max_block_lines,
                    strict_line_bounds=True,
                    ignore_blank_lines=True,
                    require_ignore_reason=True,
                    include_line_detail_header=False,
                    compact_unmapped_blocks=True,
                )
                if not passed:
                    inherited = (
                        result["diagnostic"]
                        if isinstance(result, dict)
                        and isinstance(result.get("diagnostic"), dict)
                        else result
                    )
                    return False, _actionable_checker_failure(
                        inherited,
                        error_code="design_line_map_refinement_invalid",
                        error="A Spec line map does not resolve against the refined functional contract.",
                        next_action=(
                            f"Open {map_relative} and repair the first reported source range. "
                            "Map every nonblank physical line to a current canonical FG/FC/CK "
                            "path or a reasoned IGNORE, then call Check again."
                        ),
                        artifact=map_relative,
                        location=map_relative,
                        expected="Every mapped FG/FC/CK path exists in the refined functional contract.",
                    )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_line_map_refinement_invalid",
                error="At least one Spec line map does not resolve against the refined functional contract.",
                exc=exc,
                artifact=self.map_location,
                guide="Guide_Doc/design_ut_contract.md",
                expected=(
                    "Every nonblank Spec line maps to a current FG/FC/CK path or one "
                    "reasoned IGNORE entry in its canonical line-map file."
                ),
            )
        return True, {
            "message": "All Spec line maps reference the refined functional contract.",
            "source_file_count": len(source_files),
            "checkpoint_count": len(ck_list),
        }




class DesignSpecLineMapBatchChecker(UnityChipBatchCheckerFileLineMap):
    """Count every currently valid Spec line block, including later batches."""

    def do_check(self, timeout: int = 0, is_complete: bool = False, **kwargs: Any):
        """Validate the current line-map batch and normalize inherited failures."""

        passed, result = super().do_check(
            timeout=timeout,
            is_complete=is_complete,
            **kwargs,
        )
        if passed or _is_batch_progress(result):
            return passed, result
        current_batch = [
            _line_block_base(task) for task in self.batch_task.tbd_task_list
        ]
        return False, _actionable_checker_failure(
            result,
            error_code="design_spec_line_map_invalid",
            error="The current Spec line-map batch is missing or invalid.",
            next_action=(
                "Use observed.current_batch and the first reported source range. Open "
                "its canonical map_file, map every nonblank physical line to an existing "
                "FG/FC/CK path or a reasoned IGNORE, keep each block at no more than 100 "
                "lines, remove noncanonical range-suffixed map files, then call Check again."
            ),
            artifact=self.map_location,
            expected=(
                "Every current Spec line block has one canonical mapping file whose "
                "references resolve to the current functional contract."
            ),
            current_batch=current_batch,
        )

    def _refresh_batch_state(self, ck_list=None):
        """Rebuild progress from canonical mappings instead of checkpoint order."""

        self._task_errors = []
        self._completed_validation_errors = []
        source_tasks = self._get_all_line_blocks()
        current_by_base = {
            _line_block_base(task): task for task in source_tasks
        }
        previous_by_base: dict[str, str] = {}
        for task in self.batch_task.gen_task_list:
            task_base = _line_block_base(task)
            if task_base in previous_by_base:
                self._task_errors.append(
                    f"Recorded progress contains duplicate completed line block '{task_base}'."
                )
                continue
            previous_by_base[task_base] = task
        for task_base in sorted(set(previous_by_base) - set(current_by_base)):
            self._task_errors.append(
                f"Recorded completed line block '{task_base}' does not match a current target."
            )

        completed_tasks = []
        for task in source_tasks:
            if ck_list is None:
                continue
            valid, message = self._validate_line_block(task, ck_list)
            if valid:
                completed_tasks.append(task)
                continue
            if _line_block_base(task) in previous_by_base:
                self._completed_validation_errors.append({
                    "line_block": _line_block_base(task),
                    "details": message,
                })

        self._unexpected_mapping_files = self._find_unexpected_mapping_files()
        if self._unexpected_mapping_files:
            replacements = ", ".join(
                f"{item['file']} -> {item['expected_map_file']}"
                for item in self._unexpected_mapping_files
            )
            self._task_errors.append(
                "Found mapping files with line-range suffixes that are not read by "
                f"this stage: {replacements}. Merge their valid mappings into the "
                "listed canonical files and remove the unexpected files."
            )
        self._sync_batch_state(source_tasks, completed_tasks)
