
# 九类资产的按需补全与验收

## 1. 目标与操作顺序

为当前 Test Suite 评估 Norm Rules、UDB/Params、RVVI、RVMODEL Macros、Testplan、CTP、
Coverpoints、Sail、Tests。已有内容优先复用；缺少且本轮需要的内容生成或修复；范围外问题
及真实外部阻塞可以报告。不要为填满表格重写正确源码，也不要将缺失的免费软件或可生成源码
当作外部阻塞。Skill 不是执行条件。

1. 在 plan_missing_capabilities 中创建 `intermediate/<Suite>/asset_checklist.yaml`。
   逐类遵守本轮 improve/regenerate 策略，见 `Guide_Doc/ACT4_Run_Guide.md`；导入仓库必须全部登记。
   导入的本地改动是本轮基线，不是本轮修复；重生成不能填 reuse。无需改动允许原样验收。
   `repositories` 包含独立可写的 ACT Git 副本 `act4`；需要修改规范、UDB、RVVI、模型或
   通用平台支持时，先在工作区准备各自固定版本的独立干净 Git 副本，并登记路径。
   不修改共享来源，不把已有未提交修改作为基线。首次普通 `Check()` 在任何源码更改前执行，
   然后 `Complete()`。该清单与 completion_plan 分别描述贡献类型和实施步骤，须保持一致。
2. 按清单实现。一个类别可有多个 item，例如 Sail、Spike、Wally 的宏分别列项；已有部分
   与新增部分分开，不能以一个平台通过代表其他平台。源树中每一项新增、修改、删除、mode
   变化都必须归属 generate/repair，不得改完后宣称 reuse 或 report。
3. 在 verify_completed_capabilities 调用 `Check(stage_args={"action":"validate","timeout":3600})`。
   检查在隔离副本执行，保存日志和真实结果；依赖补丁生成到 `<OUT>/dependency-patches/`。
   不编辑隔离副本、日志或收据来修复问题，回到源资产修正后重新验证。
   重验前撤下上次生成且未被改动的依赖补丁，全部验证通过后才重新交付；不会覆盖自行修改
   或同名的其他补丁。若需保留这些补丁，先移到其他位置。
4. 将 `asset-validation/checklist.md` 的整个 `Asset checklist` 章节放到最终报告摘要之后，
   不改变状态或计数。详细证据仍留在 intermediate；原生 ACT 的 `changes.patch` 独立生成。
   最终普通 Check/Complete 复核当前来源及证据，不重复执行模型或编译命令。

计划通过后不得更换仓库范围、HEAD 或独立预期来源。新增仓库需求应在修改前重新开始输入
规划，而不是改写基线。计划中的动作和检查可完善，但每次更改都需要重新验证。

## 2. 动作、范围及独立依据

每项固定字段为 `id/category/action/required/scope/reason/repository/artifacts/checks/report/oracle`。
category 使用下一节的九个机器标识。id 是唯一小写标识；required 是布尔值。
scope 写清子行为、位宽、目标和平台，reason 说明依据，不写笼统的“已处理”。

| action | 合同 |
| --- | --- |
| reference | 可选共享输入仅用作资料：列出已选原件或冻结的 `inputs/norm-rules.json`，`required: false`，`checks: []`，`report/oracle: null`。核对身份和未改动，不计作兼容性验证 |
| reuse | 实际源文件存在且未被本轮改变；至少执行一次兼容性检查，不只判断文件存在 |
| generate | 在已登记仓库中实际增加源码；履行该类别全部检查，不以空文件算生成 |
| repair | 实际修改或删除原有源码；履行该类别全部检查，验证目标缺陷及其他消费者 |
| report | 留下调查文件；report 包含 reason_code、impact、next_action，不声称已验证或已修复 |
| not_applicable | 仅用于有依据的不适用子范围，required=false，artifacts/checks 为空，report/oracle 为 null；每个核心类别仍须声明其实际必需工作 |

