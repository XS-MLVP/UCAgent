"""Audit collected literal scenario markers offline, without native or run credit."""

import json
import os
import subprocess
import sys
from textwrap import dedent, indent

import pytest

from toffee_ut.audit import audit_project, read_spec
from toffee_ut.implementation import failure_only_tests
from toffee_ut.paths import write_json
from toffee_ut.stage_audit import audit_restored_phase


@pytest.fixture
def scenario_project(project, contract_writer, monkeypatch):
    """Declare two active scenarios and forbid execution evidence in structural audits."""
    path = project / "ut_project/docs/spec/verification/Block.md"
    specification = read_spec(path, "verification", "Block")
    specification["scenarios"].append({**specification["scenarios"][0], "id": "S2"})
    contract_writer(path, specification)

    def unexpected_run(*args, **kwargs):
        """A template or empty-body check must not request a current run."""
        pytest.fail("Structural scenario audit requested current_run")

    monkeypatch.setattr("toffee_ut.stage_audit.current_run", unexpected_run)
    monkeypatch.setattr("toffee_ut.audit.current_run", unexpected_run)
    return project


def write_test(project, source):
    """Replace only the synthetic project's default test source, without importing it."""
    path = project / "ut_project/testbenches/block/tests/test_contract.py"
    path.write_text("import pytest\n" + dedent(source))
    return path


@pytest.mark.parametrize("source", [
    pytest.param('''
        @pytest.mark.scenario("S1")
        def test_one():
            assert False, "Not implemented"
        @pytest.mark.scenario("S2")
        def test_two():
            pytest.fail("pending")
    ''', id="single-ids"),
    pytest.param('''
        @pytest.mark.scenario("S1")
        @pytest.mark.scenario("S2")
        def test_value():
            pytest.fail("pending")
    ''', id="stacked"),
    pytest.param('''
        @pytest.mark.scenario("S1", "S2")
        def test_value():
            assert False, "Not implemented"
    ''', id="multiarg-function"),
    pytest.param('''
        @pytest.mark.scenario(
            "S1",
            "S2",
        )
        async def test_value():
            pytest.fail("pending")
    ''', id="multiline-async"),
    pytest.param('''
        class TestQueue:
            @pytest.mark.scenario("S1", "S2")
            def test_value(self):
                pytest.fail("pending")
    ''', id="class-method"),
    pytest.param('''
        @pytest.mark.scenario("S1", "S2")
        class TestQueue:
            def test_value(self):
                pytest.fail("pending")
    ''', id="class-marker"),
    pytest.param('''
        @pytest.mark.scenario("S1")
        @pytest.mark.scenario("S2")
        class TestQueue:
            def test_value(self):
                pytest.fail("pending")
    ''', id="stacked-class-markers"),
    pytest.param('''
        @pytest.mark.scenario("S1")
        class TestQueue:
            @pytest.mark.scenario("S2")
            def test_value(self):
                pytest.fail("pending")
    ''', id="class-and-method"),
    pytest.param('''
        @pytest.mark.scenario("S1")
        class TestFirst:
            def test_value(self):
                pytest.fail("pending")
        @pytest.mark.scenario("S2")
        class TestSecond:
            def test_value(self):
                pytest.fail("pending")
    ''', id="multiple-classes"),
    pytest.param('''
        import pytest as p
        @p.mark.scenario("S1", "S2")
        def test_value():
            p.fail("pending")
    ''', id="pytest-import-alias"),
    pytest.param('''
        class TestQueue:
            pytestmark = [pytest.mark.scenario("S1", "S2")]
            def test_value(self):
                pytest.fail("pending")
    ''', id="class-pytestmark"),
])
def test_templates_accept_all_literal_ids_on_collected_entries(scenario_project, source):
    """Templates may fail explicitly and need neither a run nor a successful result."""
    write_test(scenario_project, source)
    result = audit_restored_phase(scenario_project, "Block", "ut_project", "templates")
    assert result["ok"], result
    assert audit_project(scenario_project, "Block", phase="templates")["ok"]


