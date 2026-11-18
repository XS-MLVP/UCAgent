
# ACT4 资产生成

提供两个独立入口：状态序列/异常场景使用 `privileged-suite-generation`，无 trap 的表驱动
指令测试使用 `unprivileged-suite-generation`。这是生成机制而非 ISA 类别的划分：DeveloperGuide
中的 ZicsrF 等非规则化非特权测试也可采用 priv-style。两者共享资源准备、规范快照和原生贡献验收，但不强行共用
测试计划格式或 generator。已有模块的诊断修复优先使用 [review 工作流](review.md)。
共用编写约定在运行时 `Guide_Doc/ACT4_Asset_Authoring_Guide.md`，设计记录示例在
`Guide_Doc/act4_template/native_asset_design_template.md`；不需要启用 Skill。
先按 [插件安装说明](../README.md) 安装 UCAgent 和插件。

## 1. 准备独立工作区

特权流程共 11 阶段，非特权流程共 8 阶段；两者先准备资源、环境和固定原生输入。
资源阶段复用 [共享源码](environment.md)，只为需要写入的 ACT4 生成树创建独立 clone；ISA 规范保持共享只读。
无需每轮手动 clone 两个仓库，启动前创建独立工作区即可：

```bash
ACT4_WORKSPACE="$PWD/output/act4-H"
mkdir -p "$ACT4_WORKSPACE"
```

需要使用自己的精确版本时，仍可在启动前提供独立、可写的 `riscv-arch-test/`；不要使用共享工作树或符号链接。

运行前确认所选 ACT4 版本具有 `generators/testgen/src/testgen/priv/`、`coverpoints/priv/`
及相应的原生生成、构建入口；非特权需要原生 CSV/template/formatter/decoder 接口。
manual 必须包含相关 `src/**/*.adoc`；正式规则来自官方发布的 norm-rules.json。需要固定版本时，在初始化子模块前 checkout 选定提交；
manual 也应固定在满足本轮规范要求的提交。阶段 01 会记录实际 HEAD、状态和哈希基线。

已有 ITGen 本地依赖时，可以用独立 clone 代替上述下载。以本机 ITGen 路径为例：

```bash
ACT4_SOURCE="$HOME/tmp/ITGen/itgen/spec/RISCV/origin_full/riscv-arch-test"
git clone --no-hardlinks "$ACT4_SOURCE" "$ACT4_WORKSPACE/riscv-arch-test"
git -C "$ACT4_WORKSPACE/riscv-arch-test" checkout --detach \
  "$(git -C "$ACT4_SOURCE" rev-parse HEAD)"
git -C "$ACT4_WORKSPACE/riscv-arch-test" submodule update --init --recursive
```

显式准备 ACT4 时目标目录必须尚不存在；未提供时由资源阶段准备。本地 clone 使用提交内容，
不复制源工作区未提交的改动。manual 默认从共享缓存读取，也可通过下一节的配置指定只读副本。

工作区结构如下：

```text
act4-H/
├── riscv-arch-test/       # 独立 ACT4 副本，生成的正式资产写入此处
└── act4_assets/           # final.md、changes.patch 及 intermediate/，规范默认在共享缓存
```

## 2. 运行生成

`H` 是特权示例，必须替换为精确 ACT suite 名称。输入为 `testplans/priv/<Suite>.yaml`
和 ISA 原文；没有原生计划可新建，不以 CTP 页面是否链接在线表格作为启动条件。
以下示例使用前一节的工作区与已安装插件：

```bash
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4 \
  --plugin-workflow act4:privileged-suite-generation \
  --output act4_assets \
  --backend langchain \
  --tui
```

`--output` 必须是工作区内非空相对目录，与 `riscv-arch-test/` 分离；不能使用工作区
根目录、绝对路径或解析后越出工作区的路径（包括符号链接）。最终报告在
`act4_assets/final.md`，贡献补丁为 `act4_assets/changes.patch`。
默认输出文档为英文，任务提示和配套指南为中文。无需额外传入 ITGen 的
`--config`、`--append-py-path`、`--guid-doc-path` 或模板路径。

manual 优先使用工作区已有的 `riscv-isa-manual/`，否则复用共享来源。复用外部只读规范库时，可用环境变量：

```bash
ACT4_MANUAL_ROOT="$HOME/tmp/ITGen/itgen/spec/RISCV/origin_full/riscv-isa-manual" \
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4 \
  --plugin-workflow act4:privileged-suite-generation \
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

### 非特权指令生成

使用独立工作区和原生 suite 名称，例如为 Zba 指令资产生成/补齐使用：

```bash
mkdir -p output/act4-Zba
ucagent output/act4-Zba Zba \
  --plugin act4 \
  --plugin-workflow act4:unprivileged-suite-generation \
  --output act4_assets --backend langchain --tui
