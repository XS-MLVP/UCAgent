
# 从规范补齐测试资产与验证能力

## 1. 目标与边界

根据用户指定的 Test Suite 和规范原文，补齐 ACT 所需的适用资产。已有文件是可复用输入，
不是支持条件。先从规范独立列出行为、前置条件、边界、交互、刺激和预期，再核对上游资产。
不要因为缺计划、CTP、coverpoint、生成器、模板、格式器、解码器或参数映射而排除模块。

缺少可由软件实现的能力也属于任务：安装免费工具；编写适配器、激励驱动、配置、构建脚本、
参考模型或检查程序。模型必须另有验证依据，例如手工推导的边界结果、公开模型交叉检查、
规范例子和故障注入，不能以两个共享同一错误假设的 AI 实现相互证明正确。

商业工具只探测和记录，不自动购买许可。真实硬件、目标参数、访问授权和规范歧义无法靠
猜测补齐；必须写清具体缺什么、影响哪些行为、已经调查了什么、希望用户提供什么。
外部输入尚未取得时继续完成不依赖它的工作，报告范围为部分完成，不能称测试全部通过。
共享规则、参数、模型语义或接口确需上游协调时，使用 `external_input` 和 `reason_code: upstream_coordination`，登记调查文件、受影响行为和准确请求。该结论不代表验证通过，也不免除 suite 自身的计划、映射、生成器和构建。

## 2. 原生入口和源码边界

- 用户表格原名可能对应一个父计划、多个 SEW 变体或跨扩展子场景。记录原始需求与实际
  `native_suites`，保留位宽、特权级和额外扩展条件，不能只删名字后缀。
- 非特权输入可在 prepare 时显式提供 `plan_paths`，例如 E 使用 `["testplans/I.csv"]`。
  `native_suites` 是原生 `make EXTENSIONS=` 的实际选择；不要把父 CSV 名冒充展开后的入口。
- 特权计划为空可以补写；既有描述性名称可用 `source_request_map` 映射到完成后的明确点名，
  不能丢掉原场景。配套 `testplans/priv/*.csv` 同样要保留和补齐。
- `extension_sources` 列实际修改的生成器，包括已有、共享和子目录实现；不强制复制为同名
  顶层文件。共享扩展点修改必须列出其他消费者和相应回归。
- ACT 通用执行环境、签名、验收逻辑不能为了测试通过而修改。确需增强它们时，在
  `intermediate/<Suite>/capabilities/` 生成独立补丁、最小复现和回归，使用独立副本验证。
  这不是“只写建议”：可以生成和验证增强代码，但必须与 suite 的贡献补丁分开，
  原生 suite 验证未通过时不能宣称该增强已集成或当前工作流已完整完成。

## 3. 补全计划

同时按 `Guide_Doc/ACT4_Checker_Guide/ACT4AssetChecklistChecker.md` 建立九类资产清单，
在本阶段首次 Check 前登记干净来源，按需生成/修复，不把规范标注、UDB、RVVI、平台宏或
Sail 的缺项隐含在泛化模型项里。必要报告项同步这里的实际外部限制；无关范围可以报告而不
扩张本轮任务。资产类型验收与实施步骤验收共同决定结论，不能用其中之一替代另一项。

在 `intermediate/<Suite>/completion_plan.yaml` 覆盖以下 area：
`specification`、`testplan`、`coverage`、`norm_mapping`、`parameters`、`ctp`、`generator`、
`build`、`reference_model`、`stimulus`、`observation`。一个 area 可有多个工作项。

每项有稳定 `id`、`area`、`action`、`scope`、`rationale`、`artifacts` 和 `checks`：

- `reuse` / `generate`：均须列出实际文件与可执行检查，计划阶段允许文件尚未生成。
- `not_applicable`：只能用于真正不适用的要求，写明规范依据，文件和检查为空。
  不能用它替代规范、测试计划、生成器、运行和观察等核心工作。
- `commercial_optional`：额外记录 `tool: questa|vcs|xcelium`，checks 为空。仅免除相应商业运行，
  不免除覆盖源码、测试生成、编译及可用的非商业验证。
- `external_input`：额外提供 `reason_code: target_information|specification_ambiguity|permission|physical_device`
  和具体 `request`，artifacts 指向已完成的调查证据；不能用来表示缺 Python 生成器或免费工具。

所有 artifacts、checks.inputs 和检查 cwd 都是工作区内的明确相对路径，不使用通配符和软链接。
checks.inputs 列验证脚本及其实际源码、fixture、配置依赖；只读依赖必须完整，日志等检查输出不能列入。
检查应验证具体结果和非零产物，不能只打印“通过”、测试文件存在或复述设计目标。

`finding_checks` 逐项覆盖已验收初审中除 `not_a_defect` 外的所有 F 编号；没有时写 `{}`。
`behavior` 绑定本 suite 生成汇编中的实际用例标签，以及该标签至下一标签间按顺序出现的刺激和观察；
需要多种行为就列多个 cases。指令名或宏名写全，操作数可用 `*`，要区分寄存器时写明寄存器。
例如要求向量存储时，只有向量加载不能验收；要求读取弹栈后的指针时，别的用例有签名更新也不算。
这只证明汇编有对应序列，不证明所有配置都走过该路径或命中覆盖。`configs` 使用 `asset_contract.yaml` 中的原生配置路径。
`artifact` 和 `execution` 各用本 finding 专属的 plan item，`cases: []`；纯文档可用 `configs: []`。
映射检查应断言具体规则与覆盖点的对应，执行检查应核对该配置和非零产物，不能复用一个全局通过计数。
计划 Complete 后不要改判据；可以补充真实产物与检查，不能删换已接受的制品或执行验收命令。在生成器修复后重新生成并在原生验证阶段重验。已获准部分交付的缺失见证仍列入 `missing_witnesses`，不可报 fixed。

