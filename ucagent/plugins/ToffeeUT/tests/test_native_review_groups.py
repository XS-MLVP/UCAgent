"""Compact native zero-point reviews use synthetic counters only, never a DUT run."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from toffee_ut.audit import audit_project, delivery_data
from toffee_ut.checkers import ToffeeUTChecker
from toffee_ut.coverage import coverage_data
from toffee_ut.handoff import ToffeeUTHandoff
from toffee_ut.paths import digest, source_identity, write_json
from toffee_ut.reports import render_summary
from toffee_ut.runner import _signature
from toffee_ut.tools import CoverageInfo
from ucagent.core.stage.work import StageWork, StageWorkLoop
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config


@pytest.fixture(scope="session", autouse=True)
def isolated_plugin_imports():
    """Assert that this entire regression session imports the isolated plugin, not live code."""
    yield
    root = Path(__file__).resolve().parents[1] / "src"
    for name, module in tuple(sys.modules.items()):
        if name == "toffee_ut" or name.startswith("toffee_ut."):
            filename = getattr(module, "__file__", None)
            assert filename and Path(filename).resolve().is_relative_to(root), (name, filename)


def point_bytes(metric, line, identity, count=0):
    """Encode one native DAT point as fixture input, without simulator construction."""
    return f"C '\x01f\x02inputs/Block.sv\x01l\x02{line}\x01page\x02v_{metric}\x01o\x02{identity}' {count}\n".encode()


def group(metric, line, build="unit-only"):
    """Declare one exact source-line zero-set selector, not a coverage exclusion."""
    return {"metric": metric, "build": build, "source": "inputs/Block.sv", "line": line,
            "group": {"scope": "source-line"}, "status": "justified",
            "reason": "Independent synthetic contract excludes this configuration at this exact location"}


@pytest.fixture
def native_review(project, checked_evidence, contract_writer, monkeypatch):
    """Extend the shared checked-evidence fixture with physical lines and separate metrics."""
    data = checked_evidence
    data["record"]["line_coverage_required"] = True
    native = Path(data["manifest"]["artifacts"][0]["path"])
    with native.open("ab") as stream:
        for metric, line, count in (("branch", 10, 3), ("toggle", 10, 4), ("toggle", 11, 2)):
            for index in range(count):
                stream.write(point_bytes(metric, line, f"bit[{index}]"))
        stream.write(point_bytes("toggle", 12, "already-hit", 8))
    lcov = native.with_suffix(".info")
    lcov.write_text("SF:inputs/Block.sv\nDA:1,0\nDA:2,5\nend_of_record\n")
    data["manifest"]["artifacts"].append({"kind": "lcov", "path": str(lcov)})
    source = project / "inputs/interface.md"
    entry = {"run": data["record"]["run"], "source": "inputs/interface.md", "sha256": digest(source),
             "observation": "Review every collected metric without modifying native counters",
             "next_action": "Retain the independent fixture scope and any unresolved gaps",
             "uncovered": [{"metric": "line", "build": "unit-only", "source": "inputs/Block.sv", "line": 1,
                            "status": "justified", "reason": "Independent fixture excludes this physical line"},
                           group("branch", 10), group("toggle", 10), group("toggle", 11)]}
    monkeypatch.setattr("toffee_ut.tools.current_run", lambda *args: data)
    monkeypatch.setattr("toffee_ut.stage_checks.line_coverage.current_run", lambda *args: data)
    return {"workspace": project, "data": data, "native": native, "entry": entry, "writer": contract_writer}


def save_review(fixture):
    """Write only the temporary fixture's maintained review document."""
    path = fixture["workspace"] / "ut_project/docs/reviews/Block-stage-evidence.md"
    fixture["writer"](path, {"kind": "stage_evidence", "dut": "Block",
                            "reviews": {"line_coverage": fixture["entry"]}})


def inspect_review(fixture):
    """Read the fixture's real counter files through the production parser."""
    return coverage_data(fixture["workspace"], "ut_project", "Block", fixture["data"])


