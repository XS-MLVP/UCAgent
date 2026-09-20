# 阶段检查说明

本文档按里程碑逐一说明主配置中 24 个阶段的 Checker 配置、判断逻辑和修复指引。

每个阶段还必须通过 `WorkflowLivingPlanChecker`：Stage 0 创建
`wfgen/workflow_implementation_plan.md` 的完整架构基线，Stage 0-23 依次使用
`WorkflowPlanAppender` 追加唯一执行记录。记录必须包含阶段目标、决策与变更、产物与
验证证据、问题与处理、后续约束，并满足有效正文长度及前序内容 SHA256 链。阶段专属
的最小文件版本、常见示例和历史问题见 `Guide_Doc/stages/`；该目录只由维护者维护，
运行 Agent 只读。

## 运行协议 FAQ

| 现象 | 已确认根因 | 正确处理 |
|---|---|---|
| 业务 Checker 已通过，但 `Complete` 报 `.ucagent/history/... Permission denied` | 历史同步使用 `copy2` 保留了受管源文件的只读模式；仅在启动前 chmod 不够，因为运行中再次复制仍会恢复只读位。这不是候选工作流业务失败 | 不修改 Checker、候选结果或 UCAgent 源码。父 Makefile 必须在 `make run` 生命周期内启动 `history_permissions` 守护，并在退出时停止。运行 Agent 禁止读取、修改或删除 `.ucagent/history`；历史内容和 Git 元数据必须保留 |
| 当前阶段聚合 Check 只报告 living plan 缺记录 | 当前阶段唯一记录尚未通过 WorkflowPlanAppender 追加，LivingPlanChecker 按顺序先终止 | 先运行阶段规定的确定性 Make/测试入口收集证据，追加包含五个标题的当前记录，再调用聚合 Check |
| 修改维护者 Guide_Doc 后，workspace 仍显示旧内容 | 启动入口没有同步静态指导，已有副本不会自动刷新 | 修复父 Makefile 的 `prepare_input` 同步并重启；不得在运行中直接编辑 workspace 内的静态 FAQ |

---

## 里程碑 1：需求提取与工程模板

### Stage 1 — extract_requirements_and_plan

| 项目 | 内容 |
|------|------|
| **目标** | 从需求文档创建 `requirements_manifest.yaml`、`input_example_manifest.yaml` 和 `workflow_implementation_plan.md`，不在本阶段编写构建配置或 Checker 源码 |
| **Checker** | `WorkflowRequirementCoverageChecker` (mode=manifest) + `WorkflowImplementationPlanChecker` + `WorkflowInputExampleManifestChecker` |

**Checker 1：requirements_manifest_check**

| 维度 | 说明 |
|------|------|
| **检查对象** | `{WFGEN_DIR}/requirements_manifest.yaml` |
| **通过条件** | manifest 包含全部必需列表；`source_requirement` 指向需求文档；每个需求章节都有证据；每个 required_stages 条目都用 `{name, label, config}` 显式绑定 required_configs 中的具体文件；GuideDoc 使用 required_stages 的精确 `name` 建立阶段覆盖；六份 docs、`config.yaml` 与 `config/inc.yaml`、13 个 Make 目标和固定环境/迁移交付路径齐全；eval.yaml 仅按需加入 |
| **失败条件** | 必需列表缺失或为空；阶段缺少 name、label 或 config；config 未在 required_configs 声明；章节无证据；minimum_counts 低于固定下限；GuideDoc 阶段遗漏；用户文档、配置或交付项使用说明文字而非 `{path: ...}`；出现已取消的 quickstart.md |
| **修复** | 只修正需求清单；标准、评估、增量阶段分别绑定 `config.yaml`、`config/eval.yaml`、`config/inc.yaml`，禁止依赖缺省配置；一份 GuideDoc 可用 `stages` 列表覆盖多个阶段，不需要为每个阶段创建独立文件 |

**Checker 2：workflow_implementation_plan_check**

| 维度 | 说明 |
|------|------|
| **检查对象** | `workflow_implementation_plan.md` + `requirements_manifest.yaml` |
| **通过条件** | 九类设计章节齐全，正文不少于 1000 个有效字符，并覆盖 manifest 的阶段、工具、Checker、GuideDoc 和用户文档 |
| **失败条件** | 缺少设计章节或 manifest 组件；正文过短；没有说明目的、输入、输出、职责、验证内容或失败处理 |
| **修复** | 更新计划使其与已冻结 manifest 一致；标题空格以及“职责/作用”“验证内容/检查内容”等等价表述均可接受 |

