# -*- coding: utf-8 -*-
"""Generated-workflow templates for spec-driven MCP tool testing."""

MCP_TOOL_ADAPTERS = r'''# -*- coding: utf-8 -*-
"""Create UCAgent MCP adapters dynamically from every generated tool spec."""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, create_model
from ucagent.tools.uctool import UCTool


ROOT = Path.cwd().resolve()
SPEC_DIR = ROOT / ".workflow/tool_specs"
TYPE_MAP = {
    "string": str,
    "str": str,
    "path": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "dict": dict[str, Any],
    "mapping": dict[str, Any],
    "list": list[Any],
    "array": list[Any],
}


def _class_token(name: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", name)
    token = "".join(part[:1].upper() + part[1:] for part in parts)
    return token or "GeneratedTool"


def _load_specs() -> list[dict[str, Any]]:
    specs = []
    for path in sorted(SPEC_DIR.glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"tool spec must be a mapping: {path}")
        value["_spec_path"] = path
        specs.append(value)
    if not specs:
        raise RuntimeError(f"no tool specs found under {SPEC_DIR}")
    return specs


def _field_definition(item: dict[str, Any]):
    # MCP/FastMCP may deserialize JSON-looking string arguments into lists or
    # dicts before Pydantic validation. Keep the transport schema permissive and
    # let the generated tool implementation enforce the business contract.
    python_type = Any
    description = str(item.get("description", ""))
    if item.get("required", False):
        return python_type, Field(description=description)
    return python_type | None, Field(default=None, description=description)


def _spec_inputs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = spec.get("inputs")
    legacy = spec.get("input")
    if canonical is not None and legacy is not None and canonical != legacy:
        raise RuntimeError(
            f"conflicting input and inputs fields: {spec.get('_spec_path')}"
        )
    inputs = canonical if canonical is not None else legacy
    if not isinstance(inputs, list):
        raise RuntimeError(
            f"tool spec input/inputs must be a list: {spec.get('_spec_path')}"
        )
    return inputs


def _build_adapter(spec: dict[str, Any]) -> tuple[str, type[UCTool]]:
    name = str(spec.get("name", "")).strip()
    entry = spec.get("entry", {})
    inputs = _spec_inputs(spec)
    if not name or not isinstance(entry, dict):
        raise RuntimeError(f"invalid tool spec: {spec.get('_spec_path')}")
    module_name = str(entry.get("file", "")).removesuffix(".py").replace("/", ".")
    class_name = str(entry.get("class_name", ""))
    method_name = str(entry.get("method", "run"))
    tool_class = getattr(importlib.import_module(module_name), class_name)
    token = _class_token(name)
    fields = {
        str(item["name"]): _field_definition(item)
        for item in inputs
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    args_model = create_model(f"{token}MCPArgs", **fields)

    def _run(self, tool_input=None, run_manager=None, **kwargs):
        call_args = {}
        if isinstance(tool_input, dict):
            call_args.update(tool_input)
        call_args.update({key: value for key, value in kwargs.items() if value is not None})
        tool = tool_class(root_dir=ROOT)
        result = getattr(tool, method_name)(**call_args)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    adapter_name = f"{token}MCPTool"
    adapter = type(
        adapter_name,
        (UCTool,),
        {
            "__module__": __name__,
            "__annotations__": {
                "name": str,
                "description": str,
                "args_schema": type[BaseModel],
            },
            "name": name,
            "description": str(spec.get("description", name)),
            "args_schema": args_model,
            "_run": _run,
        },
    )
    return adapter_name, adapter


TOOL_NAMES: list[str] = []
ADAPTER_CLASS_NAMES: list[str] = []
for _spec in _load_specs():
    _adapter_name, _adapter = _build_adapter(_spec)
    globals()[_adapter_name] = _adapter
    TOOL_NAMES.append(str(_spec["name"]))
    ADAPTER_CLASS_NAMES.append(_adapter_name)
'''


