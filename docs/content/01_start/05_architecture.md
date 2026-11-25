
# 理解任务、工作区和工作流

完成一次上手后，可以用四个概念理解 UCAgent：输入资料、工作区、工作流和验收。它们决定 Agent 做什么、文件放在哪里，以及什么时候可以进入下一阶段。

## 输入资料

默认 ToffeeUT 流程使用 RTL 源码与独立需求资料，并通过 Picker 导出的 DUT Python 包进行真实仿真。包可预先由 Make 或 Master Launch 页面编译，也可在流程中使用 `BuildToffeeDUT`；仅启动 `ucagent` 不表示已完成编译或验证。

`<workspace>/<DUT>/README.md` 应描述接口、时序、功能和验证目标。需求不完整时，应先补充资料，避免让 Agent 猜测设计行为。自定义文档工作流可以使用其他类型的输入，不一定需要 DUT 包。

## 工作区与输出目录

`workspace` 是本次任务允许操作的工程目录；`--output` 可覆盖工作流的产物目录，默认 ToffeeUT 使用 `ut_project`。例如：

```text
output/                     # 启动时传入的 workspace
├── Adder/                  # DUT 包、源码和需求
├── Guide_Doc/              # 运行时指导文档
├── ut_project/             # 当前工作流的工程
│   ├── docs/               # 规格、审阅和交付报告
│   ├── testbenches/        # 验证环境和用例
│   └── results/            # 实际运行产生的报告与回执
└── .ucagent/               # 运行配置与任务状态
```

具体产物取决于工作流、启用的阶段和测试结果。波形格式及保存位置由 DUT 和测试配置决定；启动任务本身不保证生成波形或完整报告。结果阅读方法见[结果分析与流程总结](06_summary.md)。

## 工作流与验收

工作流是一组有顺序的阶段。每个阶段规定任务、参考文件、预期输出和 Checker。Agent 使用工具完成任务，再调用 `Check` 查看验收结果；调用 `Complete` 通过最终检查和适用门禁后，才能推进到下一阶段。

框架提示与默认选择在 `ucagent/core/locales/zh.yaml`，其 `workflow` 指针指向 `ucagent/plugins/ToffeeUT/src/toffee_ut/workflows/ut.yaml`（`toffee-ut:ut`）。框架包附带 ToffeeUT 和 UnitTest 资源；后者使用独立旧环境并需显式选择。Formal 等其他插件需另行安装或从源码加载，经 `--plugin` 和 `--plugin-workflow` 选用。自定义配置可通过 `--config <file>` 覆盖，具体配置方法见[工作流配置](../03_develop/03_workflow.md)。

## 配置与启动入口

- `ucagent/setting.yaml` 提供后端、工具和启动等全局默认设置。
- 语言配置提供对应语言的工作流和任务提示。
- 用户配置、工作区配置、项目 `--config` 和 CLI 覆盖共同决定本次运行的配置，加载顺序见[工作流配置](../03_develop/03_workflow.md#3-配置加载和模板变量)。
- 源码仓库的 `Makefile` 封装工作区准备和 CLI 命令；通过 pip 安装后，可以直接使用 `ucagent` 命令。

TUI、Web 页面是操作入口，后端负责模型交互，工作流定义验证任务。选择界面不会自动改变验收标准。需要扩展框架时，再阅读[架构与工作原理](../03_develop/02_architecture.md)。
