# -*- coding: utf-8 -*-
"""UCAgent checkers for workflow builder output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ucagent.checkers.base import Checker

from .core import (
    WorkflowBuildError,
    build_workflow,
    check_path_safety,
    load_yaml_config,
    validate_build_config,
)
from .plan_contract import validate_records
from .delivery_contract import (
    FORBIDDEN_PARTS,
    FORBIDDEN_SUFFIXES,
    FORBIDDEN_TOP_LEVEL,
    OUTPUT_PLACEHOLDER_NAMES,
    PARTIAL_FORBIDDEN_PREFIXES,
    PRESERVED_LOG_PREFIXES,
    has_prefix,
    is_release_runtime_artifact,
    load_acceptance_contract,
)
try:
    from ..workflow_guidedoc_generator.contract import REQUIRED_SECTION_IDS, section_id
except ImportError:  # Direct package execution from examples/workflow_builder.
    from workflow_guidedoc_generator.contract import REQUIRED_SECTION_IDS, section_id


def _render_guidedoc_spec(spec: dict[str, Any]) -> str:
    """Render a spec in memory using the same Markdown structure as the generator."""
    lines = [f"# {spec.get('title', '')}", ""]
    sections = spec.get("sections", [])
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            lines.extend([
                f"## {section.get('heading', '')}",
                "",
                str(section.get("content", "")).rstrip(),
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def _guidedoc_provenance_errors(root: Path) -> list[dict[str, str]]:
    """Report generated documents whose embedded spec identity is missing or stale."""
    errors: list[dict[str, str]] = []
    specs_dir = root / ".workflow" / "guidedoc_specs"
    if not specs_dir.is_dir():
        return errors
    for spec_path in sorted(specs_dir.glob("*.yaml")):
        try:
            spec = load_yaml_config(spec_path)
        except WorkflowBuildError as exc:
            errors.append({
                "spec": spec_path.relative_to(root).as_posix(),
                "reason": f"cannot load spec: {exc}",
            })
            continue
        output_rel = spec.get("output") if isinstance(spec, dict) else None
        if not isinstance(output_rel, str) or not output_rel:
            continue
        output = root / output_rel
        if not output.is_file():
            continue
        text = output.read_text(encoding="utf-8")
        spec_rel = spec_path.relative_to(root).as_posix()
        expected_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        source_match = re.search(r"<!--\s*GENERATED-FROM:\s*([^\n]+?)\s*-->", text)
        sha_match = re.search(r"<!--\s*SPEC-SHA256:\s*([0-9a-fA-F]+)\s*-->", text)
        if not source_match or not sha_match:
            errors.append({
                "spec": spec_rel,
                "output": output_rel,
                "reason": "generation provenance is missing; rerun WorkflowGuideDocGenerator",
            })
            continue
        actual_source = source_match.group(1).strip()
        actual_sha = sha_match.group(1).lower()
        if actual_source != spec_rel or actual_sha != expected_sha:
            errors.append({
                "spec": spec_rel,
                "output": output_rel,
                "reason": "spec changed after this document was generated; rerun WorkflowGuideDocGenerator",
                "expected_sha256": expected_sha,
                "document_sha256": actual_sha,
            })
    return errors


class WorkflowBuildConfigChecker(Checker):
    """Validate workflow_build.yaml without creating files."""

    def __init__(
        self,
        build_config_path: str,
        expected_root: str = "",
        run_planned_checker_tests: bool = False,
        **kwargs,
    ):
        super().__init__()
        self.build_config_path = build_config_path
        self.expected_root = expected_root
        self.run_planned_checker_tests = run_planned_checker_tests
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def _workspace_root(self) -> Path:
        if self.workspace:
            return Path(self.workspace).resolve()
        return Path(os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()

    def _resolve(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute():
            return path.resolve()
        return (self._workspace_root() / path).resolve()

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate workflow_build.yaml syntax, required fields, field types, and path safety.
        This checker does not create files; it only verifies that WorkflowBuilder can safely consume the build config.
        """
        config_path = self._resolve(self.build_config_path)
        path_warning = ""
        try:
            data = load_yaml_config(config_path)
            validate_build_config(data)
            check_path_safety(data, self._workspace_root())
        except WorkflowBuildError as exc:
            if exc.code == "PATH-004" and "目标目录已存在" in exc.message:
                path_warning = str(exc)
            else:
                return False, {"error": str(exc), "build_config_path": str(config_path)}
        if self.expected_root:
            configured_root = Path(str(data["root"]["path"])).as_posix()
            expected_root = Path(self.expected_root).as_posix()
            configured_root = configured_root.removeprefix("./").rstrip("/")
            expected_root = expected_root.removeprefix("./").rstrip("/")
            if configured_root != expected_root:
                return False, {
                    "error": "workflow root does not match the configured delivery directory",
                    "configured_root": configured_root,
                    "expected_root": expected_root,
                    "suggestion": (
                        "Set root.path to the exact expected_root. "
                        "Do not derive the directory from workflow.name."
                    ),
                }
        checker_test_results: dict[str, Any] = {}
        if self.run_planned_checker_tests:
            try:
                with tempfile.TemporaryDirectory(prefix="wfb-checker-preflight-") as temp_dir:
                    report = build_workflow(config_path, base_dir=temp_dir)
                    generated_root = Path(report.root_path)
                    for target in (
                        "check_checker_specs",
                        "check_checkers",
                        "test_checkers",
                    ):
                        proc = subprocess.run(
                            ["make", target],
                            cwd=str(generated_root),
                            text=True,
                            capture_output=True,
                            timeout=timeout or 120,
                        )
                        checker_test_results[target] = {
                            "returncode": proc.returncode,
                            "stdout": proc.stdout[-5000:],
                            "stderr": proc.stderr[-5000:],
                        }
                        if proc.returncode != 0:
                            return False, {
                                "error": "planned Checker preflight failed",
                                "failed_target": target,
                                "checker_test_results": checker_test_results,
                                "suggestion": (
                                    "Fix workflow_spec.checkers source, fixtures, and tests "
                                    "in workflow_build.yaml before calling WorkflowBuilder "
                                    "for the delivery directory."
                                ),
                            }
            except (WorkflowBuildError, OSError, subprocess.SubprocessError) as exc:
                return False, {
                    "error": f"planned Checker preflight could not run: {exc}",
                    "checker_test_results": checker_test_results,
                }
        result = {
            "message": "workflow_build.yaml validation passed",
            "build_config_path": str(config_path),
        }
        if checker_test_results:
            result["checker_test_results"] = checker_test_results
        if path_warning:
            result["warning"] = path_warning
        return True, result