下面是完整结构示例，展示一个小型指令 suite 的补全计划，不是已执行的测试证据。
`verify_assets.py`、模型、配置和测试也由本轮任务实际实现并核验；示例路径不能当作已有文件。

```yaml
schema_version: 1
suite: Example
requested_scope: Example instruction semantics on RV32 and RV64
finding_checks:
  F1:
    item: stimulus
    kind: behavior
    configs: [config/sail/sail-rv64-max/test_config.yaml]
    cases:
      - source: riscv-arch-test/tests/rv64i/Example/Example-add-00.S
        label: example_add_boundary
        stimulus: ['add x8, *']
        observation: ['RVTEST_SIGUPD(*x8*)']
items:
  - id: source
    area: specification
    action: reuse
    scope: Instruction definition and arithmetic width
    rationale: Pinned original text supplies behavior and constraints
    artifacts: [act4_assets/intermediate/Example/inputs/manual/src/example.adoc]
    checks: [{argv: [python, verify_assets.py, source], cwd: ., inputs: [verify_assets.py]}]
  - id: plan
    area: testplan
    action: generate
    scope: All operand and width partitions
    rationale: Build the plan independently from the specification
    artifacts: [riscv-arch-test/testplans/Example.csv]
    checks: [{argv: [python, verify_assets.py, plan], cwd: ., inputs: [verify_assets.py]}]
  - id: coverage
    area: coverage
    action: generate
    scope: Planned operand and outcome bins
    rationale: Generate native coverage and verify each planned target exists
    artifacts: [riscv-arch-test/coverpoints/unpriv/Example_coverage.svh]
    checks: [{argv: [python, verify_assets.py, coverage], cwd: ., inputs: [verify_assets.py]}]
  - id: rules
    area: norm_mapping
    action: generate
    scope: Every behavioral rule and coverage target
    rationale: Preserve source-bound traceability
    artifacts: [riscv-arch-test/coverpoints/norm/Example.yaml]
    checks: [{argv: [python, verify_assets.py, mapping], cwd: ., inputs: [verify_assets.py]}]
  - id: parameters
    area: parameters
    action: generate
    scope: MXLEN controls operand width
    rationale: XLEN affects both test selection and expected results
    artifacts: [riscv-arch-test/coverpoints/param/Example.yaml]
    checks: [{argv: [python, verify_assets.py, parameters], cwd: ., inputs: [verify_assets.py]}]
  - id: ctp
    area: ctp
    action: generate
    scope: Reachable plan and normative tables
    rationale: Expose the complete plan through the native CTP
    artifacts: [riscv-arch-test/docs/ctp/src/example.adoc]
    checks: [{argv: [python, verify_assets.py, ctp], cwd: ., inputs: [verify_assets.py]}]
  - id: generator
    area: generator
    action: generate
    scope: Operand edge cases and expected signature updates
    rationale: Implement the missing native coverpoint generator
    artifacts: [riscv-arch-test/generators/testgen/src/testgen/coverpoints/example.py]
    checks: [{argv: [python, verify_assets.py, generator], cwd: ., inputs: [verify_assets.py]}]
  - id: build
    area: build
    action: reuse
    scope: Compile nonempty RV32 and RV64 test selections
    rationale: Use installed compilers and native configuration
    artifacts: [riscv-arch-test/Makefile]
    checks: [{argv: [python, verify_assets.py, build], cwd: ., inputs: [verify_assets.py]}]
  - id: oracle
    area: reference_model
    action: generate
    scope: Independently checked arithmetic results
    rationale: Validate the new oracle with manual edge cases and mutation tests
    artifacts: [act4_assets/intermediate/Example/capabilities/reference.py]
    checks: [{argv: [python, verify_assets.py, reference], cwd: ., inputs: [verify_assets.py]}]
  - id: stimulus
    area: stimulus
    action: reuse
    scope: Registers initialized through native assembly
    rationale: No external bus driver is needed for this instruction
    artifacts: [riscv-arch-test/tests/rv64i/Example/Example-add-00.S]
    checks: [{argv: [python, verify_assets.py, stimulus], cwd: ., inputs: [verify_assets.py]}]
  - id: observation
    area: observation
    action: reuse
    scope: Destination values observed through native signatures
    rationale: Verify both expected passes and deliberately incorrect results
    artifacts: [act4_assets/intermediate/Example/capabilities/test_observation.py]
    checks: [{argv: [python, verify_assets.py, observation], cwd: ., inputs: [verify_assets.py]}]
```

## 4. 执行与交付

计划检查通过后，逐项实施。不要等到最后才修复会阻塞前面阶段的依赖。
在 verify_completed_capabilities 阶段调用：

```text
Check(stage_args={"action":"validate","timeout":3600})
Complete()
```

验证命令实际执行，日志、来源摘要和结果写入 `completion-validation/`。免费依赖缺失或
检查失败必须修复，不能改成商业可选。文件、计划或环境变化后重新验证。

最终 `final.md` 先用自然语言解释成果和限制，再放与验证结果完全一致的 `scope_completion`：

```yaml
scope_completion:
  requested_scope: Example instruction semantics on RV32 and RV64
  items: 11
  scope_complete: true
  limitations: []
```

该结论只说明补全计划的执行范围，不等于覆盖率、全仓 CI 或 DUT 认证。原生生成、编译与
运行的 `generation_result` 仍按 `Guide_Doc/ACT4_Generation_Guide.md` 单独报告。
中间日志和调查证据只链接到子目录，不在交付根目录复制多份报告。无 Skill 目录时同样执行
本指南、公开工具和检查命令，不得跳过任何工作。
