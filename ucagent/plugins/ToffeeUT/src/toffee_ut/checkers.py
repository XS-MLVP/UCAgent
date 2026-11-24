"""Stage acceptance using the same deterministic audit as the command-line tools."""

import ast
import json
from pathlib import Path

from ucagent.core.checkers.base import BatchTask, Checker

from .audit import audit_project, read_spec
from .layout import project_layout
from .implementation import collect_test_files, failure_only_tests
from .paths import digest, local_path
from .runner import current_run
from .stage_audit import RESTORED_PHASES


class ToffeeUTChecker(Checker):
    """Validate one phase of the independent UT project."""

    def __init__(self, phase, project="ut_project", dut=None, cfg=None):
        """Store phase inputs without touching files before workspace injection."""
        super().__init__()
        if phase not in {"inputs", "design", "plan", "environment", "tests", "triage", "final", *RESTORED_PHASES}:
            raise ValueError("Unknown ToffeeUT audit phase")
        self.phase, self.project, self.dut, self.cfg = phase, project, dut, cfg

    def do_check(self, is_complete=False, **kwargs):
        """Check actual artifacts and signed execution evidence for the current phase."""
        result = audit_project(self.workspace, self.dut, self.project, self.phase,
                               line_coverage_required=self.cfg.get_value("runtime_options.ut_line_coverage", True)
                               if self.cfg is not None else None)
        return result["ok"], result


