
# FG/FC/CK 与统一 UT 合同

功能文档沿用 UCAgent 的唯一 FG/FC/CK 标签格式。普通功能 CK 只描述能由 DUT 公共 pin、transaction 或 backend-neutral 事件观测的行为，并且必须能形成一个真实布尔 predicate。功能 CK 由同一套 pytest 测试在 Python 和 RTL backend 上验证，测试不得因 backend 改变期望值。

测试 API、fixture、pytest 用例数量、随机用例数量、coverage 工具接入、报告和工作流步骤属于验证计划，不是 DUT 功能 CK。这些要求写入 `{OUT}/{DUT}_design_needs_and_plan.md`；逐行映射时使用指出对应工作流阶段的具体 `IGNORE` 理由。性能测量、PPA 目标或优化流程可统一放在 `FG-PPA` 下，由后续性能合同、多个性能 TC、波形和 PPA 迭代门禁验证，不进入普通 transaction coverage。功能失败必须修复，不能记录为可保留 DUT Bug。

跨 Spec 出现相同触发、输入条件和可观察结果时只建立一个 CK，并在该 CK 中保留全部 Spec 路径。不能为了保留两个名称而制造两个观测等价的 CK。细化结束前逐项确认每个普通 CK 都能写出有业务含义的 predicate；如果不能，就合并重复 CK，或把流程要求移回设计计划。

机器标签只包含稳定 ID，例如 `<FG-ARITH>`、`<FC-ADD>` 和 `<CK-WRAP>`。可读标题放在标签
前一行的 Markdown heading 中，不能写成 `<FG-ARITH: Arithmetic>` 或把空格、冒号、斜线
放进标签。ID 在整个文档中唯一；前缀后的字符只使用字母、数字、点、下划线和连字符。

测试只接收 `env` fixture；不要定义或使用公开的 `dut` fixture。`env` 是 backend-neutral
环境，负责把 reference model 与 RTL DUT 的引脚、reset、组合刷新、Step、latency、异常和
观测结果归一化。reference 与 RTL 可以有不同的内部时序，但同一测试通过 `env` 必须看到同一
个外部 transaction 合同。底层 DUT 只能作为 adapter 的私有成员使用，测试、API、coverage
predicate 和 `mark_function` 都不得读取 `env._dut` 或直接读取具体 DUT 对象。

Python reference 是 README、Spec、已确认 architecture 和 FG/FC/CK 的可执行实现，不是永久
冻结的 oracle。创建后任何阶段都可以在需求或验证证据支持下修正其功能、状态、reset、时序、
非法输入和边界行为；修正后同步受影响的 adapter、API、fixture、coverage predicate 和测试
expected，并重新运行受影响的 Python 与 RTL 节点。若 Python 已按权威合同通过而 RTL 失败，
不得把 reference 或 expected 改成 RTL 的当前输出。

测试必须作为 `{OUT}/tests` 下已有的真实 pytest 用例执行。开发时使用 `RunTestCases` 运行函数级节点，Check/Complete 会在独立测试进程中复验并读取结构化报告。不得把 `RunTestCases` 当作任意 Python 执行器，也不得通过直接 import、`python -c` 或临时脚本执行 DUT 来代替 pytest 证据。

RTL adapter 使用立即写入端口时，必须遵守 `Guide_Doc/rtl_backend.md` 的“立即写入与组合刷新”顺序：一次写完当前事务的所有输入，先调用 `RefreshComb()` 执行立即输入驱动的组合逻辑，再调用 `Step(1)` 推进延迟一个周期的时序逻辑；边沿后需要观察新状态的组合输出时再次刷新。不得在首次刷新前推进时钟。

测试函数使用 `test_{DUT}_<scenario>` 名称和 `env` fixture。对外 API 使用 `api_{DUT}_*`；每个公开 API 的第一参数必须为 `env`，最后参数必须为 `max_cycles=<positive default>`，docstring 必须同时包含 `Args:` 和 `Returns:`。即使当前 API 不需要等待，也保留这一统一签名，调用方因此可以用同一套超时参数约定切换 backend。reset、reinitialize 和 transaction 等重复使用的 DUT 主动动作应提供对应公开 API，DUT transaction/reset 优先通过这些 API 发起。底层 DUT 只能作为 adapter 的私有成员使用，TC、API、coverage predicate 和 `mark_function` 都不得读取 `env._dut`、调用私有事件/transaction 方法、读取 active transaction 表或给 `last_event`、`last_event_data` 等公开证据字段赋值。所有空模板在实现前保留 `assert False, "Not implemented"`，实现后必须完全移除。

每个返回数据的公开 API 调用都必须通过 `==` 与独立推导的精确 expected 比较。`result != 0`、truthiness、`is not None`、仅检查编码范围、仅检查类型或 `result == result` 都不能证明 Spec 行为。命令型 reset API 可以明确返回 `None`，并用 `is None` 及 reset 后的精确公开状态共同验证。

