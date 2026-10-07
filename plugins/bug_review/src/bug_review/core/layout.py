"""Bug Review run-layout identities, normalized node IDs, and stage constants."""
from __future__ import annotations

from pathlib import Path
import re
import shutil

ANALYSIS = ("full_replay", "case_triage", "dut_evidence", "report_reconcile",
            "root_correlation", "publish")
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
REVIEW_ROOT = Path("verification_review")
RESULTS_OUT_DEFAULT = REVIEW_ROOT / "analysis"
REPORT_ROOT = REVIEW_ROOT / "report"
NOTES_ROOT = REVIEW_ROOT / "notes"
COLLECTION_TIMEOUT = 300
UNITY_TEST_ROOT = REVIEW_ROOT / "run" / "unity_test"
TEST_REPORT_ROOT = REVIEW_ROOT / "run" / "test_report"


def module_label(workspace):
    """Derive the module label from the module workspace directory."""
    path = Path(workspace).resolve()
    return safe_name(path.name)


def safe_name(value):
    """Validate a workspace label before using it as an output path component."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError(f"invalid workspace name: {value!r}")
    return value


def canonical_node(node):
    """Drop report line annotations while preserving the exact pytest node ID."""
    return re.sub(r"(?<=\.py):\d+(?:-\d+)?(?=::|$)", "", str(node))


def workspace_node(node):
    """Map one current report node to the canonical ``tests/`` case ID."""
    value = canonical_node(node)
    prefix = "verification_review/run/unity_test/"
    if value.startswith(prefix):
        value = value[len(prefix):]
    if not value.startswith("tests/"):
        raise ValueError(f"case node must be relative to run/unity_test: {node!r}")
    return value


def resolve_out_dir(root):
    """Return the v1.0 analysis directory beneath one module workspace."""
    return Path(root).resolve() / RESULTS_OUT_DEFAULT


def unity_test_root(root):
    """Return the single Bug Review execution copy of ``unity_test``."""
    return Path(root).resolve() / UNITY_TEST_ROOT


def test_report_root(root):
    """Return the writable pytest/toffee report directory."""
    return Path(root).resolve() / TEST_REPORT_ROOT


def resolve_logical_path(root, relative):
    """Resolve a logical review reference in the Master-owned workspace.

    UnityTest is the only Bug Review input copied into ``run``; DUT, RTL,
    documents, and Guide_Doc remain at the workspace root.
    """
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"invalid workspace reference: {relative}")
    if value.parts[:1] == ("tests",):
        return unity_test_root(root).joinpath(*value.parts)
    if value.parts[:1] == ("unity_test",):
        return unity_test_root(root).joinpath(*value.parts[1:])
    return Path(root).resolve() / value


def prepare_workspace_layout(root):
    """Move the Master-provided UnityTest tree into its single run location."""
    workspace = Path(root).resolve()
    target = unity_test_root(workspace)
    source = workspace / "unity_test"
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"run/unity_test is not a directory: {target}")
    elif source.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    else:
        raise ValueError(f"Master workspace is missing unity_test input: {source}")
    (workspace / TEST_REPORT_ROOT).mkdir(parents=True, exist_ok=True)
    (workspace / RESULTS_OUT_DEFAULT).mkdir(parents=True, exist_ok=True)
    (workspace / REPORT_ROOT).mkdir(parents=True, exist_ok=True)
    (workspace / NOTES_ROOT).mkdir(parents=True, exist_ok=True)
    return target
