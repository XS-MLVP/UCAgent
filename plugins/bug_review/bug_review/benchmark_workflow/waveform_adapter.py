"""Waveform adapter for the Bug Review workflow."""
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, Iterable, List
from .paths import resources_root


def resolve_fst2vcd() -> str:
    return os.environ.get("BENCHMARK_WAVEFORM_FST2VCD_BIN") or shutil.which("fst2vcd") or ""


def resolve_waveform_conversion_script() -> str:
    return os.path.join(
        str(resources_root()),
        "run_waveform_conversion.py",
    )


def auto_generate_waveform_conversion_dir(
    waveform_files: Iterable[Dict[str, object]],
    signal_hints: Iterable[str] = (),
) -> str:
    converter = resolve_fst2vcd()
    script_path = resolve_waveform_conversion_script()
    if not converter or not os.path.exists(script_path):
        return ""

    fst_inputs: List[str] = []
    for item in waveform_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if path and os.path.exists(path):
            fst_inputs.append(path)
    if not fst_inputs:
        return ""

    temp_output_dir = tempfile.mkdtemp(prefix="benchmark_waveform_auto_")
    command = [sys.executable, script_path, "--output-dir", temp_output_dir]
    for path in fst_inputs:
        command.extend(["--input", path])

    seen_hints = set()
    for hint in signal_hints:
        signal = str(hint or "").strip()
        if not signal or signal in seen_hints:
            continue
        seen_hints.add(signal)
        command.extend(["--signal-hint", signal])

    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode not in (0, 1):
        return ""

    report_path = os.path.join(temp_output_dir, "waveform_conversion.json")
    summary_path = os.path.join(temp_output_dir, "waveform_summary.json")
    if os.path.exists(report_path) or os.path.exists(summary_path):
        return temp_output_dir
    return ""
