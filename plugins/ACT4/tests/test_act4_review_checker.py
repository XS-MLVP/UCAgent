"""Exercise automatic extension review, scoped repairs, and honest partial reports."""

import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from act4_privileged_suite.checkers.act4_review_checker import ACT4ReviewChecker, ASSET_KINDS
from act4_privileged_suite.checkers import act4_review_checker
from act4_privileged_suite.checkers.act4_asset_checker import ACT4AssetChecker
from act4_privileged_suite.plugin import get_plugin
from ucagent.plugins import LoadedPlugin, create_plugin_checker_registry, load_plugin
from ucagent.verify_agent import VerifyAgent


@pytest.fixture(autouse=True)
def isolate_optional_simulators(monkeypatch) -> None:
    """Keep tests independent of developer licenses while allowing explicit probe fixtures."""
    original = act4_review_checker.shutil.which
    names = {name for binaries in act4_review_checker.OPTIONAL_SIMULATORS.values() for name in binaries}
    monkeypatch.setattr(act4_review_checker.shutil, "which", lambda name, **kwargs: None if name in names else original(name, **kwargs))


class ReviewHarness:
    """Provide persisted controller state and native fixtures for review and repair tests."""

    def __init__(self, root: Path) -> None:
        """Create a tiny committed ACT4 input with a real native command fixture."""
        self.root = root
        self.source = root / "riscv-arch-test"
        self.source.mkdir()
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        (self.source / "README.md").write_text("Native CI: python3 check.py\n")
        (self.source / "generators").mkdir()
        (self.source / "generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 1\n')
        (self.source / "check.py").write_text('from pathlib import Path\nPath("result.txt").write_text("coverage fixture\\nPASS\\n")\nPath("fixture.elf").write_bytes(b"\\x7fELFfixture")\n')
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture"], check=True)
        self.output = root / "reports/H/review"
        self.output.mkdir(parents=True)
        self.data = {}
        self.manager = SimpleNamespace(get_data=self.data.get, set_data=self.data.__setitem__)
        self.scope = {"schema_version": 1, "suite": "H", "assets": {kind: [] for kind in ASSET_KINDS},
                      "targets": ["rv64"], "references": ["manual H chapter"], "reference_files": [],
                      "shared_assets": [],
                      "discovery": ["Reviewed all extension paths"], "jobs": []}
        self.scope["assets"]["generators"] = ["generators/H.py"]
        for purpose in ("generation", "build", "reference_model", "coverage", "lint"):
            self.scope["jobs"].append({"id": purpose, "target": "rv64", "purpose": purpose,
                "source": "README.md", "disposition": "run", "argv": [sys.executable, "check.py"],
                "needs": ["environment"],
                "timeout_seconds": 10, "artifacts": [{"path": "result.txt", "kind": "coverage"}]})
        self.scope["jobs"][1]["needs"].append("generation")
        self.scope["jobs"][1]["artifacts"].append({"path": "fixture.elf", "kind": "elf"})
        for job in self.scope["jobs"][2:4]:
            job["needs"].append("build")
            job["elf_inputs"] = ["build"]
        self.scope["jobs"][2]["artifacts"] = [{"path": "result.txt", "kind": "results",
            "pass_pattern": "(?m)^PASS$", "fail_pattern": "(?m)^FAIL$"}]
        self.scope["jobs"].append({"id": "environment", "target": "rv64", "purpose": "environment",
            "source": "README.md", "disposition": "run", "probe": [sys.executable, "--version"],
            "expected_output": "Python 3", "reason": "Provide Python 3 from the native installation instructions",
            "timeout_seconds": 10})
        self.write("scope.yaml", self.scope)

    def write(self, name: str, value: dict) -> None:
        """Publish one agent-authored structured artifact."""
        (self.output / name).write_text(yaml.safe_dump(value))

    def checker(self, phase: str) -> ACT4ReviewChecker:
        """Construct a normal stage checker with trusted controller state."""
        checker = ACT4ReviewChecker(phase, "H", "reports/H/review").set_workspace(str(self.root))
        checker.set_stage_manager(self.manager)
        return checker

    def assess(self, document: dict, label: str = "before") -> dict:
        """Build source-quoted semantic judgments without certifying synthetic ISA assets."""
        evidence = json.loads((self.output / f"evidence-{label}.json").read_text())
        tasks = dict(evidence["review_tasks"])
        tasks.update({f"finding:{item['id']}": {} for item in document["findings"]})
        if "obligations" not in document:
            document["obligations"] = [{"id": f"O{number}", "sources": [identity],
                "requirement": "Assess all fixture requirements in this block", "status": "unverified",
                "reason": "Synthetic fixture cannot establish ISA completeness", "targets": evidence["targets"],
                "coverpoints": [], "implementation": [], "findings": []}
                for number, identity in enumerate(evidence["obligation_sources"], 1)]
        for item in document["obligations"]:
            tasks[f"obligation:{item['id']}"] = {"sources": sorted({evidence["obligation_sources"][source]["path"] for source in item["sources"]} | set(item["implementation"]) |
                {tasks[f"point:{point}"]["path"] for point in item["coverpoints"]})}
        for finding in document["findings"]:
            finding.setdefault("classification", "confirmed_defect")
            finding.setdefault("diagnosis", "repair_ready")
            prefix = "baseline" if label == "before" else "candidate"
            physical = (self.output / prefix / "generators/H.py").read_text().splitlines()
            source, line = f"{prefix}/generators/H.py", 1
            if not any(item.strip() for item in physical):
                source, physical = f"evidence-{label}.json", ["{"]
            finding.setdefault("investigation", [{"action": "Inspect fixture implementation", "result": "Identified the synthetic fixture boundary",
                "basis": [{"path": source, "lines": [line, line], "quote": physical[0], "observation": "Actual fixture contents"}]}])
            if finding.get("status") in {"deferred", "not_fixed"}:
                finding.setdefault("blocker", {"kind": "implementation", "detail": "Fixture implementation remains incomplete",
                    "impact": "No real ISA validation", "why_not_resolved": "This fixture only validates the review lifecycle", "owner": "agent"})
        if label == "after":
            tasks.update({f"finding:{item['id']}": {} for item in document["findings"]})
            baseline = act4_review_checker.tree_state(self.output / "baseline")
            candidate = act4_review_checker.tree_state(self.output / "candidate")
            tasks.update({f"change:{name}": {} for name in baseline.keys() | candidate.keys()
                          if baseline.get(name) != candidate.get(name)})
            review = yaml.safe_load((self.output / "review.yaml").read_text())
            for finding in document["findings"]:
                if finding.get("status") == "fixed":
                    paths = sorted(name for change in review["changes"] if finding["id"] in change["findings"]
                                   for name in change["paths"] if baseline.get(name) != candidate.get(name))
                    if paths:
                        name = paths[0]
                        tasks[f"finding:{finding['id']}"]["path"] = f"candidate/{name}" if name in candidate else f"baseline/{name}"
        judgments = []
        for identity, task in tasks.items():
            path = task.get("path", f"{'baseline' if label == 'before' else 'candidate'}/generators/H.py")
            if identity.startswith("change:"):
                name = identity.removeprefix("change:")
                path = f"candidate/{name}" if (self.output / "candidate" / name).exists() else f"baseline/{name}"
            number = task.get("line", task.get("lines", [1])[0] or 1)
            basis = []
            for source in task.get("sources", [path]):
                line = number if source == path else 1
                physical = (self.output / source).read_text().splitlines()
                if not any(item.strip() for item in physical):
                    source, line = f"evidence-{label}.json", 1
                    physical = (self.output / source).read_text().splitlines()
                quote = physical[line - 1]
                basis.append({"path": source, "lines": [line, line], "quote": quote,
                    "observation": "This is the exact fixture source being assessed"})
            fixed = any(identity == f"finding:{item['id']}" and item.get("status") == "fixed"
                        for item in document["findings"])
            confirmed = next((item for item in document["findings"] if identity == f"finding:{item['id']}" and item["classification"] == "confirmed_defect"), None)
            judgments.append({"tasks": [identity], "status": "passed" if fixed else "unverified",
                "confidence": "confirmed" if fixed else "unverified",
                "reasoning": "The cited synthetic fixture supports the lifecycle assertion only; it contains no complete ISA obligations or real bin-hit measurements.",
                "conclusion": "Fixture change verified" if fixed else "ISA semantics remain unverified",
                "limitation": "Synthetic source cannot establish real extension correctness",
                "next_action": "Review the real specification and native coverage results",
                "findings": [], "basis": basis,
                "diagnostics": {identity: "unresolved"} if identity.startswith("diagnostic:") else {}})
            if confirmed and not fixed:
                judgments[-1].update(status="issues", confidence="confirmed", findings=[confirmed["id"]])
        return {"reviewer": "ai", "evidence_digest": evidence["review_digest"], "judgments": judgments}

    def write_final(self, value: dict) -> None:
        """Publish a final fixture with a fresh, complete after-evidence reassessment."""
        value["semantic_review"] = self.assess(value, "after")
        self.write("final.yaml", value)

    def audit(self) -> dict:
        """Collect deterministic evidence then fill the review using its actual findings."""
        assert self.checker("audit").do_check()[0]
        self.checker("audit").do_check(run_commands=True)
        guide = get_plugin().root / "Guide_Doc/ACT4_Extension_Review_Guide.md"
        examples = re.findall(r"```yaml\n(.*?)```", guide.read_text(), re.DOTALL)
        review = yaml.safe_load(examples[1])
        review.pop("obligations", None)
        for finding in review["findings"]:
            for field in ("classification", "diagnosis", "investigation"):
                finding.pop(field, None)
        review["post_assets"] = self.scope["assets"]
        evidence = json.loads((self.output / "evidence-before.json").read_text())
        review["traceability"] = [{"coverpoint": point, "obligation": "H boundary obligation",
            "testcases": [], "coverage": "unverified", "evidence": ["evidence-before.json"]}
            for point in evidence["coverpoints"]]
        review["changes"] = [{"findings": ["F1"], "paths": ["generators/H.py"],
                              "action": "Add missing boundary", "risk": "case count changes",
                              "validation_jobs": ["build"]}]
        review["semantic_review"] = self.assess(review)
        self.write("review.yaml", review)
        passed, result = self.checker("audit").do_check()
        assert passed, result
        return review

@pytest.mark.parametrize("outcome", ["installed", "present", "wrong_version", "install_failure", "missing_license"])
def test_environment_probe_install_and_verify(tmp_path: Path, outcome: str) -> None:
    """Install missing tools before dependent jobs and reject failed installation or probing."""
    harness = ReviewHarness(tmp_path)
    job = harness.scope["jobs"][-1]
    tool = harness.output / "tools/bin/act4-review-fixture-tool"
    tool.parent.mkdir(parents=True)
    job.update(probe=[str(tool)], expected_output=r"\A0\.13\.1\s*\Z")
    version = "0.14" if outcome == "wrong_version" else "0.13.1"
    script = f"#!{sys.executable}\nprint({version!r})\n"
    if outcome == "present":
        tool.write_text(script)
        tool.chmod(0o755)
        job["install"] = [sys.executable, "-c", "raise SystemExit('Installer must not run')"]
    elif outcome != "missing_license":
        job["install"] = [sys.executable, "-c",
            f"from pathlib import Path; target=Path('{{TOOLS}}/bin/act4-review-fixture-tool'); target.write_text({script!r}); target.chmod(0o755)"]
        if outcome == "install_failure":
            job["install"] = [sys.executable, "-c", "raise SystemExit(7)"]
    else:
        job["reason"] = "No licensed simulator installer/license; operator must provide both, then rerun"
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    record = evidence["jobs"][-1]
    if outcome in {"installed", "present"}:
        assert record["status"] == "passed"
        assert record["installed"] is (outcome == "installed")
        assert len(record["attempts"]) == (3 if outcome == "installed" else 1)
        assert all(item["status"] == "passed" for item in evidence["jobs"])
        if outcome == "installed":
            (harness.output / record["probe_log"]).write_text("forged")
            passed, error = harness.checker("audit").do_check()
            assert not passed and "probe log changed" in error["error"]
    else:
        assert record["status"] == "unavailable"
        assert all(item["status"] == "blocked" for item in evidence["jobs"][:-1])
        assert not (harness.output / "before-reference_model.log").exists()


@pytest.mark.parametrize("defect", ["unknown", "cycle", "no_environment", "no_generation", "no_elf", "wrong_provider", "missing_results", "empty_pattern", "escape_pattern", "bad_regex"])
def test_execution_dependency_contract(tmp_path: Path, defect: str) -> None:
    """Reject matrices that could execute without the correct environment and ELF prerequisites."""
    harness = ReviewHarness(tmp_path)
    jobs = harness.scope["jobs"]
    if defect == "unknown":
        jobs[0]["needs"] = ["absent"]
    elif defect == "cycle":
        jobs[-1]["needs"] = ["build"]
    elif defect == "no_environment":
        jobs[0]["needs"] = []
    elif defect == "no_generation":
        jobs[1]["needs"] = ["environment"]
    elif defect == "no_elf":
        jobs[1]["artifacts"] = []
    elif defect == "wrong_provider":
        jobs[2]["elf_inputs"] = ["generation"]
    elif defect == "missing_results":
        jobs[2]["artifacts"] = []
    elif defect == "empty_pattern":
        jobs[2]["artifacts"][0]["pass_pattern"] = ".*"
    elif defect == "escape_pattern":
        jobs[1]["artifacts"][1].update(path="generators", pattern="../../*.elf")
    else:
        jobs[-1]["expected_output"] = "["
    harness.write("scope.yaml", harness.scope)
    passed, error = harness.checker("audit").do_check()
    assert not passed, error


@pytest.mark.parametrize("output", ["PASS\n", "", "FAIL\n", "PASS\nPASS\n", "No tests found\n"])
def test_model_requires_real_nonzero_matching_test_results(tmp_path: Path, output: str) -> None:
    """A zero exit code is insufficient without one passing result per freshly built ELF."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][2]["argv"] = [sys.executable, "-c",
        f"from pathlib import Path; assert Path('fixture.elf').read_bytes().startswith(b'\\x7fELF'); Path('result.txt').write_text({output!r})"]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    model = evidence["jobs"][2]
    assert model["elf_count"] == 1
    assert (model["status"] == "passed") is (output == "PASS\n")


@pytest.mark.parametrize("build", ["missing", "empty", "text", "valid"])
def test_missing_elf_triggers_generation_and_build_before_execution(tmp_path: Path, build: str) -> None:
    """Run native generation and build automatically and block execution on invalid ELF output."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][1]["artifacts"] = [{"path": "built", "pattern": "**/*.elf", "kind": "elf", "min_count": 1}]
    content = {"empty": b"", "text": b"not ELF", "valid": b"\x7fELFfixture"}.get(build)
    code = "from pathlib import Path; assert Path('result.txt').is_file(); Path('built').mkdir()"
    if content is not None:
        code += f"; Path('built/H.elf').write_bytes({content!r})"
    harness.scope["jobs"][1]["argv"] = [sys.executable, "-c", code]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["jobs"][0]["status"] == "passed"
    assert evidence["jobs"][1]["status"] == ("passed" if build == "valid" else "failed")
    assert evidence["jobs"][2]["status"] == ("passed" if build == "valid" else "blocked")


def test_guide_prepared_scope_validates_against_current_contract(tmp_path: Path) -> None:
    """Validate the complete native preparation example without downloading its external tools."""
    harness = ReviewHarness(tmp_path)
    examples = re.findall(r"```yaml\n(.*?)```", (get_plugin().root / "Guide_Doc/ACT4_Extension_Review_Guide.md").read_text(), re.DOTALL)
    scope = yaml.safe_load(examples[-1])
    for name in {job["source"] for job in scope["jobs"]} | set(scope["assets"]["generators"]):
        path = harness.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Native preparation fixture\n")
    harness.write("scope.yaml", scope)
    passed, error = harness.checker("audit").do_check()
    assert passed, error


def test_native_failure_is_not_hidden_by_missing_elf(tmp_path: Path) -> None:
    """Preserve a failing build's exit status and log before secondary missing-output diagnostics."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][1]["argv"] = [sys.executable, "-c", "raise SystemExit(7)"]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    build = evidence["jobs"][1]
    assert build["exit_code"] == 7
    assert "status 7" in build["reason"]
    assert build["validation_error_count"] == 2
    assert all("missing" in item for item in build["validation_errors"])
    assert evidence["jobs"][2]["status"] == "blocked"


@pytest.mark.parametrize("outcome", ["failed", "timeout", "passed"])
def test_native_diagnostics_survive_checkout_cleanup(tmp_path: Path, outcome: str) -> None:
    """Retain signature diagnostics on every outcome and verify their bytes on reuse."""
    harness = ReviewHarness(tmp_path)
    build = harness.scope["jobs"][1]
    log_name = "work/rv64/build/priv/H/H_hfence-00.sig.log"
    script = ('from pathlib import Path; import time; '
              f'log=Path({log_name!r}); log.parent.mkdir(parents=True); '
              'log.write_text("FAILURE: 1\\n"); '
              f'print("Log file: {log_name}", flush=True); ')
    script += {"failed": "raise SystemExit(7)", "timeout": "time.sleep(10)",
               "passed": 'exec(Path("check.py").read_text())'}[outcome]
    build.update(argv=[sys.executable, "-c", script], timeout_seconds=1,
                 diagnostics=[{"path": "work/rv64/build", "pattern": "**/*.sig.log"}, {"path": "absent.log"}])
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    record = evidence["jobs"][1]
    assert record["status"] == outcome
    assert record["diagnostic_summary"]["saved_files"] == 1
    diagnostic = record["diagnostics"][0]
    saved = harness.output / diagnostic["path"]
    assert saved.read_text() == "FAILURE: 1\n"
    assert diagnostic["source_path"] == log_name
    assert not diagnostic["truncated"]
    assert not list(harness.output.glob("run-before-*"))
    assert not (harness.source / log_name).exists()
    if outcome != "passed":
        report = (harness.output / "review.md").read_text()
        assert diagnostic["path"] in report and f"Log file: {log_name}" in report
        assert "Blocked by: build" in report
    saved.write_text("forged diagnostic\n")
    passed, error = harness.checker("audit").do_check()
    assert not passed and diagnostic["path"] in error["error"]


def test_diagnostics_prioritize_native_failure_and_bound_storage(tmp_path: Path, monkeypatch) -> None:
    """Prefer the native failure's referenced file and explicitly describe saved tail excerpts."""
    monkeypatch.setattr(act4_review_checker, "DIAGNOSTIC_FILE_LIMIT", 1)
    monkeypatch.setattr(act4_review_checker, "DIAGNOSTIC_BYTE_LIMIT", 5)
    harness = ReviewHarness(tmp_path)
    build = harness.scope["jobs"][1]
    build.update(argv=[sys.executable, "-c", 'from pathlib import Path; '
        'Path("aaa.log").write_text("unrelated"); Path("zzz.log").write_text("header:ERROR"); '
        'print("Log file: zzz.log"); raise SystemExit(7)'],
        diagnostics=[{"path": "aaa.log"}, {"path": "zzz.log"}])
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    record = evidence["jobs"][1]
    assert record["exit_code"] == 7
    assert record["diagnostic_summary"] == {
        "matched_files": 2, "saved_files": 1, "omitted_files": 1, "truncated_files": 1}
    diagnostic = record["diagnostics"][0]
    assert diagnostic["source_path"] == "zzz.log"
    assert diagnostic["source_size"] == 12 and diagnostic["truncated"]
    assert (harness.output / diagnostic["path"]).read_text() == "ERROR"
    report = (harness.output / "review.md").read_text()
    assert "tail excerpt" in report and "Diagnostic file limit reached" in report


def test_old_optional_diagnostics_are_not_execution_evidence(tmp_path: Path) -> None:
    """Delete frozen old diagnostic output and accept an absent optional file on success."""
    harness = ReviewHarness(tmp_path)
    old_log = harness.source / "old.sig.log"
    old_log.write_text("old failure\n")
    harness.scope["jobs"][1]["diagnostics"] = [{"path": "old.sig.log"}]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    record = json.loads((harness.output / "evidence-before.json").read_text())["jobs"][1]
    assert record["status"] == "passed" and record["diagnostics"] == []
    assert old_log.read_text() == "old failure\n"


@pytest.mark.parametrize("selector", [
    {"path": "../outside.log"}, {"path": "work", "pattern": "../*.log"},
    {"path": "work", "pattern": "/tmp/*.log"}, {"path": "log", "min_count": 0},
])
def test_diagnostic_selectors_reject_unsafe_or_ambiguous_paths(tmp_path: Path, selector: dict) -> None:
    """Keep diagnostic selectors inside the command checkout with one canonical shape."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][1]["diagnostics"] = [selector]
    harness.write("scope.yaml", harness.scope)
    passed, error = harness.checker("audit").do_check()
    assert not passed and error["error_code"] == "act4_review_contract"


def test_generated_diagnostic_symlink_cannot_escape_checkout(tmp_path: Path) -> None:
    """Reject a command-produced diagnostic symlink before reading an external file."""
    harness = ReviewHarness(tmp_path)
    outside = tmp_path / "external.log"
    outside.write_text("external data\n")
    build = harness.scope["jobs"][1]
    build.update(argv=[sys.executable, "-c",
        f'from pathlib import Path; Path("escape.log").symlink_to({str(outside)!r})'],
        diagnostics=[{"path": "escape.log"}])
    harness.write("scope.yaml", harness.scope)
    assert harness.checker("audit").do_check()[0]
    passed, error = harness.checker("audit").do_check(run_commands=True)
    assert not passed and "escapes" in error["error"]
    assert not (harness.output / "diagnostics-before/build/escape.log").exists()


@pytest.mark.parametrize("ignored", [True, False])
def test_native_git_lint_includes_frozen_untracked_assets(tmp_path: Path, ignored: bool) -> None:
    """Index all frozen source inputs in command clones without staging the original input."""
    harness = ReviewHarness(tmp_path)
    asset = "generators/untracked.py"
    (harness.source / asset).write_text('"""Existing local generator input."""\n')
    if ignored:
        (harness.source / ".gitignore").write_text(f"{asset}\n")
    harness.scope["assets"]["generators"].append(asset)
    lint = harness.scope["jobs"][4]
    lint.update(argv=["git", "ls-files", "--error-unmatch", "--", asset], artifacts=[])
    harness.write("scope.yaml", harness.scope)
    status_before = subprocess.check_output(["git", "-C", str(harness.source), "status", "--porcelain"])
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["jobs"][4]["status"] == "passed"
    assert asset in (harness.output / "before-lint.log").read_text()
    assert subprocess.check_output(["git", "-C", str(harness.source), "status", "--porcelain"]) == status_before
    assert asset not in subprocess.check_output(["git", "-C", str(harness.source), "ls-files"], text=True).splitlines()


def test_scope_commentary_reuses_evidence_and_allows_repair(tmp_path: Path, monkeypatch) -> None:
    """Allow corrected explanations and current repair plans without native reruns."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    evidence_bytes = (harness.output / "evidence-before.json").read_bytes()
    harness.scope["references"].append("Clarified manual revision and obligation")
    harness.scope["discovery"].append("Clarified why unrelated assets were excluded")
    harness.write("scope.yaml", harness.scope)

    def reject_execution(*args, **kwargs):
        """Fail if a report-only Check unexpectedly launches a native command."""
        pytest.fail("Commentary edits must not rerun native commands")

    monkeypatch.setattr(act4_review_checker, "execute_command", reject_execution)
    passed, result = harness.checker("audit").do_check()
    assert passed, result
    assert (harness.output / "evidence-before.json").read_bytes() == evidence_bytes
    passed, error = harness.checker("repair").do_check()
    assert passed, error
    assert (harness.output / "candidate").is_dir()


@pytest.mark.parametrize("change", ["assets", "jobs"])
def test_execution_contract_edits_require_fresh_evidence(tmp_path: Path, change: str) -> None:
    """Keep asset membership and native command changes in the execution fingerprint."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    if change == "assets":
        harness.scope["assets"]["generators"].append("check.py")
    else:
        harness.scope["jobs"][0]["argv"].append("--new-option")
    harness.write("scope.yaml", harness.scope)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "evidence is stale" in error["error"]


def test_explicit_native_rerun_does_not_reuse_cached_commands(tmp_path: Path, monkeypatch) -> None:
    """Treat run_commands=true as an explicit fresh execution even when all inputs match."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    original = act4_review_checker.execute_command
    commands = []

    def track_execution(argv, *args, **kwargs):
        """Observe real command execution while preserving all subprocess behavior."""
        commands.append(argv)
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(act4_review_checker, "execute_command", track_execution)
    passed, report = harness.checker("audit").do_check(run_commands=True)
    assert not passed and "semantic_review.evidence_digest" in report["error"]
    assert len(commands) == len(harness.scope["jobs"])
    review["semantic_review"] = harness.assess(review)
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check()[0]


def test_diagnostic_cleanup_cannot_delete_elf_inputs(tmp_path: Path) -> None:
    """Protect freshly built execution inputs from overlapping diagnostic output selectors."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][2]["diagnostics"] = [{"path": "fixture.elf"}]
    harness.write("scope.yaml", harness.scope)
    assert harness.checker("audit").do_check()[0]
    passed, error = harness.checker("audit").do_check(run_commands=True)
    assert not passed and "must not overwrite its ELF inputs" in error["error"]


def test_diagnostics_cannot_prove_measured_coverage(tmp_path: Path) -> None:
    """Keep optional diagnostic files outside the evidence accepted for measured coverpoints."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.scope["jobs"][1]["diagnostics"] = [{"path": "result.txt"}]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    diagnostic = evidence["jobs"][1]["diagnostics"][0]["path"]
    review["traceability"][0].update(coverage="measured", testcases=["H-00.S::case_1"],
                                     evidence=[diagnostic])
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "Measured coverpoints must reference retained coverage artifacts" in error["error"]


def test_compact_reports_keep_counts_and_link_complete_evidence(tmp_path: Path) -> None:
    """Present model counts separately from build summaries and avoid expanding large asset state."""
    harness = ReviewHarness(tmp_path)
    for number in range(80):
        name = f"H-{number:02d}.S"
        (harness.source / name).write_text("entry:\n  nop\n")
        harness.scope["assets"]["test_cases"].append(name)
    script = harness.source / "check.py"
    script.write_text(script.read_text() + 'print("243 succeeded, 1 failed (build tasks)")\n')
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    report = (harness.output / "review.md").read_text()
    assert "| build | rv64 | build | passed | 1 | — |" in report
    assert "| reference_model | rv64 | reference_model | passed | 1 | 1 |" in report
    assert "243" not in report
    assert "Build task counts are not executed test counts" in report
    assert "[evidence-before.json](evidence-before.json)" in report
    assert "reachability:" not in report and "H-79.S" not in report
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "No source changes needed",
        "findings": [{"id": "F1", "status": "deferred", "reason": "Needs root-cause confirmation",
                      "next_action": "Obtain the pinned specification and confirm the root cause",
                      "evidence": ["review.yaml"]}], "ci_passed": True,
        "remaining_risks": ["Deferred finding"], "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check()
    assert passed, result
    final_report = (harness.output / "final.md").read_text()
    assert "[review.md](review.md)" in final_report
    assert "[evidence-after.json](evidence-after.json)" in final_report
    assert "Original Review\n" not in final_report and "reachability:" not in final_report
    assert len(final_report) < len((harness.output / "evidence-after.json").read_text())
    assert all("artifacts" not in item for item in result["ci"])


def test_empty_proposal_preserves_sources(tmp_path: Path) -> None:
    """Keep unresolved findings reportable while rejecting undeclared source changes."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check()[0]
    assert "No source changes are included" in (harness.output / "review.md").read_text()
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/generators/H.py").write_text("undeclared\n")
    passed, error = harness.checker("repair").do_check()
    assert not passed and "outside review.changes paths" in error["error"]


def test_audit_preflight_cannot_complete_without_evidence_and_review(tmp_path: Path) -> None:
    """Freeze a valid scope on Check without allowing an empty audit to Complete."""
    harness = ReviewHarness(tmp_path)
    checker = harness.checker("audit")
    passed, result = checker.do_check()
    assert passed, result
    assert (harness.output / "baseline.json").is_file()
    passed, result = checker.do_check(is_complete=True)
    assert not passed and "collect before evidence" in result["error"]
    checker.do_check(run_commands=True)
    passed, result = checker.do_check(is_complete=True)
    assert not passed and "review.yaml" in result["error"]
    assert not (harness.output / "candidate").exists()


@pytest.mark.parametrize("repair_supported", [True, False])
@pytest.mark.parametrize("status", ["deferred", "not_fixed"])
def test_information_gaps_allow_partial_or_unchanged_delivery(tmp_path: Path,
        repair_supported: bool, status: str) -> None:
    """Deliver supported fixes while retaining every information gap without speculative edits."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["findings"].append({**review["findings"][0], "id": "F2",
        "problem": "Target trap behavior is unspecified",
        "recommendation": "Obtain the target configuration and expected trap behavior before editing"})
    if not repair_supported:
        review["changes"] = []
    review["semantic_review"] = harness.assess(review)
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check(is_complete=True)[0]
    checker = harness.checker("repair")
    assert checker.do_check()[0]
    if repair_supported:
        (harness.output / "candidate/generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 2\n')
    assert checker.do_check(run_commands=True)[0]
    dispositions = [{"id": finding["id"], "status": status,
        "reason": "Target configuration and expected trap behavior are missing; changing the assertions would be speculative",
        "next_action": "Obtain the target configuration and normative trap behavior, then reproduce the case",
        "evidence": ["review.yaml", "evidence-after.json"]} for finding in review["findings"]]
    if repair_supported:
        dispositions[0].update(status="fixed", reason="Applied the supported generator repair")
    final = {"schema_version": 1, "suite": "H", "summary": "Delivered supported work with explicit information gaps",
        "findings": dispositions, "ci_passed": True,
        "remaining_risks": ["Unresolved findings lack target configuration and normative trap behavior"],
        "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    report = (harness.output / "final.md").read_text()
    assert "Target configuration and expected trap behavior are missing" in report
    assert "Next action (agent):" in report and f" / {status}**" in report
    assert bool((harness.output / "changes.patch").read_text()) is repair_supported
    assert "VALUE = 1" in (harness.source / "generators/H.py").read_text()
    dispositions[-1].pop("next_action")
    harness.write_final(final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert not passed and "F2 needs next_action" in result["error"]


def test_clean_review_delivers_an_empty_patch(tmp_path: Path) -> None:
    """Complete a review with no proposed defects or edits while preserving verification limits."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review.update(findings=[], changes=[])
    review["semantic_review"] = harness.assess(review)
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check(is_complete=True)[0]
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "No source changes required",
        "findings": [], "ci_passed": True, "remaining_risks": ["Synthetic assets lack complete ISA coverage"],
        "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    assert not (harness.output / "changes.patch").read_text()


def test_repair_plan_can_be_updated_without_recollecting_unchanged_evidence(tmp_path: Path) -> None:
    """Validate new declared paths and retain a current review while allowing automatic repair."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    assert harness.checker("repair").do_check()[0]
    before = (harness.output / "evidence-before.json").read_bytes()
    review["changes"][0]["paths"].append("generators/boundary.txt")
    review["changes"][0]["action"] = "Document the boundary alongside its generator"
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/generators/boundary.txt").write_text("Boundary behavior from the frozen source\n")
    passed, result = harness.checker("repair").do_check()
    assert passed and result["changed_paths"] == ["generators/boundary.txt"], result
    assert (harness.output / "evidence-before.json").read_bytes() == before


def test_review_and_automatic_repair_end_to_end(tmp_path: Path) -> None:
    """Preserve original sources, execute real commands, and produce an applicable patch."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    checker = harness.checker("repair")
    assert checker.do_check()[0]
    candidate = harness.output / "candidate/generators/H.py"
    candidate.write_text('"""Native H generator fixture."""\nVALUE = 2\n')
    assert checker.do_check(run_commands=True)[0]
    assert checker.do_check(is_complete=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "Fixed one finding",
        "findings": [{"id": "F1", "status": "fixed", "reason": "Added case", "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Synthetic fixture has incomplete ACT4 mappings"], "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check()
    assert passed, result
    assert "VALUE = 1" in (harness.source / "generators/H.py").read_text()
    subprocess.run(["git", "-C", str(harness.source), "apply", "--check", str(harness.output / "changes.patch")], check=True)
    assert (harness.output / "final.md").read_text().startswith("\n# ")


@pytest.mark.parametrize("missing", ["review", "evidence", "semantic_review"])
def test_repair_requires_complete_review_evidence(tmp_path: Path, missing: str) -> None:
    """Prepare candidates only after validating a complete current review and its evidence."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    if missing == "review":
        (harness.output / "review.yaml").unlink()
    elif missing == "evidence":
        (harness.output / "evidence-before.json").unlink()
    else:
        review.pop("semantic_review")
        harness.write("review.yaml", review)
    passed, result = harness.checker("repair").do_check()
    assert not passed, result
    assert not (harness.output / "candidate").exists()


@pytest.mark.parametrize("drift", ["source", "baseline", "scope", "log", "artifact", "candidate"])
def test_review_rejects_drift_and_undeclared_scope(tmp_path: Path, drift: str) -> None:
    """Invalidate stale evidence and reject candidate changes outside the repair plan."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    assert harness.checker("repair").do_check()[0]
    if drift in {"source", "baseline"}:
        root = harness.source if drift == "source" else harness.output / "baseline"
        (root / "generators/H.py").write_text("changed\n")
    elif drift == "scope":
        harness.scope["jobs"][0]["argv"].append("new")
        harness.write("scope.yaml", harness.scope)
    elif drift == "log":
        (harness.output / "before-build.log").write_text("forged pass")
    elif drift == "artifact":
        (harness.output / "artifacts-before/build/result.txt").write_text("forged coverage")
    elif drift == "candidate":
        (harness.output / "candidate/README.md").write_text("undeclared")
    passed, result = harness.checker("repair").do_check()
    assert not passed, result


@pytest.mark.parametrize("failure", ["failed", "missing_tool", "missing_artifact", "timeout"])
def test_failed_ci_can_be_reviewed_but_cannot_be_claimed_passed(tmp_path: Path, failure: str) -> None:
    """Collect bounded failure evidence without blocking an honest review report."""
    harness = ReviewHarness(tmp_path)
    job = harness.scope["jobs"][0]
    if failure == "failed":
        job["argv"] = [sys.executable, "-c", "raise SystemExit(3)"]
    elif failure == "missing_tool":
        job["argv"] = ["act4-nonexistent-command"]
    elif failure == "timeout":
        job["argv"] = [sys.executable, "-c", "import time; time.sleep(10)"]
        job["timeout_seconds"] = 1
    else:
        job["artifacts"][0]["path"] = "missing.txt"
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["jobs"][0]["status"] in {"failed", "timeout", "unavailable"}
    review["checks"]["ci"]["status"] = "passed"
    harness.write("review.yaml", review)
    assert not harness.checker("audit").do_check()[0]


def test_guide_complete_no_repair_examples(tmp_path: Path) -> None:
    """Run all complete runtime guide artifacts through the actual stage gates."""
    harness = ReviewHarness(tmp_path)
    examples = re.findall(r"```yaml\n(.*?)```", (get_plugin().root / "Guide_Doc/ACT4_Extension_Review_Guide.md").read_text(), re.DOTALL)
    harness.write("scope.yaml", yaml.safe_load(examples[0]))
    assert harness.checker("audit").do_check()[0]
    harness.checker("audit").do_check(run_commands=True)
    review = yaml.safe_load(examples[1])
    review["semantic_review"]["evidence_digest"] = json.loads((harness.output / "evidence-before.json").read_text())["review_digest"]
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check()
    assert passed, result
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = yaml.safe_load(examples[3])
    final["semantic_review"]["evidence_digest"] = json.loads((harness.output / "evidence-after.json").read_text())["review_digest"]
    harness.write("final.yaml", final)
    passed, result = harness.checker("final").do_check()
    assert passed, result
    assert not (harness.output / "changes.patch").read_text()


@pytest.mark.parametrize("skill_enabled", [True, False])
def test_review_workflow_initializes_without_skill_dependency(tmp_path: Path, monkeypatch, skill_enabled: bool) -> None:
    """Initialize two automatic stages and complete task guidance in both skill modes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    loaded = load_plugin(str(Path(__file__).resolve().parents[1]))
    workflow = next(item for item in loaded.plugin.workflows if item.name == "extension-review")
    config = yaml.safe_load(workflow.config_file.read_text())
    registry = create_plugin_checker_registry([LoadedPlugin(loaded.plugin, loaded.plugin.name, "test")])
    for stage in config["stage"]:
        for gate in stage["checker"]:
            registry[gate["clss"]](**gate["args"])
    agent = VerifyAgent(workspace=str(tmp_path), dut_name="H", output="reports",
        workflow_config_file=str(workflow.config_file), plugins=[loaded],
        plugin_workflow=f"{loaded.plugin.name}:{workflow.name}",
        template_context_factory=workflow.template_context_factory,
        plugin_guide_doc_paths=[str(path) for path in workflow.guide_doc_paths],
        cfg_override=[{"backend.key_name": "blank"}, {"skill.use_skill": skill_enabled}, {"langfuse.enable": False}],
        no_embed_tools=True, no_history=True)
    try:
        assert [stage.name for stage in agent.stage_manager.stages] == ["review_audit", "review_repair"]
        assert all(not stage.is_hmcheck_needed() for stage in agent.stage_manager.stages)
        assert all(not stage.skill_list for stage in agent.stage_manager.stages)
        audit = agent.stage_manager.stages[0]
        final = agent.stage_manager.stages[-1]
        assert "semantic_review" in str(audit.task()) and "review_tasks" in str(audit.task())
        assert "finding:<ID>" in str(final.task())
        if not skill_enabled:
            assert not (tmp_path / ".ucagent/skills").exists()
        assert agent.cfg.write_dirs == ["reports"]
        assert agent.cfg.un_write_dirs == ["Guide_Doc"]
        assert (tmp_path / "Guide_Doc/ACT4_Extension_Review_Guide.md").is_file()
        from ucagent.tools.fileops import is_file_writeable
        assert not is_file_writeable("riscv-arch-test/generators/H.py", agent.cfg.un_write_dirs, agent.cfg.write_dirs)[0]
    finally:
        agent.exit()


@pytest.mark.parametrize("skill_enabled", [True, False])
@pytest.mark.parametrize("prepare_before_restart", [True, False])
@pytest.mark.parametrize("repair_supported", [True, False])
def test_real_complete_advances_automatically_and_resumes_repairs(tmp_path: Path, monkeypatch,
        skill_enabled: bool, prepare_before_restart: bool, repair_supported: bool) -> None:
    """Complete both real stages across restart without human input in either skill mode."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    if not repair_supported:
        review["changes"] = []
        harness.write("review.yaml", review)
    loaded = load_plugin(str(Path(__file__).resolve().parents[1]))
    workflow = next(item for item in loaded.plugin.workflows if item.name == "extension-review")
    options = dict(workspace=str(tmp_path), dut_name="H", output="reports",
        workflow_config_file=str(workflow.config_file), plugins=[loaded],
        plugin_workflow=f"{loaded.plugin.name}:{workflow.name}",
        template_context_factory=workflow.template_context_factory,
        plugin_guide_doc_paths=[str(path) for path in workflow.guide_doc_paths],
        cfg_override=[{"backend.key_name": "blank"}, {"skill.use_skill": skill_enabled},
                      {"langfuse.enable": False}], no_embed_tools=True, no_history=False)
    agent = VerifyAgent(**options)
    try:
        manager = agent.stage_manager
        manager.data.update(harness.data)
        gate = manager.stages[0]
        gate.on_init()
        gate.set_reference_file_status({name: "Readed" for name in gate.reference_files})
        gate.meta_set_journal({"summary": "Review and proposal delivered"})
        gate.need_pass_llm_suggestion = False
        result = manager.complete(timeout=30)
        assert result["complete"], result
        assert not agent._need_human
        assert manager.stage_index == 1
        assert not (harness.output / "candidate").exists()
        if prepare_before_restart:
            passed, result = manager.stages[1].checker[0].do_check()
            assert passed, result
            if repair_supported:
                (harness.output / "candidate/generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 2\n')
        manager.save_stage_info()
    finally:
        agent.exit()
    restored = VerifyAgent(**options)
    try:
        manager = restored.stage_manager
        assert manager.stage_index == 1
        gate = manager.stages[1]
        assert all(not stage.is_hmcheck_needed() for stage in manager.stages)
        assert gate.checker[0].do_check()[0]
        candidate = harness.output / "candidate/generators/H.py"
        if prepare_before_restart and repair_supported:
            assert "VALUE = 2" in candidate.read_text()
        elif repair_supported:
            candidate.write_text('"""Native H generator fixture."""\nVALUE = 2\n')
        gate.set_reference_file_status({name: "Readed" for name in gate.reference_files})
        gate.meta_set_journal({"summary": "Repaired candidate; validate and deliver the final report"})
        gate.need_pass_llm_suggestion = False
        result = manager.check(timeout=30, stage_args={"run_commands": True})
        assert not result["check_pass"], result
        assert (harness.output / "evidence-after.json").is_file()
        result = manager.complete(timeout=30)
        assert not result.get("complete", result.get("check_pass")), result
        assert manager.stage_index == 1 and not restored._need_human
        harness.write_final({"schema_version": 1, "suite": "H", "summary": "Review and repair completed with limitations",
            "findings": [{"id": "F1", "status": "fixed" if repair_supported else "deferred",
                "reason": "Added case" if repair_supported else "Missing specification prevents a reliable repair",
                "next_action": "Obtain the pinned specification and reproduce the missing boundary",
                "evidence": ["evidence-after.json"]}],
            "ci_passed": True, "remaining_risks": ["Synthetic fixture has incomplete ACT4 mappings"],
            "coverage_changes": [], "traceability": []})
        result = manager.complete(timeout=30)
        assert result["complete"], result
        assert all(stage.is_completed() for stage in manager.stages)
        assert not restored._need_human
        assert (harness.output / "final.md").is_file()
        assert bool((harness.output / "changes.patch").read_text()) is repair_supported
        assert "VALUE = 1" in (harness.source / "generators/H.py").read_text()
        if not skill_enabled:
            assert not (tmp_path / ".ucagent/skills").exists()
    finally:
        restored.exit()


@pytest.mark.parametrize("discover", [True, False])
def test_review_coverage_discovery_respects_exact_scope(tmp_path: Path, discover: bool) -> None:
    """Keep unrelated extension coverage out of an explicit empty review inventory."""
    path = tmp_path / "coverpoints/priv/Other_coverage.svh"
    path.parent.mkdir(parents=True)
    path.write_text("covergroup Other_cg;\ncp: coverpoint flag;\nendgroup\n")
    checker = ACT4AssetChecker(act4_root=str(tmp_path), checker_type="coverage", discover_coverage=discover)
    _, result = checker.do_check()
    assert result["report"]["checks"]["coverage_files"] == int(discover)


@pytest.mark.parametrize("defect", ["omitted", "duplicate", "measured_without_artifact", "false_pass"])
def test_coverpoint_traceability_rejects_missing_and_invented_evidence(tmp_path: Path, defect: str) -> None:
    """Require one record per defined point and retain the static/measured distinction."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    assert review["traceability"][0]["coverpoint"] == "H_cg/cp"
    if defect == "omitted":
        review["traceability"] = []
    elif defect == "duplicate":
        review["traceability"] *= 2
    elif defect == "false_pass":
        review["checks"]["test_coverage"]["status"] = "passed"
    else:
        review["traceability"][0].update(coverage="measured", testcases=["H-00.S::case_1"])
    harness.write("review.yaml", review)
    assert not harness.checker("audit").do_check()[0]


def test_new_declared_coverage_is_checked_and_reported(tmp_path: Path) -> None:
    """Revalidate new assets and require complete post-repair coverpoint accounting."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"][0]["paths"].append("H.svh")
    review["post_assets"]["coverage"] = ["H.svh"]
    harness.write("review.yaml", review)
    checker = harness.checker("repair")
    assert checker.do_check()[0]
    (harness.output / "candidate/H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    assert checker.do_check(run_commands=True)[0]
    evidence = json.loads((harness.output / "evidence-after.json").read_text())
    assert evidence["coverpoints"] == ["H_cg/cp"]
    final = {"schema_version": 1, "suite": "H", "summary": "Added coverage; runtime relationship unverified",
        "findings": [{"id": "F1", "status": "fixed", "reason": "Added missing definition", "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Coverage relation remains unverified"],
        "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    assert not harness.checker("final").do_check()[0]
    final["traceability"] = [{"coverpoint": "H_cg/cp", "obligation": "H boundary", "testcases": [],
                              "coverage": "unverified", "evidence": ["evidence-after.json"]}]
    harness.write_final(final)
    assert not harness.checker("final").do_check()[0]
    final["coverage_changes"] = [{"coverpoint": "H_cg/cp", "reason": "Added the missing sampling obligation"}]
    harness.write_final(final)
    passed, result = harness.checker("final").do_check()
    assert passed, result


@pytest.mark.parametrize("kind", ["new", "deleted", "mode", "crlf", "no_newline", "space"])
def test_review_patch_preserves_source_forms(tmp_path: Path, kind: str) -> None:
    """Verify patch applicability for additions, removals, modes and exact text bytes."""
    harness = ReviewHarness(tmp_path)
    name = "extra file.txt" if kind == "space" else "extra.txt"
    if kind != "new":
        (harness.source / name).write_bytes(b"old\r\n" if kind == "crlf" else b"old\n")
    review = harness.audit()
    review["changes"][0]["paths"] = [name]
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check()[0]
    target = harness.output / "candidate" / name
    if kind == "deleted":
        target.unlink()
    elif kind == "mode":
        target.chmod(0o755)
    else:
        target.write_bytes(b"new\r\n" if kind == "crlf" else b"new" if kind == "no_newline" else b"new\n")
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "Text repair",
        "findings": [{"id": "F1", "status": "fixed", "reason": "Applied declared change", "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Fixture is incomplete ACT4"], "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check()
    assert passed, result
    subprocess.run(["git", "-C", str(harness.source), "apply", "--check", str(harness.output / "changes.patch")], check=True)
    if kind == "crlf":
        assert b"-old\r\n+new\r\n" in (harness.output / "changes.patch").read_bytes()


def test_preexisting_candidate_cannot_smuggle_source_changes(tmp_path: Path) -> None:
    """Reject candidate trees that were not prepared from the frozen baseline."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    (harness.output / "candidate").mkdir()
    passed, result = harness.checker("repair").do_check()
    assert not passed and "not prepared from the frozen baseline" in result["error"]


def test_validation_cannot_reuse_a_stale_artifact(tmp_path: Path) -> None:
    """Require every declared output to be regenerated by its associated job."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][1]["argv"] = [sys.executable, "-c", "pass"]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["jobs"][0]["status"] == "passed"
    assert evidence["jobs"][1]["status"] == "failed"
    assert "missing" in evidence["jobs"][1]["reason"]


@pytest.mark.parametrize("field,value", [
    ("summary", True), ("check_evidence", True), ("check_conclusion", 1),
    ("finding_location", True), ("finding_evidence", "scope.yaml"),
    ("finding_problem", {"text": "missing"}), ("finding_recommendation", 1),
    ("change_findings", [{"id": "F1"}]), ("change_paths", [True]),
    ("change_action", True), ("change_risk", 1), ("change_jobs", [["build"]]),
    ("trace_coverpoint", ["H_cg/cp"]), ("trace_obligation", True),
    ("trace_evidence", [True]), ("trace_testcases", [False]),
])
def test_review_rejects_nontextual_scalar_evidence(tmp_path: Path, field: str, value) -> None:
    """Reject scalar/coerced evidence and malformed identities with contract diagnostics."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    if field == "summary":
        review[field] = value
    elif field.startswith("check_"):
        review["checks"]["ci"][field.removeprefix("check_")] = value
    elif field.startswith("finding_"):
        review["findings"][0][field.removeprefix("finding_")] = value
    elif field.startswith("change_"):
        key = field.removeprefix("change_")
        review["changes"][0]["validation_jobs" if key == "jobs" else key] = value
    else:
        review["traceability"] = [{"coverpoint": "H_cg/cp", "obligation": "H obligation",
            "evidence": ["evidence-before.json"], "testcases": [], "coverage": "unverified"}]
        review["traceability"][0][field.removeprefix("trace_")] = value
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check()
    assert not passed and result["error_code"] == "act4_review_contract"
    assert "unhashable" not in result["error"]


@pytest.mark.parametrize("field,value", [
    ("summary", True), ("findings", [{"id": ["F1"]}]),
    ("remaining_risks", [False]), ("evidence", True), ("reason", 1),
    ("next_action", None), ("next_action", " "), ("next_action", True), ("next_action", 1),
    ("coverage_changes", [{"coverpoint": "H_cg/cp", "reason": True}]),
])
def test_final_rejects_scalar_explanations(tmp_path: Path, field: str, value) -> None:
    """Reject fabricated final evidence and risks even when CI really succeeded."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "No safe source repair available",
        "findings": [{"id": "F1", "status": "deferred", "reason": "Awaiting assets",
                      "next_action": "Obtain the complete authoritative assets",
                      "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Finding F1 is deferred"],
        "coverage_changes": [], "traceability": []}
    if field in {"evidence", "reason", "next_action"}:
        final["findings"][0][field] = value
    else:
        final[field] = value
    harness.write_final(final)
    passed, result = harness.checker("final").do_check()
    assert not passed and result["error_code"] == "act4_review_contract"
    assert "unhashable" not in result["error"]


@pytest.mark.parametrize("initialized", [True, False])
def test_review_submodules_are_frozen_and_available_to_native_jobs(tmp_path: Path, initialized: bool) -> None:
    """Freeze initialized submodules and reject missing modules rather than omitting them."""
    harness = ReviewHarness(tmp_path)
    module_source = tmp_path / "module-source"
    subprocess.run(["git", "init", "-q", str(module_source)], check=True)
    (module_source / "input.txt").write_text("committed module input\n")
    subprocess.run(["git", "-C", str(module_source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(module_source), "-c", "user.name=Test", "-c",
                    "user.email=test@example.org", "commit", "-qm", "module fixture"], check=True)
    subprocess.run(["git", "-C", str(harness.source), "-c", "protocol.file.allow=always",
                    "submodule", "add", "-q", str(module_source), "deps/module"], check=True)
    if not initialized:
        subprocess.run(["git", "-C", str(harness.source), "submodule", "deinit", "-f", "deps/module"], check=True)
        passed, result = harness.checker("audit").do_check()
        assert not passed and "Initialize" in result["error"]
        return
    (harness.source / "deps/module/input.txt").write_text("dirty module input\n")
    (harness.source / "check.py").write_text('from pathlib import Path\n'
        'assert Path("deps/module/input.txt").read_text() == "dirty module input\\n"\n'
        'Path("result.txt").write_text("real submodule input checked\\nPASS\\n")\n'
        'Path("fixture.elf").write_bytes(b"\\x7fELFfixture")\n')
    harness.audit()
    baseline = json.loads((harness.output / "baseline.json").read_text())
    assert "deps/module" in baseline["submodules"]
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert all(job["status"] == "passed" for job in evidence["jobs"])
    (harness.source / "deps/module/input.txt").write_text("changed module input\n")
    passed, result = harness.checker("audit").do_check()
    assert not passed and "Input checkout" in result["error"]


@pytest.mark.parametrize("escape", ["asset", "cwd", "symlink"])
def test_review_rejects_escaping_input_paths(tmp_path: Path, escape: str) -> None:
    """Reject traversal and external symlink inputs before collecting any evidence."""
    harness = ReviewHarness(tmp_path)
    if escape == "asset":
        harness.scope["assets"]["test_plans"] = ["../external.md"]
    elif escape == "cwd":
        harness.scope["jobs"][0]["cwd"] = "../outside"
    else:
        external = tmp_path / "external.py"
        external.write_text("EXTERNAL = True\n")
        (harness.source / "generators/link.py").symlink_to(external)
        harness.scope["assets"]["generators"].append("generators/link.py")
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check()
    assert not passed and result["error_code"] == "act4_review_contract"
    assert not (harness.output / "baseline").exists()


@pytest.mark.parametrize("extension,content,check", [
    ("yaml", "items: [", "asset_yaml_schema"),
    ("json", '{"items":', "asset_json_schema"),
    ("py", "def broken(:", "asset_python_syntax"),
])
def test_review_reuses_format_checks_and_queues_diagnostics(tmp_path: Path, extension: str, content: str, check: str) -> None:
    """Retain malformed-plan facts and require AI adjudication without blocking honest audit delivery."""
    harness = ReviewHarness(tmp_path)
    name = f"plan.{extension}"
    (harness.source / name).write_text(content)
    harness.scope["assets"]["test_plans"] = [name]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert not evidence["static_passed"]
    assert any(item.get("check") == check for item in evidence["review_tasks"].values())
    expected = set(evidence["review_tasks"]) | {f"finding:{item['id']}" for item in review["findings"]} | {f"obligation:{item['id']}" for item in review["obligations"]}
    assert {task for item in review["semantic_review"]["judgments"] for task in item["tasks"]} == expected
    assert harness.checker("audit").do_check(is_complete=True)[0]


@pytest.mark.parametrize("generated", [True, False])
@pytest.mark.parametrize("condition", ["reachable", "impossible", "unknown", "unresolved", "broken"])
def test_review_links_native_descriptors_conservatively(tmp_path: Path, generated: bool, condition: str) -> None:
    """Use the existing conditional parser on both declared and freshly generated assembly."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag { bins v = {1}; }\nendgroup\n")
    harness.scope["assets"]["coverage"] = ["H.svh"]
    source = 'case_1_str: .string "test: H; cg: H_cg; cp: cp; bin: v"\n'
    if condition != "unresolved":
        prefix = {"reachable": "", "impossible": "#if 0\n", "unknown": "#ifdef FEATURE_H\n", "broken": "#if 1\n"}[condition]
        source += prefix + "case_1:\n  nop\n"
        if prefix and condition != "broken":
            source += "#endif\n"
    if generated:
        script = harness.source / "check.py"
        script.write_text(script.read_text() + f'Path("H-00.S").write_text({source!r})\n')
        harness.scope["jobs"][0]["artifacts"].append({"path": "H-00.S", "kind": "generated"})
        retained = "artifacts-before/generation/H-00.S"
    else:
        (harness.source / "H-00.S").write_text(source)
        harness.scope["assets"]["test_cases"] = ["H-00.S"]
        retained = "baseline/H-00.S"
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert set(evidence["reachability"]) == {retained}
    assert f"reachability:{retained}" in evidence["review_tasks"] if condition != "reachable" else f"reachability:{retained}" not in evidence["review_tasks"]
    assert bool(evidence["testcase_links"]) is (condition == "reachable")
    detail = evidence["review_tasks"]["point:H_cg/cp"]
    assert detail["path"] == "baseline/H.svh" and detail["line"] == 2
    assert detail["bins"] == ["v"]
    review["traceability"][0].update(coverage="static", testcases=["H-00.S::case_1"], evidence=[retained])
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert passed is (condition == "reachable"), error
    if condition == "reachable":
        review["traceability"][0]["testcases"] = ["H-00.S::invented"]
        harness.write("review.yaml", review)
        assert not harness.checker("audit").do_check()[0]


def test_review_queues_cross_design_and_duplicate_candidates(tmp_path: Path) -> None:
    """Present cross structure and identical assets as review obligations rather than deletion proof."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text(
        "covergroup H_cg;\nfirst: coverpoint flag;\nsecond: coverpoint mode;\ncombo: cross first, second;\nendgroup\n")
    (harness.source / "generators/H_copy.py").write_bytes((harness.source / "generators/H.py").read_bytes())
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.scope["assets"]["generators"].append("generators/H_copy.py")
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    cross = evidence["review_tasks"]["point:H_cg/combo"]
    assert cross["kind"] == "cross" and cross["cross_members"] == ["first", "second"]
    duplicate = evidence["review_tasks"]["duplicate:0"]
    assert duplicate["paths"] == ["generators/H.py", "generators/H_copy.py"]
    assert "outcomes" in duplicate["question"]
    judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == ["duplicate:0"])
    judgment["basis"].pop()
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "must cite its task sources" in error["error"]


def test_review_enables_existing_coverage_structure_rules(tmp_path: Path) -> None:
    """Reuse provable default-bin and bitwalk checks without changing generation checker defaults."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text(
        "covergroup H_cg;\nfirst: coverpoint flag { bins values = default; }\n"
        "walk: coverpoint $onehot(vector) { bins single = {1}; }\ncombo: cross first, walk;\nendgroup\n")
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    checks = {task.get("check") for task in evidence["review_tasks"].values()}
    assert {"coverage_default_bin", "coverage_bitwalk_bins"} <= checks


def test_commented_descriptor_cannot_create_coverpoint_link(tmp_path: Path) -> None:
    """Ignore commented metadata even when its label exists for a different real descriptor."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    (harness.source / "H-00.S").write_text(
        '/*\ncase_1_str: .string "test: H; cg: H_cg; cp: cp; bin: v"\n*/\n'
        'case_1_str: .string "test: H; cg: H_cg; cp: actual; bin: v"\ncase_1:\n nop\n')
    harness.scope["assets"].update(coverage=["H.svh"], test_cases=["H-00.S"])
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert "H_cg/cp" not in evidence["testcase_links"]
    assert evidence["testcase_links"]["H_cg/actual"][0]["line"] == 4


def test_unavailable_static_analysis_remains_reviewable(tmp_path: Path, monkeypatch) -> None:
    """Queue infrastructure failures instead of silently removing failed static analysis from AI review."""
    harness = ReviewHarness(tmp_path)
    monkeypatch.setattr(ACT4AssetChecker, "do_check", lambda self: (False, {"error": "Static analysis dependency unavailable"}))
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["review_tasks"]["diagnostic:0:failure"]["error"] == "Static analysis dependency unavailable"
    assert not evidence["static_passed"]


def test_empty_asset_can_be_reviewed_without_inventing_source_lines(tmp_path: Path) -> None:
    """Use machine-recorded file identity and diagnostics when an empty source has no quotable lines."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "generators/H.py").write_text("")
    review = harness.audit()
    assert any(citation["path"] == "evidence-before.json"
               for judgment in review["semantic_review"]["judgments"] for citation in judgment["basis"])


@pytest.mark.parametrize("topic", ["act4_compliance", "ci", "test_coverage"])
def test_ai_cannot_override_machine_failures(tmp_path: Path, topic: str) -> None:
    """Apply machine evidence limits to AI conclusions even when top-level checks admit failures."""
    harness = ReviewHarness(tmp_path)
    if topic == "ci":
        harness.scope["jobs"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(3)"]
        harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == [f"topic:{topic}"])
    judgment.update(status="passed", confidence="confirmed")
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "AI" in error["error"] and "cannot pass" in error["error"]


@pytest.mark.parametrize("defect", [
    "missing", "empty", "stale_digest", "wrong_reviewer", "missing_task", "duplicate_task", "unknown_task",
    "reasoning", "conclusion", "basis", "observation", "invented_quote", "self_report", "outside",
    "bool_lines", "reversed_lines", "out_of_range", "too_many_lines", "issues_without_finding",
    "unknown_finding", "no_limitation", "no_next_action", "inferred_pass", "bad_status", "bad_confidence",
])
def test_semantic_review_requires_complete_grounded_judgments(tmp_path: Path, defect: str) -> None:
    """Reject incomplete AI assessments and fabricated evidence while preserving actionable diagnostics."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    semantic = review["semantic_review"]
    judgment = semantic["judgments"][0]
    citation = judgment["basis"][0]
    if defect == "missing":
        del review["semantic_review"]
    elif defect == "empty":
        semantic["judgments"] = []
    elif defect == "stale_digest":
        semantic["evidence_digest"] = "0" * 64
    elif defect == "wrong_reviewer":
        semantic["reviewer"] = "static"
    elif defect == "missing_task":
        semantic["judgments"].pop()
    elif defect == "duplicate_task":
        semantic["judgments"].append(judgment)
    elif defect == "unknown_task":
        judgment["tasks"] = ["topic:invented"]
    elif defect in {"reasoning", "conclusion", "basis"}:
        del judgment[defect]
    elif defect == "observation":
        del citation["observation"]
    elif defect == "invented_quote":
        citation["quote"] = "H correctness has been proved."
    elif defect in {"self_report", "outside"}:
        citation["path"] = "review.yaml" if defect == "self_report" else "../../external.py"
    elif defect in {"bool_lines", "reversed_lines", "out_of_range", "too_many_lines"}:
        citation["lines"] = {"bool_lines": [True, True], "reversed_lines": [2, 1], "out_of_range": [0, 2], "too_many_lines": [1, 101]}[defect]
    elif defect == "issues_without_finding":
        judgment["status"] = "issues"
    elif defect == "unknown_finding":
        judgment["findings"] = ["F999"]
    elif defect in {"no_limitation", "no_next_action"}:
        del judgment["limitation" if defect == "no_limitation" else "next_action"]
    elif defect == "inferred_pass":
        judgment.update(status="passed", confidence="inferred")
    else:
        judgment["status" if defect == "bad_status" else "confidence"] = ["passed"]
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and error["error_code"] == "act4_review_contract", error
    assert "unhashable" not in error["error"]


def test_point_review_must_cite_defining_source(tmp_path: Path) -> None:
    """Prevent generic source quotations from standing in for per-coverpoint analysis."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    judgments = review["semantic_review"]["judgments"]
    point = next(item for item in judgments if item["tasks"] == ["point:H_cg/cp"])
    point["basis"] = judgments[0]["basis"]
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "defining source line" in error["error"]


def test_unverified_ai_judgment_blocks_passing_topic(tmp_path: Path) -> None:
    """Do not let a summary claim success while the detailed semantic assessment admits uncertainty."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["checks"]["redundancy"]["status"] = "passed"
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "Topic redundancy cannot pass" in error["error"]


def test_binary_artifact_is_not_textual_ai_basis(tmp_path: Path) -> None:
    """Require a textual report rather than attempting to quote opaque native binaries."""
    harness = ReviewHarness(tmp_path)
    script = harness.source / "check.py"
    script.write_text(script.read_text().replace("ELFfixture", "ELF\\xfffixture"))
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    artifact = next(item for item in evidence["jobs"][1]["artifacts"] if item["kind"] == "elf")
    review["semantic_review"]["judgments"][0]["basis"][0]["path"] = artifact["path"]
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "AI basis requires UTF-8 text" in error["error"]


def test_source_quote_line_limit_is_inclusive(tmp_path: Path) -> None:
    """Accept a complete 100-line quote but reject a 101-line source excerpt."""
    harness = ReviewHarness(tmp_path)
    reference = tmp_path / "manual.adoc"
    reference.write_text("\n".join(f"Obligation {number}" for number in range(101)) + "\n")
    harness.scope["reference_files"] = ["manual.adoc"]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    citation = review["semantic_review"]["judgments"][0]["basis"][0]
    citation.update(path="references/manual.adoc", lines=[1, 100],
        quote="\n".join(reference.read_text().splitlines()[:100]))
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check()[0]
    citation.update(lines=[1, 101], quote=reference.read_text().rstrip("\n"))
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "1..100" in error["error"]


@pytest.mark.parametrize("topic", ["omissions", "coverpoint_quality"])
@pytest.mark.parametrize("available", [True, False])
def test_passing_specification_review_requires_pinned_reference(tmp_path: Path, topic: str, available: bool) -> None:
    """Require immutable specification text for positive completeness and design conclusions."""
    harness = ReviewHarness(tmp_path)
    reference = tmp_path / "manual.adoc"
    reference.write_text("The H obligation shall be tested.\n")
    harness.scope["reference_files"] = ["manual.adoc"] if available else []
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == [f"topic:{topic}"])
    judgment.update(status="passed", confidence="confirmed")
    if available:
        judgment["basis"].append({"path": "references/manual.adoc", "lines": [1, 1],
            "quote": "The H obligation shall be tested.", "observation": "The pinned fixture obligation is explicit"})
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert passed is available, error


@pytest.mark.parametrize("drift", ["original", "copy", "membership"])
def test_reference_drift_invalidates_review_and_repair(tmp_path: Path, drift: str) -> None:
    """Validate both original reference bytes and their frozen copies before repair."""
    harness = ReviewHarness(tmp_path)
    (tmp_path / "manual.adoc").write_text("Pinned H specification\n")
    harness.scope["reference_files"] = ["manual.adoc"]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    if drift == "original":
        (tmp_path / "manual.adoc").write_text("Changed H specification\n")
    elif drift == "copy":
        (harness.output / "references/manual.adoc").write_text("Forged frozen specification\n")
    else:
        harness.scope["reference_files"] = []
        harness.write("scope.yaml", harness.scope)
    passed, error = harness.checker("repair").do_check()
    assert not passed and ("changed" in error["error"] or "baseline" in error["error"]), error
    assert not (harness.output / "candidate").exists()


@pytest.mark.parametrize("value", [None, "manual.adoc", [True], ["missing.adoc"], ["../manual.adoc"], ["reports/H/review/scope.yaml"]])
def test_scope_requires_safe_existing_reference_files(tmp_path: Path, value) -> None:
    """Reject nonexistent, output-owned and malformed reference inputs before snapshotting."""
    harness = ReviewHarness(tmp_path)
    harness.scope["reference_files"] = value
    harness.write("scope.yaml", harness.scope)
    assert not harness.checker("audit").do_check()[0]


def test_noncoverage_job_artifact_cannot_prove_measured_hits(tmp_path: Path) -> None:
    """A misleading artifact kind on a build job must not upgrade source links to measured coverage."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    review["traceability"][0].update(coverage="measured", testcases=["H-00.S::case_1"],
        evidence=[evidence["jobs"][1]["artifacts"][0]["path"]])
    harness.write("review.yaml", review)
    passed, error = harness.checker("audit").do_check()
    assert not passed and "Measured coverpoints" in error["error"]
    review["traceability"][0]["evidence"] = [evidence["jobs"][3]["artifacts"][0]["path"]]
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check()[0]


