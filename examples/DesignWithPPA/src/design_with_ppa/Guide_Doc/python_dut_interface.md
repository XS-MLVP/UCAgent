
# Python DUT 公共接口

Python reference 与 RTL 测试对象必须提供相同的引脚和仿真控制接口。测试不得按 backend
复制逻辑、读取具体 DUT 对象或依赖实现类型。reference 继承 `ReferenceDUT`，用 `PinSpec`
声明 architecture 中的全部端口；adapter 内部通过私有 `_dut.<pin>.value` 读写，并对外
提供定宽 packed 的归一化 pin 值。signed 输入既可写负整数，也可写等宽 packed 位模式。

`create_dut(backend, ReferenceClass)` 是唯一 backend 选择入口。`python` 返回新的 reference；
`rtl` 由 Check/Complete 执行。adapter 不导入具体 DUT 实现，也不根据文件是否存在选择
backend。公开 fixture 只有 `env`，不得声明或使用 `dut` fixture；底层 DUT 只能保留在 adapter
私有字段中。

reference 文件不是永久只读产物。README、Spec、已确认的 architecture 和 FG/FC/CK 才是行为
权威；任何阶段发现 reference 的功能、状态、reset、时序、非法输入或边界实现与这些合同不一致
时，都可以修正 reference，并同步受影响的 adapter/API/fixture/expected 后重新运行 Python 与
RTL 门禁。不得为匹配当前 RTL 输出或让失败用例通过而修改 reference。若 Python 已按权威合同
通过而 RTL 失败，保持 reference 和 expected 不变并修复 RTL/backend。

`conftest.py` 是模板渲染的只读托管文件，工作流已将它设为不可写：不要修改、重写或删除它，也不要在 `{OUT}` 或
`{OUT}/tests` 新建 `pytest.ini`，因为改变 pytest rootdir 会改变性能合同、sidecar 和 Toffee
报告共同使用的精确 node ID。它通过标准 pytest hook 注册托管 backend 选择器和性能 marker，
模板中对应的函数如下（确认其存在与调用即可，不要改写）：

```python
def pytest_addoption(parser):
    """Register the workflow-owned backend selector."""

    register_managed_test_options(parser)


def pytest_configure(config):
    """Register workflow-owned markers without changing the pytest root directory."""

    config.addinivalue_line(
        "markers",
        "performance: deterministic simulation performance case that emits PPA evidence",
    )
```

本文件定义了编写 reference 和 adapter 所需的完整公共接口。只允许从
`design_with_ppa` 导入 `PinSpec`、`ReferenceDUT` 和 `create_dut`；不需要也不得搜索
导入包的实现源码。公开签名如下：

```python
PinSpec(
    name: str,
    direction: str,
    width: int = 1,
    signed: bool = False,
    initial: int = 0,
)

ReferenceDUT(pin_specs: Iterable[PinSpec] | None = None)
create_dut(
    backend: str,
    reference_factory: Callable[[], ReferenceDUT],
) -> Any
```

`direction` 只能是 `"input"`、`"output"` 或 `"inout"`。reference 子类通常声明
`PIN_SPECS` 后调用 `super().__init__()`；只有动态构造端口时才向基类传 `pin_specs`。
reference 子类可实现 `_refresh_comb()`、`_step()`、`_capture_model_state()` 和
`_restore_model_state(state)`，并可调用 `reset_pins()` 与
`drive_output(name, value)`。adapter 可调用的 DUT 控制方法完整集合为：

`PIN_SPECS` 创建的 `self.<pin>` 是不可替换的 `ReferencePin` 对象。输入引脚写入必须使用
`self.<pin>.value = value`；输出引脚在 reference 内必须使用
`self.<pin>.value = value` 或 `self.drive_output("<pin>", value)`。禁止写
`self.<pin> = value`，这会替换引脚对象并在初始化或运行时失败。

```python
GetXPort()
InitClock(name: str)
RefreshComb()
Step(count: int = 1)
CheckPoint(name: str)
Restore(name: str)
SetCoverage(filename)
GetCovMetrics()
SetWaveform(filename)
ResumeWaveformDump()
PauseWaveformDump()
WaveformPaused()
GetWaveFormat()
FlushWaveform()
Finish()
```

