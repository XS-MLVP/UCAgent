"""Use a real Git checkout and RTL artifacts with only the expensive compiler replaced."""

import platform
import subprocess
import sys
from pathlib import Path

import pytest

from rtl2spec.documents import artifact_paths
from rtl2spec.tools import RTL2SpecCommand

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
            "reports",
            "evidence",
            ".cache",
            "third_party/XiangShan",
        ],
        un_write_dirs=[".ucagent"],
    )


def draft(root: Path, version: str = "v1.0.0") -> None:
    """Write the maintained complete fixture following the template structure."""
    design, report, history = artifact_paths(root, "Sbuffer", version)
    for path in (design, report, history):
        path.parent.mkdir(parents=True, exist_ok=True)
    design.write_text(
        (Path(__file__).parent / "fixtures/design_document.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    report.write_text(
        "\n# Review\n\nSynthetic test fixture only. RTL evidence exists; no formal proof was run.\n"
    )
    history.write_text(f"\n# History\n\n- {version}: fixture documentation.\n")


@pytest.fixture
def artifacts(command, workspace):
    """Generate real signed fixture evidence and synchronize document metadata."""
    result = command._run("evidence", "Sbuffer", version="v1.0.0")
    assert result["ok"], result
    draft(workspace)
    for action in ("metadata", "render", "lint"):
        result = command._run(action, "Sbuffer", version="v1.0.0")
        assert result["ok"], result
    return workspace
