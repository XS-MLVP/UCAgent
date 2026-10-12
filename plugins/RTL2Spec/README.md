
# RTL2Spec

RTL2Spec 根据源码和 RTL 证据，为指定模块生成中文设计与功能检测点文档。插件提供两条并列的工作流，共用文档模板、质量报告和验收规则。

## 安装

支持 Linux/macOS，需要 Python 3.11+ 和 UCAgent `>=26.9.2.dev14`。在同一 Python 环境中安装 UCAgent 和插件。以下命令从 UCAgent 仓库根目录执行；已有兼容 UCAgent 时可跳过第一条命令：

```bash
python -m pip install .
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

macOS 安装前先执行 `export ARCHFLAGS="-arch $(uname -m)"`，按当前机器架构编译依赖。教程默认使用 Codex 后端；运行前安装并登录 Codex CLI（`codex login`），再按 [UCAgent 使用说明](https://github.com/XS-MLVP/UCAgent/blob/main/README.zh.md)完成配置。

## 共同运行方式

两种工作流都按“核验输入与 RTL 证据 → 编写文档和质量报告 → 源码语义复核 → 最终验收”执行。每个阶段读取与当前任务相关的参考文件；端口表骨架由工具生成，正文使用逻辑接口名，附录 A 逐项映射 `ports.csv` 中的全部精确 RTL 端口，包括时钟、复位及非 `io_*` 名称。Mermaid 图保留为 Markdown 源码，不需要 Node.js 或浏览器。

准备独立工作区和输入后，使用下面的命令启动；两个教程分别给出 `SPEC_WORKSPACE`、`SPEC_MODULE`、`SPEC_WORKFLOW` 和配置的设置方法：

```bash
ucagent "$SPEC_WORKSPACE" "$SPEC_MODULE" \
  --backend codex \
  --plugin rtl2spec \
  --plugin-workflow "rtl2spec:$SPEC_WORKFLOW" \
  --output outputs \
  --no-history \
  --mcp-server-no-file-tools
```

`--mcp-server-no-file-tools` 适用于 Codex 等非 LangChain 后端，让文件读写经过 UCAgent 工具。两条工作流都无需启用 Skill。

### 输出目录与验收

沿用 UCAgent 的 `--output` / `{OUT}` 约定，全部交付产物写入同一个工作区相对目录。上述命令生成：

```text
<workspace>/outputs/
├── <Module>_design_document_zh.md          # 设计与功能检测点文档
├── <Module>_document_quality_review.md    # 质量报告与未签核项
├── semantic_review.json                 # 逐行为复核结论和源码位置
├── validation.json                      # 最终验收结果与工件摘要
├── evidence/
│   ├── <Module>.sv                       # 生成或捕获的顶层 RTL
│   ├── <Module>.preprocessed.sv          # 通用工作流的预处理视图
│   ├── source_map.json                   # 通用工作流的原始源码行映射
│   ├── ports.csv                         # 精确端口清单
│   ├── ports.md                          # 自动生成的附录 A 骨架
│   └── manifest.json                     # 签名的证据与相关源码记录
└── logs/
    ├── actions.jsonl                     # 工具调用结果与耗时
    └── stages.jsonl                      # 各阶段实际起止时间与耗时