初始 Python 接口子阶段只实现 reference、adapter、API 和 fixture。其它接口和产物属于后续
阶段，不读取、不导入，也不自行推断；这个产物分工不表示 reference 在后续阶段被冻结。

architecture 声明一个或多个时钟时，adapter 必须在 `GetXPort().AsImmWrite()` 之后按端口原名
调用 `InitClock`，并且早于 artifact 绑定、reset 或任何 `Step`。每个时钟只注册一次。纯组合
设计没有时钟，不得虚构时钟或调用 `InitClock`。Python reference 和 RTL 对象必须走同一段
adapter 初始化代码。

对外 transaction API 使用 `api_{DUT}_*` 名称。每个公开 API 的第一参数固定为 `env`，最后
参数固定为带正数默认值的 `max_cycles`，docstring 必须同时包含 `Args:` 和 `Returns:`。不等待
响应的 API 也保留该参数，使 Python reference 与 RTL 测试对象共享完全一致的调用合同。

## 仿真顺序

一次事务必须按以下顺序执行：

```text
写完所有立即输入
-> RefreshComb()
-> 可选：读取边沿前组合输出
-> Step(1)
-> RefreshComb()
-> 读取边沿后输出
```

`RefreshComb()` 不推进 cycle；`Step()` 不隐式刷新组合输出。纯组合设计写完全部输入后调用一次
`RefreshComb()` 即可读取结果。时序设计不得在第一次刷新前 `Step()`，否则边沿可能采样上一组
组合结果。

握手事务的接受时间必须在采样 `valid && ready` 的 `Step(1)` 完成后记录。响应 latency 是响应
边沿时间减去该接受边沿时间，不包含接受前的驱动区间。等待循环应先执行下一边沿并刷新，再
检查响应；因此第 `max_cycles` 个允许边沿也会被检查。adapter 保存最近一次成功事务的
`last_transaction_timing = (accepted_at, response_at)`，性能测试直接使用该仿真时间对。
adapter 同时公开只读使用语义的整数 `cycle`，初值为 0；每次实际执行一个底层 `Step` 后恰好
增加 1。transaction 事件中的接受/响应周期和 `cycle_state` 都必须引用该统一属性，不能读取
backend 私有对象的 cycle 字段。

API 不得在结果周期中途返回。观察到响应后先保存结果与 `response_at`、记录
`response_observed`，再按 architecture 推进到下一笔事务可接受的 re-arm 状态（例如
`ready_o=1` 且 `valid_o=0`），最后才返回已保存的结果。re-arm 的额外 `Step` 不计入已保存
latency，也不得覆盖最后的 `response_observed` 事件。连续调用同一个公开 API 必须能够连续
提交合法事务，测试不应为每笔正常事务 reset 环境。

## Backend-neutral 事件证据

有些可观察行为不能由合法硬件引脚的静态值表达。例如，host API 拒绝超出 1-bit 范围的
参数时，异常必须在写任何引脚和执行 `Step` 之前发生；此时不能把非法值强行写入引脚来命中
覆盖。握手接受也只发生在特定边沿，不能用事务结束后的 `ready_o` 状态反推。

adapter 必须用公开只读语义的 `last_event` 和 `last_event_data` 保存这类 backend-neutral
事件，并在真实事件发生的位置通过私有 `_record_event()` 采样覆盖。事件名使用稳定的
snake_case 字符串，数据只包含两个 backend 都能产生的确定性标量。至少按当前功能合同记录：

- API 参数拒绝前记录 `api_validation_error`，`last_event_data` 包含 `field` 和 `reason`；
- `valid && ready` 被有效边沿采样后记录 `transaction_accepted`，数据至少包含递增的
  `transaction_id`、`accepted_at` 和能区分当前操作/模式/精度的确定性标量；
- transaction 尚未完成但需要覆盖真实等待、backpressure 或 pipeline 状态时，在对应
  `RefreshComb()` 或 `Step()` 后调用 `_record_transaction_observation()`；数据包含原始接受
  identity、`observed_at`、稳定 `phase` 以及当时真实读取的状态标量；
- 响应被观察到时调用 `_record_response_observed()`；它必须自动合并原始接受 identity，
  再附加 `response_at`、latency 和有界结果摘要，并从 active transaction 表中移除该项；
- reset 相关 CK 需要事件语义时，在相应 reset 边沿记录事件。