@pytest.mark.parametrize("extra", [
    pytest.param('# @pytest.mark.scenario("S2")\n', id="comment"),
    pytest.param('EXAMPLE = \'@pytest.mark.scenario("S2")\'\n', id="string"),
    pytest.param('''
        @pytest.mark.scenario("S2")
        def helper():
            pytest.fail("not collected")
    ''', id="helper-function"),
    pytest.param('''
        def test_outer():
            @pytest.mark.scenario("S2")
            def test_nested():
                pytest.fail("not collected")
    ''', id="nested-function"),
    pytest.param('''
        @pytest.mark.scenario("S2")
        class Harness:
            def test_value(self):
                pytest.fail("not collected")
    ''', id="helper-class"),
    pytest.param('''
        @pytest.mark.scenario("S2")
        class TestEmpty:
            def helper(self):
                pytest.fail("not collected")
    ''', id="class-without-tests"),
    pytest.param('''
        @pytest.mark.scenario("S2")
        class TestDisabled:
            __test__ = False
            def test_value(self):
                pytest.fail("not collected")
    ''', id="disabled-class"),
    pytest.param('''
        class TestConstructed:
            def __init__(self):
                pass
            @pytest.mark.scenario("S2")
            def test_value(self):
                pytest.fail("not collected")
    ''', id="constructed-class"),
    pytest.param('''
        @pytest.mark.scenario("S2")
        def test_disabled():
            pytest.fail("not collected")
        test_disabled.__test__ = False
    ''', id="disabled-function"),
    pytest.param('''
        @pytest.fixture
        @pytest.mark.scenario("S2")
        def test_fixture():
            pytest.fail("fixture, not a test")
    ''', id="fixture"),
    pytest.param('''
        @pytest.mark.selftest
        @pytest.mark.scenario("S2")
        def test_adapter():
            pytest.fail("no functional credit")
    ''', id="selftest"),
    pytest.param('''
        @pytest.mark.selftest
        class TestAdapter:
            @pytest.mark.scenario("S2")
            def test_value(self):
                pytest.fail("no functional credit")
    ''', id="class-selftest"),
    pytest.param('''
        __test__ = False
        @pytest.mark.scenario("S2")
        def test_disabled_module():
            pytest.fail("not collected")
    ''', id="disabled-module"),
    pytest.param('''
        pytestmark = pytest.mark.selftest
        @pytest.mark.scenario("S2")
        def test_adapter_module():
            pytest.fail("no functional credit")
    ''', id="module-selftest"),
    pytest.param('''
        class TestAdapter:
            pytestmark = [pytest.mark.selftest]
            @pytest.mark.scenario("S2")
            def test_value(self):
                pytest.fail("no functional credit")
    ''', id="class-pytestmark-selftest"),
    pytest.param('''
        import another_module as pytest
        @pytest.mark.scenario("S2")
        def test_value():
            pytest.fail("not a pytest import")
    ''', id="rebound-pytest"),
])
def test_uncollected_or_selftest_markers_do_not_supply_active_templates(scenario_project, extra):
    """Source text outside a collected functional entry cannot fill a missing scenario."""
    write_test(scenario_project, '@pytest.mark.scenario("S1")\n'
               'def test_real():\n    pytest.fail("pending")\n' + dedent(extra))
    result = audit_project(scenario_project, "Block", phase="templates")
    assert not result["ok"], result
    assert "Each active scenario requires" in result["error"]


@pytest.mark.parametrize("arguments", [
    '"S1", "S" + "2"', '"S1", scenario_id', '*["S1", "S2"]',
    '"S1", "S2", unknown', '"S1", "S2", extra=True',
])
def test_unproven_marker_arguments_do_not_get_guessed(scenario_project, arguments):
    """Only an entirely literal, runtime-valid marker supplies statically proven IDs."""
    write_test(scenario_project, f'@pytest.mark.scenario({arguments})\n'
               'def test_value():\n    pytest.fail("pending")\n')
    result = audit_project(scenario_project, "Block", phase="templates")
    assert not result["ok"], result
    assert "Each active scenario requires" in result["error"]


@pytest.mark.parametrize("filename,class_name,function_name,options,explicit", [
    ("test_contract.py", "TestQueue", "testValue", "", False),
    ("contract_test.py", "TestQueue", "test_value", "", False),
    ("scenario_cases.py", "TestQueue", "test_value", "", True),
    ("checks_contract.py", "VerifyQueue", "check_value",
     "python_files = checks_*.py\npython_classes = Verify\npython_functions = check\n", False),
    ("checks_contract.py", "VerifyQueue", "check_value",
     "python_files = checks_*.py\npython_classes = Verify*\npython_functions = check_*\n", False),
])
def test_scenario_collection_respects_declared_locations_and_pytest_names(
        scenario_project, filename, class_name, function_name, options, explicit):
    """Default, custom and explicit-file selection share class/method marker semantics."""
    root = scenario_project / "ut_project"
    original = write_test(scenario_project, '"""No default test entry."""\n')
    path = original.with_name(filename)
    path.write_text('import pytest\n@pytest.mark.scenario("S1", "S2")\n'
                    f'class {class_name}:\n    def {function_name}(self):\n'
                    '        pytest.fail("pending")\n')
    (root / "pytest.ini").write_text("[pytest]\nmarkers =\n    scenario: Contract scenario IDs\n" + options)
    if explicit:
        write_json(root / "workspace.json", {"schema": 2, "fixtures": "conftest.py", "duts": {"Block": {
            "testbench": "block", "environment": "testbenches/block/env.py",
            "tests": [path.relative_to(root).as_posix()], "design_spec": "docs/spec/design/Block.md",
            "verification_spec": "docs/spec/verification/Block.md"}}})
    # This independent collection oracle imports only our pure synthetic source;
    # the audited implementation itself never imports or collects project code.
    selection = path if explicit else path.parent
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(selection)],
        cwd=root, env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
        text=True, capture_output=True, timeout=30, check=False)
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert f"{path.relative_to(root).as_posix()}::{class_name}::{function_name}" in collected.stdout
    result = audit_project(scenario_project, "Block", phase="templates")
    assert result["ok"], result


