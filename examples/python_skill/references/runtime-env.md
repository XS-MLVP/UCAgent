# Runtime Environment

Use `check_runtime_env.py` before you generate, repair, or smoke-run verification code.

## What must pass

- `python3`
- `picker` executable
- `picker --check` with Python support available
- `import toffee`
- `import toffee_test`
- `import pytest`
- DUT package import (when a DUT name is provided)
- or DUT export readiness (when RTL is provided before export)
- API module import (when a tests directory is provided)
- writable workspace logs directory

## Important interpretation rule

`picker --check` may report missing support for other languages such as Go, Java, or Lua.
For this skill, the blocker is missing **Python** support, not missing support for every language.

## Common failure meanings

### `FAIL picker executable`

- the local picker path is wrong, or
- the file exists but is not executable

### `FAIL picker python support`

- `picker` is installed, but the Python integration is not visible to the current environment

### `FAIL python import toffee` / `toffee_test` / `pytest`

- the package is not installed for the current `python3`, or
- the environment is using the wrong interpreter

### `FAIL dut import {DUT}`

- the DUT package has not been exported yet, or
- the exported package parent is not on `PYTHONPATH`, or
- the export directory name does not match the DUT import name

### `PASS dut export prerequisite {DUT}`

- the DUT is not importable yet, but the RTL path exists and picker export prerequisites are healthy
- this is the expected state before the first export in a fresh workspace

### `FAIL api import {DUT}_api`

- the tests directory is wrong, or
- the DUT package import is still broken inside the API layer

## Recovery order

1. fix PATH for UnityChip tools
2. fix Python package imports
3. export the DUT package with `picker`
4. rerun `check_runtime_env.py`
5. only then continue to contract checks or smoke
