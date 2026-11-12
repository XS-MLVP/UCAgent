
# RTL2Spec 工作流与工具参考

安装和运行命令见 [README](../README.md)，实现结构、测试与打包方法见[开发与验证](development.md)。

## 工作流与验收

文档生成分为四个阶段：捕获或生成 RTL 证据、编写文档、源码语义复核、最终验收。XiangShan 工作流的实现结论来自 Chisel/Scala 源码与同 commit、同配置的 RTL；通用工作流的结论来自 `inputs/{DUT}/` 中已捕获并签名的 Verilog/SystemVerilog 源码。可选需求说明用于核对设计意图，无法确认的内容保留为 `OPEN-*`。

设计文档必须遵循模板规定的固定输出顺序：文档摘要、设计概览、功能行为、验证策略与 Testplan、形式化属性契约、Sign-off 与开放项、附录 A 至附录 E。正文按职责与边界、事务模型、数据/控制通路、资源冲突、时序与状态组织；验证策略记录采样工件，形式化契约记录 harness 边界，Sign-off 和场景使用结构化表格；完整扁平 I/O、参数、源码路径和证据集中在附录。完整要求见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md)和[文档模板](../src/rtl2spec/Guide_Doc/chip_design_document_template_zh.md)。

同一次运行中可继续修订草稿、同步 metadata 和验收。Mermaid 图直接保留在 Markdown 源码中，不生成 SVG、图形清单或其他图片文件。启动新一轮生成前选择空的输出目录，或由用户自行归档并清理旧产物，插件不会自动打包、删除或覆盖旧文件。

