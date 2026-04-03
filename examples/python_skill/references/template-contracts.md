# Template Contracts

This document defines the **minimum contracts** for the three core verification files.

## Strong constraints

These are required for the MVP loop.

### `*_api.py`

Required items:

- `create_dut(request)` exists
- `dut` fixture exists
- teardown calls `set_func_coverage(...)`
- teardown calls `set_line_coverage(...)` when the API file opts into line-coverage reporting
- imports `get_coverage_groups` from `*_function_coverage_def.py`
- calls `dut.StepRis(...)` so coverage groups can sample during stepping
- exposes an `env` fixture or equivalent wrapper used by tests

Workflow rules:

- keep a stable API layer instead of forcing tests to poke low-level signals everywhere
- even for combinational DUTs, drive the design with `Step()` for a consistent flow
- prefer keeping coverage wiring in the API fixture lifecycle, not inside each test

### `*_function_coverage_def.py`

Required items:

- `get_coverage_groups(dut)` exists
- declared `FG`, `FC`, and `CK` names come from the source markdown only
- coverage groups are built with `CovGroup`
- each `FC` is represented through a named watch point

Workflow rules:

- `FG-API` should exist when the source markdown defines API-facing behavior
- if a name is missing from the markdown, add it to the markdown first instead of inventing it in Python
- treat the markdown doc as canonical and the coverage file as a faithful projection of it

### `test_*.py`

Required items:

- imports through `from <something>_api import *`
- calls `mark_function(...)`
- uses names that exist in both the markdown doc and the coverage file
- advances the DUT through `env.Step(...)` or an equivalent API-driven step path

Workflow rules:

- `from *_api import *` is mandatory because the workflow expects the API layer to expose fixtures and helpers directly
- do not bypass the API layer unless you are actively defining or repairing that layer
- bind each test to the exact `FG/FC/CK` tuple it is validating

## Recommended patterns

These are not strict MVP gates, but they are the intended direction.

- wrap DUT pins with `Bundle` / `Signals` in the API layer
- keep one clear API helper per major DUT action
- keep coverage group initialization centralized in `get_coverage_groups(dut)`
- keep generated templates parameterized and project-local

## Repair boundary

If a file violates any strong constraint, repair that file first.
Do **not** keep generating more tests, templates, or reports on top of a broken base.