class WorkflowInputExampleManifestChecker(WorkflowBuildConfigChecker):
    """Validate the WFB-side manifest that defines how bundled examples are copied."""

    def __init__(self, manifest_path: str, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.manifest_path = manifest_path

    def _safe_child(self, base: Path, rel_text: str) -> tuple[Path | None, str]:
        rel = Path(rel_text)
        if rel.is_absolute() or ".." in rel.parts:
            return None, "path must be relative and must not contain .."
        resolved = (base / rel).resolve()
        if resolved != base and base not in resolved.parents:
            return None, "path escapes base directory"
        return resolved, ""

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate `wfgen/input_example_manifest.yaml` before WorkflowBuilder creates the child workflow.
        The manifest must define how the bundled example is copied into `input/example/`, and any
        `resource.json` paths declared by the example must resolve to real files under the source directory.
        """
        manifest_path = self._resolve(self.manifest_path)
        if not manifest_path.is_file():
            return False, {"error": "input example manifest not found", "manifest_path": str(manifest_path)}
        try:
            manifest = load_yaml_config(manifest_path)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "manifest_path": str(manifest_path)}
        if not isinstance(manifest, dict):
            return False, {"error": "input example manifest must be a mapping", "manifest_path": str(manifest_path)}

        source_dir_text = str(manifest.get("source_dir", "")).strip()
        target_dir = str(manifest.get("target_dir", "")).strip()
        copy_mode = str(manifest.get("copy_mode", "")).strip()
        required_input = manifest.get("required_input")
        if not source_dir_text or not target_dir or not copy_mode:
            return False, {
                "error": "input example manifest is missing required fields",
                "required_fields": ["source_dir", "target_dir", "copy_mode", "required_input"],
            }
        if target_dir != "input/example":
            return False, {"error": "input example target_dir must be input/example", "target_dir": target_dir}
        if copy_mode not in {"copy_tree", "self_contained"}:
            return False, {"error": "unsupported input example copy_mode", "copy_mode": copy_mode}
        if not isinstance(required_input, list) or not required_input:
            return False, {"error": "required_input must be a non-empty list"}

        source_dir = self._resolve(source_dir_text)
        source_exists = source_dir.is_dir()
        if source_exists and copy_mode != "copy_tree":
            return False, {"error": "existing source_dir must use copy_mode=copy_tree", "source_dir": str(source_dir)}
        if not source_exists and copy_mode != "self_contained":
            return False, {"error": "source_dir does not exist; use copy_mode=self_contained or provide test_input", "source_dir": str(source_dir)}

        missing_required: list[str] = []
        if source_exists:
            for item in required_input:
                if isinstance(item, str):
                    rel_text = item
                    input_type = "file"
                elif isinstance(item, dict):
                    rel_text = str(item.get("path", "")).strip()
                    input_type = str(item.get("type", "file")).strip()
                else:
                    return False, {"error": "required_input entries must be strings or mappings"}
                if not rel_text:
                    return False, {"error": "required_input entry is missing path", "entry": item}
                resolved, error = self._safe_child(source_dir, rel_text)
                if error:
                    return False, {"error": error, "path": rel_text}
                if input_type == "directory":
                    if not resolved or not resolved.is_dir():
                        missing_required.append(rel_text)
                elif not resolved or not resolved.is_file():
                    missing_required.append(rel_text)
            if missing_required:
                return False, {"error": "required example inputs are missing under source_dir", "missing": missing_required}

        resource_paths = manifest.get("resource_paths", [])
        if resource_paths is None:
            resource_paths = []
        if not isinstance(resource_paths, list):
            return False, {"error": "resource_paths must be a list when present"}
        normalized_resource_paths: list[dict[str, str]] = []
        for entry in resource_paths:
            if isinstance(entry, str):
                normalized_resource_paths.append({"declared_path": entry, "source_path": entry})
            elif isinstance(entry, dict):
                declared_path = str(entry.get("declared_path", entry.get("path", ""))).strip()
                source_path = str(entry.get("source_path", entry.get("source", ""))).strip()
                if not declared_path:
                    declared_path = source_path
                if not source_path:
                    source_path = declared_path
                if not declared_path or not source_path:
                    return False, {"error": "resource_paths mapping entries need declared_path/path and source_path/source", "entry": entry}
                normalized_resource_paths.append({"declared_path": declared_path, "source_path": source_path})
            else:
                return False, {"error": "resource_paths entries must be strings or mappings", "entry": entry}

        resource_json = source_dir / "resource.json"
        declared_resource_paths: list[str] = []
        if source_exists and resource_json.is_file():
            try:
                payload = json.loads(resource_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return False, {"error": f"source resource.json is invalid: {exc}", "path": str(resource_json)}
            resources = payload.get("resources", []) if isinstance(payload, dict) else []
            if resources is None:
                resources = []
            if not isinstance(resources, list):
                return False, {"error": "source resource.json resources must be a list"}
            for index, item in enumerate(resources):
                if not isinstance(item, dict):
                    return False, {"error": "resource entries must be mappings", "index": index}
                rel_text = item.get("path")
                if isinstance(rel_text, str) and rel_text.strip():
                    declared_resource_paths.append(rel_text.strip())
            manifest_declared = {item["declared_path"] for item in normalized_resource_paths}
            manifest_sources = {item["source_path"] for item in normalized_resource_paths}
            manifest_source_names = {Path(item["source_path"]).name for item in normalized_resource_paths}
            missing_from_manifest = [
                path
                for path in declared_resource_paths
                if path not in manifest_declared
                and path not in manifest_sources
                and Path(path).name not in manifest_source_names
            ]
            if missing_from_manifest:
                return False, {"error": "resource_paths does not list all resource.json paths", "missing": missing_from_manifest}

        missing_resources: list[dict[str, str]] = []
        if source_exists:
            for item in normalized_resource_paths:
                rel_text = item["source_path"]
                resolved, error = self._safe_child(source_dir, rel_text)
                if error:
                    return False, {"error": error, "path": rel_text}
                if not resolved or not resolved.is_file():
                    missing_resources.append({
                        "source_path": rel_text,
                        "resolved_path": str(resolved) if resolved else "",
                    })
            if missing_resources:
                return False, {
                    "error": (
                        "example resource files are missing under source_dir; "
                        "source_path must be relative to source_dir and must not repeat its prefix"
                    ),
                    "source_dir": str(source_dir),
                    "missing": missing_resources,
                }

        return True, {
            "message": "input example manifest passed",
            "manifest_path": str(manifest_path),
            "source_dir": str(source_dir),
            "copy_mode": copy_mode,
            "resource_count": len(normalized_resource_paths),
        }


class WorkflowBuildOutputChecker(WorkflowBuildConfigChecker):
    """Check generated workflow skeleton and optionally run make check."""

    def __init__(
        self,
        build_config_path: str,
        workflow_root: str = "",
        input_example_manifest_path: str = "",
        run_make_check: bool = True,
        **kwargs,
    ):
        super().__init__(build_config_path, **kwargs)
        self.workflow_root = workflow_root
        self.input_example_manifest_path = input_example_manifest_path
        self.run_make_check = run_make_check

    def _workflow_root(self, data: dict[str, Any]) -> Path:
        root_text = self.workflow_root or data["root"]["path"]
        root_path = Path(root_text)
        if root_path.is_absolute():
            return root_path.resolve()
        return (self._workspace_root() / root_path).resolve()

    def _check_example_resource_paths(self, root: Path, data: dict[str, Any]) -> list[dict[str, str]]:
        runtime_contract = data.get("runtime_contract", {}) if isinstance(data.get("runtime_contract"), dict) else {}
        input_root = str(runtime_contract.get("input_root") or "input")
        example_target = str(runtime_contract.get("example_target") or "example")
        example_dir = (root / input_root / example_target).resolve()
        resource_json = example_dir / "resource.json"
        if not resource_json.is_file():
            return []

        try:
            payload = json.loads(resource_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return [{"path": "resource.json", "error": f"invalid JSON: {exc}"}]
        if not isinstance(payload, dict):
            return [{"path": "resource.json", "error": "resource.json must contain an object"}]

        resources = payload.get("resources", [])
        if resources is None:
            resources = []
        if not isinstance(resources, list):
            return [{"path": "resources", "error": "resources must be a list"}]

        errors: list[dict[str, str]] = []
        for index, item in enumerate(resources):
            if not isinstance(item, dict):
                errors.append({"path": f"resources[{index}]", "error": "resource entry must be an object"})
                continue
            rel_text = item.get("path")
            if not rel_text:
                continue
            if not isinstance(rel_text, str):
                errors.append({"path": f"resources[{index}].path", "error": "path must be a string"})
                continue
            rel_path = Path(rel_text)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                errors.append({"path": rel_text, "error": "resource path must be relative and stay under input/example"})
                continue
            resolved = (example_dir / rel_path).resolve()
            if resolved != example_dir and example_dir not in resolved.parents:
                errors.append({"path": rel_text, "error": "resource path escapes input/example"})
                continue
            if not resolved.is_file():
                errors.append({"path": rel_text, "error": "resource file does not exist under input/example"})
        return errors

    def _check_input_example_copy(self, root: Path) -> dict[str, Any] | None:
        if not self.input_example_manifest_path:
            return None
        manifest_path = self._resolve(self.input_example_manifest_path)
        try:
            manifest = load_yaml_config(manifest_path)
        except WorkflowBuildError as exc:
            return {"error": str(exc), "manifest_path": str(manifest_path)}
        if str(manifest.get("copy_mode", "")).strip() != "copy_tree":
            return None
        source = self._resolve(str(manifest.get("source_dir", "")).strip())
        target = (root / str(manifest.get("target_dir", "")).strip()).resolve()
        if not source.is_dir() or not target.is_dir():
            return {
                "error": "input example source or target directory is missing",
                "source": str(source),
                "target": str(target),
            }
        missing: list[str] = []
        content_mismatches: list[str] = []
        for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
            relative = source_file.relative_to(source)
            target_file = target / relative
            if not target_file.is_file():
                missing.append(relative.as_posix())
            elif source_file.read_bytes() != target_file.read_bytes():
                content_mismatches.append(relative.as_posix())
        if missing or content_mismatches:
            return {
                "error": "copy_tree output is not a byte-for-byte copy of the source",
                "missing": missing,
                "content_mismatches": content_mismatches,
            }
        return None

    @staticmethod
    def _check_runtime_input_alignment(root: Path, build_config: dict[str, Any]) -> dict[str, Any] | None:
        """Reject a generated Makefile that requires inputs absent from the runtime contract."""
        makefile = root / "Makefile"
        if not makefile.is_file():
            return None
        text = makefile.read_text(encoding="utf-8")
        declared = {
            str(item.get("path") if isinstance(item, dict) else item).replace("<TARGET>", "{TARGET}")
            for item in build_config.get("runtime_contract", {}).get("required_input", [])
        }
        checks = {
            "metadata": "input/$(TARGET)/metadata" in text,
            "checksums": "input/$(TARGET)/checksums.sha256" in text,
        }
        missing = []
        if checks["metadata"] and not any(path.endswith("metadata") and "directory" in str(item) for item in build_config.get("runtime_contract", {}).get("required_input", []) for path in [str(item.get("path", ""))] if isinstance(item, dict)):
            missing.append("input/<TARGET>/metadata (directory)")
        if checks["checksums"] and not any(path.endswith("checksums.sha256") for path in declared):
            missing.append("input/<TARGET>/checksums.sha256 (file)")
        if missing:
            return {"error": "Makefile input checks are not represented in runtime_contract.required_input", "missing": missing}
        return None

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate the generated workflow skeleton and run its generated `make check` target.
        The check passes only when required files/directories exist and the generated internal checkers pass.
        """
        config_path = self._resolve(self.build_config_path)
        try:
            data = load_yaml_config(config_path)
            validate_build_config(data)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "build_config_path": str(config_path)}

        root = self._workflow_root(data)
        if not root.is_dir():
            return False, {"error": f"generated workflow root not found: {root}"}

        alignment_error = self._check_runtime_input_alignment(root, data)
        if alignment_error:
            return False, alignment_error

        missing: list[str] = []
        acceptance_path = root / ".workflow" / "acceptance_rules.yaml"
        if not acceptance_path.is_file():
            return False, {"error": f"acceptance_rules.yaml not found: {acceptance_path}"}

        acceptance = load_yaml_config(acceptance_path)
        for key in ("required_public_files", "required_internal_files"):
            for rel_path in acceptance.get(key, []):
                if not (root / rel_path).is_file():
                    missing.append(rel_path)
        for key in ("required_public_dirs", "required_internal_dirs"):
            for rel_path in acceptance.get(key, []):
                if not (root / rel_path).is_dir():
                    missing.append(rel_path)
        if missing:
            return False, {"error": "generated workflow is incomplete", "missing": missing}

        migration_required = ["install.py", ".install/README.md", ".install/manifest.json"]
        migration_missing = [rel for rel in migration_required if not (root / rel).is_file()]
        if migration_missing:
            return False, {"error": "generated workflow migration files are incomplete", "missing": migration_missing}

        canonical_checkers = [
            ".workflow/checkers/config_syntax_checker.py",
            ".workflow/checkers/layout_checker.py",
            ".workflow/checkers/guidedoc_basic_checker.py",
        ]
        empty_checkers = [rel for rel in canonical_checkers if not (root / rel).is_file() or (root / rel).stat().st_size == 0]
        if empty_checkers:
            return False, {"error": "generated workflow contains empty canonical checkers", "empty_checkers": empty_checkers}

        example_resource_errors = self._check_example_resource_paths(root, data)
        if example_resource_errors:
            return False, {
                "error": "bundled example resource paths are invalid",
                "workflow_root": str(root),
                "example_resource_errors": example_resource_errors,
            }
        example_copy_error = self._check_input_example_copy(root)
        if example_copy_error:
            return False, {
                "error": "bundled example copy verification failed",
                "workflow_root": str(root),
                "copy_details": example_copy_error,
            }

        tool_generation_doc = root / "Guide_Doc" / "tool_generation.md"
        if tool_generation_doc.is_file():
            doc_text = tool_generation_doc.read_text(encoding="utf-8")
            required_doc_text = ["tool_specs", "check_tool_specs", "check_tools", "test_tools", "test_mcp", "GeneratedTools"]
            missing_doc_text = [item for item in required_doc_text if item not in doc_text]
            if missing_doc_text:
                return False, {
                    "error": "tool generation guide is incomplete",
                    "workflow_root": str(root),
                    "missing_doc_text": missing_doc_text,
                }

        planned_checkers = data.get("workflow_spec", {}).get("checkers", [])
        planned_missing: list[str] = []
        for checker in planned_checkers:
            name = checker["name"]
            for rel in (
                f".workflow/checker_specs/{name}.yaml",
                checker["entry"]["file"],
            ):
                if not (root / rel).is_file():
                    planned_missing.append(rel)
            for fixture in checker.get("fixtures", []):
                if not (root / fixture["path"]).is_file():
                    planned_missing.append(fixture["path"])
        if planned_missing:
            return False, {
                "error": "planned business checker artifacts are incomplete",
                "missing": planned_missing,
            }

        result: dict[str, Any] = {"message": "generated workflow layout exists", "workflow_root": str(root)}
        checker_targets = (
            "check_checker_specs",
            "check_checkers",
            "test_checkers",
        )
        checker_results = {}
        for target in checker_targets:
            proc = subprocess.run(
                ["make", target],
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=timeout or 60,
            )
            checker_results[target] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2500:],
                "stderr": proc.stderr[-2500:],
            }
            if proc.returncode != 0:
                result["checker_targets"] = checker_results
                return False, result
        result["checker_targets"] = checker_results
        if self.run_make_check:
            proc_timeout = timeout or 60
            proc = subprocess.run(
                ["make", "check"],
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            result["make_check_returncode"] = proc.returncode
            result["stdout"] = proc.stdout[-4000:]
            result["stderr"] = proc.stderr[-4000:]
            if proc.returncode != 0:
                return False, result
            result["message"] = "generated workflow make check passed"
        return True, result


class WorkflowMinimalInitChecker(WorkflowBuildConfigChecker):
    """Check that a generated workflow has been initialized as a runnable minimal UCAgent workflow."""

    def __init__(
        self,
        workflow_root: str,
        run_make_check: bool = True,
        run_smoke: bool = True,
        **kwargs,
    ):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.run_make_check = run_make_check
        self.run_smoke = run_smoke

    def _workflow_root_from_arg(self) -> Path:
        root_path = Path(self.workflow_root)
        if root_path.is_absolute():
            return root_path.resolve()
        return (self._workspace_root() / root_path).resolve()

    def _missing_text(self, file_path: Path, needles: list[str]) -> list[str]:
        text = file_path.read_text(encoding="utf-8")
        return [needle for needle in needles if needle not in text]

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate minimal UCAgent initialization for a generated workflow.
        The check verifies ucagent_setup.sh, Makefile run/smoke/session/tmux targets, runnable config.yaml fields,
        then optionally runs the generated workflow's `make check` and `make smoke` targets.
        """
        root = self._workflow_root_from_arg()
        if not root.is_dir():
            return False, {"error": f"workflow root not found: {root}"}

        required_files = [
            "setup.py",
            "config/environment.schema.yaml",
            "ucagent_setup.sh",
            "Makefile",
            "config.yaml",
            "README.md",
            "Guide_Doc/overview.md",
            "install.py",
            ".install/README.md",
            ".install/manifest.json",
        ]
        missing_files = [rel for rel in required_files if not (root / rel).is_file()]
        if missing_files:
            return False, {"error": "minimal workflow init files are missing", "missing_files": missing_files}

        setup_missing = self._missing_text(root / "ucagent_setup.sh", ["ucagent_env()", "proxy_on()", "UCAGENT_HOME", "UCAGENT_VENV"])
        make_missing = self._missing_text(
            root / "Makefile",
            [
                "run:",
                "smoke:",
                "session:",
                "tmux:",
                "test_mcp:",
                "configure:",
                "configure-check:",
                "python3 setup.py",
                "UCAGENT_SETUP_CMD",
                "ucagent_env",
                "proxy_on",
                "--config ./config.yaml",
                "--output $(OUT)",
                "--guid-doc-path ./Guide_Doc/",
                "--append-py-path .",
                "--mcp-server-port $(MCP_SERVER_PORT)",
                "--loop",
                "--loop-msg",
                "--exit-on-completion",
            ],
        )
        make_text = (root / "Makefile").read_text(encoding="utf-8")
        forbidden_make_text = [
            phrase
            for phrase in [
                "may be expected with --exit-on-completion",
                "UCAgent smoke exited with code",
            ]
            if phrase in make_text
        ]

        config_path = root / "config.yaml"
        try:
            config = load_yaml_config(config_path)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "config_path": str(config_path)}

        missing_config: list[str] = []
        for key in ("workflow", "paths", "model", "loop_settings", "tools", "checkers", "guide_docs"):
            if key not in config:
                missing_config.append(key)
        tools = config.get("tools", {})
        if not isinstance(tools, dict):
            missing_config.append("tools")
        elif not isinstance(tools.get("RunTestCases"), dict) or not tools["RunTestCases"].get("test_dir"):
            missing_config.append("tools.RunTestCases.test_dir")
        if not isinstance(config.get("mission"), dict):
            missing_config.append("mission")
        if not isinstance(config.get("stage"), list) or not config.get("stage"):
            missing_config.append("stage")
        if "template" not in config:
            missing_config.append("template")
        if config.get("write_dirs") != ["{OUT}/{DUT}"]:
            missing_config.append("write_dirs.{OUT}/{DUT}")
        if not isinstance(config.get("un_write_dirs"), list):
            missing_config.append("un_write_dirs")

        problems: dict[str, Any] = {
            "setup_missing_text": setup_missing,
            "makefile_missing_text": make_missing,
            "makefile_forbidden_text": forbidden_make_text,
            "config_missing_fields": missing_config,
        }
        if setup_missing or make_missing or forbidden_make_text or missing_config:
            return False, {"error": "minimal workflow init check failed", "workflow_root": str(root), **problems}

        result: dict[str, Any] = {"message": "minimal workflow initialization check passed", "workflow_root": str(root)}
        if self.run_make_check:
            proc_timeout = timeout or 60
            proc = subprocess.run(
                ["make", "check"],
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            result["make_check_returncode"] = proc.returncode
            result["stdout"] = proc.stdout[-4000:]
            result["stderr"] = proc.stderr[-4000:]
            if proc.returncode != 0:
                return False, result
        if self.run_smoke:
            proc_timeout = timeout or 240
            proc = subprocess.run(
                ["make", "smoke"],
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            result["make_smoke_returncode"] = proc.returncode
            result["make_smoke_stdout"] = proc.stdout[-6000:]
            result["make_smoke_stderr"] = proc.stderr[-6000:]
            if proc.returncode != 0:
                result["message"] = "minimal workflow smoke run failed"
                return False, result
            smoke_output = proc.stdout + proc.stderr
            completion_markers = ["All stages completed", "ToolExit", "Verify Agent finished"]
            if not any(marker in smoke_output for marker in completion_markers):
                result["message"] = "minimal workflow smoke output has no UCAgent completion marker"
                result["required_completion_markers"] = completion_markers
                return False, result
            result["message"] = "minimal workflow make check and smoke passed"
        return True, result


class WorkflowEnvironmentSetupChecker(WorkflowBuildConfigChecker):
    """Validate the generated workflow's portable environment configurator."""

    BEGIN = "# BEGIN WORKFLOW ENVIRONMENT (generated by setup.py)"
    END = "# END WORKFLOW ENVIRONMENT (generated by setup.py)"

    def __init__(self, workflow_root: str, run_test: bool = True, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.run_test = run_test

    def _root(self) -> Path:
        path = Path(self.workflow_root)
        return path.resolve() if path.is_absolute() else (self._workspace_root() / path).resolve()

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate setup.py, its schema, managed blocks, and safe repeat execution."""
        root = self._root()
        required = [
            "setup.py",
            "config/environment.schema.yaml",
            "Makefile",
            "ucagent_setup.sh",
        ]
        missing = [rel for rel in required if not (root / rel).is_file()]
        if missing:
            return False, {"error": "environment setup files are missing", "missing": missing}

        setup_source = (root / "setup.py").read_text(encoding="utf-8")
        make_source = (root / "Makefile").read_text(encoding="utf-8")
        shell_source = (root / "ucagent_setup.sh").read_text(encoding="utf-8")
        source_missing = [
            marker
            for marker in [
                "--set",
                "--config",
                "--check",
                "--dry-run",
                "--non-interactive",
                "atomic_write",
                "reject_credentials",
            ]
            if marker not in setup_source
        ]
        block_errors = []
        for rel, text in (("Makefile", make_source), ("ucagent_setup.sh", shell_source)):
            if text.count(self.BEGIN) != 1 or text.count(self.END) != 1:
                block_errors.append(f"{rel} must contain exactly one generated environment block")
        make_missing = [
            marker
            for marker in ["configure:", "configure-check:", "python3 setup.py"]
            if marker not in make_source
        ]
        proxy_function = shell_source.split("proxy_on()", 1)[-1]
        proxy_sanitization_errors = []
        if "unset all_proxy ALL_PROXY" not in proxy_function:
            proxy_sanitization_errors.append(
                "proxy_on must clear inherited all_proxy and ALL_PROXY"
            )
        elif proxy_function.find("unset all_proxy ALL_PROXY") > proxy_function.find(
            'WORKFLOW_BUILD_PROXY_ENABLED:-0'
        ):
            proxy_sanitization_errors.append(
                "proxy_on must clear inherited ALL_PROXY before the disabled early return"
            )
        try:
            schema = load_yaml_config(root / "config/environment.schema.yaml")
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}
        settings = schema.get("settings")
        schema_errors = []
        if not isinstance(settings, dict):
            schema_errors.append("settings must be a mapping")
            settings = {}
        for name in ("ucagent_home", "ucagent_venv", "python", "proxy_enabled"):
            if name not in settings:
                schema_errors.append(f"missing base setting: {name}")
        if (
            source_missing
            or block_errors
            or make_missing
            or schema_errors
            or proxy_sanitization_errors
        ):
            return False, {
                "error": "environment setup static contract failed",
                "setup_missing": source_missing,
                "block_errors": block_errors,
                "makefile_missing": make_missing,
                "schema_errors": schema_errors,
                "proxy_sanitization_errors": proxy_sanitization_errors,
            }

        if not self.run_test:
            return True, {"message": "environment setup static contract passed"}

        proc_timeout = timeout or 30
        with tempfile.TemporaryDirectory(prefix="workflow_environment_setup_") as temp:
            copied = Path(temp) / "workflow"
            shutil.copytree(root, copied)
            command = [
                sys.executable,
                "setup.py",
                "--non-interactive",
                "--set",
                f"ucagent_home={copied}",
                "--set",
                f"ucagent_venv={Path(sys.executable).parent.parent}",
                "--set",
                f"python={sys.executable}",
            ]
            first = subprocess.run(
                command,
                cwd=copied,
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            if first.returncode != 0:
                return False, {
                    "error": "environment setup execution failed",
                    "stdout": first.stdout[-3000:],
                    "stderr": first.stderr[-3000:],
                }
            first_make = (copied / "Makefile").read_bytes()
            first_shell = (copied / "ucagent_setup.sh").read_bytes()
            second = subprocess.run(
                command,
                cwd=copied,
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            if second.returncode != 0:
                return False, {"error": "environment setup repeat execution failed", "stderr": second.stderr[-3000:]}
            if first_make != (copied / "Makefile").read_bytes() or first_shell != (copied / "ucagent_setup.sh").read_bytes():
                return False, {"error": "environment setup is not idempotent"}
            local_path = copied / ".workflow/local/environment.yaml"
            if not local_path.is_file():
                return False, {"error": "environment setup did not persist local YAML"}
            local_text = local_path.read_text(encoding="utf-8")
            if re.search(r"(?i)(token|password|secret)\\s*:", local_text):
                return False, {"error": "local environment file contains a sensitive key"}
            before_invalid = {
                "Makefile": (copied / "Makefile").read_bytes(),
                "ucagent_setup.sh": (copied / "ucagent_setup.sh").read_bytes(),
                "environment.yaml": local_path.read_bytes(),
            }
            invalid = subprocess.run(
                [
                    sys.executable,
                    "setup.py",
                    "--non-interactive",
                    "--set",
                    f"ucagent_home={copied / 'missing'}",
                ],
                cwd=copied,
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            after_invalid = {
                "Makefile": (copied / "Makefile").read_bytes(),
                "ucagent_setup.sh": (copied / "ucagent_setup.sh").read_bytes(),
                "environment.yaml": local_path.read_bytes(),
            }
            if invalid.returncode == 0 or before_invalid != after_invalid:
                return False, {"error": "invalid environment configuration was not rejected atomically"}
            credential = subprocess.run(
                [
                    sys.executable,
                    "setup.py",
                    "--non-interactive",
                    "--set",
                    "http_proxy=http://user:password@127.0.0.1:7897",
                ],
                cwd=copied,
                text=True,
                capture_output=True,
                timeout=proc_timeout,
            )
            if credential.returncode == 0 or before_invalid != {
                "Makefile": (copied / "Makefile").read_bytes(),
                "ucagent_setup.sh": (copied / "ucagent_setup.sh").read_bytes(),
                "environment.yaml": local_path.read_bytes(),
            }:
                return False, {"error": "credential-bearing proxy was persisted or modified managed files"}
            proxy_probe_environment = os.environ.copy()
            proxy_probe_environment.update(
                {
                    "WORKFLOW_BUILD_PROXY_ENABLED": "0",
                    "ALL_PROXY": "socks://127.0.0.1:1080",
                    "all_proxy": "socks://127.0.0.1:1080",
                }
            )
            proxy_probe = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        ". ./ucagent_setup.sh; proxy_on; "
                        'test -z "${ALL_PROXY:-}" && test -z "${all_proxy:-}"'
                    ),
                ],
                cwd=copied,
                text=True,
                capture_output=True,
                timeout=proc_timeout,
                env=proxy_probe_environment,
            )
            if proxy_probe.returncode != 0:
                return False, {
                    "error": "proxy_on did not sanitize inherited ALL_PROXY",
                    "stdout": proxy_probe.stdout[-3000:],
                    "stderr": proxy_probe.stderr[-3000:],
                }

        return True, {"message": "environment setup contract and idempotence passed"}


class WorkflowMCPToolIntegrationChecker(WorkflowBuildConfigChecker):
    """Verify generated tools through a real child-UCAgent MCP server."""

    RESULT_LIST_MARKER = "[PASS] MCP list_tools registered generated"
    REQUIRED_SERVER_LOG_TEXT = [
        "create FastMCP server with tools:",
        "Set file mode to read-write completed",
    ]

    def __init__(self, workflow_root: str, run_test: bool = True, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.run_test = run_test

    def _workflow_root_from_arg(self) -> Path:
        root_path = Path(self.workflow_root)
        if root_path.is_absolute():
            return root_path.resolve()
        return (self._workspace_root() / root_path).resolve()

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Run the generated workflow's real MCP tool integration test."""
        root = self._workflow_root_from_arg()
        required_files = [
            "ucagent_setup.sh",
            "Makefile",
            "tools/mcp_adapters.py",
            ".workflow/tool_tests/run_mcp_tests.py",
        ]
        missing_files = [rel for rel in required_files if not (root / rel).is_file()]
        if missing_files:
            return False, {
                "error": "MCP tool integration files are missing",
                "workflow_root": str(root),
                "missing_files": missing_files,
            }

        make_text = (root / "Makefile").read_text(encoding="utf-8")
        runner_text = (root / ".workflow/tool_tests/run_mcp_tests.py").read_text(encoding="utf-8")
        missing_protocol = [
            text
            for text in [
                "test_mcp:",
                "run_mcp_tests.py",
                "streamablehttp_client",
                "ClientSession",
                "list_tools",
                "call_tool",
            ]
            if text not in make_text + runner_text
        ]
        if missing_protocol:
            return False, {
                "error": "MCP test protocol is incomplete",
                "workflow_root": str(root),
                "missing_protocol_text": missing_protocol,
            }
        forbidden_runner_text = [
            "urllib.request",
            "jsonrpc",
            "mcp_sse_server.py",
            "/sse",
        ]
        leaked = [text for text in forbidden_runner_text if text in runner_text]
        if leaked:
            return False, {
                "error": "MCP test runner uses unsupported hand-written HTTP/SSE protocol",
                "workflow_root": str(root),
                "forbidden_text": leaked,
                "fix": "Regenerate .workflow/tool_tests/run_mcp_tests.py from the WFB mcp_tool_test_runner template.",
            }

        adapter_text = (root / "tools/mcp_adapters.py").read_text(encoding="utf-8")
        adapter_errors = []
        if "def run(self, tool_input" in adapter_text or '"run": run' in adapter_text or "'run': run" in adapter_text:
            adapter_errors.append(
                "tools/mcp_adapters.py must not override BaseTool.run; direct UCAgent execution needs BaseTool to wrap _run output as ToolMessage"
            )
        for marker in ["def _run(self, tool_input=None", "json.dumps(result", "python_type = Any"]:
            if marker not in adapter_text:
                adapter_errors.append(f"tools/mcp_adapters.py missing required marker: {marker}")
        if adapter_errors:
            return False, {
                "error": "MCP adapter contract check failed",
                "workflow_root": str(root),
                "adapter_errors": adapter_errors,
            }

        result: dict[str, Any] = {
            "message": "MCP tool integration protocol exists",
            "workflow_root": str(root),
        }
        if not self.run_test:
            return True, result

        proc_timeout = timeout or 150
        mcp_proc = subprocess.run(
            ["make", "test_mcp"],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=proc_timeout,
        )
        result["make_test_mcp_returncode"] = mcp_proc.returncode
        result["make_test_mcp_stdout"] = mcp_proc.stdout[-5000:]
        result["make_test_mcp_stderr"] = mcp_proc.stderr[-5000:]
        if mcp_proc.returncode != 0:
            result["message"] = "MCP tool integration test failed"
            return False, result

        result_path = root / "output/mcp_test_result.log"
        server_log_path = root / ".workflow/logs/tool_mcp_run.log"
        result_text = result_path.read_text(encoding="utf-8") if result_path.is_file() else ""
        server_log_text = server_log_path.read_text(encoding="utf-8") if server_log_path.is_file() else ""

        try:
            config = load_yaml_config(root / "config.yaml")
        except Exception as exc:
            return False, {"error": f"cannot load generated workflow config: {exc}"}
        tools = config.get("tools", {}) if isinstance(config, dict) else {}
        generated = tools.get("GeneratedTools", []) if isinstance(tools, dict) else []
        enabled_tools = sorted(
            item.get("name")
            for item in generated
            if isinstance(item, dict) and item.get("enabled", True) and isinstance(item.get("name"), str)
        )
        if not enabled_tools:
            return False, {"error": "generated workflow config has no enabled GeneratedTools"}

        required_result_lines = [self.RESULT_LIST_MARKER] + [
            f"[PASS] MCP call {name}" for name in enabled_tools
        ]
        missing_result_lines = [line for line in required_result_lines if line not in result_text]
        missing_server_log_text = [text for text in self.REQUIRED_SERVER_LOG_TEXT if text not in server_log_text]
        missing_registered_tools = [
            name for name in enabled_tools if f"'{name}'" not in server_log_text and f'"{name}"' not in server_log_text
        ]
        call_request_count = server_log_text.count("CallToolRequest")
        completed_call_count = server_log_text.count("exit Stream-MPC mode")
        if (
            missing_result_lines
            or missing_server_log_text
            or missing_registered_tools
            or call_request_count < len(enabled_tools)
            or completed_call_count < len(enabled_tools)
        ):
            return False, {
                "error": "MCP test evidence is incomplete",
                "workflow_root": str(root),
                "enabled_tools": enabled_tools,
                "missing_result_lines": missing_result_lines,
                "missing_server_log_text": missing_server_log_text,
                "missing_registered_tools": missing_registered_tools,
                "call_request_count": call_request_count,
                "completed_call_count": completed_call_count,
            }

        post_check = subprocess.run(
            ["make", "check"],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout or 90,
        )
        result["post_mcp_make_check_returncode"] = post_check.returncode
        result["post_mcp_make_check_stdout"] = post_check.stdout[-5000:]
        result["post_mcp_make_check_stderr"] = post_check.stderr[-5000:]
        if post_check.returncode != 0:
            result["message"] = "MCP test passed but left workflow in a broken state"
            return False, result

        result["message"] = "child UCAgent MCP tool integration test and post-test make check passed"
        result["verified_tools"] = enabled_tools
        return True, result


class WorkflowGeneratedCheckerChecker(WorkflowBuildConfigChecker):
    """Validate a generated business checker and its direct-test loop."""

    def __init__(
        self,
        workflow_root: str,
        checker_name: str = "",
        spec_path: str = "",
        required_test_names: list[str] | None = None,
        run_make_targets: bool = True,
        run_smoke: bool = False,
        **kwargs,
    ):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.checker_name = checker_name
        self.spec_path = spec_path or (f".workflow/checker_specs/{checker_name}.yaml" if checker_name else "")
        self.required_test_names = required_test_names or []
        self.run_make_targets = run_make_targets
        self.run_smoke = run_smoke

    def _workflow_root_from_arg(self) -> Path:
        root_path = Path(self.workflow_root)
        if root_path.is_absolute():
            return root_path.resolve()
        return (self._workspace_root() / root_path).resolve()

    def _run_make(self, root: Path, target: str, timeout: int) -> dict[str, Any]:
        proc = subprocess.run(["make", target], cwd=str(root), text=True, capture_output=True, timeout=timeout)
        return {
            "target": target,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-5000:],
            "stderr": proc.stderr[-5000:],
        }

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate a generated checker through direct tests and optional UCAgent smoke execution."""
        root = self._workflow_root_from_arg()
        spec_rel = self.spec_path
        if not spec_rel:
            specs_dir = root / ".workflow" / "checker_specs"
            if specs_dir.is_dir():
                for sf in sorted(specs_dir.glob("*.yaml")):
                    spec_rel = sf.relative_to(root).as_posix(); break
        if not spec_rel:
            return False, {"error": "no checker spec found"}
        spec_file = root / spec_rel
        try:
            spec = load_yaml_config(spec_file)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "spec_path": str(spec_file)}
        if self.checker_name and spec.get("name") != self.checker_name:
            return False, {"error": "checker spec name mismatch", "actual": spec.get("name")}
        self.checker_name = self.checker_name or spec.get("name", "")
        entry = spec.get("entry", {})
        source_rel = entry.get("file", "")
        source = root / source_rel
        required_files = [
            ".workflow/checkers/checker_spec_checker.py",
            ".workflow/checkers/checker_static_checker.py",
            ".workflow/checkers/checker_direct_runner.py",
            spec_rel,
            source_rel,
        ]
        missing_files = [rel for rel in required_files if not (root / rel).is_file()]
        tests = spec.get("tests", [])
        test_names = [case.get("name") for case in tests if isinstance(case, dict)]
        missing_tests = [name for name in self.required_test_names if name not in test_names]
        if missing_files or missing_tests:
            return False, {
                "error": "generated checker files or tests are missing",
                "missing_files": missing_files,
                "missing_tests": missing_tests,
            }

        source_text = source.read_text(encoding="utf-8")
        missing_source_text = [
            text
            for text in ["from ucagent.checkers.base import Checker", f"class {entry.get('class_name')}(Checker)", "def do_check"]
            if text not in source_text
        ]
        config = load_yaml_config(root / "config.yaml")
        stages = config.get("stage", [])
        registered = any(
            isinstance(item, dict)
            and item.get("name") == self.checker_name
            and source_rel.replace("/", ".").removesuffix(".py") in item.get("clss", "")
            for stage in stages
            if isinstance(stage, dict)
            for item in stage.get("checker", [])
            if isinstance(stage.get("checker", []), list)
        )
        if missing_source_text or not registered:
            return False, {
                "error": "generated checker source or registration is incomplete",
                "missing_source_text": missing_source_text,
                "registered": registered,
            }

        result: dict[str, Any] = {
            "message": "generated checker structure and registration passed",
            "workflow_root": str(root),
            "checker_name": self.checker_name,
        }
        if self.run_make_targets:
            targets = ("check_checker_specs", "check_checkers", "test_checkers", "check")
            make_results = [self._run_make(root, target, timeout or 120) for target in targets]
            result["make_results"] = make_results
            failed = [item for item in make_results if item["returncode"] != 0]
            if failed:
                result["message"] = "generated checker make targets failed"
                result["failed_make_results"] = failed
                return False, result
            result["message"] = "generated checker spec, source, registration, direct tests, and make check passed"
        if self.run_smoke:
            smoke = self._run_make(root, "smoke", timeout or 240)
            result["make_smoke_result"] = smoke
            if smoke["returncode"] != 0:
                result["message"] = "generated checker UCAgent smoke integration failed"
                return False, result
            result["message"] = "generated checker direct tests and UCAgent smoke integration passed"
        return True, result


class WorkflowGeneratedConfigChecker(WorkflowBuildConfigChecker):
    """Validate a generated runtime config and its stage structure."""

    def __init__(self, workflow_root: str, spec_path: str = ".workflow/config_spec.yaml", **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.spec_path = spec_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate generated config syntax, required fields, and spec stage correspondence."""
        root = Path(self.workflow_root)
        root = root.resolve() if root.is_absolute() else (self._workspace_root() / root).resolve()
        try:
            spec = load_yaml_config(root / self.spec_path)
            config = load_yaml_config(root / "config.yaml")
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}
        required = ["workflow", "paths", "model", "loop_settings", "tools", "checkers", "guide_docs", "mission", "stage"]
        missing = [key for key in required if key not in config]
        expected = [item.get("name") for item in spec.get("stages", []) if isinstance(item, dict)]
        actual = [item.get("name") for item in config.get("stage", []) if isinstance(item, dict)]
        short_tasks = []
        if spec.get("mode") in ("default", "inc", "eval"):
            for stage in config.get("stage", []):
                task = stage.get("task", []) if isinstance(stage, dict) else []
                text = "\n".join(value for value in task if isinstance(value, str)) if isinstance(task, list) else str(task)
                length = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text))
                if length < 100:
                    short_tasks.append(f"{stage.get('name', '?')}={length}")
        if missing or expected != actual or short_tasks:
            return False, {
                "error": "generated config mismatch",
                "missing": missing,
                "expected_stages": expected,
                "actual_stages": actual,
                "short_stage_tasks": short_tasks,
            }
        return True, {"message": "generated runtime config passed", "stages": actual}


