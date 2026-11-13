"""Sequence independent document and default UnityTest missions without model calls here."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from .evidence import output_root
from .launch import LaunchSettings, UnityTestSettings, build_command
from .unitytest_prepare import handoff_documents, prepare_hardware

SHARED_CONFIG_KEYS = (
    "backend", "model_type", "openai", "anthropic", "google_genai", "embed",
    "langfuse", "conversation_summary", "rate_limiter", "cmd_timeout",
    "loop_settings", "lang", "runtime_options",
)


def continue_to_unitytest(config_file: Path, settings: LaunchSettings,
                         unitytest: UnityTestSettings) -> int:
    """Stop on failures, preserve artifacts, and exec only a prepared default mission."""
    from ucagent.util.config import get_config
    from ucagent.util.functions import load_ucagent_info

    workspace = Path(settings.workspace).expanduser()
    workspace = (config_file.parent / workspace).resolve()
    output = output_root(workspace, settings.output)
    source = output if settings.mode == "run" else (config_file.parent / Path(settings.source).expanduser()).resolve()
    verification = (workspace / Path(unitytest.workspace).expanduser()).resolve()
    project = workspace / (f"inputs/{settings.module}" if settings.workflow.startswith("generic") else "third_party/XiangShan")
    for protected in (workspace, project, output, source):
        if protected.is_relative_to(verification) or (verification.is_relative_to(protected) and protected != workspace):
            raise ValueError(f"UnityTest workspace overlaps inputs/output: {verification}; {protected}")
    for name in (".ucagent", "unity_test", "uc_test_report", settings.module, ".rtl2spec-unitytest", ".rtl2spec-preparation"):
        if (verification / name).exists() or (verification / name).is_symlink():
            raise ValueError(f"Existing UnityTest state: {verification / name}; choose a new workspace")

    workflow_file = Path(__file__).parent / "workflows" / f"{settings.workflow}.yaml"
    cfg = get_config(str(config_file), workspace=str(workspace), workflow_config_file=str(workflow_file))
    field = "GENERIC_CONFIG" if settings.workflow.startswith("generic") else "XS_CONFIG"
    config = cfg.get_value(f"template_overwrite.{field}")
    if not isinstance(config, str) or not config:
        raise ValueError(f"Missing resolved template_overwrite.{field}")
    if settings.mode == "run":
        info_path = workspace / ".ucagent/ucagent_info.json"
        before = info_path.stat().st_mtime_ns if info_path.exists() else None
        command = [*build_command(config_file), "--loop", "--exit-on-completion", "--mcp-server-port", "-1"]
        result = subprocess.run(command, check=False)
        info = load_ucagent_info(str(workspace))
        updated = info_path.exists() and info_path.stat().st_mtime_ns != before
        completed = updated and isinstance(info, dict) and info.get("all_completed") is True and info.get("dut_name") == settings.module and bool(info.get("stages_info"))
        if result.returncode not in (0, 1) or not completed:
            print(f"RTL2Spec stopped (exit status {result.returncode}); no current completed mission for {settings.module}. Preserve {workspace} and inspect .ucagent/ucagent_info.json.", file=sys.stderr)
            return result.returncode or 1
        print(f"RTL2Spec completed (upstream exit status {result.returncode}); continuing to UnityTest", flush=True)

    prepare_hardware(workspace, verification, source, settings.module, config,
                     generic=settings.workflow.startswith("generic"), fresh=settings.mode == "run")
    handoff_documents(source, verification / f"{settings.module}_Doc", settings.module)
    runtime_dir = verification / ".rtl2spec-unitytest"
    runtime_dir.mkdir(mode=0o700)
    downstream_config = runtime_dir / "config.yaml"
    shared = {key: cfg.get_value(key) for key in SHARED_CONFIG_KEYS if cfg.get_value(key) is not None}
    shared = {key: value.as_dict() if hasattr(value, "as_dict") else value for key, value in shared.items()}
    with open(downstream_config, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        yaml.safe_dump(shared, stream)
    command = [sys.executable, "-P", "-m", "ucagent.cli", str(verification), settings.module,
               "--config", str(downstream_config), "--no-history", "--mcp-server-no-file-tools",
               "--loop", "--exit-on-completion", "--mcp-server-port", "-1"]
    os.execv(sys.executable, command)
    return 0