```

流程依次为资源、环境、原生输入、指令矩阵、原生资产、贡献清单、隔离验证和最终报告。
权威计划是 `testplans/<Suite>.csv`，包括 XLEN、可选 ExtraExtensions 和 coverpoint/variant。
优先复用原生模板、coverpoint generator、formatter；仅按需增加这些扩展点或 decoder。
不需要特权 VM/resource contract，也不放宽整个框架的修改权限。已有完整资产主要需要
审查时使用 review，而不是重复生成。两种生成入口都支持关闭 Skill。

### MCP 模式

使用外部代码代理驱动 UCAgent 时，在同一命令中开启 MCP 并生成入口说明：

```bash
ucagent "$ACT4_WORKSPACE" H \
  --plugin act4 \
  --plugin-workflow act4:privileged-suite-generation \
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

## 3. 工作流与产物

| 阶段 | 主要工作 |
| --- | --- |
| prepare_resources | 复用固定版本源码，为生成准备独立可写副本 |
| prepare_environment | 复用工具、安装缺项并复验，保留环境报告 |
| prepare_generation_inputs | 捕获原生计划、规范逐文件快照及正式规则 JSON |
| 01 coverpoints | 冻结 ACT4 基线，完善原生计划并生成 coverage；CSV/Markdown 自动派生 |
| 02 norm mapping | 建立 normative rule 到 coverpoint 的映射 |
| 03 VM resources | 按实际子场景建立 VM/resource 契约与能力处置 |
| 04 generator | 使用冻结版本的 ACT4 API 编写可独立交付的 suite generator |
| 05 build | 原生生成、编译 ELF、参考模型 self-checking 及可用的 coverage 验证 |
| 06 contribution | 整理贡献集，在干净副本复核独立生成和相关本地 CI 步骤 |
| validate_native_contribution | 只应用贡献集，核对生成一致性、hooks、参数/CTP、选定原生配置编译运行 |
| 07 final report | 生成最终报告并核对审查、状态及文件清单 |

以下路径均相对工作区，`<OUT>` 对应 `--output`，`<Suite>` 对应 suite 名：

| 路径 | 内容 |
| --- | --- |
| `<OUT>/intermediate/<Suite>/` | CSV、人类 testplan、coverage 草稿、VM/resource 和 coverage intent 契约 |
| `<OUT>/intermediate/<Suite>/inputs/` | 原生计划、规范、规则 JSON 和固定来源收据 |
| `<OUT>/final.md` | 人工复核入口、结论、复现命令及限制 |
| `<OUT>/changes.patch` | 仅包含 contribution_set 的贡献补丁，不混入构建与工具产物 |
| `<OUT>/intermediate/<Suite>/reports/` | 累积 AI review、validation state、基线、switch audit、file manifest 和 checker 报告 |
| `<OUT>/intermediate/<Suite>/experimental/` | 与正式生成链隔离的实验资产 |
| `riscv-arch-test/coverpoints/{priv,unpriv,norm,param}/` | 正式 coverage/init 和 normative mapping |
| `riscv-arch-test/generators/testgen/src/testgen/priv/extensions/<Suite>.py` | 正式 generator |
| `riscv-arch-test/tests/priv/<Suite>/` | ACT4 原生生成的汇编测试 |
| `riscv-arch-test/work_itgen_<Suite>/` | 独立构建目录、ELF、签名和参考模型日志 |

先查看最终报告，再按 Report index 检查 validation state、AI review、清单及实际运行日志。
`approved_with_limitations`、`contribution_ready`、参考模型执行和 Sail/RVVI coverage
表示不同范围的结论。未运行的工具、未验证的目标、框架能力缺口和实验内容必须保留限制，
不得宣称外部 DUT 验证、全量认证、远程 CI 通过或人工审批。
参考模型失败不能直接缩减资产生成范围；受保护 ACT4 核心代码变化会阻塞工作流。

具体阶段契约见[运行指南](../src/ucagent_act4/Guide_Doc/ACT4_Privileged_Suite_Workflow_Guide.md)，
checker 边界见[checker 总览](../src/ucagent_act4/Guide_Doc/ACT4_Checker_Guide/README.md)。

## 4. 贡献边界与结论

两种流程均交付原生计划、规范映射、条件适用的参数映射、CTP 集成和对应生成源码。
生成 `.S` 是否随源码贡献遵循固定 ACT 的 Git tracked/ignore 规则，不再一概排除。
测试修复仍在 generator 中完成并重新生成；ELF、日志、工具和本地证据不进入贡献 patch。

最终报告区分资产齐备、实际验证、人工提交前提。真实原生验证收据与 generation_result
摘要须一致。缺工具是未验证限制，命令失败和零 ELF 不是通过；DCO、加密签名和维护者审批
由贡献者完成，不由 AI 冒充。suite 级原生验证不等于完整上游 CI，尤其共享模板/decoder
变化需扩大回归。公开规则发布版本与 manual HEAD 独立，规则文本仍需人工/语义核对。

共同契约和完整示例见 [原生生成指南](../src/ucagent_act4/Guide_Doc/ACT4_Generation_Guide.md)。