```

可以改为 `--output outputs/run-001`，本次运行的文档、报告和证据会一起写入该目录。省略 `--output` 时遵循 UCAgent 默认值 `unity_test`。启动时选定目录必须为空或不存在；若已有文件，请自行归档并清理，或选择新的输出目录。插件不会自动覆盖旧产物。同一次运行中可以继续修订草稿并重新验收。

工作区的输入、`Guide_Doc/`、`.ucagent/` 运行状态和 `.cache/` 工具缓存仍按 UCAgent 工作区约定管理；整理本次交付产物时只需查看选定的输出目录。

源码复核逐项检查接受边界、缓冲与背压、旁路、配置、复位、环境假设和验证计划。finalize 自动更新质量报告并生成最终验收记录；修改设计文档或证据后需要重新复核，修改交付物后需要重新验收。

质量报告只记录实际执行的操作。未运行的仿真、综合、SVA、formal 或 coverage 使用 `Unrun`/`Open`；文档生成完成不代表验证签核完成。精确端口遗漏、重复、名称或方向/位宽错误都会阻止阶段完成。工具调用和问题排查见[工作流与工具参考](docs/reference.md)。

## 选择工作流

| 工作流 | 适用模块 | 输入与 RTL 获取方式 | 配置 |
| --- | --- | --- | --- |
| `rtl2spec:xiangshan-design-document` | XiangShan Chisel/Scala 模块 | 从 `third_party/XiangShan/` 按指定 commit 和配置生成 elaborated RTL | `XIANGSHAN_CONFIG`，默认 `DefaultConfig` |
| `rtl2spec:generic-design-document` | 其他 Verilog/SystemVerilog 模块 | 捕获 `inputs/<Module>/` 中用户提供的顶层 RTL | `RTL2SPEC_CONFIG`，默认 `Generic` |

### 教程：XiangShan 模块

需要 Bash、Git、Curl、Make 和 C 编译器；JDK 17 和 Mill 由插件按需准备或复用。以下示例从 UCAgent 根目录创建工作区，并固定源码基线；也可改为目标设计要求的提交：

```bash
SPEC_WORKSPACE="$PWD/output/xiangshan-spec-workspace"
SPEC_MODULE=Sbuffer
SPEC_WORKFLOW=xiangshan-design-document
export XIANGSHAN_CONFIG=DefaultConfig
mkdir -p "$SPEC_WORKSPACE/third_party"
git clone https://github.com/OpenXiangShan/XiangShan.git "$SPEC_WORKSPACE/third_party/XiangShan"
git -C "$SPEC_WORKSPACE/third_party/XiangShan" checkout --detach aee742c92250058644c3166fae54c489161347cc
git -C "$SPEC_WORKSPACE/third_party/XiangShan" submodule update --init --recursive
```

已有源码时，在 `third_party/XiangShan/` 提供干净的 Git checkout 并初始化递归子模块。`SPEC_MODULE` 必须是实际 Chisel class 名，`XIANGSHAN_CONFIG` 必须是配置 class 名。可选需求说明放入 `inputs/<Module>/`，实现结论以源码和同 commit、同配置的 RTL 为准。不要把插件源码目录作为生成工作区。

完成准备后，在同一终端执行上面的[共同运行命令](#共同运行方式)。香山输入与证据规则见[香山生成指南](src/rtl2spec/Guide_Doc/xiangshan-input-guide.md)。

### 教程：非 XiangShan RTL 模块

将顶层 RTL 和相关源码放入 `inputs/<Module>/`；通用工作流无需 XiangShan 工具链：

```bash
SPEC_WORKSPACE="$PWD/output/generic-spec-workspace"
SPEC_MODULE=GenericBlock
SPEC_WORKFLOW=generic-design-document
export RTL2SPEC_CONFIG=Generic
mkdir -p "$SPEC_WORKSPACE/inputs/$SPEC_MODULE"
cp path/to/GenericBlock.sv "$SPEC_WORKSPACE/inputs/$SPEC_MODULE/"
```

目录示例：

```text
inputs/GenericBlock/
├── GenericBlock.sv       # 唯一声明 module GenericBlock 的顶层文件
└── related_source.sv     # 可选；实际参考的相关源码
```

输入 HDL 文件使用 UTF-8，后缀为 `.v`、`.sv`、`.vh` 或 `.svh`，简单输入中须有唯一顶层声明；有多个候选版本时，通过下述配置显式选择。相关文件位于同一输入树下，不能把顶层 RTL 重复登记为相关文件。

有文件顺序、include、外部宏或顶层整数参数覆盖时，在 `inputs/<Module>/rtl2spec.json` 写入实际配置：

```json
{
  "files": ["GenericBlock.sv"],
  "include_dirs": [],
  "defines": {"HAS_BUS": "1"},
  "parameters": {"WIDTH": 32}
}
```

按实际模块调整四个字段；文件路径相对于模块输入目录，参数必须已经声明。简单输入可省略此文件。配置、预处理视图和源码映射都会纳入证据；不支持的语法在预检时报错。通用工作流不执行综合或仿真。

完成准备后，在同一终端执行上面的[共同运行命令](#共同运行方式)。详细输入契约见[通用生成指南](src/rtl2spec/Guide_Doc/generic-generation-guide.md)。
