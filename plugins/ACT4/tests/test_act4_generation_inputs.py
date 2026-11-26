"""Verify native input preparation offline, including tampering and new-suite boundaries."""

import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ucagent.stage.vmanager import StageManager
from ucagent.stage.vstage import VerifyStage
from ucagent.util.config import Config
from ucagent_act4 import generation_inputs
from ucagent_act4.checkers.act4_generation_inputs_checker import ACT4GenerationInputsChecker
from ucagent_act4.checkers.act4_native_assets_checker import ACT4NativeAssetsChecker


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
        assert receipt["source_plans"] and all(name.startswith("plans/testplans/") for name in receipt["source_plans"].values())
    assert generation_inputs.load_rules(tmp_path / "out/inputs/norm-rules.json")["timer_rule"]["text"]


def test_unrelated_tracked_symlink_does_not_block_plan_discovery(inputs, tmp_path):
    """Only selected native plan paths receive strict symlink validation."""
    _, _, act, manual = inputs
    unrelated = act / "testplans/priv/unrelated.yaml"
    unrelated.symlink_to("Sstc.yaml")
    commit(act)
    result = generation_inputs.discover_generation_inputs(act, manual, "Sstc", "privileged", [])
    assert "testplans/priv/Sstc.yaml" in result["native_plans"]


@pytest.mark.parametrize("mode", ["local_overlay", "regenerate"])
def test_source_plan_capture_uses_selected_working_tree(inputs, tmp_path, mode):
    """Capture imported plans as-is and never resurrect a removed plan from Git HEAD."""
    factory, _, act, _ = inputs
    plan = act / "testplans/priv/Sstc.yaml"
    if mode == "regenerate":
        plan.unlink()
    else:
        plan.write_text("suite: Sstc\ncoverpoints: [{name: cp_imported}]\n")
    passed, result = factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert passed, result
    receipt = json.loads((tmp_path / "out/inputs/receipt.json").read_text())
    assert bool(receipt["source_plans"]) is (mode == "local_overlay")
    if mode == "local_overlay":
        captured = tmp_path / "out/inputs" / receipt["source_plans"]["testplans/priv/Sstc.yaml"]
        assert captured.read_text() == plan.read_text()


@pytest.mark.parametrize("kind,suite", [("privileged", "Sstc"), ("unprivileged", "I")])
def test_real_stage_dispatch_prepares_and_verifies_inputs(inputs, tmp_path, kind, suite):
    """Accept framework timeouts and declared stage arguments without relaxing Complete or unknown-key checks."""
    factory, _, _, _ = inputs
    checker = factory(kind, suite)
    stage = VerifyStage(
        cfg=Config({"_temp_cfg": {"OUT": "out", "DUT": suite}, "hist_ignore_pattern": [],
                    "skill": {"use_skill": False}}),
        workspace=str(tmp_path), name="prepare_generation_inputs", description="Freeze specification inputs",
        task=[], reference_files=[], skill_list=[], output_files=[],
        checker=[Config({"name": "generation_inputs", "clss": "ACT4GenerationInputsChecker",
                         "args": {"suite": suite, "kind": kind, "input_dir": "out/inputs", "manual_root": "manual"},
                         "extra_args": {}})],
        checker_registry={"ACT4GenerationInputsChecker": ACT4GenerationInputsChecker},
    )
    stage.checker[0].set_stage_manager(checker.stage_manager)
    arguments = {"action": "prepare", "manual_files": ["src/priv/sstc.adoc"]}
    passed, report = stage.do_check(timeout=30, stage_args=arguments)
    assert passed, report
    assert StageManager._ignored_stage_args_keys(stage, arguments) == []
    assert {"plan_paths", "rule_bindings", "manual_exclusions"} <= set(stage.checker[0].accepted_stage_args)
    assert not stage.do_check(timeout=30, is_complete=True, stage_args=arguments)[0]
    assert not stage.do_check(timeout=30, stage_args={"unexpected": True})[0]
    passed, report = stage.do_check(timeout=30, is_complete=True)
    assert passed, report


@pytest.mark.parametrize("timeout", [0, -1, True, "30"])
def test_input_preparation_rejects_invalid_timeout(inputs, tmp_path, timeout):
    """Reject malformed execution budgets before creating frozen input evidence."""
    factory, _, _, _ = inputs
    passed, report = factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"], timeout=timeout)
    assert not passed and "timeout must be a positive integer" in report["error"]
    assert not (tmp_path / "out/inputs/receipt.json").exists()


