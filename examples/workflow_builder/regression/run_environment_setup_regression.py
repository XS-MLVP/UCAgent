#!/usr/bin/env python3
"""Exercise Workflow Builder's machine-local setup interface."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UCAGENT_ROOT = ROOT.parents[1]
SPEC = importlib.util.spec_from_file_location("workflow_builder_setup", ROOT / "setup.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def main() -> int:
    """Check local settings, validation and virtualenv interpreter identity."""
    with tempfile.TemporaryDirectory() as temporary_dir:
        venv = Path(temporary_dir) / "venv"
        python = venv / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.symlink_to(Path(sys.executable).resolve())
        local_dir = Path(temporary_dir) / ".workflow_builder"
        module.LOCAL_DIR = local_dir
        module.LOCAL_CONFIG = local_dir / "local.mk"
        arguments = [
            "--non-interactive",
            "--set", f"UCAGENT_HOME={UCAGENT_ROOT}",
            "--set", f"UCAGENT_VENV={venv}",
            "--set", f"PYTHON={python}",
            "--set", f"WS={Path(temporary_dir) / 'workspace'}",
            "--set", "WORKFLOW_BUILDER_PROXY_ENABLED=0",
        ]
        assert module.main(arguments) == 0
        assert module.LOCAL_CONFIG.is_file()
        before = module.LOCAL_CONFIG.read_bytes()
        assert module.main(["--show"]) == 0
        assert module.LOCAL_CONFIG.read_bytes() == before, "--show changed the config"
        assert module.main(["--check"]) == 0
        expected_error = io.StringIO()
        with redirect_stderr(expected_error):
            assert module.main(["--check", "--set", "EVAL_UI_PORT=70000"]) == 2
        assert "EVAL_UI_PORT" in expected_error.getvalue()
        saved = module.load_local()
        assert saved["PYTHON"] == str(python), "virtualenv Python symlink was resolved"
        assert saved["WORKFLOW_BUILDER_PROXY_ENABLED"] == "0"
        assert saved["WS"] == str((Path(temporary_dir) / "workspace").resolve())
    print("[PASS] Workflow Builder environment setup regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