@pytest.fixture
def handoff(native_review):
    """Sign temporary synthetic counters, using the real receipt validator at handoff."""
    fixture = native_review
    workspace, data = fixture["workspace"], fixture["data"]
    project = workspace / "ut_project"
    results = project / "results"
    run = project / data["record"]["run"]
    node, = data["cases"]["cases"]
    cases = {**data["cases"], "collection": [node], "errors": [], "collect_only": False,
             "exitstatus": 0, "counts": {"PASS": 1}, "deselected": []}
    manifest = {**data["manifest"], "state": "committed", "coverage_complete": True,
                "tests": cases["counts"], "pytest_exitstatus": 0}
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = digest(artifact["path"])
        if "build" in artifact:
            artifact["build"]["files"] = {name: digest(name) for name in artifact["build"]["files"]}
    write_json(run / "cases.json", cases)
    write_json(run / "manifest.json", manifest)
    identity = source_identity(project, workspace)
    receipt = {**data["record"], "files": {"cases.json": digest(run / "cases.json"),
               "manifest.json": digest(run / "manifest.json")}, "waveforms": {}, "extra_inputs": [],
               "source_before": identity, "source_after": identity, "returncode": 0}
    receipt.pop("signature")
    receipt["signature"] = _signature(workspace, receipt, create=True)
    write_json(run / "receipt.json", receipt)
    write_json(results / "latest.json", receipt)
    save_review(fixture)
    stages = []
    for phase in ("line_coverage", "final"):
        checker = ToffeeUTChecker(phase, dut="Block")
        checker.workspace = workspace
        stages.append(SimpleNamespace(name=phase, checker=[checker], is_reached=lambda: True,
                                      is_skipped=lambda: False))
    work = StageWork(workspace, "Block")
    hook = ToffeeUTHandoff()
    manager = SimpleNamespace(stages=stages, stage_index=1, stage_work=work,
                              runtime_hooks=[hook], last_check_info={"check_pass": False,
                              "failure_summary": {"stage_index": 1}})

    def set_item(state, item_id):
        work.update(stages, 1, state, item_id, "fixture observation", "inputs/interface.md")

    def row(state, item_id, **fields):
        return {"state": state, "id": item_id, "source": "inputs/interface.md#scope",
                "sha256": digest(workspace / "inputs/interface.md"), "observation": "Exact fixture case",
                **fields}

    def save_items(*rows):
        reviews = project / "docs/reviews"
        fixture["writer"](reviews / "Block-handoff-inventory.md", {
            "kind": "handoff_inventory", "schema_version": 1, "dut": "Block", "run": receipt["run"],
            "native_review_sha256": digest(reviews / "Block-stage-evidence.md"),
            "scope_review": "Fixture reviewed the report, signed cases and all native gap dispositions.",
            "items": list(rows)})

    def decision(loop=None):
        work.update(stages, 1, "review", "", "", "fixture inventory reviewed")
        loop = loop or StageWorkLoop(manager, 3)
        return loop.after_round(loop.before_round(), stalled=False, validated=False)

    set_item("human", "spec-field")
    external = row("external", "spec-field", owner="Protocol owner", missing_input="Versioned R1 mapping",
                   impact="No independent expected result for the reserved encoding")
    save_items(external)
    return SimpleNamespace(**fixture, results=results, receipt=receipt, set_item=set_item,
                           row=row, save_items=save_items, external=external, decision=decision, manager=manager)


@pytest.mark.parametrize("kind", ["review_stale", "selector_mismatch", "review_incomplete"])
def test_handoff_rechecks_native_diagnostic_after_report(handoff, kind):
    entry = handoff.entry
    if kind == "review_stale":
        entry["run"] = "results/old"
    elif kind == "selector_mismatch":
        entry["uncovered"][0]["line"] = 71
    else:
        entry["uncovered"].pop()
    save_review(vars(handoff))
    reason, prompt = handoff.decision()
    assert reason is None and kind in prompt and "不为审阅重跑" in prompt


@pytest.mark.parametrize("registered", [False, True])
def test_handoff_finds_omitted_or_misclassified_facility_work(handoff, registered):
    if registered:
        handoff.set_item("human", "driver-phase")
    candidate = handoff.row("ready", "driver-phase", next_action="Compare the signed sampling waveform")
    handoff.save_items(handoff.external, candidate)
    loop = StageWorkLoop(handoff.manager, 3)
    before = digest(handoff.results / "latest.json")
    reason, prompt = handoff.decision(loop)
    assert reason is None and "driver-phase" in prompt and "signed sampling waveform" in prompt
    if not registered:
        handoff.set_item("ready", "driver-phase")
    handoff.set_item("done", "driver-phase")
    handoff.save_items(handoff.external, {**candidate, "state": "done", "result": "Verified from signed waveform"})
    assert handoff.decision(loop) == ("human_input_required", None)
    assert digest(handoff.results / "latest.json") == before


