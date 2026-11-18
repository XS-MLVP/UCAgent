"""Disposable compiler/solver smoke inputs, independent of official verification goals."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil

from .interface import inspect_interface
from .skills.lib.formal_tools import build_clock_reset_alias_context, build_whitebox_signal_context, validate_extra_config_against_design
from .skills.lib.models import FormalRecords

LABEL = "C_UCAGENT_TOOLCHAIN_SMOKE"


def context(execution):
    """Resolve source/config identity without reading or rendering official CK bodies."""
    import yaml

    target, source, root = execution._paths()
    path = target / ".formal_records.yaml"
    records = FormalRecords.model_validate(yaml.safe_load(path.read_bytes()))
    interface = inspect_interface(str(execution.workspace), execution.output_dir, execution.dut,
                                  records.spec.parameters if records.spec else {})
    mismatches = validate_extra_config_against_design(records, interface["port_info"])
    if mismatches:
        raise ValueError("Correct clock/reset configuration before toolchain smoke: " + "; ".join(mismatches))
    executable = shutil.which("FormalMC")
    if not executable:
        raise ValueError("Formal verification is unavailable; ask the operator to restore the tool and retry RunFormal.")
    files = {}
    for item in sorted(source.rglob("*")):
        if item.is_file():
            if item.is_symlink() or not item.resolve().is_relative_to(execution.workspace):
                raise ValueError("Formal source files must stay inside the workspace without symlinks")
            files[str(item.relative_to(execution.workspace))] = hashlib.sha256(item.read_bytes()).hexdigest()
    tool = Path(executable).resolve()
    config = {"parameters": records.spec.parameters if records.spec else {},
              "whitebox_signals": records.spec.whitebox_signals if records.spec else [],
              "clock_reset": build_clock_reset_alias_context(records), "extra_config": records.extra_config}
    identity = {"input_manifest_version": 2, "files": files, "config": config, "policy": asdict(execution.policy),
                "tool": [str(tool), tool.stat().st_size, tool.stat().st_mtime_ns]}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return target, root, records, interface, executable, files, config, fingerprint


def generate(execution, directory, records, interface, files):
    """Freeze smoke inputs and return the hashes of the generated solver files."""
    import jinja2

    from .execution import PROOF_MARKER

    inputs = directory / "inputs"
    for name, digest in files.items():
        content = (execution.workspace / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("RTL changed while preparing toolchain smoke; retry RunFormal preflight")
        target = inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    tests = inputs / execution.output_dir / "tests"
    tests.mkdir(parents=True)
    clock = build_clock_reset_alias_context(records)
    whitebox = build_whitebox_signal_context(records.spec.whitebox_signals if records.spec else [])
    env_clock, env_reset = clock["env_clock"], clock["env_reset"]
    actual_clock, actual_reset = clock["actual_clock"], clock["actual_reset"]
    ports = interface["port_info"]
    internal = [re.sub(r"^(input|output|inout)\s+", "", declaration) for name, declaration in ports
                if name not in {env_clock, env_reset, actual_clock, actual_reset}]
    expressions = {name: name for name, _ in ports}
    if actual_reset == env_reset and clock["reset_active_level"] == "high":
        expressions[actual_reset] = f"~{env_reset}"
    templates = Path(__file__).parent / "skills/lib/templates"
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(templates)), undefined=jinja2.StrictUndefined)
    wrapper = env.get_template("tests/wrapper.sv.j2").render(
        DUT=execution.dut, parameter_items=list(interface["effective_parameters"].items()),
        dut_parameter_items=list(interface["explicit_overrides"].items()), internal_decls=internal,
        dut_connections=[f".{name}({value})" for name, value in expressions.items()],
        checker_connections=[f".{env_clock}({env_clock})"] if clock["has_clock"] else [],
        whitebox_signals=whitebox, clock_signal=env_clock, reset_signal=env_reset,
        has_clock=clock["has_clock"], has_reset=clock["has_reset"], clock_reset_aliases=clock["aliases"])
    # The single cover checks solver availability only, not DUT behavior, reachability or assumptions.
    parameters = ", ".join("parameter " + name + " = " + value for name, value in interface["effective_parameters"].items())
    checker = "module " + execution.dut + "_checker" + (" #(" + parameters + ")" if parameters else "")
    checker += "(input logic " + env_clock + ");\n" if clock["has_clock"] else "();\n"
    checker += LABEL + ": cover property (" + ("@(posedge " + env_clock + ") " if clock["has_clock"] else "") + "1'b1);\nendmodule\n"
    tcl = env.get_template("tests/formal.tcl.j2").render(
        DUT=execution.dut, extra_config=records.extra_config, has_clock=clock["has_clock"], has_reset=clock["has_reset"],
        source_files=interface["source_files"], include_dirs=interface["include_dirs"])
    generated = {
        f"{execution.dut}_checker.sv": checker,
        f"{execution.dut}_wrapper.sv": wrapper,
        f"{execution.dut}_formal.tcl": tcl,
        "setup.tcl": tcl.split(PROOF_MARKER, 1)[0],
    }
    hashes = {}
    for name, text in generated.items():
        path = tests / name
        content = text.encode("utf-8")
        path.write_bytes(content)
        hashes[str(path.relative_to(inputs))] = hashlib.sha256(content).hexdigest()
    return hashes
