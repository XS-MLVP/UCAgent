
# UCAgent 文档

UCAgent 是面向数字电路单元测试的 AI 验证代理。它读取 DUT 和验证需求，按阶段生成文档、测试代码和覆盖率模型，运行测试并保留可复核的报告。每个阶段都由确定性 Checker 验收，必要时可以人工介入或让外部 Code Agent 通过 MCP 调用工具。

## 先跑通一次

第一次使用建议按下面顺序阅读：

1. [前置依赖安装](./01_start/00_installation.md)：安装 UCAgent、picker 和可选的 Code Agent。
2. [运行模式总览](./01_start/01_modes_overview.md)：选择普通模式、MCP 接入或 Master 模式。
3. 选择一条上手路径：[普通模式](./01_start/02_normal_mode.md)使用 LangChain 直连模型；[MCP 接入](./01_start/03_mcp_mode.md)使用 opencode 等外部 Code Agent。
4. [结果分析与流程总结](./01_start/06_summary.md)：了解工作区和验证产物。

需要集中管理多个任务时，再阅读 [Master 模式](./01_start/04_master_mode.md)。

## UCAgent 的边界

- picker 负责把 RTL 导出为可由 Python 驱动的 DUT 包；UCAgent 负责验证流程和产物管理。
- UCAgent 不替用户决定 DUT 规格。README、RTL 和其他参考文件应先准备好，测试失败也需要结合规格判断是测试问题还是 DUT 缺陷。
- 不同模式共用工作流和 Checker，但模型连接方式、进程数量和交互入口不同。

## 文档导航

本文档组织为以下几个部分：

### 开始使用

1. **[前置依赖安装](./01_start/00_installation.md)**：UCAgent 环境部署、模型配置基础准备
2. **[UCAgent 运行模式总览](./01_start/01_modes_overview.md)**：普通模式与 Master 模式对比，后端选择与交互界面入口
3. **[普通模式](./01_start/02_normal_mode.md)**：DUT 准备、模型配置与终端（TUI）直连验证
4. **[MCP 接入](./01_start/03_mcp_mode.md)**：以 opencode 为例接入外部 Code Agent
5. **[Master 模式](./01_start/04_master_mode.md)**：面向人机协同可视化操作与多任务管理
6. **[任务、工作区和工作流](./01_start/05_architecture.md)**：跑通流程后理解输入、产物和验收
7. **[结果分析 & 通用流程总结](./01_start/06_summary.md)**：统一结果解读、通用操作规范


> 使用导读：先用普通模式或 MCP 模式完成一个任务，再根据需要启用 Master、多实例或批处理。命令中的 `<workspace>`、`<DUT>` 等是需要替换的示意值，不要原样输入尖括号。配置文件中的 `{WORKSPACE}`、`{DUT}`、`{OUT}` 则是 UCAgent 模板变量，`{OUT}` 默认是 `unity_test`。

### 功能介绍

- **[直接使用](./02_usage/01_direct.md)**：使用 LangChain 后端在本地直接运行
- **[人机协同](./02_usage/02_assit.md)**：在 UCAgent 验证过程中进行人机协同
- **[参数说明](./02_usage/03_option.md)**：命令行的各个参数说明
- **[TUI 界面](./02_usage/04_tui.md)**：TUI 界面的组成与操作
- **[FAQ](./02_usage/05_faq.md)**：常见问题
- **[LLM Check & Refinement](./02_usage/06_llm_check.md)**：LLM 阶段结果检查与建议
- **[Web Master 使用指南](./02_usage/07_web_master.md)**：Master 模式 Web 界面详解
- **[技能 SKILL](./02_usage/08_skill.md)**：技能机制与使用

### 定制开发

- **[概览](./03_develop/00_index.md)**：定制开发指南总览
- **[定制开发入门](./03_develop/01_quick_start.md)**：快速创建自定义工作流
- **[架构与工作原理](./03_develop/02_architecture.md)**：UCAgent 核心架构深入解析
- **[工作流配置](./03_develop/03_workflow.md)**：完整的工作流定义和配置说明
- **[模板文件与生成产物](./03_develop/04_template.md)**：模板系统和输出文件结构
- **[定制工具](./03_develop/05_customize.md)**：开发和集成自定义工具
- **[工具列表](./03_develop/06_tool_list.md)**：内置工具完整参考
- **[检查器](./03_develop/07_checkers.md)**：自定义检查器开发指南
- **[Mini 示例](./03_develop/08_mini_example.md)**：完整可运行的示例工作流
- **[插件开发与发布](./03_develop/09_plugins.md)**：插件机制与开发指南

### 实践案例

- **[RTL2Spec 文档生成](./04_case/00_rtl2spec.md)**：基于 XiangShan 源码与 RTL 证据生成设计文档
- **[多实例并发执行](./04_case/01_multirun.md)**：同时对多个 DUT 进行并发验证
- **[批处理执行](./04_case/02_batchrun.md)**：自动完成一系列验证任务
- **[Workflow Builder](./04_case/03_workflow_builder/00_index.md)**：构建、评估和迭代自定义工作流
