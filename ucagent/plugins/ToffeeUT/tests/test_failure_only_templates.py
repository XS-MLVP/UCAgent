"""Reject known failure-only templates using text fixtures, never DUT execution."""

import pytest

from toffee_ut.audit import audit_project
from toffee_ut.checkers import ToffeeUTBatchChecker
from toffee_ut.implementation import failure_only_tests
from toffee_ut.paths import write_json


@pytest.mark.parametrize("text,expected", [
    ('import pytest\ndef test_one():\n    pytest.fail("pending")\n', {"test_one"}),
    ('import pytest as p\nasync def test_one():\n    p.fail("pending")\n', {"test_one"}),
    ('from pytest import fail as stop\ndef test_one():\n    return stop("pending")\n', {"test_one"}),
    ('import pytest\nclass TestQueue:\n    def test_one(self):\n        pytest.fail("pending")\n',
     {"TestQueue::test_one"}),
    ('import pytest\ndef helper():\n    pytest.fail("helper, not a collected test")\n', set()),
    ('def test_one(result):\n    assert result == 17\n', set()),
    ('import pytest\ndef test_one(env):\n    if env.mismatch:\n        pytest.fail("actual mismatch")\n', set()),
    ('import pytest\ndef test_one(env):\n    pytest.fail(env.exercise_and_describe())\n', set()),
    ('import pytest\nasync def test_one(env):\n    pytest.fail(await env.exercise())\n', set()),
    ('from another import fail\ndef test_one():\n    fail("not pytest")\n', set()),
    ('import pytest\ndef test_one(pytest):\n    pytest.fail("fixture-owned API")\n', set()),
    ('import pytest\npytest = other\ndef test_one():\n    pytest.fail("rebound object")\n', set()),
    ('import pytest\nfrom helpers import exercise as pytest\ndef test_one(env):\n    pytest.fail(env)\n', set()),
    ('from pytest import fail\nfrom helpers import exercise as fail\ndef test_one(env):\n    fail(env)\n', set()),
    ('import pytest\nimport exercise as pytest\ndef test_one(env):\n    pytest.fail(env)\n', set()),
    ('from helpers import exercise as AssertionError\ndef test_one(env):\n    raise AssertionError(env)\n', set()),
    ('import pytest\nclass Harness:\n    def test_helper(self):\n        pytest.fail("not collected")\n', set()),
    ('import pytest\nclass TestDisabled:\n    __test__ = False\n'
     '    def test_helper(self):\n        pytest.fail("not collected")\n', set()),
    ('import pytest\n__test__ = False\ndef test_one():\n    pytest.fail("not collected")\n', set()),
    ('import pytest\nclass TestConstructed:\n    def __init__(self):\n        pass\n'
     '    def test_helper(self):\n        pytest.fail("not collected")\n', set()),
    ('import pytest\ndef testValue():\n    pytest.fail("default pytest naming")\n', {"testValue"}),
    ('def test_one(AssertionError):\n    raise AssertionError("fixture-owned API")\n', set()),
    ('import pytest\ndef test_one():\n    def test_nested():\n        pytest.fail("not collected")\n'
     '    assert test_nested is not None\n', set()),
])
def test_failure_only_detection_is_narrow_and_does_not_execute_source(tmp_path, text, expected):
    """Only immediate known failures in collected function/method bodies are classified."""
    path = tmp_path / "test_text_fixture.py"
    path.write_text(text)
    result = failure_only_tests(path)
    assert set(result) == expected
    assert all(type(line) is int and line > 0 for line in result.values())


