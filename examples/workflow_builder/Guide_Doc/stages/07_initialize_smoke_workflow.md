# Stage 07: initialize_smoke_workflow

## 阶段目标

初始化 smoke workflow 并尝试启动 UCAgent。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{TEST_WORKFLOW_ROOT}/Makefile`
- `{TEST_WORKFLOW_ROOT}/config.yaml`
- `{TEST_WORKFLOW_ROOT}/README.md`
- `{TEST_WORKFLOW_ROOT}/docs/01快速启动.md`
- `{TEST_WORKFLOW_ROOT}/Guide_Doc/overview.md`

## 详细执行步骤

1. 第1步：使用 ReadTextFile 读取 {TEST_WORKFLOW_ROOT}/Makefile、{TEST_WORKFLOW_ROOT}/config.yaml、{TEST_WORKFLOW_ROOT}/README.md、{TEST_WORKFLOW_ROOT}/docs/01快速启动.md、{TEST_WORKFLOW_ROOT}/Guide_Doc/overview.md。
2. 第2步：确认 {TEST_WORKFLOW_ROOT}/setup.py、config/environment.schema.yaml 和 ucagent_setup.sh 已由 Builder 创建。setup.py 必须支持交互配置以及 --set、--config、--check、--dry-run、--non-interactive，并把非敏感本机值保存到 .workflow/local/environment.yaml；Makefile 与 ucagent_setup.sh 必须各包含唯一的 setup.py 受控环境区块。 schema 内置 UCAgent、Python、代理、tmux 基础项，并允许按目标工作流增加 Verilator、Yosys 等业务系统工具。随后调用 `WorkflowEnvironmentPreflight`，同时检查当前进程与 tmux 全局代理、Python、UCAGENT_HOME、UCAGENT_VENV 和四个环境交付文件。
3. 第3步：修改 {TEST_WORKFLOW_ROOT}/Makefile，保留 configure/configure-check/check/check_config/check_inc_config/check_layout/check_docs/clean， 并新增真正可用的 run、session、tmux 目标；禁止删除或手工改写 setup.py 管理的受控区块。
4. 第3.1步：Makefile 必须提供 check_target、prepare_input 和 prepare_runtime。prepare_input 只校验 runtime_contract.required_input；prepare_runtime 在 output/.runtime_targets/<TARGET>/ 创建 UCAgent 所需的隐藏 __init__.py；该隐藏路径只能供运行时包初始化使用，禁止作为 UCAgent 的 workspace 或 DUT 参数。Makefile 必须定义 WORKFLOW_WORKSPACE ?= $(CURDIR)，并让 run/run_inc/run_tui/smoke 使用 $(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) 启动 UCAgent。不得写成 $(UCAGENT) ./ $(TARGET)，不得建立根目录 TARGET 软链接，不得要求用户输入包含 data/__init__.py 或 Python/DUT 包。run、run_inc 和 run_tui 必须依赖 prepare_runtime。
5. 第4步：修改 {TEST_WORKFLOW_ROOT}/config.yaml，保留 workflow/paths/model/loop_settings/checkers/guide_docs 等骨架元数据，并补充 UCAgent 可运行的 mission、template、stage、write_dirs、un_write_dirs、tools.RunTestCases。 tools 顶层必须是 mapping，但 tools.GeneratedTools 必须是由 name/spec/file/enabled 记录组成的 list，禁止改成以工具名为键的 mapping；该列表由 WorkflowToolGenerator(update_config=true) 维护。 un_write_dirs 必须设为空列表 []。生成的工作流不得设置任何写保护目录（子工作流被强制停止时权限无法恢复， 会导致后续 make check/smoke/package 全部失败）；写保护由最终用户自行配置。注意 tools 必须是 mapping，不能是 list；工具注册放在 tools.GeneratedTools。
6. 第5步：确认 Makefile 的 run 目标会先 source ./ucagent_setup.sh，再执行 ucagent_env 和 proxy_on，然后通过 $(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) 启动 UCAgent，且 --output 指向 output。run/run_inc/run_tui/smoke 必须从 tools.mcp_adapters.ADAPTER_CLASS_NAMES 动态生成 --ex-tools 参数，确保 config.tools.GeneratedTools 在真实运行 Agent 中可见；不得只在 make test_mcp 中注册工具。
7. 第6步：仅在 {TEST_WORKFLOW_ROOT} 目录内运行 make check 和 make check_example，确认 bundled example 输入与基础检查通过。禁止在当前外层 workspace 根目录直接执行 make run TARGET=example，以免递归启动 workflow_build 自身。阻塞式运行验证统一放到后续 ChildWorkflowSupervisor 步骤。该阶段只验证基础架构，不能标记 feature_complete。
8. 第7步：调用 ChildWorkflowSupervisor(action='start', workflow_root='{TEST_WORKFLOW_ROOT}', target='example', make_target='run_tui', auto_loop=true) 启动生成工作流，记录 run_id、observe_command 和 terminal_log。注意 target 是运行时输入目录名，必须是 example；禁止把 make 目标 check_example 当作 target。
9. 第8步：启动后使用 ChildWorkflowSupervisor(action='status' 或 'capture') 进行简要观察；总观察时间控制在 60 秒左右，只验证工作流能启动、进入阶段并持续运行，不要求完整跑完。
10. 第9步：约 60 秒后调用 ChildWorkflowSupervisor(action='stop', workflow_root='{TEST_WORKFLOW_ROOT}', run_id='<前一步返回的 run_id>') 主动停止子工作流，确认权限恢复。
11. 第10步：如果 UCAgent 已启动，手动读取 README.md 和 Guide_Doc/overview.md，设置阶段日志并 Complete；退出时先 Ctrl+C 再 q。
12. 第11步：使用 SetCurrentStageJournal 记录初始化结果、运行命令、ChildWorkflowSupervisor 观察结果和是否成功启动。
13. 第12步：使用 Complete 工具完成阶段。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: initialize_smoke_workflow
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/setup.py
  - {TEST_WORKFLOW_ROOT}/config/environment.schema.yaml
  - {TEST_WORKFLOW_ROOT}/ucagent_setup.sh
  - {TEST_WORKFLOW_ROOT}/Makefile
  - {TEST_WORKFLOW_ROOT}/config.yaml
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `initialize_smoke_workflow` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_minimal_init_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `workflow_environment_setup_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 子 UCAgent 启动时报 `httpx Unknown scheme`，但当前 shell 看不到异常代理 | tmux 全局或父进程仍注入 `ALL_PROXY=socks://...`，局部 `tmux show-environment` 输出不足以证明子进程环境 | 调用 `WorkflowEnvironmentPreflight(include_tmux=true)`；必要时结合 `/proc/<pane_pid>/environ` 复核。修正生成的 `proxy_on`，确保在 disabled 早退前清理 `all_proxy/ALL_PROXY`，再重新预检和启动 |
| 环境预检只报告 UCAGENT_HOME/UCAGENT_VENV warning | 当前外层进程未显式导出变量，但生成工作流的 setup.py 仍可配置有效路径 | warning 不等于失败；以 `missing_workflow_files`、`proxy_issues` 和 `setup.py --check` 为准。不得把本机绝对路径硬编码进 acceptance 或迁移包 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
