"""Exercise V3 handoff isolation, native command evidence, and relocated delivery."""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from act4_privileged_suite import xiangshan_bundle as bundle
from act4_privileged_suite import environment
from act4_privileged_suite.checkers.act4_xiangshan_checker import ACT4XiangShanChecker, TARGET_TOPICS
from act4_privileged_suite.plugin import get_plugin
from act4_privileged_suite.workspace import validate_xiangshan_paths
from ucagent.plugins import PluginError, load_plugin
from ucagent.verify_agent import VerifyAgent


def elf_bytes() -> bytes:
    """Construct a minimal loadable RV64 fixture, not an executable hardware test."""
    content = bytearray(256)
    content[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHIQQQ", content, 16, 2, 243, 1, 0x80000000, 64, 0)
    struct.pack_into("<HHH", content, 52, 64, 56, 1)
    struct.pack_into("<IIQQQQQQ", content, 64, 1, 5, 0, 0x80000000, 0x80000000, 256, 256, 4096)
    payload = b"RVCP-SUMMARY: TEST PASSED\x00RVCP-SUMMARY: TEST FAILED\x00\x6b\x00\x05\x00"
    content[128:128 + len(payload)] = payload
    return bytes(content)


def asset_import(source: str, destination: str, origin: str = "local") -> dict:
    """Declare an import attached to the fixture's requested XiangShan function."""
    return {"origin": origin, "source": source, "destination": destination, "features": ["timer"]}


class HandoffHarness:
    """Use real temporary Git/source trees and subprocess fixtures without EDA tools."""

    def __init__(self, root: Path, monkeypatch):
        """Prepare a local module, matching framework, V3 references and native CLI fixture."""
        self.root = root
        self.output = root / "out/Sstc/handoff"
        self.output.mkdir(parents=True)
        self.source = root / "local"
        self.source.mkdir()
        (self.source / "sample.S").write_text("// START_TEST_CONFIG\n// NEEDS_SIGNATURE: true\n// END_TEST_CONFIG\naddi a0, zero, 0\n")
        self.framework = root / "framework"
        for name in ("README.md", "pyproject.toml", "uv.lock", "framework/src/act/act.py", "tests/env/rvtest_macros.h"):
            destination = self.framework / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("fixture\n")
        self.xs = root / "XiangShan"
        self.xs.mkdir()
        (self.xs / "Platform.scala").write_text("class DefaultConfig\nval platform = true\n")
        subprocess.run(["git", "init", "-q", "-b", "kunminghu-v3", str(self.xs)], check=True)
        subprocess.run(["git", "-C", str(self.xs), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.xs), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.xs), "rev-parse", "HEAD"], text=True).strip()
        self.state = {}
        self.manager = SimpleNamespace(get_data=self.state.get, set_data=self.state.__setitem__)
        self.plan = {"schema_version": 1, "suite": "Sstc",
                     "framework_paths": ["README.md", "pyproject.toml", "uv.lock", "framework", "tests/env"],
                     "imports": [asset_import("sample.S", "tests/priv/Sstc/sample.S"), asset_import("coverage.svh", "coverpoints/priv/Sstc.svh"),
                                 asset_import("norm.yaml", "coverpoints/norm/Sstc.yaml")], "generation": []}
        (self.source / "coverage.svh").write_text("covergroup Sstc_cg;\ncp_timer: coverpoint enabled;\nendgroup\n")
        (self.source / "norm.yaml").write_text("normative_rule_definitions:\n  - name: timer_enabled\n    coverpoint: ['Sstc_cg/cp_timer']\n")
        plan_path = self.framework / "testplans/Sstc.csv"
        plan_path.parent.mkdir()
        plan_path.write_text("Sstc timer planning fixture without implementation\n")
        self.scope = {"schema_version": 1, "module": "Sstc", "request": "Test the XiangShan supervisor timer",
            "features": [{"id": "timer", "description": "Timer access", "act4_suites": ["Sstc"], "queries": ["Sstc"],
                "xiangshan": {"path": "Platform.scala", "lines": [1, 1], "quote": "class DefaultConfig"},
                "inspected": [{"path": "testplans/Sstc.csv", "lines": [1, 1], "quote": plan_path.read_text().strip()}],
                "upstream_status": "partial", "assessment": "Only a plan exists in this fixture", "gap": "Runnable assembly is missing",
                "resolution": "local"}], "generation_jobs": []}
        self.write("scope.yaml", self.scope)
        self.trace = {"schema_version": 1,
            "rules": [{"id": "timer_enabled", "description": "Synthetic timer enable rule",
                "definition": {"path": "coverpoints/norm/Sstc.yaml", "lines": [2, 3], "quote": "  - name: timer_enabled\n    coverpoint: ['Sstc_cg/cp_timer']"}}],
            "coverpoints": [{"id": "Sstc_cg/cp_timer", "intent": "Observe timer enable selection",
                "definition": {"path": "coverpoints/priv/Sstc.svh", "lines": [2, 2], "quote": "cp_timer: coverpoint enabled;"},
                "group": {"path": "coverpoints/priv/Sstc.svh", "lines": [1, 1], "quote": "covergroup Sstc_cg;"},
                "rules": [{"id": "timer_enabled", "kind": "native_mapping", "reason": "Explicit fixture rule mapping",
                    "evidence": {"path": "coverpoints/norm/Sstc.yaml", "lines": [2, 3], "quote": "  - name: timer_enabled\n    coverpoint: ['Sstc_cg/cp_timer']"}}]}],
            "tests": [{"path": "priv/Sstc/sample.S", "summary": "Synthetic timer test for handoff contracts, not hardware coverage",
                "preconditions": "Synthetic RV64 fixture", "setup": "Prepare the fixture register",
                "exercise": "Write zero to a0", "check": "Emit controlled fixture selfcheck markers",
                "limitations": "No hardware validation in this fixture",
                "cases": [{"id": "file", "description": "Synthetic zero-result fixture", "stimulus": "Write zero to a0",
                    "expected": "Fixture success; not an ISA validation", "coverpoints": ["Sstc_cg/cp_timer"],
                    "evidence": {"path": "tests/priv/Sstc/sample.S", "lines": [4, 4], "quote": "addi a0, zero, 0"}}]}]}
        self.write("traceability.yaml", self.trace)
        self.write("input.yaml", self.plan)
        self.target = {"schema_version": 1, "family": "kunminghu-v3", "commit": self.commit,
                       "top": "SimTop", "configuration": "DefaultConfig", "memory": {"base": 0x80000000, "size": 0x10000000},
                       "allow_source_only": False, "limitations": ["Synthetic test fixture; no hardware validation"],
                       "decisions": {topic: {"reason": "Synthetic citation for contract testing only", "references": [
                           {"path": "Platform.scala", "lines": [1, 1], "quote": "class DefaultConfig"}]} for topic in TARGET_TOPICS}}
        self.write("target.yaml", self.target)
        self.selection = {"schema_version": 1, "tests": [{"path": "priv/Sstc/sample.S", "disposition": "include", "reason": "Synthetic suite"}]}
        self.write("selection.yaml", self.selection)
        self.write("config/test_config.yaml", {"name": "xiangshan-kmhv3", "compiler_exe": "riscv64-unknown-elf-gcc", "ref_model_exe": "sail_riscv_sim",
                                               "objdump_exe": "riscv64-unknown-elf-objdump",
                                               "udb_config": "udb.yaml", "linker_script": "link.ld", "dut_include_dir": "."})
        self.write("config/udb.yaml", {"name": "fixture", "implemented_extensions": [{"name": "Sstc"}]})
        for name in ("sail.json", "link.ld", "rvmodel_macros.h"):
            (self.output / "config" / name).write_text("fixture\n")
        self.bin = root / "bin"
        self.bin.mkdir()
        compiler = f'''#!{sys.executable}
"""Native build CLI fixture: validates driver arguments and emits synthetic evidence."""
import os
import struct
from pathlib import Path
import sys
args = sys.argv[1:]
if args == ["--version"]:
    print("uv fixture")
    sys.exit(0)
assert args[:3] == ["run", "--frozen", "act"]
assert args[args.index("--test-dir") + 1] == "selected-tests"
work = Path(args[args.index("--workdir") + 1]) / "xiangshan-kmhv3"
mode = os.environ.get("ACT4_FIXTURE_MODE", "pass")
if mode == "fail":
    sys.exit(1)
if mode != "empty":
    for path in Path("selected-tests/priv").rglob("*.S"):
        relative = path.relative_to("selected-tests")
        target = work / "elfs" / relative.with_suffix(".elf")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = bytearray({elf_bytes()!r})
        payload = bytes(int(value) for line in path.read_text().splitlines() if line.startswith('.byte ') for value in line[6:].split(','))
        note = struct.pack('<III', 8, len(payload), 1) + b'UCAGENT\\0' + payload
        note += bytes(-len(note) % 4)
        names = b'\\0.note.ucagent.act4\\0.shstrtab\\0.text\\0'
        note_offset = len(content)
        content.extend(note)
        names_offset = len(content)
        content.extend(names)
        content.extend(bytes(-len(content) % 8))
        table = len(content)
        content.extend(bytes(64))
        content.extend(struct.pack('<IIQQQQIIQQ', 1, 7, 0, 0, note_offset, len(note), 0, 0, 4, 0))
        content.extend(struct.pack('<IIQQQQIIQQ', 20, 3, 0, 0, names_offset, len(names), 0, 0, 1, 0))
        content.extend(struct.pack('<IIQQQQIIQQ', names.index(b'.text'), 1, 6, 0x80000080, 128, 128, 0, 0, 4, 0))
        struct.pack_into('<Q', content, 40, table)
        struct.pack_into('<HHH', content, 58, 64, 4, 2)
        target.write_bytes(content)
        for suffix in (".sig", ".results", ".sig.log"):
            evidence = work / "build" / relative.with_suffix(suffix)
            evidence.parent.mkdir(parents=True, exist_ok=True)
            if mode != "missing_signature" or suffix != ".results":
                evidence.write_text("synthetic evidence\\n")
print("fixture native build completed")
'''
        (self.bin / "uv").write_text(compiler)
        (self.bin / "uv").chmod(0o755)
        for name in ("objcopy", "objdump"):
            tool = self.bin / f"riscv64-unknown-elf-{name}"
            tool.write_text(f'''#!{sys.executable}
"""Controlled binutils fixture with nonempty derived artifacts."""
from pathlib import Path
import os
import sys
if sys.argv[1:] == ["--version"]:
    print("binutils fixture 1.0")
elif os.environ.get("ACT4_EXPORT_FAIL"):
    sys.exit(1)
elif {name!r} == "objcopy":
    Path(sys.argv[-1]).write_bytes(Path(sys.argv[-2]).read_bytes()[128:256])
else:
    print("80000080: fixture disassembly")
''')
            tool.chmod(0o755)
        environment_dir = self.output.parent / "environment"
        environment_dir.mkdir(parents=True)
        receipt = {"schema_version": 1, "tools": {}, "path": [str(self.bin)], "files": {}}
        for name in ("uv", "riscv64-unknown-elf-gcc", "sail_riscv_sim"):
            executable = self.bin / name
            if name != "uv":
                executable.write_text(f"#!{sys.executable}\nprint('{name} fixture 1.0')\n")
                executable.chmod(0o755)
            receipt["tools"][name] = {"status": "ready", "command": name,
                "executable": str(executable), "executable_sha256": bundle.sha256(executable)}
        bundle.write_json(environment_dir / "receipt.json", receipt)
        recipes = []
        for identifier in sorted(environment.TOOL_IDS):
            command = {"compiler": "riscv64-unknown-elf-gcc", "reference": "sail_riscv_sim"}.get(identifier, "uv")
            recipes.append({"id": identifier, "version": "fixture", "basis": "Synthetic environment recipe",
                            "probe": [command, "--version"], "expected_output": "fixture", "install": [],
                            "bin_dirs": ["bin"], "storage": "temporary"})
        (environment_dir / "plan.yaml").write_text(yaml.safe_dump({"schema_version": 1, "tools": recipes}))
        self.state[environment.state_key(environment_dir)] = bundle.sha256(environment_dir / "receipt.json")
        monkeypatch.setenv("PATH", str(self.bin) + os.pathsep + os.environ["PATH"])
        monkeypatch.delenv("ACT4_FIXTURE_MODE", raising=False)
        passed, result = self.checker("scope").do_check(action="discover", queries=["Sstc"])
        assert passed, result

    def write(self, name: str, data: dict):
        """Write an agent-authored canonical document outside frozen package content."""
        path = self.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def checker(self, phase: str) -> ACT4XiangShanChecker:
        """Construct a fresh stage checker sharing persisted controller receipts."""
        checker = ACT4XiangShanChecker(phase, "Sstc", "out/Sstc/handoff", "local", "framework", "XiangShan")
        checker.set_workspace(str(self.root))
        checker.stage_manager = self.manager
        checker.on_init()
        return checker

    def ready(self):
        """Freeze selected source and target through the public checker actions."""
        for phase, action in (("inputs", "prepare"), ("target", "adapt")):
            passed, result = self.checker(phase).do_check(action=action)
            assert passed, result

    def built(self):
        """Build one fixture ELF through a real child process."""
        self.ready()
        passed, result = self.checker("build").do_check(action="build", timeout=30)
        assert passed, result

    def emu(self, output: str, code: int = 0) -> str:
        """Create a controlled emulator process for runner verdict tests."""
        path = self.root / "emu"
        path.write_text(f'#!{sys.executable}\n"""Controlled emulator fixture."""\nprint({output!r})\nraise SystemExit({code})\n')
        path.chmod(0o755)
        return str(path)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Provide a fresh isolated V3 handoff fixture."""
    return HandoffHarness(tmp_path, monkeypatch)


def test_local_source_build_archive_and_relocated_run(harness, tmp_path):
    """Deliver complete source/ELF evidence and execute from an unrelated working directory."""
    before = bundle.identity(harness.source / "sample.S")
    harness.built()
    passed, report = harness.checker("delivery").do_check(action="package")
    assert passed and report["status"] == "built_not_run", report
    archive = harness.output / "Sstc-kunminghu-v3.tar.gz"
    destination = tmp_path / "received"
    with tarfile.open(archive) as stream:
        assert not any(name.endswith(".sig.elf") or "/.venv/" in name for name in stream.getnames())
        stream.extractall(destination, filter="data")
    package = destination / "Sstc-kunminghu-v3"
    assert subprocess.run([sys.executable, str(package / "handoff.py"), "verify"], cwd=tmp_path).returncode == 0
    emu = harness.emu("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP")
    assert subprocess.run([sys.executable, str(package / "handoff.py"), "run", "--emu", emu], cwd=tmp_path).returncode == 0
    result = json.loads((package / "local/run-result.json").read_text())
    assert result["status"] == "passed" and result["target_identity_verified"] is False
    assert bundle.identity(harness.source / "sample.S") == before
    assert harness.checker("delivery").do_check(is_complete=True)[0]


@pytest.mark.parametrize("mode", ["empty", "fail", "missing_signature"])
def test_native_failures_cannot_become_successful_builds(harness, monkeypatch, mode):
    """Reject successful zero-test commands, missing Sail results and command failures."""
    harness.ready()
    monkeypatch.setenv("ACT4_FIXTURE_MODE", mode)
    passed, result = harness.checker("build").do_check(action="build", timeout=30)
    assert not passed, result
    assert json.loads((harness.output / "bundle/build-result.json").read_text())["status"] == "failed"
    assert not harness.checker("delivery").do_check(action="package")[0]


def test_source_only_delivery_requires_real_attempt_and_states_missing_build(harness, monkeypatch):
    """Allow an honest source handoff while preventing an unbuilt ready-to-run claim."""
    harness.target["allow_source_only"] = True
    harness.target["limitations"] = ["Fixture compiler failure; repair toolchain and rebuild before running"]
    harness.write("target.yaml", harness.target)
    harness.ready()
    assert not harness.checker("delivery").do_check(action="package")[0]
    monkeypatch.setenv("ACT4_FIXTURE_MODE", "fail")
    assert harness.checker("build").do_check(action="build", timeout=30)[0]
    passed, report = harness.checker("delivery").do_check(action="package")
    assert passed and report["status"] == "source_only", report
    assert "NOT ready to run" in (harness.output / "delivery/README.md").read_text()
    with tarfile.open(harness.output / "Sstc-kunminghu-v3.tar.gz") as stream:
        assert not any(name.endswith(".elf") for name in stream.getnames())


@pytest.mark.parametrize("output,code,expected", [
    ("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP", 0, "passed"),
    ("HIT GOOD TRAP", 0, "failed"),
    ("RVCP-SUMMARY: TEST PASSED", 0, "failed"),
    ("RVCP-SUMMARY: TEST SIGRUN\nHIT GOOD TRAP", 0, "failed"),
    ("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP\nHIT BAD TRAP", 0, "failed"),
    ("RVCP-SUMMARY: TEST FAILED\nHIT GOOD TRAP", 0, "failed"),
    ("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP\nEXCEEDING CYCLE/INSTR LIMIT", 0, "failed"),
    ("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP", 1, "failed"),
])
def test_emulator_verdict_requires_all_success_conditions(harness, output, code, expected):
    """Do not infer successful selfchecks solely from process exit or simulator traps."""
    harness.built()
    harness.emu(output, code)
    assert harness.checker("build").do_check(action="run", emulator="emu", timeout=30)[0]
    passed, report = harness.checker("delivery").do_check(action="package")
    assert passed and report["status"] == f"emulator_{expected}", report


@pytest.mark.parametrize("path", ["../escape", "/tmp/outside", ".", "bad\nname", "x/../../escape", ".git/config"])
def test_portable_path_rejects_unsafe_names(tmp_path, path):
    """Forbid traversal, absolute paths, control characters and repository metadata."""
    with pytest.raises(ValueError):
        bundle.safe_path(tmp_path, path)


@pytest.mark.parametrize("mutation", ["input", "snapshot", "elf", "receipt", "plan", "config", "citation", "added_source"])
def test_modified_evidence_invalidates_completion(harness, mutation):
    """Cross-check final completion against source, target, actual artifacts and recorded receipts."""
    harness.built()
    result = json.loads((harness.output / "bundle/build-result.json").read_text())
    paths = {"input": harness.source / "sample.S",
             "snapshot": harness.output / "bundle/act4/tests/priv/Sstc/sample.S",
             "elf": harness.output / "bundle" / result["tests"][0]["elf"],
             "receipt": harness.output / "bundle/build-result.json",
             "plan": harness.output / "bundle/build-plan.json",
             "config": harness.output / "config/link.ld",
             "citation": harness.xs / "Platform.scala",
             "added_source": harness.output / "bundle/act4/framework/src/act/new_dependency.py"}
    with paths[mutation].open("ab") as stream:
        stream.write(b"\nchanged\n")
    passed, result = harness.checker("build").do_check(is_complete=True)
    assert not passed, result


def test_read_only_checks_do_not_rerun_and_adaptation_requires_rebuild(harness, monkeypatch):
    """Ordinary lifecycle calls only validate; target updates invalidate old execution evidence."""
    harness.built()
    before = list((harness.output / "bundle/builds").iterdir())
    assert harness.checker("build").do_check()[0]
    assert harness.checker("build").do_check(is_complete=True)[0]
    assert list((harness.output / "bundle/builds").iterdir()) == before
    (harness.output / "config/link.ld").write_text("updated fixture\n")
    passed, report = harness.checker("build").do_check(action="adapt")
    assert not passed and report["error_code"] == "act4_xiangshan_rebuild"
    assert not harness.checker("build").do_check(is_complete=True)[0]
    assert harness.checker("build").do_check(action="build", timeout=30)[0]


@pytest.mark.parametrize("failure", ["v2", "quote", "class", "branch", "empty_selection", "missing_selection", "external_compiler", "source_symlink"])
def test_target_and_input_boundaries(harness, failure):
    """Refuse V2 relabeling, fabricated references, omitted inputs and machine-bound configuration."""
    if failure == "source_symlink":
        (harness.source / "sample.S").unlink()
        (harness.source / "sample.S").symlink_to(harness.framework / "uv.lock")
        assert not harness.checker("inputs").do_check(action="prepare")[0]
        return
    assert harness.checker("inputs").do_check(action="prepare")[0]
    if failure == "v2":
        harness.target["family"] = "kunminghu-v2"
    elif failure == "quote":
        harness.target["decisions"]["timer"]["references"][0]["quote"] = "invented"
    elif failure == "class":
        harness.target["configuration"] = "KunminghuV3Config"
    elif failure == "branch":
        subprocess.run(["git", "-C", str(harness.xs), "branch", "-m", "kunminghu-v2"], check=True)
    elif failure == "empty_selection":
        harness.selection["tests"][0]["disposition"] = "exclude"
    elif failure == "missing_selection":
        harness.selection["tests"] = []
    elif failure == "external_compiler":
        config = yaml.safe_load((harness.output / "config/test_config.yaml").read_text())
        config["compiler_exe"] = "/outside/gcc"
        harness.write("config/test_config.yaml", config)
    harness.write("target.yaml", harness.target)
    harness.write("selection.yaml", harness.selection)
    assert not harness.checker("target").do_check(action="adapt")[0]


def test_native_generator_is_explicit_and_preserves_input(harness):
    """Support generator-only local assets without regenerating an already imported .S."""
    generator = harness.source / "generator.py"
    generator.write_text('"""Synthetic local module generator."""\nfrom pathlib import Path\npath = Path("tests/priv/Sstc/sample.S")\npath.parent.mkdir(parents=True, exist_ok=True)\npath.write_text("// START_TEST_CONFIG\\n// NEEDS_SIGNATURE: true\\n// END_TEST_CONFIG\\naddi a0, zero, 0\\n")\n')
    harness.plan["imports"] = [asset_import("generator.py", "generators/testgen/generator.py"), *harness.plan["imports"][1:]]
    harness.plan["generation"] = [["python3", "generators/testgen/generator.py"]]
    harness.write("input.yaml", harness.plan)
    assert not harness.checker("inputs").do_check(action="prepare")[0]
    assert not (harness.output / "bundle/act4/tests/priv/Sstc/sample.S").exists()
    passed, report = harness.checker("inputs").do_check(action="generate", timeout=30)
    assert passed, report
    assert not (harness.source / "tests").exists()
    assert harness.checker("inputs").do_check(is_complete=True)[0]
    assert harness.checker("target").do_check(action="adapt")[0]


def test_excluded_test_is_not_silently_delivered(harness):
    """Keep excluded source for traceability but remove it from the native selection tree."""
    (harness.source / "excluded.S").write_text("// Excluded fixture\n")
    harness.plan["imports"].append(asset_import("excluded.S", "tests/priv/Sstc/excluded.S"))
    harness.selection["tests"].append({"path": "priv/Sstc/excluded.S", "disposition": "exclude", "reason": "Synthetic unsupported configuration"})
    harness.write("input.yaml", harness.plan)
    harness.write("selection.yaml", harness.selection)
    harness.built()
    package = harness.output / "bundle"
    assert (package / "act4/tests/priv/Sstc/excluded.S").exists()
    assert not (package / "act4/selected-tests/priv/Sstc/excluded.S").exists()
    assert len(json.loads((package / "build-result.json").read_text())["tests"]) == 1


@pytest.mark.parametrize("failure", ["machine", "entry", "segment", "summary", "signature_only", "truncated"])
def test_elf_validation_rejects_wrong_or_nonselfchecking_images(tmp_path, failure):
    """Validate executable layout and markers independently from compiler return codes."""
    content = bytearray(elf_bytes())
    if failure == "machine":
        struct.pack_into("<H", content, 18, 62)
    elif failure == "entry":
        struct.pack_into("<Q", content, 24, 0x10000000)
    elif failure == "segment":
        struct.pack_into("<Q", content, 88, 0)
    elif failure == "summary":
        content[128:] = b"\0" * 128
    elif failure == "signature_only":
        content = content.replace(b"TEST PASSED", b"TEST SIGRUN")
    elif failure == "truncated":
        content = content[:80]
    path = tmp_path / "test.elf"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        bundle.inspect_elf(path, {"base": 0x80000000, "size": 0x10000000})


@pytest.mark.parametrize("source,output", [("local", "out"), ("out/input", "out"), ("local", "local/out"), ("../local", "out"), ("local", ".")])
def test_workflow_roots_protect_read_only_inputs(tmp_path, source, output):
    """Validate configured paths before agent initialization can create output files."""
    values = {"template_overwrite.ACT4_INPUT_ROOT": source, "template_overwrite.ACT4_FRAMEWORK_ROOT": "framework", "template_overwrite.ACT4_XIANGSHAN_ROOT": "XiangShan", "template_overwrite.ACT4_MANUAL_ROOT": "manual"}
    cfg = SimpleNamespace(get_value=values.__getitem__)
    if (source, output) == ("local", "out"):
        assert validate_xiangshan_paths(cfg, {"WORKSPACE": str(tmp_path), "OUT": output}) == {}
    else:
        with pytest.raises(PluginError):
            validate_xiangshan_paths(cfg, {"WORKSPACE": str(tmp_path), "OUT": output})


@pytest.mark.parametrize("skills", [False, True])
@pytest.mark.parametrize("custom_inputs", [False, True])
def test_workflow_initializes_with_optional_skills_and_environment(tmp_path, monkeypatch, skills, custom_inputs):
    """Render the actual four-stage workflow without any skill directory or commercial tool."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for field in ("ACT4_INPUT_ROOT", "ACT4_FRAMEWORK_ROOT", "ACT4_XIANGSHAN_ROOT"):
        monkeypatch.delenv(field, raising=False)
    if custom_inputs:
        monkeypatch.setenv("ACT4_INPUT_ROOT", "local/Sstc")
    loaded = load_plugin(str(Path(__file__).resolve().parents[1]))
    workflow = next(item for item in loaded.plugin.workflows if item.name == "xiangshan-v3-handoff")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = VerifyAgent(workspace=str(workspace), dut_name="Sstc", output="handoffs",
                        workflow_config_file=str(workflow.config_file), plugin_workflow=f"{loaded.plugin.name}:{workflow.name}",
                        plugins=[loaded], template_context_factory=workflow.template_context_factory,
                        plugin_guide_doc_paths=[str(path) for path in workflow.guide_doc_paths],
                        cfg_override=[{"backend.key_name": "blank"}, {"skill.use_skill": skills}, {"langfuse.enable": False}],
                        no_embed_tools=True, no_history=True)
    try:
        assert len(agent.stage_manager.stages) == 6
        assert agent.cfg.write_dirs == ["handoffs"]
        assert agent.cfg.un_write_dirs == ["Guide_Doc"]
        if not skills:
            assert not (workspace / ".ucagent/skills").exists()
        for stage in [agent.stage_manager.stages[0], *agent.stage_manager.stages[2:]]:
            assert len(stage.checker) == 1
            checker = stage.checker[0]
            checker.on_init()
            assert checker.get_template_data() is None
            assert checker.input_root == ("local/Sstc" if custom_inputs else "riscv-arch-test")
            assert not checker.do_check()[0]
        assert "ACT4ReviewDocument" not in [tool.name for tool in agent.tool_list_plugin]
    finally:
        agent.exit()


