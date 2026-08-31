# 工作流构建指南

## 目的

本系统将构建、增量维护和运行时评估分离开来。主工作流构建并静态验证生成的工作流；独立评估工作流运行生成的 default/inc 子流程，产出证据和变更请求。

## 输入

需求文档路径：

`runtime_contract.required_input` 是 `input/<TARGET>/` 结构的唯一事实源。每项使用
`path`、`type: file|directory` 和可选 `example_content`。不要默认加入 DUT、RTL 或
`data/__init__.py`；UCAgent 所需的 Python 运行包由 Makefile 在
`output/.runtime_targets/<TARGET>/` 中创建，与用户输入分离。

```text
../input/guide.md
```

修改需求文档后重新运行即可生成对应的工作流。所有生成产物必须在 `wfgen/` 或 `output/` 下。
`wfgen/workflow_build_schema.yaml` 是第一阶段 `workflow_build.yaml` 的结构参考，必须保留其中所有根级字段并根据需求清单展开列表。

需求提取时必须保留输入语义：原始内容、原始数据和可用资源只是工作流的输入材料。分析结论、结构规划、设计参数、资源选择和中间产物属于工作流职责，不能反向加入用户输入模板。

本目录是直接运行版，不使用部署安装器。工作流名称固定为 `workflow`，输入固定为
`../input/guide.md`，输出目录由 Makefile 的 `OUT` 参数决定：

```bash
make run OUT=output
make run_cli OUT=/tmp/workflow_builder_out
```

运行前需要设置 `UCAGENT_HOME` 和 `UCAGENT_VENV`，并由外部 shell 提前完成 UCAgent
环境初始化和代理配置。主工作流 Makefile 不再调用 `UCAGENT_SETUP_CMD`。

## 运行方式

运行完整非交互工作流：

```bash
make run_cli
```

独立评估生成的 default/inc 子工作流：

```bash
make run_eval
```

对评估产生的变更请求进行增量修改：

```bash
make run_inc
```

在共享 tmux 会话中运行：

```bash
make session
tmux attach -t ucagent_workflow_builder -r
```

运行确定性组件回归测试：

```bash
make regression
```

## 阶段职责

主工作流有 24 个阶段，分为五个里程碑。Stage 1 只冻结需求清单、输入示例契约和实现计划；
Stage 2 再把业务 Checker 的规划、源码、fixture 和正反测试写入 `workflow_build.yaml`。
Stage 3 初次构建时直接生成并验证这些 Checker，不再安排后置 Checker 设计阶段。

配置数组采用零基下标时，上述三个阶段分别称为 Stage 0、Stage 1、Stage 2。每个阶段
都有一份只读静态指导，位于 `Guide_Doc/stages/<两位下标>_<stage_name>.md`。配置正文
只保留顺序、边界和验收入口，最小可通过文件、完整示例及历史 FAQ 均在对应阶段指导中。
这些 FAQ 由维护者在运行结束并确认根因后更新，运行 Agent 不得修改 `Guide_Doc/`。

`wfgen/workflow_implementation_plan.md` 是贯穿 24 个阶段的单一持续规划。Stage 0 创建
完整架构基线并用 `WorkflowPlanAppender` 追加首条执行记录；其余阶段必须先读取已有
规划，再追加本阶段的决策、产物、验证证据、问题处理和后续约束。追加工具会记录前序
内容 SHA256，`WorkflowLivingPlanChecker` 检查阶段顺序、必需栏目、正文长度和哈希链，
禁止用普通文本写入覆盖此前规划。

### 里程碑 1：需求提取与工程模板

| 阶段 | 名称 | 职责 |
|------|------|------|
| 1 | extract_requirements_and_plan | 创建需求清单、输入示例清单和详细实现计划 |
| 2 | design_workflow_build_config | 根据冻结计划创建并验证 `workflow_build.yaml` |
| 3 | build_initial_template | 调用 `WorkflowBuilder` 生成工程骨架 |

### 里程碑 2：Smoke 基线

| 阶段 | 名称 | 职责 |
|------|------|------|
| 4 | verify_tool_generation_loop | 验证工具生成基础设施，不默认生成无关通用工具 |
| 5 | design_smoke_business_tool_spec | 从 manifest 选择代表性工具，设计 spec |
| 6 | implement_smoke_business_tool | 调用生成器实现 smoke 工具 |
| 7 | strengthen_smoke_business_tool_tests | 增强测试并重新验证 |
| 8 | initialize_smoke_workflow | 完善 Makefile/config，启动子 UCAgent 验证 |
| 9 | verify_generated_tools_through_mcp | 真实 MCP 调用验证工具 |
| 10 | freeze_smoke_baseline | 标记 `smoke_ready=true` |

### 里程碑 3：补齐全部业务组件

