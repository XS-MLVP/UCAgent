
# RTL2Spec

使用 XiangShan 源码和生成的 RTL，为指定模块生成中文设计与功能检测点文档。

## 安装

支持 Linux/macOS，需要 Python 3.11+、Bash、Git、Curl、Make 和 C 编译器。JDK 17 和 Mill 由插件按需准备或复用，首次运行需要网络。Mermaid 图直接保留在 Markdown 文档中，不需要 Node.js、Mermaid CLI 或浏览器。

在同一 Python 环境中安装 UCAgent 和插件，要求 UCAgent `>=26.9.2.dev14`。以下命令从 UCAgent 仓库根目录执行；已有兼容 UCAgent 时可跳过第一条命令：

macOS 安装前先执行 `export ARCHFLAGS="-arch $(uname -m)"`，按当前机器架构编译依赖。

```bash
python -m pip install .
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

运行前按 [UCAgent 使用说明](https://github.com/XS-MLVP/UCAgent/blob/main/README.zh.md)配置模型连接。

## 准备工作区

XiangShan 是工作区输入，按需下载。以下示例从 UCAgent 根目录创建工作区，并固定源码基线；也可改为目标设计要求的提交：

```bash
SPEC_WORKSPACE="$PWD/output/spec-workspace"
mkdir -p "$SPEC_WORKSPACE/third_party"
git clone https://github.com/OpenXiangShan/XiangShan.git "$SPEC_WORKSPACE/third_party/XiangShan"
git -C "$SPEC_WORKSPACE/third_party/XiangShan" checkout --detach aee742c92250058644c3166fae54c489161347cc
git -C "$SPEC_WORKSPACE/third_party/XiangShan" submodule update --init --recursive
```

已有源码时，在工作区的 `third_party/XiangShan/` 提供干净的 Git checkout，并初始化其内部子模块。不要把插件源码目录作为生成工作区。

## 生成文档

使用上面的工作区，以 `Sbuffer` 为例：

```bash
XIANGSHAN_CONFIG=DefaultConfig \
ucagent "$SPEC_WORKSPACE" Sbuffer \
  --backend langchain \
  --plugin rtl2spec \
  --plugin-workflow rtl2spec:design-document \
  --output outputs/Sbuffer \
  --no-history
```

| 参数 | 设置方式 |
| --- | --- |
| 模块 | 将 `Sbuffer` 替换为实际 Chisel class 名，同时修改 `--output` |
| 配置 | `XIANGSHAN_CONFIG`，默认 `DefaultConfig` |
| 可选需求说明 | 放入 `inputs/<Module>/`；实现结论仍以源码和 RTL 为准 |

每次运行保留 `--no-history`，从首阶段开始生成。`--output` 及当前模块的 `outputs/<Module>/`、`reports/<Module>/`、`evidence/<Module>/` 目录必须为空或不存在。发现旧产物或未完成的草稿时，插件会终止并提示；请自行打包归档、清理提示的目录后重新运行。

示例使用 LangChain；使用 OpenCode 时将参数改为 `--backend opencode`。无需启用 Skill。

## 查看结果

| 路径 | 内容 |
| --- | --- |
| `outputs/<Module>/<Module>_design_document_zh.md` | 设计与功能检测点文档 |
| `reports/<Module>/<Module>_document_quality_review.md` | 质量报告与未签核项 |
| `evidence/<Module>/` | RTL、`ports.csv`、证据清单和签名的相关模块源码记录；Mermaid 源码位于设计文档中 |

以上路径均相对于工作区。替换模块名后同步修改示例中的 `--output outputs/<Module>`；生成文档始终位于表中的固定路径。

阅读质量报告中的未签核项与 `OPEN-*`；文档生成完成不代表已经通过 SVA 编译或形式化验证。工具调用和问题排查见[工作流与工具参考](docs/reference.md)。
