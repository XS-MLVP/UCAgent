"""Validate executable ACT4 guide examples against their artifact checkers."""

import json
from pathlib import Path
import re

import yaml

from act4_privileged_suite.checkers.act4_file_manifest_checker import ACT4FileManifestChecker
from act4_privileged_suite.checkers.act4_final_report_checker import ACT4FinalReportChecker
from act4_privileged_suite.checkers.act4_test_asset_checker import ACT4TestAssetChecker
from act4_privileged_suite.checkers import act4_asset_consistency
from act4_privileged_suite.plugin import get_plugin


GUIDES = Path(__file__).resolve().parents[1] / "src/act4_privileged_suite/Guide_Doc"


def test_runtime_heading_spacing() -> None:
    """Keep runtime Markdown headings separated even inside fenced examples."""
    violations = []
    for path in GUIDES.rglob("*.md"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if re.match(r"^#{1,6}\s", line) and (index == 0 or lines[index - 1].strip()):
                violations.append(f"{path.relative_to(GUIDES)}:{index + 1}")
    assert not violations, violations


def test_generated_report_heading_spacing() -> None:
    """Apply the same heading contract to generated checker Markdown reports."""
    lines = act4_asset_consistency._format_report_markdown({}).splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s", line):
            assert index > 0 and not lines[index - 1].strip()


def test_manifest_guide_complete_example(tmp_path: Path) -> None:
    """Check the published baseline bytes, hashes and complete manifest together."""
    text = (GUIDES / "ACT4_Checker_Guide/ACT4FileManifestChecker.md").read_text(encoding="utf-8")
    baseline, manifest = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    makefile = tmp_path / "riscv-arch-test/Makefile"
    makefile.parent.mkdir()
    makefile.write_text("all:\n\t@true\n", encoding="utf-8")
    makefile.chmod(0o644)
    output = tmp_path / "act4_assets"
    output.mkdir()
    (output / "artifact.txt").write_text("asset\n", encoding="utf-8")
    (output / "baseline.yaml").write_text(baseline, encoding="utf-8")
    (output / "manifest.yaml").write_text(manifest, encoding="utf-8")
    checker = ACT4FileManifestChecker(
        manifest_file="act4_assets/manifest.yaml",
        expected_suite="H",
        inventory_patterns=["act4_assets/**/*"],
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert passed, report
    assert report["checks"]["manifested_files"] == 3


def test_final_report_guide_complete_example(tmp_path: Path) -> None:
    """Validate the entire published report using the actual final-stage gate."""
    text = (GUIDES / "ACT4_Checker_Guide/ACT4FinalReportChecker.md").read_text(encoding="utf-8")
    report_text = re.search(r"````markdown\n(.*?)````", text, re.DOTALL).group(1)
    report_path = tmp_path / "act4_assets/H/reports/H_final_summary_report.md"
    report_path.parent.mkdir(parents=True)
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", report_text):
        path = report_path.parent / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    state = report_path.parent / "H_validation_state.yaml"
    state.write_text(
        yaml.safe_dump({"contribution_ready": True, "generation_scope": {"status": "partial"}}),
        encoding="utf-8",
    )
    report_path.write_text(report_text, encoding="utf-8")
    workflow = yaml.safe_load(get_plugin().workflows[0].config_file.read_text(encoding="utf-8"))
    gate = next(
        gate for gate in workflow["stage"][-1]["checker"]
        if gate["clss"] == "ACT4FinalReportChecker"
    )
    args = json.loads(json.dumps(gate["args"]).replace("{OUT}", "act4_assets").replace("{DUT}", "H"))

    passed, report = ACT4FinalReportChecker(**args).set_workspace(str(tmp_path)).do_check()

    assert passed, report


def test_reference_run_guide_complete_example(tmp_path: Path) -> None:
    """Check the published log, signature and results as one complete run."""
    text = (GUIDES / "ACT4_Checker_Guide/ACT4TestAssetChecker.md").read_text(encoding="utf-8")
    log, signature, results = re.findall(r"```(?:text|asm)\n(.*?)```", text, re.DOTALL)
    source = tmp_path / "H-00.S"
    source.write_text("generated source\n", encoding="utf-8")
    paths = []
    for suffix, content in (("sig.log", log), ("sig", signature), ("results", results)):
        path = tmp_path / f"H-00.{suffix}"
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    checker = ACT4TestAssetChecker(
        require_reference_model_logs=True, require_signature_completeness=True,
    )
    findings = []

    summary = checker._check_reference_model_outputs([source], [paths[1]], [paths[2]], [paths[0]], findings)

    assert not findings, findings
    assert summary["complete_runs_checked"] == 1