**Checker 3：input_example_manifest_check**

| 维度 | 说明 |
|------|------|
| **检查对象** | `input_example_manifest.yaml` + 只读 `input/test_input/` |
| **通过条件** | source_dir、copy_mode、required_input 和资源映射有效；required_input/source_path 均是相对 source_dir 的真实路径 |
| **失败条件** | 用户输入缺失；required_input 原样复制 input/<TARGET> 前缀；source_path 重复 source_dir 前缀；copy_tree/self_contained 与目录存在性冲突 |
| **修复** | 修正清单中的相对路径，不得创建或修改 `input/test_input/` 来迁就检查 |

---

### Stage 2 — design_workflow_build_config

| 项目 | 内容 |
|------|------|
| **目标** | 根据已经通过检查的 manifest 和实现计划生成 `workflow_build.yaml`，把完整 Checker 实现规划与需求提取解耦 |
| **Checker** | `WorkflowBuildConfigChecker` + `WorkflowRequirementCoverageChecker` (mode=build) |

**Checker 1：workflow_build_config_check**

| 维度 | 说明 |
|------|------|
| **检查对象** | `{BUILD_CONFIG}`（workflow_build.yaml） |
| **通过条件** | YAML、根字段和路径安全通过；全部业务 Checker 包含源码、入口、方法 docstring、fixtures 及至少一个 PASS 和一个 FAIL 测试；阶段声明完整契约 |
| **失败条件** | schema 或路径错误；Checker 缺少可执行源码、正反例或阶段绑定 |
| **修复** | 只修正构建配置中 checker/stage/file 定义，不得单方面改写已经冻结的 manifest |

**Checker 2：initial_build_requirement_coverage**

| 维度 | 说明 |
|------|------|
| **检查对象** | `requirements_manifest.yaml` + `workflow_build.yaml` |
| **通过条件** | build 的 name/label、文件和中心 Checker 完整覆盖 manifest，且没有额外 Checker |
| **失败条件** | 阶段、Checker、文档、配置或交付物未声明，或中心 Checker 集合不一致 |
| **修复** | 补齐 workflow_spec 和 files 的对应项；稳定英文 name 可通过中文 label 对应显示名称 |

---

### Stage 3 — build_initial_template

| 项目 | 内容 |
|------|------|
| **目标** | 调用 `WorkflowBuilder` 生成工程骨架 |
| **Checker** | `WorkflowBuildOutputChecker` + `WorkflowRequirementCoverageChecker` (mode=build) |

**Checker 1：workflow_builder_output_check**

| 维度 | 说明 |
|------|------|
| **检查对象** | `{TEST_WORKFLOW_ROOT}/` 整个目录 |
| **通过条件** | 验收文件与目录存在；内部 Checker 和迁移设施存在；全部预规划业务 Checker 的 spec、Python 实现及 fixture 已生成；三个 Checker make 目标通过 |
| **失败条件** | 必需文件缺失；业务 Checker 产物不完整；`make check_checker_specs`、`make check_checkers` 或 `make test_checkers` 失败 |
| **修复** | 确认 `WorkflowBuilder` 调用成功；检查 `build_report.md` 中的错误和警告；确保 `workflow_build.yaml` 的 `files` 列表完整 |

---

## 里程碑 2：Smoke 基线

### Stage 4 — verify_tool_generation_loop

| 项目 | 内容 |
|------|------|
| **目标** | 验证工具生成基础设施，不默认生成无关通用工具 |
| **Checker** | `WorkflowToolGenerationChecker` |

| 维度 | 说明 |
|------|------|
| **检查对象** | `{TEST_WORKFLOW_ROOT}/` 的工具 spec/checker/runner/MCP 测试基础设施和当前已注册工具 |
| **通过条件** | Makefile 包含 `check_tool_specs`/`check_tools`/`test_tools`/`test_mcp` 且 `check` 依赖它们；config.yaml 中 `tools` 是 mapping 且保留 `RunTestCases.test_dir`；当前已注册工具均有 spec、实现和测试；`make check_tool_specs`/`check_tools`/`test_tools`/`check` 全部 exit 0 |
| **失败条件** | Makefile 目标缺失；config.tools 结构错误；当前注册工具缺 spec/实现/测试；无需求依据却生成 read_text_file_tool/write_text_file_tool/run_command_tool |
| **修复** | 固定基础设施只生成 `run_command_tool`；业务工具先从 `requirements_manifest.required_tools` 设计 smoke spec，再用 `from_spec` 和 `existing_policy=create_only` 生成并验证 |

