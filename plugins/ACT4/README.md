
# ACT4 Privileged Suite

为 RISC-V ACT4 生成可追溯的 privileged-suite 测试资产，依次完成 testplan、coverage、
规范映射、generator、构建验证和贡献交接。静态检查、参考模型通过与 coverage 命中
分别取证；插件通过不代表真实 DUT 验证或架构认证。

已有 extension 使用独立的 `extension-review` 工作流：全面检查资产、输出审查与优化方案、
等待人类批准、修复候选副本并复验，最后交付完整报告和补丁。该流程支持按现有仓库布局
审查 privileged/unprivileged 资产，原始 ACT4 checkout 始终保持不变。

```bash
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4-privileged-suite \
  --plugin-workflow act4-privileged-suite:extension-review \
  --output act4_review --backend langchain --tui
```

先按下文准备独立 checkout（保留要审查的已有资产）和只读规范库。进入人工审批阶段后，
在 UCAgent 控制台执行 `hmcheck_pass <authorization.json 中的 digest>`，再继续 agent；
未批准、拒绝或方案变化时均不能开始修复。输出位于 `act4_review/H/review/`，包括
`review.md`、`final.md`、前后验证证据及 `changes.patch`。完整字段和审批操作见
[已有资产审查指南](src/act4_privileged_suite/Guide_Doc/ACT4_Extension_Review_Guide.md)。
本地原生命令验证不等同于远端 CI 已通过；工具缺失和未覆盖项会保留在报告中。

## 1. 安装

需要 Python 3.11+、UCAgent `>=26.9.2.dev25`。生成工作流需要 Bash、Git、Curl、GNU Make；
审查工作流启动只要求 Git，实际验证工具按目标提交的原生 CI 准备。
在同一 Python 环境中从 UCAgent 仓库根目录安装：

```bash
python3 -m pip install .
python3 -m pip install ./plugins/ACT4
ucagent --list-plugins
ucagent --validate-plugin act4-privileged-suite
```

