
# RTL 测试 Backend

你只维护工作流选定语言的 `{RTL_SOURCE_GLOB}`、Python reference、统一 adapter/API/fixture
和测试。不同 backend 的 DUT 都由 `create_dut(backend, ReferenceClass)` 创建；adapter 不导入
具体 DUT 实现。公开 fixture 只有 `env`，不得声明或使用 `dut` fixture；底层 DUT 只能保留在
adapter 私有字段中。修改当前语言源码后调用 Check/Complete，并用同一套 pytest 验证行为。

公开 `RunTestCases` 只运行 reference 路径。不要手动切换实现、添加 backend 选项或直接
import 测试模块模拟执行。RTL 功能回归、性能执行和波形收集由 Check/Complete 在托管运行时
触发；测试始终只面向统一的 `env`。

Python reference 是 README、Spec、architecture 和 FG/FC/CK 的可执行实现，而不是不可修改的
黄金文件。若同一节点的 Python 执行或需求核对证明 reference 的功能、状态或时序实现错误，先
修正 reference 和受影响的共享测试产物，再用 `RunTestCases` 通过 Python 路径并由 Check 重跑
RTL。若 Python reference 已按权威合同通过而 RTL 失败，保持 reference 和 expected 不变，只
修复当前 RTL 源码或 backend adapter。已有 RTL/PPA 证据在 reference 改动后必须重新生成。

## RTL 源码注释建议

实现当前选定语言的源码时，建议在每个文件和主要 module/class 的开头说明功能目的、总体数据
流和组合/时序性质；每个端口和参数旁说明方向、类型、位宽、signedness、协议/编码含义、合法
范围以及对 latency 或资源的影响。clock/reset 和核心数据通路前应说明边沿、极性、同步语义、
状态转移、握手/backpressure、宽度转换、舍入/饱和/溢出和非法输入处理。注释是可读性建议，不
是独立风格门禁；必须和 architecture、Python executable spec 及实际源码保持一致。合理偏离时
在源码附近记录 `RTL-GUIDE-DEVIATION`、原因、范围和验证依据，不要记录中间语言或内部构建细节。

## 立即写入与组合刷新

`GetXPort().AsImmWrite()` 使 `.value` 赋值立即更新端口存储，但不会执行组合逻辑。一次事务
必须先写完所有输入，再统一刷新：

```text
写完当前事务的全部立即输入
-> RefreshComb()          # 立即输入驱动的组合逻辑
-> 读取需要的边沿前组合状态
-> Step(1)                # 延迟一个周期的时序逻辑
-> RefreshComb()          # 新寄存状态驱动的组合输出
-> 读取边沿后输出
```

逐引脚刷新会暴露无意义的中间输入组合；首次刷新前 `Step(1)` 会让时序逻辑看到上一组组合
结果。纯组合设计只需写完输入后 `RefreshComb()`，不能用 `Step(1)` 代替刷新；反过来，
`RefreshComb()` 也不能代替 `Step(1)` 来推进有延迟的时序事务。

时序或混合设计还必须为 architecture 中的每个时钟调用一次 `InitClock("<原端口名>")`。
调用位置固定在 `GetXPort().AsImmWrite()` 之后、artifact 绑定、reset 和首次 `Step` 之前。遗漏
时钟注册时，`Step` 可能只推进仿真而不产生设计所需的有效边沿。纯组合设计不调用
`InitClock`。

## 握手与等待边界

握手接受时间在采样 `valid && ready` 的 `Step(1)` 完成后记录。后续 latency 从该接受边沿
开始计算，不包含接受前的驱动区间。等待循环必须在每个后续 `Step(1)` 和组合刷新之后检查
响应，使第 `max_cycles` 个允许边沿也会被观察；成功时保存
`last_transaction_timing = (accepted_at, response_at)` 供性能测试使用。
adapter 还必须公开统一整数 `cycle`：初值为 0，每执行一个底层 `Step` 后增加 1。接受/响应事件
以及观测合同中的 `cycle_state` 只读取该属性，不读取 backend 私有对象的 cycle 字段。

