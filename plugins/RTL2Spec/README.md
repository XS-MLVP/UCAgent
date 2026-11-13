
# RTL2Spec

从香山源码或 Verilog/SystemVerilog RTL 生成中文设计文档、功能检测点和验证计划。流程为获取证据、编写草稿、源码复核、最终验收。

## 安装

需要 Python 3.11+、Linux/macOS 和 UCAgent `>=26.9.2.dev14`。先用 `cd` 进入仓库根目录，使下面的 `.` 和 `./plugins/RTL2Spec` 指向正确的安装源。两条 `pip install` 分别安装 UCAgent 核心和 RTL2Spec 插件；最后用 `--validate-plugin` 检查当前 Python 环境能否加载插件及其依赖：

```bash
cd "[你的UCAgent仓库绝对路径]"
python -m pip install .
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

核心和插件须安装在同一 Python 环境。macOS 安装前设置 `export ARCHFLAGS="-arch $(uname -m)"`。下文使用 Codex 后端，先按 [UCAgent 使用说明](https://github.com/XS-MLVP/UCAgent/blob/main/README.zh.md)配置后端。

## 目录约定

安装完成后，在独立的任务目录准备输入并启动，不必留在 UCAgent 仓库中。下面两个示例分别使用 `~/rtl2spec-runs/generic/` 和 `~/rtl2spec-runs/xiangshan/`：

| 位置 | 用途 |
| --- | --- |
| UCAgent 仓库根目录 | 执行安装命令，提供插件源码和示例 RTL |
| 任务目录 | 存放 `rtl2spec.yaml`，执行模板导出和启动命令 |
| YAML 的 `rtl2spec.workspace` | 存放输入与生成结果；相对路径以 YAML 所在目录为基准 |
| YAML 的 `rtl2spec.output` | 工作区内的输出目录，必须为空或尚不存在 |

任务目录可以自行更换，后续 `cd` 路径保持一致。`rtl2spec --init` 在当前目录导出配置，不覆盖已有文件；`Guide_Doc/`、`.ucagent/` 和输出由运行时生成，无需手工创建。

## 示例一：通用 RTL（Example: GenericBlock）

### 准备配置和输入

先用 `mkdir -p` 创建保存本次配置的任务目录，再用 `cd` 进入它。`--init generic` 将[通用 RTL 配置模板](src/rtl2spec/launch_configs/generic.yaml)导出为当前目录的 `rtl2spec.yaml`，供下一步编辑：

```bash
mkdir -p ~/rtl2spec-runs/generic
cd ~/rtl2spec-runs/generic
rtl2spec --init generic
```

接着创建工作区的 `inputs/GenericBlock/`。插件按 `inputs/模块名/` 查找通用 RTL，因此把示例源码和参数配置复制到这里，作为本次生成的输入：

```bash
mkdir -p generic-spec-workspace/inputs/GenericBlock
cp -R "[UCAgent仓库绝对路径]/plugins/RTL2Spec/examples/GenericBlock/." generic-spec-workspace/inputs/GenericBlock/
```

编辑当前目录的 `rtl2spec.yaml`。模板内容如下，注释仅用于标出替换位置：

```yaml
rtl2spec:
  workspace: ./generic-spec-workspace  # [工作区路径]
  module: GenericBlock                # [RTL 顶层模块名]
  workflow: generic-design-document
  output: outputs                     # [本次输出目录]

backend:
  key_name: codex                      # [已配置的后端]

template_overwrite:
  GENERIC_CONFIG: Generic              # [文档配置标签]
```

准备后的目录为：

```text
~/rtl2spec-runs/generic/
├── rtl2spec.yaml
└── generic-spec-workspace/
    └── inputs/
        └── GenericBlock/
            ├── GenericBlock.sv
            └── rtl2spec.json