| 阶段 | 名称 | 职责 |
|------|------|------|
| 11 | design_complete_runtime_configs | 设计 main/inc 与可选 eval 配置的详细 task |
| 12 | generate_complete_runtime_configs | 从 workflow_spec 注入契约并生成 `config/*.yaml` |
| 13 | design_all_business_tool_specs | 为全部业务工具设计 specs |
| 14 | generate_all_business_tools | 批量生成工具 |
| 15 | run_full_tool_test_suite | 全量 static/direct/MCP 测试 |
| 16 | design_all_document_specs | 为 GuideDoc 与用户文档设计 specs |
| 17 | generate_all_documentation_and_dependencies | 生成 Guide_Doc、用户 docs 和 requirements.txt |
| 18 | generate_all_reusable_templates | 生成模板文件 |
| 19 | complete_readme_and_makefile | 完善 README、用户 docs、requirements.txt 和 Makefile |

### 里程碑 4：最终验证

| 阶段 | 名称 | 职责 |
|------|------|------|
| 20 | mark_feature_complete | 更新 `feature_complete=true` |
| 21 | verify_final_requirement_coverage | 最终需求覆盖检查，`release_ready=true` |

### 里程碑 5：清理与迁移

| 阶段 | 名称 | 职责 |
|------|------|------|
| 22 | clean_release_candidate | 清理运行产物 |
| 23 | prepare_and_verify_migration_packages | 准备 full/partial 迁移包 |
| 24 | verify_migrated_release | 部署验证迁移包 |

独立评估拆分为 `eval_tools.yaml`、`eval_checkers.yaml`、`eval_flow.yaml`、
`eval_env.yaml` 和 `eval_run.yaml`。前四类只进行源码、配置、文档和白名单
确定性命令审查，禁止启动子工作流；`eval_run.yaml` 是唯一允许运行生成
工作流的评估，而且 default 与 inc 必须分开请求。全部结果按 run 追加到
工作区根目录 `eval/*.json`，用户专业知识位于只读 `res/*.json`，临时文件
和案例只能进入 `tmp/`。

独立 `inc.yaml`（3 阶段）只处理 `eval/approvals.json` 中显式批准的问题。
候选文件位于 `tmp/inc_candidates/<run_id>/`，部署工具写入哈希证据；修改
完成后仍保持 `fix_applied_pending_recheck`，由对应评估重新确认。

运行评估中的长时间子工作流必须通过 `ChildWorkflowSupervisor` 启动。该工具依据生成工作流 `.workflow/workflow_spec.yaml` 中的 runtime contract 校验输入，创建带 `agent`、`status`、`logs` 三个窗口的专用 tmux 会话，立即返回只读 attach 命令，并支持非阻塞的 `status`、`capture`、`list`、`stop` 操作；全部运行证据只写外层 `tmp/eval_runs/`。

## 运行时契约

每个生成的工作流必须遵循统一的运行时布局：

- `TARGET=<name>` 选择一个处理目标
- `input/<TARGET>/` 包含该目标的所有运行时输入
- `docs/01快速启动.md` 必须存在，基于 `input/example/` 给出可直接复制运行的命令
- `input/example/` 必须逐项包含 `runtime_contract.required_input` 声明的文件和目录，
  文件内容应能直接运行，不能是空 JSON 或占位文本
- UCAgent 所需 Python 运行包位于 `output/.runtime_targets/<TARGET>/`，不得混入用户输入
- `output/` 包含所有生成结果；运行配置的 `write_dirs` 必须为 `["{OUT}/{DUT}"]`
- `make check_input TARGET=<name>` 在启动前拒绝缺失的输入
- `make run TARGET=<name>` 运行选定目标，无默认值

UCAgent 变量使用单层花括号（如 `{DUT}`、`{OUT}`），禁止双层花括号（`{{DUT}}`）。

## 需求清单

第一阶段必须创建 `wfgen/requirements_manifest.yaml`。它是权威交付契约，必须包含：

```yaml
milestones:
  smoke_ready: false
  feature_complete: false
  release_ready: false
minimum_counts: {}
source_requirement: ../input/guide.md
requirement_sections: []
section_coverage: {}
required_stages: []
required_tools: []
required_checkers: []
required_guidedocs: []
required_user_docs: []
required_python_dependencies: []
required_system_dependencies: []
required_templates: []
required_configs: []
required_make_targets: []
required_deliverables: []
```

列表必须描述从需求文档提取的完整目标工作流，不能缩减为 smoke 子集。

填充 `required_stages` 时，每项必须使用
`{name: precise_stage_name, label: 显示名称, config: config/path.yaml}`，其中
`config` 必须逐字匹配 `required_configs` 中已经声明的具体路径。标准、评估、增量阶段
分别绑定 `config.yaml`、`config/eval.yaml`、`config/inc.yaml`，禁止依赖缺省的
`config.yaml` 归属。

其中以下内容属于 Workflow Builder 固定交付契约，不能通过调低 `minimum_counts` 删除：

- `required_user_docs` 至少包含 `docs/README.md`、`docs/01快速启动.md`、
  `docs/02输入输出.md`、`docs/03步骤及检查.md`、`docs/04开发者文档-tools.md`
  和 `docs/05开发者文档-checkers.md`。禁止重新引入已取消的 `quickstart.md`。