---

### Stage 5 — design_smoke_business_tool_spec

| 项目 | 内容 |
|------|------|
| **目标** | 从 manifest 选一个代表性工具，设计 spec |
| **Checker** | `WorkflowGeneratedToolChecker` (spec_only=true) |

| 维度 | 说明 |
|------|------|
| **检查对象** | 创建的 `{TEST_WORKFLOW_ROOT}/.workflow/tool_specs/<tool>.yaml` |
| **通过条件** | spec YAML 语法有效；`name`/`entry.file`/`entry.class_name`/`entry.method` 存在且 `file` 以 `tools/` 开头；`outputs.required_keys` 包含 5 个标准 key；`tests` 非空 |
| **失败条件** | spec 缺失必需字段；测试列表为空；file 不在 `tools/` 下 |
| **修复** | 按工具生成规范补充 spec 字段，确保正向和边界测试用例完整 |

---

### Stage 6 — implement_smoke_business_tool

| 项目 | 内容 |
|------|------|
| **目标** | 调用生成器实现 + 直接测试 smoke 工具 |
| **Checker** | `WorkflowGeneratedToolChecker` (spec_only=false) |

| 维度 | 说明 |
|------|------|
| **检查对象** | 生成的 `tools/<tool>.py` 和 `config.yaml` |
| **通过条件** | 工具文件存在；包含 `class`/`input_schema`/`output_schema`/`def run`/`_safe_resolve`；`data_required_keys` 完整；`config.yaml` 中已注册到 `GeneratedTools`；`make check_tool_specs`/`check_tools`/`test_tools`/`check` 全部通过 |
| **失败条件** | 工具文件缺失或内容不完整；未注册；make 目标失败 |
| **修复** | 确认 `WorkflowToolGenerator(mode="from_spec")` 调用成功；检查 `tool_direct_run.log` 定位失败用例 |

---

### Stage 7 — strengthen_smoke_business_tool_tests

| 项目 | 内容 |
|------|------|
| **目标** | 增强 smoke 工具测试（增加边界/变体用例） |
| **Checker** | `WorkflowGeneratedToolChecker` (spec_only=false) |

| 维度 | 说明 |
|------|------|
| **检查对象** | 增强后的 spec、保持业务实现的原工具和新增测试证据 |
| **通过条件** | spec 中的测试用例数量 ≥ 上个阶段；所有新增测试用例在 `tool_direct_run.log` 中为 PASS；所有 make 目标通过 |
| **失败条件** | 测试用例未增加；新测试失败 |
| **修复** | 创建更多测试夹具并追加 spec.tests；直接增强现有业务源码。只可用 `create_only` 检查注册，禁止重新生成覆盖人工实现 |
| **写入边界** | 顶层 `write_dirs` 必须显式包含 `{TEST_WORKFLOW}`，不能只依赖运行时可能展开为 `.` 的 `{OUT}`。本阶段的 `output_files` 必须声明选择文件、`.workflow/tool_specs/`、`.workflow/tool_tests/cases/`、`tools/` 与 `config.yaml`，保证 `workflow/...` 和 `.//workflow/...` 两种等价相对路径不会得到不同权限结果。 |

---

### Stage 8 — initialize_smoke_workflow

| 项目 | 内容 |
|------|------|
| **目标** | 完善 Makefile/config，启动子 UCAgent 验证 |
| **Checker** | `WorkflowMinimalInitChecker` |

