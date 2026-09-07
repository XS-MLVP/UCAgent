"""Security regressions for inspecting generated workspace Python code."""

import os
import sys
from types import SimpleNamespace

from ucagent.checkers.unity_test import (
    UnityChipCheckerBundleWrapper,
    UnityChipCheckerCoverageGroup,
    UnityChipCheckerDutApi,
    UnityChipCheckerDutApiTest,
    UnityChipCheckerDutCreation,
    UnityChipCheckerDutFixture,
    UnityChipCheckerMockComponent,
)


def test_static_checkers_do_not_execute_workspace_modules(tmp_path, monkeypatch):
    """AST-only Checkers must not run top-level workspace code in the agent."""

    pollution_key = "UCAGENT_STATIC_CHECKER_POLLUTION"
    monkeypatch.delenv(pollution_key, raising=False)
    target = tmp_path / "workspace_contract.py"
    target.write_text(
        "import os\n"
        f"os.environ[{pollution_key!r}] = 'polluted'\n"
        "raise RuntimeError('workspace module executed in agent process')\n\n"
        "class Bundle:\n"
        "    pass\n\n"
        "class DemoBundle(Bundle):\n"
        "    pass\n\n"
        "class MockBus:\n"
        "    def on_clock_edge(self, cycles):\n"
        "        return cycles\n\n"
        "def create_dut(request):\n"
        "    get_coverage_data_path(request, new_path=True)\n"
        "    if ucagent.is_imp_test_template():\n"
        "        return ucagent.get_fake_dut(DUTDemo)\n"
        "    return DUTDemo()\n\n"
        "@pytest.fixture(scope='function')\n"
        "def dut(request):\n"
        "    get_coverage_data_path(request, new_path=False)\n"
        "    groups = []\n"
        "    yield object()\n"
        "    set_func_coverage(request, groups)\n\n"
        "def api_Demo_operate(env, value, max_cycles=10):\n"
        "    \"\"\"Run one operation.\n\n"
        "    Args:\n"
        "        env: Verification environment.\n"
        "        value: Input value.\n"
        "        max_cycles: Timeout.\n\n"
        "    Returns:\n"
        "        The result.\n"
        "    \"\"\"\n"
        "    return value\n",
        encoding="utf-8",
    )
    cfg = {"_temp_cfg": {"DUT": "Demo"}}
    checkers = [
        UnityChipCheckerDutCreation(target.name, cfg=cfg),
        UnityChipCheckerDutFixture(target.name, cfg=cfg),
        UnityChipCheckerDutApi("api_Demo_", target.name),
        UnityChipCheckerMockComponent(target.name),
        UnityChipCheckerBundleWrapper(target.name),
    ]

    results = [
        checker.set_workspace(str(tmp_path)).do_check()
        for checker in checkers
    ]

    assert all(passed for passed, _message in results), results
    assert pollution_key not in os.environ
    assert target.stem not in sys.modules


