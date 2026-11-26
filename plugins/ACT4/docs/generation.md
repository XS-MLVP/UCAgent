
# ACT4 资产生成

提供两个独立入口：状态序列/异常场景使用 `privileged-suite-generation`，无 trap 的表驱动
指令测试使用 `unprivileged-suite-generation`。这是生成机制而非 ISA 类别的划分：DeveloperGuide
中的 ZicsrF 等非规则化非特权测试也可采用 priv-style。两者共享资源准备、规范快照和原生贡献验收，但不强行共用
测试计划格式或 generator。已有模块通过同一生成入口进行 [增量审查和修复](review.md)。
共用编写约定在运行时 `Guide_Doc/ACT4_Asset_Authoring_Guide.md`，设计记录示例在
`Guide_Doc/act4_template/native_asset_design_template.md`；不需要启用 Skill。
先按 [AI agent 执行指南](agent-run.md) 检查 UCAgent、插件和 Codex 启动条件，再按本文执行。

按进度表 Test Suite 列指定需求时，参考 [规范驱动补全说明](support-boundaries.md)
和 [逐项工作清单](support-inventory.csv)。AI 根据规范和原生入口解析位宽变体、组合场景及
供应方名称；CLI 的 DUT 必须选择 [Test Suite 目录](test-suites.md) 中的 CLI target，
启动时先校验并在终端显示原名、来源和状态。原始需求及映射范围记录在补全计划中。
缺现成资产、模板、免费工具、模型或适配器属于本轮实施工作，不是“不支持”。

## 1. 准备运行配置

使用 [统一 YAML 配置](run-configuration.md) 指定目标、路线、工作区、版本、每类来源与策略及限制。
不要预先在工作区复制 ACT 仓库：资源阶段共享下载，独立 ISA 计划验收后才按所选来源建立可写副本。
外部干净源码用 upstream 配置；本地未提交成果或上轮输出用类别级 source: local。

## 2. 运行生成

```bash
act4-run plugins/ACT4/examples/generation.yaml --print-command
act4-run plugins/ACT4/examples/generation.yaml
```

启动前按 [AI agent 执行指南](agent-run.md) 准备 UCAgent、插件及模型认证。
最终输出在配置的 workspace/output 下；恢复时使用相同配置，新策略使用新工作区。

### 非特权指令生成

在同一配置格式中选择 workflow: unprivileged-suite-generation，并设置相应 suite。
权威计划是原生 testplans CSV，包括 XLEN、ExtraExtensions 和 coverpoint/variant。
场景型入口使用原生 YAML 及状态序列生成器；两条路线都可复用、修复或重生成已有资产。

## 3. 工作流与产物

| 阶段 | 主要工作 |
| --- | --- |
| 独立 ISA 计划与来源导入 | 资源准备后先冻结应测行为，再选择、导入和隔离输入 |
| 基线审查 | 对照独立计划与允许复用资产，记录缺陷和生成项 |
| 生成后复验 | 收集真实 after 证据；报告区分来源策略与实际结果 |
| prepare_resources | 复用固定版本源码，为生成准备独立可写副本 |
| prepare_environment | 复用工具、安装缺项并复验，保留环境报告 |
| prepare_generation_inputs | 捕获计划和规范；优先用公开规则，缺标签时绑定真实原文并追踪待发布规则 |
| plan_missing_capabilities | 独立从规范确定完整范围；把缺失资产、免费模型/适配器及环境列为实施任务 |
| 01 coverpoints | 冻结 ACT4 基线，完善原生计划并生成 coverage；CSV/Markdown 自动派生 |
| 02 norm mapping | 建立 normative rule 到 coverpoint 的映射 |
| 03 VM resources | 按实际子场景建立 VM/resource 契约与能力处置 |
| 04 generator | 用冻结版本的原生 API 生成正式汇编；逐个必验配置预检选中的源，并确认并集覆盖全部正式源，不运行 ELF |
| 05 build | 每种必验 XLEN 先跑代表用例，再逐配置核对适用源的 ELF、签名、结果和签名日志；最终模型执行与 coverage 分开取证 |
| verify_completed_capabilities | 补齐全部可生成项，实际执行各项检查，核验文件、命令和日志 |
| 06 contribution | 整理贡献集，在干净副本复核独立生成和相关本地 CI 步骤 |
| validate_native_contribution | 只应用贡献集，核对生成一致性、hooks、参数/CTP、选定原生配置编译运行 |
| 07 final report | 生成最终报告并核对审查、状态及文件清单 |

以下路径均相对工作区，`<OUT>` 对应 `--output`，`<Suite>` 对应 suite 名：

