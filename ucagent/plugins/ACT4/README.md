
# UCAgent ACT4 插件

为 RISC-V ACT4 测试资产提供三个独立工作流。选择其中一个即可，无需依次运行。

| 工作流 | 用途 | 独立介绍与运行方法 |
| --- | --- | --- |
| `privileged-suite-generation` | 从 CTP/ISA 创建新的 privileged suite | [资产生成](docs/generation.md) |
| `extension-review` | 审查并增量修复上游或本地已有模块资产 | [资产审查](docs/review.md) |
| `xiangshan-v3-handoff` | 按香山模块选择上游 ACT 资产、补全适用缺口并交付可追溯源码/ELF | [香山交付](docs/xiangshan.md) |

三个工作流均在资产生成或构建前准备环境：探测已有工具，按所选 ACT4 版本安装缺项并复验。
优先复用系统和用户已安装的软件，默认新增工具放在持久化用户目录，存在冲突的环境可放临时目录。
工具准备、原生验证与真实 DUT 验证是不同结论，不能相互替代。
安装位置、版本选择、权限/网络失败和中断恢复见 [环境准备与复用](docs/environment.md)。

## 安装插件

需要 Python 3.11+、UCAgent `>=26.9.2.dev25`。在同一 Python 环境中，从 UCAgent 根目录安装：

```bash
python3 -m pip install .
python3 -m pip install ./plugins/ACT4
ucagent --list-plugins
ucagent --validate-plugin act4-privileged-suite
```

已有兼容 UCAgent 时可跳过核心安装。开发时可用 `python3 -m pip install -e ./plugins/ACT4`，
也可直接通过 `--plugin /absolute/path/to/UCAgent/plugins/ACT4` 加载源码。
模型配置见 [UCAgent 使用说明](../../README.zh.md)。若源码运行显示 `0.9.1+source.code`，
先安装核心生成版本元数据，不要降低插件要求；详情见 [开发说明](docs/development.md#源码与安装态)。

插件注册不会下载编译器或参考模型，也不会因尚未安装 Bash/Git/Curl/Make 阻止进入环境准备阶段。
工作流负责其验证工具的准备；UCAgent、插件及模型连接是启动前提。

## 共用操作

各工作流的文档分别列出输入目录、完整启动命令、阶段和产物。`--output` 使用工作区内
与原始输入分离的相对目录。不要同时让多个任务写同一工作区/输出；软件安装目录可以复用。
所有工作流均不依赖 Skill，可添加 `--no-use-skill`。

外部代码代理驱动时，将文档示例中的 `--backend langchain` 替换为
`--mcp-server-no-file-tools --gen-instruct-file AGENTS.md`，按启动输出连接 MCP。
使用 `CurrentTips`、`Check`、`Complete` 推进，并通过 stage journal 保存计划和证据。

中断后使用同一工作区、模块、输出和工作流参数重启，先恢复 journal，再继续当前阶段。
成功安装的软件通过实际版本探测复用；临时目录被清理或工具被替换时需重新准备，不能沿用旧结论。

规范与产物契约位于 [运行指南目录](src/act4_privileged_suite/Guide_Doc/)，测试与打包见
[开发说明](docs/development.md)。本插件沿用仓库根目录的 [许可证](../../LICENSE)、
[贡献流程](../../CONTRIBUTING.md)和[漏洞报告渠道](../../SECURITY.md)。
