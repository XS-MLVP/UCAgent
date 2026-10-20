
# 定制开发

定制工作流时，先定义任务和验收标准，再按需增加工具、指导文档和模板。建议先跑通 [Mini 示例](08_mini_example.md)，对照实际文件理解各部分如何协作。

## 学习路线

1. 阅读[定制开发入门](01_quick_start.md)，了解最小工作流的组成。
2. 运行 [Mini 示例](08_mini_example.md)，观察两个阶段如何生成并验收文档。
3. 根据[工作流配置](03_workflow.md)调整阶段、输入和输出。
4. 需要新能力时，编写[工具](05_customize.md)和 [Checker](07_checkers.md)。
5. 需要独立安装和交付扩展时，使用[插件](09_plugins.md)。

## 按问题查阅

| 要解决的问题 | 文档 |
| --- | --- |
| 理解组件职责和执行过程 | [架构与工作原理](02_architecture.md) |
| 配置阶段、模板变量、跳过和人工审核 | [工作流配置](03_workflow.md) |
| 编写运行时指导文档和初始文件 | [模板文件与生成产物](04_template.md) |
| 增加计算、文件或外部服务能力 | [定制工具](05_customize.md) |
| 查找内置工具的用途 | [工具列表](06_tool_list.md) |
| 验证文件、格式、业务规则和批次进度 | [自定义 Checker](07_checkers.md) |
| 运行一个不依赖 RTL 的完整例子 | [Mini 示例](08_mini_example.md) |
| 封装和发布 Tool、Checker、Skill 或工作流 | [插件开发与发布](09_plugins.md) |

首次使用 UCAgent 时，先完成[安装](../01_start/00_installation.md)和[普通模式上手](../01_start/02_normal_mode.md)。CLI 参数见[参数说明](../02_usage/03_option.md)。