@pytest.mark.parametrize("defect", ["before_digest", "missing_finding", "missing_change", "fixed_unverified", "fixed_wrong_source", "change_wrong_source", "no_risks"])
def test_final_review_reassesses_findings_changes_and_risks(tmp_path: Path, defect: str) -> None:
    """Require current AI reassessment for declared repairs and retain every remaining semantic limit."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/generators/H.py").write_text('"""Repaired generator fixture."""\nVALUE = 2\n')
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "Fixture change reviewed",
        "findings": [{"id": "F1", "status": "fixed", "reason": "Declared fixture edit",
                      "evidence": ["evidence-after.json"]}], "ci_passed": True,
        "remaining_risks": ["ISA semantics remain unverified"], "coverage_changes": [], "traceability": []}
    final["semantic_review"] = harness.assess(final, "after")
    judgments = final["semantic_review"]["judgments"]
    if defect == "before_digest":
        final["semantic_review"]["evidence_digest"] = json.loads((harness.output / "evidence-before.json").read_text())["review_digest"]
    elif defect in {"missing_finding", "missing_change"}:
        prefix = "finding:" if defect == "missing_finding" else "change:"
        final["semantic_review"]["judgments"] = [item for item in judgments if not item["tasks"][0].startswith(prefix)]
    elif defect == "fixed_unverified":
        next(item for item in judgments if item["tasks"] == ["finding:F1"]).update(status="unverified", confidence="unverified")
    elif defect in {"fixed_wrong_source", "change_wrong_source"}:
        identity = "finding:F1" if defect == "fixed_wrong_source" else "change:generators/H.py"
        next(item for item in judgments if item["tasks"] == [identity])["basis"] = [{
            "path": "baseline/README.md", "lines": [1, 1], "quote": "Native CI: python3 check.py",
            "observation": "This is an unchanged source rather than a repair"}]
    else:
        final["remaining_risks"] = []
    harness.write("final.yaml", final)
    passed, error = harness.checker("final").do_check()
    assert not passed and error["error_code"] == "act4_review_contract", error


def test_optional_preflight_precedes_scope_and_cannot_complete_audit(tmp_path: Path) -> None:
    """Discover absent simulators before authoring scope without claiming a completed review."""
    harness = ReviewHarness(tmp_path)
    (harness.output / "scope.yaml").unlink()
    checker = harness.checker("audit")
    passed, result = checker.do_check()
    assert passed, result
    assert result["optional_tools"] == {name: "not_found" for name in ("questa", "vcs", "xcelium")}
    assert (harness.output / "environment.json").is_file()
    assert not (harness.output / "baseline.json").exists()
    passed, result = checker.do_check(is_complete=True)
    assert not passed and "scope.yaml" in result["error"]


@pytest.mark.parametrize("tool", ["questa", "vcs", "xcelium"])
@pytest.mark.parametrize("outcome", ["available", "license_failure", "version_only"])
def test_optional_tools_require_real_compile_and_execution(tmp_path: Path, monkeypatch, tool: str, outcome: str) -> None:
    """Run bounded process fixtures and reject a version banner or failed license checkout."""
    harness = ReviewHarness(tmp_path)
    tool_bin = tmp_path / "fake-bin"
    tool_bin.mkdir()
    marker = "ACT4_REVIEW_SMOKE_PASS" if outcome == "available" else "Tool version 1.0"
    run_script = f"#!{sys.executable}\nprint({marker!r})\n"
    code = (f"#!{sys.executable}\nfrom pathlib import Path\nimport sys\n"
            f"assert 'covergroup' in Path('smoke.sv').read_text()\n"
            f"print({marker!r} if Path(sys.argv[0]).name in ('vsim', 'xrun') else 'compiled')\n"
            f"output = Path('smoke'); output.write_text({run_script!r}); output.chmod(0o755)\n"
            f"raise SystemExit({7 if outcome == 'license_failure' else 0})\n")
    for name in act4_review_checker.OPTIONAL_SIMULATORS[tool]:
        path = tool_bin / name
        path.write_text(code)
        path.chmod(0o755)
    monkeypatch.setattr(act4_review_checker.shutil, "which", lambda name, **kwargs: str(tool_bin / name) if (tool_bin / name).exists() else None)
    passed, result = harness.checker("audit").do_check()
    assert passed, result
    report = json.loads((harness.output / "environment.json").read_text())
    record = report["tools"][tool]
    assert record["status"] == ("available" if outcome == "available" else "unusable")
    assert all("--version" not in item["argv"] for item in record["attempts"])
    assert all((harness.output / item["log"]).is_file() for item in record["attempts"])
    saved = (harness.output / "environment.json").read_bytes()
    monkeypatch.setattr(act4_review_checker, "execute_command", lambda *args, **kwargs: pytest.fail("Ordinary Check must reuse probes"))
    assert harness.checker("audit").do_check()[0]
    assert saved == (harness.output / "environment.json").read_bytes()
    (harness.output / record["attempts"][0]["log"]).write_text("forged")
    passed, result = harness.checker("audit").do_check()
    assert not passed and "probe log changed" in result["error"]


def test_optional_probe_timeout_keeps_review_available(tmp_path: Path, monkeypatch) -> None:
    """Record an unavailable licensed capability when a bounded smoke probe times out."""
    harness = ReviewHarness(tmp_path)
    monkeypatch.setattr(act4_review_checker.shutil, "which", lambda name, **kwargs: "/fixture/vcs" if name == "vcs" else None)

    def timeout(argv, cwd, env, log, timeout, append=False):
        """Model a license server timeout without waiting for a real server."""
        assert timeout <= 20
        log.write_text("Waiting for license server")
        return {"argv": argv, "status": "timeout", "exit_code": None}

    monkeypatch.setattr(act4_review_checker, "execute_command", timeout)
    assert harness.checker("audit").do_check()[0]
    report = json.loads((harness.output / "environment.json").read_text())
    assert report["tools"]["vcs"]["status"] == "unusable"


def test_optional_tool_refresh_invalidates_native_evidence(tmp_path: Path) -> None:
    """Reject fabricated capabilities and require fresh validation after an explicit refresh."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    path = harness.output / "environment.json"
    report = json.loads(path.read_text())
    report["tools"]["questa"]["status"] = "available"
    path.write_text(json.dumps(report))
    passed, result = harness.checker("audit").do_check()
    assert not passed and "environment.json changed" in result["error"]
    passed, result = harness.checker("audit").do_check(refresh_tools=True)
    assert not passed and "evidence is stale" in result["error"]
    assert json.loads(path.read_text())["tools"]["questa"]["status"] == "not_found"