@pytest.mark.parametrize("phase", ["tests", "case_batch", "refine_tests"])
@pytest.mark.parametrize("body", ['pytest.fail("pending")', 'assert False, "Not implemented"'])
def test_multiarg_template_does_not_gain_implementation_credit(scenario_project, phase, body):
    """Recognizing both labels does not implement or execute an empty scenario."""
    write_test(scenario_project, '@pytest.mark.scenario("S1", "S2")\n'
               'def test_value():\n    ' + body + '\n')
    result = audit_project(scenario_project, "Block", phase=phase)
    assert not result["ok"], result
    assert "Unimplemented" in result["error"] and "test_contract.py" in result["error"]


@pytest.mark.parametrize("phase", ["case_batch", "refine_tests"])
def test_implemented_multiarg_entry_still_requires_execution(scenario_project, monkeypatch, phase):
    """Static membership never replaces the later phases' existing run requirement."""
    write_test(scenario_project, '@pytest.mark.scenario("S1", "S2")\n'
               'async def test_value(env):\n    await env.check_transaction()\n')

    def no_execution(*args, **kwargs):
        """Expose that membership passed, without fabricating a native execution receipt."""
        raise ValueError("Synthetic test has no execution evidence")

    monkeypatch.setattr("toffee_ut.stage_audit.current_run", no_execution)
    result = audit_project(scenario_project, "Block", phase=phase)
    assert not result["ok"], result
    assert result["error"] == "Synthetic test has no execution evidence"


def collect_synthetic_entries(project, path):
    """Read actual pytest marker membership from our pure synthetic collection only."""
    root = project / "ut_project"
    (root / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    scenario: Contract IDs\n    selftest: Adapter selftest\n")
    (root / "conftest.py").write_text('''"""Record pure collection, without constructing an environment or DUT."""
import json
from pathlib import Path

def pytest_collection_modifyitems(items):
    """Persist the collected nodes and their real inherited markers for the test oracle."""
    rows = [{"nodeid": item.nodeid,
             "scenarios": sorted({value for marker in item.iter_markers("scenario") for value in marker.args}),
             "selftest": item.get_closest_marker("selftest") is not None} for item in items]
    Path("collected.json").write_text(json.dumps(rows))
''')
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(path)], cwd=root,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
        text=True, capture_output=True, timeout=30, check=False)
    assert collected.returncode in {0, 5}, collected.stdout + collected.stderr
    return json.loads((root / "collected.json").read_text())


