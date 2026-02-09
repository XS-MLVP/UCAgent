# 欢迎来到 UCAgent 文档

本文档提供了安装、使用和开发 UCAgent 的全面指南。

## 概述

**UCAgent** 是一个基于大语言模型的通用智能体。目前默认的工作流专注于芯片设计的单元测试(Unit Test)自动化验证。该工作流通过 AI ，自动分析硬件设计/验证文档、生成测试用例、执行验证任务并生成测试报告，从而提高验证效率。

- 快速开始使用自动化硬件验证，请直接阅读**[快速入门](./01_start/02_quickstart.md):** 即刻开始使用 UCAgent。
- 自定义其他的工作流,请直接阅读**[定制开发入门](./03_develop/01_quick_start.md):** 快速创建自定义工作流。

## 文档导航

本文档组织为以下几个部分：

### 开始使用

- **[工具介绍](./01_start/00_introduce.md):** UCAgent 出现的背景和详细介绍
- **[工具安装](./01_start/01_installation.md):** 安装 UCAgent
- **[快速入门](./01_start/02_quickstart.md):** 即刻开始使用 UCAgent

### 功能介绍

- **[MCP 集成](./02_usage/00_mcp.md):** 使用 Code Agent 与 UCAgent 共同工作
- **[直接使用](./02_usage/01_direct.md):** 使用 API 直接使用 UCAgent
- **[人机协同](./02_usage/02_assit.md):** 在 UCAgent 验证过程中进行人机协同
- **[参数说明](./02_usage/03_option.md):** 命令行的各个参数说明
- **[TUI 界面](./02_usage/04_tui.md):** TUI 界面的组成与操作
- **[FAQ](./02_usage/05_faq.md):** 常见问题

### 定制开发

- **[概览](./03_develop/00_index.md):** 定制开发指南总览
- **[定制开发入门](./03_develop/01_quick_start.md):** 快速创建自定义工作流
- **[架构与工作原理](./03_develop/02_architecture.md):** UCAgent 核心架构深入解析
- **[工作流配置](./03_develop/03_workflow.md):** 完整的工作流定义和配置说明
- **[模板文件与生成产物](./03_develop/04_template.md):** 模板系统和输出文件结构
- **[定制工具](./03_develop/05_customize.md):** 开发和集成自定义工具
- **[工具列表](./03_develop/06_tool_list.md):** 内置工具完整参考
- **[检查器](./03_develop/07_checkers.md):** 自定义检查器开发指南
- **[Mini 示例](./03_develop/08_mini_example.md):** 完整可运行的示例工作流

### 实践案例

- **[规范生成](./04_case/00_genspec.md):** 从分散设计资料生成功能规范文档
- **[多实例并发执行](./04_case/01_multirun.md):** 同时对多个 DUT 进行并发验证
- **[批处理执行 ](./04_case/02_batchrun.md):** 自动完成一系列验证任务