def test_optional_coverage_unavailable_allows_independent_validation_and_delivery(tmp_path: Path) -> None:
    """Finish an honest review with generation, build and model passing without a simulator."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][3]["optional_tool"] = "questa"
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["jobs"][3]["status"] == "unavailable"
    assert all(job["status"] == "passed" for job in evidence["jobs"] if not job["optional"])
    assert not (harness.output / "before-coverage.log").exists()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check(is_complete=True)[0]
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "Source audit finished; native model passed, measured coverage unavailable.",
        "findings": [{"id": "F1", "status": "deferred", "classification": "validation_gap", "diagnosis": "cause_identified",
                      "reason": "No licensed simulator is available", "next_action": "Run coverage when a supported simulator is provided",
                      "evidence": ["environment.json"], "blocker": {"kind": "tooling", "detail": "Questa is absent on PATH",
                          "impact": "Bin hits cannot be measured", "why_not_resolved": "The smoke preflight found no executable",
                          "owner": "user", "request": "Optionally supply an existing Questa installation and working license for measured coverage",
                          "reason_user_needed": "The user controls commercial tool access"}}],
        "ci_passed": False, "remaining_risks": ["No measured coverage"], "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    report = (harness.output / "final.md").read_text()
    assert "Required native validation: **passed**" in report
    assert "Confirmed defects: **0**" in report and "validation gaps: **1**" in report
    assert "Fixed: **0**; deferred: **1**" in report
    assert "Optionally supply an existing Questa" in report
    assert report.index("Source audit finished") < report.index("Findings and outcomes") < report.index("Help requested") < report.index("Native validation (before)")
    assert "```yaml" not in report
    assert (harness.output / "changes.patch").read_text() == ""


@pytest.mark.parametrize("defect", ["required_dependency", "install", "unknown", "manual_skip", "model_optional"])
def test_optional_job_contract_prevents_required_lane_contamination(tmp_path: Path, defect: str) -> None:
    """Require declared optional capabilities and keep them out of required dependency chains."""
    harness = ReviewHarness(tmp_path)
    job = harness.scope["jobs"][3]
    job["optional_tool"] = "questa"
    if defect == "required_dependency":
        harness.scope["jobs"][4]["needs"].append("coverage")
    elif defect == "install":
        job["install"] = ["installer"]
    elif defect == "unknown":
        job["optional_tool"] = "invented"
    elif defect == "manual_skip":
        job.update(disposition="unavailable", reason="Assume license absent")
    else:
        harness.scope["jobs"][2]["optional_tool"] = "questa"
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check()
    assert not passed and "optional" in result["error"].lower()


@pytest.mark.parametrize("defect", ["none", "missing_inventory", "unknown_source", "missing_finding", "invented_point", "false_implemented", "wrong_block_quote"])
def test_plan_obligations_survive_absence_from_coverage_and_generator(tmp_path: Path, defect: str) -> None:
    """Demand forward traceability even for requirements that have no existing implementation."""
    harness = ReviewHarness(tmp_path)
    plan = "testplan.md"
    (harness.source / plan).write_text("STCE must read as zero when H is present without Sstc.\n" * 81)
    harness.scope["assets"]["test_plans"] = [plan]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["coverpoints"] == [] and len(evidence["obligation_sources"]) == 2
    for item in review["obligations"]:
        item.update(status="gap", findings=["F1"], requirement="Test H without Sstc: STCE is read-only zero")
    review["semantic_review"] = harness.assess(review)
    for judgment in review["semantic_review"]["judgments"]:
        if judgment["tasks"][0].startswith("obligation:"):
            judgment.update(status="issues", confidence="confirmed", findings=["F1"])
    if defect == "missing_inventory":
        review["obligations"].pop()
    elif defect == "unknown_source":
        review["obligations"][0]["sources"] = ["invented"]
    elif defect == "missing_finding":
        review["obligations"][0]["findings"] = []
    elif defect == "invented_point":
        review["obligations"][0]["coverpoints"] = ["Missing/cp_stce"]
    elif defect == "false_implemented":
        review["obligations"][0]["status"] = "implemented"
    elif defect == "wrong_block_quote":
        judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == [f"source:plan:{plan}:81-81"])
        judgment["basis"][0]["lines"] = [1, 1]
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check()
    assert passed is (defect == "none"), result


def test_specification_sources_are_independent_and_removed_plan_stays_reviewable(tmp_path: Path) -> None:
    """Preserve original obligations when a plan is removed and include spec-only requirements."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "plan.md").write_text("CSR writes require all four instruction variants.\n")
    (tmp_path / "manual.adoc").write_text("New settings take effect without SFENCE.VMA.\n")
    harness.scope["assets"]["test_plans"] = ["plan.md"]
    harness.scope["reference_files"] = ["manual.adoc"]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    assert len(review["obligations"]) == 2
    review["changes"][0]["paths"].append("plan.md")
    review["post_assets"]["test_plans"] = []
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/plan.md").unlink()
    assert harness.checker("repair").do_check(run_commands=True)[0]
    evidence = json.loads((harness.output / "evidence-after.json").read_text())
    assert evidence["obligation_sources"]["source:plan:plan.md:1-1"]["path"] == "baseline/plan.md"
    assert evidence["obligation_sources"]["source:specification:manual.adoc:1-1"]["path"] == "references/manual.adoc"