def test_handoff_requires_evidence_for_covered_and_unclassified_gaps(handoff):
    handoff.entry["uncovered"][0]["status"] = "gap"
    save_review(vars(handoff))
    assert "待核对" in handoff.decision()[1]  # inventory hash is stale
    handoff.save_items(handoff.external)
    assert "1 组已审阅的原生 gap 未归到" in handoff.decision()[1]
    handoff.save_items({**handoff.external, "native_gaps": [[1, 1]]})
    assert handoff.decision() == ("human_input_required", None)  # still not coverage PASS
    assert inspect_review(vars(handoff))["review"]["state"] == "gaps"


def test_handoff_does_not_treat_native_review_itself_as_external_gap_evidence(handoff):
    handoff.entry["uncovered"][0].update(status="gap", reason="No legal responder-error case has run yet")
    save_review(vars(handoff))
    review = handoff.results.parent / "docs/reviews/Block-stage-evidence.md"
    handoff.set_item("human", "all-remaining-coverage")
    handoff.save_items(handoff.external, handoff.row(
        "external", "all-remaining-coverage", source=f"{review.relative_to(handoff.workspace)}#uncovered",
        sha256=digest(review), observation="The review includes unimplemented tests", owner="Design",
        missing_input="Decide how to close coverage", impact="All native gaps remain", native_gaps=[[1, 1]]))
    before = {path: digest(path) for path in (review, handoff.results / "latest.json")}
    reason, prompt = handoff.decision()
    assert reason is None and "all-remaining-coverage" in prompt and "独立证据" in prompt
    assert "不把" in prompt and "重跑" in prompt
    assert all(digest(path) == content for path, content in before.items())
    assert inspect_review(vars(handoff))["review"]["state"] == "gaps"


def test_handoff_reports_fence_format_without_requesting_a_new_run(handoff):
    inventory = handoff.results.parent / "docs/reviews/Block-handoff-inventory.md"
    inventory.write_text(inventory.read_text().split("```yaml\n", 1)[1].split("```", 1)[0])
    reason, prompt = handoff.decision()
    assert reason is None and "单个 ```yaml 代码块" in prompt and "不要写成裸 YAML" in prompt


def test_handoff_explains_project_relative_receipt_identity(handoff):
    inventory = handoff.results.parent / "docs/reviews/Block-handoff-inventory.md"
    inventory.write_text(inventory.read_text().replace("run: results/", "run: ut_project/results/"))
    reason, prompt = handoff.decision()
    assert reason is None and "signed project-relative value: results/unit-audit-only" in prompt


def test_handoff_stall_does_not_turn_into_external_wait(handoff):
    handoff.save_items(handoff.external, handoff.row("stalled", "driver-phase", next_action="Check narrow window"))
    loop = StageWorkLoop(handoff.manager, 3)
    decisions = [handoff.decision(loop) for _ in range(6)]
    assert "验证侧事项 driver-phase 尚停滞" in decisions[0][1]
    assert decisions[-1] == ("checker_stall", None)
    assert all(reason != "human_input_required" for reason, _ in decisions)


def test_handoff_reuses_current_archive_without_approving_latest(handoff):
    latest = handoff.results / "latest.json"
    latest.unlink()
    reason, prompt = handoff.decision()
    assert reason is None and handoff.receipt["run"] in prompt and "不原样重跑" in prompt
    assert "CoverageInfo(run=" in prompt and "不改 latest" in prompt
    assert not latest.exists()


def test_coverage_archive_is_verified_without_reading_or_updating_latest(handoff):
    run = handoff.receipt["run"]
    latest = handoff.results / "latest.json"
    latest.write_text("other latest bytes")
    archive = handoff.results.parent / run / "receipt.json"
    before = digest(archive)
    reply = coverage_tool(vars(handoff))._run(run=run, view="groups")
    assert reply["ok"] and reply["explicit_archive"] and reply["full_selection"] and reply["run"] == run
    assert reply["review"]["state"] == "complete"
    assert latest.read_text() == "other latest bytes" and digest(archive) == before