@pytest.mark.parametrize("mutation", ["receipt", "rules", "manual", "snapshot"])
def test_generation_input_tampering_fails(inputs, tmp_path, mutation):
    """Editable output cannot replace original evidence after successful preparation."""
    factory, _, _, manual = inputs
    checker = factory()
    assert checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]
    path = {"receipt": tmp_path / "out/inputs/receipt.json", "rules": tmp_path / "out/inputs/norm-rules.json",
            "manual": manual / "src/priv/sstc.adoc", "snapshot": tmp_path / "out/inputs/plans/testplans/priv/Sstc.yaml"}[mutation]
    path.write_text(path.read_text() + "\n")
    passed, report = checker.do_check(is_complete=True)
    assert not passed and report["error_code"] == "act4_generation_inputs"


@pytest.mark.parametrize("payload", [{}, {"normative_rules": [{"name": "rule"}]},
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


@pytest.mark.parametrize("indexed", [False, True])
def test_source_binding_unblocks_unpublished_specification(inputs, tmp_path, indexed):
    """Source text stays authoritative when official tags are absent or publishing lags."""
    factory, published, _, manual = inputs
    text = "A device request must report the translated address."
    (manual / "iommu.adoc").write_text(text + "\n")
    commit(manual)
    if not indexed:
        published["normative_rules"] = []
    checker = factory(suite="IOMMU")
    passed, report = checker.do_check(action="prepare", manual_files=["iommu.adoc"])
    assert passed, report
    assert report["rule_count"] == 0
    assert not checker.do_check(is_complete=True)[0]
    binding = {"name": "pending_translation", "source": "iommu.adoc", "start_line": 1, "end_line": 1,
               "text": text, "upstream": "Pending tag proposal for IOMMU translation"}
    passed, report = checker.do_check(action="bind_rules", rule_bindings=[binding])
    assert passed, report
    assert checker.do_check(is_complete=True)[0]
    assert report["pending_rules"] == {"pending_translation": binding["upstream"]}
    assert not checker.do_check(action="bind_rules", rule_bindings=[binding])[0]
    rules = generation_inputs.load_rules(tmp_path / "out/inputs/norm-rules.json")
    assert rules["pending_translation"]["status"] == "pending_source_binding"
    assert rules["pending_translation"]["text"] == text


@pytest.mark.parametrize("mutation", ["text", "range", "source", "tracking", "published", "duplicate", "complete_args"])
def test_pending_bindings_cannot_forge_authority(inputs, tmp_path, mutation):
    """Reject fabricated excerpts, unselected files, invalid ranges and false published identities atomically."""
    factory, _, _, _ = inputs
    checker = factory()
    assert checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]
    binding = {"name": "pending_timer", "source": "src/priv/sstc.adoc", "start_line": 1, "end_line": 1,
               "text": "[#norm:timer_rule]#Architectural timer behavior.#", "upstream": "Pending proposal"}
    original = (tmp_path / "out/inputs/receipt.json").read_bytes()
    if mutation == "text":
        binding["text"] = "Invented expected result"
    elif mutation == "range":
        binding["start_line"] = 0
    elif mutation == "source":
        binding["source"] = "../outside.adoc"
    elif mutation == "tracking":
        binding["upstream"] = ""
    elif mutation == "published":
        binding["name"] = "timer_rule"
    bindings = [binding, binding] if mutation == "duplicate" else [binding]
    assert not checker.do_check(action="bind_rules", rule_bindings=bindings, is_complete=mutation == "complete_args")[0]
    assert (tmp_path / "out/inputs/receipt.json").read_bytes() == original


def test_unavailable_index_still_allows_source_preparation(inputs, monkeypatch):
    """An unavailable public index limits mapping publication, not reading a valid specification."""
    from urllib.error import URLError
    factory, _, _, _ = inputs

    def unavailable(*args, **kwargs):
        """Simulate an unreachable official rule publication."""
        raise URLError("offline")

    monkeypatch.setattr(generation_inputs, "urlopen", unavailable)
    checker = factory()
    passed, report = checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert passed, report
    assert report["unpublished_tags"] == ["timer_rule"]
    assert not checker.do_check(is_complete=True)[0]


def test_native_alias_and_privileged_csv_are_captured(inputs, tmp_path):
    """E may reference I.csv; privileged instruction companions are frozen rather than ignored."""
    factory, _, act, _ = inputs
    (act / "testplans/priv/Sstc.csv").write_text("Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\n")
    commit(act)
    checker = factory()
    passed, report = checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert passed and report["companion_plans"] == {"testplans/priv/Sstc.csv": "plans/testplans/priv/Sstc.csv"}
    alias = factory("unprivileged", "E")
    alias.input_dir = "out/e-inputs"
    passed, report = alias.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"], plan_paths=["testplans/I.csv"])
    assert passed, report
    assert report["native_plans"] == ["testplans/I.csv"]


def test_discovery_captures_composite_plans_and_detects_omitted_specification(inputs, tmp_path):
    """A family without a same-name plan is existing work, including every privilege-mode member."""
    factory, _, act, manual = inputs
    for member in ("common", "U", "S", "Sm", "H"):
        entries = "[{heading: Shared context}]" if member == "common" else "[{name: cp_access, description: Uses Svpbmt}]"
        (act / f"testplans/priv/Zicfiss_{member}.yaml").write_text(f"suite: Zicfiss_{member}\ncoverpoints: {entries}\n")
    (act / "testplans/priv/Zicfiss_H.csv").write_text("Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\n")
    for name, content in {"cfi": "Zicfiss. See <<permission>>.\n[#norm:timer_rule]#Architectural timer behavior.#\n",
                          "machine": "[#norm:permission]#Machine rule.#\n[[permission]]\n",
                          "svpbmt": "Page memory types.\n", "supervisor": "Zicfiss control.\n"}.items():
        (manual / f"src/priv/{name}.adoc").write_text(content)
    commit(act)
    commit(manual)
    checker = factory(suite="Zicfiss")
    passed, discovered = checker.do_check(action="discover", manual_files=["src/priv/cfi.adoc"])
    assert passed, discovered
    assert len(discovered["native_plans"]) == 5 and not discovered["new_suite"]
    assert set(discovered["manual_candidates"]) == {f"src/priv/{name}.adoc" for name in ("cfi", "machine", "svpbmt", "supervisor")}
    assert not (tmp_path / "out/inputs/receipt.json").exists()
    assert not checker.do_check(is_complete=True)[0]
    assert not checker.do_check(action="prepare", manual_files=["src/priv/cfi.adoc"])[0]
    assert not (tmp_path / "out/inputs/receipt.json").exists()
    files = sorted(discovered["manual_candidates"])
    assert not checker.do_check(action="prepare", manual_files=files, plan_paths=["testplans/priv/Zicfiss_common.yaml"])[0]
    passed, prepared = checker.do_check(action="prepare", manual_files=files)
    assert passed, prepared
    assert prepared["rule_count"] == 1
    assert prepared["companion_plans"] == {"testplans/priv/Zicfiss_H.csv": "plans/testplans/priv/Zicfiss_H.csv"}
    assert checker.do_check(is_complete=True)[0]


def test_scope_can_only_extend_before_completion_without_refetching_rules(inputs, tmp_path, monkeypatch):
    """Add pinned sources atomically, preserving pending bindings and rejecting scope shrinkage or late edits."""
    factory, _, _, manual = inputs
    extra = manual / "src/priv/details.adoc"
    extra.write_text("Detailed source behavior.\n")
    commit(manual)
    checker = factory()
    assert checker.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]
    binding = {"name": "pending_timer", "source": "src/priv/sstc.adoc", "start_line": 1, "end_line": 1,
               "text": "[#norm:timer_rule]#Architectural timer behavior.#", "upstream": "Proposed timer source binding"}
    assert checker.do_check(action="bind_rules", rule_bindings=[binding])[0]
    receipt = tmp_path / "out/inputs/receipt.json"
    original = receipt.read_bytes()
    published = (tmp_path / "out/inputs/published-norm-rules.json").read_bytes()

    def forbidden_download(*args, **kwargs):
        """Fail if an extension attempts to change the frozen publication."""
        pytest.fail("Scope extension must not refetch the published rule index")

    monkeypatch.setattr(generation_inputs, "urlopen", forbidden_download)
    assert not checker.do_check(action="extend", manual_files=["src/priv/details.adoc"])[0]
    assert not checker.do_check(action="extend", manual_files=["src/priv/sstc.adoc", "src/priv/missing.adoc"])[0]
    assert receipt.read_bytes() == original
    passed, report = checker.do_check(action="extend", manual_files=["src/priv/sstc.adoc", "src/priv/details.adoc"])
    assert passed, report
    assert report["pending_rules"] == {"pending_timer": binding["upstream"]}
    assert (tmp_path / "out/inputs/published-norm-rules.json").read_bytes() == published
    assert checker.do_check(is_complete=True)[0]
    assert not checker.do_check(action="extend", manual_files=report["manual_sources"])[0]
    assert not checker.do_check(action="bind_rules", rule_bindings=[binding])[0]