def test_generation_and_review_registration_stay_separate():
    """Add one opt-in workflow without changing the existing entry point order or requirements."""
    plugin = get_plugin()
    assert [item.name for item in plugin.workflows] == ["privileged-suite-generation", "extension-review", "xiangshan-v3-handoff"]
    assert not plugin.workflows[0].command_requirements
    assert not plugin.workflows[2].command_requirements
    for workflow in plugin.workflows[:2]:
        assert "ACT4XiangShanChecker" not in workflow.config_file.read_text()


def test_relocated_package_can_rebuild_with_its_own_framework(harness, tmp_path):
    """Keep rebuild inputs complete without requiring the original workspace or UCAgent."""
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    destination = tmp_path / "different-machine"
    with tarfile.open(harness.output / "Sstc-kunminghu-v3.tar.gz") as archive:
        archive.extractall(destination, filter="data")
    package = destination / "Sstc-kunminghu-v3"
    command = subprocess.run([sys.executable, str(package / "handoff.py"), "build", "--timeout", "30"], cwd=tmp_path)
    assert command.returncode == 0
    result = json.loads((package / "local/build-result.json").read_text())
    assert result["status"] == "passed"
    attempt = package / result["attempt"]
    native = json.loads((attempt / "build-result.json").read_text())
    assert set(native["tool_versions"]) == {"uv", "compiler", "sail", "objcopy", "objdump"}
    assert bundle.validate_build(attempt, native)["suite"] == "Sstc"


