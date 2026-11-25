"""Real Toffee/pytest adapter runs on pure Python; no demonstration RTL is built."""

import json
from pathlib import Path

import pytest

from toffee_ut.audit import delivery_data
from toffee_ut.runner import current_run, run_tests, runtime_info, validate_run


@pytest.mark.parametrize("workers", [1, 2])
def test_real_runner_retains_all_canonical_outcomes(project, workers):
    """Parametrized identities and full-phase classification survive serial and xdist transport."""
    code = '''"""Pure pytest outcome adapter contract."""
import pytest

@pytest.mark.scenario("S1")
@pytest.mark.parametrize("value", [0, 1], ids=["zero", "one::exact"])
def test_pass(value):
    assert value in (0, 1)

@pytest.mark.uncertain(reason="Unit contract evidence pending", reference="R1")
def test_uncertain():
    assert True

@pytest.mark.uncertain(reason="Cannot hide a real failure")
def test_fail():
    assert 3 == 4

@pytest.mark.xfail(reason="Unit test expects failure")
def test_xfail():
    assert False

@pytest.mark.xfail(reason="Unit test expects strict xpass", strict=True)
def test_xpass():
    assert True

@pytest.mark.skip(reason="Adapter skip path")
def test_skip():
    pass

@pytest.fixture
def bad_cleanup():
    yield
    raise RuntimeError("independent cleanup error")

@pytest.mark.uncertain(reason="Cannot hide a cleanup error")
def test_error(bad_cleanup):
    assert True
'''
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text(code)
    result = run_tests(project, "Block", workers=workers, seed=37)
    assert result["ok"], result
    assert result["tests"] == {"PASS": 2, "UNCERTAIN": 1, "FAIL": 1, "XFAIL": 1, "XPASS": 1, "SKIP": 1, "ERROR": 1}
    checked = current_run(project, "ut_project")
    assert checked["record"]["returncode"] == 1
    assert checked["record"]["seed"] == 37 and checked["cases"]["requested_seed"] == 37
    assert any("[one::exact]" in node for node in checked["cases"]["cases"])
    error = next(row for node, row in checked["cases"]["cases"].items() if "test_error" in node)
    assert error["status"] == "ERROR" and error["phases"]["call"]["uncertain"]


def test_exit_zero_uncertain_is_not_a_pass_or_a_native_dut_run(project):
    """No native registration means no hardware credit, even with exit code zero."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('import pytest\n@pytest.mark.scenario("S1")\n@pytest.mark.uncertain(reason="Unconfirmed oracle")\n'
                    'def test_uncertain():\n    assert True\n')
    result = run_tests(project, "Block")
    assert result["ok"] and result["tests"] == {"UNCERTAIN": 1}
    assert current_run(project, "ut_project")["record"]["returncode"] == 0
    summary = delivery_data(project, "Block", "ut_project")
    assert summary["status"] == "INCOMPLETE"
    assert set(summary["problems"]) == {"missing_per_case_native_registration", "missing_native_build_evidence",
                                        "static_review_missing", "native_line_coverage_not_collected", "native_line_coverage_review_missing",
                                        "non_verifying_tests"}


def test_partial_selection_and_source_edits_cannot_reuse_full_green(project):
    """Each new launch has its own selection and any subsequent source edit invalidates it."""
    first = run_tests(project, "Block")
    assert first["ok"] and first["full_selection"]
    second = run_tests(project, "Block", keyword="value")
    assert second["ok"] and not second["full_selection"] and second["run"] != first["run"]
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text(test.read_text() + "\n# changed after execution\n")
    with pytest.raises(ValueError, match="stale"):
        current_run(project, "ut_project")


@pytest.mark.parametrize("failure", ["no_tests", "collection", "runtime"])
def test_failed_launch_invalidates_old_current_pointer(project, monkeypatch, failure):
    """An empty selection, collection error or unavailable runtime never falls back to old evidence."""
    assert run_tests(project, "Block")["ok"]
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    if failure == "no_tests":
        result = run_tests(project, "Block", keyword="does_not_exist")
        assert not result["ok"]
    elif failure == "collection":
        test.write_text("invalid syntax !!\n")
        result = run_tests(project, "Block")
        assert not result["ok"]
    else:
        def unavailable():
            """Fail before any test process starts."""
            raise ValueError("runtime unavailable")
        monkeypatch.setattr("toffee_ut.runner.runtime_info", unavailable)
        with pytest.raises(ValueError):
            run_tests(project, "Block")
    assert not (project / "ut_project/results/latest.json").exists()


def test_raw_artifact_and_receipt_changes_are_rejected(project):
    """A copied signature or a hand-edited case report is not current execution evidence."""
    result = run_tests(project, "Block")
    assert result["ok"], result
    checked = current_run(project, "ut_project")
    receipt = checked["record"]
    with pytest.raises(ValueError, match="receipt"):
        validate_run(project, "ut_project", {**receipt, "seed": 999})
    path = project / "ut_project" / result["run"] / "cases.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="artifact"):
        current_run(project, "ut_project")


def test_hidden_pytest_options_do_not_narrow_or_replace_the_run(project, monkeypatch):
    """The tool owns selectors and plugin loading rather than inheriting hidden addopts."""
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTEST_PLUGINS", "nonexistent_plugin")
    ini = project / "ut_project/pytest.ini"
    ini.write_text(ini.read_text() + "\naddopts = -k never_matches\n")
    result = run_tests(project, "Block")
    assert result["ok"] and result["tests"] == {"PASS": 1}


@pytest.mark.parametrize("selector", ["--collect-only", "../outside.py", "/abs.py", "conftest.py", "testbenches/missing.py"])
def test_run_selector_cannot_be_a_command_or_escape(project, selector):
    """Only real test files below testbenches may become command arguments."""
    with pytest.raises(ValueError):
        run_tests(project, "Block", targets=[selector])


def test_selftests_do_not_pollute_functional_coverage(project):
    """selftest and shared tests keep exact verdicts but contribute no hardware bins."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('''import pytest
