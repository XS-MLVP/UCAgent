#!/usr/bin/env python3
import argparse
import json
import importlib.util
from pathlib import Path


DOC_SUFFIX = "_functions_and_checks.md"
GUIDE_DIR_NAMES = {"guide_doc", "template", "formaldoc"}


def load_extract_module():
    script_path = Path(__file__).with_name("extract_fg_fc_ck.py")
    spec = importlib.util.spec_from_file_location("extract_fg_fc_ck", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXTRACT_MODULE = load_extract_module()


def has_fg_fc_ck_structure(doc_path: Path) -> bool:
    structure = EXTRACT_MODULE.extract_structure(doc_path.read_text(encoding="utf-8"))
    groups = structure.get("groups") or []
    return any(function.get("checks") for group in groups for function in group.get("functions") or [])


def is_scaffold_doc(doc_path: Path) -> bool:
    """Return True for placeholder docs that are not real DUT specs.

    This filters out UCAgent template scaffolds that use a brace-wrapped DUT
    placeholder and guide/template/formal-doc examples that teach the format
    rather than describe a concrete DUT.
    """
    stem = doc_path.name[: -len(DOC_SUFFIX)]
    normalized = stem.replace("{", "").replace("}", "").strip()
    in_guide_dir = any(part.lower() in GUIDE_DIR_NAMES for part in doc_path.parts)

    if normalized == "DUT" and "{" in stem and "}" in stem:
        return True

    if in_guide_dir and not has_fg_fc_ck_structure(doc_path):
        return True

    return False


def has_sibling_tests(doc_path: Path) -> bool:
    return (doc_path.parent / "tests").is_dir()


def find_ucagent_candidates(project_root: Path):
    rooted_examples = sorted(project_root.glob(f"examples/*/unity_test/*{DOC_SUFFIX}"))
    rooted_examples = [path for path in rooted_examples if not is_scaffold_doc(path)]
    if rooted_examples:
        return rooted_examples

    candidates = sorted(
        path
        for path in project_root.rglob(f"*{DOC_SUFFIX}")
        if path.parent.name == "unity_test" and not is_scaffold_doc(path)
    )
    return candidates


def find_tests_dir(doc_path: Path, project_root: Path | None = None):
    sibling_tests = doc_path.parent / "tests"
    if sibling_tests.is_dir():
        return sibling_tests

    descendants = sorted(
        (path for path in doc_path.parent.rglob("tests") if path.is_dir()),
        key=lambda path: (len(path.relative_to(doc_path.parent).parts), str(path)),
    )
    if descendants:
        return descendants[0]

    ancestors = list(doc_path.parents)
    for ancestor in ancestors[1:]:
        if project_root is not None:
            try:
                ancestor.relative_to(project_root)
            except ValueError:
                break
        candidate = ancestor / "tests"
        if candidate.is_dir():
            return candidate

    return None


def pick_doc(project_root: Path, candidates, project_type: str):
    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda path: (
            0 if has_fg_fc_ck_structure(path) else 1,
            0 if has_sibling_tests(path) else 1,
            0 if infer_dut_name(path, project_type) is not None else 1,
            len(path.relative_to(project_root).parts),
            str(path),
        ),
    )[0]


def infer_dut_name(doc_path: Path, project_type: str):
    if not doc_path:
        return None

    dut_name = doc_path.name[: -len(DOC_SUFFIX)]
    if project_type == "generic" and dut_name.lower() == "dut":
        return None
    return dut_name


def detect_layout(project_root: Path):
    if project_root.name == "tests" and project_root.parent.name == "unity_test":
        project_root = project_root.parent

    ucagent_candidates = find_ucagent_candidates(project_root)
    generic_candidates = sorted(
        path
        for path in project_root.rglob(f"*{DOC_SUFFIX}")
        if not is_scaffold_doc(path)
    )

    ucagent_doc_path = pick_doc(project_root, ucagent_candidates, "ucagent")
    generic_doc_path = pick_doc(project_root, generic_candidates, "generic")

    if generic_doc_path is not None and has_fg_fc_ck_structure(generic_doc_path):
        if ucagent_doc_path is None or not has_fg_fc_ck_structure(ucagent_doc_path):
            doc_path = generic_doc_path
            project_type = "generic"
        else:
            doc_path = ucagent_doc_path
            project_type = "ucagent"
    else:
        doc_path = ucagent_doc_path
        project_type = "ucagent"
        if doc_path is None:
            doc_path = generic_doc_path
            project_type = "generic"

    tests_dir = find_tests_dir(doc_path, project_root) if doc_path else None
    dut_name = infer_dut_name(doc_path, project_type)
    has_fg_fc_ck_doc = bool(doc_path and has_fg_fc_ck_structure(doc_path))

    return {
        "project_type": project_type,
        "dut_name": dut_name,
        "tests_dir": str(tests_dir.resolve()) if tests_dir else None,
        "docs_dir": str(doc_path.parent.resolve()) if doc_path else None,
        "has_fg_fc_ck_doc": has_fg_fc_ck_doc,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Detect a pytoffee project layout with UCAgent-first rules and deterministic generic fallback."
    )
    parser.add_argument("project_root", help="Path to the project root to inspect.")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    result = detect_layout(project_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