def test_missing_include_can_be_added_by_explicit_resnapshot(harness):
    """Report missing dependencies and preserve old attempts while preparing corrected inputs."""
    with (harness.source / "sample.S").open("a") as stream:
        stream.write('#include "helpers.h"\n')
    assert harness.checker("inputs").do_check(action="prepare")[0]
    passed, report = harness.checker("target").do_check(action="adapt")
    assert not passed and "helpers.h" in report["error"]
    (harness.source / "helpers.h").write_text("#define HELPER 1\n")
    harness.plan["imports"].append(asset_import("helpers.h", "tests/priv/Sstc/helpers.h"))
    harness.write("input.yaml", harness.plan)
    assert not harness.checker("inputs").do_check()[0]
    assert harness.checker("inputs").do_check(action="prepare")[0]
    assert list((harness.output / "previous-inputs").iterdir())
    assert harness.checker("target").do_check(action="adapt")[0]


def test_local_generator_replacement_is_explicit_and_never_changes_framework(harness):
    """Overlay only named local test-generator files and retain both source identities."""
    relative = "generators/testgen/src/testgen/priv/extensions/Sstc.py"
    original = harness.framework / relative
    original.parent.mkdir(parents=True)
    original.write_text('"""Original generator fixture."""\n')
    (harness.source / "Sstc.py").write_text('"""Local generator fixture."""\n')
    harness.plan["framework_paths"].append("generators")
    harness.plan["imports"].append(asset_import("Sstc.py", relative))
    harness.write("input.yaml", harness.plan)
    assert harness.checker("scope").do_check(action="discover", queries=["Sstc"])[0]
    assert not harness.checker("inputs").do_check(action="prepare")[0]
    harness.plan["framework_exclude"] = [relative]
    harness.write("input.yaml", harness.plan)
    assert harness.checker("inputs").do_check(action="prepare")[0]
    assert "Original" in original.read_text()
    assert "Local" in (harness.output / "bundle/act4" / relative).read_text()
    assert harness.checker("target").do_check(action="adapt")[0]
    provenance = json.loads((harness.output / "bundle/provenance.json").read_text())
    assert relative in provenance["inputs"]["framework_replaced"]