在生成工作流中，Norm Rules、UDB/Params、RVVI、RVMODEL Macros、Sail 只允许修复有证据的既有输入，不能 generate。缺失、范围外或怀疑错误用 report/not_applicable，不得把不可用的共享能力计作通过。仅需引用时用 reference；需要声称实测兼容时仍用 reuse。规则原文与 suite 的规则到覆盖点映射是不同资产。

确需 repair 时，先在未改基线上复现，列出已选择的原文件，在原有 oracle 中增设 `baseline_failure: {check_index: 0, exit_code: 4, message: "实际失败输出中的具体诊断"}`。索引从 0 起，指向同一项内能检出缺陷的类别专属正向检查（如 schema、semantic 或 runtime），不强制语义测试来证明格式错误，输入包括待修原件和独立预期来源。规划阶段的 Check 在隔离的原基线上核对该非零退出码和诊断原文，验证阶段再对候选运行同一检查并要求通过；超时、启动失败或另一条命令的失败不能替代。无此证据不发布修复补丁。

报告的 reason_code 为 `outside_scope`、`external_input`、`commercial_license` 或
`upstream_coordination`。required=true 不能使用 outside_scope；必要项未完成时在最终报告
保留部分范围，并同步 completion_plan 的实际外部限制。不能因不会写生成器而选 report。
Testplan、CTP、Coverpoints、Tests 每类必须至少有一个 required=true 项，不能整体不适用。

generate/repair 必须有 oracle：`method` 为 manual_examples、independent_model 或
upstream_tests；`sources` 列固定的手册例子、外部模型源码或上游测试等工作区内文件，
`explanation` 说明如何得到独立预期。不能把被修改文件或本轮生成的结果当作自己的正确性依据。
其他动作 oracle=null。共享同一错误假设的两个 AI 实现不能互相证明正确。

artifacts 和 inputs 使用工作区相对文件路径，不接受软链接、目录、通配符或路径越界。
仓库不能相互嵌套或与 evidence/patch 输出目录重叠；验证资料不能来自 `.ucagent/`。
修改项的 artifact 必须属于其 repository；复用项可引用冻结规范快照或独立调查文件。

## 3. 每类新增或修复的检查

每个修改项除了下表角色，都必须有 `regression` 和 `negative`。角色是检查的目的，
不是随意给同一个“文件存在”脚本换名字；按固定版本的原生工具、消费者和规范预期实现。

| category | 必需角色 | 应验证什么 |
| --- | --- | --- |
| norm_rules | extract, schema, semantic | 修改真实手册标签/规则源；重建索引，检查唯一 ID、原文对应和规则引用；本地绑定不等于上游标签已合入 |
| udb_params | schema, query, semantic | UDB 原生定义和约束通过 schema；真实消费者查询参数；合法/非法边界符合规范，不能只写 ACT 参数映射 |
| rvvi | producer, consumer, roundtrip | 信号产生、读取、类型/位宽/时序及跨端传递一致；有已知输入/期望轨迹，不能用签名检查代替接口验证 |
| rvmodel_macros | compile, runtime | 对所选目标编译宏、实际执行并观测事件；如结束、故障地址或中断，验证发生和未发生两种情况 |
| testplan | schema, traceability, semantic | 原生计划格式、原始请求和规范追踪，行为/边界/预期完整，不丢子计划 |
| ctp | render, includes | 原生渲染、章节可达性、计划/规则/参数表引用；不是仅匹配章节名 |
| coverpoints | structure, traceability, semantic | 原生结构检查、计划/规则对应，已知正向刺激和错误/未触发刺激的区别；动态商业覆盖另列限制 |
| sail | build, semantic | 编译实际 Sail 源码，用规范边界和独立向量验证扩展语义；Python 模型或 Spike 通过不算 Sail 实现 |
| tests | generate, build, self_check | 原生重生成、非空编译产物、最终自检运行；不能只运行签名采集 ELF，不能将零测试当通过 |

regression 覆盖共享消费者和未修改的相关行为。negative 使用同一验证器及单独的错误
fixture，要求预期非零退出码和具体诊断；不能用缺依赖或命令不可执行来充当成功反例。
对于需要评估“错误实现能否被检出”的语义检查，应加入故障注入/变异，而非只检查格式错误。
RVVI 标准扩展或跨项目接口变更需要上游协调；本地通过不代替协议审查或维护者批准。

