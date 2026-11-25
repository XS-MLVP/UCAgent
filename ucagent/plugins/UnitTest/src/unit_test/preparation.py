"""Prepare and validate Picker workspaces from raw RTL or previously prepared inputs."""
from dataclasses import replace
from pathlib import Path
from typing import Literal
import hashlib
import json
import sys

from pydantic import Field
from ucagent import PreparationOptions, rtl_source


class UnitTestPreparationOptions(PreparationOptions):
    """Declare the simulator and visibility of the copied RTL."""
    simulator: Literal["verilator", "gsim", "vcs", "uvs"] = "verilator"
    blackbox: bool = Field(default=False, description="Hide copied RTL after exporting and validating the simulator interface.")


def input_signature(ctx, seeds):
    """Hash normalized source contents and options for raw and redacted prepared inputs."""
    digest = hashlib.sha256(json.dumps({"version": 1, "dut": ctx.dut_name, **ctx.options.model_dump()}, sort_keys=True).encode())
    roots = [ctx.workspace / f"{ctx.dut_name}_RTL", ctx.workspace / f"{ctx.dut_name}_Doc"]
    for path in sorted(path for root in roots for path in root.rglob("*")):
        ctx.check_cancelled()
        if path.is_file():
            digest.update(json.dumps([str(path.relative_to(ctx.workspace)), path.stat().st_size]).encode())
            with path.open("rb") as stream:
                while data := stream.read(1024 * 1024):
                    ctx.check_cancelled()
                    digest.update(data)
    for path in sorted(seeds):
        if not path.resolve().is_relative_to(ctx.source):
            raise ValueError("DUT supplemental source escapes workspace")
        digest.update(json.dumps([path.name, path.stat().st_size]).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def simulator_rw_mode(simulator: str) -> str:
    """Use direct memory access only for Verilator exports."""
    return "1" if simulator == "verilator" else "0"


def prepare_unittest(ctx):
    """Export a source-bound interface, validate it, and record reusable preparation evidence."""
    name, workspace = ctx.dut_name, ctx.workspace
    source_rtl = rtl_source(ctx.source, name)
    rtl = workspace / f"{name}_RTL"
    rtl.mkdir()
    for path in sorted(source_rtl.iterdir()):
        if path.name in {"Doc", name, f"{name}_Doc"}:
            continue
        if path.is_dir() or path.suffix in {".v", ".sv", ".vh", ".svh", ".scala", ".txt"}:
            if path.name.startswith('.') or path.name in {"__pycache__", "unit_test", "uc_test_report"}:
                continue
            ctx.copy(path, rtl / path.name)
    docs = ctx.source / f"{name}_Doc"
    if not docs.is_dir():
        docs = source_rtl / "Doc"
    if docs.is_dir():
        ctx.copy(docs, workspace / f"{name}_Doc")
    cache = ctx.cache or ctx.source
    receipt = cache / ".ucagent/preparation.json"
    previous = {}
    if receipt.is_file() and receipt.resolve().is_relative_to(cache):
        try:
            previous = json.loads(receipt.read_text())
        except (ValueError, OSError):
            pass
    if not isinstance(previous, dict):
        previous = {}
    seeds = [p for p in source_rtl.iterdir() if p.is_file() and p.suffix in {".md", ".py"}]
    if source_rtl != ctx.source:
        seed_names = previous.get("seed_files", []) if cache == ctx.source else []
        if not isinstance(seed_names, list) or any(not isinstance(n, str) or Path(n).name != n for n in seed_names):
            raise ValueError("Invalid preparation seed files; select original DUT sources and retry")
        seeds += [ctx.source / name / seed for seed in seed_names]
        if "seed_files" not in previous:
            seeds += list((ctx.source / name).glob("*.md"))
    seeds = sorted(set(seeds))
    if cache == ctx.source and previous.get("options") and not ctx.options.model_fields_set:
        ctx.options = UnitTestPreparationOptions.model_validate(previous["options"])
    signature = input_signature(ctx, seeds)
    interface = workspace / name
    if (previous.get("signature") == signature or (cache == ctx.source and ctx.options.blackbox
            and previous.get("prepared_signature") == signature and previous.get("options") == ctx.options.model_dump())) and (cache / name / "example.py").is_file():
        ctx.progress("Reusing source-matched simulator interface")
        replace(ctx, source=cache).copy(cache / name, interface)
    else:
        ctx.progress("Exporting simulator interface")
        top = next((rtl / f"{name}{ext}" for ext in (".v", ".sv") if (rtl / f"{name}{ext}").is_file()), None)
        if top is None or not top.read_text().strip():
            raise ValueError(f"Missing nonempty {name}.v/.sv; select original RTL sources to export a new interface")
        suffix = {"verilator": "fst", "gsim": "fst", "vcs": "fsdb", "uvs": "usdb"}[ctx.options.simulator]
        argv = ["picker", "export", top, "--sim", ctx.options.simulator, "--rw", simulator_rw_mode(ctx.options.simulator), "--sname", name,
                "--tdir", str(workspace) + "/", "-c", "-w", interface / f"{name}.{suffix}"]
        if (rtl / "filelist.txt").is_file():
            argv.extend(["--fs", rtl / "filelist.txt"])
        ctx.run_command(argv)
    for path in seeds:
        destination = interface / path.name
        if destination.exists():
            destination.chmod(destination.stat().st_mode | 0o200)
        ctx.copy(path, destination)
    if not (interface / "example.py").is_file():
        raise ValueError("Simulator interface lacks example.py; repair the DUT export and retry")
    ctx.progress("Validating simulator interface")
    ctx.run_command([sys.executable, interface / "example.py"])
    if ctx.options.blackbox:
        for path in [*rtl.rglob("*"), *interface.glob("*")]:
            if path.is_file() and path.suffix in {".v", ".sv", ".vh", ".svh", ".txt"}:
                path.chmod(path.stat().st_mode | 0o200)
                path.write_text("")
    receipt = workspace / ".ucagent/preparation.json"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps({"version": 1, "dut_name": name, "signature": signature,
        "options": ctx.options.model_dump(), "prepared_signature": input_signature(ctx, seeds), "seed_files": [p.name for p in seeds]}, indent=2))
