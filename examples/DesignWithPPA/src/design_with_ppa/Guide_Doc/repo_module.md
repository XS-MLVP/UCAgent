
# 仓库模块开发合同

读取任务 README/Spec 和 `source_snapshot` 中的目标源码与依赖。仓库只解决源码依赖；只构建、测试和测量选定模块，不构建整个系统。人工编写文件仅位于 `{OUT}/repo`。源码快照、运行目录和验证记录不可人工修改。

源码导入结果中的 `source_paths` 非空时，仅包含指定文件、目录及选中的子模块；空列表代表全部源码。新增模块必须位于选中的目录内，依赖必须已导入。发现范围不足时报告缺失路径，在新工作区扩大选择并重新建立基线。被排除的子模块不能作为已验证依赖。

## 阶段产物

依次完成源码快照、功能合同（FG/FC/CK）、模块合同、独立可执行参考与覆盖率统计、基线、pytest 用例与反标、优化候选、最终交付。每阶段使用 CurrentTips 获取路径，完成后 Check/Complete。需要再次执行时调用 `RunRepoValidation`；不直接运行 shell 或 Python。pytest 用例可用 `RunTestCases` 自行运行调试。重启后已存在的文档/代码基于其完善，不推倒重写。无需 Skill。

`contract.yaml` 声明要求和测量边界，`verification/` 声明与接口无关的逻辑工作负载和期望，两者在基线后冻结。`functions_and_checks.md` 与 `tests/` 在 pytest 用例阶段完成时由 Check 一并封存；候选迭代期间修改它们会被拒绝。发现合同或参考错误时报告原因，并在新工作区修正后重新建立基线，不能为了匹配错误硬件修改期望。

可选硬目标 `max_area`、`max_power_w`、`max_effective_period_ns` 分别限制库面积单位、瓦特和纳秒。原始基线必须功能正确且可测量，可以尚未达到优化目标；最终交付必须满足全部硬目标。

`candidate/` 包含完整接口版本、模块构建配方、引脚适配、协议测试，以及 `files/` 中按目标仓库路径组织的文件。`candidate.yaml` 显式列出增改删操作。`files/` 必须恰好包含所有 add/replace 文件，不放构建输出。建议一个独立功能一个 RTL 文件，具体架构、流水线和资源复用由任务约束决定。

`optimize` 的原始基线必须没有源码修改；`add` 的基线必须包含新增目标模块并通过单元测试。调用 `RunRepoValidation(baseline=true)`。后续修改使用新的 `variant_id`；改变引脚或协议必须更新 `interface.version`。`interface_policy=preserve` 时完整接口保持一致。

## 引脚与单元测试

`interface.yaml` 必须完整列出顶层端口的方向、位宽、符号性和用途。`clock`、`reset` 可为 null；非空时必须为一位输入。`reset_active`、`reset_cycles`、`request_when`、`response_when` 和 `protocol` 描述复位、请求接受、响应有效、顺序、异常与时序。参数在 `parameters` 给出，构建后的真实端口必须与合同完全一致。当前公共端口支持 input/output，双向总线应在模块边界明确拆分。

参考模型 `evaluate(transactions)` 返回 `{transaction_id: {result_field: integer}}`，不得读取 RTL 或测试实际结果。工作负载每个场景给出唯一事务 ID、逻辑输入、最早释放周期及独立计算的 `expected_examples`。所有 requirement ID 至少由一个场景覆盖；加入数值边界、连续请求、复位、背压、异常及任务要求的其他场景。释放调度必须让吞吐可达：场景事务数除以释放跨度（最晚与最早 `release_cycle` 之差加一）不得小于 `min_throughput_per_cycle`，否则 Check 在参考阶段直接拒绝。

`adapter.py` 的 `run(env, transactions)` 只负责协议映射。`protocol.py` 定义至少一个含真实断言的 `test_*(env)`。每个测试和逻辑场景使用复位后的独立 DUT。禁止内部状态、反射、文件访问、动态执行或导入硬件/参考模块；允许 math、random、itertools、functools、collections、typing、dataclasses、fractions、decimal。

公共 env API：

| API | 合同 |
| --- | --- |
| `env.cycle` | 初始复位后经过的周期数 |
| `env.drive(a=3)` | 写公开输入的非负 packed 值；不能手动写时钟 |
| `env.read("result")` | 读取声明的公开引脚 |
| `env.tick(count=1)` | 推进周期，受 max_cycles 限制 |
| `env.accept(id)` | 请求已满足 request_when 且达到 release_cycle 时登记事务 |
| `env.sample(id, {"value": "result"})` | 从真实输出引脚采样逻辑结果，检查 response_when |

