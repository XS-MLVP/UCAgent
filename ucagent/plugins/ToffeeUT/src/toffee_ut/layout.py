"""Resolve the active DUT from schema2 metadata without changing an existing suite."""

import json
from pathlib import Path
import re

from .paths import local_path


def project_layout(workspace, dut, project="ut_project"):
    """Use declared testbench, environment, specifications and export names when present."""
    if not isinstance(dut, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dut) or dut == "shared":
        raise ValueError("DUT must be an identifier other than the reserved name shared")
    root = local_path(workspace, project, allow_root=True)
    metadata = local_path(workspace, (Path(project) / "workspace.json").as_posix())
    registered = metadata.is_file()
    row = {}
    if registered:
        value = json.loads(metadata.read_text())
        if not isinstance(value, dict) or value.get("schema") != 2 or not isinstance(value.get("duts"), dict):
            raise ValueError("workspace.json must use schema 2 and declare duts")
        if dut not in value["duts"] or not isinstance(value["duts"][dut], dict):
            raise ValueError(f"DUT {dut!r} is not registered in workspace.json; available: {sorted(value['duts'])[:30]}")
        if value.get("fixtures") != "conftest.py":
            raise ValueError("workspace.json fixtures must point to the project conftest.py")
        row = value["duts"][dut]
        if not {"testbench", "environment", "tests", "design_spec", "verification_spec"} <= set(row):
            raise ValueError("Each registered DUT must explicitly declare testbench, environment, tests and both specifications")
    bench = row.get("testbench", dut.lower())
    if not isinstance(bench, str) or not bench.isidentifier() or bench == "shared":
        raise ValueError("Each DUT requires a testbench identifier other than shared")
    result = {"root": root, "dut": dut, "testbench": bench, "registered": registered,
              "environment": row.get("environment", f"testbenches/{bench}/env.py"),
              "tests": row.get("tests", [f"testbenches/{bench}/tests"]),
              "design_specs": row.get("design_spec", [f"docs/spec/design/{dut}.md"]),
              "verification_specs": row.get("verification_spec", [f"docs/spec/verification/{dut}.md"])}
    for kind in ("design", "verification"):
        key = kind + "_specs"
        if isinstance(result[key], str):
            result[key] = [result[key]]
        paths = result[key]
        if not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths):
            raise ValueError(f"{kind}_spec must contain project-relative specification paths")
        for path in paths:
            local_path(workspace, (Path(project) / path).as_posix())
            if not Path(path).is_relative_to(f"docs/spec/{kind}") or ".." in Path(path).parts:
                raise ValueError(f"{kind}_spec must remain below docs/spec/{kind}")
        primary = next((path for path in paths if path.endswith(".md")), None)
        if primary is None:
            raise ValueError(f"{kind}_spec requires a Markdown document for the maintained contract")
        result[kind + "_spec"] = primary
    if not isinstance(result["tests"], list) or not result["tests"]:
        raise ValueError("DUT tests must be a nonempty list of project-relative paths")
    for path in [result["environment"], *result["tests"]]:
        if not isinstance(path, str) or not Path(path).is_relative_to(f"testbenches/{bench}"):
            raise ValueError("DUT environment and tests must remain in its declared testbench")
        local_path(workspace, (Path(project) / path).as_posix())
    config = local_path(workspace, (Path(project) / "ucv.json").as_posix())
    native = {}
    if config.is_file():
        value = json.loads(config.read_text())
        if not isinstance(value, dict) or not isinstance(value.get("duts"), dict):
            raise ValueError("ucv.json must declare duts")
        if dut not in value["duts"]:
            raise ValueError(f"DUT {dut!r} is missing from ucv.json; do not guess its native top or export name")
        native = value["duts"][dut]
        if not isinstance(native, dict):
            raise ValueError("ucv.json DUT configuration must be an object")
    result.update(top=native.get("top", dut), export_name=native.get("export_name", dut))
    for name in ("top", "export_name"):
        if not isinstance(result[name], str) or not result[name].isidentifier():
            raise ValueError(f"DUT {name} must be an identifier")
    return result
