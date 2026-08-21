# Stage 01: design_workflow_build_config

## 阶段目标

根据已冻结的需求计划生成并交叉验证 WorkflowBuilder 配置。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{WFGEN_DIR}/input_example_manifest.yaml`
- `{WFGEN_DIR}/workflow_implementation_plan.md`
- `{WFGEN_DIR}/workflow_build_schema.yaml`
- `Guide_Doc/workflow_build_yaml_guide.md`

## 详细执行步骤

1. 第1步：依次使用 ReadTextFile 完整读取 {WFGEN_DIR}/requirements_manifest.yaml、 {WFGEN_DIR}/input_example_manifest.yaml、{WFGEN_DIR}/workflow_implementation_plan.md、 {WFGEN_DIR}/workflow_build_schema.yaml 和 Guide_Doc/workflow_build_yaml_guide.md。 前三份文件是上一阶段已经通过检查的规划基线；后两份规定构建配置结构、模板名称和 Checker 源码契约。 禁止在本阶段扩充或重命名 manifest 组件；若确实发现需求遗漏，必须先同步更新 manifest 和实现计划并重新检查。
2. 第2步：创建 {BUILD_CONFIG}，其 workflow_spec.stages 和 files 必须覆盖 manifest 中全部阶段、Guide_Doc、用户文档、用户可复用模板文件和配置；required_configs 中每个 path 必须原样出现在 files.public，禁止使用 config_inc.yaml 等不同名字代替 config/inc.yaml。必须按 workflow_build_schema.yaml 声明 runtime_contract，并固定 input_root=input、output_root=output、example_target=example。根目录 config.yaml 是唯一主流程入口，同时声明 config/inc.yaml；eval.yaml 仅在 manifest 明确要求独立评估时加入，禁止声明 config/default.yaml 或 config/empty.yaml。files.public 和 required_deliverables 必须显式包含 setup.py、config/environment.schema.yaml、requirements.txt 及六份固定 docs 用户文档。workflow_spec.stages 的 name 可使用便于配置引用的稳定英文标识；若 requirements_manifest.required_stages 使用中文业务名称，则每个阶段必须同时用 label 原样记录对应中文名称。
3. 第2.1步：{BUILD_CONFIG} 必须包含 workflow、root、runtime_contract、directories、files、makefile、config、workflow_spec 和 acceptance 这些根级字段；acceptance 禁止省略，且至少包含 required_public_files 和 required_public_dirs 两个列表。
4. 第2.2步：files.internal 必须声明 .workflow/acceptance_rules.yaml，template 必须是 acceptance_rules_basic；acceptance.required_public_files 必须覆盖 setup.py、config/environment.schema.yaml、requirements.txt、docs/README.md、docs/01快速启动.md、docs/02输入输出.md、docs/03步骤及检查.md、docs/04开发者文档-tools.md、docs/05开发者文档-checkers.md、config.yaml、config/inc.yaml 以及 runtime_contract.required_input 对应的 input/example/ 文件；acceptance.required_public_dirs 必须覆盖 input、input/example、output、docs、Guide_Doc 和根级 tmp。
5. 第2.3步：workflow_spec 中每个 reference_files 与 output_files 项都必须是具体文件。reference_files 只能来自 files.public/files.internal 声明的固定文件、runtime_contract 中 type=file 的明确用户输入，或严格早于当前阶段的具体 output_files；任何目录、通配符、不带文件名的目录形状路径以及“运行时也许会出现”的日志都禁止填写。目录型产物必须规划一个 manifest、summary 或 report 文件作为阶段输出证据。
5. 第2.3步：检查 {BUILD_CONFIG} 中所有 files.public/files.internal 的 template，必须属于 Guide_Doc/workflow_build_yaml_guide.md 的支持集合。禁止使用未知模板名，禁止让 Builder 生成空文件。
6. 第3步：workflow_spec 必须在初次构建前完整规划全部业务 Checker 和全部业务阶段。checkers 使用中心化定义，每项必须包含唯一 name、详细 description、entry.file/class_name/method、完整 source、 显式 fixtures 和 tests；source 中入口类必须继承 Checker，do_check 方法体第一条语句必须是非空 docstring， tests 至少包含一个 expected_pass=true 和一个 expected_pass=false。fixture 只能写入 .workflow/checker_tests/cases/<CheckerName>/。Checker 参数要求目录时，tests.args 必须指向目录，fixtures 必须分别声明目录下的实际文件，禁止用单个 txt 文件冒充目录。workflow_spec.stages 每项必须声明 description、 reference_files、output_files 和 checker 绑定及 args；Checker 路径参数只能引用当前或更早阶段的输出及静态输入，禁止引用未来阶段才产生的报告。required_checkers 必须与中心 Checker 名称逐项一致，每个 Checker 至少绑定一个阶段。禁止提交缺少这些字段的旧格式 workflow_build.yaml。
7. 第4步：配置必须包含子工作流运行所需的 Guide_Doc/overview.md、Guide_Doc/environment_setup.md、Guide_Doc/operation.md 或真实业务阶段 GuideDoc、内部 tool/checker 检查器、MCP 测试入口，以及 install.py、.install/README.md、.install/manifest.json 迁移设施。`directories.internal` 必须显式包含 `.workflow/tool_tests/logs`，因为工具 direct runner 和 Stage 03 基础设施 Checker 都把它作为固定日志目录；Builder 也会为兼容旧配置主动补建该目录。禁止默认包含 Guide_Doc/tool_generation.md 和 Guide_Doc/checker_generation.md；这些是 WFB 生成工具链的参考文档，应使用当前 WFB 的 Guide_Doc/tool_generation_guide.md 和 Guide_Doc/checker_generation_guide.md。
8. 第5步：确认 root.path 精确为 `{TEST_WORKFLOW_ROOT}`，root.overwrite 为 false，所有输出位于 {OUT} 或 {WFGEN_DIR}。禁止添加 `./`，也禁止使用 workflow.name 作为 root.path；产品名与固定交付目录不是同一个概念。调用 Builder 前必须先通过带 `expected_root={TEST_WORKFLOW_ROOT}` 的 WorkflowBuildConfigChecker，不能先生成错误目录再修正。
9. 第5.1步：在 Complete 前必须确认 {BUILD_CONFIG} 能被 YAML parser 正常解析。解析后必须逐项确认根级 acceptance 存在， files.internal 中存在 .workflow/acceptance_rules.yaml，且全部 template 名称来自 Guide_Doc/workflow_build_yaml_guide.md 的支持表。
10. 第5.1.1步：逐项比较 runtime_contract.required_input、Makefile 的 prepare_input 检查和 acceptance.required_public_files/dirs。Makefile 不得强制检查未声明的输入；每个声明为必需的 file/directory 都必须有对应示例和 acceptance 路径。特别检查 metadata、checksums.sha256 等固定输入，禁止 README、Makefile、manifest 三处出现不同必需级别。
11. 第5.2步：只有五份 reference_files 都已被 ReadTextFile 读取且 {BUILD_CONFIG} 解析成功后，才允许使用 Check 预跑本阶段 checker；如果 checker 失败，只修改其明确指出的构建配置问题。禁止为迁就 workflow_build.yaml 单方面改变 manifest 或实现计划。
12. 第6步：使用 SetCurrentStageJournal 记录阶段数、Checker 数、声明文件数、schema 校验结果和配置路径，然后 Complete。

## 关键文件的最小可通过版本

`workflow_build.yaml` 不能只列名称。最小 Checker 必须带实现、docstring、正反 fixture、测试和阶段绑定：

```yaml
root:
  path: workflow
  overwrite: false