观察到响应后，adapter 必须先保存结果、响应时间并记录 `response_observed`，再按 architecture
推进完结果周期，直到接口重新满足下一笔事务的接受条件（例如 `ready_o=1` 且 `valid_o=0`），
然后才向 API 调用者返回。re-arm 使用的额外 `Step` 不得改变已保存的 `response_at`、latency
或最后的 `response_observed` 事件。这样同一个 `env` 可以连续发起多笔合法事务；不能要求每笔
事务前 reset，也不能让上一笔结果周期导致下一笔请求被误判为 blocked。

瞬时事件不能由事务结束后的 pin 快照代替。adapter 在真正的接受边沿记录
`transaction_accepted`，数据包含 transaction ID、仿真时间和操作/模式/精度等 CK-specific
标量并存入私有不可变 active transaction 表；在真实 post-refresh/post-step 等待或 backpressure
观察点记录 `transaction_observation`；在观察到响应时自动合并原接受 identity、latency 与结果
摘要到 `response_observed`，随后移除 active 项；API 在写 pin 或 Step 前
拒绝非法参数时记录 `api_validation_error`。这些事件通过公开 `last_event` 和
`last_event_data` 供 Python/RTL 共用 coverage predicate 读取，并由 adapter 的私有
`_record_event()` 在事件发生时立即采样。测试不得直接调用该方法、transaction helper、读取
active transaction 表或修改事件字段。完整规则和
非法 API 示例见 `Guide_Doc/python_dut_interface.md` 的“Backend-neutral 事件证据”。

## 波形生命周期

fixture 必须在 reset 或任何 `Step` 之前为 RTL DUT 调用 `SetCoverage`、`SetWaveform` 和
`ResumeWaveformDump`。每个性能 TC 使用由 `get_performance_waveform_path(request)` 得到的唯一
路径。TC 固定 observation window 完成后先 `FlushWaveform()`，再调用
`write_performance_result()`。fixture 收尾也必须在 `Finish()` 之前执行一次幂等的
`FlushWaveform()`；普通功能 TC 不需要额外 flush，由 `Finish()` 关闭仿真资源；不得在
`Finish()` 之后再次调用原生波形 API。覆盖率注册有明确的顺序：先调用
`set_func_coverage(request, groups)` 保存功能覆盖，再调用 `adapter.finish()` 让 native
runtime 写完 `.dat`，最后调用 `set_line_coverage(request, coverage_path, ignore=...)` 将已完成的
文件交给 Toffee。不能在 `Finish()` 前注册行覆盖，也不能省略 `set_line_coverage()`；Python
reference 不产生 RTL 波形或行覆盖文件。

`rtl_shared_regression` 的失败诊断会给出 `rtl_debug.test_target`、可直接传回 Check 的
`rtl_debug.targeted_check`、以及 `rtl_debug.waveform_test_case_name`。先用定向 Check 只复验这
一个节点；若 `waveform_retained=true`，再把 `waveform_test_case_name` 原样传给 WaveInfo。
失败 RTL 运行的最新临时波形会保留用于诊断，通过的临时运行会自动清理。不要通过
RunTestCases 尝试生成 RTL 波形，也不要手写全量 regression report；最终报告只由不带 target
的 Complete 在全量用例通过后生成。

## RTL 调试方法

调试按“定向复验 → 波形定位 → 最小修复”的循环进行：先用 `rtl_debug.targeted_check`
只复验第一个失败节点，定位出第一个错误值后只修一处，再复验。没有证据指向具体信号之前
不要猜测性改动 RTL。

### WaveInfo 三步定位

1. 无参数调用 `WaveInfo`，列出最新 `toffee_tmp_*` session 的波形清单与元数据，确认失败
   节点对应的波形文件存在。