@pytest.mark.parametrize("fault", ["stale", "tamper", "wrong_path", "redirected"])
def test_coverage_archive_rejects_invalid_or_stale_receipt(handoff, fault):
    run = handoff.receipt["run"]
    archive = handoff.results.parent / run / "receipt.json"
    if fault == "stale":
        (handoff.results.parent / "pytest.ini").write_text("[pytest]\n# changed since signing\n")
    elif fault == "tamper":
        write_json(archive, {**handoff.receipt, "seed": 99})
    elif fault == "wrong_path":
        run = "results/../results/unit-audit-only"
    else:
        (handoff.results / "alias").symlink_to(archive.parent, target_is_directory=True)
        run = "results/alias"
    reply = coverage_tool(vars(handoff))._run(run=run)
    assert not reply["ok"] and reply["error_code"] == "UT_COVERAGE_INVALID"


def coverage_tool(fixture):
    """Bind the read-only tool to a synthetic workspace and controlled checked receipt."""
    return CoverageInfo(workspace=str(fixture["workspace"]), project="ut_project", dut="Block", cfg=Config({}))


def test_compact_groups_cover_all_and_only_the_location_zero_sets(native_review):
    """Branch/toggle groups close review representation, never alter counters or prove hardware."""
    before = inspect_review(native_review)
    save_review(native_review)
    result = inspect_review(native_review)
    assert result["review"]["state"] == "complete", result["review"]
    assert result["line"]["coverage"] == 50
    assert result["branch"]["coverage"] == 0
    assert result["toggle"]["coverage"] == 100 / 7
    for metric in ("line", "branch", "toggle"):
        assert {key: result[metric][key] for key in ("state", "found", "hit", "coverage", "uncovered")} == {
            key: before[metric][key] for key in ("state", "found", "hit", "coverage", "uncovered")}
    assert audit_project(native_review["workspace"], "Block", phase="line_coverage")["ok"]
    report = delivery_data(native_review["workspace"], "Block", "ut_project")
    assert "not a hardware verdict" in render_summary(report)


def test_missing_metric_and_position_are_counted_not_called_lcov_lines(native_review):
    """Omitting zero sets returns bounded, metric-specific counts and exact position examples."""
    native_review["entry"]["uncovered"] = native_review["entry"]["uncovered"][:1]
    save_review(native_review)
    review = inspect_review(native_review)["review"]
    assert review["state"] == "invalid"
    assert review["unreviewed_total"] == 9
    assert review["unreviewed_by_metric"] == {"line": 0, "branch": 3, "toggle": 6}
    assert len(review["unreviewed"]) == 3
    assert {row["metric"] for row in review["unreviewed"]} == {"branch", "toggle"}
    assert all(row["build"] == "unit-only" and row["source"] == "inputs/Block.sv" for row in review["unreviewed"])
    assert "Unreviewed LCOV" not in review["error"]
    assert not audit_project(native_review["workspace"], "Block", phase="line_coverage")["ok"]


@pytest.mark.parametrize("index,metric,count", [(0, "line", 1), (1, "branch", 3), (3, "toggle", 2)])
def test_one_omitted_position_still_blocks_complete_review(native_review, index, metric, count):
    """All other locations being reviewed cannot hide a single remaining metric/location."""
    native_review["entry"]["uncovered"].pop(index)
    save_review(native_review)
    review = inspect_review(native_review)["review"]
    assert review["state"] == "invalid" and review["unreviewed_total"] == count
    assert review["unreviewed_by_metric"][metric] == count


def test_many_unreviewed_locations_have_bounded_examples_and_complete_totals(native_review):
    """Diagnostics do not print every location, but still count all omitted metrics and points."""
    with native_review["native"].open("ab") as stream:
        for metric in ("branch", "toggle"):
            for line in range(100, 200):
                stream.write(point_bytes(metric, line, "unreviewed"))
    native_review["entry"]["uncovered"] = native_review["entry"]["uncovered"][:1]
    save_review(native_review)
    tool = coverage_tool(native_review)
    page = tool._run(metric="branch", view="groups", limit=5)
    assert page["groups_total"] == 101 and page["uncovered_total"] == 103
    assert len(page["groups"]) == 5
    review = page["review"]
    assert review["state"] == "invalid" and review["unreviewed_total"] == 209
    assert review["unreviewed_by_metric"] == {"line": 0, "branch": 103, "toggle": 106}
    assert len(review["unreviewed"]) == 8
    assert len(json.dumps(page)) < 15_000