| 维度 | 说明 |
|------|------|
| **检查对象** | `{TEST_WORKFLOW_ROOT}/` 的运行时就绪状态 |
| **通过条件** | `setup.py`、`config/environment.schema.yaml` 和 `ucagent_setup.sh` 存在；环境程序支持交互与 `--set`/`--config`/`--check`/`--dry-run`/`--non-interactive`，Makefile 和 shell 各有唯一受控区块，临时执行两次结果幂等；Makefile 包含 `configure:`/`configure-check:`/`run:`/`prepare_input:`/`prepare_runtime:`/`check_input:`/`check_example:`/`smoke:`/`session:`/`tmux:`/`test_mcp:`，定义 `WORKFLOW_WORKSPACE ?= $(CURDIR)`，所有运行目标使用 `$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET)`，动态传入 `tools.mcp_adapters` 的 `--ex-tools`，并引用 `ucagent_env`/`proxy_on`/`--config`/`--output`/`--guid-doc-path`/`--append-py-path`/`--loop`/`--exit-on-completion`；用户输入不要求 `data/__init__.py`，隐藏运行包位于 `output/.runtime_targets/` 且不得作为 UCAgent workspace 或 DUT 参数；`config.yaml` 包含 `mission`/`stage`/`template`/`write_dirs`/`un_write_dirs`/`tools.RunTestCases`，其中 `tools` 是 mapping 而 `tools.GeneratedTools` 是记录 list；`runtime_contract` 验证通过；`make check_example` 和 `make check` exit 0 |
| **失败条件** | 任一必需文件/脚本内容/Makefile 目标/config 字段缺失；runtime_contract 任意项失败 |
| **修复** | 按 task 描述补充 `setup.py`、environment schema、`ucagent_setup.sh`、Makefile 和 config.yaml；只修改环境受控区块，注意 `un_write_dirs` 写具体子目录而非 `.workflow/` |

---

### Stage 9 — verify_generated_tools_through_mcp

| 项目 | 内容 |
|------|------|
| **目标** | 启动子 UCAgent，通过真实 MCP 调用验证工具 |
| **Checker** | `WorkflowMCPToolIntegrationChecker` |

| 维度 | 说明 |
|------|------|
| **检查对象** | `output/mcp_test_result.log` + `.workflow/logs/tool_mcp_run.log` |
| **通过条件** | `make test_mcp` exit 0；日志包含 4 条 `[PASS]`（list_tools + 3 个工具调用）；MCP server 日志包含工具注册和调用记录（`create FastMCP server`、`CallToolRequest` 等）；`tools/mcp_adapters.py` 只实现 `_run`，不覆盖 `BaseTool.run`，不注册 `"run": run`；MCP 测试后 `make check` 仍通过 |
| **失败条件** | mcp_test_result 缺少 PASS 行；server 日志缺少调用记录；测试后 make check 失败（权限/端口残留）；adapter 返回裸 `str` 导致直接运行报 `Tool <name> returned unexpected type: <class 'str'>` |
| **修复** | 检查 `tools/mcp_adapters.py` 和 `.workflow/tool_tests/run_mcp_tests.py`；确认子 UCAgent 使用动态端口；adapter 保持 WFB 模板：`_run` 返回 JSON 字符串，`BaseTool.run` 负责包装 `ToolMessage` |
| **产物顺序** | 本阶段 `output_files` 必须为空。`WorkflowMCPToolIntegrationChecker` 会先执行 `make test_mcp`，再读取并验证 `output/mcp_test_result.log` 与 `.workflow/logs/tool_mcp_run.log`；如果把这些派生日志声明为阶段前置输出，UCAgent 会在调用 checker 前因日志不存在而失败。 |

---

### Stage 10 — freeze_smoke_baseline

| 项目 | 内容 |
|------|------|
| **目标** | 标记 `smoke_ready=true` |
| **Checker** | `WorkflowRequirementCoverageChecker` (mode=manifest) |

| 维度 | 说明 |
|------|------|
| **检查对象** | `requirements_manifest.yaml` 的里程碑字段 |
| **通过条件** | manifest 结构完整；`milestones.smoke_ready=true` |
| **失败条件** | manifest 不完整或 smoke_ready 不为 true |
| **修复** | 确认 Stage 3-8 全部通过后更新 manifest |

---

## 里程碑 3：补齐全部业务组件

### Stage 11 — design_complete_runtime_configs

| 项目 | 内容 |
|------|------|
| **目标** | 设计 main/inc 配置 spec，并按需设计独立 eval spec |
| **Checker** | 无显式 Checker（后续 Stage 11 的 `WorkflowConfigGenerator` 执行严格校验） |