@pytest.mark.parametrize("defect", ["none", "unknown_path", "no_consumers", "no_boundary", "unclassified_diagnostic"])
def test_shared_assets_and_scanner_scope_are_explicit(tmp_path: Path, defect: str) -> None:
    """Review cross-suite dependencies and retain raw diagnostics with separate adjudication."""
    harness = ReviewHarness(tmp_path)
    harness.scope["shared_assets"] = [{"path": "generators/H.py", "consumers": ["H", "Sstc"],
        "boundary": "Review shared CSR helpers for both consumers; native matrix is H only"}]
    if defect == "unknown_path":
        harness.scope["shared_assets"][0]["path"] = "missing.py"
    elif defect == "no_consumers":
        harness.scope["shared_assets"][0]["consumers"] = []
    elif defect == "no_boundary":
        harness.scope["shared_assets"][0]["boundary"] = ""
    harness.write("scope.yaml", harness.scope)
    if defect in {"unknown_path", "no_consumers", "no_boundary"}:
        passed, result = harness.checker("audit").do_check()
        assert not passed and "shared" in result["error"].lower()
        return
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert "shared:generators/H.py" in evidence["review_tasks"]
    judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"][0].startswith("diagnostic:"))
    if defect == "unclassified_diagnostic":
        judgment.pop("diagnostics")
    else:
        judgment.update(status="not_applicable", confidence="confirmed", diagnostics={judgment["tasks"][0]: "scope_mismatch"})
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check()
    assert passed is (defect == "none"), result
    if passed:
        report = (harness.output / "review.md").read_text()
        assert "Scanner diagnostics (not defect counts)" in report and "scope_mismatch: 1" in report
        assert evidence["static_passed"] is False


