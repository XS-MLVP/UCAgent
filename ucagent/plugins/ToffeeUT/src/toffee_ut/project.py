"""Deterministic input discovery and non-destructive ucv4xs-style scaffolding."""

import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .layout import project_layout
from .paths import digest, local_path


def inspect_inputs(workspace, dut, project="ut_project", documents=None, rtl_dirs=None, mode="auto"):
    """Discover real inputs; document existence selects preparation, not specification trust."""
    root = Path(workspace).resolve()
    layout = project_layout(root, dut, project)
    if mode not in {"auto", "provided", "derive"}:
        raise ValueError("document mode must be auto, provided or derive")
    if documents is None:
        candidates = [f"{dut}/README.md", f"{dut}_Doc", "inputs/docs",
                      *[(Path(project) / path).as_posix() for path in layout["design_specs"]]]
    else:
        candidates = documents
    found = {}
    for value in candidates:
        path = local_path(root, value)
        paths = path.rglob("*") if path.is_dir() else [path]
        for item in paths:
            if not item.resolve().is_relative_to(root):
                raise ValueError(f"Input symlink escapes workspace: {item}")
            if item.is_file() and item.suffix.lower() in {".md", ".txt", ".pdf", ".rst"}:
                if item.stat().st_size:
                    # Our unfilled skeleton must not turn an RTL-derived resume into
                    # an apparent independent specification input.
                    if item.suffix == ".md" and "<!-- toffee-ut:unfilled -->" in item.read_text():
                        continue
                    found[item.relative_to(root).as_posix()] = digest(item)
        if documents is not None and not path.exists():
            raise FileNotFoundError(f"Explicit document not found: {value}")
    sources = {}
    for value in rtl_dirs if rtl_dirs is not None else [f"{dut}_RTL", dut, f"{project}/rtl"]:
        path = local_path(root, value, allow_root=True)
        for item in path.rglob("*") if path.is_dir() else [path]:
            if not item.resolve().is_relative_to(root):
                raise ValueError(f"RTL symlink escapes workspace: {item}")
            if item.is_file() and item.suffix in {".v", ".sv", ".vh", ".svh", ".scala"}:
                sources[item.relative_to(root).as_posix()] = digest(item)
        if rtl_dirs is not None and not path.exists():
            raise FileNotFoundError(f"Explicit RTL input not found: {value}")
    if mode == "provided" and not found:
        raise ValueError("provided mode requires at least one nonempty document")
    return {"dut": dut, "project": project, "testbench": layout["testbench"],
            "document_mode": "provided" if (mode == "provided" or mode == "auto" and found) else "derive",
            "documents": found, "rtl": sources,
            "environment": layout["environment"], "tests": layout["tests"],
            "design_spec": layout["design_spec"], "verification_spec": layout["verification_spec"]}


def scaffold(workspace, dut, project="ut_project", native_package=None, *, authorize=lambda paths: None):
    """Create only missing project files; preserve existing code, fixtures and metadata."""
    root = Path(workspace).resolve()
    layout = project_layout(root, dut, project)
    target = layout["root"]
    package_parts = [target.name]
    parent = target.parent
    while (parent / "__init__.py").is_file():
        package_parts.insert(0, parent.name)
        parent = parent.parent
    package = ".".join(package_parts)
    template_root = Path(__file__).parent / "templates/project"
    renderer = Environment(loader=FileSystemLoader(template_root), undefined=StrictUndefined,
                           keep_trailing_newline=True, autoescape=False)
    context = {"DUT": dut, "TB": layout["testbench"], "PACKAGE": package,
               "EXPORT_NAME": layout["export_name"], "IMPORT_ROOT": os.path.relpath(parent, target)}
    created, preserved = [], []
    pending = {}
    # A registered suite already owns its fixtures and tests. Adoption must not
    # insert a failing placeholder or a second env.py beside a real env package.
    for source in sorted(template_root.rglob("*")):
        if not source.is_file() or source.suffix != ".j2":
            continue
        relative = source.relative_to(template_root).as_posix()
        rendered_name = renderer.from_string(relative[:-3]).render(context)
        if layout["registered"]:
            continue
        if rendered_name.endswith("/env.py") and (target / rendered_name[:-3]).is_dir():
            continue
        if rendered_name.endswith("/tests/test_contract.py") and any((target / f"testbenches/{layout['testbench']}/tests").rglob("test_*.py")):
            continue
        destination = local_path(root, (Path(project) / rendered_name).as_posix())
        if destination.exists() or destination.is_symlink():
            preserved.append(destination.relative_to(root).as_posix())
            continue
        pending[destination] = renderer.get_template(relative).render(context)
    if pending and not all(part.isidentifier() for part in package_parts):
        raise ValueError("New project package directories must be Python identifiers")
    metadata = target / "workspace.json"
    if layout["registered"]:
        preserved.extend((path.relative_to(root).as_posix() for path in
                          (metadata, target / "ucv.json", target / "conftest.py", target / "pytest.ini") if path.exists()))
    elif not metadata.exists():
        environment = layout["environment"]
        if (target / f"testbenches/{layout['testbench']}/env").is_dir():
            environment = f"testbenches/{layout['testbench']}/env/__init__.py"
        pending[metadata] = json.dumps({"schema": 2, "fixtures": "conftest.py", "duts": {dut: {
            "testbench": layout["testbench"], "environment": environment,
            "tests": layout["tests"], "design_spec": layout["design_spec"],
            "verification_spec": layout["verification_spec"]}}}, indent=2) + "\n"
    if native_package is None and (root / dut / "__init__.py").is_file():
        native_package = dut
    link = local_path(root, (Path(project) / "dut" / dut).as_posix())
    native = None
    if native_package:
        native = local_path(root, native_package)
        if not (native / "__init__.py").is_file():
            raise ValueError("native_package must contain a Picker __init__.py")
        if (link.exists() or link.is_symlink()) and link.resolve() != native.resolve():
            raise ValueError("The requested native package conflicts with the existing project DUT; nothing was replaced")
    new_link = native is not None and not link.exists() and not link.is_symlink()
    authorize([*pending, *([link] if new_link else [])])
    for destination, contents in pending.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x") as stream:
            stream.write(contents)
        created.append(destination.relative_to(root).as_posix())
    if new_link:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(native, target_is_directory=True)
        created.append(link.relative_to(root).as_posix())
    return {"project": project, "package": package, "created": created, "preserved": preserved,
            "adopted": layout["registered"], "testbench": layout["testbench"],
            "design_spec": layout["design_spec"], "verification_spec": layout["verification_spec"],
            "next_action": "Complete design and verification specs, then implement the DUT environment and scenarios."}


def package_root(project):
    """Find the import root of a standalone project or an existing suites.* package."""
    parent = Path(project).resolve().parent
    while (parent / "__init__.py").is_file():
        parent = parent.parent
    return parent