| 维度 | 说明 |
|------|------|
| **检查对象** | `{TEST_WORKFLOW_ROOT}/.workflow/config_spec.yaml` |
| **通过条件** | YAML 有效；阶段名唯一；main/inc 及可选 eval 每个 task 有效正文至少 100；阶段存在于 workflow_spec；不覆盖其引用、输出或 Checker 规划；引用和输出只使用具体文件 |
| **失败条件** | task 有效长度不足；占位符、write_dirs 或路径非法；阶段未规划；显式契约与 workflow_spec 冲突 |
| **修复** | 在 config spec 增加具体输入、操作、工具、产物、检查与恢复说明；业务契约必须回到 workflow_build.yaml 修改 |

---

### Stage 12 — generate_complete_runtime_configs

| 项目 | 内容 |
|------|------|
| **目标** | 调用 `WorkflowConfigGenerator` 生成 `config/*.yaml` |
| **Checker** | `WorkflowConfigGenerator` 内置校验（`validate_config_spec`） |

| 维度 | 说明 |
|------|------|
| **检查对象** | 生成的 `config.yaml`、`config/inc.yaml` 和按需生成的 `eval.yaml` |
| **通过条件** | mode 正确；main/inc task 至少 100 有效字符；引用、输出与 Checker 注册由 workflow_spec 注入且完全一致；不存在 `config/default.yaml` 或 `config/empty.yaml` |
| **失败条件** | mode 或阶段数错误；task 不足 100；路径非法；阶段契约与 workflow_spec 不一致 |
| **修复** | task 修 config spec；Checker、引用或输出规划修 workflow_build.yaml 并重新构建，禁止只改最终配置 |

---

### Stage 13 — design_all_business_tool_specs

| 项目 | 内容 |
|------|------|
| **目标** | 为全部业务工具设计 specs |
| **Checker** | 本阶段用 `make check_tool_specs`（Stage 3 checker 的相同逻辑） |

| 维度 | 说明 |
|------|------|
| **检查对象** | `.workflow/tool_specs/` 下全部 YAML |
| **通过条件** | `required_tools` 中每个工具有对应 spec；spec 包含完整 `entry`/`inputs`/`outputs`/`tests`；`tests` 包含正向+边界+失败用例 |
| **失败条件** | spec 缺失或字段不完整；测试用例不足 |
| **修复** | 补全缺失的 spec；为每个工具添加至少一个正向和一个失败测试 |

---

### Stage 14 — generate_all_business_tools

| 项目 | 内容 |
|------|------|
| **目标** | 批量生成全部业务工具 |
| **Checker** | `WorkflowToolGenerationChecker` 的子集（make check_tools + make test_tools） |

| 维度 | 说明 |
|------|------|
| **检查对象** | 全部 `tools/*.py` |
| **通过条件** | 每个 `required_tool` 有对应实现文件；源码完整；**业务工具的 data 字段在 direct runner 日志中返回真实计算值（非骨架默认值 0/False/[]/""）**；`make check_tools`/`test_tools` 通过 |
| **失败条件** | 工具缺失；源码不完整；**data 字段全为默认值（说明生成器只产了空壳，需手写实现）**；测试失败 |
| **修复** | `WorkflowToolGenerator` 生成框架 → 手动补全业务逻辑 → `make test_tools` 验证 |

---

### Stage 15 — run_full_tool_test_suite

| 项目 | 内容 |
|------|------|
| **目标** | 全量 static/direct/MCP 测试 |
| **Checker** | `WorkflowToolGenerationChecker` + `WorkflowMCPToolIntegrationChecker`（通过 make 目标触发） |

| 维度 | 说明 |
|------|------|
| **检查对象** | 全部工具的测试结果 |
| **通过条件** | `make check_tool_specs`/`check_tools`/`test_tools`/`test_mcp`/`check` 全部 exit 0；每个 `required_tool` 在 `tool_direct_run.log` 中正向测试 PASS；**业务工具 data 字段值非默认值（非 0/False/[]/""）**；在 `mcp_test_result.log` 中被 MCP 发现并调用成功；`tools/mcp_adapters.py` 不覆盖 `BaseTool.run` |
| **失败条件** | 任一 make 目标失败；有工具未被 MCP 发现或调用失败；adapter 覆盖 `run()` 或注册 `"run": run`，导致直接 UCAgent 运行返回裸 `str` |
| **修复** | 读取 `tool_direct_run.log` 和 `tool_mcp_run.log`，逐个定位并修复失败的工具 |
| **产物顺序** | 与 Stage 8 相同，MCP 日志由 checker 执行 `make test_mcp` 后生成，不得作为调用 checker 之前必须存在的 `output_files`。 |

