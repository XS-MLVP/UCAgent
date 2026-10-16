"""Use a real Git checkout and RTL artifacts with only the expensive compiler replaced."""

import platform
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from rtl2spec.documents import artifact_paths, generate_port_scaffold
from rtl2spec.tools import RTL2SpecCommand
from rtl2spec.review import prepare_review

RTL = """// Test fixture, not XiangShan design evidence.
module Sbuffer (
 input clock,
 input reset,
 input [7:0] io_data,
 output [7:0] io_result
);
assign io_result = io_data;
endmodule
"""


def executable(path: Path, text: str) -> None:
    """Install an executable external-tool fixture under the temporary workspace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Create source plus local fake Java/Mill/Espresso; production scripts remain intact."""
    root = tmp_path / "workspace with spaces"
    source = root / "third_party/XiangShan"
    (source / "src/main/scala/top").mkdir(parents=True)
    (source / "src/main/scala/top/Configs.scala").write_text(
        "class DefaultConfig\nclass TestConfig\n"
    )
    (source / "src/main/scala/Sbuffer.scala").write_text("class Sbuffer\n")
    (source / ".mill-version").write_text("fixture\n")
    executable(source / "src/main/resources/espresso", "#!/bin/sh\nexit 0\n")
    for args in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Test fixture",
        ],
    ):
        subprocess.run(
            ["git", "-C", str(source), *args], check=True, capture_output=True
        )
    java = root / ".cache/fake-jdk/bin/java"
    executable(java, "#!/bin/sh\necho 'openjdk version \"17-fixture\"' >&2\n")
    monkeypatch.setenv("JAVA_HOME", str(java.parent.parent))
    espresso_key = f"{platform.system()}-{platform.machine()}".lower()
    executable(
        root
        / f".cache/tools/espresso/{espresso_key}/85265139e9598852f9388d293658a1977a829a01/espresso",
        "#!/bin/sh\nexit 0\n",
    )
    executable(
        root / ".cache/tools/mill/fixture/mill",
        f'''#!{sys.executable}
"""Simulate only TopMain's external compilation, writing actual parseable RTL."""
import os, sys, time
from pathlib import Path
args = sys.argv[1:]
target = Path(args[args.index('--target-dir') + 1])
count = Path(os.environ['RTL2SPEC_WORKSPACE']) / '.cache/compiler-calls'
count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')
time.sleep(float(os.environ.get('RTL2SPEC_TEST_DELAY', '0')))
if not os.environ.get('RTL2SPEC_TEST_NO_RTL'):
    (target / 'Sbuffer.sv').write_text({RTL!r})
sys.exit(int(os.environ.get('RTL2SPEC_TEST_RC', '0')))
''',
    )
    return root


@pytest.fixture
def command(workspace):
    """Use the real plugin tool and packaged subprocess with its normal write policy."""
    return RTL2SpecCommand(
        workspace=str(workspace),
        write_dirs=[
            "outputs",
            ".cache",
            "third_party/XiangShan",
        ],
        un_write_dirs=[".ucagent"],
    )


def draft(root: Path, output_dir: str = "outputs") -> None:
    """Write the maintained complete fixture following the template structure."""
    design, report = artifact_paths(root, "Sbuffer", output_dir)
    for path in (design, report):
        path.parent.mkdir(parents=True, exist_ok=True)
    design.write_text(
        (Path(__file__).parent / "fixtures/design_document.md").read_text(
            encoding="utf-8"
        ).replace("outputs/evidence/", f"{output_dir}/evidence/"),
        encoding="utf-8",
    )
    report.write_text(
        """\n# RTL2Spec 质量复核报告

## 输入基线

Synthetic fixture for Sbuffer/DefaultConfig; captured RTL is the only input.

## 源码复核发现

P-FORWARD was compared with the captured assignment and its E-RTL-01 range.

## 结构化事实统计

| 统计项 | 数量 | 说明 |
| --- | ---: | --- |
| P-* 总数 | 1 | 当前行为数 |
| asserted | 1 | assignment fact |
| no_deterministic_fact | 0 | 无 |
| 关联 OPEN-* | 0 | 无 |

## OPEN 与限制

OPEN-FORMAL-01 保持 Open；本 fixture 不声称已经完成 formal。

## 未执行验证

仿真、综合、回归、断言编译、formal 和 coverage 均为 Unrun。

## 验收范围

仅覆盖文档、源码证据、端口映射和复核记录的一致性。
"""
    )
    manifest = root / output_dir / "evidence/manifest.json"
    if manifest.is_file():
        try:
            manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            schema = manifest_value.get("schema_version")
            generate_port_scaffold(
                root,
                "Sbuffer",
                manifest_value.get("config", "DefaultConfig"),
                generic=schema == 3,
                output_dir=output_dir,
            )
        except (OSError, ValueError, KeyError, TypeError):
            # Some negative tests intentionally create an incomplete manifest.
            pass


def complete_review(root: Path, module: str = "Sbuffer", config: str = "DefaultConfig", *,
                    generic: bool = False, output_dir: str = "outputs") -> None:
    """Fill explicit synthetic review records for the fixture's combinational assignment."""
    prepare_review(root, module, config, generic=generic, output_dir=output_dir)
    path = root / output_dir / "semantic_review.json"
    value = json.loads(path.read_text())
    rtl = (root / output_dir / "evidence" / f"{module}.sv").read_text()
    assignment = re.search(r"\bassign\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*([A-Za-z_][A-Za-z0-9_$]*)\s*;", rtl)
    assert assignment is not None
    lhs, rhs = assignment.groups()
    assignment_line = rtl.count("\n", 0, assignment.start()) + 1
    for behavior in value["behaviors"]:
        behavior.update(
            fact_status="asserted",
            facts=[
                {
                    "kind": "assignment",
                    "lhs": lhs,
                    "rhs": rhs,
                    "operator": "=",
                    "process": "continuous",
                    "event": None,
                    "guards": [],
                    "evidence": [
                        {
                            "path": f"{output_dir}/evidence/{module}.sv",
                            "start_line": assignment_line,
                            "end_line": assignment_line,
                        }
                    ],
                }
            ],
        )
        for aspect, check in behavior["checks"].items():
            check.update(status="not_applicable", conclusion="Synthetic fixture: continuous assignment has no storage, bypass, configuration control or recovery state.",
                         evidence=[{"path": f"{output_dir}/evidence/{module}.sv", "start_line": 2, "end_line": 8}])
            if aspect == "verification_plan":
                check.update(status="reviewed", conclusion="Synthetic forwarding check compares the current input and output; coverage samples known equal data.",
                             ck_ids=["CK-EVENT-RESULT"], coverage_ids=["COV-NORMAL"])
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def artifacts(command, workspace):
    """Generate real signed fixture evidence and synchronize document metadata."""
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    draft(workspace)
    assert command._run("metadata", "Sbuffer")["ok"]
    complete_review(workspace)
    result = command._run("finalize", "Sbuffer")
    assert result["ok"], result
    return workspace