实现批次中的已有测试模板时，必须原位替换函数体，不能在同一文件追加同名 `def`。每次保存后
检查整个文件的顶层测试函数名唯一，并确认字面量 `mark_function` 引用该唯一函数；同名后定义
会隐藏前面的真实实现或占位函数，使 pytest 收集和覆盖关联失真。

覆盖模型分两步完成。结构阶段一次性声明除 `FG-PPA` 外的完整功能 FG/FC/CK 层级，每个功能 CK predicate 必须使用
统一占位 `lambda _env: False`；结构存在不代表条件已经实现。predicate 批处理阶段优先替换
`CurrentTips` 当前批次的占位。其他 CK 尚未实现时保留占位；如果它们已经按相同合同正确实现，则保留实现，
Checker 会复验并同步完成统计，不得为了匹配批次提示而回退。恒真 callable 不能
作为实现，不同 CK 也不能复用归一化后相同的泛化 predicate。无法由真实输入、输出或事件字段
区分的 CK 必须回到功能合同合并；禁止添加恒真子句、无意义范围、取模或任意 transaction ID
差异使源码看起来不同。最终可达性由同套 pytest 的真实 coverage hit 证明。

所有批处理 stage 都把 `CurrentTips` 列表作为当前优先工作，而不是源码中唯一允许存在的工作。
`Check` 首先要求当前 batch 满足合同，同时扫描 canonical 文档、predicate、测试或记录中已经完成的
其他 batch。正确的提前完成内容会保留并计入进度；格式错误、未知 CK、失败测试、无真实断言、
伪造关联或无有效执行证据的内容仍会失败并给出修复诊断。不得直接编辑批次 checkpoint 或进度文件。

## 完整功能文档示例

```markdown

# Adder 功能与检测点

## 算术功能

<FG-ARITH>

### 无符号加法

<FC-ADD>

#### 普通输入

<CK-NORMAL>

当 `valid_i=1` 时，`sum` 等于两个操作数之和的低 WIDTH 位，`valid_o=1`。

#### 溢出截断

<CK-WRAP>

结果超过 WIDTH 位时只保留低 WIDTH 位。
```

## 完整测试示例

```python
"""Shared directed tests for both design backends."""

import pytest

from Adder_api import api_Adder_add


@pytest.mark.parametrize("a,b,expected", [(1, 2, 3), (255, 1, 0)])
def test_Adder_add(env, a, b, expected):
    """Cover FG-ARITH/FC-ADD/CK-NORMAL and CK-WRAP."""

    checkpoints = ["CK-WRAP"] if a + b > 255 else ["CK-NORMAL"]
    env.fc_cover["FG-ARITH"].mark_function(
        "FC-ADD", test_Adder_add, checkpoints
    )
    assert api_Adder_add(env, a, b, max_cycles=4) == expected
```

## 完整覆盖模型示例

```python
"""Functional coverage matching the complete Adder FG/FC/CK contract."""

from toffee.funcov import CovGroup


def get_coverage_groups(env):
    """Build one group with executable predicates over public environment state."""

    arithmetic = CovGroup("FG-ARITH")
    arithmetic.add_watch_point(
        env,
        {
            "CK-NORMAL": lambda model: model.a.value + model.b.value <= 255,
            "CK-WRAP": lambda model: model.a.value + model.b.value > 255,
        },
        name="FC-ADD",
    )
    return [arithmetic]
```

对应的结构阶段写法如下；进入 predicate 批次后，才按当前 CK 逐项替换这些占位：

```python
arithmetic.add_watch_point(
    env,
    {
        "CK-NORMAL": lambda _env: False,
        "CK-WRAP": lambda _env: False,
    },
    name="FC-ADD",
)
```

## 瞬时事件覆盖示例

下面的 predicate 区分真实握手接受和 host API 参数拒绝。`last_event_data` 是不可修改映射；
adapter 在动作发生处采样，因此测试调用返回后即使事件已变为 `response_observed`，先前的
`transaction_accepted` 命中仍会保留。

```python
protocol = CovGroup("FG-PROTOCOL")
protocol.add_watch_point(
    env,
    {
        "CK-ACCEPT-ADD": lambda model: (
            model.last_event == "transaction_accepted"
            and model.last_event_data.get("operation") == "add"
            and model.last_event_data.get("transaction_id", 0) > 0
        ),
        "CK-WAITING": lambda model: (
            model.last_event == "transaction_observation"
            and model.last_event_data.get("phase") == "waiting_response"
            and model.last_event_data.get("ready") == 0
        ),
        "CK-ADD-RESULT": lambda model: (
            model.last_event == "response_observed"
            and model.last_event_data.get("operation") == "add"
            and model.last_event_data.get("result")
            == (
                model.last_event_data.get("a", 0)
                + model.last_event_data.get("b", 0)
            ) & 0xFF
        ),
        "CK-INVALID": lambda model: (
            model.last_event == "api_validation_error"
            and model.last_event_data.get("field") in {"a", "b", "max_cycles"}
        ),
    },
    name="FC-TRANSACTION",
)
```

