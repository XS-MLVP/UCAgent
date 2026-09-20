
# RTL 行覆盖与精确排除规范

本阶段以真实 RTL backend 回归产生的行覆盖报告为依据。先为可达、有功能意义的未覆盖分支
补充测试；只有能够从 architecture、Spec 和源码控制条件证明不可达，或确定不产生硬件语义的
精确行范围，才允许排除。缺少测试向量、断言不充分、当前未触发、覆盖率接近阈值，以及 Spec
明确要求的零值、饱和、异常编码、reset 或协议行为，都不是排除理由。

每个调用 `api_{DUT}_*` 的正常功能测试都必须用 `==` 将返回值与独立推导的精确期望值比较。
`result is not None`、`result != 0`、`assert result`、`result == result` 等只能证明“有返回”或
自反关系，不能证明 Python executable spec 与 RTL 行为一致，也不能作为有效覆盖证据。异常输入
应使用 `pytest.raises` 验证精确异常合同。

原始 ignore 文件和分析 Markdown 是两个不同的产物：

- `{OUT}/tests/{DUT}.ignore` 由 Toffee 直接解析，只包含原始 glob/range 或独立 `#` 注释。
- `{OUT}/{DUT}_line_coverage_analysis.md` 面向审查，每个原始模式用一个完全相同的
  `<LINE_IGNORE>...</LINE_IGNORE>` 标签，并提供可追溯的 `proof` 与 `evidence`。

不能把 Markdown 标签、冒号后的理由、引号或自然语言写入 `.ignore`。这会使覆盖生成失败，
而不是形成一个有效排除。

## 覆盖率文件生命周期

`Check` 会先运行完整的 RTL 共享测试，再读取 Toffee 生成的
`{OUT}/uc_test_report/line_dat/code_coverage.json` 和 `merged.info`。fixture 必须在第一次
reset/Step 之前调用 adapter 的覆盖率配置，让每个测试使用独立的 `.dat` 路径。测试收尾时按
以下顺序执行：

```text
FlushWaveform()                 # 仅性能测试需要
set_func_coverage(request, groups)
adapter.finish()                # 关闭 RTL runtime，写完 .dat
set_line_coverage(request, path, ignore=...)
```

`set_line_coverage()` 只是向 Toffee 注册已经写完的文件；它不会替代 `SetCoverage()`，也不会
自己生成覆盖率。若 RTL 测试断言失败，Toffee 会忽略失败测试的行覆盖记录，阶段必须先修复
功能回归，不能把此时的 `line.total: 0` 当作真实的零覆盖率。若全部测试通过但
`code_coverage.json` 缺失，检查 fixture 是否确实执行了上述注册顺序、覆盖率路径是否位于
当前测试目录的 Toffee 临时目录，以及 `toffee_report.json.coverages.line.error` 是否给出具体
转换错误。

## 覆盖率排障流程

按下面的顺序分析一次 Check 生成覆盖率的结果。不要跳过前置步骤，也不要直接编辑机器生成
的 JSON/LCOV 文件：

1. 先确认当前 RTL 源码能通过综合和托管 runtime 准备；如果收到
   `rtl_synthesis_failed`、`rtl_synthesis_width_warning` 或
   `rtl_line_coverage_backend_invalid`，先修复源码、top、端口、literal/intermediate 位宽、
   signedness 或 library 配置，覆盖率尚未开始。Yosys 返回 0 但报告 literal 位宽不足时，常量
   已发生确定性截断，仍不能进入 RTL regression。
2. Check 使用同一套共享 pytest TC 运行 RTL backend。每个 `env` fixture 创建 adapter，调用
   `get_coverage_groups(env)`，再调用 `adapter.bind_coverage(groups)`。RTL backend 还要为当前
   TC 取得唯一的 `.dat` 和波形路径，并调用 `adapter.configure_test_artifacts(...)`。这些调用
   必须发生在第一次 `reset()`/`Step()` 之前，否则前面的时钟和事务没有被插桩。
3. DUT transaction/reset 优先通过 `api_{DUT}_*`，以保持 Python reference 与 RTL 的外部
   语义一致。coverage predicate 不得 import 或访问底层 DUT、调用私有事件/transaction 方法、
   读取 active transaction 表或篡改事件证据。先用 `RunTestCases` 确认 Python reference 通过，
   再让 Check 用同一节点验证 RTL。