def test_group_directory_is_bounded_and_keeps_exact_point_reads(native_review):
    """Directory counts and selectors agree with point pagination and exact-location filters."""
    tool = coverage_tool(native_review)
    first = tool._run(metric="toggle", view="groups", limit=1)
    assert first["ok"], first
    assert first["groups_total"] == 2 and first["uncovered_total"] == 6
    assert len(first["groups"]) == 1 and first["next_offset"] == 1
    second = tool._run(metric="toggle", view="groups", offset=1, limit=1)
    assert second["next_offset"] is None
    rows = first["groups"] + second["groups"]
    assert [row["zero_points"] for row in rows] == [4, 2]
    for row in rows:
        selector = row["selector"]
        assert selector["group"] == {"scope": "source-line"}
        points = tool._run(metric="toggle", build=selector["build"], source=selector["source"],
                           line=selector["line"], limit=200)
        assert points["ok"] and len(points["uncovered"]) == row["zero_points"]
        assert all(point["count"] == 0 for point in points["uncovered"])
    end = tool._run(metric="toggle", view="groups", offset=200)
    assert end["groups"] == [] and end["groups_total"] == 2


@pytest.mark.parametrize("change", [
    {"metric": "line"}, {"metric": "unknown"}, {"metric": []}, {"source": "inputs/*.sv"},
    {"line": 999}, {"line": True}, {"line": 0}, {"line": "10"},
    {"build": "other-build"}, {"build": ""}, {"point": "not-a-point"},
    {"group": {}}, {"group": {"scope": "all"}}, {"group": {"scope": "source-line", "end": 999}},
    {"group": []}, {"group": None}, {"line": 12, "metric": "toggle"},
    {"reason": " "}, {"status": "ignored"}, {"status": []}, {"range": [1, 999]},
])
def test_invalid_or_unknown_group_never_covers_counters(native_review, change):
    """Selectors are finite exact identities, not arbitrary scopes, globs or extra ranges."""
    native_review["entry"]["uncovered"][1].update(change)
    save_review(native_review)
    result = inspect_review(native_review)["review"]
    assert result["state"] == "invalid", result
    assert "branch" in result["error"] or str(change.get("metric", "branch")) in result["error"]
    assert not audit_project(native_review["workspace"], "Block", phase="line_coverage")["ok"]


@pytest.mark.parametrize("kind", ["group-group", "point-group", "group-point", "point-point"])
def test_duplicate_and_overlapping_dispositions_are_invalid(native_review, kind):
    """Every zero point has exactly one disposition even when selector forms are mixed."""
    report = inspect_review(native_review)
    exact = {**report["branch"]["uncovered"][0], "metric": "branch", "status": "justified", "reason": "Fixture only"}
    selector = native_review["entry"]["uncovered"][1]
    pair = {"group-group": [selector, deepcopy(selector)], "point-group": [exact, selector],
            "group-point": [selector, exact], "point-point": [exact, deepcopy(exact)]}[kind]
    native_review["entry"]["uncovered"][1:2] = pair
    save_review(native_review)
    review = inspect_review(native_review)["review"]
    assert review["state"] == "invalid" and "overlap" in review["error"].lower(), review


def test_line_stays_individual_and_exact_non_line_points_still_work(native_review):
    """Grouping is not a substitute for reviewing each physical line; exact points remain valid."""
    report = inspect_review(native_review)
    native_review["entry"]["uncovered"] = [native_review["entry"]["uncovered"][0]] + [
        {**row, "metric": metric, "status": "justified", "reason": "Independent fixture restriction"}
        for metric in ("branch", "toggle") for row in report[metric]["uncovered"]]
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "complete"
    native_review["entry"]["uncovered"][0]["group"] = {"scope": "source-line"}
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "invalid"