- `required_configs` 必须包含 `config.yaml` 和 `config/inc.yaml`；只有业务需要独立评估时才加入 `eval.yaml`，禁止生成 `config/default.yaml` 或 `config/empty.yaml`。
- `required_make_targets` 必须包含 help、configure、configure-check、check、check_config、check_inc_config、check_example、
  test_tools、test_checkers、test_mcp、plan、run、run_inc、clean 和 package。
- `required_deliverables` 必须包含环境配置、迁移、六份 docs、`config.yaml` 和 `config/inc.yaml`。
  `required_user_docs`、`required_configs`、`required_deliverables` 每项都使用
  `{path: relative/path}` mapping；“全部 Checker”“完整代码”等描述不是路径，禁止写入这些列表。
- `minimum_counts.user_docs/configs/make_targets/deliverables` 分别不得低于 6、4、15、19。

同一阶段必须创建 `wfgen/workflow_implementation_plan.md`。计划逐项解释目标工作流的
阶段、工具、Checker、GuideDoc、用户文档和依赖，并说明各自目的、输入输出、产物、
检查条件及失败处理。`WorkflowImplementationPlanChecker` 会将其中的名称与
requirements manifest 完整交叉校验；不得用后续生成的简略清单替代该文件。

## 环境配置

生成的工作流固定提供 `setup.py` 和 `make configure`，用于在移植后的机器上配置
Python、UCAgent、代理以及业务系统工具。建议首次运行：

```bash
make configure
make configure-check
```

非交互部署可使用 `python setup.py --non-interactive --set KEY=VALUE`。公开声明位于
`config/environment.schema.yaml`，本机非敏感值位于 `.workflow/local/environment.yaml`；
后者不会进入迁移包。Token、密码和带认证信息的代理地址只能通过运行时环境变量提供。

## 指导文档

更多详细规范请参阅：

- [工具生成规范](tool_generation_guide.md)
- [Checker 生成规范](checker_generation_guide.md)
- [配置文件生成规范](config_generation_guide.md)
- [workflow_build.yaml 生成规范](workflow_build_yaml_guide.md)
- [GuideDoc 生成规范](guidedoc_generation_guide.md)
- [阶段检查说明](stage_check_guide.md)

## 故障恢复

- 读取 `.ucagent/run_cli.log` 查看外层工作流日志
- 读取 `{OUT}/workflow/.workflow/logs/` 查看生成工作流的检查日志
- 如果后端在 assistant `tool_calls` 消息后报 missing tool responses，用 `Ctrl+C` 停止，输入 `q`，然后以 `--no-history --force-stage-index <从0开始计数的当前阶段>` 重启
- 工作流允许对无共享写入的只读操作和独立文件生成并行发起 tool_calls；会写入 config、注册表、workflow_spec、实现计划或全量测试结果的操作必须串行收敛。若后端报告 missing tool responses，停止后以更小批次恢复，不能直接重放整批写入操作
- 不要在同一个固定 MCP 端口上运行多个 UCAgent 进程
- 修改 workflow_build Python 代码后，重启 UCAgent 再测试
- 退出 TUI UCAgent：按 `Ctrl+C`，然后输入 `q`
- 如果业务 Checker 已通过但 `Complete` 报 `.ucagent/history/... Permission denied`，这是历史快照保留了源文件只读模式。母工作流 `make run` 会启动 `history_permissions` 守护，在整个运行期间恢复历史快照的属主写权限并在退出时停止；不要修改 UCAgent 源码，也不要让运行 Agent 读取、修改或删除历史仓库。

## 常见问题

### Q: Stage 15 执行时 `.workflow/` 目录 Permission denied

**根因**：Stage 7 中 Agent 在生成 `config.yaml` 时将 `un_write_dirs` 写为 `- .workflow/`。UCAgent 在每个阶段完成后对目录执行 `chmod a-w`，锁住整个 `.workflow/`。前面阶段不需要在 `.workflow/` 下新建子目录所以不暴露，到 Stage 15 需要建 `guidedoc_specs/` 时 `mkdir` 失败。

**应急修复**：
```bash
python3 -c "import os, stat; \
  p = '.workflow'; \
  os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)"
```

**根本修复**：`un_write_dirs` 写为具体子目录而非 `.workflow/` 本身。

### Q: Complete 时报 `GUIDEDOC-GEN-SPEC-006`

**根因**：GuideDoc spec 的 `Inputs` 和 `Usage` 章节缺少 checker 要求的标准化关键词。Checker 对 `Inputs` 要求包含 `input/<TARGET>/` 和 `input/example`；`Usage` 要求包含 `TARGET`、`input/<TARGET>/`、`input/example`、`output/`、`make check_example`、`make run`；`Outputs` 要求包含 `output/`。

**修复**：确保每个 GuideDoc spec 的对应章节包含上述标准路径和命令。