4. fixture teardown 必须依次完成：性能 TC 先 `FlushWaveform()`，然后
   `set_func_coverage(request, groups)` 保存 FG/FC/CK 命中，调用 `adapter.finish()`（或
   `Finish()`）关闭 RTL runtime 并写完 `.dat`，最后调用
   `set_line_coverage(request, coverage_path, ignore=...)` 注册已经完成的 `.dat`。不能在
   `finish()` 前注册行覆盖，也不能在 `finish()` 后再次调用原生 DUT 的 coverage/waveform API。
5. Toffee 汇总所有 TC 的结果并写出 `uc_test_report/toffee_report.json`。行覆盖转换随后产生
   `uc_test_report/line_dat/code_coverage.json` 和同目录 `merged.info`；Checker 会把它们与
   当前 authored RTL 文件、源行数和 `.ignore` 精确匹配。三者缺一、为空、是符号链接、或
   `coverages.line.error` 非空，均属于生成失败，不是覆盖率百分比。
6. 只有完整 RTL TC 全部 `PASSED` 后，才分析 `code_coverage.json` 的 authored-source
   `uncovered.data` 与 `merged.info` 的 `DA` 计数。根据真实未覆盖行补充 directed/boundary/
   reset/sequence/random TC；可达行为不能写入 ignore。完成后再次运行完整 RTL TC，确认报告、
   line coverage 和 FC/CK 结果来自同一次运行。

排障时优先读取以下证据：

- `observed.failed_cases`、`observed.pytest.failed_nodes`：第一条失败 TC、phase、异常和 CK；
- `observed.coverage_artifacts`：`code_coverage_json`、`merged_info`、`toffee_report` 的
  exists/regular/non_empty/size 状态；
- `observed.toffee_line_coverage` 与 `uc_test_report/toffee_report.json:coverages.line.error`：
  转换阶段的具体错误；
- `observed.uncovered`：通过功能回归后的真实 authored 未覆盖行；
- `observed.synthesis_hazards` 与 `observed.tool_output`：综合失败时的源代码位置和工具输出。

收到 `rtl_design_test_failed` 时，不要继续修改 coverage predicate 或 `.ignore`；先修复第一条
失败 TC。收到 `rtl_line_coverage_generation_failed` 时，按上面的 fixture 顺序修复 artifact
生命周期。收到 `rtl_line_coverage_below_threshold` 时，才可以增加有意义的测试或提交有证据的
精确排除。每次修复后都重新调用 Check，不能沿用上一次运行的报告。

## Check 失败诊断与修复顺序

Check 返回的诊断包含 `error_code`、`error`、`observed`、`expected` 和 `next_action`。
先按 `error_code` 处理第一项失败，不要把所有失败同时改动：

- `rtl_design_test_failed`：Python executable spec 已通过，但 RTL 对相同共享 TC 的行为不一致。
  先查看 `observed.failed_cases` 中第一个节点的 phase、exception 和 CK，再用
  `Check stage_args.test_target` 定点复现；检查 pin 宽度/signedness、打包解码、
  `RefreshComb`/`Step` 顺序、reset、握手、latency、舍入和饱和。保持 Spec、测试期望和断言不变，
  修复 RTL 或被证据指向的 adapter 后重新运行完整回归。
- `rtl_line_coverage_generation_failed`：功能回归通过，但 Toffee 没有得到可用的
  `code_coverage.json`/`merged.info`，或报告记录了转换错误。阅读 `observed.artifact_state`
  和 `toffee_report.json:coverages.line.error`，修复 fixture 的覆盖率绑定、dat 文件收尾或
  raw ignore 语法，然后重新运行完整 RTL TC；不要复制旧报告或手写机器 JSON。
- `rtl_line_coverage_below_threshold`：当前 authored-source 覆盖率低于门禁。先把
  `observed.uncovered` 的未覆盖行分成三类，再按类选择提升手段（可混合使用）：

  1. **删除无关 RTL 代码**（最直接，减少覆盖分母）：与 Spec、architecture 或功能合同无关的
     遗留/试验性/不可达代码直接删除；删除前确认 architecture 与 FG/FC/CK 合同不引用它们，
     删除后重跑完整 RTL 回归确认无行为回归。
  2. **增加针对性测试**：为 Spec 中可达但未测的行为增加 directed/boundary/reset/
     sequence/random 共享测试；新测试必须有独立 expected 与真实断言。
  3. **ignore 必要的共享/基础代码**：确实必需但无法逐行触发的公共功能 glue 代码或基础库
     wrapper（例如参数合法性防御分支、综合工具生成的 glue），写入 `.ignore` 和分析
     Markdown proof（标明 proof kind 与精确理由）。

  只有能够追溯证明不可达或非可执行的精确范围才可同步写入 `.ignore` 和分析 Markdown
  proof；不要只依赖增加测试一种手段，也不要为提升数字而 ignore 可达行为。
