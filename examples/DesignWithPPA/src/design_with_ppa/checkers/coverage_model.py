"""Functional coverage skeleton and checkpoint-batch gates."""

from __future__ import annotations

import ast
import copy
import os
from pathlib import Path
import re
import shutil
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
import ucagent.util.functions as uc_functions
from ..contracts import (
    diagnostic,
    load_fenced_yaml,
    resolve_workspace_path,
)

from .common import (
    _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES,
    _checkpoint_prefixes,
    _exception_contract_diagnostic,
    _functional_checkpoints,
)
from .test_quality import (
    _environment_contract_violations,
)




def _coverage_predicate_inventory(
    source: Path,
    public_attributes: set[str] | None = None,
) -> dict[str, str]:
    """Classify canonical CK predicates without importing generated Python.

    The canonical coverage source is deliberately static: one literal list of
    named ``CovGroup`` objects, literal FC/CK identifiers, and predicates over
    the factory's public ``env`` argument. This lets stage gates validate
    untrusted workspace code without loading it into the UCAgent process.
    """

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    violations = _environment_contract_violations(source, tree)
    if violations:
        raise ValueError(
            "coverage predicates must not access private DUT/transaction state, "
            "call private event helpers, or assign normalized event evidence: "
            f"{violations}"
        )
    factories = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "get_coverage_groups"
    ]
    if len(factories) != 1:
        raise ValueError("coverage source must define exactly one get_coverage_groups")
    factory = factories[0]
    positional = [*factory.args.posonlyargs, *factory.args.args]
    if (
        len(positional) != 1
        or positional[0].arg != "env"
        or factory.args.vararg is not None
        or factory.args.kwarg is not None
    ):
        raise ValueError("get_coverage_groups must have exactly one argument named env")
    function_defs = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    lambda_defs: dict[str, ast.Lambda] = {}
    group_names: dict[str, str] = {}
    bin_mappings: dict[str, ast.Dict] = {}
    for statement in [*tree.body, *factory.body]:
        target = None
        value = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target = statement.targets[0].id
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            target = statement.target.id
            value = statement.value
        if target is None or value is None:
            continue
        if isinstance(value, ast.Lambda):
            lambda_defs[target] = value
        if isinstance(value, ast.Dict):
            bin_mappings[target] = value
        if not isinstance(value, ast.Call) or not value.args:
            continue
        called_name = None
        if isinstance(value.func, ast.Name):
            called_name = value.func.id
        elif isinstance(value.func, ast.Attribute):
            called_name = value.func.attr
        if (
            called_name == "CovGroup"
            and isinstance(value.args[0], ast.Constant)
            and isinstance(value.args[0].value, str)
        ):
            group_names[target] = value.args[0].value

    returns = [node for node in factory.body if isinstance(node, ast.Return)]
    if len(returns) != 1 or not isinstance(returns[0].value, (ast.List, ast.Tuple)):
        raise ValueError("get_coverage_groups must return one literal list of named groups")
    returned_group_vars = [
        element.id
        for element in returns[0].value.elts
        if isinstance(element, ast.Name)
    ]
    if (
        len(returned_group_vars) != len(returns[0].value.elts)
        or len(returned_group_vars) != len(set(returned_group_vars))
        or set(returned_group_vars) != set(group_names)
    ):
        raise ValueError("get_coverage_groups must return every declared CovGroup exactly once")

    missing = object()

    def constant_callable(node: ast.AST) -> object:
        """Return a literal callable result or ``missing`` when state-dependent."""

        if isinstance(node, ast.Name) and node.id in lambda_defs:
            node = lambda_defs[node.id]
        if isinstance(node, ast.Lambda):
            if isinstance(node.body, ast.Constant):
                return node.body.value
            return missing
        if not isinstance(node, ast.Name) or node.id not in function_defs:
            return missing
        statements = function_defs[node.id].body
        if (
            statements
            and isinstance(statements[0], ast.Expr)
            and isinstance(statements[0].value, ast.Constant)
            and isinstance(statements[0].value.value, str)
        ):
            statements = statements[1:]
        if (
            len(statements) == 1
            and isinstance(statements[0], ast.Return)
            and isinstance(statements[0].value, ast.Constant)
        ):
            return statements[0].value.value
        return missing

    inventory: dict[str, str] = {}
    implemented_signatures: dict[str, list[str]] = {}
    for call in [node for node in ast.walk(factory) if isinstance(node, ast.Call)]:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "add_watch_point":
            continue
        if not isinstance(call.func.value, ast.Name):
            raise ValueError("add_watch_point receiver must be a named CovGroup")
        group_name = group_names.get(call.func.value.id)
        if group_name is None:
            raise ValueError("add_watch_point receiver has no literal CovGroup name")
        target_node = call.args[0] if call.args else None
        bins_node = call.args[1] if len(call.args) > 1 else None
        point_node = call.args[2] if len(call.args) > 2 else None
        for keyword in call.keywords:
            if keyword.arg in {"dut", "target"}:
                target_node = keyword.value
            elif keyword.arg == "bins":
                bins_node = keyword.value
            elif keyword.arg == "name":
                point_node = keyword.value
        if not isinstance(target_node, ast.Name) or target_node.id != "env":
            raise ValueError("every coverage watch point must target the public env argument")
        if isinstance(bins_node, ast.Name):
            bins_node = bin_mappings.get(bins_node.id)
        if not isinstance(bins_node, ast.Dict):
            raise ValueError("add_watch_point bins must be a literal or named dict")
        if not (
            isinstance(point_node, ast.Constant)
            and isinstance(point_node.value, str)
            and point_node.value.startswith("FC-")
        ):
            raise ValueError("add_watch_point name must be a literal FC identifier")
        for key_node, predicate_node in zip(bins_node.keys, bins_node.values):
            if not (
                isinstance(key_node, ast.Constant)
                and isinstance(key_node.value, str)
                and key_node.value.startswith("CK-")
            ):
                raise ValueError("coverage bin names must be literal CK identifiers")
            checkpoint = f"{group_name}/{point_node.value}/{key_node.value}"
            if checkpoint in inventory:
                raise ValueError(f"duplicate coverage checkpoint: {checkpoint}")
            constant = constant_callable(predicate_node)
            state = (
                "placeholder"
                if constant is False
                else "constant"
                if constant is not missing
                else "implemented"
            )
            inventory[checkpoint] = state
            if state != "implemented":
                continue

            resolved_predicate = predicate_node
            if isinstance(resolved_predicate, ast.Name):
                if resolved_predicate.id in lambda_defs:
                    resolved_predicate = lambda_defs[resolved_predicate.id]
                elif resolved_predicate.id in function_defs:
                    resolved_predicate = function_defs[resolved_predicate.id]
            if not isinstance(
                resolved_predicate,
                (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                raise ValueError(
                    f"coverage predicate for {checkpoint} must be a lambda or named function"
                )
            predicate_args = (
                [
                    *resolved_predicate.args.posonlyargs,
                    *resolved_predicate.args.args,
                ]
                if hasattr(resolved_predicate, "args")
                else []
            )
            if (
                len(predicate_args) != 1
                or resolved_predicate.args.vararg is not None
                or resolved_predicate.args.kwarg is not None
            ):
                raise ValueError(
                    f"coverage predicate for {checkpoint} must accept exactly one env value"
                )
            predicate_arg = predicate_args[0].arg
            predicate_body: ast.AST
            if isinstance(resolved_predicate, ast.Lambda):
                predicate_body = resolved_predicate.body
            else:
                statements = list(resolved_predicate.body)
                if (
                    statements
                    and isinstance(statements[0], ast.Expr)
                    and isinstance(statements[0].value, ast.Constant)
                    and isinstance(statements[0].value.value, str)
                ):
                    statements = statements[1:]
                predicate_body = ast.Module(body=statements, type_ignores=[])

            private_attributes = sorted({
                node.attr
                for node in ast.walk(predicate_body)
                if isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
            })
            if private_attributes:
                raise ValueError(
                    f"coverage predicate for {checkpoint} reads private attributes: "
                    f"{private_attributes[:10]}"
                )
            direct_attributes = {
                node.attr
                for node in ast.walk(predicate_body)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == predicate_arg
            }
            if public_attributes is not None:
                unknown_attributes = sorted(direct_attributes - public_attributes)
                if unknown_attributes:
                    raise ValueError(
                        f"coverage predicate for {checkpoint} reads undeclared public "
                        f"environment attributes: {unknown_attributes[:10]}"
                    )
            event_names = {
                node.value
                for node in ast.walk(predicate_body)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            reads_event_data = any(
                isinstance(node, ast.Attribute)
                and node.attr == "last_event_data"
                for node in ast.walk(predicate_body)
            )
            if event_names & {"transaction_accepted", "response_observed"} and not reads_event_data:
                raise ValueError(
                    f"coverage predicate for {checkpoint} must refine transaction events "
                    "with public last_event_data"
                )

            normalized = copy.deepcopy(predicate_body)

            class NormalizePredicateArgument(ast.NodeTransformer):
                """Replace the local predicate argument for stable comparison."""

                def visit_Name(self, node: ast.Name) -> ast.AST:
                    """Canonicalize references to the predicate environment."""

                    if node.id == predicate_arg:
                        return ast.copy_location(ast.Name(id="__env__", ctx=node.ctx), node)
                    return node

            normalized = NormalizePredicateArgument().visit(normalized)
            signature = ast.dump(normalized, include_attributes=False)
            implemented_signatures.setdefault(signature, []).append(checkpoint)
    if not inventory:
        raise ValueError("coverage source contains no CK predicate mappings")
    duplicate_predicates = [
        checkpoints
        for checkpoints in implemented_signatures.values()
        if len(checkpoints) > 1
    ]
    if duplicate_predicates:
        raise ValueError(
            "implemented coverage predicates must be CK-specific; duplicate predicates: "
            f"{duplicate_predicates[:10]}. Merge CKs that describe the same observable "
            "behavior, or record meaningful input/result event fields for genuinely "
            "different behavior; do not add tautologies or arbitrary transaction-ID "
            "arithmetic to make predicates syntactically different"
        )
    return inventory




def _coverage_public_attributes(
    workspace: Path,
    architecture_file: str,
    adapter_file: str,
) -> set[str]:
    """Derive the public coverage surface from architecture pins and adapter state."""

    architecture = load_fenced_yaml(
        resolve_workspace_path(workspace, architecture_file, must_exist=True),
        "architecture",
    )
    attributes = {
        row.get("name")
        for row in architecture.get("ports", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    adapter_path = resolve_workspace_path(workspace, adapter_file, must_exist=True)
    adapter_tree = ast.parse(
        adapter_path.read_text(encoding="utf-8"), filename=str(adapter_path)
    )
    adapter_classes = [
        node
        for node in adapter_tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Adapter")
    ]
    if len(adapter_classes) != 1:
        raise ValueError("adapter must define exactly one public environment class")
    adapter_class = adapter_classes[0]
    attributes.update(
        node.name
        for node in adapter_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in node.decorator_list
        )
    )
    attributes.update(
        target.attr
        for node in ast.walk(adapter_class)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and not target.attr.startswith("_")
    )
    # Backend selection and reporting infrastructure are public for fixtures,
    # but cannot prove backend-neutral functional behavior.
    attributes.difference_update(
        {"backend", "coverage_groups", "fc_cover", "waveform_path"}
    )
    return attributes




def _cleanup_transient_coverage_data(test_dir: Path) -> None:
    """Remove only Toffee's generated per-run coverage directories."""

    data_dir = test_dir / "data"
    if data_dir.is_symlink() or not data_dir.is_dir():
        return
    resolved_data = data_dir.resolve()
    for candidate in data_dir.iterdir():
        if (
            not re.fullmatch(r"toffee_tmp_[0-9]{14}_[0-9]+", candidate.name)
            or candidate.is_symlink()
            or not candidate.is_dir()
            or candidate.resolve().parent != resolved_data
        ):
            continue
        shutil.rmtree(candidate)




def _coverage_artifact_state(
    workspace: Path,
    paths: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    """Describe coverage artifacts without exposing generated implementation paths."""

    state: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        try:
            relative = path.resolve().relative_to(workspace).as_posix()
        except (OSError, ValueError):
            relative = str(path)
        entry: dict[str, Any] = {
            "path": relative,
            "exists": path.exists(),
            "regular": path.is_file() and not path.is_symlink(),
        }
        if entry["regular"]:
            try:
                size_bytes = path.stat().st_size
                entry["size_bytes"] = size_bytes
                entry["non_empty"] = size_bytes > 0
            except OSError:
                entry["size_bytes"] = None
                entry["non_empty"] = None
        state[name] = entry
    return state




def _coverage_pipeline_status(blocked_at: str) -> list[dict[str, str]]:
    """Describe the public coverage lifecycle and its current blocking step."""

    steps = (
        (
            "synthesis",
            "Current selected-language source and top hierarchy pass synthesis.",
        ),
        (
            "instrumentation_setup",
            "get_coverage_groups(env), adapter.bind_coverage(groups), and RTL adapter.configure_test_artifacts(...) run before reset/Step.",
        ),
        (
            "shared_rtl_regression",
            "The same shared functional pytest nodes run through api_{DUT}_* and all pass on RTL.",
        ),
        (
            "fixture_teardown",
            "set_func_coverage(request, groups), adapter.finish(), then set_line_coverage(request, coverage_path, ignore=...) run in this order.",
        ),
        (
            "toffee_artifacts",
            "toffee_report.json, line_dat/code_coverage.json, and line_dat/merged.info are non-empty results from the current run.",
        ),
        (
            "authored_source_mapping",
            "Coverage source records and line counts match the current authored RTL manifest and exact ignore ranges.",
        ),
        (
            "coverage_threshold",
            "Reachable authored lines are exercised and the configured minimum is met after proven exact exclusions.",
        ),
    )
    names = [name for name, _requirement in steps]
    blocked_index = names.index(blocked_at) if blocked_at in names else 0
    return [
        {
            "step": name,
            "status": (
                "complete"
                if index < blocked_index
                else "blocked"
                if index == blocked_index
                else "not_run"
            ),
            "required": requirement,
        }
        for index, (name, requirement) in enumerate(steps)
    ]




def _coverage_fixture_lifecycle_violations(path: Path) -> list[str]:
    """Check the env fixture's coverage registration order without importing it."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    env_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "env"
    ]
    if not env_functions:
        return [
            "conftest.py does not define the required env fixture; coverage cannot be bound to the shared test environment"
        ]
    calls: list[tuple[str, int]] = []
    for node in ast.walk(env_functions[0]):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else ""
        )
        if name in {
            "bind_coverage",
            "configure_test_artifacts",
            "set_func_coverage",
            "set_line_coverage",
            "finish",
            "Finish",
            "reset",
            "Reset",
            "step",
            "Step",
        }:
            calls.append((name, node.lineno))
    bind_calls = [line for name, line in calls if name == "bind_coverage"]
    artifact_calls = [line for name, line in calls if name == "configure_test_artifacts"]
    line_calls = [line for name, line in calls if name == "set_line_coverage"]
    func_calls = [line for name, line in calls if name == "set_func_coverage"]
    finish_calls = [line for name, line in calls if name in {"finish", "Finish"}]
    reset_step_calls = [
        line
        for name, line in calls
        if name in {"reset", "Reset", "step", "Step"}
    ]
    violations: list[str] = []
    if not bind_calls:
        violations.append(
            "env fixture does not bind functional coverage with adapter.bind_coverage()"
        )
    if reset_step_calls and bind_calls and min(bind_calls) > min(reset_step_calls):
        violations.append(
            "adapter.bind_coverage() must run before the first reset/Step so execution is instrumented"
        )
    if line_calls and not artifact_calls:
        violations.append(
            "env fixture does not configure per-test coverage/waveform artifact paths"
        )
    if reset_step_calls and artifact_calls and min(artifact_calls) > min(reset_step_calls):
        violations.append(
            "configure_test_artifacts() must run before the first reset/Step"
        )
    if not line_calls:
        violations.append("env fixture does not call set_line_coverage()")
    if not func_calls:
        violations.append("env fixture does not call set_func_coverage()")
    if not finish_calls:
        violations.append("env fixture does not finalize the adapter with finish()")
    if finish_calls and line_calls and min(line_calls) <= max(finish_calls):
        violations.append(
            "set_line_coverage() must run after adapter.finish() so the native .dat file is finalized"
        )
    if finish_calls and func_calls and min(func_calls) >= max(finish_calls):
        violations.append(
            "set_func_coverage() must run before adapter.finish() because finish clears coverage groups"
        )
    return violations




class _DesignCoverageEnvironmentMixin:
    """Validate coverage factories statically against the public ``env`` API."""

    def basic_check(self):
        """Parse canonical coverage without importing workspace-authored code."""

        def error_message(message):
            """Return one complete bounded diagnostic for inherited checkers."""

            return diagnostic(
                "design_coverage_source_invalid",
                "The functional coverage source cannot be validated statically.",
                (
                    f"Open {self.cov_file} and fix the exact missing file, syntax, "
                    "get_coverage_groups(env), or public-observation problem in "
                    "observed.reason using Guide_Doc/design_ut_contract.md; then call "
                    "Check again."
                ),
                artifact=self.cov_file,
                location=self.cov_file,
                observed={"reason": message},
                expected="One statically valid get_coverage_groups(env) definition using public environment evidence.",
            )

        target_file = self.get_path(self.cov_file)
        if not os.path.exists(target_file):
            return False, error_message(
                f"Functional coverage file '{self.cov_file}' not found in workspace."
            )
        try:
            inventory = _coverage_predicate_inventory(Path(target_file))
        except (OSError, SyntaxError, ValueError) as exc:
            return False, error_message(
                f"Unable to parse functional coverage file '{self.cov_file}': {exc}"
            )
        groups: dict[str, dict[str, Any]] = {}
        points: dict[tuple[str, str], dict[str, Any]] = {}
        for checkpoint in inventory:
            functional_group, functional_coverage, check = checkpoint.split("/", 2)
            group = groups.setdefault(
                functional_group,
                {"name": functional_group, "points": []},
            )
            point = points.get((functional_group, functional_coverage))
            if point is None:
                point = {"name": functional_coverage, "bins": []}
                points[(functional_group, functional_coverage)] = point
                group["points"].append(point)
            point["bins"].append({"name": check})
        return True, list(groups.values())




class DesignCoverageStructureChecker(
    _DesignCoverageEnvironmentMixin, UnityChipCheckerCoverageGroup
):
    """Require the functional CK skeleton while leaving PPA CKs to later gates."""

    def __init__(
        self,
        *args: Any,
        ignore_ck_prefix: str | list[str] | None = None,
        architecture_file: str | None = None,
        adapter_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the explicit boundary between functional and performance CKs."""

        super().__init__(*args, **kwargs)
        self.ignore_ck_prefix = _checkpoint_prefixes(
            _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES
            if ignore_ck_prefix is None
            else ignore_ck_prefix
        )
        if (architecture_file is None) != (adapter_file is None):
            raise ValueError("architecture_file and adapter_file must be configured together")
        self.architecture_file = architecture_file
        self.adapter_file = adapter_file

    def do_check(self, timeout=0, **kwargs):
        """Validate coverage structure while rejecting implemented CKs at this stage."""

        del timeout, kwargs
        try:
            source = resolve_workspace_path(
                Path(self.workspace), self.cov_file, must_exist=True
            )
            public_attributes = (
                _coverage_public_attributes(
                    Path(self.workspace), self.architecture_file, self.adapter_file
                )
                if self.architecture_file is not None and self.adapter_file is not None
                else None
            )
            inventory = _coverage_predicate_inventory(source, public_attributes)
            all_documented = uc_functions.get_unity_chip_doc_marks(
                self.get_path(self.doc_file), "CK", 1
            )
            documented = _functional_checkpoints(
                all_documented, self.ignore_ck_prefix
            )
            if not documented:
                raise ValueError("the design contract contains no functional CK paths")
        except (OSError, SyntaxError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_coverage_structure_invalid",
                error="The functional coverage skeleton cannot be validated.",
                exc=exc,
                artifact=self.cov_file,
                guide="Guide_Doc/design_ut_contract.md",
                expected=(
                    "One get_coverage_groups(env) definition containing exactly every "
                    "functional CK with the false-predicate placeholder."
                ),
            )
        missing = sorted(set(documented) - set(inventory))
        extra = sorted(set(inventory) - set(documented))
        if missing or extra:
            return False, diagnostic(
                "design_coverage_checkpoint_set_mismatch",
                "The coverage skeleton and functions-and-checks document disagree.",
                "Declare every documented CK exactly once under its canonical FG/FC, then call Check.",
                artifact=self.cov_file,
                location=self.cov_file,
                observed={"missing": missing[:20], "extra": extra[:20]},
                expected="The coverage skeleton contains exactly the documented CK paths.",
            )
        non_placeholders = sorted(
            checkpoint
            for checkpoint, state in inventory.items()
            if state != "placeholder"
        )
        if non_placeholders:
            return False, diagnostic(
                "design_coverage_predicate_implemented_early",
                "CK predicates were implemented before the checkpoint batch stage.",
                "Use `lambda _env: False` for every CK predicate in this structure stage, then call Check.",
                artifact=self.cov_file,
                location=self.cov_file,
                observed={"checkpoint_count": len(non_placeholders), "checkpoints": non_placeholders[:20]},
                expected="Every declared CK uses the exact false-predicate placeholder.",
            )
        return True, {
            "message": "Functional coverage FG/FC/CK structure and placeholders are complete.",
            "checkpoint_count": len(documented),
            "performance_checkpoints_excluded": len(all_documented) - len(documented),
        }




class DesignCoverageGroupBatchChecker(
    _DesignCoverageEnvironmentMixin, UnityChipCheckerCoverageGroupBatchImplementation
):
    """Advance CK batches from static predicate implementation evidence."""

    def __init__(
        self,
        *args: Any,
        ignore_ck_prefix: str | list[str] | None = None,
        architecture_file: str | None = None,
        adapter_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the functional CK scope before creating batch state."""

        super().__init__(*args, **kwargs)
        self.ignore_ck_prefix = _checkpoint_prefixes(
            _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES
            if ignore_ck_prefix is None
            else ignore_ck_prefix
        )
        if (architecture_file is None) != (adapter_file is None):
            raise ValueError("architecture_file and adapter_file must be configured together")
        self.architecture_file = architecture_file
        self.adapter_file = adapter_file

    def on_init(self):
        """Initialize batch state from only the current functional CK source set."""

        source_tasks = self.smanager_get_value(self.data_key, [])
        if not isinstance(source_tasks, list):
            source_tasks = []
        source_tasks = _functional_checkpoints(
            source_tasks, self.ignore_ck_prefix
        )
        note: list[str] = []
        self.batch_task.sync_source_task(
            source_tasks,
            note,
            f"Functional CK source list in data key '{self.data_key}' changed.",
        )
        self.batch_task.update_current_tbd()
        try:
            _, blocks = uc_functions.get_unity_chip_doc_marks(
                self.get_path(self.doc_file),
                "CK",
                0,
                return_line_block=True,
            )
            self.cached_ck_file_blocks = {
                checkpoint: blocks[checkpoint]
                for checkpoint in source_tasks
                if checkpoint in blocks
            }
        except (AssertionError, OSError, TypeError, ValueError):
            self.cached_ck_file_blocks = None
        return Checker.on_init(self)

    def do_check(self, timeout=0, is_complete=False, **kwargs):
        """Validate every predicate and count correct implementations from any batch."""

        basic_pass, groups_or_message = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_message
        try:
            source = resolve_workspace_path(
                Path(self.workspace), self.cov_file, must_exist=True
            )
            public_attributes = (
                _coverage_public_attributes(
                    Path(self.workspace), self.architecture_file, self.adapter_file
                )
                if self.architecture_file is not None and self.adapter_file is not None
                else None
            )
            inventory = _coverage_predicate_inventory(source, public_attributes)
            all_documented, all_blocks = (
                uc_functions.get_unity_chip_doc_marks(
                    self.get_path(self.doc_file),
                    "CK",
                    1,
                    return_line_block=True,
                )
            )
            documented = _functional_checkpoints(
                all_documented, self.ignore_ck_prefix
            )
            self.cached_ck_file_blocks = {
                checkpoint: all_blocks[checkpoint]
                for checkpoint in documented
                if checkpoint in all_blocks
            }
            if not documented:
                raise ValueError("the design contract contains no functional CK paths")
        except (OSError, SyntaxError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_coverage_predicate_invalid",
                error="The functional coverage predicates cannot be validated.",
                exc=exc,
                artifact=self.cov_file,
                guide="Guide_Doc/design_ut_contract.md",
                expected=(
                    "Every canonical functional CK has one predicate derived only from "
                    "public env pins, cycle state, last_event, or last_event_data."
                ),
            )
        missing = sorted(set(documented) - set(inventory))
        extra = sorted(set(inventory) - set(documented))
        if missing or extra:
            return False, diagnostic(
                "design_coverage_checkpoint_set_mismatch",
                "The coverage model and functions-and-checks document disagree.",
                "Restore every canonical CK mapping without changing FG/FC/CK identities, then call Check.",
                artifact=self.cov_file,
                location=self.cov_file,
                observed={"missing": missing[:20], "extra": extra[:20]},
                expected="The coverage model contains exactly the documented CK paths.",
            )
        constant_predicates = sorted(
            checkpoint
            for checkpoint, state in inventory.items()
            if state == "constant"
        )
        if constant_predicates:
            return False, diagnostic(
                "design_coverage_constant_predicate",
                "One or more CK predicates are unconditionally true.",
                "Replace each reported predicate with a condition derived from public observable state, then call Check.",
                artifact=self.cov_file,
                location=self.cov_file,
                observed={"checkpoint_count": len(constant_predicates), "checkpoints": constant_predicates[:20]},
                expected="Implemented CK predicates are not literal constant callables.",
            )

        note: list[str] = []
        self.batch_task.sync_source_task(
            documented,
            note,
            f"Documentation '{self.doc_file}' CK points changed.",
        )
        self.batch_task.update_current_tbd()
        implemented = [
            checkpoint
            for checkpoint in documented
            if inventory[checkpoint] == "implemented"
        ]
        self.batch_task.sync_gen_task(
            implemented,
            note,
            "Implemented CK predicates changed.",
        )
        result = self.batch_task.do_complete(
            note,
            is_complete,
            f"in file: {self.doc_file}",
            f"in file: {self.cov_file}",
            " The CurrentTips batch is the priority; valid predicates implemented in another batch are retained and counted.",
        )
        return result
