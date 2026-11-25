"""Record exact pytest identities and outcomes without changing test verdicts."""

from collections import Counter
import hashlib
from pathlib import Path
import sys
import weakref

import pytest
from toffee.outcomes import case_status, phase_record

from .paths import write_json


def pytest_addoption(parser):
    """Register the automation-owned destination for per-case evidence."""
    parser.addoption("--toffee-ut-cases", default=None, help="ToffeeUT per-case evidence path")
    parser.addoption("--toffee-ut-seed", type=int, default=1, help="Seed supplied to the project's native DUT fixture")
    parser.addoption("--toffee-ut-waveforms", action="store_true", help="Capture fixture-owned native DUT waveforms without advancing simulation")


def pytest_configure(config):
    """Register markers and one controller/worker evidence adapter."""
    config.addinivalue_line("markers", "scenario(*ids): verification specification scenario identifiers")
    config.addinivalue_line("markers", "selftest: verification infrastructure, not DUT functional evidence")
    for role in ("api", "envcheck", "modelcheck", "mockcheck", "random"):
        config.addinivalue_line("markers", f"{role}: ToffeeUT stage-specific test role")
    if config.getoption("toffee_ut_cases"):
        config.pluginmanager.register(CaseEvidence(config), "toffee-ut-case-evidence")


