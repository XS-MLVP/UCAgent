"""Managed Python-DUT and pytest runtime helpers."""

from __future__ import annotations

import ast
import importlib.machinery
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
from ucagent.util.test_tools import ucagent_lib_path
from ..python_dut import (
    _RTL_DUT_CLASS_ENV,
    _RTL_DUT_MODULE_ENV,
)
from ..rtl import (
    _generated_python_dut_identity,
    _workspace_python_dut_root,
)

from .common import (
    _PLUGIN_PYTHON_IMPORT_ROOT,
    _PYTHON_IDENTIFIER_RE,
    _redact_backend_output,
)
from .coverage_model import (
    _cleanup_transient_coverage_data,
)




def _validate_workspace_python_dut(
    workspace: Path,
    manifest: dict[str, Any],
) -> tuple[str, str]:
    """Verify the workspace runtime and return its isolated import identity."""

    expected = manifest.get("generated_content")
    if not isinstance(expected, dict) or set(expected) != {
        "file_count",
        "content_sha256",
    }:
        raise ValueError("RTL backend generated-content receipt is invalid")
    import_identity = manifest.get("python_dut_import")
    if not isinstance(import_identity, dict) or set(import_identity) != {
        "module",
        "class",
    }:
        raise ValueError("RTL validation import identity is invalid")
    module_name = import_identity.get("module")
    class_name = import_identity.get("class")
    if not isinstance(module_name, str) or not _PYTHON_IDENTIFIER_RE.fullmatch(
        module_name
    ):
        raise ValueError("RTL validation module identity is invalid")
    if not isinstance(class_name, str) or not _PYTHON_IDENTIFIER_RE.fullmatch(
        class_name
    ):
        raise ValueError("RTL validation class identity is invalid")
    target = _workspace_python_dut_root(workspace) / module_name
    if _generated_python_dut_identity(target) != expected:
        raise ValueError("generated Python-DUT runtime differs from its build receipt")
    _validate_python_dut_tree(target, class_name)
    return module_name, class_name




def _validate_python_dut_tree(root: Path, class_name: str) -> None:
    """Statically require one complete generated package without importing it."""

    entrypoint = root / "__init__.py"
    if (
        root.is_symlink()
        or not root.is_dir()
        or entrypoint.is_symlink()
        or not entrypoint.is_file()
    ):
        raise ValueError("RTL validation did not produce a complete runtime package")
    if entrypoint.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("RTL validation runtime entrypoint is unexpectedly large")
    try:
        tree = ast.parse(entrypoint.read_text(encoding="utf-8"), filename="<runtime>")
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ValueError("RTL validation runtime entrypoint is invalid") from exc
    if not any(
        isinstance(node, ast.ClassDef) and node.name == class_name
        for node in tree.body
    ):
        raise ValueError("RTL validation runtime entrypoint is incomplete")
    extension_suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    if not any(
        path.is_file()
        and not path.is_symlink()
        and any(path.name.endswith(suffix) for suffix in extension_suffixes)
        for path in root.rglob("*")
    ):
        raise ValueError("RTL validation did not produce a loadable native extension")




def _probe_python_dut_subprocess(
    package_parent: Path,
    module_name: str,
    class_name: str,
    timeout: int,
) -> None:
    """Instantiate the generated DUT in an isolated child process."""

    probe = (
        "import importlib,sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "module = importlib.import_module(sys.argv[2])\n"
        "dut = getattr(module, sys.argv[3])()\n"
        "required = ('GetXPort','RefreshComb','Step','Finish')\n"
        "assert all(callable(getattr(dut, name, None)) for name in required)\n"
        "dut.Finish()\n"
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            probe,
            str(package_parent),
            module_name,
            class_name,
        ],
        cwd=package_parent,
        env=environment,
        text=True,
        capture_output=True,
        timeout=min(timeout, 120),
        check=False,
    )
    if completed.returncode != 0:
        # The child's own output names the real root cause (missing native
        # module, import or syntax error inside the generated runtime); losing
        # it leaves the build diagnostic with no actionable evidence.
        details = _redact_backend_output(
            f"{(completed.stdout or '').strip()}\n{(completed.stderr or '').strip()}".strip(),
            2000,
        )
        raise ValueError(
            "RTL validation runtime could not be initialized"
            + (f": {details}" if details else "")
        )