每个 check 固定字段：

- kind：上表角色、regression、negative；复用检查可用 inspect。
- argv：直接命令列表，不使用内联 shell/Python、echo/true 等占位命令。
- cwd：工作区相对目录或 `.`。隔离执行保留相同的相对布局，不能引用原工作区绝对路径。
- inputs：真实验证脚本、源码、fixture、配置依赖；正向检查须包含修改的源文件。
  语义/运行/回归检查的输入还必须包含 oracle.sources，实际读取这些独立依据推导或核对预期。
- outputs：`相对路径: 格式`，路径相对隔离工作区。必须位于源码仓库及 asset-validation
  目录之外，每次由命令重新产生，不得与 inputs 重叠。格式为 junit/json/yaml/elf/text，
  以及原生规则索引 norm_rules、原生参数查询列表 udb_parameters。
- exit_code：正向为 0；negative 为 1..125；diagnostic 仅 negative 填具体正则，其他为 null。

semantic、regression、roundtrip、self_check、runtime 必须输出 JUnit，至少一个真实执行且
通过的 testcase，不能全跳过、零测试或含失败。原生工具不直接输出 JUnit 时，编写测试驱动
调用该工具并用真实断言检查结果，再由测试框架输出 JUnit；不手写“passed”替代测试。
norm_rules/extract 必须输出 norm_rules，要求原生 normative_rules 数组及唯一 name/text；
udb_params/query 必须输出 udb_parameters，要求真实消费者返回非空且名称唯一的参数记录。
elf 输出须为非空 RISC-V ELF。native build/render 等可以输出实际 JSON、YAML、文本或二进制
验证摘要；格式正确不证明语义正确，仍必须满足该类别的独立预期、反例和回归。

商业 coverage 可缺失，但覆盖源修改不能免除非商业结构、语义与回归检查。最终分别说明
Pass Sail、动态覆盖率、T-SBI、GCC/Clang；只验证一个配置不能代表全表 Done。

## 4. 完整清单示例

下面是一份完整的九类处理计划：规则仅引用、RVVI 不适用，其余按所需范围验证复用。它不是已运行证据。Example 路径及脚本均需
替换成实际 suite 的来源和原生验证入口。validate_existing.py 必须真实调用各类消费者并检查
结果，不能直接输出样例 JSON。无必要修改时不应为了这个检查创建新的模型或平台支持。
一个类别有不同处置时增加独立 item，不替换掉原有范围。

