
# Python 可执行规格

Python reference 是设计行为的可执行规格，不是返回固定值的 mock。先读取
`Guide_Doc/python_dut_interface.md`，再按 architecture 实现全部端口、状态、reset、transaction、
latency、backpressure、非法输入和 timeout 语义。reference 与 RTL 使用同一个 adapter、API、
fixture、FG/FC/CK 和 pytest；测试不得根据 backend 改变 expected。

只通过 `RunTestCases` 执行已有 pytest 节点。target 相对 `{OUT}/tests`，例如
`test_Adder_functional.py::test_Adder_add_normal`，不能重复 `{OUT}/tests/` 前缀。禁止用
`python -c`、临时脚本或 shell 直接 import reference、adapter、fixture、coverage 或测试模块；
这些执行不是有效回归证据。

## 权威来源与 reference 修正

README、Spec、已确认的 architecture 和 FG/FC/CK 功能合同共同定义外部行为。Python reference
是这些权威需求的可执行实现，不是创建后永久冻结的 oracle。reference 初版通过后，任何后续
阶段如果由需求条文、确定性测试或 Check 诊断证明其功能、状态、reset、时序、非法输入或边界
行为不符合权威合同，都应修正 `{OUT}/tests/{DUT}_reference.py`。同时检查并同步受影响的
adapter、API、fixture、coverage predicate、测试 expected 和文档。

每次 reference 修正后，先用 `RunTestCases` 重新运行直接受影响的 Python 节点，再运行完整
Python 门禁；已经建立 RTL 或 PPA 证据时，还必须让 Check/Complete 用同一套 TC 重新验证 RTL、
性能波形和 PPA。旧测试或证据不能证明新 reference。不得根据当前 DUT/RTL 的失败输出、旧
expected、期望的 PPA 数值或“让测试通过”的目的反推 reference。若 reference 已符合权威合同且
Python 测试通过，而同一节点只在 RTL 下失败，应保持 reference 与 expected 不变并修复 RTL 或
backend adapter。

## 实现步骤

1. 从 architecture 逐项复制端口名称、方向、位宽与 signedness 到 `PIN_SPECS`。
2. 在 `__init__` 初始化全部内部状态；不得读取 wall-clock 或随机全局状态。
3. 在 `_refresh_comb` 只计算组合输出，不推进 cycle 或修改寄存状态。
4. 在 `_step` 只实现一个有效边沿的状态转移，不隐式调用 `_refresh_comb`。
5. 实现 architecture 的 reset 行为，并把 cycle 和全部内部状态恢复到确定值。
6. 在 adapter 中一次写完全部输入后 `RefreshComb()`，需要状态推进时再 `Step(1)` 并再次刷新；
   接受时间在握手采样的 Step 完成后记录，等待循环在每个后续 Step 后立即检查响应；API 参数
   拒绝、事务接受和响应等非静态事件按 `Guide_Doc/python_dut_interface.md` 记录并采样。
7. 每个公开 API 的第一参数固定为 `env`，最后参数固定为正数默认值 `max_cycles=...`，
   docstring 同时包含 `Args:` 和 `Returns:`。API 不得读取底层 DUT、adapter 私有字段或私有
   事件/transaction helper，也不得伪造事件证据。
8. 用 `RunTestCases` 分别运行每个新增测试节点，按权威需求修复 reference/API/fixture 基础设施
   错误；reference 修改后重跑所有受影响节点。

当 Spec 给出离散编码查表时，必须把查表当作规范本身实现，不能根据字段位置、移位或
当前 DUT 输出猜测另一套公式。对每个编码先写出独立的 `code -> value` 表，再用同一张表
实现 reference 的 decode 和测试中的 expected；若输出格式有舍入/饱和，也要在测试中独立
计算并明确检查边界。对于 packed 数据，先从 Spec 写出元素顺序、每元素位宽、最低位元素、
保留位策略和一个完整字面量示例，再实现 pack/unpack。测试注释应同时写出该布局和算术
结果，避免把 byte、bit field 和元素索引混为一谈。