两条工作流都使用 UCAgent 的 `--output` 目录（工作流中为 `{OUT}`）：设计文档和质量报告位于目录根部，RTL、端口清单/骨架和 `manifest.json` 位于其 `evidence/` 子目录；复核记录与最终验收记录位于目录根部，调用耗时位于 `logs/actions.jsonl`，阶段起止时间与总耗时位于 `logs/stages.jsonl`。工具、阶段参考文件和验收均使用同一目录；完整布局见 [README](../README.md#查看生成结果)。

确定性检查从草稿阶段启用。完整字段、状态与引用规则见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md#确定性验收规则)。规则允许多对多追溯、共享接口、有理由的不适用项及额外说明表；检查通过不代表实现语义或硬件功能正确。

## 启动配置

`rtl2spec --config rtl2spec.yaml` 读取 YAML 中的 `rtl2spec` 区块选择工作区、模块和工作流，其余区块按 UCAgent 的配置层级加载。模板随插件安装，可用 `rtl2spec --init generic` 或 `rtl2spec --init xiangshan` 导出；`--config` 同时指定导出目标，已有文件不会被覆盖。配置文件缺失、YAML 格式错误或启动字段无效时，命令会报错并以非零状态退出。

| 字段 | 用途 |
| --- | --- |
| `rtl2spec.workspace` | 必填。工作区路径；相对路径以 YAML 所在目录为基准，支持绝对路径和 `~` |
| `rtl2spec.module` | 必填。精确顶层模块名 |
| `rtl2spec.workflow` | 必填。`generic-design-document` 或 `xiangshan-design-document` |
| `rtl2spec.output` | 默认 `outputs`。工作区内的空目录或尚不存在的目录 |
| `backend.key_name` | UCAgent 后端；两个模板均使用 `codex` |
| `template_overwrite.GENERIC_CONFIG` | 通用 RTL 的文档配置标签；实际编译选项仍来自输入目录中的 `rtl2spec.json` |
| `template_overwrite.XS_CONFIG` | 香山生成时使用的配置类名 |

启动配置中直接写明的配置标签覆盖工作流的环境变量默认值，不需要额外 export。可在同一 YAML 中增加 UCAgent 支持的配置区块；`rtl2spec` 区块只接受上表四个启动字段。选择不同模块或不同参数时分别保存配置，并使用独立的工作区或输出目录。

启动器使用当前 Python 环境执行原有 `ucagent` CLI，固定启用 `--no-history` 和 `--mcp-server-no-file-tools`，使新任务从第一阶段开始并通过 UCAgent 工具读写文件。配置文件放在输入目录之外，避免被作为 DUT 源码捕获；它与工作区可以分别存放。

## FM-Agent 管理

通过以下命令分别管理源码、依赖和本地路径。fetch 和 install 会显示操作提醒并请求确认；使用 `-y` 或 `--yes` 可跳过询问。非交互运行需提供该选项。一键脚本同样接受并传递该选项。

| 命令 | 参数与行为 |
| --- | --- |
| `rtl2spec fmagent fetch` | `--fmagent-root`、`--repo`、`--branch`；默认获取 `https://github.com/fmagent-project/FM-Agent` 的 `main` 到插件 `third_party/FM-Agent`，已有有效 checkout 仅复用，不更新、安装或绑定 |
| `rtl2spec fmagent install` | `--fmagent-root`；要求已有源码，调用其 `bash install.sh` 准备 `root/.venv`，可显式透传 `--with-dsh`、`--with-erlang`、`--with-chisel` |
| `rtl2spec fmagent bind` | `--fmagent-root`、`--fmagent-python`；仅保存路径，可绑定尚未准备依赖的源码并提醒；缺源码报错 |
| `rtl2spec fmagent status` | `--fmagent-root`、`--fmagent-python`；显示路径及来源，本地短时检查源码、解释器、Python 导入和原生配置 |

`status` 就绪返回 0，环境未就绪返回 1，参数/本地 TOML 错误返回 2。它不验证模型凭据或外部工具是否可执行。fetch 的来源/分支差异只作本地提醒：默认目录按默认值或显式值比较，自定义目录仅比较显式值；不修改 remote、切换分支或清理用户改动。开发来源可显式选 `--repo https://github.com/n3sRan/FM-Agent --branch feat/chip-only-spec`，不固定提交、不登记 submodule。

管理命令（独立 `bind` 除外）共用路径选择：**显式参数 > 进程环境 > 插件本地 TOML > 默认值**。环境变量为 `RTL2SPEC_FMAGENT_ROOT`、`RTL2SPEC_FMAGENT_PYTHON`；不读取任何 `.env` 来选择这些路径。路径支持 `~` 和相对路径并转为绝对路径，空字符串按未提供处理。Python 默认选定 root 下的 `.venv/bin/python`，只能由 root 同层或更高层的 Python 覆盖；例如环境 root 不继承 TOML Python，显式 root 不继承环境 Python。

绑定文件固定为保留的插件源码根目录 `rtl2spec.local.toml`，不依赖当前目录，也不使用 HOME 全局注册表：

```toml
[fmagent]
root = "/absolute/path/to/FM-Agent"
python = "/absolute/path/to/FM-Agent/.venv/bin/python"
```

独立 `bind` 按 **显式参数 > 本地 TOML > 默认值** 选择保存目标，不读取临时 `RTL2SPEC_FMAGENT_*`；root/python 仍按同层配对。它只更新两个路径字段，保留其他表、字段和注释，不修改 shell 配置或任务 YAML；进程环境仍可临时覆盖保存值并显示提醒。损坏 TOML 需要修正，或在路径选择时同时显式指定 root/python 绕过；bind 不能覆盖无法解析的文件。管理功能要求从保留的本地目录普通或 editable 安装，不支持独立 wheel；删除原来源后需重新从本地源码安装。

源码 `scripts/install.sh` 先用 `--python` 指定的 Python（默认 `python3`，需含 pip）安装插件声明依赖，再用同一环境顺序执行 fetch/install/bind。可用 `--skip-fetch`、`--skip-install`、`--skip-bind` 跳过对应动作；三个全跳过时只装插件。脚本支持 `--fmagent-root`、`--fmagent-python`、`--repo`、`--branch`，其中 `--fmagent-python` 要求 `--skip-install`，用于绑定已有解释器。跳过 fetch 时，install/bind 要求已有源码。脚本显示本次选定的路径，安装成功后保存 root 和其 `.venv/bin/python`；跳过安装时保存选定的已有解释器。使用 `--skip-bind` 可保持原绑定。失败时保留已完成步骤。原生安装的网络及用户工具/配置影响按 FM-Agent 文档处理。

`--init generic/xiangshan` 只导出任务模板，已有文件不覆盖，不解析路径或探测 FM-Agent 环境。模板不含 root/python，路径选项仅保留在管理子命令中。

### 可选自动规格准备

设置 `fmagent.enabled: true` 后，工作流在证据阶段前自动准备 FM-Agent 规格；默认关闭时保持原四阶段。配置项为 `mode`（`run` 或 `reuse`）、`resume`、`isolate` 和项目内相对路径 `submodule`。`run` 调用原生 `chip --only-spec`，需已有 FM-Agent 环境；`reuse` 使用输入项目已有的 `fm_agent/`，不启动生成，也不需要 FM-Agent 环境。`reuse` 不接受 `resume` 或 `isolate`。`--init` 仅导出模板，不检查或写入 FM-Agent 路径。

Generic 输入位于 `inputs/{DUT}/`，包含 RTL 和 `rtl2spec.json`；XiangShan 输入位于 `third_party/XiangShan/`，`submodule` 指向分析范围。CLI 会按 `enabled` 选择对应 workflow；直接使用 UCAgent 时，选择对应的 `*-design-document-fmagent` workflow，并在新任务中启用该配置。

启用后阶段顺序为准备、证据、草稿、源码复核和验收。准备结束时，项目中的 `fm_agent/` 与存在的 `.codegraph/` 永久迁至 `{OUT}-fmagent/`，不自动搬回。`{OUT}` 和 `{OUT}-fmagent` 必须为空或不存在，并位于输入项目及 Git 仓库之外。下一次 reuse 前，操作者手动将旧 `fm_agent/` 复制回输入项目，并使用新的空输出目录。

FM-Agent 的 spec/info 会登记为原四阶段的必读参考。证据阶段完成后，系统把所有 `*_spec.md` 按原层级和字节复制到 `{OUT}/specs/`；info 保留在完整运行副本中，作为可选参考。没有 spec 时仍创建空目录并继续，不检查正文质量或模块覆盖，也不修订规格内容。

输入、配置、权限、进程、迁移或复制失败会阻止后续阶段并保留已有数据，不自动回迁、删除或重试。Generic 的 `inputs/` 父目录保持只读；fresh 运行若需在该目录下创建 FM-Agent 原生归档，可能因权限失败。按运行日志处理输入布局后再启动；不自动放宽权限或切换 reuse。

## 后端配置

在启动 YAML 中修改 `backend.key_name` 并添加该后端所需的 UCAgent 配置。使用其他后端时，先配置并验证同等权限限制；后端权限验证方法见[开发与验证](development.md#开发与验证)。

## 插件工具

UCAgent 在工作流中调用 `RTL2SpecCommand`，并通过 `Check`、`Complete` 验收阶段：

| 香山 action | 通用 action | 用途 |
| --- | --- | --- |
| `preflight` | `generic_preflight` | 单独诊断输入、配置和所需环境；证据操作已包含预检，无需重复执行 |
| `evidence` | `generic_evidence` | 生成或捕获 RTL、端口和签名证据；通用输入同时记录预处理配置与源码映射 |
| `related_sources` | `generic_related_sources` | 登记确实参考的相关 Scala 模块或输入文件 |
| `ports` | `generic_ports` | 根据当前证据生成附录 A 辅助骨架 `evidence/ports.md`，补充逻辑分组和协议后用于写作 |
| `metadata` | `generic_metadata` | 按字段/证据条目更新事实，保留无关文字和各源文件自己的摘要 |
| `validate` | `generic_validate` | 草稿诊断：字段/表格完整性、精确端口、ID 与跨表追溯、源码位置、签核声明及 Mermaid 围栏 |
| `review` | `generic_review` | 为当前文档生成 `semantic_review.json` 问题；按 P-* 依赖指纹保留未变化行为的答案，只为变化行为创建新问题 |
| `lint` | `generic_lint` | 复核诊断：包含草稿检查，并验证每个行为的复核项、源码位置和当前摘要 |
| `finalize` | `generic_finalize` | 检查全部最终内容与生成限制，自动更新报告，生成绑定最终工件的 `validation.json` |

正常路径为 evidence → related_sources（需要时）→ ports → 编写草稿 → metadata → 源码复核/review → finalize；各阶段记录日志后 Complete。validate/lint 用于需要诊断时，正常收尾不要求连续重复 validate、lint 和 Check。Check/Complete 始终核验当前内容；final 阶段还要求当前有效的验收记录。

端口验收直接核对实际 RTL、ports.csv 和附录 A，不要求辅助骨架逐字保持原样。partial 生成在 finalize 时就必须保留 Open/Deferred 的 `OPEN-GENERATION-PARTIAL`，并在质量报告说明受限范围；不要求说明使用固定的英文关键词。检查依据与取舍见[Checker 设计](architecture.md#checker-设计)。

复核记录格式与完整例子见 [源码复核指南](../src/rtl2spec/Guide_Doc/source-review-guide.md)。记录证明引用和复核项完整，不证明行为已通过动态或形式化验证。finalize 后不再手工回填验收结果；若修改设计或证据，先重新 metadata/review，再 finalize。

每个 P-* 的七类复核证据都须与正文引用的 E-* 源码范围相交，`no_deterministic_fact` 也遵守此规则，并额外引用仍为 Open/Deferred 的 OPEN-* 解释缺口。赋值事实只对比支持范围内的赋值、条件与事件；端口和行为事实的检查边界见[插件原理与设计](architecture.md#源码复核与最终验收)。

质量报告使用[质量复核模板](../src/rtl2spec/Guide_Doc/document-quality-review-template.md)的唯一一级标题和六个有序二级区块，每块填写具体发现或限制，不能只留下表头、全空行或子标题。报告里的统计数字和自然语言结论仍需对照当前复核记录审阅。

调用时传入 `module` 和 `config`。需要把相关源码纳入证据时，先读取相关模块，再传入 `related_modules`：

```python
RTL2SpecCommand(action="evidence", module="Sbuffer", config="DefaultConfig")
RTL2SpecCommand(action="related_sources", module="Sbuffer", config="DefaultConfig", related_modules=["Helper"])
RTL2SpecCommand(action="generic_evidence", module="GenericBlock", config="Generic")
RTL2SpecCommand(action="generic_related_sources", module="GenericBlock", config="Generic", related_files=["helper.sv"])
```

将 `Helper` 替换为本次确实读取的 XiangShan Scala class 名；若它支撑文档结论，就在正文引用对应的 `E-REL-*` 并在附录 C 定义，若只用于上下文核对，则只进入质量报告，不需要在正文中伪造引用。

通用工作流的 `related_files` 必须是 `inputs/GenericBlock/` 下的相对 POSIX 路径；工具会拒绝绝对路径、路径穿越、重复路径和顶层 RTL。输入目录发生变化后，旧 evidence 会失效，必须选择空的输出目录并重新开始一轮生成。

单次工具调用默认上限为 3660 秒。只加载 `--plugin` 可复用工具和 Checker；选择 `--plugin-workflow` 才会启用文档工作流并复制 Guide_Doc。修改插件资源后必须重新启动工作流，重新加载工作流 YAML 并更新工作区中的 Guide_Doc。

## 常见问题

- **找不到插件或同名冲突**：确认 pip 与 ucagent 使用同一 Python 环境；源码调试使用 `--plugin /绝对路径/UCAgent/plugins/RTL2Spec`。
- **环境检查失败**：XiangShan 工作流按诊断补齐工具或子模块，确认模块及配置 class 名正确；通用工作流检查 `inputs/{DUT}/rtl2spec.json` 指定的文件顺序、include、宏和参数；未提供配置时需要唯一顶层源文件。完整输入例见[通用输入指南](../src/rtl2spec/Guide_Doc/generic-generation-guide.md)。选择 XiangShan 工作流时要求 Bash、Git、Curl、Make 的 `--version` 能正常执行，通用工作流不依赖这组 XiangShan 工具链。
- **工具不可见**：检查 `tools.selected_tools` 与 `tools.ignore_tools`，勿屏蔽工作流所需工具。
- **验收失败**：按 `Check` 指出的文件和位置修复；按诊断选择草稿修订、metadata、review 或 finalize。损坏的 manifest 或越界软链接修复为有效签名证据后，可以直接重新 Check，不需要靠重启清除失败状态。`stale review` 表示文档/源码已变化，须重新复核；`stale acceptance` 表示交付物已变化，须重新验收。输入配置变化后应选择空输出目录重新捕获证据。
- **相关模块证据缺失**：XiangShan 工作流先读取实际支撑结论的 Scala 模块，再执行 `related_sources`；通用工作流先读取 `inputs/{DUT}/` 下的源码，再执行 `generic_related_sources`。在正文引用生成的 `E-REL-*`，并把它加入附录 C。不要仅因为文件存在就把它列为参考文件。
- **修改插件资源后仍使用旧内容**：重新启动工作流并重新生成工作区的运行资源。