串行接口可多次 sample，用 `{"pin": "data", "lsb": 0, "width": 8, "offset": 8}` 指定逻辑字段片段。所有片段必须覆盖字段一次，不得重叠，不能提交软件计算的结果。适配器不能以隐藏运算或缓冲代替必要硬件。

延迟从固定 `release_cycle` 测到最后结果采样，包含等待；吞吐由完成事务数和同一场景起止周期得到。比较使用相同逻辑事务与工艺条件，允许接口版本的物理引脚轨迹不同。任何为模块服务的必要硬件适配都必须包含在本次模块测量顶层内。调用方改动建议写入 `caller_impact`；单元验证不证明完整系统可用。

统一时序比较指标为 `ppa.timing.effective_period_ns`：组合模块使用关键路径延迟，时序模块使用最大工作频率的倒数；原始 STA 报告同时保留。周期级延迟和吞吐必须分别满足合同，不能仅用频率提升掩盖增加的事务周期。

功耗活动从真实波形提取公开引脚：投影窗口由公开引脚（时钟除外）的首末真实翻转界定，复位段与空闲等待都被排除，再映射到固定的 `clock_period_ns`。原始 FST 波形与临时转换件在测量后即删除；其 SHA256 与时间映射证据保留在封签记录中。最后一个响应后最多允许一个收尾周期，不得添加空闲周期稀释平均功耗。

## 功能合同、覆盖率与测试用例

`functions_and_checks.md` 是模块全部功能需求的唯一 FG/FC/CK 标签化合同。分析任务 README、可选 spec 与源码快照中的目标模块，把每个可由公开引脚观测的功能、边界、复位、握手、时序和异常行为落成 FG（功能组）→ FC（功能）→ CK（检查点）层级；标签必须唯一、完整、不含非法字符。`contract.yaml` 的 requirements 键必须逐一使用全部 CK 叶子路径，Check 校验一一对应。

```markdown

# 功能合同

## 字节旋转

<FG-ROTATE>

### 旋转行为

<FC-BYTE-LANE>

#### 旋转结果

<CK-RESULT>

按公开引脚观测：result 的 8 个字节 lane 是 data 按 amount 整体旋转的结果，255 回绕到 0，两个方向都必须成立。
```

工作负载每个场景的 `covers` 列出覆盖的 CK 路径；Check 执行参考自测后生成 `{OUT}/repo/coverage.json`，给出每个 CK 的场景数、事务数与总覆盖率——所有 CK 必须被至少一个场景覆盖。

参考模型必须先于 pytest 用例完成并覆盖每个 CK 的可计算行为；基线测量之后编写 pytest 用例：`tests/conftest.py` 提供受管 `env` 夹具，自动加载最近一次实测构建的公开引脚 DUT（与 Check 相同的 PinEnvironment 纪律）。每个 `test_*.py` 声明模块级 `COVERS = ["FG-.../FC-.../CK-..."]` 反标其覆盖的检查点；期望值通过 conftest 的 `reference` 夹具从冻结参考 `evaluate(transactions)` 计算，不硬编码常量；用 `RunTestCases` 自行运行 `{OUT}/repo/tests` 调试，断言只用公开引脚。Check 校验反标完备（全部 CK 至少一个 TC）且 pytest 全部通过；候选阶段每轮新测量后与交付复验时都会重新运行全部 pytest 用例，失败即拒绝。

每次 PPA 测量都会刷新 `{OUT}/design_with_ppa_dashboard.html`（复用既有 HTML 报告），其中嵌入最新面积/时序/功耗结果。

## 独立构建配方

`recipe.yaml` 的 `scope` 必须是 `unit`。`build` 为可选命令列表，每项含 `argv`、副本内 `cwd` 和 `timeout`；命令仅导出目标模块及其依赖。不要配置顶层系统构建。Chisel 等生成器使用目标项目所需版本和依赖，在副本内运行模块级导出。`tool_versions` 使用同样结构记录项目工具版本。

`rtl_files` 是按编译顺序列出的明确路径，不是 glob；文件可为原始 Verilog/SystemVerilog 或模块导出结果。`include_dirs`、`defines`、`systemverilog` 指定预处理条件。综合前端不支持的 SystemVerilog 结构需由配方中的转换步骤处理，不能忽略解析失败。每个命令超时和整个模块工具调用上限均由配方提供。

## 完整产物示例