详细 CK 模板之前先实现 `{OUT}/tests/test_{DUT}_smoke.py`。该文件固定包含且只包含
`test_{DUT}_smoke_reset`、`test_{DUT}_smoke_transaction` 和
`test_{DUT}_smoke_invalid` 三个顶层测试：分别验证一个可观察 reset 输出、一个具有独立精确
expected 的合法公开 API transaction，以及一个在 DUT 活动前拒绝的非法公开 API 请求。
transaction smoke 必须使用至少一个可静态识别的非默认数据输入，并用 `==` 将公开 API 结果
与测试中独立写出的非默认精确 expected 比较。全零、全空、复位等价输入，或同样等于复位值的
expected 不能验证算术/数据通路；不要从 DUT 输出计算 expected。smoke 测试不按 backend 分支，
不使用常量断言，并通过 `RunTestCases` 执行；Check 会用 Python
backend 复验，不能用文档自述替代。

## 完整 reference 示例

```python
"""Executable specification for an 8-bit registered incrementer."""

from design_with_ppa import PinSpec, ReferenceDUT


class IncrementerReference(ReferenceDUT):
    """Model reset and one-cycle valid response behavior."""

    PIN_SPECS = (
        PinSpec("clk_i", "input"),
        PinSpec("rst_ni", "input"),
        PinSpec("valid_i", "input"),
        PinSpec("data_i", "input", width=8),
        PinSpec("ready_o", "output"),
        PinSpec("valid_o", "output"),
        PinSpec("data_o", "output", width=8),
    )

    def __init__(self):
        """Initialize deterministic registered state."""

        super().__init__()
        self.response_valid = 0
        self.response_data = 0
        self.RefreshComb()

    def reset(self):
        """Restore the architecture reset state."""

        self.reset_pins()
        self.cycle = 0
        self.response_valid = 0
        self.response_data = 0
        self.RefreshComb()

    def _refresh_comb(self):
        """Drive outputs from current registered state."""

        self.drive_output("ready_o", 1)
        self.drive_output("valid_o", self.response_valid)
        self.drive_output("data_o", self.response_data)

    def _step(self):
        """Apply reset or accept one request at the active edge."""

        if self.rst_ni.value == 0:
            self.response_valid = 0
            self.response_data = 0
            return
        self.response_valid = int(self.valid_i.value and self.ready_o.value)
        if self.response_valid:
            self.response_data = (self.data_i.value + 1) & 0xFF

    def _capture_model_state(self):
        """Capture complete non-pin state for deterministic replay."""

        return (self.response_valid, self.response_data)

    def _restore_model_state(self, state):
        """Restore state returned by _capture_model_state."""

        self.response_valid, self.response_data = state
```

## 完整 API 示例

```python
"""Backend-neutral transaction API for Incrementer."""


def api_Incrementer_increment(env, value, max_cycles=4):
    """Return one incremented response within max_cycles.

    Args:
        env: Active backend-neutral adapter.
        value: Input value to increment.
        max_cycles: Positive simulation-cycle timeout.

    Returns:
        The incremented output value.
    """

    if not isinstance(max_cycles, int) or isinstance(max_cycles, bool) or max_cycles < 1:
        raise ValueError("max_cycles must be a positive integer")
    return env.increment(value, max_cycles=max_cycles)
```

## 完整 smoke 测试示例

```python
"""Executable-spec smoke tests for Incrementer."""

import pytest

from Incrementer_api import api_Incrementer_increment


def test_Incrementer_smoke_reset(env):
    """Verify the specified reset-state outputs."""

    assert env.ready_o.value == 1
    assert env.valid_o.value == 0


def test_Incrementer_smoke_transaction(env):
    """Verify one independently calculated legal transaction."""

    result = api_Incrementer_increment(env, 41, max_cycles=4)
    assert result == 42


def test_Incrementer_smoke_invalid(env):
    """Verify invalid timeout input is rejected before DUT activity."""

    before = (env.data_i.value, env.valid_i.value)
    with pytest.raises(ValueError, match="positive integer"):
        api_Incrementer_increment(env, 1, max_cycles=0)
    assert (env.data_i.value, env.valid_i.value) == before
```

Python 功能测试阶段完成时不得存在 `assert False, "Not implemented"`。所有非 `FG-PPA` 功能 CK 必须由至少一个测试
显式关联，覆盖 predicate 必须真正采样，全部 Python backend pytest 必须 Pass。