def test_native_nonsignature_tests_do_not_require_sail_artifacts(harness, monkeypatch):
    """Use the canonical metadata header instead of guessing whether a test needs signatures."""
    path = harness.source / "sample.S"
    path.write_text(path.read_text().replace("NEEDS_SIGNATURE: true", "NEEDS_SIGNATURE: false"))
    harness.ready()
    monkeypatch.setenv("ACT4_FIXTURE_MODE", "missing_signature")
    passed, report = harness.checker("build").do_check(action="build", timeout=30)
    assert passed, report
    result = json.loads((harness.output / "bundle/build-result.json").read_text())
    assert not any(name.endswith(".sig") for name in result["artifacts"])


def test_command_timeout_and_killcheck_terminate_process_groups(harness):
    """Bound execution time and make explicit cancellation reach all command descendants."""
    log = harness.root / "timeout.log"
    result = bundle.execute([sys.executable, "-c", "import time; time.sleep(10)"], harness.root, log, 1)
    assert result["status"] == "timeout"
    checker = harness.checker("build")
    outcomes = []

    def execute():
        """Run one long fixture in a thread so KillCheck can cancel it."""
        outcomes.append(bundle.execute([sys.executable, "-c", "import time; print('active', flush=True); time.sleep(30)"], harness.root, harness.root / "active.log", 30, checker._track_process))

    worker = threading.Thread(target=execute)
    worker.start()
    deadline = time.monotonic() + 5
    while (checker._process is None or "active" not in checker.check_std(5)) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "active" in checker.check_std(5)
    assert "cancelled" in checker.kill()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert outcomes[0]["status"] == "failed"