@pytest.mark.parametrize("body", [
    'pytest.fail("blocked by another issue", pytrace=False)',
    '"""Scenario has not been implemented."""\n    pytest.fail(BLOCKER + " template")',
    'assert False, "blocked pending configuration"',
    'raise AssertionError("scenario not implemented")',
])
def test_fail_only_function_does_not_satisfy_implemented_test_gate(project, body):
    """Renaming a placeholder failure does not implement a functional scenario."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\nBLOCKER = "unimplemented"\n'
                    '@pytest.mark.scenario("S1")\ndef test_value(env):\n    ' + body + "\n")
    result = audit_project(project, "Block", phase="tests")
    assert not result["ok"], "A failure-only template was accepted as implemented"
    assert "test_contract.py" in result["error"] and "test_value" in result["error"]


def test_fail_only_template_remains_allowed_in_template_creation_stage(project):
    """Template creation precedes implementation and must not require fabricated DUT work."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'def test_value(env):\n    pytest.fail("unimplemented")\n')
    assert audit_project(project, "Block", phase="templates")["ok"]


def test_real_stimulus_before_failure_is_not_rejected_as_a_template(project):
    """A real API call followed by a retained failure is not the known empty-body pattern."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'async def test_value(env):\n    await env.check_transaction()\n'
                    '    pytest.fail("observed contract mismatch")\n')
    assert audit_project(project, "Block", phase="tests")["ok"]


def test_fail_only_template_cannot_supply_batch_completion_credit(project, checked_evidence, monkeypatch):
    """A signed FAIL with native registration still cannot implement an empty scenario."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'def test_value(env):\n    pytest.fail("blocked template")\n')
    case = next(iter(checked_evidence["cases"]["cases"].values()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    monkeypatch.setattr("toffee_ut.checkers.current_run", lambda workspace, project: checked_evidence)
    checker = ToffeeUTBatchChecker(phase="case_batch", dut="Block")
    checker.set_workspace(str(project))
    source, generated = checker._current_items()
    assert source == ["S1"]
    assert generated == [], "The batch incorrectly credited an unimplemented failing template"


def test_batch_keeps_real_failures_with_preceding_work(project, checked_evidence, monkeypatch):
    """Rejecting known templates must not erase implementation credit for an actual failing test."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'async def test_value(env):\n    await env.check_transaction()\n'
                    '    pytest.fail("observed mismatch")\n')
    node, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    checked_evidence["cases"]["cases"] = {node + "[parameter]": case}
    monkeypatch.setattr("toffee_ut.checkers.current_run", lambda workspace, project: checked_evidence)
    checker = ToffeeUTBatchChecker(phase="case_batch", dut="Block")
    checker.set_workspace(str(project))
    assert checker._current_items() == (["S1"], ["S1"])


def test_batch_rejects_parameterized_class_template(project, checked_evidence, monkeypatch):
    """Class and parameter nodeid wrappers do not hide a recognized empty test body."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\nclass TestQueue:\n    @pytest.mark.scenario("S1")\n'
                    '    def test_value(self, env):\n        pytest.fail("blocked template")\n')
    _, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    checked_evidence["cases"]["cases"] = {
        "testbenches/block/tests/test_contract.py::TestQueue::test_value[parameter]": case}
    monkeypatch.setattr("toffee_ut.checkers.current_run", lambda workspace, project: checked_evidence)
    checker = ToffeeUTBatchChecker(phase="case_batch", dut="Block")
    checker.set_workspace(str(project))
    assert checker._current_items() == (["S1"], [])


@pytest.mark.parametrize("filename", ["test_contract.py", "contract_test.py"])
@pytest.mark.parametrize("explicit_file", [False, True])
def test_file_and_directory_layouts_agree_on_default_collected_templates(project, filename, explicit_file):
    """Both default file patterns use the same template/implementation stage boundary."""
    root = project / "ut_project"
    path = root / "testbenches/block/tests/test_contract.py"
    if filename != path.name:
        path = path.rename(path.with_name(filename))
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'def testValue(env):\n    pytest.fail("pending implementation")\n')
    if explicit_file:
        write_json(root / "workspace.json", {"schema": 2, "fixtures": "conftest.py", "duts": {"Block": {
            "testbench": "block", "environment": "testbenches/block/env.py",
            "tests": [path.relative_to(root).as_posix()], "design_spec": "docs/spec/design/Block.md",
            "verification_spec": "docs/spec/verification/Block.md"}}})
    assert audit_project(project, "Block", phase="templates")["ok"]
    result = audit_project(project, "Block", phase="tests")
    assert not result["ok"] and filename in result["error"]


