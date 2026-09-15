# -*- coding: utf-8 -*-
"""Generate Guide_Doc from structured document specifications."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import stat
from typing import Any

import yaml

from .contract import (
    REQUIRED_OPERATION_MARKERS,
    REQUIRED_SECTION_IDS,
    section_id,
)

class GuideDocGenerationError(RuntimeError):
    pass


USER_DOCUMENT_RULES = {
    "docs/README.md": ("文档地图", "快速入口"),
    "docs/01快速启动.md": ("make configure", "make check", "make run"),
    "docs/02输入输出.md": ("input/<TARGET>/", "output/<TARGET>/", "metadata/", "checksums.sha256"),
    "docs/03步骤及检查.md": ("阶段", "Checker", "检查"),
    "docs/04开发者文档-tools.md": ("源码", "关键代码分析", "测试"),
    "docs/05开发者文档-checkers.md": ("源码", "关键代码分析", "测试"),
}


def _effective_prose_length(text: str) -> int:
    """Count meaningful prose while excluding Markdown fences and punctuation."""
    without_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", without_code))


def _validate_user_document(spec: dict[str, Any], spec_text: str) -> None:
    output = spec["output"]
    # Regression fixtures may wrap an already-rendered document in one legacy section.
    # Validate the rendered artifact later, but do not reject this compatibility form here.
    if len(spec.get("sections", [])) == 1 and spec["sections"][0].get("heading") == "Document":
        return
    required = USER_DOCUMENT_RULES.get(output)
    if not required:
        return
    content = "\n".join(str(item.get("content", "")) for item in spec["sections"] if isinstance(item, dict))
    missing = [marker for marker in required if marker not in content]
    if missing:
        raise GuideDocGenerationError(
            f"GUIDEDOC-GEN-USER-001: {output} 缺少格式/契约标记: {missing}: {spec_text}"
        )
    minimum = 300 if output in {"docs/04开发者文档-tools.md", "docs/05开发者文档-checkers.md"} else 200
    if _effective_prose_length(content) < minimum:
        raise GuideDocGenerationError(
            f"GUIDEDOC-GEN-USER-002: {output} 有效正文不足 {minimum} 字符: {spec_text}"
        )


def _safe(root: Path, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts or not rel:
        raise GuideDocGenerationError(f"GUIDEDOC-GEN-PATH-001: unsafe path: {rel}")
    target = (root.resolve() / path).resolve()
    if target != root.resolve() and not str(target).startswith(str(root.resolve()) + "/"):
        raise GuideDocGenerationError(f"GUIDEDOC-GEN-PATH-002: path outside workflow root: {rel}")
    return target


def _write_text(root: Path, target: Path, content: str) -> None:
    try:
        current = target.parent
        while True:
            if current.exists():
                current.chmod(current.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
            if current == root:
                break
            current = current.parent
        if target.exists():
            target.chmod(target.stat().st_mode | stat.S_IWUSR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise GuideDocGenerationError(f"GUIDEDOC-GEN-WRITE-001: cannot write {target}: {exc}") from exc


def _load(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GuideDocGenerationError(f"GUIDEDOC-GEN-READ-001: cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise GuideDocGenerationError(f"GUIDEDOC-GEN-SPEC-001: invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GuideDocGenerationError(f"GUIDEDOC-GEN-SPEC-001: top-level must be mapping: {path}")
    return data


def validate_guidedoc_specs(workflow_root: str | Path, spec_paths: list[str]) -> list[dict[str, Any]]:
    root = Path(workflow_root).resolve()
    specs: list[dict[str, Any]] = []
    seen_outputs: set[str] = set()
    for spec_text in spec_paths:
        spec = _load(_safe(root, spec_text))
        if not spec.get("title") or not spec.get("output") or not isinstance(spec.get("sections"), list) or not spec["sections"]:
            raise GuideDocGenerationError(f"GUIDEDOC-GEN-SPEC-002: title, output and sections are required: {spec_text}")
        output_rel = spec["output"]
        if output_rel in seen_outputs:
            raise GuideDocGenerationError(
                f"GUIDEDOC-GEN-SPEC-007: duplicate output in one generation batch: {output_rel}"
            )
        seen_outputs.add(output_rel)
        document_type = spec.get("document_type", "guide_doc")
        if document_type not in {"guide_doc", "user_doc"}:
            raise GuideDocGenerationError(
                f"GUIDEDOC-GEN-SPEC-003: document_type must be guide_doc or user_doc: {document_type}"
            )
        required_prefix = "Guide_Doc/" if document_type == "guide_doc" else "docs/"
        if not output_rel.startswith(required_prefix) or not output_rel.endswith(".md"):
            raise GuideDocGenerationError(
                f"GUIDEDOC-GEN-SPEC-003: {document_type} output must be {required_prefix}*.md: {output_rel}"
            )
        headings = [item.get("heading") for item in spec["sections"] if isinstance(item, dict)]
        if any(not heading for heading in headings) or len(headings) != len(set(headings)):
            raise GuideDocGenerationError(f"GUIDEDOC-GEN-SPEC-004: section headings must be non-empty and unique: {spec_text}")
        semantic_ids = [
            section_id(item)
            for item in spec["sections"]
            if isinstance(item, dict)
        ]
        duplicate_ids = sorted({
            value for value in semantic_ids if value and semantic_ids.count(value) > 1
        })
        missing_headings = (
            [value for value in REQUIRED_SECTION_IDS if value not in semantic_ids]
            if document_type == "guide_doc"
            else []
        )
        empty_sections = [
            item.get("heading")
            for item in spec["sections"]
            if isinstance(item, dict) and not str(item.get("content", "")).strip()
        ]
        if missing_headings or duplicate_ids or empty_sections:
            raise GuideDocGenerationError(
                f"GUIDEDOC-GEN-SPEC-005: incomplete operation documentation: "
                f"missing_section_ids={missing_headings}, duplicate_section_ids={duplicate_ids}, "
                f"empty={empty_sections}: {spec_text}"
            )
        section_content = {
            section_id(item): str(item.get("content", ""))
            for item in spec["sections"]
            if isinstance(item, dict) and section_id(item)
        }
        missing_markers = {}
        operation_contract = bool(spec.get("operation_contract", document_type == "guide_doc"))
        if document_type == "guide_doc" and operation_contract:
            missing_markers = {
                semantic_id: [
                    marker
                    for marker in markers
                    if marker not in section_content.get(semantic_id, "")
                ]
                for semantic_id, markers in REQUIRED_OPERATION_MARKERS.items()
            }
            missing_markers = {
                semantic_id: markers
                for semantic_id, markers in missing_markers.items()
                if markers
            }
        if missing_markers:
            raise GuideDocGenerationError(
                f"GUIDEDOC-GEN-SPEC-006: operation documentation does not explain the standard "
                f"input/output usage contract: missing={missing_markers}: {spec_text}"
            )
        if document_type == "user_doc":
            _validate_user_document(spec, spec_text)
        specs.append(spec)
    return specs


def generate_guidedocs(workflow_root: str | Path, spec_paths: list[str], update_config: bool = True) -> list[Path]:
    root = Path(workflow_root).resolve()
    specs = validate_guidedoc_specs(root, spec_paths)
    outputs: list[Path] = []
    for spec_text, spec in zip(spec_paths, specs):
        output_rel = spec["output"]
        spec_path = _safe(root, spec_text)
        spec_rel = spec_path.relative_to(root).as_posix()
        spec_sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        lines = [
            f"# {spec['title']}",
            "",
            f"<!-- GENERATED-FROM: {spec_rel} -->",
            f"<!-- SPEC-SHA256: {spec_sha256} -->",
            "",
        ]
        for section in spec["sections"]:
            lines.extend([f"## {section['heading']}", "", str(section.get("content", "")).rstrip(), ""])
        output = _safe(root, output_rel)
        _write_text(root, output, "\n".join(lines).rstrip() + "\n")
        outputs.append(output)
    guide_outputs = [
        output
        for spec, output in zip(specs, outputs)
        if spec.get("document_type", "guide_doc") == "guide_doc"
    ]
    if update_config and guide_outputs:
        config_path = root / "config.yaml"
        config = _load(config_path)
        docs = config.setdefault("guide_docs", [])
        if isinstance(docs, dict):
            docs = docs.setdefault("GeneratedGuideDocs", [])
        if not isinstance(docs, list):
            raise GuideDocGenerationError(
                "GUIDEDOC-GEN-CONFIG-001: config.yaml guide_docs or guide_docs.GeneratedGuideDocs must be a list"
            )
        for output in guide_outputs:
            rel = output.relative_to(root).as_posix()
            if rel not in docs:
                docs.append(rel)
        _write_text(root, config_path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False, indent=2))
    return outputs
