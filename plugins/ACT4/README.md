
# UCAgent ACT4 插件

帮助 AI 从规范生成 RISC-V ACT4 测试资产、审查并修复已有资产，以及为香山 Kunminghu V3 准备测试交付包。
工作流负责资源复用、工具准备和分阶段检查，最终给出报告、补丁或交付包，并说明未验证范围与遗留问题。

## 选择工作流

两个生成入口都包含审查和增量修复；香山交付保持独立。按生成机制选择入口。

| 工作流 | 适合的任务 |
| --- | --- |
| `privileged-suite-generation` | 从规范生成场景型测试资产，适合状态序列、异常和特权行为；[详情](docs/generation.md) |
| `unprivileged-suite-generation` | 从规范创建或完善指令测试计划，生成无 trap 的表驱动资产；[详情](docs/generation.md#非特权指令生成) |
| `xiangshan-v3-handoff` | 为指定香山模块选择、补全并适配 ACT 资产，交付可追溯源码和 ELF；[详情](docs/xiangshan.md) |

## 一句话开始

在 UCAgent 仓库目录打开能执行终端命令的 AI agent（例如 Codex、OpenCode），复制下面这句话，
将 **【】中的内容**替换为自己的需求，再交给 agent 执行：

```text
请先阅读 plugins/ACT4/docs/agent-run.md，使用 UCAgent ACT4 插件，以 codex 后端运行【工作流：privileged-suite-generation】，为【目标：Sstc】完成任务，请创建或复用【运行配置：run-Sstc.yaml】，工作区使用【工作区：output/act4-Sstc】，资产策略为【策略：默认改进上游已有资产，缺失则生成】，请准备启动条件、实际调用并跟踪 UCAgent，结束后告诉我完成情况、最终报告与补丁或交付包的位置，以及尚未完成的事项及原因。
```

| 替换内容 | 怎么填写 |
| --- | --- |
| **工作流** | 从上表选择一个完整工作流名。 |
| **目标** | 两个生成工作流从 [Test Suite 目录](docs/test-suites.md) 选择，如 `Sstc`、`I`、`Vx32`；香山流程填写模块名，如 `Vector`。 |
| **工作区** | 本次任务的独立目录；恢复已有任务时填写原工作区。 |
| **运行配置** | 两个生成流程的运行选择集中到这份 YAML；[示例与字段](docs/run-configuration.md)。 |
| **策略** | 默认改进上游资产；可逐类指定本地输出目录或从 ISA 重生成。香山输入见其详情。 |

用户不需要手动拼接 UCAgent 命令或逐个推进阶段；agent 按 [执行指南](docs/agent-run.md) 准备环境、
使用 Codex 后端启动任务并跟踪结果。需要模型授权或确实缺少的外部输入时，agent 会说明需要你提供什么。

## 更多说明

- [Test Suite 完整目录](docs/test-suites.md)：可选目标及名称说明。
- [规范驱动的补全范围](docs/support-boundaries.md)：哪些缺项由工作流补全，哪些需要外部信息。
- [环境与资源复用](docs/environment.md)、[开发与维护](docs/development.md)：操作细节与维护方法。

本插件沿用仓库根目录的 [许可证](../../LICENSE)、[贡献流程](../../CONTRIBUTING.md)和[漏洞报告渠道](../../SECURITY.md)。
