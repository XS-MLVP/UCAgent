# Workflow Builder

Workflow Builder 根据用户提供的 `input/guide.md` 和 `input/test_input/` 生成可独立运行、评估和增量维护的 UCAgent 业务工作流。

完整文档、快速启动、开发说明和排障经验请从 **[Workflow Builder 文档](../../docs/content/04_case/03_workflow_builder/00_index.md)** 进入。首次使用建议先执行：

```bash
python setup.py
make configure-check
make help
```

以下内容保留核心运行契约，便于已经熟悉项目的开发者快速查阅。

这个目录是 `workflow_build` 的直接运行版，用来根据业务根目录中的 `input/guide.md`
生成一个名为 `workflow` 的 UCAgent 工作流候选。根 `setup.py` 只配置
Workflow Builder 自身的本机默认值；它不是安装器，也不替代生成工作流内部的环境配置程序。

## 输入与输出

- 工作流名称固定为 `workflow`。
- 需求输入固定为 `../input/guide.md`。
- 中间规格写入 `wfgen/`。
- 生成产物写入 `$(OUT)/workflow/`，默认 `OUT=.`。
- 如需调整输出目录，在运行 make 时传入 `OUT=<目录>`。

示例：

```bash
make run OUT=output
make run_cli OUT=/tmp/workflow_builder_out
```

## 环境变量

推荐先通过 `python setup.py` 配置本机路径，也可以直接提供环境变量并按本机习惯启用代理：

```bash
export UCAGENT_HOME=/path/to/UCAgent
export UCAGENT_VENV=/path/to/UCAgent/.venv
# 例如在你的机器上通常还需要先运行：
# ucagent_env
# proxy_on
```

默认 Python 为 `$(UCAGENT_VENV)/bin/python`。如果需要覆盖，可以设置：

```bash
export PYTHON=/path/to/python
```

保存的本地配置可以选择导出 HTTP/HTTPS 代理。代理凭据和 Token 不落盘，仍由运行时环境提供。

## 常用命令

```bash
make help
make configure-check
make run
make run_cli
make run_eval
make run_eval_runtime_default
make run_eval_runtime_inc
make run_inc
make session
make regression
```

`make run` 会启动 TUI，并默认通过 `--loop --loop-msg "$(RUN_LOOP_MSG)"`
让内部 Agent 自动开始执行，适用于 tmux 监督策略。需要由外部通过 MCP 获取任务并逐步执行时，
使用 `make run RUN_LOOP_ARGS=` 清空自动 loop 参数，适用于 tmux 干预策略。共享观察窗口：

```bash
tmux attach -t ucagent_workflow_builder -r
```

退出 TUI：先 `Ctrl+C`，再输入 `q`。

## 组件关系

```text
tools/
  workflow_builder
    -> 创建工程骨架、Makefile、基础 config，并从 workflow_spec 直接生成业务 Checker
  workflow_tool_generator
    -> 从 tool spec 生成工具并注册
  workflow_checker_generator
    -> 供 Builder 物化内联 Checker、显式 fixture，也支持后续受控维护
  workflow_config_generator
    -> 从 config spec 生成最终配置，并从 workflow_spec 注入阶段契约
  workflow_guidedoc_generator
    -> 从 GuideDoc spec 生成指导文档并注册
  workflow_child_supervisor
    -> 在独立 tmux 会话中启动、观察和停止长时间运行的子工作流
  workflow_evaluation_control
    -> 校验并原子更新 eval/res JSON、聚合报告、部署显式批准的增量修改
regression
  -> 确定性验证上述生成器
```

生成出来的子工作流仍可以由 `workflow_builder` 组件决定是否包含迁移能力；本目录自身只是直接运行入口，不再通过安装器部署。

## 评估与增量

`make run_eval` 依次运行 `eval_tools.yaml`、`eval_checkers.yaml`、
`eval_flow.yaml` 和 `eval_env.yaml`，这四个流程只审查源码、配置、文档和
白名单确定性命令，不启动生成工作流。昂贵的运行评估由
`make run_eval_runtime_default` 或 `make run_eval_runtime_inc` 单独选择，
二者共用 `eval_run.yaml`，但一轮只执行一种模式。

所有 Make 入口都会创建并校验工作区根目录的 `eval/`、`res/` 和 `tmp/`。
正式报告按 run 追加到 `eval/*.json`；`res/*.json` 由用户提供专业知识；
fixture、日志、候选修改和运行案例只能放入 `tmp/`。增量流程只处理
`eval/approvals.json` 中明确批准的 finding 或 suggestion。
