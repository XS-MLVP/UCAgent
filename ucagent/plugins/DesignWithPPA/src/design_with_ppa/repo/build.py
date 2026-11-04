"""Module-only native elaboration and reuse of the existing managed RTL builder."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from ucagent.util.config import Config

from ..checkers.rtl_validation import RTLBackendBuildChecker
from ..contracts import atomic_json, atomic_text, load_json, sha256_file
from ..rtl import _config_value
from .common import inside, run_command
from .models import Interface, Recipe


def prepare_unit(repository: Path, candidate: Path, build: Path,
                 recipe: Recipe, interface: Interface, cfg=None) -> dict:
    """Run a unit export recipe, resolve parameters, validate pins, and build its Python DUT.

    ``cfg`` is the resolved workflow configuration: its
    ``design_with_ppa.rtl.python_dut.options`` (verilator passthrough and
    ccache) are honored exactly as in the unit workflow, while the language,
    source glob, and template stay pinned to the repo module's normalized
    unit sources.
    """

    build.mkdir(parents=True, exist_ok=False)
    commands = []
    for command in recipe.tool_versions + recipe.build:
        commands.append(run_command(command.argv, inside(repository, command.cwd, exists=True), command.timeout))
    files = [inside(repository, p, exists=True) for p in recipe.rtl_files]
    if any(not p.is_file() for p in files):
        raise ValueError("Every rtl_files entry must identify a regular module/dependency file")
    includes = [inside(repository, p, exists=True) for p in recipe.include_dirs]
    if any(not p.is_dir() for p in includes):
        raise ValueError("include_dirs must identify directories in the independent copy")
    normalized = build / "design/rtl/unit.v"
    normalized.parent.mkdir(parents=True)
    netlist = build / "ports.json"
    read_args = ["-sv"] if recipe.systemverilog else []
    # Yosys does not unquote -I paths consistently. Private relative aliases keep
    # ordered include resolution intact even when a checkout path contains spaces.
    if includes:
        aliases = Path(tempfile.mkdtemp(prefix=".unit-includes-", dir=repository))
        for index, directory in enumerate(includes):
            alias = aliases / str(index)
            alias.symlink_to(directory, target_is_directory=True)
            read_args.append("-I" + alias.relative_to(repository).as_posix())
    read_args += [f"-D{k}={v}" for k, v in recipe.defines.items()]
    read_args += [json.dumps(str(p)) for p in files]
    hierarchy_args = " ".join(f"-chparam {k} {v}" for k, v in interface.parameters.items())
    script = ("read_verilog " + " ".join(read_args)
              + f"; hierarchy -check -top {interface.top} {hierarchy_args}; proc; check -assert; "
              + f"write_json {json.dumps(str(netlist))}; write_verilog -noattr {json.dumps(str(normalized))}")
    commands.append(run_command(["yosys", "-Q", "-T", "-p", script], repository, recipe.timeout))
    modules = load_json(netlist)["modules"]
    ports = modules[interface.top]["ports"]
    actual = {name: {"direction": pin["direction"], "width": len(pin["bits"]),
                     "signed": bool(pin.get("signed", 0))} for name, pin in ports.items()}
    declared = {name: spec.model_dump(exclude={"purpose"}) for name, spec in interface.pins.items()}
    if actual != declared:
        raise ValueError(f"interface.yaml pins differ from elaborated top: expected={declared}, observed={actual}")
    raw_options = (
        _config_value(cfg, "design_with_ppa.rtl.python_dut.options", {})
        if cfg is not None
        else {}
    )
    if hasattr(raw_options, "as_dict"):
        raw_options = raw_options.as_dict()
    if not isinstance(raw_options, dict):
        raise ValueError("design_with_ppa.rtl.python_dut.options must be a mapping")
    unit_cfg = Config({"design_with_ppa": {"rtl": {"language": "verilog",
                  "source_glob": "design/rtl/*.v", "source_template": "verilog-2005",
                  "library_paths": [], "language_options": {},
                  "python_dut": {"interface": "automatic", "options": dict(raw_options)}}}})
    unit_cfg._temp_cfg = {"DUT": "unit_runtime", "OUT": "design"}
    atomic_text(build / "design/architecture.md", "\n# Unit\n\n```yaml\narchitecture:\n  top_module: " + interface.top + "\n```\n")
    checker = RTLBackendBuildChecker(architecture_file="design/architecture.md",
                                    manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
                                    timeout=recipe.timeout, cfg=unit_cfg).set_workspace(str(build))
    passed, result = checker.do_check()
    if not passed:
        raise ValueError(f"Module RTL build failed: {result}")
    shutil.copytree(candidate, build / "candidate")
    provenance = {"commands": commands, "ordered_rtl": [
        {"path": name, "sha256": sha256_file(path)} for name, path in zip(recipe.rtl_files, files)],
        "normalized_rtl_sha256": sha256_file(normalized), "pins": actual,
        "parameters": interface.parameters, "recipe": recipe.model_dump(),
        "builder": load_json(build / ".ucagent/design_with_ppa/rtl_backend_manifest.json")}
    atomic_json(build / "build_evidence.json", provenance)
    return provenance
