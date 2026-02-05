# 欢迎来到 UCAgent 文档

本文档提供了安装、使用和开发 UCAgent 的全面指南。

## 概述

**UCAgent** 是一个基于大语言模型的自动化硬件验证智能体，专注于芯片设计的单元测试(Unit Test)验证工作。该项目通过 AI 技术自动分析硬件设计，生成测试用例，并执行验证任务生成测试报告，从而提高验证效率。

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

- **[工作流](./03_develop/01_workflow.md):** 整体工作流与自定工作流方法
- **[模板文件](./03_develop/02_template.md):** 输入的模板文件和生成文件解释
- **[定制工具](./03_develop/03_customize.md):** 自定义 MCP 工具
- **[工具列表](./03_develop/04_tool_list.md):** 已有工具列表
- **[checker](./03_develop/01_workflow.md/#定制校验器checker):** 增加、减少、自定义校验器

### 自定义工作流

- **[完整指南](./04_custom_workflow/00_index.md):** 从零开始创建自定义工作流的完整教程
- **[架构原理](./04_custom_workflow/01_ucagent_architecture.md):** UCAgent 核心架构与工作流程
- **[工作流配置](./04_custom_workflow/02_create_workflow.md):** 定义验证任务的步骤和检查点
- **[模板系统](./04_custom_workflow/03_template_files.md):** 编写模板文件指导 Agent 生成规范文档
- **[自定义工具](./04_custom_workflow/04_custom_tools.md):** 实现领域专用的工具扩展
- **[自定义检查器](./04_custom_workflow/05_custom_checkers.md):** 开发检查器验证业务规则和输出质量
- **[Mini 示例](./04_custom_workflow/06_mini_example.md):** 完整的可运行示例（文档生成器）
- **[Formal 案例](./04_custom_workflow/07_formal_analysis.md):** 专业领域深入实践（形式化验证）
- **[运行与调试](./04_custom_workflow/08_run_debug.md):** 运行技巧和问题排查

### 实践案例

- **[规范生成](./04_case/00_genspec.md):** 从分散设计资料生成功能规范文档
- **[多实例并发执行](./04_case/01_multirun.md):** 同时对多个 DUT 进行并发验证
- **[批处理执行 ](./04_case/02_batchrun.md):** 自动完成一系列验证任务