def _run_pytest(
    workspace: Path,
    test_dir: Path,
    backend: str,
    timeout: int,
    extra_args: list[str],
    test_files: list[Path] | None = None,
    rtl_dut_identity: tuple[str, str] | None = None,
    pytest_targets: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one all-pass backend regression with bounded captured diagnostics."""

    targets = (
        list(pytest_targets)
        if pytest_targets is not None
        else (
            [path.relative_to(workspace).as_posix() for path in test_files]
            if test_files is not None
            else [test_dir.relative_to(workspace).as_posix()]
        )
    )
    # Use the console entry point when available.  ``python -m pytest`` puts
    # the current working directory at ``sys.path[0]`` and can let a DUT
    # input directory shadow the private generated Python-DUT package when
    # both use the same module name.
    pytest_entry = Path(sys.executable).with_name("pytest")
    if not pytest_entry.is_file() or not os.access(pytest_entry, os.X_OK):
        pytest_entry = Path(shutil.which("pytest") or "")
    command = [
        str(pytest_entry),
        "--rootdir",
        str(workspace),
        *targets,
        "-q",
        "-x",
        f"--design-backend={backend}",
        *extra_args,
    ] if pytest_entry.is_file() else [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "--rootdir",
        str(workspace),
        *targets,
        "-q",
        "-x",
        f"--design-backend={backend}",
        *extra_args,
    ]
    environment = os.environ.copy()
    import_paths = [
        str(_workspace_python_dut_root(workspace)),
        str(_PLUGIN_PYTHON_IMPORT_ROOT),
        str(Path(ucagent_lib_path()).resolve()),
        str(workspace),
        str(test_dir),
    ]
    current = environment.get("PYTHONPATH", "")
    if current:
        import_paths.append(current)
    environment["PYTHONPATH"] = os.pathsep.join(import_paths)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if backend == "rtl":
        if (
            not isinstance(rtl_dut_identity, tuple)
            or len(rtl_dut_identity) != 2
            or any(
                not isinstance(value, str)
                or not _PYTHON_IDENTIFIER_RE.fullmatch(value)
                for value in rtl_dut_identity
            )
        ):
            raise ValueError("RTL pytest requires a valid managed DUT identity")
        environment[_RTL_DUT_MODULE_ENV], environment[_RTL_DUT_CLASS_ENV] = (
            rtl_dut_identity
        )
    else:
        environment.pop(_RTL_DUT_MODULE_ENV, None)
        environment.pop(_RTL_DUT_CLASS_ENV, None)
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=environment,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        if backend != "rtl":
            _cleanup_transient_coverage_data(test_dir)
        raise
    if backend != "rtl" or completed.returncode == 0:
        _cleanup_transient_coverage_data(test_dir)
    return completed


def backend_option_usage_failure(
    completed: subprocess.CompletedProcess[str],
) -> bool:
    """Return whether pytest rejected the managed backend option before running.

    A workspace conftest that drops the template-managed
    ``register_managed_test_options`` call makes pytest abort at argument
    parsing (exit code 4) before any test executes.  Callers use this to
    report a conftest-infrastructure failure instead of implying a
    functional reference or test defect.
    """

    stderr = completed.stderr or ""
    return (
        completed.returncode != 0
        and "unrecognized arguments" in stderr
        and "--design-backend" in stderr
    )


_PYTEST_SUMMARY_RE = re.compile(
    r"\b\d+ (?:passed|failed|error|skipped|xfailed|xpassed|warnings?)\b"
    r"|\bno tests ran\b",
    re.IGNORECASE,
)


def timeout_stream_fragment(value: Any) -> str:
    """Decode one subprocess.TimeoutExpired captured stream fragment.

    TimeoutExpired carries bytes or str in its ``stdout``/``stderr`` fields;
    the fragment shows how far the run progressed and any error printed
    before the hang, which a bare ``str(exc)`` (just the timeout notice)
    discards.
    """

    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value if isinstance(value, str) else ""


def pytest_died_before_summary(
    completed: subprocess.CompletedProcess[str],
) -> bool:
    """Return whether pytest was killed before printing any run summary.

    The RTL native runtime aborts the whole process when it cannot write an
    artifact file (for example a coverage path whose directory does not
    exist).  The abort happens right after the first progress character, so
    the captured stdout contains no summary line, no FAILED entry, and the
    captured stderr is empty; every real test diagnostic is lost.  Callers
    use this signature to report a native infrastructure abort instead of a
    functional test failure.
    """

    if completed.returncode == 0:
        return False
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return False
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return False
    return not any(_PYTEST_SUMMARY_RE.search(line) for line in lines[-3:])


def _normalize_final_test_node(
    node_id: Any,
    workspace: Path,
    test_files: list[Path],
) -> str:
    """Normalize a Toffee or pytest node to one workspace-relative identity."""

    if not isinstance(node_id, str) or "::" not in node_id:
        raise ValueError("test report contains an invalid pytest node ID")
    value = node_id.strip().replace("\\", "/")
    if value.startswith("TC-"):
        value = value[3:]
    path_value, node_tail = value.split("::", 1)
    path_value = re.sub(r":\d+-\d+$", "", path_value)
    selected = {
        path.resolve(): path.relative_to(workspace).as_posix()
        for path in test_files
    }
    candidate_path = Path(path_value)
    if candidate_path.is_absolute():
        try:
            candidate = candidate_path.resolve()
        except OSError as exc:
            raise ValueError("test report contains an unreadable test path") from exc
        relative = selected.get(candidate)
    else:
        normalized_path = Path(path_value).as_posix().lstrip("./")
        relative = normalized_path if normalized_path in selected.values() else None
        if relative is None:
            suffixes = [
                rel
                for rel in selected.values()
                if normalized_path.endswith("/" + rel)
            ]
            relative = suffixes[0] if len(suffixes) == 1 else None
    if relative is None:
        raise ValueError(f"test report node is outside the selected test files: {node_id}")
    if not node_tail.strip():
        raise ValueError("test report contains an empty pytest node suffix")
    return f"{relative}::{node_tail.strip()}"




def _parse_collected_final_nodes(
    output: str,
    workspace: Path,
    test_files: list[Path],
) -> set[str]:
    """Extract exact node IDs from pytest's collect-only output."""

    nodes: set[str] = set()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "::" not in line or ".py::" not in line:
            continue
        # A parameterized node ID may contain spaces inside ``[...]``.  The
        # collect-only output has one node per line, so preserve the entire line.
        token = line
        try:
            nodes.add(_normalize_final_test_node(token, workspace, test_files))
        except ValueError:
            continue
    return nodes




def _parse_pytest_pass_count(output: str) -> int:
    """Return the passed-node count from the last pytest terminal summary."""

    counts = [
        int(match.group("count"))
        for match in re.finditer(
            r"(?<!\w)(?P<count>\d+)\s+passed\b",
            output,
            flags=re.IGNORECASE,
        )
    ]
    return counts[-1] if counts else 0