@pytest.mark.parametrize("defect", ["investigation", "quote", "classification", "diagnosis", "blocker", "impact", "why_not_resolved", "owner", "user_request", "reason_user_needed"])
def test_unresolved_findings_require_specific_investigation_and_blockers(tmp_path: Path, defect: str) -> None:
    """Reject unsupported deferrals and avoid transferring ordinary investigation to the user."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "Missing implementation remains open",
        "findings": [{"id": "F1", "status": "deferred", "reason": "No implementation yet", "evidence": ["evidence-after.json"],
            "next_action": "Implement the specified behavior"}], "ci_passed": True,
        "remaining_risks": ["Unimplemented behavior"], "coverage_changes": [], "traceability": []}
    final["semantic_review"] = harness.assess(final, "after")
    finding = final["findings"][0]
    if defect in {"investigation", "classification", "diagnosis", "blocker"}:
        finding.pop(defect)
    elif defect == "quote":
        finding["investigation"][0]["basis"][0]["quote"] = "fabricated"
    elif defect in {"user_request", "reason_user_needed"}:
        finding["blocker"].update(owner="user", request="Provide a custom configuration", reason_user_needed="Configuration is external")
        finding["blocker"].pop("request" if defect == "user_request" else "reason_user_needed")
    else:
        finding["blocker"].pop(defect)
    harness.write("final.yaml", final)
    passed, result = harness.checker("final").do_check()
    assert not passed and result["error_code"] == "act4_review_contract"


@pytest.mark.parametrize("field,value", [("classification", "suspected_defect"), ("diagnosis", "symptoms_only")])
def test_repair_proposals_require_supported_diagnosis(tmp_path: Path, field: str, value: str) -> None:
    """Keep evidence-insufficient findings in the audit without inventing a repair proposal."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["findings"][0][field] = value
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check()
    assert not passed and "repair_ready" in result["error"]
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check()[0]