def test_exact_point_error_keeps_the_counter_identity(native_review):
    """A mismatched exact point is named as a point, not as an unexplained LCOV line."""
    native_review["entry"]["uncovered"][1].pop("group")
    native_review["entry"]["uncovered"][1]["point"] = "unknown-counter"
    save_review(native_review)
    review = inspect_review(native_review)["review"]
    assert review["state"] == "invalid"
    for value in ("metric=branch", "build=unit-only", "inputs/Block.sv", "line=10", "unknown-counter"):
        assert value in review["error"]


def test_group_gap_blocks_stage_and_delivery_without_changing_raw_coverage(native_review):
    """A known RTL failure is still a gap, not an automatic justification or coverage hit."""
    native_review["entry"]["uncovered"][2].update(status="gap", reason="Blocked by known RTL bug; remains required")
    save_review(native_review)
    report = inspect_review(native_review)
    assert report["review"]["state"] == "gaps" and len(report["review"]["gaps"]) == 1
    assert report["toggle"]["found"] == 7 and report["toggle"]["hit"] == 1
    assert not audit_project(native_review["workspace"], "Block", phase="line_coverage")["ok"]
    assert delivery_data(native_review["workspace"], "Block", "ut_project")["status"] == "INCOMPLETE"


def test_multiple_builds_need_explicit_identity_for_each_selector(native_review):
    """The same source position in two builds is never merged or inferred from its spelling."""
    data = native_review["data"]
    original = data["manifest"]["artifacts"][0]
    second = native_review["native"].parent / "second" / "coverage.dat"
    second.parent.mkdir()
    second.write_bytes(native_review["native"].read_bytes())
    lcov = second.with_suffix(".info")
    lcov.write_text(native_review["native"].with_suffix(".info").read_text())
    data["manifest"]["artifacts"].extend([
        {**original, "path": str(second), "build": {**original["build"], "build_id": "second"}},
        {"kind": "lcov", "path": str(lcov)}])
    native_review["entry"]["uncovered"] += [
        {**row, "build": "second"} for row in native_review["entry"]["uncovered"]]
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "complete"
    native_review["entry"]["uncovered"][1].pop("build")
    save_review(native_review)
    review = inspect_review(native_review)["review"]
    assert review["state"] == "invalid" and "build" in review["error"], review
    native_review["entry"]["uncovered"][1]["build"] = "unit-only"
    native_review["entry"]["uncovered"][0].pop("build")
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "invalid"


def test_single_build_default_and_no_lcov_do_not_weaken_review(native_review):
    """Build omission is allowed only for a unique build, while LCOV is still required."""
    for row in native_review["entry"]["uncovered"]:
        row.pop("build")
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "complete"
    data = native_review["data"]
    data["manifest"]["artifacts"] = [row for row in data["manifest"]["artifacts"] if row["kind"] != "lcov"]
    result = inspect_review(native_review)
    assert result["line"]["state"] == "not_collected" and result["line"]["coverage"] is None
    assert result["review"]["state"] == "invalid" and "LCOV" in result["review"]["error"]


def test_not_collected_metric_cannot_be_reviewed_by_fabricated_group(native_review):
    """An explicit selector cannot invent collection of another metric."""
    native_review["native"].write_bytes(b"# SystemC::Coverage-3\n")
    save_review(native_review)
    result = inspect_review(native_review)
    assert result["branch"]["state"] == "not_collected"
    assert result["review"]["state"] == "invalid" and "no actual zero points" in result["review"]["error"]


@pytest.mark.parametrize("change", [{"run": "results/stale"}, {"sha256": "0" * 64}])
def test_compact_reviews_do_not_bypass_run_or_source_freshness(native_review, change):
    """Compact syntax uses the same exact current run and independent-source fingerprint."""
    native_review["entry"].update(change)
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "invalid"


def test_tool_keeps_missing_metrics_wrong_dut_and_stale_run_invalid(project, checked_evidence, monkeypatch):
    """The directory view never supplies evidence absent from the checked current run."""
    tool = CoverageInfo(workspace=str(project), project="ut_project", dut="Block", cfg=Config({}))
    monkeypatch.setattr("toffee_ut.tools.current_run", lambda *args: checked_evidence)
    result = tool._run(metric="branch", view="groups")
    assert result["ok"] and result["metrics"]["branch"]["state"] == "not_collected"
    assert result["metrics"]["branch"]["coverage"] is None and result["groups"] == []
    assert result["metrics"]["line"]["state"] == "not_collected"
    checked_evidence["record"]["dut"] = "Other"
    assert not tool._run(view="groups")["ok"]

    def stale(*args):
        """Replace only signed-reader input, never create or accept a stale receipt."""
        raise ValueError("Run is stale for current sources")

    monkeypatch.setattr("toffee_ut.tools.current_run", stale)
    assert "stale" in tool._run(view="groups")["error"]


