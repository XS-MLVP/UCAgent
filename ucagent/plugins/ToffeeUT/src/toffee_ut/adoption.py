"""Task-scoped handoff validation without inheriting or certifying verification progress."""

from pathlib import Path

import yaml

from ucagent.core.checkers.base import Checker

from .audit import read_spec
from .paths import local_path


def stage_catalog(stages=None):
    """Read stable stage names and parent relationships from the main workflow."""
    if stages is None:
        path = Path(__file__).parent / "workflows/ut.yaml"
        stages = yaml.safe_load(path.read_text())["stage"]
    catalog = {}

    def collect(rows, parent=None):
        """Traverse actual workflow nodes rather than maintaining a skip whitelist."""
        for row in rows:
            name = row["name"]
            if name in catalog:
                raise ValueError(f"Ambiguous main workflow stage name: {name}")
            catalog[name] = {"description": row["desc"], "parent": parent}
            collect(row.get("stage", []), name)

    collect(stages)
    return catalog


def validate_task_selection(task, selected, catalog):
    """Validate an explicit task scope; None retains the complete configured workflow."""
    if not isinstance(task, str):
        raise ValueError("runtime_options.ut_task must be a string")
    if selected is None:
        return None
    if not task.strip():
        raise ValueError("Selecting stages requires a nonempty runtime_options.ut_task")
    if (not isinstance(selected, list) or not selected
            or any(not isinstance(name, str) or not name.strip() for name in selected)):
        raise ValueError("runtime_options.ut_task_stages must be null or a nonempty list of stage names")
    if len(selected) != len(set(selected)):
        raise ValueError("runtime_options.ut_task_stages must not contain duplicates")
    unknown = [name for name in selected if name not in catalog]
    if unknown:
        raise ValueError(f"Unknown task stages: {unknown[:8]}; use names from workflows/ut.yaml")
    return list(selected)


class ToffeeUTAdoptionChecker(Checker):
    """Check a bounded task handoff, not full-suite readiness or hardware correctness."""

    def __init__(self, phase, project="ut_project", dut=None, cfg=None):
        """Store inputs without reading workspace state during construction."""
        super().__init__()
        if phase not in {"task", "inventory", "handoff"}:
            raise ValueError("Unknown task adoption phase")
        self.phase, self.project, self.dut, self.cfg = phase, project, dut, cfg

    def do_check(self, is_complete=False, **kwargs):
        """Validate task scope, referenced assets and an explicit stage proposal only."""
        relative = (Path(self.project) / f"docs/reviews/{self.dut}-adoption.md").as_posix()
        try:
            path = local_path(self.workspace, relative)
            data = read_spec(path, "task_adoption", self.dut)
            if data.get("project") != self.project:
                raise ValueError(f"Handoff project must be {self.project!r}")
            task = data.get("task")
            if not isinstance(task, str) or not task.strip():
                raise ValueError("Handoff task must state the current user request")
            configured_task = self.cfg.get_value("runtime_options.ut_task", "") if self.cfg is not None else ""
            if configured_task and task != configured_task:
                raise ValueError("Handoff task differs from runtime_options.ut_task; confirm the intended scope")
            for key in ("acceptance", "out_of_scope"):
                items = data.get(key)
                if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
                    raise ValueError(f"{key} must be a list of nonempty scope statements")
                if key == "acceptance" and not items:
                    raise ValueError("State at least one task-specific acceptance condition")
            if self.phase != "task":
                assets = data.get("assets")
                if not isinstance(assets, list):
                    raise ValueError("assets must list only the existing materials relevant to this task")
                seen = set()
                for asset in assets:
                    if not isinstance(asset, dict) or asset.get("use") not in {"reuse", "inspect", "repair"}:
                        raise ValueError("Each asset needs path, use: reuse/inspect/repair, and note")
                    name = asset.get("path")
                    source = local_path(self.workspace, name)
                    if not source.is_file() or source.resolve() == path.resolve() or name in seen:
                        raise ValueError(f"Asset must be a unique existing workspace file, not this handoff: {name}")
                    if not isinstance(asset.get("note"), str) or not asset["note"].strip():
                        raise ValueError(f"Explain the role and evidence limitations of asset: {name}")
                    seen.add(name)
                dependencies = data.get("dependencies")
                if not isinstance(dependencies, list) or any(not isinstance(item, str) or not item.strip() for item in dependencies):
                    raise ValueError("dependencies must list missing prerequisites or use [] when none are known")
                if not assets and not dependencies:
                    raise ValueError("Identify relevant existing assets or explain the missing prerequisites")
            if self.phase == "handoff":
                selected = validate_task_selection(task, data.get("selected_stages"), stage_catalog())
                if selected is None:
                    raise ValueError("Propose explicit selected_stages for this task, not a blanket progress claim")
                configured = self.cfg.get_value("runtime_options.ut_task_stages", None) if self.cfg is not None else None
                if configured is not None and selected != configured:
                    raise ValueError("Proposed stages differ from the explicitly configured task scope")
                revalidation = data.get("revalidation")
                if (not isinstance(revalidation, list) or not revalidation
                        or any(not isinstance(item, str) or not item.strip() for item in revalidation)):
                    raise ValueError("Explain the bounded revalidation plan, or why no new execution is needed")
            return True, {"ok": True, "phase": self.phase, "artifact": relative,
                          "note": "Handoff structure checked; this is not stage completion, execution evidence or hardware PASS."}
        except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
            return False, {"error_code": "UT_ADOPTION_INVALID", "error": str(error)[:1800],
                           "artifact": relative,
                           "next_action": "Repair this task handoff using Guide_Doc/ut-adoption.md; do not run unrelated verification."}