---

### Stage 16 — design_all_document_specs

| 项目 | 内容 |
|------|------|
| **目标** | 为全部 GuideDoc 和用户文档设计 specs |
| **Checker** | `WorkflowGuideDocSpecChecker` |

| 维度 | 说明 |
|------|------|
| **检查对象** | `.workflow/guidedoc_specs/` 下全部 YAML |
| **通过条件** | 每个 spec 声明 document_type/title/output/sections；GuideDoc 含 7 个必需章节且覆盖业务阶段，只有 operation_contract=true 时强制运行命令；user_doc 输出到 docs/ 且覆盖固定文档集合。工具和 Checker 开发文档为每个实际注册组件建立独立标题，每项具有至少 100 个有效正文字符的设计摘要，并原样记录实际注册的实现路径、class_name 和 method |
| **失败条件** | 缺少字段；章节缺失或为空；操作契约标记缺失；只覆盖 overview.md/operation.md；manifest 未声明覆盖关系；组件标题缺失、设计摘要过短、实现文件不存在，或路径/class_name/method 与最终注册信息不一致 |
| **修复** | 对照最终工具和 Checker 注册表补齐组件标题、职责、源码映射与下一阶段分析范围。不要在本阶段逐项复制源码或完成最终 300 字文档；真实源码围栏、固定标签和完整关键代码分析由下一阶段生成并验收 |

---

### Stage 17 — generate_all_documentation_and_dependencies

| 项目 | 内容 |
|------|------|
| **目标** | 批量生成 Guide_Doc、用户 docs 和 requirements.txt |
| **Checker** | `WorkflowGeneratedGuideDocChecker`、`WorkflowUserDocsChecker`、`WorkflowDependencyChecker` |

| 维度 | 说明 |
|------|------|
| **检查对象** | `Guide_Doc/`、`docs/` 和 `requirements.txt` |
| **通过条件** | GuideDoc 完整且注册；每份用户文档至少 200 个有效正文字符；工具和 Checker 的准确名称分别出现在独立标题中，正文只统计当前组件标题之后到下一个二级至六级标题之前的内容，每项至少 300 个有效正文字符，原样引用实际注册路径、class_name、method，并含与真实实现逐字匹配的连续 python/py 代码片段以及源码、业务逻辑和修改影响分析；依赖清单覆盖 manifest，用户 docs 不注册为 guide_docs |
| **失败条件** | 文件、章节、说明长度、注册或依赖覆盖不满足契约；组件正文少于 300 个有效字符，只写概述/重复文字，实际源码未注册或不存在，代码片段不能与真实实现匹配，或者缺少三类分析 |
| **修复** | 根据 `source_evidence_errors` 和缺失标记定位组件，回到 guidedoc spec 补充真实注册值、源码片段和至少 500 个有效正文字符的具体分析，然后重新生成；不要直接手工补写生成后的 Markdown |

---

### Stage 18 — generate_all_reusable_templates

| 项目 | 内容 |
|------|------|
| **目标** | 生成模板文件 |
| **Checker** | 无显式 checker（存在性和非空由后续需求覆盖检查验证） |

| 维度 | 说明 |
|------|------|
| **通过条件** | `required_templates` 为空时明确记录需求未要求用户模板；非空时其中每个用户可复用模板路径存在且非空。该字段不得包含 `readme_basic`、`config_basic` 等 Builder 渲染标识符 |
| **修复** | 为每个模板生成内容，使用需求规定的占位符 |

---

### Stage 19 — complete_readme_and_makefile

| 项目 | 内容 |
|------|------|
| **目标** | 完善 README、用户 docs、requirements.txt 和 Makefile |
| **Checker** | 本阶段的产物由后续 `runtime_contract` 和需求覆盖检查验证 |

