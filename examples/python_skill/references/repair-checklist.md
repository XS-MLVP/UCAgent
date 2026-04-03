# Repair Checklist

Use this checklist when either the RTL-analysis front half is uncertain or the execution back half reports FAIL.

## 0. RTL-analysis review failures

### Symptom

- multiple top-level candidates remain plausible
- the draft `FG/FC/CK` still contains placeholders
- the human has not approved the analysis output yet

### Repair action

- revise the review drafts first
- make uncertainty explicit instead of forcing execution
- do not enter workspace/runtime execution before approval

## 1. Workspace safety failures

### Symptom

- `bootstrap_workspace.py` refuses to initialize the chosen directory
- the target directory already contains generated or user-maintained files

### Repair action

- switch to a fresh disposable path
- preserve maintained trees and keep the workspace for exports/logs only
- keep picker exports under `<workspace>/exports/{DUT}`

## 2. Runtime environment failures

### Symptom

- `check_runtime_env.py` fails on Python, `picker`, `toffee`, `toffee_test`, or `pytest`
- `picker --check` does not show Python support
- logs directory is not writable

### Repair action

- prefix PATH with `/nfs/home/share/unitychip/bin`
- confirm `/nfs/home/share/unitychip/bin/picker --help` and `--check` both work
- ensure `python3 -c "import toffee, toffee_test, pytest"` succeeds
- repair the environment before generating or repairing tests

## 3. DUT export and import failures

### Symptom

- `check_runtime_env.py` reports `FAIL dut import {DUT}`
- `run_smoke_test.py` returns `picker_failure` or `dut_import_failure`
- pytest collection fails with `ModuleNotFoundError: No module named '{DUT}'`

### Repair action

- export the DUT with `picker export` into `<workspace>/exports/{DUT}`
- put `<workspace>/exports` on `PYTHONPATH`
- keep the export directory name equal to the DUT package name expected by `from {DUT} import DUT{DUT}`

## 4. Import discipline failures

### Symptom

- `check_verif_contracts.py` reports a failing API import contract
- tests use `from x import y`, `import env`, or other non-wildcard imports

### Repair action

- change the test file to `from {DUT}_api import *` or the equivalent existing `*_api.py` module
- keep fixtures and helper APIs exported through that module

### Why it matters

The workflow assumes fixtures and helpers are exposed directly from the API file. UCAgent guidance explicitly requires `import *` here.

## 5. Fixture lifecycle failures

### Symptom

- missing `dut` fixture
- no `env` fixture or no stable wrapper around the DUT
- tests recreate setup logic manually

### Repair action

- keep DUT creation inside `create_dut(request)`
- expose a module-scoped `dut` fixture
- expose an `env` fixture or equivalent wrapper for tests

## 6. Coverage wiring failures

### Symptom

- missing `set_func_coverage(...)`
- missing `set_line_coverage(...)` in an API that opts into line-coverage reporting
- no `dut.StepRis(...)` sampling callback
- `fc_cover` is not bound to the DUT instance

### Repair action

- wire coverage setup in the API fixture lifecycle
- ensure teardown exports both function coverage and line coverage
- register `StepRis(...)` before tests run so coverage groups sample during stepping

## 7. FG/FC/CK alignment failures

### Symptom

- tests call `mark_function(...)` with unknown names
- coverage file declares names not present in the markdown doc
- source markdown gained new names that Python files do not reflect

### Repair action

1. re-run `extract_fg_fc_ck.py` on the markdown doc
2. re-run `check_fg_fc_ck_mapping.py`
3. repair the coverage file and tests so they use the canonical names exactly

### Rule

All `FG`, `FC`, and `CK` names must come from `{DUT}_functions_and_checks.md`. If the name is not there, add it there first.

## 8. Step usage failures

### Symptom

- tests or API helpers skip `Step()` because the DUT looks combinational
- coverage never samples because the DUT is not stepped

### Repair action

- keep `env.Step(...)` or `dut.Step(...)` in the execution path
- treat `Step()` as required workflow glue, not as an optional timing detail

## 9. Smoke failure mapping

### `picker_failure`

- inspect the picker export log first
- check PATH and picker support
- verify `--tdir` does not already exist

### `dut_import_failure`

- confirm `<workspace>/exports/{DUT}` exists
- confirm `PYTHONPATH` contains `<workspace>/exports`
- confirm the exported package name matches the import in `*_api.py`

### `pytest_collection_failure`

- repair import errors and syntax errors before debugging test logic
- verify the test node path resolves correctly

### `fixture_failure`

- repair fixture names, scopes, and exports through `*_api.py`
- do not proceed to broader smoke until fixture setup works

### `test_failure`

- this is a real executed test failure
- debug the DUT, API helper, or expected result rather than the toolchain first

## 10. Repair-vs-regenerate rule

Prefer repair when:

- files already exist and contain user edits
- only one or two contracts are broken
- names drifted but the overall structure is valid

Prefer regenerate only when:

- the target directory is empty or disposable
- the current files are pure scaffold output and not manually maintained

## 11. Recheck order

After each repair, rerun checks in this order:

1. `check_runtime_env.py`
2. `check_verif_contracts.py`
3. `run_smoke_test.py`
4. `check_fg_fc_ck_mapping.py`
5. any broader project-specific test command