def test_coverage_factory_runs_only_in_isolated_process(tmp_path, monkeypatch):
    """Coverage materialization must not leak imports or side effects to the agent."""

    pollution_key = "UCAGENT_COVERAGE_CHECKER_POLLUTION"
    monkeypatch.delenv(pollution_key, raising=False)
    coverage_file = tmp_path / "workspace_coverage_probe.py"
    coverage_file.write_text(
        "import os\n"
        f"os.environ[{pollution_key!r}] = 'child-only'\n"
        "from toffee.funcov import CovGroup\n\n"
        "def get_coverage_groups(dut):\n"
        "    group = CovGroup('FG-API')\n"
        "    group.add_watch_point(\n"
        "        dut,\n"
        "        {'CK-BASIC': lambda target: True},\n"
        "        name='FC-OPERATE',\n"
        "    )\n"
        "    return [group]\n",
        encoding="utf-8",
    )
    doc_file = tmp_path / "functions_and_checks.md"
    doc_file.write_text(
        "\n# Functions and checks\n\n"
        "### API <FG-API>\n\n"
        "#### Operate <FC-OPERATE>\n\n"
        "##### Basic <CK-BASIC>\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerCoverageGroup(
        ".",
        coverage_file.name,
        doc_file.name,
        ["FG", "FC", "CK"],
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is True, message
    assert pollution_key not in os.environ
    assert coverage_file.stem not in sys.modules
    assert "_ucagent_coverage_probe_target" not in sys.modules


def test_coverage_probe_inherits_active_source_import_roots(tmp_path, monkeypatch):
    """Isolated coverage probes must resolve source plugins and the running UCAgent."""

    pollution_key = "UCAGENT_SOURCE_PLUGIN_PROBE_POLLUTION"
    monkeypatch.delenv(pollution_key, raising=False)
    source_root = tmp_path / "plugin-src"
    plugin_package = source_root / "probe_plugin"
    plugin_package.mkdir(parents=True)
    (plugin_package / "__init__.py").write_text(
        "import os\n"
        "from ucagent.util.config import load_runtime_config\n"
        f"os.environ[{pollution_key!r}] = 'child-only'\n"
        "PROBE_VALUE = bool(load_runtime_config)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(source_root))
    coverage_file = tmp_path / "source_plugin_coverage.py"
    coverage_file.write_text(
        "from probe_plugin import PROBE_VALUE\n"
        "from toffee.funcov import CovGroup\n\n"
        "def get_coverage_groups(dut):\n"
        "    assert PROBE_VALUE\n"
        "    group = CovGroup('FG-API')\n"
        "    group.add_watch_point(\n"
        "        dut,\n"
        "        {'CK-BASIC': lambda target: True},\n"
        "        name='FC-OPERATE',\n"
        "    )\n"
        "    return [group]\n",
        encoding="utf-8",
    )
    doc_file = tmp_path / "functions_and_checks.md"
    doc_file.write_text(
        "\n# Functions and checks\n\n"
        "### API <FG-API>\n\n"
        "#### Operate <FC-OPERATE>\n\n"
        "##### Basic <CK-BASIC>\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerCoverageGroup(
        ".",
        coverage_file.name,
        doc_file.name,
        ["FG", "FC", "CK"],
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is True, message
    assert pollution_key not in os.environ
    assert "probe_plugin" not in sys.modules
    assert coverage_file.stem not in sys.modules
    assert "_ucagent_coverage_probe_target" not in sys.modules


def test_coverage_probe_failure_is_isolated_and_bounded(tmp_path, monkeypatch):
    """An executing coverage module must return a bounded child-process failure."""

    pollution_key = "UCAGENT_FAILED_COVERAGE_POLLUTION"
    monkeypatch.delenv(pollution_key, raising=False)
    coverage_file = tmp_path / "broken_coverage_probe.py"
    coverage_file.write_text(
        "import os\n"
        f"os.environ[{pollution_key!r}] = 'child-only'\n"
        "raise RuntimeError('x' * 5000)\n\n"
        "def get_coverage_groups(dut):\n"
        "    return []\n",
        encoding="utf-8",
    )
    doc_file = tmp_path / "functions_and_checks.md"
    doc_file.write_text("\n# Functions and checks\n", encoding="utf-8")
    checker = UnityChipCheckerCoverageGroup(
        ".",
        coverage_file.name,
        doc_file.name,
        "FG",
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is False
    assert "isolated coverage definition probe failed" in message["error"]
    assert "RuntimeError" in message["error"]
    assert len(message["error"]) < 2500
    assert pollution_key not in os.environ
    assert coverage_file.stem not in sys.modules


def test_api_test_checker_does_not_import_api_after_isolated_run(
    tmp_path, monkeypatch
):
    """API coverage matching after pytest must inspect source without importing it."""

    pollution_key = "UCAGENT_API_TEST_CHECKER_POLLUTION"
    monkeypatch.delenv(pollution_key, raising=False)
    api_file = tmp_path / "workspace_api.py"
    api_file.write_text(
        "import os\n"
        f"os.environ[{pollution_key!r}] = 'polluted'\n"
        "raise RuntimeError('API module imported in agent process')\n\n"
        "def api_Demo_operate(env, max_cycles=10):\n"
        "    return None\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_Demo_api.py"
    test_file.write_text(
        "def test_api_Demo_operate(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    functions_file = tmp_path / "functions_and_checks.md"
    functions_file.write_text(
        "\n# Functions and checks\n\n"
        "### API <FG-API>\n\n"
        "#### Operate <FC-OPERATE>\n\n"
        "##### Basic <CK-BASIC>\n",
        encoding="utf-8",
    )
    bug_file = tmp_path / "bug_analysis.md"
    bug_file.write_text(
        "\n# Dynamic Bug analysis\n\n"
        "## Dynamic Bug records\n\n"
        "<DYNAMIC-BUGS>\n"
        "</DYNAMIC-BUGS>\n\n"
        "## Root cause analysis\n\n"
        "<ROOT-CAUSES>\n"
        "</ROOT-CAUSES>\n\n"
        "## Waveform evidence\n\n"
        "<WAVEFORM-EVIDENCE>\n"
        "</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )
    test_node = "test_Demo_api.py:1-2::test_api_Demo_operate"
    report = {
        "run_test_success": True,
        "total_funct_point": 1,
        "total_check_point": 1,
        "test_function_with_no_check_point_mark": 0,
        "test_function_with_no_check_point_mark_list": [],
        "all_check_point_list": ["FG-API/FC-OPERATE/CK-BASIC"],
        "failed_check_point_list": [],
        "failed_test_case_with_check_point_list": {},
        "test_case_with_check_point_list": {
            test_node: ["FG-API/FC-OPERATE/CK-BASIC"]
        },
        "unmarked_check_points": 0,
        "unmarked_check_point_list": [],
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {test_node: "PASSED"},
        },
    }
    checker = UnityChipCheckerDutApiTest(
        "api_Demo_",
        api_file.name,
        test_file.name,
        functions_file.name,
        bug_file.name,
    ).set_workspace(str(tmp_path))
    checker.run_test = SimpleNamespace(
        set_report_context=lambda _context: None,
        do=lambda *_args, **_kwargs: (report, "", ""),
    )

    passed, message = checker.do_check()

    assert passed is True, message
    assert pollution_key not in os.environ
    assert api_file.stem not in sys.modules