非法 API 测试先保存合法 pin 快照，再调用公开 API。异常后 pin 必须未改变；覆盖由 adapter 在
抛出异常前的真实 `api_validation_error` 事件采样，不由测试补写。

```python
def test_Adder_invalid_operand(env):
    """Cover FG-PROTOCOL/FC-TRANSACTION/CK-INVALID."""

    env.fc_cover["FG-PROTOCOL"].mark_function(
        "FC-TRANSACTION", test_Adder_invalid_operand, ["CK-INVALID"]
    )
    before = (env.a_i.value, env.b_i.value)
    with pytest.raises(ValueError, match="8-bit unsigned integer"):
        api_Adder_add(env, 256, 1, max_cycles=4)
    assert (env.a_i.value, env.b_i.value) == before
    assert env.last_event == "api_validation_error"
    assert env.last_event_data["field"] == "a"
```

每个普通测试的第一条业务动作必须用字面量 FG/FC/CK 调用
`env.fc_cover[...].mark_function(...)`，并且 API 或测试必须在有效结果产生后调用
`env.sample_coverage()`。覆盖定义入口固定为 `get_coverage_groups(env)`，watch-point target
固定为 `env`；predicate 只能读取环境提供的公开归一化属性或方法，不能把裸 `dut` 作为输入。
对于 API 参数拒绝、握手接受沿等不能由合法 pin 静态值准确表达的行为，predicate 必须读取
adapter 公开的 `last_event`/`last_event_data`，且 transaction 接受/响应 predicate 必须读取
能区分当前 CK 的事件字段，不能只写 `last_event == "response_observed"`。事件由 adapter 在真实动作发生处调用私有
`_record_event()` 记录并立即采样。测试不得直接调用 `_record_event()`、任何私有 transaction
helper 或读取 active transaction 表，不得修改事件字段、访问 `env._dut` 或
向 pin 写入超宽非法值来伪造命中。完整时序与例子见
`Guide_Doc/python_dut_interface.md` 的“Backend-neutral 事件证据”。

adapter 在接受点调用 `_record_transaction_accepted()` 保存 immutable request identity。等待、
backpressure 或 pipeline CK 使用真实 post-`RefreshComb`/post-`Step` 观察点调用
`_record_transaction_observation()`；运算、转换与输出 CK 使用
`_record_response_observed()` 自动带回 operation/mode/precision/输入，并结合结果判断；固定
latency CK 使用同一 response 中的 `accepted_at`、`response_at` 与 `latency_cycles`。不能把
transaction ID 大小、奇偶、时间戳存在性或无关 precision 分区当成功能差异。
空模板保留占位断言；进入实现阶段后必须删除占位并添加独立
expected 与真实断言。随机测试必须固定 seed、调用 `ucagent.repeat_count()`，只
`mark_function` 其采样能实际命中的 CK；不适合随机化的 CK 在 `stage_args.generated`
中给出具体原因，且不要在随机测试中 `mark_function` 这些 CK。

## Observation contract 与 predicate

在实现 coverage predicate 前，先按 `Guide_Doc/design_observation_contract.md` 完成
`{OUT}/{DUT}_observation_contract.yaml` 和共享 adapter/API instrumentation。该合同逐项说明
每个 CK 使用公开 pin 还是瞬时事件、需要哪些字段以及字段的真实来源。coverage 批次不得临时
修改事件字段来迎合 predicate。

为降低生成错误率，实际 coverage 文件使用“每个 CK 一个顶层命名函数”的形式。每个函数只
接收一个 env 参数，只返回一个布尔表达式，并在 bins 字典中通过函数名引用。函数可以先保存
`model.last_event_data`，但不得读取私有成员或修改环境。

```python
def ck_add_response(model):
    """Match one accepted add response with its exact public result."""

    data = model.last_event_data
    return (
        model.last_event == "response_observed"
        and data.get("operation") == "add"
        and data.get("result")
        == ((data.get("a", 0) + data.get("b", 0)) & 0xFF)
    )


def get_coverage_groups(env):
    """Return the shared functional coverage groups."""

    group = CovGroup("FG-ARITH")
    group.add_watch_point(
        env,
        {"CK-ADD-RESPONSE": ck_add_response},
        name="FC-ADD",
    )
    return [group]
```

不要在 bins 中直接编写复杂多行 lambda，也不要在一个函数中根据 CK 名称动态分派。完整 CK
路径仍由既有 FG/FC watch point 和 CK key 组成。缺失字段必须回到 observation contract 和真实
动作点修复；不能用常量 fallback、无关字段或任意算术让不同 predicate 的源码看起来不同。