from toffee import Bin, CoverGroupDef, CoverPointDef
@pytest.mark.selftest
def test_helper():
    group = CoverGroupDef("helper", (CoverPointDef("x", {"one": Bin.values(1)}),)).instantiate("helper")
    group.sample({"x": 1})
    assert group.covered
''')
    result = run_tests(project, "Block")
    assert result["ok"], result
    checked = current_run(project, "ut_project")
    assert all(row["selftest"] for row in checked["cases"]["cases"].values())
    assert checked["manifest"]["functional_groups"] == 0


def test_runtime_rejects_legacy_metadata(monkeypatch):
    """The single venv cannot silently mix two distributions that own the toffee import."""
    from importlib import metadata
    real_version = metadata.version
    monkeypatch.setattr(metadata, "version", lambda name: "1.0" if name == "pytoffee" else real_version(name))
    with pytest.raises(ValueError, match="conflicting"):
        runtime_info()


def test_independent_source_outside_project_is_fingerprinted(project):
    """Changing an independent oracle document invalidates a run even without a prior inventory."""
    assert run_tests(project, "Block")["ok"]
    (project / "inputs/interface.md").write_text("The independent contract changed.\n")
    with pytest.raises(ValueError, match="stale"):
        current_run(project, "ut_project")


def test_sources_modified_during_execution_cannot_commit_current_evidence(project):
    """A test cannot edit its own source and leave that run selected for completion."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('from pathlib import Path\ndef test_changes():\n    p = Path(__file__)\n'
                    '    p.write_text(p.read_text() + "\\n# changed during execution\\n")\n    assert True\n')
    result = run_tests(project, "Block")
    assert not result["ok"] and "Sources changed during" in result["error"]
    assert not (project / "ut_project/results/latest.json").exists()


@pytest.mark.parametrize("workers", [1, 2])
def test_plugin_deselection_is_visible_even_without_explicit_filters(project, workers):
    """Worker-side deselection must not masquerade as a complete declared selection."""
    root = project / "ut_project"
    (root / "testbenches/block/tests/test_extra.py").write_text('def test_extra():\n    assert True\n')
    (root / "conftest.py").write_text('''def pytest_collection_modifyitems(config, items):
    removed = [item for item in items if "test_extra" in item.nodeid]
    items[:] = [item for item in items if item not in removed]
    config.hook.pytest_deselected(items=removed)
''')
    result = run_tests(project, "Block", workers=workers)
    assert result["ok"] and not result["full_selection"], result
    assert len(current_run(project, "ut_project")["cases"]["deselected"]) == 1


def test_run_honors_a_mapped_testbench_in_existing_metadata(project):
    """Default selection uses workspace.json, not dut.lower() directory guesses."""
    from toffee_ut.paths import write_json
    root = project / "ut_project"
    data = json.loads((root / "workspace.json").read_text())
    row = data["duts"]["Block"]
    row.update(testbench="aliased", environment="testbenches/aliased/env.py", tests=["testbenches/aliased/tests"])
    (root / "testbenches/block").rename(root / "testbenches/aliased")
    write_json(root / "workspace.json", data)
    result = run_tests(project, "Block")
    assert result["ok"] and result["full_selection"], result
    assert all(node.startswith("testbenches/aliased/") for node in current_run(project, "ut_project")["cases"]["cases"])


def test_run_timeout_keeps_logs_but_no_current_receipt(project):
    """A bounded real pytest run that times out retains diagnostics and cannot reuse prior success."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('import time\ndef test_slow():\n    time.sleep(10)\n')
    result = run_tests(project, "Block", timeout=1)
    assert not result["ok"] and result["error_code"] == "TIMEOUT"
    assert (project / "ut_project" / result["run"] / "stdout.log").exists()
    assert not (project / "ut_project/results/latest.json").exists()