def test_dismissed_finding_is_not_counted_as_a_fix(tmp_path: Path) -> None:
    """Allow a source-grounded false positive resolution without producing a fake patch."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "The suspected issue was a scope mismatch",
        "findings": [{"id": "F1", "status": "dismissed", "classification": "not_a_defect", "reason": "External suite owns this obligation",
                      "evidence": ["evidence-after.json"]}], "ci_passed": True,
        "remaining_risks": ["Synthetic fixture is not an ISA proof"], "coverage_changes": [], "traceability": []}
    final["semantic_review"] = harness.assess(final, "after")
    judgment = next(item for item in final["semantic_review"]["judgments"] if item["tasks"] == ["finding:F1"])
    judgment.update(status="not_applicable", confidence="confirmed")
    harness.write("final.yaml", final)
    passed, result = harness.checker("final").do_check()
    assert passed, result
    report = (harness.output / "final.md").read_text()
    assert "Fixed: **0**" in report and "dismissed without a patch: **1**" in report
    assert "No user input is currently required" in report
    assert (harness.output / "changes.patch").read_text() == ""


@pytest.mark.parametrize("defect", ["none", "plan_as_implementation", "missing_definition", "unconfirmed_finding"])
def test_implemented_obligations_require_both_definition_and_code(tmp_path: Path, defect: str) -> None:
    """Tie positive forward mappings to actual code and coverage without upgrading them to hits."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "plan.md").write_text("Observe flag on the fixture transaction.\n")
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    harness.scope["assets"]["test_plans"] = ["plan.md"]
    harness.scope["assets"]["coverage"] = ["H.svh"]
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    review["obligations"][0].update(status="implemented", implementation=["baseline/generators/H.py"], coverpoints=["H_cg/cp"])
    review["semantic_review"] = harness.assess(review)
    judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == ["obligation:O1"])
    judgment.update(status="passed", confidence="confirmed")
    citation = next(item for item in judgment["basis"] if item["path"] == "baseline/H.svh")
    if defect != "missing_definition":
        citation.update(lines=[2, 2], quote="cp: coverpoint flag;")
    if defect == "plan_as_implementation":
        review["obligations"][0]["implementation"] = ["baseline/plan.md"]
    elif defect == "unconfirmed_finding":
        finding = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == ["finding:F1"])
        finding.update(status="unverified", confidence="unverified")
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check()
    assert passed is (defect == "none"), result
    assert review["traceability"][0]["coverage"] == "unverified"
