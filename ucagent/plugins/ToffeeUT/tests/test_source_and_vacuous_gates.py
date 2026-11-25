"""Independent inputs and implemented test bodies cannot be replaced with self-attestation."""

import json

import pytest

from toffee_ut.audit import audit_project, delivery_data, read_spec
from toffee_ut.checkers import ToffeeUTBatchChecker
from toffee_ut.implementation import non_verifying_tests
from toffee_ut.sources import source_record_path
from toffee_ut.tools import UTProject
from ucagent.util.config import Config


@pytest.mark.parametrize("body", ["pass", "assert True", "assert 1 == 1", "return None", "...",
                                  '"Only a docstring"', "pass\n    assert True\n    return None"])
def test_vacuous_bodies_cannot_pass_implementation_audit(project, body):
    """Successful collection or fixture registration cannot credit an empty scenario."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('import pytest\n@pytest.mark.scenario("S1")\ndef test_value():\n    ' + body + '\n')
    result = audit_project(project, "Block", phase="tests")
    assert not result["ok"] and "vacuous" in result["error"]


@pytest.mark.parametrize("body", ["verify_response(env)", "assert env.result == expected",
                                  "await verify_response(env)", "return check_response(env)"])
def test_delegated_verification_does_not_require_inline_assert(tmp_path, body):
    """Helpers, fixtures with consumed results and asynchronous comparisons remain valid."""
    path = tmp_path / "test_helper.py"
    path.write_text("async def test_response(env, expected):\n    " + body + "\n")
    assert non_verifying_tests(path) == {}


@pytest.mark.parametrize("mutation", ["self_authored", "url", "changed_input", "forged_record", "missing_record"])
def test_confirmed_requirements_need_captured_unchanged_inputs(project, contract_writer, mutation):
    """Existence, URL syntax and edits to unsigned inventory do not establish source provenance."""
    path = project / "ut_project/docs/spec/design/Block.md"
    design = read_spec(path, "design", "Block")
    source_record, _ = source_record_path(project, "Block", "ut_project")
    if mutation == "self_authored":
        source = project / "ut_project/docs/self-authored.md"
        source.write_text("The DUT is correct.")
        design["requirements"][0]["source"] = source.relative_to(project).as_posix()
    elif mutation == "url":
        design["requirements"][0]["source"] = "https://unverified.invalid/claim"
    elif mutation == "changed_input":
        (project / "inputs/interface.md").write_text("Changed after startup")
    elif mutation == "forged_record":
        record = json.loads(source_record.read_text())
        record["documents"]["arbitrary.md"] = "fake"
        source_record.write_text(json.dumps(record))
    else:
        source_record.unlink()
    contract_writer(path, design)
    result = audit_project(project, "Block", phase="design")
    assert not result["ok"] and result["next_action"]


@pytest.mark.parametrize("skills", [False, True])
def test_inspect_cannot_promote_late_files_or_refresh_changed_inputs(project, skills):
    """The normal tool binds its source set before model edits regardless of optional Skills."""
    cfg = Config({"runtime_options": {"ut_documents": ["inputs"]}, "skill": {"use_skill": skills},
                  "write_dirs": ["ut_project"], "un_write_dirs": []}).freeze()
    tool = UTProject(workspace=str(project), project="ut_project", dut="Block", cfg=cfg)
    (project / "inputs/late.md").write_text("Late self-authored assertion")
    assert tool._run("inspect")["ok"]
    record_path, _ = source_record_path(project, "Block", "ut_project")
    original = record_path.read_bytes()
    assert "inputs/late.md" not in json.loads(original)["documents"]
    (project / "inputs/interface.md").write_text("Changed to match RTL")
    result = tool._run("inspect")
    assert not result["ok"] and "input changed" in result["error"]
    assert record_path.read_bytes() == original


@pytest.mark.parametrize("body", ["pass", "assert True", "return None"])
def test_signed_fixture_registration_cannot_credit_vacuous_pass(project, checked_evidence, monkeypatch, body):
    """Synthetic audit inputs prove gate behavior, not a fabricated native end-to-end PASS."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('import pytest\n@pytest.mark.scenario("S1")\ndef test_value():\n    ' + body + '\n')
    for case in checked_evidence["cases"]["cases"].values():
        case["roles"] = ["api"]
    monkeypatch.setattr("toffee_ut.stage_audit.current_run", lambda *args: checked_evidence)
    monkeypatch.setattr("toffee_ut.checkers.current_run", lambda *args: checked_evidence)
    checker = ToffeeUTBatchChecker("case_batch", dut="Block")
    checker.set_workspace(str(project))
    assert checker._current_items() == (["S1"], [])
    result = audit_project(project, "Block", phase="api_tests")
    assert not result["ok"] and "vacuous" in result["error"]
    summary = delivery_data(project, "Block", "ut_project")
    assert summary["status"] == "INCOMPLETE" and "non_verifying_tests" in summary["problems"]
