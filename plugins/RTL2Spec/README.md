
# RTL2Spec

RTL2Spec 根据模块源码和 RTL 证据，生成中文设计说明、功能检测点及验证计划。插件分别提供香山模块和通用 RTL 模块的工作流，两者使用相同的文档模板、质量报告和验收规则。

## 安装

支持 Linux/macOS，需要 Python 3.11+ 和 UCAgent `>=26.9.2.dev14`。在同一 Python 环境中安装 UCAgent 和插件。以下命令从 UCAgent 仓库根目录执行；已有兼容 UCAgent 时可跳过第一条命令：

```bash
python -m pip install .
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

macOS 安装前先执行 `export ARCHFLAGS="-arch $(uname -m)"`，按当前机器架构编译依赖。教程默认使用 Codex 后端；运行前安装并登录 Codex CLI（`codex login`），再按 [UCAgent 使用说明](https://github.com/XS-MLVP/UCAgent/blob/main/README.zh.md)完成配置。

## 生成流程

两种工作流都经过四个阶段：核验输入并获取 RTL 证据、编写文档和质量报告、对照源码复核、最终验收。插件自动提取端口并生成表格骨架，AI 负责分析模块行为、编写说明和验证计划；checker 检查文档结构、端口、引用和证据的一致性。

先按下面对应的教程准备输入，再执行[启动命令](#启动文档生成)，最后在[输出目录](#查看生成结果)查看文档和验收结果。

## 准备模块输入

| 工作流 | 适用模块 | 输入与 RTL 获取方式 | 配置 |
| --- | --- | --- | --- |
| `rtl2spec:xiangshan-design-document` | 香山 Chisel/Scala 模块 | 从 `third_party/XiangShan/` 按指定提交和配置生成 RTL | `XIANGSHAN_CONFIG` 选择配置类，默认 `DefaultConfig` |
| `rtl2spec:generic-design-document` | 非香山 Verilog/SystemVerilog 模块 | 读取并保存 `inputs/<Module>/` 中用户提供的 RTL | `RTL2SPEC_CONFIG` 标记文档配置，默认 `Generic`；实际输入选项通过 `rtl2spec.json` 指定 |

### 香山模块

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

已有源码时，在 `third_party/XiangShan/` 放置没有未提交修改的 Git 工作树，并初始化递归子模块。`SPEC_MODULE` 使用实际 Chisel 类名，`XIANGSHAN_CONFIG` 使用该源码版本中的配置类名；它决定生成 RTL 时采用的硬件参数，未设置时使用 `DefaultConfig`。可选需求说明放入 `inputs/<Module>/`，实现结论以源码及相同提交、配置下的 RTL 为准。生成工作区应独立于插件源码目录。

准备完成后，在同一终端执行[启动命令](#启动文档生成)。详细输入要求见[香山输入指南](src/rtl2spec/Guide_Doc/xiangshan-input-guide.md)。

### 通用 RTL 模块（非香山）

将顶层 RTL 和相关源码放入 `inputs/<Module>/`；通用工作流无需香山工具链：

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

需要指定文件顺序、include 搜索目录、外部宏或覆盖顶层整数参数时，在 `inputs/<Module>/rtl2spec.json` 写入配置：

```json
{
  "files": ["GenericBlock.sv"],
  "include_dirs": [],
  "defines": {"HAS_BUS": "1"},
  "parameters": {"WIDTH": 32}
}
```

按实际模块填写这四个字段；文件路径相对于模块输入目录，只能覆盖模块已经声明的参数。简单输入可省略此文件。配置、预处理结果和源码行号映射都会纳入证据；超出当前预处理和端口解析能力的输入会在预检时报错。`RTL2SPEC_CONFIG` 用于标记本次文档的配置名称，不替代上述输入选项。

准备完成后，在同一终端执行[启动命令](#启动文档生成)。详细输入要求见[通用输入指南](src/rtl2spec/Guide_Doc/generic-generation-guide.md)。

## 启动文档生成

完成任一输入教程后，使用已设置的 `SPEC_WORKSPACE`、`SPEC_MODULE` 和 `SPEC_WORKFLOW` 启动任务。两种工作流使用相同的命令：

```bash
ucagent "$SPEC_WORKSPACE" "$SPEC_MODULE" \
  --backend codex \
  --plugin rtl2spec \
  --plugin-workflow "rtl2spec:$SPEC_WORKFLOW" \
  --output outputs \
  --no-history \
  --mcp-server-no-file-tools
```

`--mcp-server-no-file-tools` 适用于 Codex 等非 LangChain 后端，让文件读写经过 UCAgent 工具。两条工作流都无需启用 Skill。文档中的 Mermaid 图保留为 Markdown 源码，生成过程不需要 Node.js 或浏览器。

`--output` 指定工作区内的输出目录，启动时该目录必须为空或不存在。可以使用 `--output outputs/run-001` 区分不同任务；若已有文件，请归档并清理，或选择新的输出目录。同一次运行中可以继续修订草稿并重新验收。

## 查看生成结果

上述命令将文档、报告、证据和运行日志集中保存到 `<workspace>/outputs/`：

```text
<workspace>/outputs/
├── <Module>_design_document_zh.md         # 设计说明、功能检测点和验证计划
├── <Module>_document_quality_review.md   # 质量报告与待确认项
├── semantic_review.json                # 逐项行为复核结论和源码位置
├── validation.json                     # 最终验收结果与文件摘要
├── evidence/
│   ├── <Module>.sv                      # 生成或保存的目标模块 RTL
│   ├── <Module>.preprocessed.sv         # 通用工作流的预处理结果
│   ├── source_map.json                  # 通用工作流的原始源码行号映射
│   ├── ports.csv                        # 精确端口清单
│   ├── ports.md                         # 自动生成的附录 A 骨架
│   └── manifest.json                    # 签名的证据与相关源码记录
└── logs/
    ├── actions.jsonl                    # 工具调用结果与耗时
    └── stages.jsonl                     # 各阶段实际起止时间与耗时
```

省略 `--output` 时遵循 UCAgent 默认值 `unity_test`。输入、`Guide_Doc/`、`.ucagent/` 运行状态和 `.cache/` 工具缓存仍保留在工作区对应位置。

阅读结果时，先查看设计文档，再结合质量报告中的开放项和 `validation.json` 确认验收情况。文档附录 A 必须完整、准确地映射实际 RTL 端口；端口遗漏、重复或方向、位宽错误都会阻止阶段完成。最终验收由工具更新报告并记录结果；设计文档或证据变化后需要重新复核，验收所绑定的文件变化后需要重新验收。

验收通过表示文档满足结构、引用和证据一致性要求。模块行为仍需对照源码审阅；本工作流不执行综合、仿真或形式化验证，未执行的验证项目保留 `Unrun`/`Open`。

## 相关文档

- [工作流与工具参考](docs/reference.md)：工具操作、验收要求和常见问题。
- [插件原理与设计](docs/architecture.md)：开发者使用的架构、工作流、证据和 checker 设计说明。
- [开发与验证](docs/development.md)：项目结构、修改约定、测试和打包方法。
