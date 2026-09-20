"""Opt-in real XiangShan unit builds, public-pin regressions, PPA and delivery replay."""

from __future__ import annotations

import helpers  # noqa: F401

import json
import os
from pathlib import Path
import random
import shutil
import sys

import pytest

from ucagent.util.config import Config
from design_with_ppa.contracts import atomic_json, atomic_text, atomic_yaml, sha256_file
from design_with_ppa.repo.common import RepoPaths, git_read, run_command
from design_with_ppa.repo.delivery import deliver
from design_with_ppa.repo.snapshot import snapshot_repository
from design_with_ppa.repo.validation import validate_unit


ASSETS = Path(__file__).parent / "fixtures/repo_xiangshan"
ROTATOR = "src/main/scala/utils/VecRotate.scala"
ICACHE = "src/main/scala/xiangshan/frontend/icache"


def repository_state(root):
    """Hash source, Git metadata, symlink targets and modes without refreshing the index."""

    return {path.relative_to(root).as_posix(): {
        "mode": path.lstat().st_mode,
        "content": os.readlink(path) if path.is_symlink() else sha256_file(path),
    } for path in sorted(root.rglob("*")) if path.is_file() or path.is_symlink()}


@pytest.mark.parametrize("mode", ["optimize", "add"])
def test_xiangshan_unit_workflow(tmp_path, mode):
    """Measure an existing Scala dependency or add a unit, leaving XiangShan byte-identical."""

    source_value = os.environ.get("DESIGN_WITH_PPA_XIANGSHAN_SOURCE")
    if not source_value:
        pytest.skip("Set DESIGN_WITH_PPA_XIANGSHAN_SOURCE for opt-in project validation")
    source = Path(source_value).resolve()
    java = str(Path(os.environ["JAVA_HOME"]) / "bin/java")
    scala_cli = str(Path(os.environ["SCALA_CLI_JAR"]).resolve())
    assert Path(scala_cli).is_file(), "SCALA_CLI_JAR must identify scala-cli's bootstrapped JAR"
    assert all(shutil.which(tool) for tool in ("yosys", "picker", "sta", "verilator"))
    before = repository_state(source)
    status_before = git_read(source, "status", "--porcelain=v1", "-z")
    workspace = tmp_path / mode
    workspace.mkdir()
    atomic_json(workspace / "source-before.json", before)
    target = ROTATOR if mode == "optimize" else ICACHE + "/myICache.scala"
    cfg = Config({"design_with_ppa": {
        "repo": {"enabled": True, "source_path": str(source), "source_paths": [
            "build.mill", ROTATOR, ICACHE,
        ], "mode": mode},
        "no_regression_metrics": "performance,timing", "ppa": {},
        "score_weights": {"area": 1.0, "timing": 1.0, "power": 1.0},
    }})
    cfg._temp_cfg = {"OUT": "design", "DUT": "task"}
    paths = RepoPaths(workspace, cfg)
    atomic_text(workspace / "task/README.md", "\n# Byte Lane Reordering\n\n"
                "Preserve eight byte lanes under left/right rotation. Only the selected unit is built.\n")
    try:
        snapshot = snapshot_repository(paths)
        assert snapshot["excluded_submodules"]
        build_text = (paths.snapshot / "build.mill").read_text()
        assert 'defaultScalaVersion = "2.13.17"' in build_text
        assert "org.chipsalliance::chisel:7.13.0" in build_text
        assert not (paths.snapshot / "ready-to-run").exists()
        atomic_yaml(paths.edit / "contract.yaml", {
            "objective": "Rotate eight byte lanes without loss; verify both directions and every amount",
            "target_paths": [target], "allowed_changes": [target], "dependencies": [ROTATOR],
            "caller_impact": "VecRotate source API preserved; new myICache is an unintegrated auxiliary unit",
            "requirements": {"lanes": "Rotate byte lanes, not individual bits", "direction": "Both directions and amounts 0 through 7"},
            "result_fields": {"result": {"width": 64}}, "clock_period_ns": 10.0,
            "max_latency_cycles": 2, "min_throughput_per_cycle": 0.5, "max_cycles": 2000,
        })
        rng = random.Random(73)
        transactions = []
        for word in [0, 2**64 - 1, 0x0706050403020100] + [rng.getrandbits(64) for _ in range(12)]:
            for left in (0, 1):
                for amount in range(8):
                    index = len(transactions)
                    transactions.append({"id": f"t{index}", "inputs": {"data": word, "left": left, "amount": amount},
                                         "release_cycle": index * (2 if mode == "add" else 1)})
        atomic_yaml(paths.edit / "verification/workload.yaml", {"seed": 73, "scenarios": [{
            "name": "all_rotations", "covers": ["lanes", "direction"], "transactions": transactions,
            "expected_examples": {"t0": {"result": 0}, "t33": {"result": 0x0605040302010007},
                                  "t41": {"result": 0x0007060504030201}},
        }]})
        shutil.copy2(ASSETS / "reference.py", paths.edit / "verification/reference.py")
        candidate = paths.edit / "candidate"
        candidate.mkdir()
        pins = {name: {"direction": direction, "width": width, "purpose": purpose} for name, direction, width, purpose in (
            ("data", "input", 64, "Eight byte lanes, lane zero in the least significant byte"),
            ("amount", "input", 3, "Byte rotation amount"), ("left", "input", 1, "Rotate left when asserted"),
            ("result", "output", 64, "Reordered byte lanes"),
        )}
        wrapper = (ASSETS / "VecRotateUnit.scala").read_text()
        top = "VecRotateUnit"
        changes = []
        sources = [ROTATOR]
        if mode == "add":
            top = "myICache"
            pins.update({name: {"direction": direction, "width": 1, "purpose": purpose} for name, direction, purpose in (
                ("clock", "input", "Rising-edge clock"), ("reset", "input", "Synchronous active-high reset"),
                ("req_valid", "input", "Request valid"), ("req_ready", "output", "Request acceptance"),
                ("resp_valid", "output", "Response valid"), ("resp_ready", "input", "Response acceptance"),
            )})
            changes = [{"path": target, "action": "add"}]
            atomic_text(candidate / "files" / target, (ASSETS / "myICache.scala").read_text())
            sources.append(target)
            wrapper = '/** Emit only the new auxiliary unit. */\nimport circt.stage.ChiselStage\nobject UnitMain extends App {\n' \
                '  ChiselStage.emitSystemVerilogFile(new xiangshan.frontend.icache.myICache,\n' \
                '    Array("--target-dir", "unit-rtl"), Array("--disable-all-randomization", "--strip-debug-info",\n' \
                '      "--lowering-options=disallowLocalVariables,disallowPackedArrays"))\n}\n'
        interface = {"version": "v1", "top": top, "pins": pins,
                     "clock": "clock" if mode == "add" else None, "reset": "reset" if mode == "add" else None,
                     "reset_active": 1, "reset_cycles": 2,
                     "request_when": {"req_valid": 1, "req_ready": 1} if mode == "add" else {},
                     "response_when": {"resp_valid": 1, "resp_ready": 1} if mode == "add" else {},
                     "protocol": "In order; rising-edge ready/valid; hold output under backpressure; reset discards pending output"
                     if mode == "add" else "Combinational byte-lane rotation with no clock or reset"}
        atomic_yaml(candidate / "interface.yaml", interface)
        atomic_yaml(candidate / "candidate.yaml", {"variant_id": "baseline", "hypothesis": "Measure the first verified unit", "changes": changes})
        atomic_yaml(candidate / "recipe.yaml", {
            "scope": "unit", "timeout": 600, "systemverilog": True,
            "tool_versions": [{"argv": [java, "-version"]}, {"argv": [java, "-jar", scala_cli, "version", "--cli-version"]}],
            "build": [{"argv": [sys.executable, "-c", (ASSETS / "export.py").read_text(), java, scala_cli, wrapper, *sources], "timeout": 600}],
            "rtl_files": [f"unit-rtl/{top}.sv"],
        })
        for name in ("adapter", "protocol"):
            shutil.copy2(ASSETS / (name + ("_elastic" if mode == "add" else "") + ".py"), candidate / (name + ".py"))
        baseline = validate_unit(paths, baseline=True)
        assert baseline["accepted"] and baseline["hard_targets_pass"]
        if mode == "optimize":
            source_text = (paths.snapshot / ROTATOR).read_text()
            original = """    // generate one-hot encoding of n if needed
    val idxOH = if (storeOneHot) n else UIntToOH(n)
    // generate all possible rotations
    val rotations = VecInit((0 until vecLength).map { rotateNum =>
      VecInit((0 until vecLength).map(i => vec(getRotatedIdx(i, rotateNum, direction))))
    })
    // select the correct rotation
    Mux1H(idxOH, rotations)"""
            replacement = """    if (!storeOneHot && isPow2(vecLength)) {
      // Binary-controlled stages avoid expanding every possible rotation.
      (0 until log2Ceil(vecLength)).foldLeft(vec) { (stage, bit) =>
        VecInit((0 until vecLength).map { i =>
          Mux(n(bit), stage(getRotatedIdx(i, 1 << bit, direction)), stage(i))
        })
      }
    } else {
      val idxOH = if (storeOneHot) n else UIntToOH(n)
      val rotations = VecInit((0 until vecLength).map { rotateNum =>
        VecInit((0 until vecLength).map(i => vec(getRotatedIdx(i, rotateNum, direction))))
      })
      Mux1H(idxOH, rotations)
    }"""
            assert original in source_text, "Review the optimization against this XiangShan revision"
            atomic_text(candidate / "files" / target, source_text.replace(original, replacement))
            changes = [{"path": target, "action": "replace"}]
        else:
            module = (candidate / "files" / target).read_text()
            module = module.replace("val result = IO(Output(UInt(64.W)))",
                                    "val result_lo = IO(Output(UInt(32.W)))\n  val result_hi = IO(Output(UInt(32.W)))")
            module = module.replace("result := stored", "result_lo := stored(31, 0)\n  result_hi := stored(63, 32)")
            atomic_text(candidate / "files" / target, module)
            interface["version"] = "v2"
            interface["pins"].pop("result")
            for suffix in ("lo", "hi"):
                interface["pins"]["result_" + suffix] = {"direction": "output", "width": 32, "purpose": suffix + " result half"}
            atomic_yaml(candidate / "interface.yaml", interface)
            adapter = (candidate / "adapter.py").read_text().replace(
                'env.sample(transaction["id"], {"result": "result"})',
                'env.sample(transaction["id"], {"result": {"pin": "result_lo", "offset": 0}})\n'
                '        env.sample(transaction["id"], {"result": {"pin": "result_hi", "offset": 32}})')
            atomic_text(candidate / "adapter.py", adapter)
            protocol = (candidate / "protocol.py").read_text().replace('env.read("result")',
                '(env.read("result_lo") | (env.read("result_hi") << 32))')
            atomic_text(candidate / "protocol.py", protocol)
        atomic_yaml(candidate / "candidate.yaml", {"variant_id": "candidate", "hypothesis":
                    "Use logarithmic mux stages" if mode == "optimize" else "Explore two 32-bit response pins",
                    "changes": changes})
        measured = validate_unit(paths)
        assert measured["functional_regression"]["pass"]
        result = deliver(paths, migration_script=True)
        assert result["patch_rebuild_pass"]
        assert (paths.edit / "delivery/changes.patch").is_file()
        preview = run_command([sys.executable, str(paths.edit / "delivery/apply.py"), "--target", str(source)], workspace, 30)
        assert preview["returncode"] == 0
        atomic_json(workspace / "summary.json", {"commit": snapshot["commit"], "mode": mode,
                    "baseline": baseline["ppa_metrics"], "candidate": measured["ppa_metrics"],
                    "candidate_accepted": measured["accepted"], "delivery": result})
        print(json.dumps({"workspace": str(workspace), "commit": snapshot["commit"], "mode": mode,
                          "delivered_variant": result["variant_id"], "improvement_found": result["improvement_found"]}))
    finally:
        after = repository_state(source)
        atomic_json(workspace / "source-after.json", after)
        assert before == after, "Original XiangShan source, Git metadata or permissions changed"
        assert status_before == git_read(source, "status", "--porcelain=v1", "-z")