class WorkflowRuntimeConfigAuditChecker(WorkflowBuildConfigChecker):
    """Audit generated runtime configs for synchronization and reference provenance."""

    CONFIG_CANDIDATES = (
        "config.yaml",
        "config/inc.yaml",
        "inc.yaml",
        "eval.yaml",
        "config/eval.yaml",
    )

    def __init__(self, workflow_root: str, manifest_path: str, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path

    @staticmethod
    def _normalize_path(value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = re.sub(r"/{2,}", "/", normalized)
        return normalized.rstrip("/")

    @classmethod
    def _declared_delivery_paths(cls, manifest: dict[str, Any]) -> set[str]:
        paths: set[str] = set()
        for key in (
            "required_guidedocs",
            "required_user_docs",
            "required_templates",
            "required_configs",
            "required_deliverables",
        ):
            for value in _manifest_item_names(manifest.get(key, [])):
                if isinstance(value, str) and value.strip():
                    paths.add(cls._normalize_path(value))
        return paths

    @classmethod
    def _runtime_input_files(cls, workflow_spec: dict[str, Any]) -> set[str]:
        runtime = workflow_spec.get("runtime_contract", {})
        if not isinstance(runtime, dict):
            return set()
        input_root = cls._normalize_path(str(runtime.get("input_root") or "input"))
        result: set[str] = set()
        required_input = runtime.get("required_input", [])
        if not isinstance(required_input, list):
            return result
        for item in required_input:
            if isinstance(item, str):
                path_text, item_type = item, "file"
            elif isinstance(item, dict):
                path_text = str(item.get("path") or item.get("name") or "")
                item_type = str(item.get("type") or "file")
            else:
                continue
            if not path_text or item_type != "file":
                continue
            path_text = cls._normalize_path(path_text)
            for prefix in ("input/<TARGET>/", "input/{TARGET}/", "input/{DUT}/"):
                if path_text.startswith(prefix):
                    path_text = path_text[len(prefix):]
                    break
            result.add(cls._normalize_path(f"{input_root}/{{DUT}}/{path_text}"))
        return result

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Reject generated configs whose references are not proven fixed deliveries,
        declared input files, or outputs of earlier authoritative stages.
        """
        root = self._resolve(self.workflow_root)
        workspace = self._workspace_root()
        if root != workspace and workspace not in root.parents:
            return False, {
                "error": "workflow_root is outside the checker workspace",
                "workflow_root": str(root),
                "workspace": str(workspace),
            }
        try:
            manifest = load_yaml_config(self._resolve(self.manifest_path))
            workflow_spec = load_yaml_config(root / ".workflow" / "workflow_spec.yaml")
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}

        try:
            try:
                from ..workflow_evaluation_control.static_audit import run_static_audit
            except ImportError:
                from workflow_evaluation_control.static_audit import run_static_audit

            relative_root = "." if root == workspace else root.relative_to(workspace).as_posix()
            audit = run_static_audit(workspace, relative_root)
        except (ImportError, OSError, ValueError) as exc:
            return False, {"error": f"runtime config static audit could not run: {exc}"}

        severe_findings = [
            item
            for item in audit.get("findings", [])
            if item.get("severity") in {"critical", "high"}
        ]
        planned_paths = self._declared_delivery_paths(manifest)
        planned_paths.update({
            ".workflow/workflow_spec.yaml",
            ".workflow/acceptance_rules.yaml",
        })
        runtime_inputs = self._runtime_input_files(workflow_spec)

        authoritative_stages = workflow_spec.get("stages", [])
        authoritative_order: dict[str, int] = {}
        produced_at: dict[str, int] = {}
        if isinstance(authoritative_stages, list):
            for index, stage in enumerate(authoritative_stages):
                if not isinstance(stage, dict):
                    continue
                name = stage.get("name")
                if isinstance(name, str):
                    authoritative_order[name] = index
                outputs = stage.get("output_files", [])
                if isinstance(outputs, list):
                    for output in outputs:
                        if isinstance(output, str):
                            produced_at.setdefault(self._normalize_path(output), index)

        unproven: list[dict[str, Any]] = []
        checked_references = 0
        checked_configs: list[str] = []
        for relative in self.CONFIG_CANDIDATES:
            config_path = root / relative
            if not config_path.is_file():
                continue
            checked_configs.append(relative)
            try:
                config = load_yaml_config(config_path)
            except WorkflowBuildError as exc:
                unproven.append({
                    "config": relative,
                    "error": str(exc),
                })
                continue
            stages = config.get("stage", [])
            if not isinstance(stages, list):
                continue
            for runtime_index, stage in enumerate(stages):
                if not isinstance(stage, dict):
                    continue
                stage_name = str(stage.get("name") or f"stage[{runtime_index}]")
                stage_index = authoritative_order.get(stage_name, runtime_index)
                references = stage.get("reference_files", [])
                if not isinstance(references, list):
                    continue
                for reference in references:
                    if not isinstance(reference, str):
                        continue
                    checked_references += 1
                    normalized = self._normalize_path(reference)
                    producer_index = produced_at.get(normalized)
                    if producer_index is not None and producer_index < stage_index:
                        continue
                    if normalized in runtime_inputs:
                        continue
                    if "{" not in normalized:
                        if normalized in planned_paths or (root / normalized).is_file():
                            continue
                    reason = (
                        "reference has no earlier authoritative producer and is not a "
                        "declared type=file runtime input or fixed delivery file"
                    )
                    if producer_index is not None:
                        reason = (
                            f"reference is first produced at authoritative stage index "
                            f"{producer_index}, not before current index {stage_index}"
                        )
                    unproven.append({
                        "config": relative,
                        "stage": stage_name,
                        "reference": reference,
                        "normalized_reference": normalized,
                        "reason": reason,
                    })

        if severe_findings or unproven:
            return False, {
                "error": "generated runtime config self-audit failed",
                "static_audit_findings": severe_findings,
                "unproven_reference_files": unproven,
                "checked_configs": checked_configs,
                "checked_reference_count": checked_references,
                "suggestion": (
                    "Correct .workflow/workflow_spec.yaml and the matching config spec, "
                    "regenerate every affected config, then rerun this checker."
                ),
            }
        return True, {
            "message": "generated runtime config synchronization and reference provenance passed",
            "checked_configs": checked_configs,
            "checked_reference_count": checked_references,
            "runtime_input_files": sorted(runtime_inputs),
        }


class WorkflowGeneratedGuideDocChecker(WorkflowBuildConfigChecker):
    """Validate generated Guide_Doc and config registration."""

    def __init__(self, workflow_root: str, required_docs: list[str] | None = None, required_headings: list[str] | None = None, manifest_path: str = "", **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path
        self.manifest: dict[str, Any] = {}
        if required_docs is not None:
            self.required_docs = list(required_docs)
        elif manifest_path:
            try:
                manifest = load_yaml_config(self._resolve(manifest_path))
                self.manifest = manifest
                self.required_docs = [
                    (d.get("path") or d.get("file") or d.get("name") or "")
                    if isinstance(d, dict)
                    else d
                    for d in manifest.get("required_guidedocs", [])
                ]
                self.required_docs = [
                    path for path in self.required_docs if isinstance(path, str) and path
                ]
            except Exception:
                self.required_docs = []
        else:
            self.required_docs = []
        self.required_headings = required_headings or []

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate generated GuideDoc files, headings, and config registration."""
        root = Path(self.workflow_root)
        root = root.resolve() if root.is_absolute() else (self._workspace_root() / root).resolve()
        if self.manifest_path and not self.manifest:
            try:
                self.manifest = load_yaml_config(self._resolve(self.manifest_path))
                self.required_docs = [
                    path
                    for path in WorkflowGuideDocSpecChecker._paths(
                        self.manifest.get("required_guidedocs", []),
                        fallback_name=False,
                    )
                    if path
                ]
            except WorkflowBuildError as exc:
                return False, {"error": str(exc), "manifest_path": self.manifest_path}
        config = load_yaml_config(root / "config.yaml")
        registered = config.get("guide_docs", [])
        missing_files = [path for path in self.required_docs if not (root / path).is_file()]
        missing_registered = [path for path in self.required_docs if path not in registered]
        missing_headings = {
            path: [heading for heading in self.required_headings if heading not in (root / path).read_text(encoding="utf-8")]
            for path in self.required_docs
            if (root / path).is_file()
        }
        missing_headings = {path: items for path, items in missing_headings.items() if items}
        coverage_errors = []
        if self.manifest:
            checker = WorkflowGuideDocSpecChecker(self.workflow_root)
            checker.manifest = self.manifest
            coverage_errors = checker._manifest_doc_coverage_errors()
        provenance_errors = _guidedoc_provenance_errors(root)
        if missing_files or missing_registered or missing_headings or coverage_errors or provenance_errors:
            return False, {
                "error": "generated GuideDoc validation failed",
                "missing_files": missing_files,
                "missing_registered": missing_registered,
                "missing_headings": missing_headings,
                "coverage_errors": coverage_errors,
                "stale_generated_documents": provenance_errors,
            }
        return True, {"message": "generated Guide_Doc passed", "docs": self.required_docs}


class WorkflowMigrationPackageChecker(WorkflowBuildConfigChecker):
    """Validate prepared full and partial workflow migration packages."""

    PARTIAL_FORBIDDEN = PARTIAL_FORBIDDEN_PREFIXES
    CLEAN_FORBIDDEN_TOP_LEVEL = FORBIDDEN_TOP_LEVEL
    CLEAN_FORBIDDEN_PARTS = FORBIDDEN_PARTS
    CLEAN_FORBIDDEN_SUFFIXES = FORBIDDEN_SUFFIXES
    PRESERVED_LOG_PREFIXES = PRESERVED_LOG_PREFIXES
    OUTPUT_PLACEHOLDER_NAMES = OUTPUT_PLACEHOLDER_NAMES

    def __init__(self, workflow_root: str, run_deploy_test: bool = True, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.run_deploy_test = run_deploy_test

    @classmethod
    def _allowed_output_placeholders(cls, root: Path) -> set[str]:
        try:
            contract = load_acceptance_contract(root)
        except Exception:
            return set()
        return set(contract.allowed_output_placeholders)

    @classmethod
    def _is_dirty_package_file(
        cls,
        rel: str,
        allowed_output_placeholders: set[str],
    ) -> bool:
        return is_release_runtime_artifact(rel, allowed_output_placeholders)

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate both package manifests, enforce mode boundaries, and optionally test file-level deployment."""
        root = Path(self.workflow_root)
        root = root.resolve() if root.is_absolute() else (self._workspace_root() / root).resolve()
        required = [root / "install.py", root / ".install/README.md", root / ".install/manifest.json"]
        missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
        if missing:
            return False, {"error": "migration infrastructure is incomplete", "missing": missing}
        tmp_root = root / "tmp"
        tmp_dirty = [
            path.relative_to(root).as_posix()
            for path in tmp_root.rglob("*")
        ] if tmp_root.is_dir() else ["tmp/: missing"]
        if tmp_dirty:
            return False, {
                "error": "root tmp directory must be empty before packaging",
                "tmp_artifacts": tmp_dirty[:20],
            }
        runtime_passed, runtime_result = validate_runtime_contract(root)
        if not runtime_passed:
            return False, {
                "error": "source workflow runtime contract failed before migration",
                "runtime_contract": runtime_result,
            }
        try:
            acceptance = load_acceptance_contract(root)
        except ValueError as exc:
            return False, {"error": f"invalid acceptance contract: {exc}"}

        try:
            import json

            manifest = json.loads((root / ".install/manifest.json").read_text(encoding="utf-8"))
        except Exception as exc:
            return False, {"error": f"invalid migration manifest: {exc}"}
        packages = manifest.get("packages", {}) if isinstance(manifest, dict) else {}
        package_directories = manifest.get("package_directories", {}) if isinstance(manifest, dict) else {}
        if not isinstance(packages, dict) or any(mode not in packages for mode in ("full", "partial")):
            return False, {"error": "full and partial migration packages must both be prepared"}
        if not isinstance(package_directories, dict) or any(
            mode not in package_directories for mode in ("full", "partial")
        ):
            return False, {"error": "full and partial migration package directories must both be prepared"}
        full = packages["full"]
        partial = packages["partial"]
        full_directories = package_directories["full"]
        partial_directories = package_directories["partial"]
        if not all(
            isinstance(items, list)
            for items in (full, partial, full_directories, partial_directories)
        ):
            return False, {"error": "migration package file and directory manifests must be lists"}
        forbidden = [
            rel
            for rel in partial
            if has_prefix(rel, self.PARTIAL_FORBIDDEN)
        ]
        forbidden_directories = [
            rel
            for rel in partial_directories
            if has_prefix(rel, self.PARTIAL_FORBIDDEN)
        ]
        package_required_missing = {
            mode: [rel for rel in acceptance.package_files(mode) if rel not in files]
            for mode, files in (("full", full), ("partial", partial))
        }
        package_required_directories_missing = {
            mode: [
                rel
                for rel in acceptance.package_dirs(mode)
                if rel not in directories
            ]
            for mode, directories in (
                ("full", full_directories),
                ("partial", partial_directories),
            )
        }
        missing_package_directories = {
            mode: [
                rel
                for rel in directories
                if not (root / ".install" / "packages" / mode / rel).is_dir()
            ]
            for mode, directories in (
                ("full", full_directories),
                ("partial", partial_directories),
            )
        }
        allowed_output_placeholders = set(acceptance.allowed_output_placeholders)
        dirty = [
            rel
            for rel in set(full + partial)
            if self._is_dirty_package_file(rel, allowed_output_placeholders)
        ]
        if (
            forbidden
            or forbidden_directories
            or any(package_required_missing.values())
            or any(package_required_directories_missing.values())
            or any(missing_package_directories.values())
            or dirty
        ):
            return False, {
                "error": "migration mode boundary or cleanliness check failed",
                "partial_forbidden": forbidden[:10],
                "partial_forbidden_directories": forbidden_directories[:10],
                "package_required_missing": package_required_missing,
                "package_required_directories_missing": package_required_directories_missing,
                "missing_package_directories": missing_package_directories,
                "dirty_files": sorted(dirty)[:20],
            }

        result: dict[str, Any] = {"message": "migration packages passed", "full_files": len(full), "partial_files": len(partial)}
        if self.run_deploy_test:
            with tempfile.TemporaryDirectory(prefix="workflow_migration_check_") as temp:
                for mode in ("full", "partial"):
                    target = Path(temp) / mode
                    proc = subprocess.run(
                        [os.environ.get("PYTHON", "python3"), "install.py", "-o", str(target), "--mode", mode],
                        cwd=root,
                        text=True,
                        capture_output=True,
                        timeout=timeout or 60,
                    )
                    if proc.returncode != 0:
                        return False, {"error": f"{mode} deployment failed", "stdout": proc.stdout, "stderr": proc.stderr}
                if (Path(temp) / "partial/tools").exists() or (Path(temp) / "partial/checkers").exists():
                    return False, {"error": "partial deployment contains tools or checkers"}
                deployed_missing = {
                    mode: [
                        rel
                        for rel in acceptance.package_files(mode)
                        if not (Path(temp) / mode / rel).is_file()
                    ]
                    + [
                        rel + "/"
                        for rel in acceptance.package_dirs(mode)
                        if not (Path(temp) / mode / rel).is_dir()
                    ]
                    for mode in ("full", "partial")
                }
                if any(deployed_missing.values()):
                    return False, {
                        "error": "deployed packages violate acceptance_rules.yaml",
                        "missing": deployed_missing,
                    }
        return True, result


class WorkflowToolGenerationChecker(WorkflowBuildConfigChecker):
    """Check generated tool infrastructure and the workflow-specific tools that are actually declared."""

    def __init__(
        self,
        workflow_root: str,
        manifest_path: str = "",
        required_tools: list[str] | None = None,
        run_make_targets: bool = True,
        **kwargs,
    ):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path
        self.required_tools = required_tools or []
        self.run_make_targets = run_make_targets

    def _workflow_root_from_arg(self) -> Path:
        root_path = Path(self.workflow_root)
        if root_path.is_absolute():
            return root_path.resolve()
        return (self._workspace_root() / root_path).resolve()

    def _contains_all(self, path: Path, needles: list[str]) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [needle for needle in needles if needle not in text]

    def _run_make(self, root: Path, target: str, timeout: int) -> dict[str, Any]:
        proc = subprocess.run(
            ["make", target],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "target": target,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-3000:],
            "stderr": proc.stderr[-3000:],
        }

    @staticmethod
    def _tool_records_from_manifest(manifest: dict[str, Any]) -> list[dict[str, str]]:
        records = []
        for item in manifest.get("required_tools", []):
            if isinstance(item, str):
                name = item
                spec = f".workflow/tool_specs/{name}.yaml"
                tool = f"tools/{name}.py"
            elif isinstance(item, dict):
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    continue
                spec = item.get("spec") or item.get("spec_path") or f".workflow/tool_specs/{name}.yaml"
                tool = item.get("file") or item.get("tool") or item.get("tool_path") or f"tools/{name}.py"
            else:
                continue
            records.append({"name": name, "spec": str(spec), "tool": str(tool)})
        return records

    @staticmethod
    def _tool_records_from_config(config: dict[str, Any]) -> list[dict[str, str]]:
        tools = config.get("tools", {})
        registry = tools.get("GeneratedTools", []) if isinstance(tools, dict) else tools
        records = []
        if isinstance(registry, list):
            for item in registry:
                if not isinstance(item, dict) or item.get("enabled") is False:
                    continue
                name = item.get("name")
                spec = item.get("spec")
                tool = item.get("file")
                if isinstance(name, str) and isinstance(spec, str) and isinstance(tool, str):
                    records.append({"name": name, "spec": spec, "tool": tool})
        return records

    def _expected_tool_records(self, root: Path, config: dict[str, Any]) -> list[dict[str, str]]:
        if self.manifest_path:
            manifest = load_yaml_config(self._resolve(self.manifest_path))
            return self._tool_records_from_manifest(manifest)
        if self.required_tools:
            return [
                {"name": name, "spec": f".workflow/tool_specs/{name}.yaml", "tool": f"tools/{name}.py"}
                for name in self.required_tools
            ]
        return self._tool_records_from_config(config)

    def _config_registers_record(self, config: dict[str, Any], expected: dict[str, str]) -> bool:
        tools = config.get("tools", {})
        registry = tools.get("GeneratedTools", []) if isinstance(tools, dict) else tools
        return isinstance(registry, list) and any(
            isinstance(item, dict)
            and item.get("name") == expected["name"]
            and item.get("spec") == expected["spec"]
            and item.get("file") == expected["tool"]
            and item.get("enabled") is True
            for item in registry
        )

    def _validate_tool_record(self, root: Path, config: dict[str, Any], record: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {"name": record["name"], "ok": True}
        spec_path = root / record["spec"]
        tool_path = root / record["tool"]
        if not spec_path.is_file():
            result.update({"ok": False, "error": "missing spec", "path": record["spec"]})
            return result
        if not tool_path.is_file():
            result.update({"ok": False, "error": "missing tool", "path": record["tool"]})
            return result
        try:
            spec = load_yaml_config(spec_path)
        except WorkflowBuildError as exc:
            result.update({"ok": False, "error": str(exc)})
            return result
        entry = spec.get("entry", {}) if isinstance(spec, dict) else {}
        outputs = spec.get("outputs", {}) if isinstance(spec, dict) else {}
        required_keys = outputs.get("required_keys", []) if isinstance(outputs, dict) else []
        tests = spec.get("tests", []) if isinstance(spec, dict) else []
        expected_spec = {
            "name": record["name"],
            "file": record["tool"],
            "class_name": entry.get("class_name", ""),
            "method": entry.get("method", ""),
        }
        spec_errors = []
        for key, expected in expected_spec.items():
            actual = spec.get(key) if key == "name" else entry.get(key)
            if actual != expected:
                spec_errors.append(f"{key}={expected!r}")
        missing_output_keys = [key for key in ("ok", "data", "errors", "warnings", "meta") if key not in required_keys]
        if not isinstance(tests, list) or not tests:
            spec_errors.append("tests")
        if missing_output_keys:
            spec_errors.append("outputs.required_keys:" + ",".join(missing_output_keys))
        tool_missing = self._contains_all(
            tool_path,
            [
                f"class {entry.get('class_name', '')}",
                record["name"],
                "input_schema",
                "output_schema",
                f"def {entry.get('method', '')}",
            ],
        )
        registered = self._config_registers_record(config, record)
        if spec_errors or tool_missing or not registered:
            result.update(
                {
                    "ok": False,
                    "spec_errors": spec_errors,
                    "tool_missing_text": tool_missing,
                    "registered": registered,
                }
            )
        return result

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate the tool-generation loop without forcing unrelated built-in tools.
        The check verifies checker/runner/MCP infrastructure, Makefile targets, and whichever tools are
        declared by the manifest or already registered in config.yaml.
        """
        root = self._workflow_root_from_arg()
        if not root.is_dir():
            return False, {"error": f"workflow root not found: {root}"}

        required_files = [
            ".workflow/checkers/tool_spec_checker.py",
            ".workflow/checkers/tool_static_checker.py",
            ".workflow/checkers/tool_direct_runner.py",
            ".workflow/tool_tests/run_mcp_tests.py",
            "tools/mcp_adapters.py",
            "Makefile",
            "config.yaml",
        ]
        required_dirs = [
            ".workflow/tool_specs",
            ".workflow/tool_tests",
            ".workflow/tool_tests/cases",
            ".workflow/tool_tests/logs",
        ]
        missing_files = [rel for rel in required_files if not (root / rel).is_file()]
        missing_dirs = [rel for rel in required_dirs if not (root / rel).is_dir()]
        if missing_files or missing_dirs:
            return False, {
                "error": "tool generation files or directories are missing",
                "workflow_root": str(root),
                "missing_files": missing_files,
                "missing_dirs": missing_dirs,
            }

        adapter_text = (root / "tools/mcp_adapters.py").read_text(encoding="utf-8")
        adapter_errors = []
        if "def run(self, tool_input" in adapter_text or '"run": run' in adapter_text or "'run': run" in adapter_text:
            adapter_errors.append(
                "tools/mcp_adapters.py must not override BaseTool.run; implement only _run so LangGraph wraps results as ToolMessage"
            )
        for marker in ["def _run(self, tool_input=None", "json.dumps(result", "python_type = Any"]:
            if marker not in adapter_text:
                adapter_errors.append(f"tools/mcp_adapters.py missing required marker: {marker}")
        if adapter_errors:
            return False, {
                "error": "MCP adapter contract check failed",
                "workflow_root": str(root),
                "adapter_errors": adapter_errors,
            }

        make_missing = self._contains_all(
            root / "Makefile",
            [
                "check_tool_specs:",
                "check_tools:",
                "test_tools:",
                "test_mcp:",
                "check: check_config check_layout check_docs check_tool_specs check_tools test_tools check_checker_specs check_checkers test_checkers",
            ],
        )
        config_path = root / "config.yaml"
        try:
            config = load_yaml_config(config_path)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "config_path": str(config_path)}
        try:
            expected_records = self._expected_tool_records(root, config)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "workflow_root": str(root)}
        record_results = [self._validate_tool_record(root, config, record) for record in expected_records]
        failed_records = [item for item in record_results if not item.get("ok")]
        if make_missing or failed_records:
            return False, {
                "error": "tool generation content check failed",
                "workflow_root": str(root),
                "makefile_missing_text": make_missing,
                "failed_tools": failed_records,
            }

        result: dict[str, Any] = {
            "message": "tool generation loop check passed",
            "workflow_root": str(root),
            "checked_tools": [record["name"] for record in expected_records],
        }
        if self.run_make_targets:
            proc_timeout = timeout or 90
            make_results = [self._run_make(root, target, proc_timeout) for target in ("check_tool_specs", "check_tools", "test_tools", "check")]
            result["make_results"] = make_results
            failed = [item for item in make_results if item["returncode"] != 0]
            if failed:
                result["message"] = "tool generation make targets failed"
                result["failed_make_results"] = failed
                return False, result
        return True, result


class WorkflowGeneratedToolChecker(WorkflowToolGenerationChecker):
    """Check a generated tool from its tool_spec."""

    def __init__(
        self,
        workflow_root: str,
        tool_name: str = "",
        spec_path: str = "",
        tool_selection_file: str = "",
        manifest_path: str = "",
        required_fixture_count: int = 0,
        spec_only: bool = False,
        required_test_names: list[str] | None = None,
        required_data_keys: list[str] | None = None,
        run_make_targets: bool = True,
        **kwargs,
    ):
        super().__init__(workflow_root=workflow_root, run_make_targets=run_make_targets, **kwargs)
        self.tool_name = tool_name
        self.spec_path = spec_path
        self.tool_selection_file = tool_selection_file
        self.manifest_path = manifest_path
        self.required_fixture_count = required_fixture_count
        self.spec_only = spec_only
        self.required_test_names = required_test_names or []
        self.required_data_keys = required_data_keys or []

    @staticmethod
    def _safe_relative_path(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise WorkflowBuildError("GEN-TOOL-CHK-002", f"{field} must be a non-empty relative path")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise WorkflowBuildError("GEN-TOOL-CHK-002", f"unsafe {field}: {value}")
        return path.as_posix()

    @staticmethod
    def _manifest_tool_names(manifest: dict[str, Any]) -> set[str]:
        names = set()
        for item in manifest.get("required_tools", []):
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                names.add(item["name"])
        return names

    @staticmethod
    def _fixture_exists(root: Path, rel_path: str) -> bool:
        target = root / rel_path
        if target.is_file():
            return True
        if target.is_dir():
            return any(item.is_file() for item in target.rglob("*"))
        return False

    def _load_tool_selection(self, root: Path) -> tuple[str, str, list[str]]:
        selection_path = self._resolve(self.tool_selection_file)
        selection = load_yaml_config(selection_path)
        name = selection.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise WorkflowBuildError("GEN-TOOL-CHK-002", f"invalid selected tool name: {name!r}")
        spec_rel = self._safe_relative_path(selection.get("spec_path"), "spec_path")
        expected_spec = f".workflow/tool_specs/{name}.yaml"
        if spec_rel != expected_spec:
            raise WorkflowBuildError(
                "GEN-TOOL-CHK-002",
                f"selected spec_path must be {expected_spec}, got {spec_rel}",
            )
        fixture_values = selection.get("fixture_paths", [])
        if not isinstance(fixture_values, list):
            raise WorkflowBuildError("GEN-TOOL-CHK-002", "fixture_paths must be a list")
        fixtures = [
            self._safe_relative_path(value, f"fixture_paths[{index}]")
            for index, value in enumerate(fixture_values)
        ]
        if len(fixtures) < self.required_fixture_count:
            raise WorkflowBuildError(
                "GEN-TOOL-CHK-002",
                f"selected tool requires at least {self.required_fixture_count} fixture paths",
            )
        missing_fixtures = [
            path for path in fixtures if not self._fixture_exists(root, path)
        ]
        if missing_fixtures:
            raise WorkflowBuildError(
                "GEN-TOOL-CHK-002",
                "selected tool fixtures are missing, or are empty directories: "
                f"{', '.join(missing_fixtures)}",
            )
        if self.manifest_path:
            manifest = load_yaml_config(self._resolve(self.manifest_path))
            required_tools = self._manifest_tool_names(manifest)
            if name not in required_tools:
                raise WorkflowBuildError(
                    "GEN-TOOL-CHK-002",
                    f"selected tool is not declared in requirements manifest: {name}",
                )
        return name, spec_rel, fixtures

    def _resolve_tool_name_and_spec(self, root: Path) -> tuple[str, str, list[str]]:
        if self.tool_selection_file:
            return self._load_tool_selection(root)
        if self.tool_name:
            return self.tool_name, self.spec_path or f".workflow/tool_specs/{self.tool_name}.yaml", []
        if self.spec_path:
            sf = root / self.spec_path
            if sf.is_file():
                s = load_yaml_config(sf)
                return s.get("name", ""), self.spec_path, []
        d = root / ".workflow" / "tool_specs"
        if d.is_dir():
            for sf in sorted(d.glob("*.yaml")):
                s = load_yaml_config(sf)
                n = s.get("name", "")
                if n and n not in {"read_text_file_tool", "write_text_file_tool", "run_command_tool"}:
                    return n, sf.relative_to(root).as_posix(), []
        return "", "", []

    def _load_tool_spec(self, root: Path) -> tuple[Path, dict[str, Any], list[str]]:
        tool_name, spec_rel, fixtures = self._resolve_tool_name_and_spec(root)
        if tool_name:
            self.tool_name = tool_name
        if not spec_rel:
            raise WorkflowBuildError("GEN-TOOL-CHK-001", "no tool spec found")
        spec_path = root / spec_rel
        spec = load_yaml_config(spec_path)
        return spec_path, spec, fixtures

    def _config_registers_tool(self, config: dict[str, Any], expected: dict[str, str]) -> bool:
        tools = config.get("tools", {})
        registry = tools.get("GeneratedTools", []) if isinstance(tools, dict) else tools
        return isinstance(registry, list) and any(
            isinstance(item, dict)
            and item.get("name") == expected["name"]
            and item.get("spec") == expected["spec"]
            and item.get("file") == expected["tool"]
            and item.get("enabled") is True
            for item in registry
        )

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate a generated tool from an arbitrary tool_spec.
        In spec-only mode, this checker validates only the spec and optional spec make target.
        In full mode, it also validates generated code, config registration, direct-run tests, and make check.
        """
        root = self._workflow_root_from_arg()
        if not root.is_dir():
            return False, {"error": f"workflow root not found: {root}"}

        try:
            spec_path, spec, fixtures = self._load_tool_spec(root)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "workflow_root": str(root)}

        if spec.get("name") != self.tool_name:
            return False, {
                "error": "tool_spec name mismatch",
                "expected_tool_name": self.tool_name,
                "actual_tool_name": spec.get("name"),
                "spec_path": str(spec_path),
            }

        entry = spec.get("entry", {})
        outputs = spec.get("outputs", {})
        tests = spec.get("tests", [])
        test_input_values = {
            value
            for case in tests
            if isinstance(case, dict) and isinstance(case.get("input"), dict)
            for value in case["input"].values()
            if isinstance(value, str)
        }
        unreferenced_fixtures = [path for path in fixtures if path not in test_input_values]
        if unreferenced_fixtures:
            return False, {
                "error": "selected fixtures are not referenced by tool spec tests",
                "workflow_root": str(root),
                "tool_name": self.tool_name,
                "unreferenced_fixtures": unreferenced_fixtures,
            }
        spec_rel = spec_path.relative_to(root).as_posix()
        tool_rel = entry.get("file", "")
        expected = {
            "name": self.tool_name,
            "spec": spec_rel,
            "tool": tool_rel,
            "class_name": entry.get("class_name", ""),
            "method": entry.get("method", ""),
            "data_keys": outputs.get("data_required_keys", []) if isinstance(outputs, dict) else [],
            "test_names": [item.get("name") for item in tests if isinstance(item, dict)],
        }
        missing_required_tests = [name for name in self.required_test_names if name not in expected["test_names"]]
        missing_required_data_keys = [key for key in self.required_data_keys if key not in expected["data_keys"]]
        if missing_required_tests or missing_required_data_keys:
            return False, {
                "error": "generated tool spec is missing required tests or data keys",
                "workflow_root": str(root),
                "tool_name": self.tool_name,
                "missing_required_tests": missing_required_tests,
                "missing_required_data_keys": missing_required_data_keys,
            }

        spec_needles = [
            f"name: {expected['name']}",
            f"class_name: {expected['class_name']}",
            f"method: {expected['method']}",
            *[str(name) for name in expected["test_names"] if name],
            *[str(key) for key in expected["data_keys"]],
        ]
        spec_missing = self._contains_all(spec_path, spec_needles)
        if spec_missing:
            return False, {
                "error": "generated tool spec is incomplete",
                "workflow_root": str(root),
                "tool_name": self.tool_name,
                "spec_missing_text": spec_missing,
            }

        result: dict[str, Any] = {
            "message": "generated tool spec check passed" if self.spec_only else "generated tool check passed",
            "workflow_root": str(root),
            "tool_name": self.tool_name,
            "spec_path": spec_rel,
            "fixture_paths": fixtures,
        }

        if self.spec_only:
            if self.run_make_targets:
                make_result = self._run_make(root, "check_tool_specs", timeout or 60)
                result["make_results"] = [make_result]
                if make_result["returncode"] != 0:
                    result["message"] = "generated tool spec make target failed"
                    return False, result
            return True, result

        tool_path = root / tool_rel
        if not tool_path.is_file():
            return False, {
                "error": "generated tool file is missing",
                "workflow_root": str(root),
                "tool_name": self.tool_name,
                "missing_file": tool_rel,
            }
        tool_needles = [
            f"class {expected['class_name']}",
            expected["name"],
            "input_schema",
            "output_schema",
            f"def {expected['method']}",
            *[str(key) for key in expected["data_keys"]],
        ]
        tool_missing = self._contains_all(tool_path, tool_needles)

        try:
            config = load_yaml_config(root / "config.yaml")
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "config_path": str(root / "config.yaml")}
        registered = self._config_registers_tool(config, expected)
        if tool_missing or not registered:
            return False, {
                "error": "generated tool content check failed",
                "workflow_root": str(root),
                "tool_name": self.tool_name,
                "tool_missing_text": tool_missing,
                "registered": registered,
            }

        if self.run_make_targets:
            proc_timeout = timeout or 120
            targets = ("check_tool_specs", "check_tools", "test_tools", "check")
            make_results = [self._run_make(root, target, proc_timeout) for target in targets]
            result["make_results"] = make_results
            failed = [item for item in make_results if item["returncode"] != 0]
            if failed:
                result["message"] = "generated tool make targets failed"
                result["failed_make_results"] = failed
                return False, result
        return True, result


class WorkflowBusinessToolGenerationChecker(WorkflowToolGenerationChecker):
    """Check the first complete business-tool generation flow."""

    BUSINESS_TOOL = {
        "name": "example_business_tool",
        "tool": "tools/example_business_tool.py",
        "spec": ".workflow/tool_specs/example_business_tool.yaml",
        "example": ".workflow/tool_tests/cases/example_business_tool/sample_input.txt",
        "class_name": "AnalyzeDutSourceTool",
        "test_name": "basic_test",
        "data_keys": [
            "status",
            "summary",
            "items",
            "line_count",
            "has_content",
            "has_errors",
        ],
    }

    def __init__(
        self,
        workflow_root: str,
        spec_only: bool = False,
        run_make_targets: bool = True,
        **kwargs,
    ):
        super().__init__(workflow_root=workflow_root, run_make_targets=run_make_targets, **kwargs)
        self.spec_only = spec_only

    def _config_registers_business_tool(self, config: dict[str, Any]) -> bool:
        tools = config.get("tools", {})
        registry = tools.get("GeneratedTools", []) if isinstance(tools, dict) else tools
        expected = self.BUSINESS_TOOL
        return isinstance(registry, list) and any(
            isinstance(item, dict)
            and item.get("name") == expected["name"]
            and item.get("spec") == expected["spec"]
            and item.get("file") == expected["tool"]
            and item.get("enabled") is True
            for item in registry
        )

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Validate the first business tool generation flow.
        In spec-only mode, this checker verifies the tool spec and example input.
        In full mode, it also verifies tool implementation, config registration, direct-run tests, and make check.
        """
        root = self._workflow_root_from_arg()
        if not root.is_dir():
            return False, {"error": f"workflow root not found: {root}"}

        expected = self.BUSINESS_TOOL
        required_files = [expected["spec"], expected["example"]]
        if not self.spec_only:
            required_files.append(expected["tool"])
        missing_files = [rel for rel in required_files if not (root / rel).is_file()]
        if missing_files:
            return False, {
                "error": "business tool generation files are missing",
                "workflow_root": str(root),
                "missing_files": missing_files,
            }

        spec_needles = [
            f"name: {expected['name']}",
            f"class_name: {expected['class_name']}",
            "method: run",
            expected["test_name"],
            expected["example"],
            *expected["data_keys"],
        ]
        spec_missing = self._contains_all(root / expected["spec"], spec_needles)
        if spec_missing:
            return False, {
                "error": "business tool spec is incomplete",
                "workflow_root": str(root),
                "spec_missing_text": spec_missing,
            }

        result: dict[str, Any] = {
            "message": "business tool spec check passed" if self.spec_only else "business tool generation check passed",
            "workflow_root": str(root),
            "business_tool": expected["name"],
        }

        if self.spec_only:
            if self.run_make_targets:
                proc_timeout = timeout or 60
                make_result = self._run_make(root, "check_tool_specs", proc_timeout)
                result["make_results"] = [make_result]
                if make_result["returncode"] != 0:
                    result["message"] = "business tool spec make target failed"
                    return False, result
            return True, result

        tool_needles = [
            f"class {expected['class_name']}",
            f'name = "{expected["name"]}"',
            "input_schema",
            "output_schema",
            "def run",
            *expected["data_keys"],
        ]
        tool_missing = self._contains_all(root / expected["tool"], tool_needles)

        try:
            config = load_yaml_config(root / "config.yaml")
        except WorkflowBuildError as exc:
            return False, {"error": str(exc), "config_path": str(root / "config.yaml")}
        registered = self._config_registers_business_tool(config)
        if tool_missing or not registered:
            return False, {
                "error": "business tool content check failed",
                "workflow_root": str(root),
                "tool_missing_text": tool_missing,
                "registered": registered,
            }

        if self.run_make_targets:
            proc_timeout = timeout or 120
            targets = ("check_tool_specs", "check_tools", "test_tools", "check")
            make_results = [self._run_make(root, target, proc_timeout) for target in targets]
            result["make_results"] = make_results
            failed = [item for item in make_results if item["returncode"] != 0]
            if failed:
                result["message"] = "business tool make targets failed"
                result["failed_make_results"] = failed
                return False, result
        return True, result


def _stage_entries(config: dict[str, Any]) -> list[Any]:
    stages = config.get("stage")
    if isinstance(stages, list):
        return stages
    workflow = config.get("workflow", {})
    nested = workflow.get("stages") if isinstance(workflow, dict) else None
    return nested if isinstance(nested, list) else []


_RUNTIME_SYMBOL_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


def _unknown_runtime_symbols(config: dict[str, Any]) -> list[str]:
    template = config.get("template_overwrite", {})
    declared = set(template) if isinstance(template, dict) else set()
    allowed = {"DUT", "OUT", "Version"} | declared
    errors: list[str] = []

    def walk(value: Any, location: str = "") -> None:
        if isinstance(value, str):
            unknown = sorted(set(_RUNTIME_SYMBOL_RE.findall(value)) - allowed)
            if unknown:
                errors.append(f"{location or '<root>'}: {', '.join(unknown)}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{location}[{index}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key) in {"source", "source_code", "implementation", "code"}:
                    continue
                walk(item, f"{location}.{key}" if location else str(key))

    walk(config)
    return errors


def find_parent_workflow_path_leaks(
    config: dict[str, Any],
    *,
    config_path: str,
    workflow_root_name: str,
) -> list[str]:
    """Report child config paths that still include the parent workflow directory."""
    prefix = re.compile(rf"^\s*(?:\./+)?{re.escape(workflow_root_name)}/")
    leaks: list[str] = []

    def inspect(value: Any, location: str) -> None:
        if isinstance(value, str):
            if prefix.match(value):
                leaks.append(f"{config_path}:{location}: {value}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                inspect(item, f"{location}[{index}]")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                inspect(item, f"{location}.{key}")

    for index, stage in enumerate(_stage_entries(config)):
        if not isinstance(stage, dict):
            continue
        stage_name = stage.get("name") or f"stage[{index}]"
        for field in ("reference_files", "output_files"):
            inspect(stage.get(field, []), f"{stage_name}.{field}")
        inspect(stage.get("checker", []), f"{stage_name}.checker")
    return leaks


def validate_runtime_contract(root: Path) -> tuple[bool, dict[str, Any]]:
    """Validate the generated workflow's runtime contract."""
    errors = []
    result: dict[str, Any] = {}

    # readme checks
    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
    quickstart_path = root / "docs" / "01快速启动.md"
    quickstart = quickstart_path.read_text(encoding="utf-8") if quickstart_path.is_file() else ""
    makefile = (root / "Makefile").read_text(encoding="utf-8") if (root / "Makefile").is_file() else ""
    overview = (root / "Guide_Doc" / "overview.md").read_text(encoding="utf-8") if (root / "Guide_Doc" / "overview.md").is_file() else ""

    missing_readme = []
    for line in ["TARGET=", "input/", "output/", "make check_input", "make check_example", "make run"]:
        if line not in readme:
            missing_readme.append(line)
    missing_quickstart = []
    for line in ["input/example/", "make check", "make check_example", "make run TARGET=example", "output/"]:
        if line not in quickstart:
            missing_quickstart.append(line)
    missing_overview = []
    if "# 使用方法" not in overview:
        missing_overview.append("# 使用方法")
    missing_makefile = []
    for line in [
        "check_target:", "prepare_input:", "prepare_runtime:", "check_input:",
        "check_example:", "run:", "tmux:", "SMOKE_TARGET ?=",
        "make run TARGET=$(TARGET)", "GENERATED_TOOLS_CMD", "--ex-tools", "RUNTIME_DUT :=", "WORKFLOW_WORKSPACE ?=",
    ]:
        if line not in makefile:
            missing_makefile.append(line)
    runtime_input_errors = [
        marker
        for marker in (
            'runtime="$(RUNTIME_DUT)"',
            'touch "$$runtime/__init__.py"',
            '$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET)',
            '--output $(OUT)',
        )
        if marker not in makefile
    ]
    if "$(UCAGENT) ./ $(TARGET)" in makefile:
        runtime_input_errors.append("Makefile still passes './' as UCAgent workspace; use $(WORKFLOW_WORKSPACE)")
    if "input/$(TARGET)/data/__init__.py" in makefile or "missing DUT package" in makefile:
        runtime_input_errors.append("Makefile still couples user input to a DUT Python package")
    test_tools_recipe = ""
    if "test_tools:" in makefile:
        test_tools_recipe = makefile.split("test_tools:", 1)[1].split("\n\n", 1)[0]
    volatile_test_dependencies = [
        marker
        for marker in ("tmp/", "output/")
        if marker in test_tools_recipe
    ]
    target_match = re.search(r"^TARGET[ \t]*\?=[ \t]*(.*)$", makefile, re.MULTILINE)
    bad_target = not target_match or bool(target_match.group(1).strip())

    # config checks
    mode_errors = []
    output_errors = []
    placeholder_errors = []
    parent_scope_leaks = []
    reference_file_errors = []
    stage_file_contract_errors = []
    binary_reference_suffixes = {
        ".bmp", ".gif", ".jpeg", ".jpg", ".pdf", ".png", ".ppt", ".pptx", ".webp", ".zip",
    }
    configs: dict[str, dict[str, Any]] = {}
    for cfg_rel, expected_mode in [("config/inc.yaml", "inc")]:
        p = root / cfg_rel
        if not p.is_file():
            mode_errors.append(f"{cfg_rel}: missing")
            continue
        try:
            cfg = load_yaml_config(p)
        except WorkflowBuildError:
            mode_errors.append(f"{cfg_rel}: invalid yaml")
            continue
        configs[cfg_rel] = cfg
        for stage in _stage_entries(cfg):
            if not isinstance(stage, dict):
                continue
            references = stage.get("reference_files", [])
            outputs = stage.get("output_files", [])
            for field, values in (("reference_files", references), ("output_files", outputs)):
                if not isinstance(values, list):
                    stage_file_contract_errors.append(
                        f"{cfg_rel}:{stage.get('name')}:{field} must be a list"
                    )
                    continue
                for value in values:
                    basename = (
                        Path(value.removeprefix("./").rstrip("/")).name
                        if isinstance(value, str)
                        else ""
                    )
                    if (
                        not isinstance(value, str)
                        or value.endswith("/")
                        or (
                            not Path(basename).suffix
                            and basename not in {"Makefile", "Dockerfile", "requirements"}
                        )
                    ):
                        stage_file_contract_errors.append(
                            f"{cfg_rel}:{stage.get('name')}:{field}:{value}"
                        )
            for reference in references if isinstance(references, list) else []:
                if isinstance(reference, str) and Path(reference).suffix.lower() in binary_reference_suffixes:
                    reference_file_errors.append(f"{cfg_rel}:{stage.get('name')}:{reference}")
        actual_mode = cfg.get("workflow", {}).get("mode") if isinstance(cfg, dict) else None
        if actual_mode != expected_mode:
            mode_errors.append(f"{cfg_rel}: mode={actual_mode}, expected '{expected_mode}'")
        write_dirs = cfg.get("write_dirs", []) if isinstance(cfg, dict) else []
        if write_dirs != ["{OUT}/{DUT}"]:
            output_errors.append(f"{cfg_rel}: write_dirs must be exactly [{{OUT}}/{{DUT}}]")
        text = p.read_text(encoding="utf-8")
        if "{{" in text:
            placeholder_errors.append(f"{cfg_rel}")
        if "{TARGET}" in text:
            placeholder_errors.append(f"{cfg_rel}: unsupported {{TARGET}} placeholder")
        for error in _unknown_runtime_symbols(cfg):
            placeholder_errors.append(f"{cfg_rel}: unknown runtime symbol at {error}")
        for forbidden in ("output/workflow_build", "input/workflow_build", "output/workflow_build"):
            if forbidden in text:
                placeholder_errors.append(f"{cfg_rel}: leaked parent workflow path {forbidden}")

    root_config_errors = []
    root_config_path = root / "config.yaml"
    try:
        root_config = load_yaml_config(root_config_path)
    except WorkflowBuildError:
        root_config_errors.append("config.yaml: missing or invalid yaml")
        root_config = {}
    if root_config:
        if root_config.get("workflow", {}).get("mode") != "default":
            root_config_errors.append("config.yaml: workflow.mode must be default")
        if root_config.get("write_dirs") != ["{OUT}/{DUT}"]:
            root_config_errors.append("config.yaml: write_dirs must be exactly [{OUT}/{DUT}]")
        root_config_text = root_config_path.read_text(encoding="utf-8")
        if "{{" in root_config_text:
            root_config_errors.append("config.yaml: unresolved double-brace placeholder")
        if "{TARGET}" in root_config_text:
            root_config_errors.append("config.yaml: unsupported {TARGET} placeholder")
        for error in _unknown_runtime_symbols(root_config):
            root_config_errors.append(f"config.yaml: unknown runtime symbol at {error}")
        for forbidden in ("output/workflow_build", "input/workflow_build", "output/workflow_build"):
            if forbidden in root_config_text:
                root_config_errors.append(f"config.yaml: leaked parent workflow path {forbidden}")
        template_overwrite = root_config.get("template_overwrite", {})
        root_tools = root_config.get("tools")
        if not isinstance(root_tools, dict):
            root_config_errors.append("config.yaml: tools must be a mapping")
        elif not isinstance(root_tools.get("GeneratedTools", []), list):
            root_config_errors.append("config.yaml: tools.GeneratedTools must be a list")
        if not isinstance(template_overwrite, dict):
            root_config_errors.append("config.yaml: template_overwrite must be a mapping")
        else:
            if template_overwrite.get("INPUT_ROOT") != "input/{DUT}":
                root_config_errors.append("config.yaml: INPUT_ROOT must be input/{DUT}")
            if template_overwrite.get("OUTPUT_ROOT") != "{OUT}/{DUT}":
                root_config_errors.append("config.yaml: OUTPUT_ROOT must be {OUT}/{DUT}")
        for stage in _stage_entries(root_config):
            if not isinstance(stage, dict):
                continue
            for field in ("reference_files", "output_files"):
                values = stage.get(field, [])
                if not isinstance(values, list):
                    stage_file_contract_errors.append(
                        f"config.yaml:{stage.get('name')}:{field} must be a list"
                    )
                    continue
                for value in values:
                    basename = (
                        Path(value.removeprefix("./").rstrip("/")).name
                        if isinstance(value, str)
                        else ""
                    )
                    if (
                        not isinstance(value, str)
                        or value.endswith("/")
                        or (
                            not Path(basename).suffix
                            and basename not in {"Makefile", "Dockerfile", "requirements"}
                        )
                    ):
                        stage_file_contract_errors.append(
                            f"config.yaml:{stage.get('name')}:{field}:{value}"
                        )

    for scan_root in ("checkers", "Guide_Doc"):
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for forbidden in ("output/workflow_build", "input/workflow_build", "output/workflow_build"):
                if forbidden in text:
                    parent_scope_leaks.append(f"{path.relative_to(root)}: {forbidden}")

    acceptance_path = root / ".workflow" / "acceptance_rules.yaml"
    try:
        acceptance = load_yaml_config(acceptance_path)
    except WorkflowBuildError:
        acceptance = {}
    required_example_paths = ["input/README.md", "input/example/README.md"]
    for path in acceptance.get("required_public_files", []):
        if isinstance(path, str) and path.startswith("input/example/"):
            required_example_paths.append(path)
    missing_example_inputs = [path for path in required_example_paths if not (root / path).is_file()]
    example_errors = []
    for path in required_example_paths:
        target = root / path
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            example_errors.append(f"{path}: empty")
        if "Replace this placeholder" in text:
            example_errors.append(f"{path}: placeholder content")
        if target.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except Exception as exc:
                example_errors.append(f"{path}: invalid json: {exc}")
            else:
                if value in ({}, []):
                    example_errors.append(f"{path}: placeholder json")
    standard_path_errors = []
    if not (root / "output").is_dir():
        standard_path_errors.append("output/: missing directory")
    if not (root / "docs").is_dir():
        standard_path_errors.append("docs/: missing directory")
    if not (root / "tmp").is_dir():
        standard_path_errors.append("tmp/: missing required temporary directory")
    if (root / ".workflow/temp").exists():
        standard_path_errors.append(".workflow/temp: temporary files must use root tmp/")
    if (root / "example").exists() or (root / "example").is_symlink():
        standard_path_errors.append("example: root runtime symlink/directory is forbidden")
    if (root / "examples").exists():
        standard_path_errors.append("examples/: obsolete root examples directory is forbidden")
    if (root / "check_example_inputs.py").exists():
        standard_path_errors.append("check_example_inputs.py: root ad-hoc checker script is forbidden")
    for pattern in ("run_checks*.py", "run_checks*.sh", "run_tool_checks*.sh", "_test_*"):
        for path in root.glob(pattern):
            standard_path_errors.append(
                f"{path.name}: root ad-hoc or temporary script must be removed or placed under tmp/"
            )
    for obsolete in ("config/default.yaml", "config/empty.yaml"):
        if (root / obsolete).exists():
            standard_path_errors.append(f"{obsolete}: obsolete duplicate runtime config is forbidden")
    if (root / "Guide_Doc" / "tool_generation_guide.md").exists():
        standard_path_errors.append("Guide_Doc/tool_generation_guide.md: WFB reference doc leaked into child workflow")
    if (root / "Guide_Doc" / "checker_generation_guide.md").exists():
        standard_path_errors.append("Guide_Doc/checker_generation_guide.md: WFB reference doc leaked into child workflow")

    failed = any([
        missing_readme, missing_quickstart, missing_overview, missing_makefile,
        runtime_input_errors, volatile_test_dependencies, bad_target, mode_errors, output_errors, placeholder_errors, root_config_errors,
        reference_file_errors, stage_file_contract_errors, parent_scope_leaks,
        missing_example_inputs, example_errors, standard_path_errors,
    ])
    return not failed, {
        "error": "generated workflow runtime contract is incomplete" if failed else "",
        "missing_readme_text": missing_readme,
        "missing_docs_quickstart_text": missing_quickstart,
        "missing_overview_text": missing_overview,
        "missing_makefile_text": missing_makefile,
        "runtime_input_errors": runtime_input_errors,
        "volatile_test_dependencies": volatile_test_dependencies,
        "bad_default_target": bad_target,
        "config_mode_errors": mode_errors,
        "output_path_errors": output_errors,
        "invalid_placeholder_configs": placeholder_errors,
        "invalid_reference_files": reference_file_errors,
        "invalid_stage_file_contracts": stage_file_contract_errors,
        "parent_scope_leaks": parent_scope_leaks,
        "root_config_errors": root_config_errors,
        "standard_path_errors": standard_path_errors,
        "missing_example_inputs": missing_example_inputs,
        "example_errors": example_errors,
    }


class WorkflowGuideDocSpecChecker(WorkflowBuildConfigChecker):
    """Validate design-time GuideDoc coverage, structure, and source mapping."""

    REQUIRED_SECTION_IDS = REQUIRED_SECTION_IDS
    USAGE_MARKERS = ("TARGET", "input/", "input/example", "output/", "make check_example", "make run")

    def __init__(self, workflow_root: str, required_docs: list[str] | None = None, manifest_path: str = "", **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path
        self.manifest: dict[str, Any] = {}
        if required_docs is not None:
            self.required_docs = list(required_docs)
        elif manifest_path:
            try:
                self.manifest = load_yaml_config(self._resolve(manifest_path))
                self.required_docs = self._paths(self.manifest.get("required_guidedocs", []), fallback_name=False)
            except Exception:
                self.required_docs = []
        else:
            self.required_docs = []

    @staticmethod
    def _paths(items, fallback_name=True):
        if not isinstance(items, list):
            return []
        paths = []
        for item in items:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                p = item.get("path") or item.get("file")
                if not p and fallback_name:
                    p = item.get("name")
                if isinstance(p, str) and p:
                    paths.append(p)
        return paths

    @staticmethod
    def _doc_stage_targets(item: Any) -> set[str]:
        if not isinstance(item, dict):
            return set()
        targets: set[str] = set()
        stage = item.get("stage")
        if isinstance(stage, str) and stage:
            targets.add(stage)
        stages = item.get("stages")
        if isinstance(stages, list):
            targets.update(value for value in stages if isinstance(value, str) and value)
        scope = item.get("scope")
        if isinstance(scope, str) and scope in {"all", "business", "default"}:
            targets.add("*")
        return targets

    def _manifest_doc_coverage_errors(self) -> list[str]:
        if not self.manifest:
            return []
        stage_names = WorkflowRequirementCoverageChecker._names(self.manifest.get("required_stages", []))
        if len(stage_names) < 3:
            return []
        exempt = set(WorkflowRequirementCoverageChecker._names(self.manifest.get("guidedoc_exempt_stages", [])))
        required = [name for name in stage_names if name not in exempt]
        doc_items = self.manifest.get("required_guidedocs", [])
        if not isinstance(doc_items, list):
            return ["required_guidedocs is not a list"]
        covered: set[str] = set()
        stage_specific_covered: set[str] = set()
        stage_specific_count = 0
        for item in doc_items:
            targets = self._doc_stage_targets(item)
            if targets - {"*"}:
                stage_specific_count += 1
                stage_specific_covered.update(targets - {"*"})
            if "*" in targets:
                covered.update(required)
            else:
                covered.update(targets)
        errors = []
        missing = [name for name in required if name not in covered]
        if missing:
            errors.append("missing stage GuideDoc coverage: " + ", ".join(missing))
        if stage_specific_count == 0:
            errors.append("required_guidedocs must include at least one stage-specific document")
        missing_specific = [name for name in required if name not in stage_specific_covered]
        if missing_specific:
            errors.append("missing stage-specific GuideDoc: " + ", ".join(missing_specific))
        generic_paths = {"Guide_Doc/overview.md", "Guide_Doc/operation.md"}
        doc_paths = set(self._paths(doc_items, fallback_name=False))
        if doc_paths and doc_paths.issubset(generic_paths):
            errors.append("required_guidedocs cannot be only overview.md/operation.md")
        return errors

    @staticmethod
    def _developer_spec_design_errors(
        root: Path,
        manifest: dict[str, Any],
        config: dict[str, Any],
        component_texts: dict[str, str],
    ) -> dict[str, Any]:
        """Check component coverage and source mapping without final prose validation."""
        errors: dict[str, Any] = {}
        tools = config.get("tools", {}) if isinstance(config, dict) else {}
        registry = tools.get("GeneratedTools", []) if isinstance(tools, dict) else []
        registered_tools = [
            item.get("name")
            for item in registry
            if isinstance(item, dict)
            and item.get("enabled") is not False
            and isinstance(item.get("name"), str)
        ] if isinstance(registry, list) else []
        source_contracts = WorkflowUserDocsChecker._component_sources(root, config)

        for key, text in component_texts.items():
            names = _manifest_item_names(manifest.get(key, []))
            if key == "required_tools":
                names = list(dict.fromkeys([*names, *registered_tools]))
            else:
                names = list(dict.fromkeys([
                    *names,
                    *source_contracts["required_checkers"].keys(),
                ]))
            failures: dict[str, Any] = {}
            for name in names:
                section = WorkflowUserDocsChecker._component_section(text, name)
                length = _effective_prose_length(section)
                contract = source_contracts.get(key, {}).get(name)
                mapping_errors: list[str] = []
                if not contract:
                    mapping_errors.append(
                        "component is not registered with a real implementation source"
                    )
                else:
                    source_path = root / contract["file"]
                    if not source_path.is_file():
                        mapping_errors.append(
                            f"implementation source is missing: {contract['file']}"
                        )
                    if contract["file"] not in section:
                        mapping_errors.append(
                            f"section does not cite exact implementation path: {contract['file']}"
                        )
                    for marker_name in ("class_name", "method"):
                        marker = contract.get(marker_name, "")
                        if marker and marker not in section:
                            mapping_errors.append(
                                f"section does not cite actual {marker_name}: {marker}"
                            )
                if length < 100 or mapping_errors:
                    failures[name] = {
                        "effective_length": length,
                        "required_design_length": 100,
                        "source_mapping_errors": mapping_errors,
                    }
            if failures:
                errors[key] = failures
        return errors

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate GuideDoc specs for required headings and contract markers."""
        root = Path(self.workflow_root)
        if root.is_absolute():
            root = root.resolve()
        else:
            root = (self._workspace_root() / root).resolve()
        if self.manifest_path and not self.manifest:
            try:
                self.manifest = load_yaml_config(self._resolve(self.manifest_path))
                self.required_docs = self._paths(
                    self.manifest.get("required_guidedocs", []),
                    fallback_name=False,
                )
            except WorkflowBuildError as exc:
                return False, {"error": str(exc), "manifest_path": self.manifest_path}
        specs_dir = root / ".workflow" / "guidedoc_specs"
        if not specs_dir.is_dir():
            return False, {"error": "guidedoc_specs dir not found"}
        specs = []
        for sf in sorted(specs_dir.glob("*.yaml")):
            try:
                s = load_yaml_config(sf)
                specs.append(s)
            except WorkflowBuildError:
                continue
        declared = [sp.get("output", "") for sp in specs if isinstance(sp, dict)]
        required = [d for d in self.required_docs if d not in declared and not (root / d).is_file()]
        if required:
            return False, {"error": "GuideDoc specs do not cover required documents", "missing_outputs": required}
        manifest_coverage_errors = self._manifest_doc_coverage_errors()
        if manifest_coverage_errors:
            return False, {"error": "GuideDoc manifest stage coverage is incomplete", "coverage_errors": manifest_coverage_errors}
        for sp in specs:
            if not isinstance(sp, dict):
                continue
            if sp.get("document_type", "guide_doc") == "user_doc":
                continue
            sections = sp.get("sections", [])
            if not isinstance(sections, list) or not sections:
                return False, {"error": f"spec missing sections: {sp.get('output', '?')}"}
            section_ids = [section_id(sec) for sec in sections if isinstance(sec, dict)]
            for semantic_id in self.REQUIRED_SECTION_IDS:
                if semantic_id not in section_ids:
                    return False, {
                        "error": (
                            f"spec missing semantic section id '{semantic_id}': "
                            f"{sp.get('output', '?')}"
                        )
                    }
            if sp.get("operation_contract", True):
                usage_sections = [
                    sec.get("content", "")
                    for sec in sections
                    if isinstance(sec, dict) and section_id(sec) == "usage"
                ]
                usage_text = " ".join(usage_sections)
                for m in self.USAGE_MARKERS:
                    if m not in usage_text:
                        return False, {"error": f"Usage missing marker '{m}': {sp.get('output', '?')}"}
        user_specs = {
            sp.get("output"): sp
            for sp in specs
            if isinstance(sp, dict)
            and sp.get("document_type", "guide_doc") == "user_doc"
            and isinstance(sp.get("output"), str)
        }
        required_user_docs = list(dict.fromkeys([
            *WorkflowUserDocsChecker.FIXED_DOCS,
            *_manifest_item_names(self.manifest.get("required_user_docs", [])),
        ]))
        missing_user_specs = [path for path in required_user_docs if path not in user_specs]
        rendered_user_docs = {
            output: _render_guidedoc_spec(spec)
            for output, spec in user_specs.items()
        }
        short_user_specs = {
            output: _effective_prose_length(text)
            for output, text in rendered_user_docs.items()
            if output in required_user_docs and _effective_prose_length(text) < 200
        }
        config_path = root / "config.yaml"
        config = load_yaml_config(config_path) if config_path.is_file() else {}
        developer_texts = {
            "required_tools": rendered_user_docs.get("docs/04开发者文档-tools.md", ""),
            "required_checkers": rendered_user_docs.get("docs/05开发者文档-checkers.md", ""),
        }
        developer_spec_errors = self._developer_spec_design_errors(
            root,
            self.manifest,
            config,
            developer_texts,
        )
        if missing_user_specs or short_user_specs or developer_spec_errors:
            return False, {
                "error": "user documentation specs fail pre-generation validation",
                "missing_user_doc_specs": missing_user_specs,
                "short_user_doc_specs": short_user_specs,
                "developer_doc_spec_errors": developer_spec_errors,
                "suggestion": (
                    "Fix .workflow/guidedoc_specs YAML first. Every component needs an "
                    "independent design section and exact implementation path/class/method mapping. "
                    "Final prose length, analysis labels, and verbatim source snippets are checked "
                    "after document generation."
                ),
            }
        return True, {"message": "GuideDoc specs passed", "spec_count": len(specs)}


class WorkflowRequirementCoverageChecker(WorkflowBuildConfigChecker):
    """Validate requirement extraction and final generated-workflow coverage."""

    FIXED_USER_DOCS = (
        "docs/README.md",
        "docs/01快速启动.md",
        "docs/02输入输出.md",
        "docs/03步骤及检查.md",
        "docs/04开发者文档-tools.md",
        "docs/05开发者文档-checkers.md",
    )
    FIXED_CONFIGS = (
        "config.yaml",
        "config/inc.yaml",
    )
    FIXED_MAKE_TARGETS = (
        "help",
        "configure",
        "configure-check",
        "check",
        "check_example",
        "test_tools",
        "test_checkers",
        "test_mcp",
        "plan",
        "run",
        "run_inc",
        "clean",
        "package",
        "check_config",
        "check_inc_config",
    )
    FIXED_DELIVERABLES = (
        "README.md",
        "setup.py",
        "config/environment.schema.yaml",
        "requirements.txt",
        "ucagent_setup.sh",
        "Makefile",
        "install.py",
        ".install/README.md",
        ".install/manifest.json",
        *FIXED_USER_DOCS,
        *FIXED_CONFIGS,
    )
    STRICT_PATH_LISTS = (
        "required_user_docs",
        "required_configs",
        "required_deliverables",
    )
    REQUIRED_LISTS = (
        "required_stages", "required_tools", "required_checkers",
        "required_guidedocs", "required_user_docs", "required_templates", "required_configs",
        "required_make_targets", "required_deliverables",
    )
    EMPTY_ALLOWED_LISTS = {"required_templates"}
    MINIMUM_COUNT_ALIASES = {
        "stages": "required_stages", "tools": "required_tools",
        "checkers": "required_checkers", "guidedocs": "required_guidedocs",
        "user_docs": "required_user_docs",
        "templates": "required_templates", "configs": "required_configs",
        "make_targets": "required_make_targets", "deliverables": "required_deliverables",
    }

    def __init__(self, manifest_path: str, workflow_root: str = "", build_config_path: str = "", mode: str = "manifest", **kwargs):
        super().__init__(build_config_path, **kwargs)
        self.manifest_path = manifest_path
        self.workflow_root = workflow_root
        self.mode = mode

    @staticmethod
    def _names(items):
        if not isinstance(items, list):
            return []
        names = []
        for item in items:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("path")
                if isinstance(name, str) and name:
                    names.append(name)
        return names

    @staticmethod
    def _stage_names(items):
        """Return stable stage identifiers and optional human-facing labels."""
        if not isinstance(items, list):
            return []
        names = []
        for item in items:
            if isinstance(item, str):
                names.append(item)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("name", "label"):
                value = item.get(key)
                if isinstance(value, str) and value and value not in names:
                    names.append(value)
        return names

    @staticmethod
    def _paths(items, fallback_name=True):
        if not isinstance(items, list):
            return []
        paths = []
        for item in items:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                p = item.get("path") or item.get("file")
                if not p and fallback_name:
                    p = item.get("name")
                if isinstance(p, str) and p:
                    paths.append(p)
        return paths

    @staticmethod
    def _missing_paths(root, paths):
        return [p for p in paths if not (root / p).exists()]

    @staticmethod
    def _required_stage_configs(items):
        configs = {}
        if not isinstance(items, list):
            return configs
        for item in items:
            if isinstance(item, str):
                configs.setdefault("config.yaml", []).append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                config = item.get("config", "config.yaml")
                if isinstance(name, str) and name and isinstance(config, str) and config:
                    configs.setdefault(config, []).append(name)
        return configs

    @staticmethod
    def _guidedoc_stage_targets(item: Any) -> set[str]:
        if not isinstance(item, dict):
            return set()
        targets: set[str] = set()
        stage = item.get("stage")
        if isinstance(stage, str) and stage:
            targets.add(stage)
        stages = item.get("stages")
        if isinstance(stages, list):
            targets.update(value for value in stages if isinstance(value, str) and value)
        scope = item.get("scope")
        if isinstance(scope, str) and scope in {"all", "business", "default"}:
            targets.add("*")
        return targets

    def _validate_guidedoc_manifest_coverage(self, manifest: dict[str, Any]) -> dict[str, Any]:
        stage_names = self._names(manifest.get("required_stages", []))
        doc_items = manifest.get("required_guidedocs", [])
        if len(stage_names) < 3:
            return {}
        if not isinstance(doc_items, list):
            return {
                "doc_metadata_errors": ["required_guidedocs must be a list"],
                "missing_stage_specific_guidedocs": stage_names,
            }
        exempt = set(self._names(manifest.get("guidedoc_exempt_stages", [])))
        required_stages = [name for name in stage_names if name not in exempt]
        stage_specific_covered: set[str] = set()
        metadata_errors = []
        for index, item in enumerate(doc_items):
            if not isinstance(item, dict):
                metadata_errors.append(f"required_guidedocs[{index}] must be a mapping with path and stage/stages/scope")
                continue
            path = item.get("path") or item.get("file")
            if not isinstance(path, str) or not path:
                metadata_errors.append(f"required_guidedocs[{index}] missing path")
            targets = self._guidedoc_stage_targets(item)
            if not targets and item.get("scope") != "environment":
                metadata_errors.append(f"required_guidedocs[{index}] missing stage/stages/scope")
            if targets - {"*"}:
                stage_specific_covered.update(targets - {"*"})
        return {
            "doc_metadata_errors": metadata_errors,
            "missing_stage_specific_guidedocs": [
                name for name in required_stages if name not in stage_specific_covered
            ],
        }

    def _validate_required_stage_configs(self, manifest: dict[str, Any]) -> list[str]:
        """Require every planned stage to name its concrete runtime config."""
        items = manifest.get("required_stages", [])
        if not isinstance(items, list):
            return ["required_stages must be a list"]
        declared_configs = set(
            self._paths(manifest.get("required_configs", []), fallback_name=False)
        )
        errors: list[str] = []
        for index, item in enumerate(items):
            location = f"required_stages[{index}]"
            if not isinstance(item, dict):
                errors.append(
                    f"{location} must be a mapping with name, label, and config"
                )
                continue
            name = item.get("name")
            label = item.get("label")
            config = item.get("config")
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{location}.name must be a non-empty string")
            if not isinstance(label, str) or not label.strip():
                errors.append(f"{location}.label must be a non-empty string")
            if not isinstance(config, str) or not config.strip():
                errors.append(
                    f"{location}.config must name the concrete runtime config"
                )
                continue
            config_path = Path(config)
            if (
                config_path.is_absolute()
                or ".." in config_path.parts
                or config_path.suffix.lower() not in {".yaml", ".yml"}
            ):
                errors.append(
                    f"{location}.config must be a safe relative YAML file path: {config}"
                )
            elif config not in declared_configs:
                errors.append(
                    f"{location}.config is not declared in required_configs: {config}"
                )
        return errors

    def _load_manifest(self):
        p = self._resolve(self.manifest_path)
        return p, load_yaml_config(p)

    def _validate_manifest(self, manifest):
        missing_keys = [k for k in self.REQUIRED_LISTS if k not in manifest]
        empty_lists = [
            key
            for key in self.REQUIRED_LISTS
            if key not in self.EMPTY_ALLOWED_LISTS and not self._names(manifest.get(key))
        ]
        sr = manifest.get("source_requirement")
        source_missing = not isinstance(sr, str) or not sr or not self._resolve(sr).is_file()
        sections = self._names(manifest.get("requirement_sections"))
        coverage = manifest.get("section_coverage", {})
        uncovered = [sec for sec in sections if not isinstance(coverage, dict) or not isinstance(coverage.get(sec), list) or not coverage.get(sec)]
        metadata_missing = []
        if source_missing:
            metadata_missing.append("source_requirement")
        if not sections:
            metadata_missing.append("requirement_sections")
        if not isinstance(coverage, dict):
            metadata_missing.append("section_coverage")
        minimums = manifest.get("minimum_counts", {})
        if "minimum_counts" not in manifest or not isinstance(minimums, dict):
            metadata_missing.append("minimum_counts")
        dependency_errors = []
        for key in ("required_python_dependencies", "required_system_dependencies"):
            if key not in manifest or not isinstance(manifest.get(key), list):
                dependency_errors.append(f"{key} must be a list")
        stdlib_dependencies = []
        stdlib_names = {name.casefold() for name in getattr(sys, "stdlib_module_names", set())}
        for item in manifest.get("required_python_dependencies", []):
            name = (
                item.get("package") or item.get("name")
                if isinstance(item, dict)
                else item
            )
            if isinstance(name, str) and name.casefold() in stdlib_names:
                stdlib_dependencies.append(name)
        if stdlib_dependencies:
            dependency_errors.append(
                "required_python_dependencies contains Python standard-library modules: "
                + ", ".join(stdlib_dependencies)
            )
        count_failures = {}
        if isinstance(minimums, dict):
            for key, expected in minimums.items():
                list_key = self.MINIMUM_COUNT_ALIASES.get(key, key)
                if list_key in self.REQUIRED_LISTS and isinstance(expected, int):
                    actual = len(self._names(manifest.get(list_key)))
                    if actual < expected:
                        count_failures[key] = {"list": list_key, "expected_at_least": expected, "actual": actual}
        fixed_contracts = {
            "required_user_docs": self.FIXED_USER_DOCS,
            "required_configs": self.FIXED_CONFIGS,
            "required_make_targets": self.FIXED_MAKE_TARGETS,
            "required_deliverables": self.FIXED_DELIVERABLES,
        }
        fixed_contract_errors = {}
        for key, required in fixed_contracts.items():
            if key in self.STRICT_PATH_LISTS:
                actual = set(self._paths(manifest.get(key, []), fallback_name=False))
            else:
                actual = set(self._names(manifest.get(key, [])))
            missing = [value for value in required if value not in actual]
            if missing:
                fixed_contract_errors[key] = {"missing": missing}

        item_shape_errors = {}
        for key in self.STRICT_PATH_LISTS:
            items = manifest.get(key, [])
            invalid = [
                index
                for index, item in enumerate(items if isinstance(items, list) else [])
                if not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].strip()
            ]
            if invalid:
                item_shape_errors[key] = {
                    "invalid_indexes": invalid,
                    "required_shape": {"path": "relative/file/path"},
                }

        strict_paths = [
            path
            for key in self.STRICT_PATH_LISTS
            for path in self._paths(manifest.get(key, []), fallback_name=False)
        ]
        forbidden_user_docs = [
            path for path in strict_paths
            if Path(path).name.casefold() == "quickstart.md"
        ]
        minimum_count_floors = {
            "user_docs": len(self.FIXED_USER_DOCS),
            "configs": len(self.FIXED_CONFIGS),
            "make_targets": len(self.FIXED_MAKE_TARGETS),
            "deliverables": len(self.FIXED_DELIVERABLES),
        }
        understated_minimums = {
            key: {"required_at_least": floor, "declared": minimums.get(key)}
            for key, floor in minimum_count_floors.items()
            if not isinstance(minimums, dict)
            or not isinstance(minimums.get(key), int)
            or minimums[key] < floor
        }
        guidedoc_coverage = self._validate_guidedoc_manifest_coverage(manifest)
        required_stage_config_errors = self._validate_required_stage_configs(manifest)
        return {
            "missing_keys": missing_keys, "empty_lists": empty_lists,
            "metadata_missing": metadata_missing, "uncovered_sections": uncovered,
            "count_failures": count_failures,
            "fixed_contract_errors": fixed_contract_errors,
            "item_shape_errors": item_shape_errors,
            "forbidden_user_docs": forbidden_user_docs,
            "understated_minimums": understated_minimums,
            "guidedoc_coverage": {key: value for key, value in guidedoc_coverage.items() if value},
            "required_stage_config_errors": required_stage_config_errors,
            "dependency_errors": dependency_errors,
        }

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate manifest completeness, build-plan coverage, or final workflow coverage."""
        try:
            manifest_path, manifest = self._load_manifest()
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}
        problems = self._validate_manifest(manifest)
        if any(problems.values()):
            return False, {"error": "requirements manifest is incomplete", **problems}
        if self.mode == "manifest":
            return True, {"message": "requirements manifest passed", "manifest_path": str(manifest_path),
                "counts": {k: len(self._names(manifest[k])) for k in self.REQUIRED_LISTS}}
        required_stages = self._names(manifest["required_stages"])
        required_docs = self._paths(manifest["required_guidedocs"])
        required_user_docs = self._paths(manifest["required_user_docs"])
        # These are user-facing reusable template file paths, not WorkflowBuilder
        # renderer identifiers from files.*[].template.
        required_templates = self._paths(manifest["required_templates"])
        required_configs = self._paths(manifest["required_configs"])
        required_deliverables = self._paths(manifest["required_deliverables"], fallback_name=False)
        if self.mode == "build":
            try:
                build = load_yaml_config(self._resolve(self.build_config_path))
            except WorkflowBuildError as exc:
                return False, {"error": str(exc)}
            build_stages = self._stage_names(build.get("workflow_spec", {}).get("stages", []))
            planned_checker_names = self._names(build.get("workflow_spec", {}).get("checkers", []))
            required_checker_names = self._names(manifest["required_checkers"])
            declared_files = [item.get("path") for group in ("public", "internal") for item in build.get("files", {}).get(group, []) if isinstance(item, dict) and isinstance(item.get("path"), str)]
            declared_dirs = [p for group in ("public", "internal") for p in build.get("directories", {}).get(group, []) if isinstance(p, str)]
            declared_paths = {p.rstrip("/") for p in declared_files + declared_dirs}
            wf_name = str(build.get("workflow", {}).get("name", "")).rstrip("/")
            root_name = Path(str(build.get("root", {}).get("path", ""))).name.rstrip("/")
            root_deliverables = {n for n in (wf_name, root_name) if n}
            required_paths = required_docs + required_user_docs + required_templates + required_configs
            normalized = []
            for p in required_deliverables:
                n = p.rstrip("/")
                for rp in root_deliverables:
                    if n.startswith(f"{rp}/"):
                        n = n[len(rp) + 1:]; break
                normalized.append(n)
            required_paths += normalized
            missing_stages = [n for n in required_stages if n not in build_stages]
            missing_p = [p for p in required_paths if p.rstrip("/") not in declared_paths and p.rstrip("/") not in root_deliverables]
            checker_plan_mismatch = {
                "missing": sorted(set(required_checker_names) - set(planned_checker_names)),
                "unexpected": sorted(set(planned_checker_names) - set(required_checker_names)),
            }
            forbidden_build_paths = [
                path
                for path in declared_files
                if Path(path).name.casefold() == "quickstart.md"
            ]
            if (
                missing_stages
                or missing_p
                or any(checker_plan_mismatch.values())
                or forbidden_build_paths
            ):
                return False, {
                    "error": "workflow build plan does not cover requirements",
                    "missing_stages": missing_stages,
                    "missing_declared_paths": missing_p,
                    "checker_plan_mismatch": checker_plan_mismatch,
                    "forbidden_quickstart_paths": forbidden_build_paths,
                }
            return True, {"message": "workflow build plan covers requirements", "stages": len(required_stages)}
        if self.mode != "final":
            return False, {"error": f"unknown mode: {self.mode}"}
        root = self._resolve(self.workflow_root)
        if not root.is_dir():
            return False, {"error": f"workflow root not found: {root}"}
        forbidden_final_paths = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name.casefold() == "quickstart.md"
        ]
        if forbidden_final_paths:
            return False, {
                "error": "generated workflow contains cancelled quickstart.md",
                "forbidden_quickstart_paths": forbidden_final_paths,
            }
        normalized_deliverables = []
        for p in required_deliverables:
            n = p.rstrip("/")
            prefix = f"{root.name}/"
            if n.startswith(prefix):
                n = n[len(prefix):]
            normalized_deliverables.append(n)
        required_deliverables = normalized_deliverables
        required_stage_configs = self._required_stage_configs(manifest["required_stages"])
        configs_by_path = {}
        config_load_errors = []
        for rel in required_stage_configs:
            try:
                configs_by_path[rel] = load_yaml_config(root / rel)
            except WorkflowBuildError as exc:
                config_load_errors.append(str(exc))
        stages_by_path = {rel: _stage_entries(cfg) for rel, cfg in configs_by_path.items()}
        workflow_spec_contract_errors = []
        try:
            workflow_spec = load_yaml_config(root / ".workflow/workflow_spec.yaml")
            for error in _unknown_runtime_symbols(workflow_spec):
                workflow_spec_contract_errors.append(
                    f".workflow/workflow_spec.yaml: unknown runtime symbol at {error}"
                )
            central = {
                item["name"]: item
                for item in workflow_spec.get("checkers", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            planned_stages = {
                item["name"]: item
                for item in workflow_spec.get("stages", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            for rel, stages in stages_by_path.items():
                for stage in stages:
                    name = stage.get("name") if isinstance(stage, dict) else None
                    if name not in planned_stages:
                        workflow_spec_contract_errors.append(f"{rel}:{name}: stage is not planned")
                        continue
                    planned = planned_stages[name]
                    for key in ("reference_files", "output_files"):
                        if stage.get(key, []) != planned.get(key, []):
                            workflow_spec_contract_errors.append(f"{rel}:{name}.{key}: differs from workflow_spec")
                    expected_checkers = []
                    for binding in planned.get("checker", []):
                        checker_def = central.get(binding.get("name"), {})
                        entry = checker_def.get("entry", {}) if isinstance(checker_def, dict) else {}
                        if not entry:
                            workflow_spec_contract_errors.append(
                                f"{rel}:{name}: unknown planned checker {binding.get('name')}"
                            )
                            continue
                        module = Path(entry["file"]).with_suffix("").as_posix().replace("/", ".")
                        expected_checkers.append(
                            {
                                "name": binding["name"],
                                "clss": f"{module}.{entry['class_name']}",
                                "args": binding.get("args", {}),
                            }
                        )
                    if stage.get("checker", []) != expected_checkers:
                        workflow_spec_contract_errors.append(f"{rel}:{name}.checker: differs from workflow_spec")
        except WorkflowBuildError as exc:
            workflow_spec_contract_errors.append(str(exc))
        runtime_config_paths = {
            "config.yaml",
            "config/inc.yaml",
            *(
                path
                for path in required_configs
                if Path(path).suffix.lower() in {".yaml", ".yml"}
            ),
        }
        parent_workflow_path_leaks = []
        for rel in sorted(runtime_config_paths):
            path = root / rel
            if not path.is_file():
                continue
            try:
                runtime_config = load_yaml_config(path)
            except WorkflowBuildError:
                continue
            parent_workflow_path_leaks.extend(
                find_parent_workflow_path_leaks(
                    runtime_config,
                    config_path=rel,
                    workflow_root_name=root.name,
                )
            )
        missing_stages = [f"{rel}:{name}" for rel, names in required_stage_configs.items() for name in names if name not in self._names(stages_by_path.get(rel, []))]
        exempt = set(self._names(manifest.get("checker_exempt_stages", [])))
        stages_without_checker = [f"{rel}:{s.get('name')}" for rel, stages in stages_by_path.items() for s in stages if isinstance(s, dict) and s.get("name") in required_stage_configs.get(rel, []) and s.get("name") not in exempt and not s.get("checker")]
        tool_names = {p.stem for p in (root / ".workflow" / "tool_specs").glob("*.yaml")}
        checker_specs: dict[str, dict[str, Any]] = {}
        checker_spec_errors: list[str] = []
        for path in (root / ".workflow" / "checker_specs").glob("*.yaml"):
            try:
                checker_spec = load_yaml_config(path)
            except WorkflowBuildError as exc:
                checker_spec_errors.append(str(exc))
                continue
            checker_name = checker_spec.get("name")
            if not isinstance(checker_name, str) or not checker_name:
                checker_spec_errors.append(f"checker spec missing name: {path}")
                continue
            checker_specs[checker_name] = checker_spec
        checker_names = set(checker_specs)
        missing_tools = [n for n in self._names(manifest["required_tools"]) if n not in tool_names]
        missing_checkers = [n for n in self._names(manifest["required_checkers"]) if n not in checker_names]
        missing_checker_implementations = []
        for name in self._names(manifest["required_checkers"]):
            spec = checker_specs.get(name, {})
            entry = spec.get("entry", {}) if isinstance(spec, dict) else {}
            rel = entry.get("file") if isinstance(entry, dict) else None
            if not isinstance(rel, str) or not (root / rel).is_file():
                missing_checker_implementations.append(f"{name}:{rel or '<missing entry.file>'}")
        missing_paths = self._missing_paths(
            root,
            required_docs + required_user_docs + required_templates + required_configs + required_deliverables,
        )
        incomplete_guidedocs = []
        guidedoc_stage_coverage = {
            key: value
            for key, value in self._validate_guidedoc_manifest_coverage(manifest).items()
            if value
        }
        guidedoc_markers = ("input/<TARGET>/", "input/example", "output/", "make check_example", "make run")
        guidedoc_specs_by_output: dict[str, dict[str, Any]] = {}
        for spec_path in (root / ".workflow" / "guidedoc_specs").glob("*.yaml"):
            try:
                spec = load_yaml_config(spec_path)
            except WorkflowBuildError:
                continue
            output = spec.get("output") if isinstance(spec, dict) else None
            if isinstance(output, str):
                guidedoc_specs_by_output[output] = spec
        doc_metadata = {
            item.get("path") or item.get("file"): item
            for item in manifest.get("required_guidedocs", [])
            if isinstance(item, dict)
        }
        for rel in required_docs:
            p = root / rel
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
            spec = guidedoc_specs_by_output.get(rel, {})
            sections = spec.get("sections", []) if isinstance(spec, dict) else []
            by_id = {
                section_id(section): section.get("heading", "")
                for section in sections
                if isinstance(section, dict) and section_id(section)
            }
            missing_parts = [
                f"section:{semantic_id}"
                for semantic_id in REQUIRED_SECTION_IDS
                if semantic_id not in by_id or f"## {by_id[semantic_id]}" not in text
            ]
            if doc_metadata.get(rel, {}).get("operation_contract", True):
                missing_parts.extend(f"usage:{m}" for m in guidedoc_markers if m not in text)
            if missing_parts:
                incomplete_guidedocs.append(f"{rel}: {', '.join(missing_parts)}")
        makefile_text = (root / "Makefile").read_text(encoding="utf-8") if (root / "Makefile").is_file() else ""
        missing_targets = [n for n in self._names(manifest["required_make_targets"]) if f"{n}:" not in makefile_text]
        runtime_passed, runtime_result = validate_runtime_contract(root)
        user_docs_checker = WorkflowUserDocsChecker(
            workflow_root=str(root),
            manifest_path=str(manifest_path),
        )
        user_docs_checker.workspace = self.workspace
        user_docs_passed, user_docs_result = user_docs_checker.do_check(timeout=timeout)
        dependency_checker = WorkflowDependencyChecker(
            workflow_root=str(root),
            manifest_path=str(manifest_path),
        )
        dependency_checker.workspace = self.workspace
        dependency_passed, dependency_result = dependency_checker.do_check(timeout=timeout)
        implementation_plan_checker = WorkflowImplementationPlanChecker(
            plan_path=str(manifest_path.parent / "workflow_implementation_plan.md"),
            manifest_path=str(manifest_path),
        )
        implementation_plan_checker.workspace = self.workspace
        implementation_plan_passed, implementation_plan_result = implementation_plan_checker.do_check(timeout=timeout)
        environment_checker = WorkflowEnvironmentSetupChecker(
            workflow_root=str(root),
            run_test=True,
        )
        environment_checker.workspace = self.workspace
        environment_passed, environment_result = environment_checker.do_check(timeout=timeout)
        milestones = manifest.get("milestones", {})
        incomplete_milestones = [
            name
            for name in ("smoke_ready", "feature_complete", "release_ready")
            if not isinstance(milestones, dict) or milestones.get(name) is not True
        ]
        failures = {
            "missing_stages": missing_stages, "config_load_errors": config_load_errors,
            "parent_workflow_path_leaks": parent_workflow_path_leaks,
            "workflow_spec_contract_errors": workflow_spec_contract_errors,
            "stages_without_checker": stages_without_checker, "missing_tools": missing_tools,
            "missing_checkers": missing_checkers,
            "checker_spec_errors": checker_spec_errors,
            "missing_checker_implementations": missing_checker_implementations,
            "missing_paths": missing_paths,
            "incomplete_guidedocs": incomplete_guidedocs, "missing_make_targets": missing_targets,
            "guidedoc_stage_coverage": guidedoc_stage_coverage,
            "incomplete_milestones": incomplete_milestones,
            "runtime_contract_errors": [] if runtime_passed else [runtime_result],
            "user_documentation_errors": [] if user_docs_passed else [user_docs_result],
            "dependency_errors": [] if dependency_passed else [dependency_result],
            "implementation_plan_errors": [] if implementation_plan_passed else [implementation_plan_result],
            "environment_setup_errors": [] if environment_passed else [environment_result],
        }
        if any(failures.values()):
            return False, {"error": "final workflow does not cover requirements", **failures}
        return True, {"message": "final workflow requirement coverage passed", "stage_count": len(required_stages), "tool_count": len(tool_names), "checker_count": len(checker_names), "document_count": len(required_docs) + len(required_user_docs), "template_count": len(required_templates)}


def _effective_prose_length(text: str) -> int:
    """Count prose characters while excluding fenced code and Markdown formatting."""
    without_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    without_inline = re.sub(r"`[^`]*`", "", without_code)
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9]", without_inline))


def _manifest_item_names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            value = item.get("name") or item.get("path")
            if isinstance(value, str) and value:
                result.append(value)
    return result


class WorkflowImplementationPlanChecker(WorkflowBuildConfigChecker):
    """Cross-check the initial implementation plan against the requirements manifest."""

    REQUIRED_HEADINGS = (
        "工作流概述",
        "输入输出契约",
        "阶段设计",
        "工具设计",
        "Checker设计",
        "GuideDoc设计",
        "用户文档设计",
        "环境配置设计",
        "运行模式与依赖",
    )
    MARKER_ALIASES = {
        "目的": ("目的", "目标"),
        "输入": ("输入",),
        "输出": ("输出", "产物"),
        "作用": ("作用", "职责", "用途", "功能"),
        "检查内容": ("检查内容", "检查对象", "检查项", "验证内容", "校验内容"),
        "失败": ("失败", "异常", "错误处理"),
    }

    def __init__(self, plan_path: str, manifest_path: str, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.plan_path = plan_path
        self.manifest_path = manifest_path

    @staticmethod
    def _named_section(text: str, name: str) -> str:
        pattern = re.compile(
            rf"^#{{3,6}}\s+[^\n]*{re.escape(name)}[^\n]*\n"
            rf"(.*?)(?=^#{{2,6}}\s+|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1) if match else ""

    def _detail_errors(self, text: str, manifest: dict[str, Any]) -> dict[str, Any]:
        business_tools = _manifest_item_names(manifest.get("required_tools", []))
        tools = list(
            dict.fromkeys(
                [
                    *business_tools,
                    "run_command_tool",
                ]
            )
        )
        checkers = _manifest_item_names(manifest.get("required_checkers", []))
        stage_errors = {}
        for stage in _manifest_item_names(manifest.get("required_stages", [])):
            section = self._named_section(text, stage)
            errors = []
            if _effective_prose_length(section) < 200:
                errors.append("stage design needs at least 200 effective prose characters")
            if business_tools and not any(name in section for name in business_tools):
                errors.append("stage design does not bind a declared tool")
            if checkers and not any(name in section for name in checkers):
                errors.append("stage design does not bind a declared Checker")
            for marker in ("目的", "输入", "输出", "失败"):
                if marker not in section:
                    errors.append(f"stage design missing {marker}")
            if errors:
                stage_errors[stage] = errors

        tool_errors = {}
        for name in tools:
            section = self._named_section(text, name)
            errors = []
            if _effective_prose_length(section) < 300:
                errors.append("tool design needs at least 300 effective prose characters")
            for marker, aliases in {
                "作用": ("作用", "职责"),
                "使用阶段": ("使用阶段", "绑定阶段"),
                "输入": ("输入", "参数"),
                "输出": ("输出", "返回"),
                "失败": ("失败", "错误"),
                "实现入口": ("实现文件", "入口类", "入口函数"),
                "调用链": ("调用链", "调用路径", "执行流程"),
                "核心逻辑": ("核心逻辑", "关键代码", "算法"),
                "测试": ("测试", "fixture", "回归"),
                "扩展点": ("扩展点", "调整方式", "可配置"),
            }.items():
                if not any(alias in section for alias in aliases):
                    errors.append(f"tool design missing {marker}")
            if errors:
                tool_errors[name] = errors

        checker_errors = {}
        for name in checkers:
            section = self._named_section(text, name)
            errors = []
            if _effective_prose_length(section) < 300:
                errors.append("Checker design needs at least 300 effective prose characters")
            for marker, aliases in {
                "使用阶段": ("使用阶段", "绑定阶段"),
                "检查对象": ("检查对象",),
                "检查内容": ("检查内容", "验证内容", "结构化字段", "证据字段"),
                "通过条件": ("通过条件",),
                "失败条件": ("失败条件",),
                "实现入口": ("实现文件", "入口类", "do_check"),
                "关键分支": ("关键分支", "判定流程", "检查流程"),
                "异常": ("异常", "错误处理", "失败传播"),
                "测试": ("测试", "fixture", "回归"),
                "扩展点": ("扩展点", "调整方式", "可配置"),
            }.items():
                if not any(alias in section for alias in aliases):
                    errors.append(f"Checker design missing {marker}")
            if errors:
                checker_errors[name] = errors
        return {
            "stage_detail_errors": stage_errors,
            "tool_detail_errors": tool_errors,
            "checker_detail_errors": checker_errors,
        }

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate implementation-plan sections and manifest component coverage."""
        plan_path = self._resolve(self.plan_path)
        manifest_path = self._resolve(self.manifest_path)
        if not plan_path.is_file() or not manifest_path.is_file():
            return False, {
                "error": "implementation plan or requirements manifest is missing",
                "plan_path": str(plan_path),
                "manifest_path": str(manifest_path),
            }
        try:
            manifest = load_yaml_config(manifest_path)
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}
        text = plan_path.read_text(encoding="utf-8")
        compact_text = re.sub(r"\s+", "", text)
        missing_headings = [
            heading for heading in self.REQUIRED_HEADINGS
            if re.sub(r"\s+", "", heading) not in compact_text
        ]
        groups = {
            key: _manifest_item_names(manifest.get(key, []))
            for key in (
                "required_stages",
                "required_tools",
                "required_checkers",
                "required_guidedocs",
                "required_user_docs",
            )
        }
        missing_items = {
            key: [name for name in names if name not in text]
            for key, names in groups.items()
        }
        missing_items = {key: value for key, value in missing_items.items() if value}
        missing_markers = [
            marker for marker, aliases in self.MARKER_ALIASES.items()
            if not any(alias in text for alias in aliases)
        ]
        detail_errors = {
            key: value
            for key, value in self._detail_errors(text, manifest).items()
            if value
        }
        if (
            missing_headings
            or missing_items
            or missing_markers
            or detail_errors
            or _effective_prose_length(text) < 1000
        ):
            return False, {
                "error": "workflow implementation plan is incomplete",
                "missing_headings": missing_headings,
                "missing_items": missing_items,
                "missing_markers": missing_markers,
                **detail_errors,
                "effective_prose_characters": _effective_prose_length(text),
            }
        return True, {
            "message": "workflow implementation plan passed",
            "effective_prose_characters": _effective_prose_length(text),
            "covered_counts": {key: len(value) for key, value in groups.items()},
        }


class WorkflowLivingPlanChecker(WorkflowBuildConfigChecker):
    """Validate the ordered append-only record for the current WFB stage."""

    def __init__(self, plan_path: str, current_stage: str, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.plan_path = plan_path
        self.current_stage = current_stage

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Check stage sequence, record detail, required headings, and SHA256 chain."""
        path = self._resolve(self.plan_path)
        if not path.is_file():
            return False, {
                "error": "living workflow implementation plan is missing",
                "plan_path": str(path),
            }
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return False, {"error": f"cannot read living plan: {exc}"}
        problems = validate_records(text, self.current_stage)
        if problems:
            return False, {
                "error": "living workflow implementation plan is incomplete or rewritten",
                "current_stage": self.current_stage,
                **problems,
            }
        return True, {
            "message": "living workflow implementation plan passed",
            "current_stage": self.current_stage,
        }


class WorkflowUserDocsChecker(WorkflowBuildConfigChecker):
    """Validate required user docs and per-tool/checker developer explanations."""

    FIXED_DOCS = (
        "docs/README.md",
        "docs/01快速启动.md",
        "docs/02输入输出.md",
        "docs/03步骤及检查.md",
        "docs/04开发者文档-tools.md",
        "docs/05开发者文档-checkers.md",
    )

    def __init__(self, workflow_root: str, manifest_path: str, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path

    @staticmethod
    def _component_section(text: str, name: str) -> str:
        pattern = re.compile(
            rf"^#{{2,6}}\s+[^\n]*{re.escape(name)}[^\n]*\n(.*?)(?=^#{{2,6}}\s+|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1) if match else ""

    @staticmethod
    def _normalized_code(text: str) -> str:
        lines = [line.strip() for line in text.strip().splitlines()]
        return "\n".join(line for line in lines if line)

    @classmethod
    def _matching_source_snippet(cls, section: str, source: str) -> bool:
        """Require a substantial fenced snippet copied from the real implementation."""
        normalized_source = cls._normalized_code(source)
        blocks = re.findall(
            r"```(?:python|py)?[ \t]*\n(.*?)```",
            section,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for block in blocks:
            normalized = cls._normalized_code(block)
            meaningful_lines = [
                line for line in normalized.splitlines()
                if line and not line.startswith("#")
            ]
            if (
                len(meaningful_lines) >= 2
                and len(re.sub(r"\s+", "", normalized)) >= 40
                and normalized in normalized_source
            ):
                return True
        return False

    @staticmethod
    def _component_sources(
        root: Path,
        config: dict[str, Any],
    ) -> dict[str, dict[str, dict[str, str]]]:
        result: dict[str, dict[str, dict[str, str]]] = {
            "required_tools": {},
            "required_checkers": {},
        }
        tools = config.get("tools", {}) if isinstance(config, dict) else {}
        registry = tools.get("GeneratedTools", []) if isinstance(tools, dict) else []
        if isinstance(registry, list):
            for item in registry:
                if (
                    not isinstance(item, dict)
                    or item.get("enabled") is False
                    or not isinstance(item.get("name"), str)
                ):
                    continue
                entry: dict[str, Any] = {}
                spec_path = item.get("spec")
                if isinstance(spec_path, str) and (root / spec_path).is_file():
                    try:
                        spec = load_yaml_config(root / spec_path)
                        entry = spec.get("entry", {}) if isinstance(spec, dict) else {}
                    except WorkflowBuildError:
                        entry = {}
                file_path = entry.get("file") or item.get("file")
                if isinstance(file_path, str):
                    result["required_tools"][item["name"]] = {
                        "file": file_path,
                        "class_name": str(entry.get("class_name", "")),
                        "method": str(entry.get("method", "")),
                    }
        spec_path = root / ".workflow" / "workflow_spec.yaml"
        if spec_path.is_file():
            try:
                workflow_spec = load_yaml_config(spec_path)
            except WorkflowBuildError:
                workflow_spec = {}
            for item in workflow_spec.get("checkers", []) if isinstance(workflow_spec, dict) else []:
                entry = item.get("entry", {}) if isinstance(item, dict) else {}
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("name"), str)
                    and isinstance(entry, dict)
                    and isinstance(entry.get("file"), str)
                ):
                    result["required_checkers"][item["name"]] = {
                        "file": entry["file"],
                        "class_name": str(entry.get("class_name", "")),
                        "method": str(entry.get("method", "do_check")),
                    }
        return result

    @classmethod
    def _component_validation_errors(
        cls,
        root: Path,
        manifest: dict[str, Any],
        config: dict[str, Any],
        component_texts: dict[str, str],
    ) -> dict[str, Any]:
        """Apply the final per-component developer-doc contract to rendered text."""
        component_errors: dict[str, Any] = {}
        config_tools = config.get("tools", {}) if isinstance(config, dict) else {}
        registry = config_tools.get("GeneratedTools", []) if isinstance(config_tools, dict) else []
        registered_tool_names = [
            item.get("name")
            for item in registry
            if isinstance(item, dict)
            and item.get("enabled") is not False
            and isinstance(item.get("name"), str)
        ] if isinstance(registry, list) else []
        source_contracts = cls._component_sources(root, config)
        for key, text in component_texts.items():
            failures = {}
            component_names = _manifest_item_names(manifest.get(key, []))
            if key == "required_tools":
                component_names = list(dict.fromkeys([*component_names, *registered_tool_names]))
            else:
                component_names = list(
                    dict.fromkeys([
                        *component_names,
                        *source_contracts["required_checkers"].keys(),
                    ])
                )
            for name in component_names:
                section = cls._component_section(text, name)
                length = _effective_prose_length(section)
                required_code_markers = (
                    ("实现文件",),
                    ("入口类", "入口函数", "do_check"),
                    ("关键代码", "核心逻辑", "判定流程"),
                    ("调用路径", "调用链", "执行流程"),
                    ("输入参数", "输入字段"),
                    ("返回值", "证据产物", "输出字段"),
                    ("分支",),
                    ("异常", "错误处理"),
                    ("扩展点", "调整方式"),
                    ("测试", "fixture", "回归"),
                )
                missing_code_analysis = [
                    "/".join(markers)
                    for markers in required_code_markers
                    if not any(marker in section for marker in markers)
                ]
                business_analysis_markers = (
                    ("源码分析", "代码分析", "逐行分析"),
                    ("业务逻辑", "业务规则", "业务含义"),
                    ("修改影响", "影响范围", "联动修改"),
                )
                missing_business_analysis = [
                    "/".join(markers)
                    for markers in business_analysis_markers
                    if not any(marker in section for marker in markers)
                ]
                contract = source_contracts.get(key, {}).get(name)
                source_errors = []
                if not contract:
                    source_errors.append("component is not registered with a real implementation source")
                else:
                    source_path = root / contract["file"]
                    if not source_path.is_file():
                        source_errors.append(f"implementation source is missing: {contract['file']}")
                    else:
                        source = source_path.read_text(encoding="utf-8")
                        if contract["file"] not in section:
                            source_errors.append(
                                f"section does not cite exact implementation path: {contract['file']}"
                            )
                        for marker_name in ("class_name", "method"):
                            marker = contract.get(marker_name, "")
                            if marker and marker not in section:
                                source_errors.append(
                                    f"section does not cite actual {marker_name}: {marker}"
                                )
                        if not cls._matching_source_snippet(section, source):
                            source_errors.append(
                                "no entire fenced Python block matches one uninterrupted source "
                                "substring; use a small verbatim block of 2-6 consecutive substantive "
                                "lines and do not skip methods, comments, decorators, or statements "
                                "inside that block"
                            )
                if length < 300 or missing_code_analysis or missing_business_analysis or source_errors:
                    failures[name] = {
                        "effective_length": length,
                        "required_length": 300,
                        "missing_code_analysis": missing_code_analysis,
                        "missing_business_analysis": missing_business_analysis,
                        "source_evidence_errors": source_errors,
                    }
            if failures:
                component_errors[key] = failures
        return component_errors

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate required user documents, content markers, and component detail."""
        root = self._resolve(self.workflow_root)
        try:
            manifest = load_yaml_config(self._resolve(self.manifest_path))
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}
        manifest_docs = _manifest_item_names(manifest.get("required_user_docs", []))
        required = list(dict.fromkeys([*self.FIXED_DOCS, *manifest_docs]))
        missing = [path for path in required if not (root / path).is_file()]
        short_docs = {}
        for path in required:
            target = root / path
            if target.is_file():
                length = _effective_prose_length(target.read_text(encoding="utf-8"))
                if length < 200:
                    short_docs[path] = length
        config_path = root / "config.yaml"
        config = load_yaml_config(config_path) if config_path.is_file() else {}
        component_paths = {
            "required_tools": root / "docs/04开发者文档-tools.md",
            "required_checkers": root / "docs/05开发者文档-checkers.md",
        }
        component_texts = {
            key: path.read_text(encoding="utf-8")
            for key, path in component_paths.items()
            if path.is_file()
        }
        component_errors = self._component_validation_errors(
            root,
            manifest,
            config,
            component_texts,
        )
        content_errors = {}
        required_markers = {
            "docs/README.md": [Path(path).name for path in self.FIXED_DOCS[1:]],
            "docs/01快速启动.md": [
                "setup.py",
                "make configure",
                "make configure-check",
                "input/example",
                "output/",
                "make check",
                "make check_example",
                "make run",
            ],
            "docs/02输入输出.md": [
                "input/<TARGET>/",
                "output/<TARGET>/",
                "config/environment.schema.yaml",
                ".workflow/local/environment.yaml",
            ],
            "docs/03步骤及检查.md": [
                *_manifest_item_names(manifest.get("required_stages", [])),
                *_manifest_item_names(manifest.get("required_checkers", [])),
            ],
        }
        for rel, markers in required_markers.items():
            path = root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            missing_markers = [marker for marker in markers if marker not in text]
            if missing_markers:
                content_errors[rel] = missing_markers
        wrongly_registered = []
        if config_path.is_file():
            registered = config.get("guide_docs", [])
            if isinstance(registered, list):
                wrongly_registered = [path for path in registered if isinstance(path, str) and path.startswith("docs/")]
        provenance_errors = [
            item
            for item in _guidedoc_provenance_errors(root)
            if str(item.get("output", "")).startswith("docs/")
        ]
        failures = {
            "missing_docs": missing,
            "short_docs": short_docs,
            "short_component_sections": component_errors,
            "missing_document_content": content_errors,
            "user_docs_registered_as_guidedocs": wrongly_registered,
            "stale_generated_documents": provenance_errors,
        }
        if any(failures.values()):
            return False, {"error": "user documentation validation failed", **failures}
        return True, {"message": "user documentation passed", "documents": required}


class WorkflowDependencyChecker(WorkflowBuildConfigChecker):
    """Validate requirements.txt against dependency records in the manifest."""

    def __init__(self, workflow_root: str, manifest_path: str, **kwargs):
        super().__init__(kwargs.get("build_config_path", ""), **kwargs)
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate requirements.txt against declared Python and system dependencies."""
        root = self._resolve(self.workflow_root)
        path = root / "requirements.txt"
        try:
            manifest = load_yaml_config(self._resolve(self.manifest_path))
        except WorkflowBuildError as exc:
            return False, {"error": str(exc)}
        if not path.is_file():
            return False, {"error": "requirements.txt is missing"}
        text = path.read_text(encoding="utf-8")
        package_lines = [
            line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        python_missing = []
        for item in manifest.get("required_python_dependencies", []):
            name = item.get("package") or item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and not any(
                re.match(rf"^{re.escape(name)}(?:\[.*?\])?(?:[<>=!~].*)?$", line, re.IGNORECASE)
                for line in package_lines
            ):
                python_missing.append(name)
        system_missing = []
        for item in manifest.get("required_system_dependencies", []):
            if isinstance(item, dict):
                name = item.get("name")
                install = item.get("install") or item.get("installation")
            else:
                name, install = item, None
            missing_parts = [
                value for value in (name, install)
                if isinstance(value, str) and value and value not in text
            ]
            if missing_parts:
                system_missing.append({"dependency": name, "missing_text": missing_parts})
        if python_missing or system_missing:
            return False, {
                "error": "requirements.txt does not cover declared dependencies",
                "missing_python_dependencies": python_missing,
                "missing_system_dependency_instructions": system_missing,
            }
        return True, {
            "message": "requirements.txt covers declared dependencies",
            "python_entries": len(package_lines),
        }