2. 用诊断中的 `rtl_debug.waveform_test_case_name` 作为 `test_case_name` 再次调用。不带
   `pattern` 时返回元数据与信号目录；需要查事件时用结构化 `pattern` 条目：`signal` 支持
   wavekit 语法的精确点分路径、`*`、`**`、`/{regex}/` 与 `{}` 备选/范围，`event` 可选
   `change`、`rising`、`falling`、`equals`（`equals` 必须带 `value`，接受整数或 Verilog
   字面量如 `8'hff`）。先筛 clock/reset、握手 valid/ready、打包输入、输出，以及第一个
   错误值相关的内部信号。
3. 拿到事件时间点后，用 `start_step`/`end_step` 显式窗口，或 `logged_cycle` 加精确
   `clock_signal`（配合 `clock_edge`、`cycle_origin`）把测试日志周期对齐到波形，再用
   `context_steps` 取前后若干点，依据真实边沿与数据变化归因。两种窗口模式每次调用只能
   选一种；一次查不清楚就缩小信号集拆成多次调用，`max_signals`/`max_points` 保持有界。

信号目录包含 DUT 内部层级路径，是定位内部信号最直接的入口。

### 内部信号分析

共享测试只面向 `env` 的公开 pin 与事件合同：不得读取 `env._dut`、绕过 adapter 访问内部
层级，也不要为观测内部信号而修改 adapter、architecture、observation contract 或测试本身
——这些改动会改变原有 TC 的语义与证据，可能掩盖真实缺陷。基于保留波形用 WaveInfo 分析
内部信号（信号目录含 DUT 内部层级路径，依据真实边沿与数据变化定位第一个错误值）是最
直接、证据最完整的推荐方式；在不改变原有 TC 语义与证据强度的前提下，也可以自行设计
其他非侵入式定位方法。`Guide_Doc/design_observation_contract.md` 的观测规则同样禁止依赖
私有 DUT 成员。

### 常见调试建议

- 临时日志：在当前语言源码可写打印的位置加入有界打印，例如 Verilog 的
  `$display("t=%0t state=%0d acc=%0d", $time, state, acc);`，只打印关键状态与数据通路
  节点，避免每拍全宽度转储。打印输出会出现在失败诊断的 `stdout_tail`/`stderr_tail` 与
  定向 Check 结果中。修复后必须删除全部调试打印；它们不属于交付源码。对生成式语言产物
  （如 Chisel 生成的 Verilog）不可手改中间文件，用 WaveInfo 代替日志。
- Python 侧对拍：reference 路径可用 `RunTestCases` 复跑同一向量并临时打印参考中间值，
  与 RTL 波形逐级比较；同样在修复后删除。
- 每轮只验证一个假设：先定向 Check 复现，修一处再复验，通过后再全量 Check 找下一个
  失败；不要同时改多处后跑全量。
- 高频根因清单：写完输入忘记 `RefreshComb()`；`Step(1)` 后未刷新就读输出；遗漏某个时钟
  的 `InitClock`；reset 极性或同步语义与 architecture 不符；立即写与组合刷新顺序颠倒；
  字面量/中间信号宽度或 signedness 不足以表示最大中间值；打包/字节序与 Spec 不一致；
  未复位寄存器产生 X 传播；握手 latency 与响应周期（re-arm）处理错误。

## 完整 adapter 示例