@pytest.mark.parametrize("reason", ["", None, "Only a related instruction, not part of this suite's normative behavior"])
def test_discovered_candidates_need_capture_or_explicit_exclusion(inputs, reason):
    """Discovery is not semantic authority: out-of-scope references need a reviewable reason, not silent omission."""
    factory, _, _, manual = inputs
    (manual / "src/priv/related.adoc").write_text("Sstc is mentioned here.\n")
    commit(manual)
    passed, report = factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"],
                                       manual_exclusions={"src/priv/related.adoc": reason})
    assert passed == bool(reason), report
    if passed:
        assert report["manual_exclusions"] == {"src/priv/related.adoc": reason}


def test_rule_references_are_not_definition_evidence(inputs, tmp_path):
    """A cross-reference to an external rule cannot authenticate that rule's source location."""
    factory, published, _, manual = inputs
    source = manual / "src/priv/sstc.adoc"
    source.write_text(source.read_text() + "See <<norm:foreign_rule>> and [norm:foreign_rule].\n")
    published["normative_rules"].append({"name": "foreign_rule", "text": "Not defined in the captured source."})
    commit(manual)
    passed, report = factory().do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])
    assert passed and report["rule_count"] == 1
    receipt = json.loads((tmp_path / "out/inputs/receipt.json").read_text())
    assert "foreign_rule" not in receipt["rule_locations"]


