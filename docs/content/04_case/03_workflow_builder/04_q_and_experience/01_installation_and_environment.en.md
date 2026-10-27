
# Installation and Environment Issues

## Missing UCAgent or Python

**Symptom**: `make` reports that `ucagent.py` is missing, Python is not executable, or importing `examples.workflow_builder` fails.

**Impact**: Workflows cannot start; this is a blocking issue that must be resolved before execution.

**Verification Method**:

```bash
python setup.py --show
python setup.py --check
test -f "$UCAGENT_HOME/ucagent.py"
test -x "$UCAGENT_VENV/bin/python"
```

**Resolution Steps**: Re-run `python setup.py` in the root directory to configure the actual UCAgent source and virtual environment paths. Command-line overrides can be used temporarily for validation, but permanent values should be saved in local configuration. Do not write absolute paths from a specific machine into the public config or GuideDoc.

**Prevention**: After migrating machines, run `make configure-check` in the root directory before starting the business workspace.

## Relationship between `ucagent_env` and setup.py

`ucagent_env` is typically a function already present in the user's shell, used to activate PATH, PYTHON, and PYTHONPATH. The Workflow Builder root `setup.py` saves the native default paths required by the Makefile into `.workflow_builder/local.mk`. These two can coexist; `setup.py` does not write to `~/.bashrc`, so it does not permanently inject environment variables into the parent shell.

Another `setup.py` located in the workflow root directory (`workflow/setup.py`) configures the business workflow execution environment. Before execution, it is necessary to distinguish between the two programs using `pwd`.

## Connection Failures After Proxy Enablement

**Possible Causes**: Incorrect proxy address, missing credentials, server disconnection, inherited incompatible `ALL_PROXY`, oversized model requests, or proxy instability.

**Verification Method**: Check the `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` actually inherited by the current process; perform a short request using the same environment; compare results with and without the proxy. Do not assume the issue is unrelated to request size or the server simply because the network changed.

Local configuration rejects saving URLs with embedded credentials. When authentication is required, set it in the current shell or a secrets management system; do not write it to the version control system or document screenshots.

## Missing Ports or Tool Dependencies

MCP and console ports must be between 1 and 65535. System tools like tmux, LibreOffice, and Verilator must be checked using their respective version commands. Missing business tools should be reported by the `requirements.txt` and environment documentation generated when creating the workflow, not by Workflow Builder attempting to install unknown system packages.

## Mixing Virtual Environment and System Python

**Symptom**: A regression can run via the root `make regression`, but direct `python3` fails due to `typing.NotRequired`, langgraph, or missing packages.

**Verification Method**: Compare `which python3`, `$UCAGENT_VENV/bin/python --version`, and the `sys.path` of both. The root regression passes the venv Python, but manually entering the regression directory may revert to the system interpreter.

**Resolution**: Explicitly execute `make -C regression PYTHON="$UCAGENT_VENV/bin/python" <target>`. Do not modify business Checkers based on interpreter dependency errors.

## Local Configuration Not Taking Effect

Use `make configure-show` to check saved values, then observe expansion with `make -n WS=... run`. Command-line variables take precedence over local configuration; if local files are manually corrupted, re-run `python setup.py` rather than directly editing Make syntax.

## Proxy Credentials and Business Dependencies

`setup` rejects saving proxy URLs containing account and password. Secrets are injected via the runtime environment and must ensure tmux inheritance. Clear tokens and authentication URLs before sharing logs. "Command exists" only proves installation, not that the version and functionality meet requirements; business setup/check should also verify version and key capabilities.