MCP_TOOL_TEST_RUNNER = r'''# -*- coding: utf-8 -*-
"""Call every generated tool through a child UCAgent MCP server."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


ROOT = Path.cwd().resolve()
LOG_PATH = ROOT / ".workflow/logs/tool_mcp_run.log"
RESULT_LOG_PATH = ROOT / "output/mcp_test_result.log"
SPEC_DIR = ROOT / ".workflow/tool_specs"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADAPTER_MODULE = importlib.import_module("tools.mcp_adapters")
ADAPTERS = ",".join(
    f"tools.mcp_adapters.{name}" for name in ADAPTER_MODULE.ADAPTER_CLASS_NAMES
)


def _load_specs() -> list[dict[str, Any]]:
    specs = []
    for path in sorted(SPEC_DIR.glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise AssertionError(f"tool spec must be a mapping: {path}")
        value["_spec_path"] = path.relative_to(ROOT).as_posix()
        specs.append(value)
    if not specs:
        raise AssertionError("no generated tool specs found")
    return specs


SPECS = _load_specs()
REQUIRED_TOOLS = {str(spec["name"]) for spec in SPECS}


def _record(message: str) -> None:
    print(message)
    with RESULT_LOG_PATH.open("a", encoding="utf-8") as result_log:
        result_log.write(message + "\n")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _restore_writable() -> None:
    for path in [ROOT, *ROOT.rglob("*")]:
        try:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass


def _ucagent_command(port: int) -> list[str]:
    ucagent_home = Path(os.environ.get("UCAGENT_HOME", Path.home() / "FDocB/UCAgent"))
    ucagent_py = ucagent_home / "ucagent.py"
    if not ucagent_py.is_file():
        raise RuntimeError(f"UCAgent entry not found: {ucagent_py}")
    config_path = "./config.yaml"
    return [
        sys.executable,
        str(ucagent_py),
        "./",
        "example",
        "--config",
        config_path,
        "--output",
        "output/mcp_test_agent",
        "--guid-doc-path",
        "./Guide_Doc/",
        "--mcp-server-no-file-tools",
        "--mcp-server-host",
        "127.0.0.1",
        "--mcp-server-port",
        str(port),
        "--ex-tools",
        ADAPTERS,
        "--append-py-path",
        ".",
        "-s",
        "-hm",
        "--no-embed-tools",
        "--no-history",
    ]


def _decode_result(result) -> dict[str, Any]:
    texts = [item.text for item in result.content if hasattr(item, "text")]
    if not texts:
        raise AssertionError("MCP result contains no text")
    try:
        value = json.loads(texts[0])
    except json.JSONDecodeError as exc:
        raise AssertionError(f"MCP result is not JSON: {texts[0]!r}") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"MCP result is not a dict: {value!r}")
    return value


def _positive_case(spec: dict[str, Any]) -> dict[str, Any]:
    for case in spec.get("tests", []):
        if not isinstance(case, dict):
            continue
        expected = case.get("expected", {})
        if isinstance(expected, dict) and expected.get("ok") is True and isinstance(case.get("input"), dict):
            return case
    raise AssertionError(f"tool has no expected.ok=true MCP test case: {spec.get('name')}")


def _has_meaningful_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_meaningful_value(item) for item in value)
    return value not in (None, "", False, 0)


def _validate_result(spec: dict[str, Any], case: dict[str, Any], result: dict[str, Any]) -> None:
    required = {"ok", "data", "errors", "warnings", "meta"}
    missing = sorted(required - set(result))
    if missing:
        raise AssertionError(f"{spec['name']} result missing keys: {missing}")
    expected = case.get("expected", {})
    if result["ok"] is not bool(expected.get("ok")):
        raise AssertionError(
            f"{spec['name']} returned ok={result['ok']!r}, expected {expected.get('ok')!r}; "
            f"errors={result.get('errors')!r}; meta={result.get('meta')!r}"
        )
    data = result.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"{spec['name']} result.data must be a mapping")
    data_keys = spec.get("outputs", {}).get("data_required_keys", [])
    missing_data = [key for key in data_keys if key not in data]
    if missing_data:
        raise AssertionError(f"{spec['name']} result.data missing keys: {missing_data}")
    if data_keys and not _has_meaningful_value({key: data.get(key) for key in data_keys}):
        raise AssertionError(f"{spec['name']} result.data contains only default values")


async def _wait_for_server(port: int) -> None:
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 45
    last_error = None
    while time.monotonic() < deadline:
        try:
            async with streamablehttp_client(url, timeout=5) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    await session.list_tools()
                    return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"MCP server did not become ready: {last_error}")


async def _call_and_check(port: int) -> None:
    await _wait_for_server(port)
    url = f"http://127.0.0.1:{port}/mcp"
    async with streamablehttp_client(url, timeout=10) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            missing = sorted(REQUIRED_TOOLS - names)
            if missing:
                raise AssertionError(f"Generated MCP tools not registered: {missing}")
            _record("[PASS] MCP list_tools registered generated tools: " + ",".join(sorted(REQUIRED_TOOLS)))
    for spec in SPECS:
        case = _positive_case(spec)
        async with streamablehttp_client(url, timeout=10) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = _decode_result(await session.call_tool(str(spec["name"]), case["input"]))
                _validate_result(spec, case, result)
                _record(f"[PASS] MCP call {spec['name']}")


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_LOG_PATH.unlink(missing_ok=True)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    port = _free_port()
    command = _ucagent_command(port)
    with LOG_PATH.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            asyncio.run(_call_and_check(port))
        finally:
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write("q\n")
                    process.stdin.flush()
                    process.wait(timeout=15)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                _restore_writable()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