class CaseEvidence:
    """Aggregate all phases on the controller, including xdist worker reports."""

    def __init__(self, config):
        """Retain run-local state, never a session-global singleton."""
        self.config = config
        self.worker = hasattr(config, "workerinput")
        self.distributed = self.worker or bool(getattr(config.option, "numprocesses", 0))
        self.collection = None
        self.cases = {}
        self.errors = []
        self.deselected = []
        self.active_item = None
        self.waveforms = {}

    def observe_native(self, item, value, depth=0, seen=None):
        """Associate fixture-owned native resources, without taking simulation ownership."""
        seen = set() if seen is None else seen
        if depth > 3 or id(value) in seen:
            return
        seen.add(id(value))
        if all(callable(getattr(type(value), method, None)) for method in
               ("SetCoverage", "GetCovMetrics", "GetXClock", "Finish")):
            module = sys.modules.get(type(value).__module__)
            source = getattr(module, "__file__", None)
            if source:
                identity = {"class": type(value).__name__, "source": str(Path(source).resolve())}
                pair = ("toffee_ut_native_dut", identity)
                if pair not in item.user_properties:
                    item.user_properties.append(pair)
                if self.config.getoption("toffee_ut_waveforms") and item.get_closest_marker("selftest") is None:
                    previous = self.waveforms.get(id(value))
                    if previous is None or previous[0]() is not value:
                        setter = getattr(value, "SetWaveform", None)
                        error_message = None
                        path = None
                        if not callable(setter):
                            error_message = "Native DUT has no SetWaveform; provide a trace-enabled build"
                        else:
                            root = Path(self.config.getoption("toffee_ut_cases")).parent.resolve()
                            worker = getattr(self.config, "workerinput", {}).get("workerid", "main")
                            token = hashlib.sha256(item.nodeid.encode()).hexdigest()[:16]
                            path = root / "waveforms" / worker / token / f"dut-{len(self.waveforms)}.fst"
                            path.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                setter(str(path))
                            except Exception as error:
                                path = None
                                error_message = f"Waveform capture failed: {error}"
                        previous = (weakref.ref(value), path, error_message)
                        self.waveforms[id(value)] = previous
                    if previous[2]:
                        prop = ("toffee_ut_waveform_error", previous[2])
                        if prop not in item.user_properties:
                            item.user_properties.append(prop)
                    elif previous[1] is not None:
                        row = {"path": previous[1].relative_to(Path(self.config.rootpath).resolve()).as_posix(), "native_dut": identity}
                        prop = ("toffee_ut_waveform", row)
                        if prop not in item.user_properties:
                            item.user_properties.append(prop)
            return
        if isinstance(value, dict):
            children = value.values()
        elif isinstance(value, (list, tuple)):
            children = value
        else:
            children = [child for key, child in getattr(value, "__dict__", {}).items()
                        if key in {"dut", "_dut", "_instances"}]
        for child in children:
            self.observe_native(item, child, depth + 1, seen)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item):
        """Keep explicit factory registration attached to the currently executing case."""
        self.active_item = item
        try:
            yield
        finally:
            self.active_item = None

    def pytest_deselected(self, items):
        """Preserve hidden or plugin-driven selection reductions in the receipt."""
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collection_modifyitems(self, items):
        """Keep shared/self-check coverage out of hardware functional credit."""
        for item in items:
            path = Path(item.nodeid.split("::", 1)[0])
            shared = path.is_relative_to("testbenches/shared/tests")
            if shared and item.get_closest_marker("selftest") is None:
                item.add_marker(pytest.mark.selftest)
            if item.get_closest_marker("selftest") is not None:
                item.add_marker(pytest.mark.toffee_functional_coverage(False), append=False)

    def pytest_runtest_call(self, item):
        """Inspect actual fixture resources for existing suites that register automatically."""
        for value in item.funcargs.values():
            self.observe_native(item, value)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        """Observe factory-created DUTs before owning fixtures release their instances."""
        for value in item.funcargs.values():
            self.observe_native(item, value)
        yield

    def pytest_collection_finish(self, session):
        """Record actual selected nodes after deselection in serial execution."""
        if not self.distributed:
            self.collection = [item.nodeid for item in session.items]

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids):
        """Require the same ordered collection on every worker."""
        if self.collection is None:
            self.collection = list(ids)
        elif self.collection != list(ids):
            self.errors.append(f"Worker collection differs: {node.gateway.id}")

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        """Transport worker-side deselection rather than inferring a full selection from executed nodes."""
        metadata = getattr(node, "workeroutput", {}).get("toffee_ut_selection")
        if error or metadata is None:
            self.errors.append(f"Worker did not provide selection evidence: {node.gateway.id}")
        else:
            self.deselected = sorted(set(self.deselected) | set(metadata["deselected"]))

    def pytest_collectreport(self, report):
        """Keep collection errors separate from unexecuted tests."""
        if report.failed:
            self.errors.append(f"Collection failed: {report.nodeid}")

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        """Observe explicit real-DUT registration without replacing the collector."""
        outcome = yield
        if outcome.excinfo is None and self.active_item is not None:
            self.observe_native(self.active_item, outcome.get_result())
        if fixturedef.argname == "toffee_register_dut" and outcome.excinfo is None:
            original = outcome.get_result()

            def register(dut):
                """Delegate native collection and retain the actual owning test."""
                result = original(dut)
                if self.active_item is not None:
                    self.observe_native(self.active_item, dut)
                return result

            outcome.force_result(register)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        """Serialize scenario membership and evidence class for xdist transport."""
        outcome = yield
        report = outcome.get_result()
        scenario_ids = []
        for marker in item.iter_markers("scenario"):
            if marker.kwargs or not marker.args or any(not isinstance(value, str) or not value for value in marker.args):
                raise pytest.UsageError("scenario requires one or more nonempty string IDs")
            scenario_ids.extend(marker.args)
        report.user_properties.append(("toffee_ut_scenarios", sorted(set(scenario_ids))))
        report.user_properties.append(("toffee_ut_selftest", item.get_closest_marker("selftest") is not None))
        report.user_properties.append(("toffee_ut_roles",
            sorted(role for role in ("api", "envcheck", "modelcheck", "mockcheck", "random")
                   if item.get_closest_marker(role) is not None)))

    def pytest_runtest_logreport(self, report):
        """Retain bounded diagnostics and the framework's canonical phase records."""
        if self.worker:
            return
        row = self.cases.setdefault(report.nodeid, {"phases": {}, "scenarios": [], "selftest": False,
                                                   "roles": [], "native_duts": [], "declared_native_seed": None,
                                                   "waveforms": [], "waveform_errors": []})
        if report.when in row["phases"]:
            self.errors.append(f"Duplicate phase: {report.nodeid}:{report.when}")
        phase = phase_record(report)
        capture = {"unit": "unicode_characters", "retention": "head",
                   "limits": {"section_chars": 6000, "phase_chars": 12000, "sections": 12},
                   "sections": [], "omitted_sections": 0, "omitted_chars": 0}
        remaining = capture["limits"]["phase_chars"]
        names = {f"Captured {stream} {report.when}" for stream in ("stdout", "stderr", "log")}
        # Pytest reports accumulate earlier phases; the aggregate capstdout/log
        # properties would duplicate their text and misattribute it to this phase.
        for name, text in report.sections:
            if not isinstance(name, str) or name not in names or not isinstance(text, str):
                continue
            if len(capture["sections"]) >= capture["limits"]["sections"] or remaining == 0:
                capture["omitted_sections"] += 1
                capture["omitted_chars"] += len(text)
                continue
            retained = text[:min(capture["limits"]["section_chars"], remaining)]
            capture["sections"].append({"name": name, "text": retained, "original_chars": len(text),
                                        "retained_chars": len(retained), "truncated": len(retained) < len(text)})
            remaining -= len(retained)
        if capture["sections"] or capture["omitted_sections"]:
            phase["captured_diagnostics"] = capture
        if report.failed:
            phase["failure"] = str(report.longrepr)[-6000:]
        row["phases"][report.when] = phase
        for key, value in report.user_properties:
            if key == "toffee_ut_scenarios":
                row["scenarios"] = value
            elif key == "toffee_ut_selftest":
                row["selftest"] = value
            elif key == "toffee_ut_roles":
                row["roles"] = value
            elif key == "toffee_ut_native_dut" and value not in row["native_duts"]:
                row["native_duts"].append(value)
            elif key == "toffee_ut_seed":
                row["declared_native_seed"] = value
            elif key == "toffee_ut_waveform" and value not in row["waveforms"]:
                row["waveforms"].append(value)
            elif key == "toffee_ut_waveform_error" and value not in row["waveform_errors"]:
                row["waveform_errors"].append(value)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        """Persist evidence even on failure; a missing phase remains INCOMPLETE."""
        if self.worker:
            self.config.workeroutput["toffee_ut_selection"] = {"deselected": self.deselected}
            return
        for row in self.cases.values():
            row["status"] = case_status(row["phases"])
            retained = []
            for wave in row["waveforms"]:
                path = Path(self.config.rootpath) / wave["path"]
                if path.is_file() and path.stat().st_size:
                    retained.append(wave)
                else:
                    row["waveform_errors"].append("Native DUT produced no waveform; check trace build and registration before simulation")
            row["waveforms"] = retained
        collection = self.collection or []
        if len(collection) != len(set(collection)):
            self.errors.append("Duplicate node IDs in collection")
        if not self.config.option.collectonly and set(collection) != set(self.cases):
            self.errors.append("Executed nodes differ from collection")
        write_json(Path(self.config.getoption("toffee_ut_cases")), {
            "schema_version": 1, "rootdir": str(self.config.rootpath),
            "collection": collection, "cases": self.cases,
            "counts": dict(Counter(row["status"] for row in self.cases.values())),
            "errors": self.errors, "exitstatus": int(session.exitstatus),
            "collect_only": self.config.option.collectonly, "deselected": self.deselected,
            "requested_seed": self.config.getoption("toffee_ut_seed"),
        })