@pytest.mark.parametrize("scope", ["module", "class"])
@pytest.mark.parametrize("bindings,ids,expected", [
    pytest.param('pytestmark = [pytest.mark.scenario("S2")]\npytestmark = []\n',
                 '"S1"', {"S1"}, id="clear-mark"),
    pytest.param('pytestmark = [pytest.mark.scenario("S2")]\n'
                 'pytestmark = [pytest.mark.scenario("S1")]\n',
                 '"S1"', {"S1"}, id="replace-mark"),
    pytest.param('pytestmark = []\npytestmark = pytest.mark.scenario("S2")\n',
                 '"S1"', {"S1", "S2"}, id="restore-mark"),
    pytest.param('pytestmark = [pytest.mark.scenario("S2")]\npytestmark: list = []\n',
                 '"S1"', {"S1"}, id="annotated-clear"),
    pytest.param('pytestmark = [pytest.mark.scenario("S2")]\npytestmark: list\n',
                 '"S1"', {"S1", "S2"}, id="annotation-only"),
    pytest.param('pytestmark = [pytest.mark.selftest]\npytestmark = []\n',
                 '"S1", "S2"', {"S1", "S2"}, id="clear-selftest"),
    pytest.param('pytestmark = [pytest.mark.selftest]\n'
                 'pytestmark = [pytest.mark.scenario("S2")]\n',
                 '"S1"', {"S1", "S2"}, id="replace-selftest"),
    pytest.param('pytestmark = []\npytestmark = [pytest.mark.selftest]\n',
                 '"S1", "S2"', set(), id="final-selftest"),
    pytest.param('pytestmark = [pytest.mark.scenario("S2")]\n'
                 'unknown_marks = []\npytestmark = unknown_marks\n',
                 '"S1"', {"S1"}, id="unknown-final-mark"),
])
def test_final_pytestmark_binding_matches_collection(scenario_project, scope, bindings, ids, expected):
    """Replacing namespace marks neither retains removed IDs nor a cleared selftest flag."""
    source = bindings + f'@pytest.mark.scenario({ids})\n'
    arguments = "self" if scope == "class" else ""
    source += f'def test_real({arguments}):\n    pytest.fail("pending")\n'
    if scope == "class":
        source = "class TestQueue:\n" + indent(source, "    ")
    path = write_test(scenario_project, source)
    entries = collect_synthetic_entries(scenario_project, path)
    functional = {tag for entry in entries if not entry["selftest"] for tag in entry["scenarios"]}
    assert functional == expected, entries
    result = audit_project(scenario_project, "Block", phase="templates")
    assert result["ok"] == (expected == {"S1", "S2"}), result
    if not result["ok"]:
        assert "Each active scenario requires" in result["error"]
        assert "S2" in result["error"]


@pytest.mark.parametrize("scope", ["module", "class", "function"])
@pytest.mark.parametrize("bindings,enabled", [
    pytest.param("{target} = False\n{target} = True\n", True, id="false-true"),
    pytest.param("{target} = True\n{target} = False\n", False, id="true-false"),
    pytest.param("{target} = False\n{target}: bool = True\n", True, id="annotated-true"),
    pytest.param("{target} = True\n{target}: bool = False\n", False, id="annotated-false"),
    pytest.param("{target} = False\n{target}: bool\n", False, id="annotation-after-false"),
    pytest.param("{target} = True\n{target}: bool\n", True, id="annotation-after-true"),
])
def test_final_test_flag_binding_matches_collection(scenario_project, scope, bindings, enabled):
    """Final literal booleans control collection; an annotation without a value does not bind."""
    source = '@pytest.mark.scenario("S1")\n@pytest.mark.scenario("S2")\n'
    arguments = "self" if scope == "class" else ""
    source += f'def test_real({arguments}):\n    pytest.fail("pending")\n'
    target = "test_real.__test__" if scope == "function" else "__test__"
    source += bindings.format(target=target)
    if scope == "class":
        source = "class TestQueue:\n" + indent(source, "    ")
    path = write_test(scenario_project, source)
    entries = collect_synthetic_entries(scenario_project, path)
    assert bool(entries) is enabled, entries
    if enabled:
        assert entries[0]["scenarios"] == ["S1", "S2"], entries
    result = audit_project(scenario_project, "Block", phase="templates")
    assert result["ok"] is enabled, result
    # Named-function filtering remains local to scenario membership; the existing
    # failure-only detector still examines its body. Namespace flags are shared.
    identity = "TestQueue::test_real" if scope == "class" else "test_real"
    expected_empty = {identity} if enabled or scope == "function" else set()
    assert set(failure_only_tests(path, project=path.parents[3])) == expected_empty


@pytest.mark.parametrize("scope", ["module", "class", "function"])
def test_unknown_final_test_flag_does_not_claim_membership(scenario_project, scope):
    """A runtime expression is not evaluated or guessed even when its synthetic value is True."""
    source = '@pytest.mark.scenario("S1", "S2")\n'
    arguments = "self" if scope == "class" else ""
    source += f'def test_real({arguments}):\n    pytest.fail("pending")\n'
    target = "test_real.__test__" if scope == "function" else "__test__"
    source += f'{target} = True\nflag = True\n{target} = flag\n'
    if scope == "class":
        source = "class TestQueue:\n" + indent(source, "    ")
    path = write_test(scenario_project, source)
    assert len(collect_synthetic_entries(scenario_project, path)) == 1
    result = audit_project(scenario_project, "Block", phase="templates")
    assert not result["ok"], result
    assert "Each active scenario requires" in result["error"]
    identity = "TestQueue::test_real" if scope == "class" else "test_real"
    assert set(failure_only_tests(path, project=path.parents[3])) == {identity}