已有兼容 UCAgent 时可跳过核心安装。开发时可以使用
`python3 -m pip install -e ./plugins/ACT4`，也可直接以
`--plugin /absolute/path/to/UCAgent/plugins/ACT4` 加载本地源码。
模型连接按仓库根目录的 [UCAgent 使用说明](../../README.zh.md)配置。
源码根目录运行若显示 `0.9.1+source.code`，先执行 `python3 -m pip install .`
生成版本元数据，再重新校验；不要降低插件版本要求。源码开发与安装态验证的区别见
[开发说明](docs/development.md#源码与安装态)。

生成和验证所需的 ACT4 Python 环境、交叉编译器、参考模型及可选 Sail/RVVI coverage
依赖，必须按所选 ACT4 提交的 `README.md`、`docs/DeveloperGuide.md` 和配置准备。
插件注册校验不安装这些工具。已有资产审查会先探测、安装缺少的工具并复验，再按依赖顺序
生成测试、构建非空 ELF、实际执行并核对测试结果。公开工具按目标提交 CI 安装至隔离目录；
Questa/VCS 需要可用的合法安装介质和许可证，缺少时报告具体阻塞及恢复动作。
运行中需要联网获取本轮 CTP 及其 Google Sheet CSV。

## 2. 准备独立工作区

每个 suite 使用独立、可写的 ACT4 Git clone。不要把插件源码、共享 ACT4 checkout、
符号链接或 Git worktree 作为 `riscv-arch-test/` 输入，避免生成操作影响其他任务。
以下命令从 UCAgent 根目录执行：

```bash
ACT4_WORKSPACE="$PWD/output/act4-H"
mkdir -p "$ACT4_WORKSPACE"
git clone --branch act4 https://github.com/riscv/riscv-arch-test.git \
  "$ACT4_WORKSPACE/riscv-arch-test"
git -C "$ACT4_WORKSPACE/riscv-arch-test" submodule update --init --recursive
git clone https://github.com/riscv/riscv-isa-manual.git \
  "$ACT4_WORKSPACE/riscv-isa-manual"
```

运行前确认所选 ACT4 版本具有 `generators/testgen/src/testgen/priv/`、`coverpoints/priv/`
及相应的原生生成、构建入口；manual 版本必须包含 `src/**/*.adoc` 和
`normative_rule_defs/*.yaml`。需要固定版本时，在初始化子模块前 checkout 选定提交；
manual 也应固定在满足本轮规范要求的提交。阶段 01 会记录实际 HEAD、状态和哈希基线。

已有 ITGen 本地依赖时，可以用独立 clone 代替上述下载。以本机 ITGen 路径为例：

```bash
ACT4_SOURCE="$HOME/tmp/ITGen/itgen/spec/RISCV/origin_full/riscv-arch-test"
git clone --no-hardlinks "$ACT4_SOURCE" "$ACT4_WORKSPACE/riscv-arch-test"
git -C "$ACT4_WORKSPACE/riscv-arch-test" checkout --detach \
  "$(git -C "$ACT4_SOURCE" rev-parse HEAD)"
git -C "$ACT4_WORKSPACE/riscv-arch-test" submodule update --init --recursive
```

两种 ACT4 准备方式选其一；目标目录必须尚不存在。本地 clone 使用提交内容，
不复制源工作区未提交的改动。manual 也可独立 clone，或通过下一节的配置复用只读副本。

工作区结构如下：

```text
act4-H/
├── riscv-arch-test/       # 独立 ACT4 副本，生成的正式资产写入此处
└── riscv-isa-manual/      # 只读规范输入
```

## 3. 运行生成

`H` 是示例，必须替换为本轮在线 CTP 中的精确 suite 名称。工作流只支持其 Coverpoints
表含唯一 Google Sheet tab 链接、且能导出为非空 CSV 的 privileged suite。
以下示例使用前一节的工作区与已安装插件：

```bash
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4-privileged-suite \
  --plugin-workflow act4-privileged-suite:privileged-suite-generation \
  --output act4_assets \
  --backend langchain \
  --tui
```

`--output` 必须是工作区内非空相对目录，与 `riscv-arch-test/` 分离；不能使用工作区
根目录、绝对路径或解析后越出工作区的路径（包括符号链接）。最终报告在
`act4_assets/H/reports/`。
默认输出文档为英文，任务提示和配套指南为中文。无需额外传入 ITGen 的
`--config`、`--append-py-path`、`--guid-doc-path` 或模板路径。

manual 默认从工作区的 `riscv-isa-manual/` 读取。复用外部只读规范库时，可用环境变量：

```bash
ACT4_MANUAL_ROOT="$HOME/tmp/ITGen/itgen/spec/RISCV/origin_full/riscv-isa-manual" \
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4-privileged-suite \
  --plugin-workflow act4-privileged-suite:privileged-suite-generation \
  --output act4_assets --backend langchain --tui
```

也可用 `--override template_overwrite.ACT4_MANUAL_ROOT=/absolute/path/to/manual`。
相对路径以工作区为基准。正式输出和 ACT4 副本加入可写目录，`Guide_Doc/` 加入只读目录；
manual 位于可写目录之外，外部 manual 还受核心文件工具的工作区边界约束。
插件会拒绝 manual 与输出目录或 ACT4 副本重叠的配置。
ACT4 核心代码的完整性由基线及后续 checker 验证。

工作流不依赖 Skill。可加 `--no-use-skill`，仍使用相同阶段和 checker。
指南及填写模板会复制到工作区 `Guide_Doc/`，并按阶段列入 `reference_files`；
进入阶段后先阅读列出的规范，再读取任务指定的前序产物。

### MCP 模式

使用外部代码代理驱动 UCAgent 时，在同一命令中开启 MCP 并生成入口说明：

```bash
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4-privileged-suite \
  --plugin-workflow act4-privileged-suite:privileged-suite-generation \
  --output act4_assets \
  --mcp-server-no-file-tools --gen-instruct-file AGENTS.md --tui
```

按 UCAgent 启动时显示的地址连接 MCP。外部代理使用自己的文件和终端工具修改工作区，
通过 `RoleInfo`、`CurrentTips`、`Check`、`Complete` 推进阶段，
通过 `StageJournal` 和 `SetCurrentStageJournal` 保存进度；全部完成后调用 `Exit`。

### 中断恢复

使用同一工作区、suite、输出目录和插件参数重新启动，沿用 UCAgent 阶段历史。
先读取当前 stage journal 和现有证据再继续，不能补造历史计划或把未运行命令写成通过。
需要从头重做时使用新工作区，保留原有资产和失败证据。

## 4. 工作流与产物

| 阶段 | 主要工作 |
| --- | --- |
| 01 coverpoints | 冻结 ACT4 基线，获取 CTP/Sheet 和 manual 证据，重建 testplan 并生成 coverage |
| 02 norm mapping | 建立 normative rule 到 coverpoint 的映射 |
| 03 VM resources | 按实际子场景建立 VM/resource 契约与能力处置 |
| 04 generator | 使用冻结版本的 ACT4 API 编写可独立交付的 suite generator |
| 05 build | 原生生成、编译 ELF、参考模型 self-checking 及可用的 coverage 验证 |
| 06 contribution | 整理贡献集，在干净副本复核独立生成和相关本地 CI 步骤 |
| 07 final report | 生成最终报告并核对审查、状态及文件清单 |

以下路径均相对工作区，`<OUT>` 对应 `--output`，`<Suite>` 对应 suite 名：

| 路径 | 内容 |
| --- | --- |
| `<OUT>/<Suite>/` | CSV、人类 testplan、coverage 草稿、VM/resource 和 coverage intent 契约 |
| `<OUT>/<Suite>/references/` | 本轮 CTP、原始 Sheet CSV、选定规范和 metadata 快照 |
| `<OUT>/<Suite>/reports/<Suite>_final_summary_report.md` | 人工复核入口、结论、复现命令及限制 |
| `<OUT>/<Suite>/reports/` | 累积 AI review、validation state、基线、switch audit、file manifest 和 checker 报告 |
| `<OUT>/<Suite>/experimental/` | 与正式生成链隔离的实验资产 |
| `riscv-arch-test/coverpoints/{priv,norm}/` | 正式 coverage/init 和 normative mapping |
| `riscv-arch-test/generators/testgen/src/testgen/priv/extensions/<Suite>.py` | 正式 generator |
| `riscv-arch-test/tests/priv/<Suite>/` | ACT4 原生生成的汇编测试 |
| `riscv-arch-test/work_itgen_<Suite>/` | 独立构建目录、ELF、签名和参考模型日志 |

先查看最终报告，再按 Report index 检查 validation state、AI review、清单及实际运行日志。
`approved_with_limitations`、`contribution_ready`、参考模型执行和 Sail/RVVI coverage
表示不同范围的结论。未运行的工具、未验证的目标、框架能力缺口和实验内容必须保留限制，
不得宣称外部 DUT 验证、全量认证、远程 CI 通过或人工审批。
参考模型失败不能直接缩减资产生成范围；受保护 ACT4 核心代码变化会阻塞工作流。

具体阶段契约见[运行指南](src/act4_privileged_suite/Guide_Doc/ACT4_Privileged_Suite_Workflow_Guide.md)，
checker 边界见[checker 总览](src/act4_privileged_suite/Guide_Doc/ACT4_Checker_Guide/README.md)。

## 5. 常见问题

- 插件找不到：确认插件和 `ucagent` 安装在同一 Python 环境，或使用绝对源码目录作为 `--plugin`。
- CTP 无匹配表/Sheet：检查 suite 大小写和本轮在线 CTP；工作流不会用本地历史 CSV 替代。
- manual 没有可信配对：检查 `ACT4_MANUAL_ROOT`、Git HEAD、ADOC 及 normative metadata 是否完整。
- 生成/构建接口不匹配：按冻结 ACT4 的文档与源码定位，不修改受保护框架来迁就 suite。
- 工具或可选 coverage 不可用：保留真实尝试、证据与影响范围，按阶段规则记录 limitation。

维护、测试与打包步骤见[开发说明](docs/development.md)。本插件沿用仓库根目录的
[许可证](../../LICENSE)、[贡献流程](../../CONTRIBUTING.md)和[漏洞报告渠道](../../SECURITY.md)。
