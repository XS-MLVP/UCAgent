"""Production dependencies cannot reintroduce a Python debugger or UI-owned runtime."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_has_no_debugger_imports_or_thread_exception_injection():
    """Inspect all production Python without excluding feature directories."""
    offenders = []
    for path in (ROOT / "ucagent").rglob("*.py"):
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Unrendered workflow Python templates contain Jinja identifiers.
            assert "{{" in source and "templates" in path.parts, path
            assert not any(token in source for token in ("import pdb", "import bdb", "verify_pdb", "PyThreadState_SetAsyncExc")), path
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            if any(name.split(".")[0] in {"pdb", "bdb"} or "verify_pdb" in name for name in names):
                offenders.append(f"{path}:{node.lineno}")
        if "PyThreadState_SetAsyncExc" in path.read_text():
            offenders.append(str(path))
    assert not offenders
    assert not (ROOT / "ucagent/verify_pdb.py").exists()


def test_runtime_host_has_no_concrete_frontend_imports():
    """The lifetime owner receives its frontend and HTTP construction dependencies."""
    tree = ast.parse((ROOT / "ucagent/runtime/host.py").read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and (name.startswith("ucagent.interfaces.terminal.tui") or name.startswith("ucagent.interfaces.server")) for name in imports)
