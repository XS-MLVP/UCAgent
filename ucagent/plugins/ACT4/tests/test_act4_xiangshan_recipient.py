"""Exercise compact recipient archives, exact ACT selection and editable rebuild boundaries."""

import copy
import fcntl
import json
import os
import subprocess
import sys
import tarfile

import pytest
import yaml

from test_act4_xiangshan_handoff import HandoffHarness, asset_import


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Create two ACT programs so subset operations cannot accidentally pass as full builds."""
    harness = HandoffHarness(tmp_path, monkeypatch)
    (harness.source / "second.S").write_text((harness.source / "sample.S").read_text())
    harness.plan["imports"].append(asset_import("second.S", "tests/priv/Sstc/second.S"))
    harness.write("input.yaml", harness.plan)
    harness.selection["tests"].append({"path": "priv/Sstc/second.S", "disposition": "include", "reason": "Independent program fixture"})
    harness.write("selection.yaml", harness.selection)
    second = copy.deepcopy(harness.trace["tests"][0])
    second["path"] = "priv/Sstc/second.S"
    second["cases"][0]["evidence"]["path"] = "tests/priv/Sstc/second.S"
    harness.trace["tests"].append(second)
    harness.write("traceability.yaml", harness.trace)
    return harness


@pytest.fixture
def received(harness, tmp_path):
    """Relocate the actual generated archive without producer paths or environment files."""
    harness.built()
    passed, result = harness.checker("delivery").do_check(action="package")
    assert passed, result
    destination = tmp_path / "recipient with spaces"
    with tarfile.open(harness.output / "Sstc-kunminghu-v3.tar.gz") as archive:
        archive.extractall(destination, filter="data")
    return destination / "Sstc-kunminghu-v3"


def invoke(root, *args):
    """Invoke the standalone recipient interface from outside the delivery directory."""
    return subprocess.run([sys.executable, str(root / "handoff.py"), *args], cwd=root.parent,
                          capture_output=True, text=True, timeout=60)


def test_compact_archive_has_one_index_and_no_producer_evidence(harness, received):
    """Keep only required assets, guide and index; preserve ACT hierarchy and frozen originals."""
    manifest = json.loads((received / "manifest.json").read_text())
    names = set(manifest["files"])
    assert {"README.md", "TESTS.md", "Makefile", "handoff.py", "act4_driver.py"} <= names
    assert not any(name.endswith((".log", ".sig", ".results", ".elf.md", ".sig.elf")) for name in names)
    assert not names & {"traceability.json", "build-plan.json", "build-result.json", "run-result.json", "scope.yaml", "input.yaml"}
    assert not any(name.startswith(("builds/", "runs/", "acquisition/", "generation/", "local/")) for name in names)
    assert "framework/tests/priv/Sstc/sample.S" not in names
    for name in ("sample", "second"):
        for directory, suffix in (("src", "S"), ("elf", "elf"), ("bin", "bin"), ("disass", "disass")):
            assert f"{directory}/priv/Sstc/{name}.{suffix}" in names
    report = (received / "TESTS.md").read_text()
    assert "Sstc_cg/cp_timer" in report and "timer_enabled" in report
    assert "Program index" in report and "Coverpoint to norm rules" in report
    assert (harness.output / "bundle/build-result.json").is_file()
    assert list((harness.output / "bundle/builds").rglob("*.sig.log"))
    assert invoke(received, "verify").returncode == 0
    assert not (received / "__pycache__").exists()


def test_make_single_build_run_and_all_preserve_program_boundaries(harness, received):
    """Compile exactly one selected program or all programs, without cutting internal testcase blocks."""
    selected = "priv/Sstc/second.S"
    command = subprocess.run(["make", "build", f"TEST={selected}", "TIMEOUT=30"], cwd=received, capture_output=True, text=True)
    assert command.returncode == 0, command.stderr + command.stdout
    result = json.loads((received / "local/build-result.json").read_text())
    assert [test["source"] for test in result["tests"]] == [selected]
    assert result["tests"][0]["elf"] == "local/elf/priv/Sstc/second.elf"
    assert not (received / "local/elf/priv/Sstc/sample.elf").exists()
    emu = harness.emu("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP")
    run = invoke(received, "run", "--local", "--emu", emu)
    assert run.returncode == 0, run.stderr
    result = json.loads((received / "local/run-result.json").read_text())
    assert [test["source"] for test in result["tests"]] == [selected]
    assert invoke(received, "run", "--local", "--test", "priv/Sstc/sample.S", "--emu", emu).returncode != 0
    assert invoke(received, "build", "--test", "Sstc_cg/cp_timer").returncode != 0
    assert invoke(received, "build", "--test", "../escape.S").returncode != 0
    assert invoke(received, "build", "--test", selected, "--test", selected).returncode != 0
    command = subprocess.run(["make", "all", "TIMEOUT=30"], cwd=received, capture_output=True, text=True)
    assert command.returncode == 0, command.stderr + command.stdout
    assert len(json.loads((received / "local/build-result.json").read_text())["tests"]) == 2
    assert invoke(received, "verify").returncode == 0


def test_delivered_single_run_does_not_require_compiler_or_sail(harness, received, monkeypatch):
    """Executing delivered ELF only needs Python and the supplied emulator."""
    emu = harness.emu("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP")
    monkeypatch.setenv("PATH", "/nonexistent")
    command = invoke(received, "run", "--test", "priv/Sstc/sample.S", "--emu", emu)
    assert command.returncode == 0, command.stderr
    result = json.loads((received / "local/run-result.json").read_text())
    assert len(result["tests"]) == 1 and result["input_kind"] == "delivered"
    assert invoke(received, "doctor", "--emu", emu).returncode == 0
    assert invoke(received, "doctor").returncode != 0


def test_modified_build_invalidates_mapping_and_never_overwrites_delivery(harness, received):
    """Permit explicit edits while retaining original artifacts and rejecting stale local execution."""
    original = (received / "elf/priv/Sstc/sample.elf").read_bytes()
    source = received / "src/priv/Sstc/sample.S"
    source.write_text(source.read_text().replace("addi a0, zero, 0", "addi a0, zero, 1"))
    assert invoke(received, "build", "--test", "priv/Sstc/sample.S").returncode != 0
    build = invoke(received, "build", "--modified", "--test", "priv/Sstc/sample.S")
    assert build.returncode == 0, build.stderr + build.stdout
    result = json.loads((received / "local/build-result.json").read_text())
    assert result["mapping_status"] == "recipient_modified_unreviewed"
    assert "src/priv/Sstc/sample.S" in result["changes"]
    assert (received / "elf/priv/Sstc/sample.elf").read_bytes() == original
    emu = harness.emu("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP")
    assert invoke(received, "run", "--local", "--emu", emu).returncode == 0
    assert json.loads((received / "local/run-result.json").read_text())["mapping_status"] == "recipient_modified_unreviewed"
    (received / "config/link.ld").write_text("changed after build\n")
    assert invoke(received, "run", "--local", "--emu", emu).returncode != 0


@pytest.mark.parametrize("mutation", ["framework", "new_test", "symlink", "missing_source"])
def test_modified_mode_does_not_allow_framework_changes_or_new_programs(received, mutation):
    """Local development remains bounded to the declared ACT program set and safe input roots."""
    if mutation == "framework":
        (received / "framework/framework/src/act/act.py").write_text("modified\n")
    elif mutation == "new_test":
        (received / "src/priv/Sstc/new.S").write_text("new program\n")
    elif mutation == "symlink":
        (received / "src/link.h").symlink_to(received.parent / "outside")
    else:
        (received / "src/priv/Sstc/sample.S").unlink()
    assert invoke(received, "build", "--modified").returncode != 0


def test_failed_rebuild_does_not_run_stale_products(harness, received, monkeypatch):
    """A failed new attempt cannot silently reuse artifacts from an older passing attempt."""
    assert invoke(received, "build").returncode == 0
    monkeypatch.setenv("ACT4_FIXTURE_MODE", "fail")
    assert invoke(received, "build").returncode != 0
    emu = harness.emu("RVCP-SUMMARY: TEST PASSED\nHIT GOOD TRAP")
    result = invoke(received, "run", "--local", "--emu", emu)
    assert result.returncode != 0 and "Latest local build" in result.stderr


def test_product_export_failure_blocks_delivery(harness, monkeypatch):
    """ELF construction alone cannot claim a complete ELF/bin/disassembly handoff."""
    harness.ready()
    monkeypatch.setenv("ACT4_EXPORT_FAIL", "1")
    passed, result = harness.checker("build").do_check(action="build", timeout=30)
    assert not passed, result
    assert not harness.checker("delivery").do_check(action="package")[0]


def test_failed_run_retains_diagnosis_without_shipping_logs(harness):
    """Keep actionable failure status in the index and the detailed logs only with the producer."""
    harness.built()
    harness.emu("RVCP-SUMMARY: TEST FAILED\nHIT BAD TRAP")
    assert harness.checker("build").do_check(action="run", emulator="emu", timeout=30)[0]
    passed, result = harness.checker("delivery").do_check(action="package")
    assert passed and result["status"] == "emulator_failed", result
    report = (harness.output / "delivery/TESTS.md").read_text()
    assert "Run diagnosis:" in report and "failed" in report
    assert not list((harness.output / "delivery").rglob("*.log"))
    assert list((harness.output / "bundle/runs").rglob("*.log"))


def test_unrecorded_delivery_log_blocks_completion(harness):
    """The final directory, not only the archive, must remain free of unrecorded output."""
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    (harness.output / "delivery/extra.log").write_text("unwanted intermediate output\n")
    assert not harness.checker("delivery").do_check(is_complete=True)[0]
    assert harness.checker("delivery").do_check(action="package")[0]
    assert not (harness.output / "delivery/extra.log").exists()


def test_setup_reuses_tools_and_records_missing_dependencies(received, monkeypatch):
    """Probe and setup are standalone, persistent within local/, and report missing tools honestly."""
    assert invoke(received, "doctor").returncode == 0
    assert invoke(received, "setup").returncode == 0
    manifest_before = (received / "manifest.json").read_bytes()
    monkeypatch.setenv("PATH", "/nonexistent")
    assert invoke(received, "setup", "--timeout", "30").returncode != 0
    result = json.loads((received / "local/environment.json").read_text())
    assert result["status"] == "failed"
    assert any(tool["status"] == "unavailable" for tool in result["tools"].values())
    assert (received / "manifest.json").read_bytes() == manifest_before


def test_setup_installs_missing_tool_in_local_prefix(harness, monkeypatch):
    """Exercise the exported installer recipe and reuse its tool on a subsequent invocation."""
    plan_path = harness.output.parent / "environment/plan.yaml"
    plan = yaml.safe_load(plan_path.read_text())
    tool = next(tool for tool in plan["tools"] if tool["id"] == "compiler")
    tool["install"] = [["mkdir", "-p", "{PREFIX}/bin"],
                       ["curl", "-fL", "https://example.invalid/compiler", "-o", "{PREFIX}/bin/riscv64-unknown-elf-gcc"],
                       ["chmod", "+x", "{PREFIX}/bin/riscv64-unknown-elf-gcc"]]
    plan_path.write_text(yaml.safe_dump(plan))
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    package = harness.output / "delivery"
    fake_download = harness.bin / "curl"
    payload = f"#!{sys.executable}\nprint('riscv64-unknown-elf-gcc fixture 1.0')\n"
    fake_download.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nimport sys\nPath(sys.argv[sys.argv.index('-o')+1]).write_text({payload!r})\n")
    fake_download.chmod(0o755)
    (harness.bin / "riscv64-unknown-elf-gcc").unlink()
    monkeypatch.setenv("PATH", str(harness.bin) + os.pathsep + "/usr/bin:/bin")
    result = invoke(package, "setup")
    assert result.returncode == 0, result.stderr + result.stdout
    installed = package / "local/tools/compiler/bin/riscv64-unknown-elf-gcc"
    assert installed.is_file()
    assert invoke(package, "doctor").returncode == 0
    assert invoke(package, "build", "--test", "priv/Sstc/sample.S").returncode == 0


def test_producer_local_installer_is_not_shipped(harness):
    """Do not export a host-dependent copy recipe as an allegedly portable installer."""
    plan_path = harness.output.parent / "environment/plan.yaml"
    plan = yaml.safe_load(plan_path.read_text())
    compiler = next(tool for tool in plan["tools"] if tool["id"] == "compiler")
    compiler["install"] = [["cp", "-a", "/producer/private/toolchain", "{PREFIX}/bin"]]
    plan_path.write_text(yaml.safe_dump(plan))
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    manifest = json.loads((harness.output / "delivery/manifest.json").read_text())
    compiler = next(tool for tool in manifest["environment"] if tool["id"] == "compiler")
    assert compiler["install"] == [] and "unavailable_reason" in compiler
    assert "/producer/private" not in json.dumps(manifest)


def test_recipient_operations_do_not_race_on_current_result(received):
    """Concurrent invocations must not overwrite the latest build/run selection."""
    (received / "local").mkdir()
    with (received / "local/.operation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = invoke(received, "build")
        assert result.returncode != 0 and "Another build" in result.stderr


@pytest.mark.parametrize("field", ["preconditions", "setup", "exercise", "check", "limitations"])
def test_program_design_requires_execution_logic(harness, field):
    """Reject file summaries that omit one of the required design explanations."""
    del harness.trace["tests"][0][field]
    harness.write("traceability.yaml", harness.trace)
    assert harness.checker("inputs").do_check(action="prepare")[0]
    passed, result = harness.checker("target").do_check(action="adapt")
    assert not passed and field in result["error"], result
