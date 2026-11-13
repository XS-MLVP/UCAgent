"""Prepare picker inputs and byte-preserving document handoff for default UnityTest."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .evidence import local_path, read_json
from .generic_evidence import generic_input_preflight
from .runtime import SCRIPTS


def handoff_documents(source: Path, destination: Path, module: str) -> None:
    """Preflight all flattened names and conflicts before copying any document bytes."""
    design = source / f"{module}_design_document_zh.md"
    if not design.is_file():
        raise ValueError(f"Missing design document: {design}")
    documents = [*sorted((source / "specs").rglob("*_spec.md")), design]
    copies = {}
    for path in documents:
        target = destination / path.name
        if target in copies:
            raise ValueError(f"Flattened document name collision: {copies[target]} and {path}")
        if target.is_symlink() or target.exists() and (not target.is_file() or target.read_bytes() != path.read_bytes()):
            raise ValueError(f"Document target conflict: {path} -> {target}")
        copies[target] = path
    if destination.is_symlink():
        raise ValueError(f"Document directory is redirected: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for target, path in copies.items():
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(path.read_bytes())


def run_logged(command: list[str], cwd: Path, log: Path, *, env: dict | None = None) -> None:
    """Run one external operation without retry, retaining its complete diagnostic output."""
    with log.open("xb") as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise ValueError(f"Command exited {result.returncode}; preserved log: {log}; command: {shlex.join(command)}")


def generation_inputs(workspace: Path, module: str, config: str, fresh: bool,
                      logs: Path) -> tuple[Path, Path]:
    """Use the current explicit generation result, invoking its entry at most once for reuse."""
    result_path = local_path(workspace, f".cache/generation-{module}.json")
    available = False
    if result_path.is_file():
        result = read_json(result_path)
        rtl = local_path(workspace, result["rtl"])
        if rtl.name != f"{module}.sv" or not rtl.is_relative_to(workspace / ".cache"):
            raise ValueError(f"Generation result does not identify current module/cache: {result_path}")
        if shlex.split(result.get("command", ""))[-2:] != ["--config", config]:
            raise ValueError(f"Generation result configuration differs from {config}: {result_path}")
        filelist = rtl.parent / "filelist.f"
        available = rtl.is_file() and filelist.is_file()
    if not available:
        if fresh:
            raise ValueError(f"Fresh mission has no usable generation result/filelist: {result_path}")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, RTL2SPEC_WORKSPACE=str(workspace), XIANGSHAN_ROOT=str(workspace / "third_party/XiangShan"),
                   RTL2SPEC_CACHE=str(workspace / ".cache"), RTL2SPEC_PYTHON=sys.executable)
        run_logged(["bash", str(SCRIPTS / "generate_rtl.sh"), "--module", module, "--config", config,
                    "--result", str(result_path)], workspace, logs / "generation.log", env=env)
        return generation_inputs(workspace, module, config, True, logs)
    return rtl, filelist


def parameter_template(parameters: dict, module: str, directory: Path) -> Path:
    """Copy the picker-advertised template and override the single native DUT instance."""
    result = subprocess.run(["picker", "export", "--help"], capture_output=True, text=True, check=True)
    match = re.search(r"--sdir,--source_dir\s+TEXT\s+\[([^\]\n]+)\]", result.stdout)
    if not match:
        raise ValueError("picker does not advertise its --sdir template directory; cannot apply parameters")
    source = Path(match[1])
    top = source / "lib/top.sv"
    if not top.is_file():
        raise ValueError(f"picker template is missing: {top}")
    original = top.read_bytes()
    marker = b"{{__INNER_MODULES__}}"
    if original.count(marker) != 1:
        raise ValueError(f"Unsupported picker top template: {top}")
    makefile = source / "lib/Makefile"
    make_original = makefile.read_bytes()
    source_argument = b"--source_dir {{__GENERATOR_TEMPLATE_PATH__}}/mem_direct"
    if make_original.count(source_argument) != 1:
        raise ValueError(f"Unsupported picker mem_direct template: {makefile}")
    shutil.copytree(source, directory)
    (directory / "lib/Makefile").write_bytes(make_original.replace(
        source_argument, b'--source_dir "{{__GENERATOR_TEMPLATE_PATH__}}/mem_direct"'))
    overrides = "\n".join(f"defparam {module}.{name} = {value};" for name, value in parameters.items())
    (directory / "lib/top.sv").write_bytes(original.replace(marker, marker + b"\n\n" + overrides.encode()))
    return directory


def prepare_hardware(workspace: Path, verification: Path, source: Path, module: str,
                     config: str, *, generic: bool, fresh: bool) -> None:
    """Build only Verilator/FST, keeping full compilation inputs out of analysis scope."""
    for tool in ("picker", "verilator"):
        if not shutil.which(tool):
            raise ValueError(f"Required executable not found in PATH: {tool}")
    logs = verification / ".rtl2spec-preparation"
    if logs.exists() or logs.is_symlink():
        raise ValueError(f"Existing preparation: {logs}; preserve it and choose a new UnityTest workspace")
    analysis = verification / f"{module}_RTL"
    if analysis.is_symlink():
        raise ValueError(f"Analysis directory is redirected: {analysis}")
    logs.mkdir(parents=True)
    if generic:
        facts = generic_input_preflight(workspace, module)
        compilation = facts["compilation"]
        base = workspace / f"inputs/{module}"
        files = [local_path(base, name) for name in compilation["files"]]
        analysis_files = files
        includes = [local_path(base, name) for name in compilation["include_dirs"]]
        lines = [json.dumps("-I" + str(path)) for path in includes]
        lines += [json.dumps(f"+define+{name}={value}") for name, value in compilation["defines"].items()]
        lines += [json.dumps(str(path)) for path in files]
        filelist = logs / "compilation.f"
        filelist.write_text("\n".join(lines) + "\n", encoding="utf-8")
        parameters = compilation["parameters"]
    else:
        rtl, filelist = generation_inputs(workspace, module, config, fresh, logs)
        base = workspace
        manifest = source / "evidence/manifest.json"
        related = read_json(manifest).get("related_sources", []) if manifest.is_file() else []
        analysis_files = [rtl, *[local_path(workspace, record["path"]) for record in related]]
        parameters = {}
    copies = {}
    for path in analysis_files:
        target = local_path(analysis, path.relative_to(base))
        if not path.is_file():
            raise ValueError(f"Analysis source is missing in current project: {path}")
        if target.is_symlink() or target.exists() and (not target.is_file() or target.read_bytes() != path.read_bytes()):
            raise ValueError(f"Analysis source target conflict: {target}; choose a new workspace")
        copies[target] = path
    for target, path in copies.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(path.read_bytes())
    command = ["picker", "export", "--fs", str(filelist), "--sim", "verilator", "--rw", "1", "--sname", module,
               "--tdir", str(verification) + os.sep, "-c", "-w", str(verification / module / f"{module}.fst")]
    if parameters:
        template = parameter_template(parameters, module, logs / "picker-template")
        command += ["--sdir", str(template)]
        for name, value in parameters.items():
            command += [f"--sflag=-G{name}={value}"]
    environment = os.environ.copy()
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    if sys.prefix != sys.base_prefix:
        environment["VIRTUAL_ENV"] = sys.prefix
    run_logged(command, workspace, logs / "picker.log", env=environment)
    package = verification / module
    readme = package / "README.md"
    requirement = f"\n# {module}\n\nTarget: {module}\n\nConfiguration: {config}\n\nDocuments: ../{module}_Doc/\n\nAnalysis sources: ../{module}_RTL/\n".encode()
    with readme.open("ab") as stream:
        stream.write(requirement)
    if generic and (base / "README.md").is_file():
        with readme.open("ab") as stream:
            stream.write(b"\n\n" + (base / "README.md").read_bytes())
    run_logged([sys.executable, str(package / "example.py")], package, logs / "example.log")