每个已接受 transaction 的 operation、mode、precision 和输入摘要只在接受点登记一次，随后由
adapter 的私有不可变映射传递给 observation 和 response。不存在的 transaction ID 必须拒绝，
response 完成后同一 ID 也必须拒绝；不能由测试或事后输出反推、补写请求 identity。

不得调用 `_record_event()` 或任何私有 `_record_transaction_*`/`_record_response_observed()`
helper，不得读取 active transaction 表、修改 `last_event`、访问 `_dut` 或向硬件 pin 写入不可
表示的值来制造覆盖。pin 可直接表达的数值/状态条件仍优先读取公开 `env.<pin>.value`，不必
全部改成事件。

公开 API 的参数校验应委托给 adapter 的事务入口，使 adapter 在抛出 `TypeError` 或 `ValueError`
之前记录 `api_validation_error`；API 层不要先复制一套校验并直接抛异常，否则非法输入虽然会
失败，却无法留下两个 backend 共用的事件证据。测试通过共享 API 发起该非法输入并用
`pytest.raises` 检查异常，再读取 `env.last_event` 和 `env.last_event_data`。

`transaction_accepted` 和 `response_observed` 的 coverage predicate 必须同时读取
`last_event_data` 中能区分当前 CK 的字段。仅判断事件名会让多个行为无差别命中，不能作为
CK-specific coverage。不同 CK 不能复用归一化后完全相同的 predicate。

当同一笔事务包含多个可观测阶段时，adapter 必须在真实动作点记录可区分的阶段证据，不能
让所有 CK 都复用一个 `response_observed` 条件。组合/累加阶段应在等待期间记录
`transaction_observation`，其 `phase` 使用稳定值（例如 `accumulating` 或
`waiting_response`）；结果转换应在 `response_observed` 中附带 `conversion_kind`（只能是
`normal`、`rounded`、`saturated` 或 `underflow` 等实际发生的值）和结果摘要；精确消除或
带符号零应附带 `zero_kind`（例如 `cancellation` 或 `underflow`）；无下游反压的单周期
`valid_o` 应附带真实测得的 `valid_pulse_width`。coverage predicate 应分别读取这些字段，
例如 `phase == "accumulating"`、`conversion_kind == "saturated"`、
`zero_kind == "cancellation"`、`valid_pulse_width == 1`。只有在测试确实触发相应场景时才
记录对应值；不得用常量、事务 ID 算术或恒真条件伪造差异。

## 完整 reference 示例

```python
"""Pin-compatible executable specification for Adder."""

from design_with_ppa import PinSpec, ReferenceDUT


class AdderReference(ReferenceDUT):
    """Model one-cycle valid/ready modular addition."""

    PIN_SPECS = (
        PinSpec("clk_i", "input"),
        PinSpec("rst_ni", "input"),
        PinSpec("valid_i", "input"),
        PinSpec("ready_o", "output"),
        PinSpec("a_i", "input", width=8),
        PinSpec("b_i", "input", width=8),
        PinSpec("valid_o", "output"),
        PinSpec("sum_o", "output", width=8),
    )

    def __init__(self):
        """Initialize registered response state."""

        super().__init__()
        self.pending_valid = 0
        self.pending_sum = 0
        self.RefreshComb()

    def reset(self):
        """Restore pins, cycle, and registered state."""

        self.reset_pins()
        self.cycle = 0
        self.pending_valid = 0
        self.pending_sum = 0
        self.RefreshComb()

    def _refresh_comb(self):
        """Expose outputs from the current registered state."""

        self.drive_output("ready_o", 1)
        self.drive_output("valid_o", self.pending_valid)
        self.drive_output("sum_o", self.pending_sum)

    def _step(self):
        """Capture one accepted request at the active edge."""

        if self.rst_ni.value == 0:
            self.pending_valid = 0
            self.pending_sum = 0
            return
        self.pending_valid = int(self.valid_i.value and self.ready_o.value)
        if self.pending_valid:
            self.pending_sum = (self.a_i.value + self.b_i.value) & 0xFF

    def _capture_model_state(self):
        """Return all state needed by CheckPoint/Restore."""

        return {
            "pending_valid": self.pending_valid,
            "pending_sum": self.pending_sum,
        }

    def _restore_model_state(self, state):
        """Restore state emitted by _capture_model_state."""

        self.pending_valid = state["pending_valid"]
        self.pending_sum = state["pending_sum"]
```