def test_discovery_ignores_unselected_symlinks_but_never_captures_them(inputs):
    """Documentation aliases must not break discovery or allow source snapshots to follow links."""
    factory, _, _, manual = inputs
    alias = manual / "linked.adoc"
    alias.symlink_to("src/priv/sstc.adoc")
    commit(manual)
    checker = factory()
    passed, report = checker.do_check(action="discover")
    assert passed and "linked.adoc" not in report["manual_candidates"]
    assert not checker.do_check(action="prepare", manual_files=["linked.adoc"])[0]


def test_shared_chapter_does_not_recursively_import_unrelated_rule_sections(inputs):
    """Inspect nearby target context in shared chapters, not every unrelated extension in a long CSR manual."""
    factory, _, _, manual = inputs
    (manual / "shared.adoc").write_text("Sstc behavior refers to <<timer-details>>.\n" + "\n" * 40 + "Unrelated <<vector-details>>.\n")
    (manual / "timer.adoc").write_text("[[timer-details]]\nTimer behavior.\n")
    (manual / "vector.adoc").write_text("[[vector-details]]\nUnrelated vector behavior.\n")
    commit(manual)
    passed, report = factory().do_check(action="discover", manual_files=["shared.adoc"])
    assert passed and "timer.adoc" in report["manual_candidates"] and "vector.adoc" not in report["manual_candidates"]


@pytest.mark.parametrize("skills", [False, True])
@pytest.mark.parametrize("kind,suite", [("privileged", "Sstc"), ("unprivileged", "I")])
def test_native_assets_accept_real_stage_dispatch_with_prepared_inputs(inputs, tmp_path, skills, kind, suite):
    """Execute preparation and the next gate through VerifyStage, with and without skills, including Complete."""
    factory, _, act, _ = inputs
    preparation = factory(kind, suite)
    assert preparation.do_check(action="prepare", manual_files=["src/priv/sstc.adoc"])[0]
    assert preparation.do_check(is_complete=True)[0]
    if kind == "privileged":
        (act / "testplans/priv/Sstc.yaml").write_text(
            "suite: Sstc\ncoverpoints:\n- name: cp_one\n  goal: Timer access\n"
            "  description: Compare timer state\n  expectation: Expected timer value\n"
            "  check: Compare signature\n  rules: [timer_rule]\n")
    stage = VerifyStage(
        cfg=Config({"_temp_cfg": {"OUT": "out", "DUT": suite}, "hist_ignore_pattern": [], "skill": {"use_skill": skills}}),
        workspace=str(tmp_path), name="native_assets", description="Validate captured plan scope",
        task=[], reference_files=[], skill_list=[], output_files=[],
        checker=[Config({"name": "native_assets", "clss": "ACT4NativeAssetsChecker", "extra_args": {},
                         "args": {"suite": suite, "kind": kind, "input_dir": "out/inputs",
                                  "contract_file": "out/asset_contract.yaml", "phase": "plan"}})],
        checker_registry={"ACT4NativeAssetsChecker": ACT4NativeAssetsChecker},
    )
    stage.checker[0].set_stage_manager(preparation.stage_manager)
    assert not (tmp_path / ".ucagent/skills").exists()
    for complete in (False, True):
        passed, report = stage.do_check(timeout=30, is_complete=complete)
        assert passed, report
    assert not stage.do_check(timeout=30, stage_args={"unexpected": True})[0]
    for timeout in (0, -1, True, "30"):
        assert not stage.checker[0].do_check(timeout=timeout)[0]
