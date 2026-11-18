"""Verify native input preparation offline, including tampering and new-suite boundaries."""

import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ucagent_act4 import generation_inputs
from ucagent_act4.checkers.act4_generation_inputs_checker import ACT4GenerationInputsChecker


def commit(root: Path) -> None:
    """Commit a tiny fixture without relying on the developer's Git identity."""
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.org",
                    "commit", "-qm", "fixture"], check=True)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    """Supply pinned native repositories and an authenticated-publication test double."""
    act = tmp_path / "riscv-arch-test"
    manual = tmp_path / "manual"
    for root in (act, manual):
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    (act / "testplans/priv").mkdir(parents=True)
    (act / "testplans/priv/testplan.schema.json").write_text(json.dumps({"type": "object"}))
    (act / "testplans/priv/Sstc.yaml").write_text("suite: Sstc\ncoverpoints: [{name: cp_one}]\n")
    (act / "testplans/I.csv").write_text("Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\n")
    (manual / "src/priv").mkdir(parents=True)
    (manual / "src/priv/sstc.adoc").write_text("[#norm:timer_rule]#Architectural timer behavior.#\n")
    commit(act)
    commit(manual)
    payload = {"normative_rules": [{"name": "timer_rule", "text": "Architectural timer behavior."}]}

    def published(url, timeout):
        """Return only the fixed official endpoint with bounded data and no network."""
        assert url == generation_inputs.RULES_URL and timeout == 60
        stream = io.BytesIO(json.dumps(payload).encode())
        stream.geturl = lambda: url
        return stream

    monkeypatch.setattr(generation_inputs, "urlopen", published)
    state = {}
    manager = SimpleNamespace(get_data=state.get, set_data=state.__setitem__)

    def checker(kind="privileged", suite="Sstc"):
        """Bind each test to the same persisted preparation registry."""
        return ACT4GenerationInputsChecker(suite, kind, "out/inputs", "manual").set_workspace(str(tmp_path)).set_stage_manager(manager)

    return checker, payload, act, manual


@pytest.mark.parametrize("kind,suite", [("privileged", "Sstc"), ("unprivileged", "I"), ("privileged", "NewSuite")])
def test_native_inputs_do_not_require_ctp_or_sheet(inputs, tmp_path, kind, suite):
    """Both formats and a new suite freeze valid rules without an HTML/Sheet dependency."""
    factory, _, _, _ = inputs
    checker = factory(kind, suite)
    passed, report = checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert passed, report
    assert report["new_suite"] == (suite == "NewSuite")
    assert checker.do_check(is_complete=True)[0]
    receipt = json.loads((tmp_path / "out/inputs/receipt.json").read_text())
    if suite != "NewSuite":
        assert receipt["source_plan"] in {"source-plan.yaml", "source-plan.csv"}
    assert generation_inputs.load_rules(tmp_path / "out/inputs/norm-rules.json")["timer_rule"]["text"]


@pytest.mark.parametrize("mutation", ["receipt", "rules", "manual", "snapshot"])
def test_generation_input_tampering_fails(inputs, tmp_path, mutation):
    """Editable output cannot replace original evidence after successful preparation."""
    factory, _, _, manual = inputs
    checker = factory()
    assert checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]
    path = {"receipt": tmp_path / "out/inputs/receipt.json", "rules": tmp_path / "out/inputs/norm-rules.json",
            "manual": manual / "src/priv/sstc.adoc", "snapshot": tmp_path / "out/inputs/source-plan.yaml"}[mutation]
    path.write_text(path.read_text() + "\n")
    passed, report = checker.do_check(is_complete=True)
    assert not passed and report["error_code"] == "act4_generation_inputs"


@pytest.mark.parametrize("payload", [{}, {"normative_rules": []}, {"normative_rules": [{"name": "rule"}]},
                                     {"normative_rules": [{"name": "rule", "text": "text"}] * 2}])
def test_malformed_native_rule_index_is_rejected(inputs, payload):
    """An empty, malformed, or duplicate rule index must not create completion evidence."""
    factory, published, _, _ = inputs
    published.clear()
    published.update(payload)
    passed, report = factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert not passed and report["error_code"] == "act4_generation_inputs"


@pytest.mark.parametrize("files", [[], ["../manual/src/priv/sstc.adoc"], ["src/priv/sstc.adoc"] * 2])
def test_invalid_source_selection_is_rejected(inputs, files):
    """Selection must be explicit, unique, and confined to source ADOC files."""
    factory, _, _, _ = inputs
    assert not factory().do_check(action="prepare", manual_files=files)[0]


def test_mutated_or_untracked_manual_is_not_an_authority(inputs):
    """Only bytes from the pinned manual commit can become specification evidence."""
    factory, _, _, manual = inputs
    (manual / "src/priv/sstc.adoc").write_text("[#norm:timer_rule]#Invented behavior.#")
    assert not factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]


def test_inputs_need_preparation_and_cannot_be_refrozen(inputs):
    """Neither fabricated files nor repeated prepare can silently replace the run's scope."""
    factory, _, _, _ = inputs
    checker = factory()
    assert not checker.do_check(is_complete=True)[0]
    assert checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]
    assert not checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]


@pytest.mark.parametrize("selected", [False, True])
def test_official_non_text_rules_preserve_source_evidence(inputs, tmp_path, selected):
    """Native encoding figures may have empty published text, but never fabricated prose."""
    factory, published, _, _ = inputs
    if selected:
        published["normative_rules"][0]["text"] = ""
    else:
        published["normative_rules"].append({"name": "unrelated_encoding", "text": ""})
    passed, report = factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert passed, report
    receipt = json.loads((tmp_path / "out/inputs/receipt.json").read_text())
    assert receipt["non_text_rules"] == (["timer_rule"] if selected else [])
    assert receipt["rule_locations"]["timer_rule"] == [{"file": "manual/src/priv/sstc.adoc", "line": 1}]
    assert len(report["limitations"]) == (2 if selected else 1)