workflow_spec:
  checkers:
    - name: ResultChecker
      description: 检查结构化结果状态和证据文件
      entry: {file: checkers/result_checker.py, class_name: ResultChecker, method: do_check}
      source: |
        class ResultChecker(Checker):
            def do_check(self, timeout=0, **kwargs):
                """Validate structured result evidence."""
                return True, {"message": "fixture"}
      fixtures:
        - {path: .workflow/checker_tests/cases/ResultChecker/pass.json, content: "{\"status\": \"passed\"}"}
        - {path: .workflow/checker_tests/cases/ResultChecker/fail.json, content: "{\"status\": \"failed\"}"}
      tests:
        - {fixture: .workflow/checker_tests/cases/ResultChecker/pass.json, expected_pass: true}
        - {fixture: .workflow/checker_tests/cases/ResultChecker/fail.json, expected_pass: false}
  stages:
    - name: analyze
      description: 分析并验证输入
      reference_files: [input/{DUT}/requirements.md]
      output_files: ["{OUT}/{DUT}/analysis/result.json"]
      checker: [{name: ResultChecker, args: {}}]
```

同时必须声明 workflow、root、runtime_contract、directories、files、makefile、config 和 acceptance；全部模板名必须来自支持表。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `design_workflow_build_config` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_build_config_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `initial_build_requirement_coverage`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| Stage 1 结构检查通过但 Stage 2 的 `test_checkers` 失败 | 正向 fixture 的真实类型与 Checker 参数不一致，例如源码要求目录而测试传入 `valid_input.txt` | 在 `{BUILD_CONFIG}` 中用多个 fixture 文件构成目录，并让测试参数指向其父目录；启用 `run_planned_checker_tests` 后必须在 Stage 1 临时预检通过，禁止只修生成侧 spec |
| 生成工作流运行时某阶段必然报告结果文件不存在 | 阶段 Checker 参数绑定了后续阶段才声明的输出，例如 smoke 阶段提前检查最终 simulation report | 在 workflow_spec 中把当前阶段真实证据加入当前 output_files 并检查它，或把 Checker 绑定移动到证据生成阶段；BUILD-SPEC-012 必须在 Stage 1 通过 |
| workspace 根目录多出与 `workflow.name` 同名的工程目录 | 把产品名称误当成 `root.path`，先构建到错误位置后才改成固定交付目录 | `root.path` 必须精确为 `{TEST_WORKFLOW_ROOT}`；先运行带 `expected_root` 的 WorkflowBuildConfigChecker，通过后才能调用 Builder。不得依赖后续阶段删除越界目录 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