| 路径 | 内容 |
| --- | --- |
| `<OUT>/intermediate/<Suite>/` | CSV、人类 testplan、coverage 草稿、VM/resource 和 coverage intent 契约 |
| `<OUT>/intermediate/<Suite>/inputs/` | 原生计划、规范、规则 JSON 和固定来源收据 |
| `<OUT>/intermediate/<Suite>/completion_plan.yaml` | 用户范围到原生入口、各类缺项的实施与验证计划 |
| `<OUT>/intermediate/<Suite>/completion-validation/` | 补全任务的实际命令结果、日志和可复核收据 |
| `<OUT>/intermediate/<Suite>/capabilities/` | 新模型、激励/观察适配器、独立框架增强及其回归；不混入 suite 补丁 |
| `<OUT>/final.md` | 人工复核入口、结论、复现命令及限制 |
| `<OUT>/changes.patch` | 仅包含 contribution_set 的贡献补丁，不混入构建与工具产物 |
| `<OUT>/dependency-patches/` | 按需生成、独立验证的规范/UDB/RVVI/平台支持/Sail 等仓库补丁，不混入 ACT suite patch |
| `<OUT>/intermediate/<Suite>/asset_checklist.yaml` | 九类资产的复用、生成、修复、报告或不适用决策及类别检查 |
| `<OUT>/intermediate/<Suite>/asset-validation/` | 隔离检查日志、结果收据及供 final.md 引用的 checklist |
| `<OUT>/intermediate/<Suite>/reports/` | 累积 AI review、validation state、基线、switch audit、file manifest 和 checker 报告 |
| `<OUT>/intermediate/<Suite>/experimental/` | 与正式生成链隔离的实验资产 |
| `riscv-arch-test/coverpoints/{priv,unpriv,norm,param}/` | 正式 coverage/init 和 normative mapping |
| `asset_contract.yaml` 的 `extension_sources` 所列原生路径 | 正式 generator、模板等；允许已有、共享、子目录实现及独立新配置 |
| `riscv-arch-test/tests/priv/<Suite>/` | ACT4 原生生成的汇编测试 |
| `riscv-arch-test/work_itgen_<Suite>/` | 独立构建目录、ELF、签名和参考模型日志 |

先查看最终报告，再按 Report index 检查 validation state、AI review、清单及实际运行日志。
`approved_with_limitations`、`contribution_ready`、参考模型执行和 Sail/RVVI coverage
表示不同范围的结论。未运行的工具、未验证的目标、框架能力缺口和实验内容必须保留限制，
不得宣称外部 DUT 验证、全量认证、远程 CI 通过或人工审批。
参考模型失败不能直接缩减资产生成范围；缺免费验证能力时先安装或实现并独立验证。
商业许可可选；真实外部输入缺失时说明具体子场景与用户帮助请求。正式 ACT 副本中的
受保护核心代码变化仍阻塞；确需通用增强时生成独立补丁与回归，在隔离副本验证。

补全任务的验收方法、完整计划示例和最终 `scope_completion` 结果见
[补全运行指南](../src/ucagent_act4/Guide_Doc/ACT4_Checker_Guide/ACT4GenerationCompletionChecker.md)。
该结果与原生资产的 `generation_result` 分开，不能用资产文件齐全宣称完整执行或覆盖率。

具体阶段契约见[运行指南](../src/ucagent_act4/Guide_Doc/ACT4_Privileged_Suite_Workflow_Guide.md)，
checker 边界见[checker 总览](../src/ucagent_act4/Guide_Doc/ACT4_Checker_Guide/README.md)。

## 4. 贡献边界与结论

两种流程均交付原生计划、规范映射、条件适用的参数映射、CTP 集成和对应生成源码。
生成 `.S` 是否随源码贡献遵循固定 ACT 的 Git tracked/ignore 规则，不再一概排除。
测试修复仍在 generator 中完成并重新生成；ELF、日志、工具和本地证据不进入贡献 patch。

最终报告区分资产齐备、实际验证、人工提交前提。真实原生验证收据与 generation_result
摘要须一致。免费原生依赖缺失时安装或补齐后重试；商业许可可选，未执行的验证如实记录。
命令失败和零 ELF 不是通过；DCO、加密签名和维护者审批
由贡献者完成，不由 AI 冒充。suite 级原生验证不等于完整上游 CI，尤其共享模板/decoder
变化需扩大回归。公开规则发布版本与 manual HEAD 独立，规则文本仍需人工/语义核对。

共同契约和完整示例见 [原生生成指南](../src/ucagent_act4/Guide_Doc/ACT4_Generation_Guide.md)。

## 5. 九类资产的按需补全

两个生成工作流均评估九类资产，但不是九项生成任务。Testplan、CTP、Coverpoints、Tests 按 suite 需要复用、生成或修复；Norm Rules、UDB/Params、RVVI、RVMODEL Macros、Sail 是共享输入，默认不改。只有原基线可复现、候选修复通过同一检查时才交付其修复。仅作参考的资料不要求额外执行兼容性测试，也不报告为通过。真实外部阻塞和
范围外问题可以报告。不是每轮都重写九类资产，也不能以 ACT 参数映射代替 UDB 定义、
以签名观察代替 RVVI 信号、以 Python 模型或 Spike 代替 Sail 实现。

在 `plan_missing_capabilities` 阶段先冻结清单中独立 Git 仓库的干净基线，再进入源码修改。每类变更有专属检查要求，
并要求独立预期来源、反例、回归和实际非空结果。缺项补全验收时，在隔离副本执行这些检查；
源码、模式、脚本、环境、输出或补丁变化会使既有证据失效。最终报告摘要后必须包含检查结果
生成的九类 checklist，分别显示 referenced（仅核对来源）、reused、generated、repaired、reported、not applicable、范围和
未解决事项的下一步。required 的报告项不能被写成完整范围已完成。

配套项目修改按仓库交付独立补丁，既有原生 ACT 验收与源码保护门槛不变，review 和香山
工作流不接入这套新增门槛。商业动态 coverage 仍可选；本地类别检查不代替维护者审查、
上游合入、全量 CI、100% 动态覆盖或真实 DUT 认证，也不是任意程序正确性的形式化证明。
操作和完整格式见 [九类资产验收指南](../src/ucagent_act4/Guide_Doc/ACT4_Checker_Guide/ACT4AssetChecklistChecker.md)。