| 维度 | 说明 |
|------|------|
| **检查对象** | README.md / docs/*.md / requirements.txt / Makefile |
| **通过条件** | README 包含运行契约；`docs/01快速启动.md` 包含 `setup.py`、`make configure`、`make configure-check` 和可执行示例命令；输入输出文档区分业务输入与 `.workflow/local/environment.yaml`；固定用户文档齐全且满足有效正文长度，开发者文档逐项覆盖工具和 Checker；requirements.txt 覆盖 Python 与系统依赖；Makefile 包含完整目标链并动态注册工具 |
| **失败条件** | 内容缺失；Makefile 目标不完整；`TARGET` 有默认值；仍使用 `$(UCAGENT) ./ $(TARGET)` |
| **修复** | 按 `runtime_contract` 要求补全内容和 Makefile 目标 |

---

## 里程碑 4：最终验证

### Stage 20 — mark_feature_complete

| 项目 | 内容 |
|------|------|
| **目标** | 更新 `feature_complete=true` |
| **Checker** | 无显式 Checker（由 Stage 20 验证） |

| 维度 | 说明 |
|------|------|
| **通过条件** | 所有 required 组件已生成；确定性检查通过；`milestones.feature_complete=true` |
| **修复** | 确保 Stage 12-18 全部完成后更新 manifest |

---

### Stage 21 — verify_final_requirement_coverage

| 项目 | 内容 |
|------|------|
| **目标** | 最终需求覆盖检查，`release_ready=true` |
| **Checker** | `WorkflowRequirementCoverageChecker` (mode=final) |

| 维度 | 说明 |
|------|------|
| **检查对象** | `requirements_manifest.yaml` + 生成工作流全部文件 |
| **通过条件** | manifest 中所有阶段、工具、Checker、GuideDoc、用户文档、依赖、模板、配置和交付物均存在并满足各自 Checker；四份运行配置不含父工作流路径前缀；只有 operation_contract=true 的 GuideDoc 强制操作标记；runtime_contract 与里程碑通过 |
| **失败条件** | 任一 required 项缺失（报告格式：`config/path.yaml:stage_name`）；`parent_workflow_path_leaks` 非空；`runtime_contract` 失败；`smoke_ready` 或 `feature_complete` 不为 true |
| **修复** | 根据错误报告的缺失项逐项补充；若报告 `parent_workflow_path_leaks`，回到对应 `.workflow/config_specs/*.yaml` 删除父级 `workflow/` 前缀并重新生成全部配置 |

---

## 里程碑 5：清理与迁移

### Stage 22 — clean_release_candidate

| 项目 | 内容 |
|------|------|
| **目标** | 清理运行产物、缓存和日志 |
| **Checker** | 无显式 Checker（由 Stage 22 的 `WorkflowMigrationPackageChecker` 验证洁净度） |

| 维度 | 说明 |
|------|------|
| **通过条件** | `.ucagent`/`__pycache__`/`.pytest_cache`/`.workflow/logs` 运行日志/`output` 运行产物已删除；根级 `tmp/` 已清空且目录保留；`output/` 空目录保留；`input/example/` 完整可运行；测试夹具日志保留 |
| **修复** | 对遗漏的缓存/日志/产物文件手动删除 |

---

### Stage 23 — prepare_and_verify_migration_packages

| 项目 | 内容 |
|------|------|
| **目标** | 准备 full/partial 迁移包 |
| **Checker** | `WorkflowMigrationPackageChecker` |

| 维度 | 说明 |
|------|------|
| **检查对象** | `.install/manifest.json` + `.install/packages/full/` + `.install/packages/partial/` |
| **通过条件** | manifest 包含 full 和 partial；partial 排除工具/Checker实现与内部测试，full 保留它们；两种包都保留 requirements.txt、完整 docs、input/example 和空 output；Stage 22 检查包结构，Stage 23 执行临时部署验证 |
| **失败条件** | 模式边界破坏（partial 含工具/checker）；洁净化失败（含缓存/日志/产物）；部署后 check 失败 |
| **修复** | 重新运行 `install.py --prepare both --force`；手动清理残留文件 |

---

### Stage 24 — verify_migrated_release

| 项目 | 内容 |
|------|------|
| **目标** | 最终验证迁移后的发布包 |
| **Checker** | `WorkflowMigrationPackageChecker` (run_deploy_test=true) |

| 维度 | 说明 |
|------|------|
| **检查对象** | 临时部署的 full 和 partial 目录 |
| **通过条件** | full 部署目录 `make check_example` 和 `make check` 通过；partial 部署目录 `make check_example` 通过；两个部署目录都满足 `runtime_contract`；无运行中子 UCAgent |
| **失败条件** | 部署目录 check 失败；runtime_contract 不满足 |
| **修复** | 检查部署目录的 `config.yaml`、`Makefile`、`docs/01快速启动.md` 和 `requirements.txt` 是否正确 |