以下为读取 `rtl/unit.v` 中组合加一模块的完整基线输入。该示例没有源码变更，因此不创建 `candidate/files`。根据实际任务替换内容，不把示例模块名或算法作为硬约束。

`{OUT}/repo/contract.yaml`：

```yaml
objective: Increment bytes modulo 256
target_paths: [rtl/unit.v]
allowed_changes: [rtl/unit.v]
dependencies: []
caller_impact: Keep the caller's byte-level increment semantics; system build is outside this task.
requirements:
  increment: Increment every input byte modulo 256, including overflow.
result_fields:
  result: {width: 8, signed: false}
clock_period_ns: 10.0
max_latency_cycles: 10
min_throughput_per_cycle: 0.1
max_cycles: 1000
ordering: in_order
```

`{OUT}/repo/verification/workload.yaml`：

```yaml
seed: 1
scenarios:
  - name: boundary
    covers: [increment]
    transactions:
      - {id: zero, inputs: {a: 0}, release_cycle: 0}
      - {id: overflow, inputs: {a: 255}, release_cycle: 1}
    expected_examples:
      zero: {result: 1}
      overflow: {result: 0}
```

`{OUT}/repo/verification/reference.py`：

```python
"""Independent modulo-byte arithmetic."""


def evaluate(transactions):
    """Return expected logical fields for every transaction ID."""

    return {t["id"]: {"result": (t["inputs"]["a"] + 1) % 256}
            for t in transactions}
```

`{OUT}/repo/candidate/candidate.yaml`：

```yaml
variant_id: baseline
hypothesis: Measure the original module.
changes: []
```

`{OUT}/repo/candidate/interface.yaml`：

```yaml
version: v1
top: Unit
pins:
  a: {direction: input, width: 8, signed: false, purpose: operand}
  y: {direction: output, width: 8, signed: false, purpose: incremented byte}
clock: null
reset: null
reset_active: 0
reset_cycles: 2
request_when: {}
response_when: {}
protocol: Combinational result after inputs settle; no backpressure or reset state.
parameters: {}
```

`{OUT}/repo/candidate/recipe.yaml`：

```yaml
scope: unit
build: []
tool_versions: []
rtl_files: [rtl/unit.v]
include_dirs: []
defines: {}
systemverilog: false
timeout: 600
```

`{OUT}/repo/candidate/adapter.py`：

```python
"""Public-pin mapping for the combinational increment unit."""


def run(env, transactions):
    """Drive requests and capture every result directly from the output pin."""

    for transaction in transactions:
        while env.cycle < transaction["release_cycle"]:
            env.tick()
        env.drive(a=transaction["inputs"]["a"])
        env.accept(transaction["id"])
        env.sample(transaction["id"], {"result": "y"})
        env.tick()
```

`{OUT}/repo/candidate/protocol.py`：

```python
"""Independent public-output boundary checks."""


def test_overflow(env):
    """Verify wrap behavior through public pins."""

    env.drive(a=255)
    assert env.read("y") == 0
    env.tick()
```

后续候选替换 `rtl/unit.v` 时使用新的 ID，并将源文件放入 `candidate/files/rtl/unit.v`：

```yaml
variant_id: carry_variant
hypothesis: Explore a different carry implementation while preserving byte semantics.
changes:
  - {path: rtl/unit.v, action: replace, executable: false}
```

新增模块使用 `action: add`；删除文件使用 `action: delete`，该文件不出现在 `files/` 中。文件必须在 `allowed_changes` 范围内。

## 完成与交付

`RunRepoValidation()` 测量当前候选。工具返回真实功能结果、模块 PPA、接受状态和完整报告路径。达到配置的最少轮数后继续探索，直到耐心条件或最多轮数满足。拒绝候选也保留实测记录；构建和功能错误必须修复后才能计入有效轮次。

`RunRepoValidation(action="restore_best")` 恢复最佳完整版本，保留被替换草稿。`RunRepoValidation(action="deliver")` 复验最佳版本并在新副本中验证补丁应用及重新构建/单元测试。交付包含源码、标准化 RTL、变更清单、二进制兼容补丁、基线/最终接口和验证历史。没有有效改善时明确说明，不伪造优化结论。交付同时生成 `summary.md`：基线与交付指标、改善结论、接口版本和验证范围全部来自封签测量记录；向用户汇报时以该文件为准，不手写测量结论。

需要迁移脚本时设置 `migration_script=true`。脚本默认预览，手动应用需明确指定目标及 `--apply`，遇到基准或文件冲突立即拒绝。工作流从不应用到原始仓库。所有交付都明确标记 `verification_scope: unit_only` 与 `system_integration: not_run`。
