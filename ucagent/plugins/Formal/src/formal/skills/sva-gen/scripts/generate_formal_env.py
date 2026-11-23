"""Generate Formal verification sources from parsed, effectively bound RTL interfaces."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import jinja2

from formal.interface import checker_signal_widths, inspect_interface
from formal.execution import atomic_json, input_lock
from formal.preflight import PreflightError, check_generated
from formal.skills.lib.formal_paths import FormalPaths
from formal.skills.lib.formal_tools import (
    INITIAL_RESET_SAMPLE, implemented_initial_reset,
    load_records, incremental_merge_checker, build_whitebox_signal_context,
    build_clock_reset_alias_context, validate_extra_config_against_design, validate_managed_setup,
)


def main() -> int:
    """Render only after actual RTL parameters and concrete ports resolve successfully."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["full", "append"], default="full")
    args = parser.parse_args()
    paths = FormalPaths()
    try:
        with input_lock(Path(paths.base)), tempfile.TemporaryDirectory(dir=paths.base, prefix=".formal-preflight-") as directory:
            preflight = generate(paths, args.mode, Path(directory))
        print(json.dumps(preflight))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps(getattr(exc, "diagnostic", {"status": "error", "error": str(exc)})), file=sys.stderr)
        return 2


def generate(paths: FormalPaths, mode: str, staged: Path) -> dict:
    """Render a temporary input set, preflight it and publish the complete set."""
    original = Path(paths.records_yaml).read_bytes()
    records = load_records(paths.records_yaml)
    if records is None:
        raise ValueError("Current .formal_records.yaml is missing; initialize the Formal task first")
    validate_managed_setup(records.extra_config)
    internal = any(ck.latest_transfer or any(rule.binding == "internal" for rule in (ck.transaction_balance or []))
                   for fg in (records.spec.function_groups if records.spec else []) for fc in fg.functions for ck in fc.check_points)
    interface = inspect_interface(paths.workspace, paths.out, paths.dut, records.spec.parameters if records.spec else {},
                                  include_signals=internal)
    context = build_clock_reset_alias_context(records)
    port_info = interface["port_info"]
    mismatches = validate_extra_config_against_design(records, port_info)
    if mismatches:
        error = PreflightError("clock_reset", [
            {"path": f"{paths.out}/.formal_records.yaml", "field": "basic_info.clock_reset", "message": message}
            for message in mismatches
        ])
        error.diagnostic["next_action"] = "Correct basic_info.clock_reset using the actual DUT input ports and reset polarity, then retry."
        raise error
    clock, reset = context["env_clock"], context["env_reset"]
    actual_clock, actual_reset = context["actual_clock"], context["actual_reset"]
    if records.spec is None:
        raise ValueError("Implement the current spec before generating a Formal environment")
    # Effective constants belong to the generated checker only. Never persist
    # resolved dependent defaults into spec.parameters or pass them to the DUT.
    checker_records = records.model_copy(deep=True)
    checker_records.spec.parameters = interface["effective_parameters"]
    files = {Path(path).name: Path(path) for path in (paths.checker, paths.wrapper, paths.tcl)}
    if mode == "append":
        for name, path in files.items():
            if path.is_file():
                shutil.copyfile(path, staged / name)
    checker, wrapper, tcl = (staged / Path(path).name for path in (paths.checker, paths.wrapper, paths.tcl))
    initial_sample = INITIAL_RESET_SAMPLE if implemented_initial_reset(records) else ""
    if checker.is_file() and "uca_latest_" in checker.read_text(encoding="utf-8"):
        mode = "full"
    if initial_sample or (tcl.is_file() and f"add_init u_checker.{INITIAL_RESET_SAMPLE} -one" in tcl.read_text(encoding="utf-8")):
        mode = "full"
    signal_widths = checker_signal_widths(interface, records.spec.whitebox_signals)
    incremental_merge_checker(checker_records, str(checker), port_info=port_info, mode=mode, signal_widths=signal_widths)
    templates = Path(__file__).resolve().parents[2] / "lib" / "templates"
    environment = jinja2.Environment(loader=jinja2.FileSystemLoader(str(templates)),
                                    undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    if mode == "full" or not wrapper.exists():
        internal = []
        for name, declaration in port_info:
            if name not in {clock, reset, actual_clock, actual_reset}:
                internal.append(re.sub(r"^(input|output|inout)\s+", "", declaration))
        checker_connections = []
        if context["has_clock"]:
            checker_connections.append(f".{clock}({clock})")
        if context["has_reset"]:
            checker_connections.append(f".{reset}({reset})")
        checker_connections.extend(f".{name}({name})" for name, _ in port_info if name not in {clock, reset, actual_clock, actual_reset})
        whitebox = build_whitebox_signal_context(records.spec.whitebox_signals)
        checker_connections.extend(f".{signal['name']}({signal['name']})" for signal in whitebox)
        dut_ports = {name: name for name, _ in port_info}
        if actual_reset == reset and context["reset_active_level"] == "high":
            dut_ports[actual_reset] = f"~{reset}"
        wrapper_context = {"DUT": records.dut, "internal_decls": internal,
                           "dut_connections": [f".{name}({expression})" for name, expression in dut_ports.items()],
                           "checker_connections": checker_connections,
                           "parameter_items": list(interface["effective_parameters"].items()),
                           "dut_parameter_items": list(interface["explicit_overrides"].items()),
                           "whitebox_signals": whitebox, "clock_signal": clock, "reset_signal": reset,
                           "has_clock": context["has_clock"], "has_reset": context["has_reset"],
                           "clock_reset_aliases": context["aliases"]}
        rendered = environment.get_template("tests/wrapper.sv.j2").render(**wrapper_context)
        wrapper.write_text(rendered, encoding="utf-8")
    if mode == "full" or not tcl.exists():
        rendered = environment.get_template("tests/formal.tcl.j2").render(
            DUT=records.dut, extra_config=records.extra_config, has_clock=context["has_clock"], has_reset=context["has_reset"],
            source_files=interface["source_files"], include_dirs=interface["include_dirs"], initial_sample=initial_sample)
        tcl.write_text(rendered, encoding="utf-8")
    try:
        preflight = check_generated(Path(paths.workspace).resolve(), paths.out, paths.dut, staged, interface, records)
    except PreflightError as error:
        error.attach_candidate_sources(paths.out, checker, wrapper)
        raise
    if Path(paths.records_yaml).read_bytes() != original:
        raise ValueError("Formal records changed during generation; retry with the latest revision.")
    Path(paths.tests).mkdir(parents=True, exist_ok=True)
    for name, path in files.items():
        os.replace(staged / name, path)
    atomic_json(Path(paths.tests) / "sva_preflight.json", preflight)
    return preflight


if __name__ == "__main__":
    raise SystemExit(main())