```yaml
schema_version: 1
suite: Example
repositories:
  act4: riscv-arch-test
  udb: capabilities/udb
items:
  - id: norm_rules
    category: norm_rules
    action: reference
    required: false
    scope: Published rules cited by the Example testplan
    reason: Use the pinned rule index as a reference; no independent check of the rule implementation is claimed
    repository: null
    artifacts: [act4_assets/intermediate/Example/inputs/norm-rules.json]
    report: null
    oracle: null
    checks: []
  - &base
    id: udb_params
    category: udb_params
    action: reuse
    required: true
    scope: Existing MXLEN definition used by the selected target
    reason: UDB query and boundary constraints already match the suite
    repository: udb
    artifacts: [capabilities/udb/params/MXLEN.yaml]
    oracle: null
    report: null
    checks:
      - &inspection
        kind: inspect
        cwd: .
        argv: [python, validate_existing.py, udb_params, results/udb_params.json]
        inputs: [validate_existing.py, capabilities/udb/params/MXLEN.yaml]
        outputs: {results/udb_params.json: json}
        exit_code: 0
        diagnostic: null
  - <<: *base
    id: rvvi
    category: rvvi
    action: not_applicable
    required: false
    scope: Trace interface changes for the selected self-checking suite
    reason: This run uses architectural signatures and makes no RVVI verification claim
    repository: null
    artifacts: []
    checks: []
  - <<: *base
    id: rvmodel_macros
    category: rvmodel_macros
    scope: Selected target macros
    reason: Existing target adapter provides the required events
    repository: act4
    artifacts: [riscv-arch-test/config/example/model_test.h]
    checks:
      - <<: *inspection
        argv: [python, validate_existing.py, rvmodel_macros, results/macros.json]
        inputs: [validate_existing.py, riscv-arch-test/config/example/model_test.h]
        outputs: {results/macros.json: json}
  - <<: *base
    id: testplan
    category: testplan
    scope: Example instruction and width matrix
    reason: Existing plan covers the independently derived requests
    repository: act4
    artifacts: [riscv-arch-test/testplans/Example.csv]
    checks:
      - <<: *inspection
        argv: [python, validate_existing.py, testplan, results/testplan.json]
        inputs: [validate_existing.py, riscv-arch-test/testplans/Example.csv]
        outputs: {results/testplan.json: json}
  - <<: *base
    id: ctp
    category: ctp
    scope: Example chapter and generated rule tables
    reason: Existing chapter renders the selected plan and mapping
    repository: act4
    artifacts: [riscv-arch-test/docs/ctp/src/example.adoc]
    checks:
      - <<: *inspection
        argv: [python, validate_existing.py, ctp, results/ctp.json]
        inputs: [validate_existing.py, riscv-arch-test/docs/ctp/src/example.adoc]
        outputs: {results/ctp.json: json}
  - <<: *base
    id: coverpoints
    category: coverpoints
    scope: Example architectural coverage
    reason: Existing targets match the plan and known outcome partitions
    repository: act4
    artifacts: [riscv-arch-test/coverpoints/unpriv/Example_coverage.svh]
    checks:
      - <<: *inspection
        argv: [python, validate_existing.py, coverpoints, results/coverage.json]
        inputs: [validate_existing.py, riscv-arch-test/coverpoints/unpriv/Example_coverage.svh]
        outputs: {results/coverage.json: json}
  - <<: *base
    id: sail
    category: sail
    scope: Example support in the selected Sail release
    reason: Native smoke cases confirm this model supports the selected behavior
    repository: act4
    artifacts: [riscv-arch-test/config/example/sail.json]
    checks:
      - <<: *inspection
        argv: [python, validate_existing.py, sail, results/sail.json]
        inputs: [validate_existing.py, riscv-arch-test/config/example/sail.json]
        outputs: {results/sail.json: json}
  - <<: *base
    id: tests
    category: tests
    scope: Example self-checking tests on the selected configuration
    reason: Existing generator and generated tests exercise the plan
    repository: act4
    artifacts: [riscv-arch-test/generators/testgen/src/testgen/coverpoints/example.py]
    checks:
      - <<: *inspection
        argv: [python, validate_existing.py, tests, results/tests.json]
        inputs: [validate_existing.py, riscv-arch-test/generators/testgen/src/testgen/coverpoints/example.py]
        outputs: {results/tests.json: json}
```

修改项须将 action 改为 generate 或 repair，补充独立 oracle，并用
`Guide_Doc/ACT4_Checker_Guide/ACT4AssetChecklistChecker.md section 3` 的全部角色
替换 inspect。例如一个 Sail 修复项有 build、semantic、regression、negative，不能只有
“模型可执行”的版本探测。标准、UDB 或 Sail 的修改在对应独立仓库形成补丁；上游合入仍需
维护者审查，不能在清单中伪称已合入。

## 5. 结果与边界

检查会比较基线与实际文件变化，要求变更归属，执行声明的类别检查，核验反例诊断、非空
产物及非零测试，并将来源、环境、脚本、日志、结果和补丁绑定到本轮证据。变化后须重新验证。
report 不计作 verified；required 的 report 会令资产范围不完整，最终 scope_completion
不能同时声称完整。清单中的 checked 仅表示记录的检查通过，不是任意实现正确性的数学证明。
本地测试通过、上游认可、完整覆盖率、真实 DUT 运行分别报告。

依赖补丁与 ACT suite 补丁分开。通用框架增强只在独立副本验证，不绕过原生 ACT 的受保护
源码门槛；补丁尚未集成时，不能把独立试验写成正式原生验证通过。把依赖补丁登记到文件清单，
在 final.md 中链接交付，不重复打包验证日志。
