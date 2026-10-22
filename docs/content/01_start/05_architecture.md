
# 理解任务、工作区和工作流

完成一次上手后，可以用四个概念理解 UCAgent：输入资料、工作区、工作流和验收。它们决定 Agent 做什么、文件放在哪里，以及什么时候可以进入下一阶段。

## 输入资料

默认单元测试流程需要 DUT 的 Python 包、需求文档，以及分析所需的 RTL 源码。Python DUT 包通常由 picker 导出；直接运行 `ucagent` 不会自动编译 RTL。源码仓库的 Make 目标和 Master Launch 页面可以负责这一步。

`<workspace>/<DUT>/README.md` 应描述接口、时序、功能和验证目标。需求不完整时，应先补充资料，避免让 Agent 猜测设计行为。自定义文档工作流可以使用其他类型的输入，不一定需要 DUT 包。

## 工作区与输出目录

`workspace` 是本次任务允许操作的工程目录；`--output` 是其中的产物目录名，默认 `unity_test`。例如：

```text
output/                     # 启动时传入的 workspace
├── Adder/                  # DUT 包、源码和需求
├── Guide_Doc/              # 运行时指导文档
├── unity_test/             # 当前工作流生成的文档和测试
├── uc_test_report/         # 实际运行测试后生成的报告
└── .ucagent/               # 运行配置与任务状态
```

具体产物取决于工作流、启用的阶段和测试结果。波形格式及保存位置由 DUT 和测试配置决定；启动任务本身不保证生成波形或完整报告。结果阅读方法见[结果分析与流程总结](06_summary.md)。

## 工作流与验收

工作流是一组有顺序的阶段。每个阶段规定任务、参考文件、预期输出和 Checker。Agent 使用工具完成任务，再调用 `Check` 查看验收结果；调用 `Complete` 通过最终检查和适用门禁后，才能推进到下一阶段。

默认中文 UT 工作流定义在 `ucagent/lang/zh/config/default.yaml`，另有 Formal、Vibe、Increment 等配置。自定义流程通过 `--config <file>` 加载，无需修改框架或额外注册。具体配置方法见[工作流配置](../03_develop/03_workflow.md)。

## 配置与启动入口

- `ucagent/setting.yaml` 提供后端、工具和启动等全局默认设置。
- 语言配置提供对应语言的工作流和任务提示。
- 用户配置、工作区配置、项目 `--config` 和 CLI 覆盖共同决定本次运行的配置，加载顺序见[工作流配置](../03_develop/03_workflow.md#3-配置加载和模板变量)。
- 源码仓库的 `Makefile` 封装工作区准备和 CLI 命令；通过 pip 安装后，可以直接使用 `ucagent` 命令。

TUI、Web 页面是操作入口，后端负责模型交互，工作流定义验证任务。选择界面不会自动改变验收标准。需要扩展框架时，再阅读[架构与工作原理](../03_develop/02_architecture.md)。
