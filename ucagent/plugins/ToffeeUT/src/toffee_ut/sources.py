"""Bind independent specification sources to operator-selected, unchanged input bytes."""

import hashlib
import hmac
import json
from pathlib import Path

from .layout import project_layout
from .paths import digest, local_path, write_json
from .project import inspect_inputs
from .runner import _signature


def capture_source_documents(workspace, dut, project, documents=None):
    """Capture inputs at tool construction, excluding maintained contracts and RTL aliases."""
    layout = project_layout(workspace, dut, project)
    maintained = {(layout["root"] / name).resolve() for name in
                  (*layout["design_specs"], layout["verification_spec"])}
    inventory = inspect_inputs(workspace, dut, project, documents, rtl_dirs=[])
    sources = {}
    for relative in inventory["documents"]:
        source = local_path(workspace, relative).resolve()
        if source in maintained or source.suffix.lower() in {".v", ".sv", ".vh", ".svh", ".scala"}:
            continue
        sources[source.relative_to(Path(workspace).resolve()).as_posix()] = digest(source)
    return sources


def source_record_path(workspace, dut, project):
    """Give each DUT/project its own evidence identity, including project-root adoption."""
    root = local_path(workspace, project, allow_root=True)
    relative = root.relative_to(Path(workspace).resolve()).as_posix()
    identity = hashlib.sha256(json.dumps([dut, relative]).encode()).hexdigest()
    return local_path(workspace, f".ucagent/toffee_ut_sources/{identity}.json"), relative


def record_source_documents(workspace, dut, project, documents):
    """Persist only the captured inputs; inspect cannot promote newly written documents."""
    for relative, expected in documents.items():
        if digest(local_path(workspace, relative)) != expected:
            raise ValueError(f"Independent input changed: {relative}; ask the operator to review and restart with the intended inputs")
    path, relative = source_record_path(workspace, dut, project)
    record = {"kind": "toffee-ut-input-sources", "dut": dut, "project": relative, "documents": documents}
    record["signature"] = _signature(workspace, record, create=True)
    write_json(path, record)


def confirmed_source_documents(workspace, dut, project):
    """Validate the source record rather than trusting model-writable inventory or URLs."""
    path, relative = source_record_path(workspace, dut, project)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        signature = record.pop("signature")
        valid = (hmac.compare_digest(signature, _signature(workspace, record))
                 and record["kind"] == "toffee-ut-input-sources" and record["dut"] == dut
                 and record["project"] == relative and isinstance(record["documents"], dict))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Independent input evidence is missing or invalid; call UTProject(action='inspect') before confirming requirements")
    return record["documents"]