class ToffeeUTBatchChecker(Checker):
    """Reconcile source-driven RTL, document, coverage or case batches with live artifacts."""

    def __init__(self, phase, project="ut_project", dut=None, batch_size=10, cfg=None):
        """Register a bounded batch without reading mutable workspace files in construction."""
        super().__init__()
        if phase not in {"static", "line_map", "coverage_checks", "case_batch", "mock_batch"}:
            raise ValueError(f"Unknown ToffeeUT batch phase: {phase}")
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100")
        self.phase, self.project, self.dut, self.cfg = phase, project, dut, cfg
        self.batch_size = batch_size
        self.batch_task = BatchTask(phase, self)

    def on_init(self):
        """Derive initial work from current source and discard checkpoint-only progress."""
        try:
            source, generated = self._current_items()
        except (OSError, ValueError, KeyError, TypeError, SyntaxError):
            source, generated = [], []
        self.batch_task.source_task_list = source
        self.batch_task.gen_task_list = generated
        self.batch_task.tbd_task_list = [item for item in self.batch_task.tbd_task_list
                                         if item in source and item not in generated]
        self.batch_task.cmp_task_list = []
        self.batch_task.update_current_tbd()
        return super().on_init()

    def _current_items(self):
        """Compute unique source identities and independently verified completed items."""
        layout = project_layout(self.workspace, self.dut, self.project)
        root = layout["root"]
        bench = root / "testbenches" / layout["testbench"]
        if self.phase in {"static", "line_map"}:
            inventory = json.loads((root / "results/input_inventory.json").read_text())
            field = "rtl" if self.phase == "static" else "documents"
            source = sorted(inventory[field])
            if self.phase == "line_map" and source and any(Path(name).suffix.lower() not in {".md", ".txt", ".rst"} for name in source):
                raise ValueError("Line mapping needs physical text lines; convert PDF sources to text and refresh the input inventory")
            location = (root / f"docs/reviews/{self.dut}-static-review.md" if self.phase == "static"
                        else root / f"docs/spec/verification/{self.dut}-line-map.md")
            try:
                document = read_spec(location, "static_review" if self.phase == "static" else "line_map", self.dut)
            except FileNotFoundError:
                return source, []
            generated = []
            checkpoints = set()
            if self.phase == "line_map":
                design = read_spec(root / layout["design_spec"], "design", self.dut)
                checkpoints = {row["id"] for row in design.get("checkpoints", [])}
            for row in document.get("sources", []):
                if not isinstance(row, dict) or row.get("path") not in inventory[field]:
                    continue
                name = row["path"]
                path = local_path(self.workspace, name)
                if digest(path) != inventory[field][name]:
                    raise ValueError(f"Input changed: {name}; call UTProject(action='inspect') to refresh the inventory before continuing")
                if row.get("sha256") != digest(path):
                    continue
                if self.phase == "static":
                    valid = isinstance(row.get("review"), str) and bool(row["review"].strip())
                else:
                    text = path.read_text().splitlines()
                    spans, valid = set(), isinstance(row.get("lines"), list)
                    for item in row.get("lines", []):
                        if not isinstance(item, dict) or type(item.get("start")) is not int or type(item.get("end")) is not int:
                            valid = False
                            break
                        first, last = item["start"], item["end"]
                        if not 1 <= first <= last <= len(text) or last - first >= 100 or set(range(first, last + 1)) & spans:
                            valid = False
                            break
                        if item.get("checkpoint") not in checkpoints and not (item.get("checkpoint") == "IGNORE" and isinstance(item.get("reason"), str) and item["reason"].strip()):
                            valid = False
                            break
                        spans.update(range(first, last + 1))
                    valid = valid and all(not value.strip() or index in spans for index, value in enumerate(text, 1))
                if valid:
                    generated.append(name)
            return source, sorted(set(generated))
        if self.phase == "coverage_checks":
            design = read_spec(root / layout["design_spec"], "design", self.dut)
            source = sorted({row["id"] for row in design.get("checkpoints", [])})
            files = [path for path in bench.rglob("*.py") if "tests" not in path.parts]
            covered = {node.value for path in files if "coverage" in path.parts or path.stem == "coverage"
                       for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            sample = any(isinstance(node, ast.Attribute) and node.attr == "sample"
                         for path in files for node in ast.walk(ast.parse(path.read_text())))
            return source, sorted(set(source) & covered) if sample else []
        if self.phase == "mock_batch":
            source = sorted(path.stem for path in bench.rglob("*.py") if "tests" not in path.parts and "mock" in path.stem)
            try:
                cases = current_run(self.workspace, self.project)["cases"]["cases"]
            except FileNotFoundError:
                return source, []
            return source, [name for name in source if any(name in node and case["status"] == "PASS"
                and case["selftest"] and "mockcheck" in case.get("roles", []) for node, case in cases.items())]
        specification = read_spec(root / layout["verification_spec"], "verification", self.dut)
        source = sorted(row["id"] for row in specification.get("scenarios", []) if row.get("status") == "active")
        try:
            cases = current_run(self.workspace, self.project)["cases"]["cases"]
        except FileNotFoundError:
            return source, []
        empty_tests = {(path.relative_to(root).as_posix(), name)
                       for path in collect_test_files(root, layout["tests"])
                       for name in failure_only_tests(path, project=root)}
        cases = {node: case for node, case in cases.items()
                 if (node.partition("::")[0], node.partition("::")[2].split("[", 1)[0]) not in empty_tests}
        return source, [name for name in source if any(name in case["scenarios"] and not case["selftest"]
            and case["native_duts"] and case["status"] in {"PASS", "FAIL", "UNCERTAIN"}
            for case in cases.values())]

    def do_check(self, is_complete=False, **kwargs):
        """Reconcile each batch with live files; enforce the full phase gate after all items."""
        try:
            source, generated = self._current_items()
            if not source and self.phase == "line_map":
                return False, {"error_code": "UT_LINE_MAP_NO_DOCUMENTS",
                               "error": "There are no input documents to map; do not claim line mapping was performed.",
                               "next_action": "Supply a text specification with runtime_options.ut_documents and rerun UTProject inspect."}
            if not source and self.phase == "mock_batch":
                return False, {"error_code": "UT_MOCK_BATCH_NO_COMPONENTS",
                               "error": "No Mock components exist in this DUT testbench.",
                               "next_action": "Disable ut_mock_components if no Mock is needed, or implement and test the required producer."}
            if not source:
                result = audit_project(self.workspace, self.dut, self.project, self.phase)
                return result["ok"], result
            notes = []
            self.batch_task.sync_source_task(source, notes, "Batch source changed")
            self.batch_task.sync_gen_task(generated, notes, "Batch evidence changed")
            passed, result = self.batch_task.do_complete(
                notes, is_complete, "current design, inventory or scenario IDs",
                "verified line mappings, coverage points or signed test cases",
                " Read Guide_Doc/ut-stages.md and handle the next reported batch.")
            if not passed:
                return passed, result
            final = audit_project(self.workspace, self.dut, self.project, self.phase)
            return final["ok"], final
        except (OSError, ValueError, KeyError, TypeError, SyntaxError) as error:
            return False, {"error_code": "UT_BATCH_EVIDENCE_INVALID",
                           "error": str(error)[:2000], "artifact": self.phase,
                           "next_action": "Repair the current source or signed run and recheck this batch using Guide_Doc/ut-stages.md."}
