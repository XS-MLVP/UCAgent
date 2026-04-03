# pytoffee Patterns

This guide focuses on how an agent should use core `pytoffee` concepts while building verification code.

The current skill generates UCAgent-style `pytest` fixtures in `*_api.py`, but the same workflow often needs local `toffee` / `toffee_test` syntax guidance. Use this file for `toffee` objects and `toffee-test-quickref.md` for pure `toffee_test` fixture/testcase patterns.

## `Bundle`

Use `Bundle` to group DUT-facing pins into one coherent IO object inside the API layer.
Do this in `*_api.py`, not ad hoc inside every test.

```python
from toffee import Bundle, Signals


class AdderBundle(Bundle):
    a, b, cin, sum, cout = Signals(5)
```

## `Signal` / `Signals`

Use `Signal` or `Signals` declarations to bind named DUT ports into that bundle.
Keep the mapping near the environment definition so tests do not need to rediscover pin names.

```python
class AdderEnv:
    def __init__(self, dut):
        self.dut = dut
        self.io = AdderBundle.from_dict({
            "a": "a",
            "b": "b",
            "cin": "cin",
            "sum": "sum",
            "cout": "cout",
        })
        self.io.bind(dut)
```

## `Env`

Use an environment wrapper to expose the DUT, the bound IO bundle, and common helper methods.
Tests should work through this wrapper instead of rebuilding local helpers.

```python
class AdderEnv:
    def __init__(self, dut):
        self.dut = dut
        self.io = AdderBundle.from_dict({...})
        self.io.bind(dut)

    def Step(self, cycles: int = 1):
        return self.dut.Step(cycles)
```

## `start_clock`

Use `start_clock(dut)` or `dut.InitClock(...)` only when the DUT really has a clocked interface.
For the current UCAgent-style scaffolds, prefer `InitClock` inside `create_dut(...)` when one of the known clock names exists.

```python
from toffee import start_clock

start_clock(dut)
```

## `Agent` and `driver_method`

Use `Agent` when you need a reusable driver API instead of direct signal pokes in every test.

```python
from toffee import Agent, driver_method


class AdderAgent(Agent):
    @driver_method()
    async def drive_add(self, a: int, b: int, cin: int = 0):
        self.bundle.a.value = a
        self.bundle.b.value = b
        self.bundle.cin.value = cin
```

For the current skill, this is an advanced pattern to add **after** the basic API and smoke path work.

## `Model` and `driver_hook`

Use `Model` plus `driver_hook` only when you need a behavioral reference or scoreboarding layer.

```python
from toffee import Model, driver_hook


class AdderModel(Model):
    @driver_hook(agent_name="adder", driver_name="drive_add")
    def expect_add(self, a: int, b: int, cin: int = 0):
        total = a + b + cin
        return total & ((1 << 63) - 1), (total >> 63) & 1
```

Keep this out of the first smoke-test loop unless the project already uses it.

## `Step`

Always keep a `Step()` path in the API or environment layer.
Even when the DUT is combinational, this workflow expects stepping so sampling and execution stay consistent.

```python
def api_Adder_add(env, a: int, b: int, cin: int = 0):
    env.io.a.value = a
    env.io.b.value = b
    env.io.cin.value = cin
    env.Step(1)
    return env.io.sum.value, env.io.cout.value
```

## `StepRis`

Use `StepRis(...)` to register coverage sampling callbacks.
Bind it in the `dut` fixture lifecycle before tests run so coverage groups sample during stepping.

```python
func_coverage_group = get_coverage_groups(dut)
dut.StepRis(lambda _: [group.sample() for group in func_coverage_group])
```

## `CovGroup`

Use `CovGroup` to represent canonical `FG-*` groups.
Each named watch point should represent one `FC-*`, and each check inside that watch point should correspond to `CK-*` items from the markdown doc.

```python
import toffee.funcov as fc


def get_coverage_groups(dut):
    group = fc.CovGroup("FG-API")
    group.add_watch_point(
        dut,
        {"CK-ADD": lambda _: True},
        name="FC-OPERATION",
    )
    return [group]
```

## `mark_function(...)`

Use exact markdown-derived names when marking runtime coverage.

```python
env.dut.fc_cover["FG-API"].mark_function(
    "FC-OPERATION",
    test_basic,
    ["CK-ADD"],
)
```

Do not invent fallback names, wildcards, or translated aliases.

## Practical workflow rules

- Build the API layer first.
- Bind coverage groups in the API fixture lifecycle.
- Mark tests with exact `FG/FC/CK` names through `mark_function(...)`.
- Prefer stable API helpers over direct low-level pokes.
- Prefer `picker`-exported DUT packages placed under `<workspace>/exports/{DUT}`.
- Run one real smoke node before scaling out to random or full-suite tests.
- If names drift, fix the markdown-to-Python mapping before adding more tests.