```

`GenericBlock.sv` 是带同步复位和使能的寄存器示例。输入目录中的 `rtl2spec.json` 将 `WIDTH` 设为 32；它配置 HDL 文件顺序、include、宏和参数，与任务目录中的启动 YAML 用途不同。简单输入可以省略 JSON，支持范围见[通用输入指南](src/rtl2spec/Guide_Doc/generic-generation-guide.md)。

### 替换成自己的模块

例如改为 `Uart` 时，修改以下位置；不要只改 RTL 文件名：

| 位置 | 如何修改 |
| --- | --- |
| `rtl2spec.yaml` 的 `rtl2spec.module` | 将 `GenericBlock` 改为 `Uart`，与源码中的 `module Uart` 完全一致 |
| 工作区的 `inputs/GenericBlock/` | 换为 `inputs/Uart/`，放入自己的顶层 RTL、依赖文件及 include 文件 |
| `inputs/Uart/rtl2spec.json` | `files` 改为实际源文件列表，按需设置 `include_dirs`、`defines` 和 `parameters`；路径相对 `inputs/Uart/`。删除或替换示例的 `WIDTH` 参数，不能覆盖目标模块未声明的参数 |
| `rtl2spec.yaml` 的 `template_overwrite.GENERIC_CONFIG` | 按需修改文档标签，例如 `Uart32`；这个标签不会设置 HDL 参数 |
| `rtl2spec.yaml` 的 `workspace` / `output` | 按需换工作区；已有生成结果时，为新任务选择新的空输出目录 |

RTL 文件名可以与模块名不同，只需 `files` 指向实际文件。`workflow` 保持 `generic-design-document`。

完成配置和输入准备后，继续[启动文档生成](#启动文档生成)，选择通用 RTL 的任务目录。

## 示例二：香山（Example: Sbuffer）

### 准备配置和源码

需要 Bash、Git、Curl、Make 和 C 编译器；插件按需准备 JDK 17 和 Mill。先创建并进入独立的香山任务目录，再用 `--init xiangshan` 将[香山配置模板](src/rtl2spec/launch_configs/xiangshan.yaml)导出为该目录的 `rtl2spec.yaml`：

```bash
mkdir -p ~/rtl2spec-runs/xiangshan
cd ~/rtl2spec-runs/xiangshan
rtl2spec --init xiangshan
```

接着为生成 RTL 准备完整源码：`mkdir -p` 创建源码父目录，`git clone` 下载香山仓库，`checkout` 固定本次使用的源码版本，`submodule update` 获取与该版本配套的依赖仓库。`git -C` 指定要操作的仓库，因此这些命令都可以在香山任务目录执行：

```bash
mkdir -p xiangshan-spec-workspace/third_party
git clone https://github.com/OpenXiangShan/XiangShan.git xiangshan-spec-workspace/third_party/XiangShan
git -C xiangshan-spec-workspace/third_party/XiangShan checkout --detach aee742c92250058644c3166fae54c489161347cc # [可改：目标源码提交]
git -C xiangshan-spec-workspace/third_party/XiangShan submodule update --init --recursive
```

当前目录的 `rtl2spec.yaml` 内容为：

```yaml
rtl2spec:
  workspace: ./xiangshan-spec-workspace  # [工作区路径]
  module: Sbuffer                       # [目标模块名]
  workflow: xiangshan-design-document
  output: outputs                       # [本次输出目录]

backend:
  key_name: codex                        # [已配置的后端]

template_overwrite:
  XS_CONFIG: DefaultConfig              # [香山配置类名]
```

准备后的目录为：

```text
~/rtl2spec-runs/xiangshan/
├── rtl2spec.yaml
└── xiangshan-spec-workspace/
    └── third_party/
        └── XiangShan/
            ├── .git/
            ├── src/main/scala/
            └── ...（其余仓库文件及递归子模块）