- `rtl_line_coverage_fixture_invalid`、`rtl_line_coverage_ignore_invalid`、
  `rtl_line_coverage_proof_invalid` 或 `rtl_line_coverage_authored_scope_invalid`：这是
  覆盖率输入/证据合同错误。修复 `artifact`/`location` 指向的文件并重新调用 Check，
  不要降低阈值来绕过验证。

无论哪一种失败，`next_action` 中的步骤是当前阶段的最小修复顺序；只有完整共享 RTL 回归、
当前 authored-source machine coverage 和公开分析报告全部一致后，才可以调用 Complete。

## 原始 ignore 语法

每个非注释行必须指定精确行范围：

```text
*/path/to/source.v:10-20,30-30
```

源码 glob 必须以 `*/` 开始。行号必须是正整数闭区间；单行写成 `30-30`，起始行不能大于
结束行。多个范围用英文逗号连接。注释必须独占一行并以 `#` 开始。不能排除整个用户编写的
源码文件；不属于用户源码的自动生成内容不会进入本阶段统计，无需写入 ignore。

范围只能包含当前 LCOV 中计数为零的真实可执行行。覆盖 JSON 的可视化 span 可能同时包含已覆盖
行和未插桩结构行，不能直接复制成 ignore。若 Checker 报告某些 ignore 行“not currently
uncovered”，先从 `.ignore` 和分析 Markdown 同时删除诊断列出的精确行段，再调用 Check 获取
当前公开的精确未覆盖行。

下面是完整的 `{OUT}/tests/Adder.ignore` 示例：

```text
# Constant default branch retained by the generator but unreachable for legal WIDTH.
*/Adder.v:84-86
# This helper declaration emits no executable hardware statement.
*/Adder.v:102-102
```

## 分析 Markdown 格式

分析文件必须给出当前覆盖结果，并为 `.ignore` 中每个原始模式提供完全相同的标签值。每项
使用以下单行格式：

```text
<LINE_IGNORE>原始模式</LINE_IGNORE>: [proof=证明类型; evidence=工作区路径:起始行-结束行] 精确论证
```

`proof` 只能是：

- `parameter_unreachable`：合法参数或输入域使该分支不可达；`evidence` 指向 README、Spec 或 architecture。
- `state_unreachable`：合法状态与 transaction 序列使该分支不可达；`evidence` 指向 README、Spec 或 architecture。
- `non_executable_structure`：该范围只含声明边界等无可执行硬件语义的结构；`evidence` 指向当前用户编写的 RTL 源码。

`evidence` 必须指向存在且覆盖所引行号的工作区文件。理由要写出从该证据到目标分支的推导。
一个标签只解释一个原始模式，不能有多余或重复标签。理由若承认该行为可达、缺测试、当前
向量未触发、存在 RTL 缺陷或不在当前阶段范围，Checker 会拒绝；此时必须补测试或修正 RTL。

下面是完整的 `{OUT}/Adder_line_coverage_analysis.md` 示例：

```markdown

# Adder RTL 行覆盖分析

## 结果

- 覆盖率：`96.40%`
- 最低要求：`90.00%`
- 机器覆盖报告：`uc_test_report/line_dat/code_coverage.json`

## 精确排除

<LINE_IGNORE>*/Adder.v:84-86</LINE_IGNORE>: [proof=parameter_unreachable; evidence=design/Adder_architecture.md:12-14] `WIDTH` 被限定为 2..64，而该分支条件为 `WIDTH == 0`，所以任何合法实例均无法进入该分支。

<LINE_IGNORE>*/Adder.v:102-102</LINE_IGNORE>: [proof=non_executable_structure; evidence=design/rtl/Adder.v:102-102] 该行仅结束一个 helper 声明，不包含可执行语句、组合赋值、寄存器更新或硬件分支。

## 结论

全部可达且有功能意义的源码行已由 Python/RTL 共用测试验证；上述模式与原始 ignore 文件逐项一致。
```

## 执行顺序

1. 先调用 Check 生成真实覆盖报告，定位未覆盖文件和行。
2. 对照 Spec、architecture 和分支条件，优先补充定向、边界、reset、序列或随机测试。
3. 用 `RunTestCases` 验证修改后的同套测试在 Python backend 通过。
4. 确认每个正常 API 调用都以独立精确期望值作 `==` 比较，再调用 Check 验证 RTL backend 与行覆盖。
5. 仅对证明合法的精确范围同步更新原始 `.ignore` 和带 `proof/evidence` 的分析 Markdown。
6. 覆盖率、完整功能回归和排除分析都通过后调用 Complete。
