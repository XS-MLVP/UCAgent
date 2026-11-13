"""User-visible PPA histories, actual source changes, failed attempts, and safe rendering."""

from __future__ import annotations

import helpers  # noqa: F401

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

from helpers import _config, _prepare_iteration_workspace, _write_candidate_report
from test_repo_module import repo_case  # noqa: F401  (shared isolated Git fixture)
from design_with_ppa.contracts import atomic_json, atomic_text, atomic_yaml, sha256_file
from design_with_ppa.optimization_log import changed_files, write_source_diff, write_unit_optimization_log
from design_with_ppa.repo.evidence import unseal
from design_with_ppa.repo.models import Candidate
from design_with_ppa.ppa import AnalyzePPA
from design_with_ppa.ppa.dashboard import refresh_dashboard_snapshot
from design_with_ppa.repo.validation import validate_unit, validated_records, write_repo_optimization_log
from ucagent.util.markdown import markdown_heading_spacing_errors
from ucagent.util.config import save_runtime_config


@pytest.mark.parametrize("skills_enabled", [False, True])
@pytest.mark.parametrize("outcome", ["accepted", "rejected", "functional_failure"])
def test_unit_log_captures_intent_actual_diff_and_result(tmp_path, monkeypatch, outcome, skills_enabled):
    """Both Skill settings expose every measured outcome, including restored failed sources."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=1, max_iterations=1)
    checker.cfg.set_value("skill", {"use_skill": skills_enabled})
    _write_candidate_report(tmp_path, base_id, area=9.0, delay=2.0 if outcome == "rejected" else 1.0)
    candidate_hash = sha256_file(tmp_path / "output/rtl/dut.v")
    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 1 if outcome == "functional_failure" else 0,
                                                    "1 failed" if outcome == "functional_failure" else "1 passed", ""))
    passed, result = checker.do_check()
    assert passed, result
    path = tmp_path / "output/dut_optimization_log.md"
    text = path.read_text()
    assert "Reduce mapped cell area in candidate 1." in text
    assert "area_by_cell_type.BUF_X1" in text
    assert f"v1 / candidate / {'accepted' if outcome == 'accepted' else 'rejected'}" in text
    assert "output/rtl/dut.v" in text and candidate_hash in text
    assert "Change % vs previous" in text and "Change % vs base" in text
    assert path.with_suffix(".html").is_file()
    diff = tmp_path / "output/reports/ppa/iterations/iteration-001.diff"
    assert "wire n0;" in diff.read_text()
    assert not markdown_heading_spacing_errors(text)
    assert not (tmp_path / ".ucagent/skills").exists()
    if outcome == "functional_failure":
        assert "functional_regression_failed" in text
        assert "no complete PPA measurement" in text
    if outcome != "accepted":
        assert sha256_file(tmp_path / "output/rtl/dut.v") != candidate_hash
    before = path.read_bytes()
    diff.write_text("forged public diff")
    ledger = yaml.safe_load((tmp_path / "output/dut_optimization_ledger.yaml").read_text())
    write_unit_optimization_log(tmp_path, ledger, "output/dut_optimization_ledger.yaml")
    assert "wire n0;" in diff.read_text()
    checker.do_check()
    assert path.read_bytes() == before
    assert text.count("## v1 /") == 1


def test_source_changes_include_add_delete_mode_binary_and_no_final_newline(tmp_path):
    """Review diffs keep deletions/additions, EOF semantics, and explicit omitted-content notices."""

    rows = changed_files({"delete": "old", "edit": {"mode": "100644"}},
                         {"add": "new", "edit": {"mode": "100755"}})
    assert {row["path"]: row["action"] for row in rows} == {"add": "add", "delete": "delete", "edit": "modify"}
    old, new, binary = tmp_path / "old", tmp_path / "new", tmp_path / "binary"
    empty, large = tmp_path / "empty", tmp_path / "large"
    old.write_text("old")
    new.write_text("new\n")
    binary.write_bytes(b"\0data")
    empty.write_text("")
    large.write_bytes(b"x" * 2_000_001)
    diff = tmp_path / "changes.diff"
    write_source_diff(diff, {"edit": old, "delete": old, "empty-delete": empty},
                      {"edit": new, "add": new, "binary": binary, "empty-add": empty, "large": large})
    text = diff.read_text()
    assert "-old\n\\ No newline at end of file" in text
    assert "+new" in text and "--- a/delete" in text and "+++ b/add" in text
    assert "Content diff omitted for binary/large file: binary" in text
    assert "Content diff omitted for binary/large file: large" in text
    assert "Empty file added: empty-add" in text and "Empty file deleted: empty-delete" in text


@pytest.mark.parametrize("repo_enabled", [False, True])
def test_dashboard_embeds_resolved_workflow_for_offline_log_link(tmp_path, repo_enabled):
    """A fresh file-mode dashboard retains the workflow flag needed to open the correct log."""

    cfg = _config()
    cfg.set_value("design_with_ppa.repo", {"enabled": repo_enabled})
    save_runtime_config(str(tmp_path), cfg, runtime_config_keys=["design_with_ppa.repo.enabled"])
    (tmp_path / "output").mkdir()
    tool = AnalyzePPA(workspace=str(tmp_path), output_dir="output", write_dirs=["output"], un_write_dirs=[])
    refresh_dashboard_snapshot(tool.workspace, tool.output_dir, {"schema_version": "1.2", "status": "success", "report_id": "test", "summary": {}})
    html = (tmp_path / "output/dut_ppa_dashboard.html").read_text()
    match = re.search(r'<script id="design-with-ppa-snapshot" type="application/json">(.*?)</script>', html, re.S)
    assert json.loads(match[1])["runtime"]["plugin_options"]["design_with_ppa.repo.enabled"] is repo_enabled
    assert 'id="optimization-log-link"' in html
    assert "repo/reports/optimization_log.html" in html
    assert "{{" not in html
    if shutil.which("node"):
        script = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
        subprocess.run(["node", "--check"], input=script, text=True, capture_output=True, check=True)


@pytest.fixture
def measured_repo(repo_case, monkeypatch):
    """Run the real record/snapshot path with controlled compiler and PPA results."""

    paths = repo_case
    controls = {"delay": 1.0, "fail": False}

    def prepare(repository, candidate, build, recipe, interface, cfg):
        """Supply deterministic build evidence after checking the visible start event."""

        assert "started_unmeasured" in (paths.edit / "reports/optimization_log.md").read_text()
        if controls["fail"]:
            raise ValueError("rtl/unit.v:3: unresolved signal carry")
        atomic_text(build / "design/rtl/unit.v", (repository / "rtl/unit.v").read_text())
        shutil.copytree(candidate, build / "candidate")
        return {"normalized_rtl_sha256": sha256_file(build / "design/rtl/unit.v")}

    def run(argv, cwd, timeout, **kwargs):
        """Write a complete deterministic workload result in the disposable build."""

        if argv[-2] == "rtl":
            atomic_json(cwd / "unit_results.json", {"scenarios": {"bytes": {
                "results": {name: {"completed_cycle": index + 1}
                            for index, name in enumerate(("t0", "t1", "t127", "t255"))},
                "waveform": "waves/bytes.vcd"}}})
        return {"returncode": 0, "stdout": "passed", "stderr": ""}

    def analyze(self, args):
        """Return deterministic measured metrics without invoking native tools."""

        return {"status": "success", "summary": {"area": {"total": 10.0, "unit": "liberty_area_unit"},
                "power": {"total_w": 0.001}, "timing": {"critical_path_delay_ns": controls["delay"]}}}

    monkeypatch.setattr("design_with_ppa.repo.validation.prepare_unit", prepare)
    monkeypatch.setattr("design_with_ppa.repo.validation.run_command", run)
    monkeypatch.setattr("design_with_ppa.repo.validation.AnalyzePPA.analyze", analyze)
    validate_unit(paths, baseline=True)
    return paths, controls


@pytest.mark.parametrize("skills_enabled", [False, True])
def test_repo_log_preserves_failures_rejected_measurements_and_resume(measured_repo, skills_enabled):
    """Unmeasured failures survive a retry while formal rounds stay unique and source-bound."""

    paths, controls = measured_repo
    paths.cfg.set_value("skill", {"use_skill": skills_enabled})
    candidate = paths.edit / "candidate"
    hypothesis = "Share carry logic to reduce area <script>alert(1)</script> | timing\nExpected lower area."
    atomic_yaml(candidate / "candidate.yaml", {"variant_id": "carry", "hypothesis": hypothesis,
                "changes": [{"path": "rtl/unit.v", "action": "replace"}]})
    atomic_text(candidate / "files/rtl/unit.v", (paths.source / "rtl/unit.v").read_text() + "// shared carry\n")
    controls["fail"] = True
    with pytest.raises(ValueError, match="unresolved signal"):
        validate_unit(paths)
    log = paths.edit / "reports/optimization_log.md"
    assert "failed_unmeasured" in log.read_text()
    assert "rtl/unit.v:3: unresolved signal carry" in log.read_text()
    assert len(validated_records(paths)) == 1
    controls.update(fail=False, delay=2.0)
    rejected = validate_unit(paths)
    assert rejected["accepted"] is False
    assert rejected["optimization_hypothesis"] == hypothesis
    assert rejected["source_changes"][0]["path"] == "rtl/unit.v"
    assert rejected["source_changes"][0]["after"]["sha256"] == sha256_file(candidate / "files/rtl/unit.v")
    assert "// shared carry" in (paths.edit / "reports/carry.diff").read_text()
    text = log.read_text()
    assert "v1 / carry / rejected" in text and "pareto_regression" in text
    assert text.count("failed_unmeasured") == 1
    assert "&lt;script&gt;" in log.with_suffix(".html").read_text()
    assert "<script>alert" not in log.with_suffix(".html").read_text()
    assert "&#124;" in text or "| timing" in text
    assert not markdown_heading_spacing_errors(text)
    assert not (paths.workspace / ".ucagent/skills").exists()
    log.unlink()
    log.with_suffix(".html").unlink()
    (paths.edit / "reports/carry.diff").write_text("forged public diff")
    assert validate_unit(paths) == rejected
    assert "// shared carry" in (paths.edit / "reports/carry.diff").read_text()
    assert log.read_text() == text
    assert len(validated_records(paths)) == 2
    assert all(unseal(paths, path)["decision"] in {"measured", "failed_unmeasured"}
               for path in (paths.state / "attempts").glob("*.json"))


def test_repo_log_uses_verified_history_instead_of_public_report_claims(measured_repo):
    """Regenerating a view repairs edited public reports without manufacturing a new round."""

    paths, _ = measured_repo
    report = paths.edit / "reports/baseline.json"
    payload = json.loads(report.read_text())
    payload["optimization_hypothesis"] = "forged direction"
    atomic_json(report, payload)
    write_repo_optimization_log(paths, validated_records(paths))
    assert "forged direction" not in report.read_text()
    assert "Measure original" in (paths.edit / "reports/optimization_log.md").read_text()
    assert len(validated_records(paths)) == 1


def test_repo_accepted_log_compares_against_selected_version_after_rejection(measured_repo):
    """A rejected predecessor never replaces the actual comparison source or metric baseline."""

    paths, controls = measured_repo
    candidate = paths.edit / "candidate"
    for name, delay in (("slow", 2.0), ("fast", 0.5)):
        atomic_yaml(candidate / "candidate.yaml", {"variant_id": name,
                    "hypothesis": "Reduce carry propagation delay with " + name,
                    "changes": [{"path": "rtl/unit.v", "action": "replace"}]})
        atomic_text(candidate / "files/rtl/unit.v", (paths.source / "rtl/unit.v").read_text() + "// " + name + "\n")
        controls["delay"] = delay
        record = validate_unit(paths)
        assert record["accepted"] is (name == "fast")
        assert record["parent_accepted_iteration"] == 0
    log = (paths.edit / "reports/optimization_log.md").read_text()
    assert "Best measured version: v2" in log
    assert "v1 / slow / rejected" in log and "v2 / fast / accepted" in log
    assert record["comparisons"]["ppa.timing.effective_period_ns"]["percent_change"] == -50.0
    diff = (paths.edit / "reports/fast.diff").read_text()
    assert "+// fast" in diff and "-// slow" not in diff


def test_repo_hypothesis_requires_a_visible_direction():
    """Whitespace cannot satisfy the candidate's optimization narrative requirement."""

    with pytest.raises(ValueError, match="optimization direction"):
        Candidate(variant_id="empty", hypothesis="  \n", changes=[])


def test_repo_log_paths_cannot_escape_output(measured_repo, tmp_path):
    """A symlinked log directory cannot redirect generated user reports outside the workspace."""

    paths, _ = measured_repo
    reports = paths.edit / "reports"
    shutil.rmtree(reports)
    external = tmp_path / "external"
    external.mkdir()
    reports.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        write_repo_optimization_log(paths, validated_records(paths))
    assert list(external.iterdir()) == []