```

已有干净的源码仓库时，可将完整 Git checkout 放在工作区的 `third_party/XiangShan/`，并初始化递归子模块。不需要把 `Sbuffer.scala` 单独复制到 `inputs/Sbuffer/`，也不需要事先提供 RTL；插件从该源码版本和配置生成证据。

### 替换成其他香山模块或配置

| 位置 | 如何修改 |
| --- | --- |
| `rtl2spec.yaml` 的 `rtl2spec.module` | 将 `Sbuffer` 改为目标模块名，使用该源码版本中实际存在的 Chisel 类及对应生成模块名 |
| `rtl2spec.yaml` 的 `template_overwrite.XS_CONFIG` | 将 `DefaultConfig` 改为该源码版本中实际存在的配置类名；它会影响生成 RTL 使用的硬件参数 |
| 上述 `git checkout` 的提交号 | 按设计需求选择源码版本，然后重新执行递归子模块初始化，保持工作树干净 |
| `rtl2spec.yaml` 的 `workspace` / `output` | 按需换工作区；更改模块、源码或配置后，用新的空输出目录生成 |

`workflow` 保持 `xiangshan-design-document`，源码目录仍为所选工作区下的 `third_party/XiangShan/`。目标模块还须能在所选配置的生成结果中找到，详细要求见[香山输入指南](src/rtl2spec/Guide_Doc/xiangshan-input-guide.md)。

完成配置和源码准备后，继续[启动文档生成](#启动文档生成)，选择香山的任务目录。

## 启动文档生成

前面两个示例完成的是配置和输入准备。`--init` 用于首次创建 YAML；现在使用已有的 YAML 启动生成，无需再次导出模板。

### 1. 进入要运行的任务目录

如果准备的是 GenericBlock，执行：

```bash
cd ~/rtl2spec-runs/generic
```

如果准备的是 Sbuffer，执行：

```bash
cd ~/rtl2spec-runs/xiangshan
```

两者选择一个。切换目录是为了让后续命令中的 `rtl2spec.yaml` 指向你刚准备的配置文件；输入源码仍位于该配置指定的工作区内。

### 2. 开始生成文档

确认配置和输入准备好后，在同一目录执行：

```bash
rtl2spec --config rtl2spec.yaml
```

`--config rtl2spec.yaml` 指定要读取的配置文件。这条命令读取 YAML，启动选定的后端，并按 `workflow` 执行获取证据、编写草稿、源码复核和最终验收。通用工作流读取 `inputs/模块名/` 中的 RTL；香山工作流先根据源码和 `XS_CONFIG` 生成目标 RTL，再编写文档。配置有误时按报错提示修正，再执行同一条命令。

结果写入 `workspace` 下的 `output` 目录。使用本页配置时，两个任务分别输出到：

| 任务 | 输出目录 |
| --- | --- |
| GenericBlock | `~/rtl2spec-runs/generic/generic-spec-workspace/outputs/` |
| Sbuffer | `~/rtl2spec-runs/xiangshan/xiangshan-spec-workspace/outputs/` |

如果想从其他目录启动，可以直接指定配置文件的完整路径。例如下面的命令仍运行同一个 GenericBlock 任务：

```bash
rtl2spec --config ~/rtl2spec-runs/generic/rtl2spec.yaml
```

更换模块、输入或配置后开始新任务时，将 YAML 中的 `output` 改为新的空目录，如 `outputs/run-002`，用于保留上一轮结果并避免新旧证据混用。同一次运行中可以修订当前文档并重新验收。其他字段与后端配置见[启动配置参考](docs/reference.md#启动配置)。

## 查看生成结果

结果保存在配置指定的工作区和输出目录中，下表的 `[模块名]` 由 YAML 的 `rtl2spec.module` 自动替换，无需手工创建这些文件：

| 文件或目录 | 内容 |
| --- | --- |
| `[模块名]_design_document_zh.md` | 设计说明、功能检测点、Testplan 与开放项 |
| `[模块名]_document_quality_review.md` | 复核发现、限制与自动验收区块 |
| `semantic_review.json` | 各行为的源码复核记录 |
| `validation.json` | 最终验收结果和文件摘要 |
| `evidence/` | RTL、精确端口清单、输入基线；`ports.md` 提供附录 A 骨架 |
| `logs/` | 工具调用和阶段耗时 |

先读设计文档，再查看质量报告与验收记录。验收覆盖文档结构、引用和证据一致性；本流程不执行仿真或形式化验证，未执行项目保留 `Unrun`/`Open`。常见报错与修复入口见[工具参考](docs/reference.md#常见问题)。

流程不依赖 Skill。Mermaid 图保留在 Markdown 源码中，阅读时使用支持 Mermaid 的查看器即可。

## 相关文档

- [工作流与工具参考](docs/reference.md)：操作、验收和排障。
- [插件原理与设计](docs/architecture.md)：背景、数据流、检查依据及能力边界。
- [开发与验证](docs/development.md)：代码结构、测试和打包。
