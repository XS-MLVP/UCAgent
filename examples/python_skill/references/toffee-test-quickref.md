# Toffee-Test Quick Reference

This file focuses on the minimum syntax an LLM usually needs but often misremembers.

## Two modes in this skill

### Mode A — Current UCAgent-style scaffold

The generated templates stay `pytest`-fixture based:

```python
import pytest


@pytest.fixture(scope="module")
def dut(request):
    ...


@pytest.fixture()
def env(dut):
    ...
```

Use this mode when you are following the existing FG/FC/CK scaffold and contract checker.

### Mode B — Pure `toffee_test` fixture/testcase style

Use this when the target project already follows Toffee's own fixture/testcase flow.

```python
import toffee_test


@toffee_test.fixture
def dut(toffee_request):
    from Adder import DUTAdder
    return toffee_request.create_dut(DUTAdder)


@toffee_test.testcase
async def test_smoke(dut):
    dut.Step(1)
```

## API names confirmed in the local installation

- `toffee_test.fixture`
- `toffee_test.testcase`
- `ToffeeRequest.create_dut(...)`
- `ToffeeRequest.add_cov_groups(...)`
- `ToffeeRequest.finish(...)`

## Typical `create_dut(...)` pattern

```python
@toffee_test.fixture
def dut(toffee_request):
    from Adder import DUTAdder
    return toffee_request.create_dut(
        DUTAdder,
        clock_name=None,
        waveform_filename=None,
        coverage_filename=None,
    )
```

If your DUT has a clock, pass the actual clock signal name.

## Smoke command patterns

### Minimal pytest node

```bash
PYTHONPATH=/tmp/pytoffee_skill_ws/exports:../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests:$PYTHONPATH \
pytest -q ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests/test_Adder_api_basic.py::test_api_Adder_add_zero_values
```

### Toffee report mode

```bash
pytest -q test_demo.py::test_smoke --toffee-report
```

Use report mode only when the local project already expects it.

## Common syntax traps

- Do not mix up `pytest.fixture` and `toffee_test.fixture` blindly; keep the project's existing style.
- Do not assume the DUT package is magically importable; export it first or fix `PYTHONPATH`.
- Do not skip stepping just because the DUT is combinational.
- Do not write `mark_function(...)` names that are not present in the markdown spec.