def test_mcp_schema_exposes_one_finite_directory_view(native_review):
    """The read-only MCP schema exposes bounded pagination and exact filters, no alternate selectors."""
    schema = to_mcp_tool(coverage_tool(native_review)).parameters
    assert schema["additionalProperties"] is False
    assert schema["properties"]["view"]["enum"] == ["points", "groups"]
    assert schema["properties"]["limit"]["maximum"] == 200
    assert {"build", "source", "line"} <= schema["properties"].keys()


def test_guide_compact_example_matches_the_same_review_contract(native_review):
    """The complete guide example parses and closes only matching synthetic zero sets."""
    from toffee_ut.audit import read_spec
    guide = Path(__file__).parents[1] / "src/toffee_ut/Guide_Doc/ut-coverage.md"
    example = read_spec(guide, "stage_evidence", "Queue")["reviews"]["line_coverage"]["uncovered"]
    native = native_review["native"]
    native.write_bytes(b"# SystemC::Coverage-3\n" + point_bytes("branch", 42, "alternative")
                       + point_bytes("toggle", 42, "instance-a.bit[0]") + point_bytes("toggle", 42, "instance-b.bit[1]"))
    native.with_suffix(".info").write_text("SF:inputs/Block.sv\nDA:42,0\nend_of_record\n")
    native_review["entry"]["uncovered"] = [
        {**row, "source": "inputs/Block.sv", "build": "unit-only"} for row in example]
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "complete"


def test_half_million_points_use_indexed_matching_and_bounded_output(native_review, monkeypatch):
    """Scale is enforced by lookup budgets and compact output, not fragile wall-clock limits."""
    native = native_review["native"]
    with native.open("wb") as stream:
        stream.write(b"# SystemC::Coverage-3\n")
        for index in range(500_000):
            stream.write(point_bytes("branch" if index < 250_000 else "toggle", 10 + index % 64, f"bit[{index}]"))
    entry = native_review["entry"]
    entry["uncovered"] = entry["uncovered"][:1] + [group(metric, line)
        for metric in ("branch", "toggle") for line in range(10, 74)]
    save_review(native_review)
    from toffee_ut import audit
    original = audit.read_spec
    lookups = 0

    class CountedRow(dict):
        """Fail deterministically if matching rescans all points for each disposition."""

        def get(self, *args):
            """Budget review-row lookups independently of CPU speed or test scheduling."""
            nonlocal lookups
            lookups += 1
            assert lookups <= 128 * len(entry["uncovered"]), "Quadratic review-row matching"
            return super().get(*args)

    def counted(*args, **kwargs):
        """Preserve real YAML parsing, instrumenting only the review disposition mappings."""
        value = original(*args, **kwargs)
        if value.get("kind") == "stage_evidence":
            review = value["reviews"]["line_coverage"]
            review["uncovered"] = [CountedRow(row) for row in review["uncovered"]]
        return value

    monkeypatch.setattr(audit, "read_spec", counted)
    start = time.perf_counter()
    report = coverage_data(native_review["workspace"], "ut_project", "Block", native_review["data"],
                           directory=("toggle", {}, 0, 10))
    assert report["review"]["state"] == "complete", report["review"]
    assert report["branch"]["found"] == report["toggle"]["found"] == 250_000
    assert report["directory"]["groups_total"] == 64 and report["directory"]["uncovered_total"] == 250_000
    assert len(report["directory"]["groups"]) == 10
    monkeypatch.setattr("toffee_ut.tools.coverage_data", lambda *args, **kwargs: report)
    page = coverage_tool(native_review)._run(metric="toggle", view="groups", limit=10)
    assert page["groups_total"] == 64 and len(page["groups"]) == 10
    assert len(json.dumps(page)) < 20_000
    import resource
    print({"zero_points": 500_001, "review_rows": len(entry["uncovered"]), "review_lookups": lookups,
           "elapsed_seconds": time.perf_counter() - start, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