def test_detached_v3_revision_is_accepted_with_branch_ancestry(harness):
    """Permit reproducible detached checkouts while still rejecting unrelated V2 revisions."""
    subprocess.run(["git", "-C", str(harness.xs), "update-ref", "refs/remotes/origin/kunminghu-v3", harness.commit], check=True)
    subprocess.run(["git", "-C", str(harness.xs), "checkout", "--detach", "-q"], check=True)
    harness.ready()


def test_upstream_checkout_and_framework_can_be_same_input(harness):
    """Use one ACT checkout as both framework source and module source without rewriting it."""
    relative = "tests/priv/Sstc/sample.S"
    path = harness.framework / relative
    path.parent.mkdir(parents=True)
    path.write_bytes((harness.source / "sample.S").read_bytes())
    harness.plan["imports"] = [asset_import(relative, relative, "upstream")]
    harness.write("input.yaml", harness.plan)
    assert harness.checker("scope").do_check(action="discover", queries=["Sstc"])[0]
    checker = harness.checker("inputs")
    checker.input_root = "framework"
    passed, report = checker.do_check(action="prepare")
    assert passed, report
    assert path.read_bytes() == (harness.output / "bundle/act4" / relative).read_bytes()


def test_generation_receipt_cannot_be_replaced_by_document_claims(harness):
    """Require an actual native generator invocation before marking generator inputs ready."""
    harness.plan["generation"] = [["python3", "-c", "print('generated')"]]
    harness.write("input.yaml", harness.plan)
    assert not harness.checker("inputs").do_check(action="prepare")[0]
    harness.write("generation-result.json", {"schema_version": 1, "commands": [{"status": "passed"}]})
    assert not harness.checker("inputs").do_check(is_complete=True)[0]


def test_archive_mutation_blocks_complete(harness):
    """Seal the archive itself, not just loose files in the producer workspace."""
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    with (harness.output / "Sstc-kunminghu-v3.tar.gz").open("ab") as stream:
        stream.write(b"changed")
    assert not harness.checker("delivery").do_check(is_complete=True)[0]