@pytest.mark.parametrize("parameter", ["plain", "left::right"])
@pytest.mark.parametrize("class_method", [False, True])
@pytest.mark.parametrize("real_work", [False, True])
def test_parameter_nodeids_cannot_change_template_or_real_failure_credit(
        project, checked_evidence, monkeypatch, parameter, class_method, real_work):
    """Parameter separators are data, not additional Python object identity components."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    definition = 'async def test_value(env):\n'
    body = '    await env.check_transaction()\n' if real_work else ""
    body += '    pytest.fail("recorded failure")\n'
    source = 'import pytest\n@pytest.mark.scenario("S1")\n' + definition + body
    if class_method:
        source = 'import pytest\nclass TestQueue:\n' + "\n".join(
            "    " + line for line in ('@pytest.mark.scenario("S1")\n' + definition + body).splitlines()) + "\n"
    path.write_text(source)
    node, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    node = node.split("::", 1)[0] + "::" + ("TestQueue::" if class_method else "") + f"test_value[{parameter}]"
    checked_evidence["cases"]["cases"] = {node: case}
    monkeypatch.setattr("toffee_ut.checkers.current_run", lambda workspace, project: checked_evidence)
    checker = ToffeeUTBatchChecker(phase="case_batch", dut="Block")
    checker.set_workspace(str(project))
    assert checker._current_items() == (["S1"], ["S1"] if real_work else [])


def test_declared_pytest_patterns_are_used_without_executing_test_code(project):
    """Custom naming remains a declared collection choice, not a new metadata requirement."""
    root = project / "ut_project"
    (root / "pytest.ini").write_text("[pytest]\npython_files = checks_*.py\npython_classes = Verify\npython_functions = check\n")
    path = root / "testbenches/block/tests/checks_contract.py"
    path.write_text('import pytest\nclass VerifyQueue:\n'
                    '    def check_value(self):\n        pytest.fail("pending")\n')
    assert set(failure_only_tests(path, project=root)) == {"VerifyQueue::check_value"}
    result = audit_project(project, "Block", phase="tests")
    assert not result["ok"] and "checks_contract.py" in result["error"]


def test_uncollected_helper_classes_do_not_block_a_real_test(project):
    """Ordinary and explicitly disabled class helpers are not collected functional templates."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\nclass Harness:\n'
                    '    def test_helper(self):\n        pytest.fail("helper")\n'
                    'class TestDisabled:\n    __test__ = False\n'
                    '    def test_helper(self):\n        pytest.fail("disabled helper")\n'
                    '@pytest.mark.scenario("S1")\nasync def test_real(env):\n'
                    '    await env.check_transaction()\n')
    assert audit_project(project, "Block", phase="tests")["ok"]


def test_malformed_collection_options_return_a_named_repair_diagnostic(project):
    """Invalid declared naming configuration does not leak a parser exception through the gate."""
    root = project / "ut_project"
    (root / "pytest.ini").write_text("not an ini section\npython_files = test_*.py\n")
    result = audit_project(project, "Block", phase="tests")
    assert not result["ok"] and "pytest.ini" in result["error"]


@pytest.mark.parametrize("filename", ["test_contract.py", "contract_test.py"])
def test_batch_default_filename_and_function_prefix_match_implementation_audit(
        project, checked_evidence, monkeypatch, filename):
    """Default pytest filename variants and the test prefix share the same batch exclusion."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    if path.name != filename:
        path = path.rename(path.with_name(filename))
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'def testValue(env):\n    pytest.fail("empty")\n')
    _, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    checked_evidence["cases"]["cases"] = {f"testbenches/block/tests/{filename}::testValue": case}
    monkeypatch.setattr("toffee_ut.checkers.current_run", lambda workspace, project: checked_evidence)
    checker = ToffeeUTBatchChecker(phase="case_batch", dut="Block")
    checker.set_workspace(str(project))
    assert checker._current_items() == (["S1"], [])