## 完整 adapter 示例

```python
"""One backend-neutral adapter for Adder."""

from pathlib import Path
from types import MappingProxyType

from design_with_ppa import create_dut, prepare_native_artifact_path
from Adder_reference import AdderReference


class AdderAdapter:
    """Drive either implementation through one transaction contract."""

    def __init__(self, backend):
        """Create the selected DUT and enable immediate pin writes."""

        self.backend = backend
        self._dut = create_dut(backend, AdderReference)
        self._dut.GetXPort().AsImmWrite()
        self._dut.InitClock("clk_i")
        self._public_pin_names = frozenset(
            spec.name for spec in AdderReference.PIN_SPECS
        )
        self.coverage_groups = []
        self.waveform_path = None
        self.cycle = 0
        self.sim_time_ns = 0
        self.last_transaction_timing = None
        self._next_transaction_id = 1
        self._active_transactions = {}
        self._last_event = "initialized"
        self._last_event_data = MappingProxyType({})

    def __getattr__(self, name):
        """Expose only declared pins through the public environment surface."""

        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._public_pin_names:
            return getattr(self._dut, name)
        raise AttributeError(name)

    @property
    def last_event(self):
        """Return the latest backend-neutral observable event name."""

        return self._last_event

    @property
    def last_event_data(self):
        """Return immutable scalar evidence for the latest event."""

        return self._last_event_data

    def configure_test_artifacts(self, coverage_path, waveform_path):
        """Bind unique RTL artifacts before reset or the first Step."""

        if self.backend != "rtl":
            return
        # Native writers abort the whole process when an artifact path cannot
        # be opened, silently swallowing all pending pytest diagnostics; both
        # paths must be validated and their parent directories created on the
        # Python side before reaching the native runtime.
        self.coverage_path = prepare_native_artifact_path(coverage_path, "coverage")
        self.waveform_path = prepare_native_artifact_path(waveform_path, "waveform")
        self._dut.SetCoverage(str(self.coverage_path))
        self._dut.SetWaveform(str(self.waveform_path))
        self._dut.ResumeWaveformDump()

    def bind_coverage(self, groups):
        """Bind the same coverage groups in both modes."""

        self.coverage_groups = list(groups)
        self.fc_cover = {group.name: group for group in groups}

    def _record_event(self, event, **data):
        """Publish and sample one event produced by a real adapter action."""

        if not isinstance(event, str) or not event:
            raise ValueError("coverage event must be a non-empty string")
        self._last_event = event
        self._last_event_data = MappingProxyType(dict(data))
        self.sample_coverage()

    def _record_transaction_accepted(self, accepted_at, **identity):
        """Record one accepted request with operation-specific scalar identity."""

        if not identity:
            raise ValueError("accepted transaction evidence requires identity fields")
        reserved = {"transaction_id", "accepted_at", "observed_at", "response_at"}
        if reserved.intersection(identity):
            raise ValueError("accepted transaction identity uses a reserved field")
        transaction_id = self._next_transaction_id
        self._next_transaction_id += 1
        evidence = {
            "transaction_id": transaction_id,
            "accepted_at": accepted_at,
            **identity,
        }
        self._active_transactions[transaction_id] = MappingProxyType(evidence)
        self._record_event("transaction_accepted", **evidence)
        return transaction_id

    def _record_transaction_observation(
        self, transaction_id, observed_at, phase="inflight", **state
    ):
        """Record real in-flight state while retaining accepted-request identity."""

        accepted = self._active_transactions.get(transaction_id)
        if accepted is None:
            raise ValueError("transaction observation refers to an unknown transaction")
        if not isinstance(phase, str) or not phase:
            raise ValueError("transaction observation phase must be a non-empty string")
        reserved = set(accepted) | {"observed_at", "phase", "response_at"}
        if reserved.intersection(state):
            raise ValueError("transaction observation state overwrites identity")
        evidence = {
            **accepted,
            "observed_at": observed_at,
            "phase": phase,
            **state,
        }
        self._record_event("transaction_observation", **evidence)

    def _record_response_observed(self, transaction_id, response_at, **result):
        """Record a response with its accepted identity, then retire the request."""

        accepted = self._active_transactions.pop(transaction_id, None)
        if accepted is None:
            raise ValueError("response refers to an unknown transaction")
        reserved = set(accepted) | {"observed_at", "phase", "response_at"}
        if reserved.intersection(result):
            raise ValueError("response result overwrites accepted transaction identity")
        evidence = {**accepted, "response_at": response_at, **result}
        self._record_event("response_observed", **evidence)

    def _drive(self, *, rst_ni, valid_i, a_i, b_i):
        """Write one complete input set, then evaluate combinational logic."""

        self._dut.rst_ni.value = rst_ni
        self._dut.valid_i.value = valid_i
        self._dut.a_i.value = a_i
        self._dut.b_i.value = b_i
        self._dut.RefreshComb()

    def _step(self):
        """Advance one cycle and refresh outputs driven by new state."""

        self._dut.Step(1)
        self.cycle += 1
        self.sim_time_ns += 1
        self._dut.RefreshComb()

    def reset(self):
        """Apply the architecture reset sequence."""

        self._drive(rst_ni=0, valid_i=0, a_i=0, b_i=0)
        self._step()
        self._record_event("reset_asserted")
        self._drive(rst_ni=1, valid_i=0, a_i=0, b_i=0)
        self._step()
        self._record_event("reset_released")

    def add(self, a, b, max_cycles=4):
        """Run one request and return its bounded response."""

        if not isinstance(max_cycles, int) or isinstance(max_cycles, bool) or max_cycles < 1:
            self._record_event(
                "api_validation_error", field="max_cycles", reason="not_positive_integer"
            )
            raise ValueError("max_cycles must be a positive integer")
        for field, value in (("a", a), ("b", b)):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 255:
                self._record_event(
                    "api_validation_error", field=field, reason="outside_unsigned_8_bit"
                )
                raise ValueError(f"{field} must be an 8-bit unsigned integer")
        self.last_transaction_timing = None
        self._drive(rst_ni=1, valid_i=1, a_i=a, b_i=b)
        if not self._dut.ready_o.value:
            self._record_event("request_blocked")
            raise TimeoutError("request was not accepted")
        self._step()
        accepted_at = self.sim_time_ns
        transaction_id = self._record_transaction_accepted(
            accepted_at,
            operation="add",
            a=a,
            b=b,
        )
        self._drive(rst_ni=1, valid_i=0, a_i=0, b_i=0)
        if self._dut.valid_o.value:
            self.last_transaction_timing = (accepted_at, self.sim_time_ns)
            result = self._dut.sum_o.value
            self._record_response_observed(
                transaction_id,
                self.sim_time_ns,
                latency_cycles=self.sim_time_ns - accepted_at,
                result=result,
            )
            self._step()
            if not self._dut.ready_o.value or self._dut.valid_o.value:
                raise TimeoutError("unit did not re-arm after response")
            return result
        for _ in range(max_cycles):
            self._step()
            if self._dut.valid_o.value:
                self.last_transaction_timing = (accepted_at, self.sim_time_ns)
                result = self._dut.sum_o.value
                self._record_response_observed(
                    transaction_id,
                    self.sim_time_ns,
                    latency_cycles=self.sim_time_ns - accepted_at,
                    result=result,
                )
                self._step()
                if not self._dut.ready_o.value or self._dut.valid_o.value:
                    raise TimeoutError("unit did not re-arm after response")
                return result
            self._record_transaction_observation(
                transaction_id,
                self.sim_time_ns,
                phase="waiting_response",
                ready=int(self._dut.ready_o.value),
                valid=int(self._dut.valid_o.value),
            )
        raise TimeoutError("response timeout")

    def sample_coverage(self):
        """Sample functional coverage after an observable transaction."""

        for group in self.coverage_groups:
            group.sample()

    def flush_waveform(self):
        """Flush real RTL activity before writing its sidecar."""

        if self.backend == "rtl":
            self._dut.FlushWaveform()

    def finish(self):
        """Release per-test resources."""

        for group in self.coverage_groups:
            group.clear()
        self._dut.Finish()


def create_adapter(backend):
    """Create the implementation selected by the pytest fixture."""

    return AdderAdapter(backend)
```

所有 reference 内部状态必须可确定性重置。若测试会调用 `CheckPoint/Restore`，reference 还必须
通过 `_capture_model_state` 与 `_restore_model_state` 保存、恢复全部非引脚状态。禁止用真实
wall-clock 代表硬件时间。