```python
"""Backend-neutral adapter for Adder."""

from pathlib import Path
from types import MappingProxyType

from design_with_ppa import create_dut
from Adder_reference import AdderReference


class AdderAdapter:
    """Drive one-cycle addition through the shared pin interface."""

    def __init__(self, backend):
        """Create the selected implementation without backend-specific imports."""

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
        """Bind unique RTL artifacts before reset and the first Step."""

        if self.backend != "rtl":
            return
        self.waveform_path = Path(waveform_path).resolve()
        self.waveform_path.parent.mkdir(parents=True, exist_ok=True)
        self._dut.SetCoverage(str(coverage_path))
        self._dut.SetWaveform(str(self.waveform_path))
        self._dut.ResumeWaveformDump()

    def bind_coverage(self, groups):
        """Bind the same FG/FC coverage groups in both modes."""

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
        """Write a complete input transaction and refresh once."""

        self._dut.rst_ni.value = rst_ni
        self._dut.valid_i.value = valid_i
        self._dut.a_i.value = a_i
        self._dut.b_i.value = b_i
        self._dut.RefreshComb()

    def _step(self):
        """Advance one active edge and refresh post-edge outputs."""

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
        """Return one accepted response within max_cycles."""

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
            raise TimeoutError("request not accepted")
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

    def run_until_observation_end(self, end_time_ns):
        """Hold idle inputs and preserve a fixed waveform duration."""

        self._drive(rst_ni=1, valid_i=0, a_i=0, b_i=0)
        while self.sim_time_ns < end_time_ns:
            self._step()

    def sample_coverage(self):
        """Sample bound functional coverage."""

        for group in self.coverage_groups:
            group.sample()

    def flush_waveform(self):
        """Make RTL activity durable before sidecar creation."""

        if self.backend == "rtl":
            self._dut.FlushWaveform()

    def finish(self):
        """Release one test instance and its coverage state."""

        for group in self.coverage_groups:
            group.clear()
        self._dut.Finish()


def create_adapter(backend):
    """Create the backend selected by the pytest fixture."""

    return AdderAdapter(backend)
```

## 完整 fixture 示例

```python
"""Create one instrumented backend-neutral test environment."""

from pathlib import Path

import pytest
from design_with_ppa import (
    get_performance_waveform_path,
    managed_test_implementation,
    register_managed_test_options,
)
from toffee_test.reporter import get_file_in_tmp_dir, set_func_coverage, set_line_coverage

from Adder_adapter import create_adapter
from Adder_function_coverage_def import get_coverage_groups


def pytest_configure(config):
    """Register workflow-owned markers without changing the pytest root directory."""

    config.addinivalue_line(
        "markers",
        "performance: deterministic simulation performance case that emits PPA evidence",
    )


def pytest_addoption(parser):
    """Register the workflow-owned backend selector."""

    register_managed_test_options(parser)


@pytest.fixture
def env(request):
    """Bind artifacts before reset and return one fresh adapter."""

    backend = managed_test_implementation(request.config)
    adapter = create_adapter(backend)
    groups = get_coverage_groups(adapter)
    adapter.bind_coverage(groups)
    coverage_path = None
    if backend == "rtl":
        data_dir = Path(__file__).resolve().parent / "data"
        coverage_path = get_file_in_tmp_dir(
            request, str(data_dir), f"{request.node.name}.dat", new_path=True
        )
        if request.node.get_closest_marker("performance") is not None:
            waveform_path = get_performance_waveform_path(request)
        else:
            waveform_path = get_file_in_tmp_dir(
                request, str(data_dir), f"{request.node.name}.vcd", new_path=True
            )
        adapter.configure_test_artifacts(coverage_path, waveform_path)
    adapter.reset()
    yield adapter
    # Save functional coverage before adapter.finish() clears the groups.
    set_func_coverage(request, groups)
    # Finish closes the native runtime and writes the coverage dat file.
    adapter.finish()
    if coverage_path is not None:
        # Register only the finalized dat file with Toffee.
        set_line_coverage(request, coverage_path, ignore="Adder.ignore")
```

两种 backend 的 API 返回结构、异常和 timeout 必须一致。失败只能按权威需求修正当前 RTL
源语言、reference、adapter、fixture 或测试解决，不能跳过用例或弱化断言；不能为了迁就错误
RTL 而改写 reference 或 expected。
