# GuideDoc 生成规范

## 概述

`WorkflowGuideDocGenerator` 将结构化 `.workflow/guidedoc_specs/*.yaml` 转换为
Agent 使用的 `Guide_Doc/*.md` 或用户使用的 `docs/*.md`。只有 GuideDoc 自动注册到
`config.yaml`，用户文档不得进入运行时 `guide_docs`。

## GuideDoc Spec 格式

每份 spec 位于 `.workflow/guidedoc_specs/<name>.yaml`，必须包含三个根级字段：

```yaml
title: "文档标题"
document_type: guide_doc
operation_contract: true
output: "Guide_Doc/output_name.md"
sections:
  - id: purpose
    heading: "章节标题"
    content: "章节内容"
  - id: inputs
    heading: "另一个章节"
    content: "内容..."
```

关键约束：

- `document_type` 为 `guide_doc` 或 `user_doc`，省略时兼容为 `guide_doc`
- `operation_contract` 只控制 GuideDoc 是否强制标准运行命令
- `sections` 是由稳定语义 `id`、展示用 `heading` 和 `content` 组成的列表（禁止 mapping）
- 操作类 GuideDoc 使用固定英文语义 ID，`heading` 必须采用适合用户阅读的中文标题
- `guide_doc` 输出到 `Guide_Doc/`，`user_doc` 输出到 `docs/`

## GuideDoc 覆盖契约

`requirements_manifest.yaml` 中的 `required_guidedocs` 不能只是路径列表。每项应使用 mapping，声明该文档覆盖的阶段或范围：

```yaml
required_guidedocs:
  - path: Guide_Doc/overview.md
    scope: all
    purpose: "总览、输入输出和快速运行入口"
  - path: Guide_Doc/analyze_content.md
    stage: analyze_content
    purpose: "解释内容分析阶段的输入、输出、检查和失败恢复"
  - path: Guide_Doc/render_outputs.md
    stages: [plan_output, render_output]
    purpose: "解释输出规划和渲染阶段"
```

约束：

- `path` 必须指向 `Guide_Doc/*.md`
- 使用 `stage` 覆盖单个步骤，使用 `stages` 覆盖多个紧密相关步骤，使用 `scope: all` 表示总览文档
- 复杂业务步骤应有独立 GuideDoc，禁止只生成 `overview.md` 和 `operation.md`
- Spec 的 `output` 必须与 manifest 中的 `path` 一致

## GuideDoc 强制 7 章节

每份操作类 GuideDoc 必须包含以下章节（非空）：

| 章节 | 说明 |
|------|------|
| `purpose` | 工作流解决的问题，推荐标题“目的” |
| `inputs` | 输入位置和必需文件，推荐标题“输入” |
| `outputs` | 输出位置和产物，推荐标题“输出” |
| `usage` | 可直接执行的命令和 TARGET 选择方式，推荐标题“使用方法” |
| `execution` | 运行和验证命令，推荐标题“执行步骤” |
| `checks` | 成功判定标准，推荐标题“检查” |
| `failure_recovery` | 日志位置和修复流程，推荐标题“失败恢复” |

## 操作契约标记

只有 `operation_contract: true` 的 GuideDoc，其 `Usage` 章节必须显式包含以下关键词：

- `TARGET` — 目标选择变量
- `input/<TARGET>/` — 输入目录路径
- `input/example` — 示例输入
- `output/` — 输出目录
- `make check_example` — 示例检查命令
- `make run` — 运行命令

`Inputs` 章节必须包含 `input/<TARGET>/` 和 `input/example`。

`Outputs` 章节必须包含 `output/`。

## 完整 Spec 示例

```yaml
title: "文档处理工作流操作指南"
output: "Guide_Doc/operation.md"
sections:
  - id: purpose
    heading: "目的"
    content: |
      本工作流用于读取输入文档、分析内容并生成处理报告。
  - id: inputs
    heading: "输入"
    content: |
      将待处理文档放在 `input/<TARGET>/document.txt`。
      参考 `input/example/` 下的示例输入了解预期格式。
  - id: outputs
    heading: "输出"
    content: |
      所有生成结果写入 `output/`：
      - `output/analysis.json` — 分析结果
      - `output/report.md` — 处理报告
  - id: usage
    heading: "使用方法"
    content: |
      通过 `TARGET` 变量选择处理目标。
      输入位于 `input/<TARGET>/`，示例见 `input/example/`。
      结果写入 `output/`。

      ```bash
      make check_example
      make check_input TARGET=my_doc
      make run TARGET=my_doc
      ```
  - id: execution
    heading: "执行步骤"
    content: |
      运行前先执行 `make check`，确认所有基础检查通过。
      然后执行 `make check_input TARGET=<name>` 验证输入完整性。
      最后执行 `make run TARGET=<name>` 启动工作流。
  - id: checks
    heading: "检查"
    content: |
      确认 `make check` 全部通过。
      确认 `output/analysis.json` 和 `output/report.md` 生成且非空。
  - id: failure_recovery
    heading: "失败恢复"
    content: |
      查看 `.workflow/logs/` 下的日志定位失败原因。
      修复输入或配置后重新运行 `make check` 和 `make run`。
```

## 配置注册

生成的 GuideDoc 自动添加到 `config.yaml` 的 `guide_docs` 列表；`user_doc` 不注册：

```yaml
guide_docs:
  - Guide_Doc/overview.md
  - Guide_Doc/operation.md   # ← 自动添加
```

注册是幂等的，不会重复添加已存在的路径。

## 批量生成与上下文预算

文档阶段必须将 spec 编写和 Markdown 生成分成两个明确阶段。先按每批 3-4 个组件读取注册信息、真实源码和 fixture，立即把完整章节写入对应的开发者文档 spec；下一批只读取 spec 中的标题和完成状态，禁止因为上下文压缩而重新读取已经完成组件的源码。两个开发者文档 spec 的全部组件完成后，才调用一次 `WorkflowGuideDocGenerator`，并将全部受影响的 `spec_paths` 一次传入。正常流程不得按组件或按单份文档调用生成器，也不得在每个 spec 写入后运行 `make check_docs`。

生成器完成后只运行一次 `make check_docs` 并读取结构化结果。若检查失败，只针对报告中的组件修正 spec，再调用一次生成器并重新检查；不得直接编辑生成 Markdown，也不得为修复一个组件重新读取全部工具和 Checker 源码。建议在 spec 中保留准确的组件标题、实现路径、入口和源码围栏作为持久化完成账本，使后续上下文压缩不会导致重复扫描。

## 用户文档长度与逐组件统计

所有 `docs/*.md` 的 spec 都应在生成前写出足够详细的正文。固定用户文档的硬性要求是每份至少
200 个有效正文字符。`docs/04开发者文档-tools.md` 和
`docs/05开发者文档-checkers.md` 还有逐组件要求：必须分别为
`requirements_manifest.required_tools` 与实际启用工具的并集，以及
`requirements_manifest.required_checkers` 与 `.workflow/workflow_spec.yaml.checkers` 实际注册项的并集中每个名称建立独立的
二级至六级 Markdown 标题，而且标题必须包含准确的 manifest 名称。

逐组件检查器只截取“当前组件标题之后、下一个二级至六级标题之前”的内容进行统计。文档总览、
其他组件的长篇内容和标题本身都不会补足当前组件的长度；代码围栏、空白和标点也不能作为有效
说明。每个组件至少 300 个有效正文字符，硬性下限为 300 个有效正文字符。为避免 Markdown 标记和代码片段被过滤后刚好
低于下限，编写 spec 时应以每个组件至少 500 个有效中文正文字符为目标。

开发者文档必须先阅读已经生成的 `tools/`、`checkers/`、注册配置、测试脚本和 fixture，再进行
关键代码分析。每个工具条目必须明确写出实现文件、入口类或函数、关键代码或核心逻辑、调用路径、输入
参数、返回值或落盘产物、异常处理、可扩展位置以及测试方法。每个 Checker 条目应说明检查目标、
`do_check` 等入口、读取的数据、核心判定分支、PASS/FAIL 证据、边界条件、注册阶段、fixture 和
回归方法。应引用实际存在的类名、函数名和配置字段，说明代码为何这样工作；不得复制同一段泛化
文字、重复句子或无关公共说明来凑足字数。

“引用实际代码”是可验证契约，不是建议。编写每个组件前，必须从最终
`config.tools.GeneratedTools` 或 `.workflow/workflow_spec.yaml.checkers` 读取其真实注册项，然后
读取注册项指向的实现源码。组件章节必须原样写出实现相对路径、`class_name` 和 `method`，并提供一个
标注为 `python` 或 `py` 的 Markdown 围栏代码块。优先逐字复制实现文件同一位置连续 2-6 行非注释
有效源码，去除空白后不少于 40 字符；Checker 会把整个代码块规范化后作为一个不间断子串与真实
源文件匹配。围栏两端都是真源码并不代表可以通过：只要中间跳过了一个方法、装饰器、注释或语句，
整个围栏就不是连续片段。需要展示多个位置时必须拆成多个独立围栏，每个围栏都必须自身连续。伪代码、
带省略号的片段、改变语句后的近似写法、跨段拼接、spec 中的计划代码、fixture 或测试代码都不能通过。

最小可通过证据示例应保持短而稳定：

```python
def run(self, value: str) -> dict:
    normalized = value.strip()
    return {"ok": bool(normalized), "value": normalized}
```

如果真实源码在 `normalized = ...` 与 `return ...` 之间还有日志、注释或条件分支，上例就不能省略它们；
应完整复制中间行，或另选真正连续的 2-6 行。不要把“类定义 + 很后面的 run 方法”放进同一个围栏。

围栏代码块后必须分别给出三类具体分析：第一类是“源码分析、代码分析或逐行分析”，说明参数如何
进入关键分支、状态如何变化以及返回或证据如何形成；第二类是“业务逻辑、业务规则或业务含义”，
说明该代码为何满足当前工作流需求，而不是只翻译 Python 语句；第三类是“修改影响、影响范围或联动
修改”，指出调整条件、字段或返回结构后必须同步修改的 spec、adapter、配置、Checker、fixture 和
回归命令。YAML 文档 spec 应使用 `content: |` 等 literal block 保留 Markdown 围栏与缩进。

这些最终内容应在 `generate_all_documentation_and_dependencies` 阶段补入
`.workflow/guidedoc_specs/*.yaml` 对应 section 的 `content`，再调用
`WorkflowGuideDocGenerator` 生成文档。如果最终文档 Checker 报告某个组件过短，应回到该组件的
spec，补充缺失的实现分析并重新生成，而不是手工修改生成后的 Markdown。

前一阶段 `design_all_document_specs` 只负责冻结文档集合、组件覆盖和源码映射。该设计阶段要求每个
实际注册组件具有独立标题、至少 100 个有效正文字符的设计摘要，并原样记录实现路径、`class_name`
和 `method`；不要求逐字源码围栏、下列全部固定标签或最终 300 字正文。这样可以尽早发现漏项和错误
映射，又不会把源码逐项精读和最终写作重复执行两次。最终生成阶段必须重新读取实际源码并完成本节
规定的全部内容，设计阶段通过不能替代最终验收。

### 固定组件标签

每个工具与 Checker 的组件章节必须逐字包含下列语义组中的至少一个词。推荐直接使用冒号前的固定
标签，避免近义改写无法被机器契约识别：

```text
实现文件：
入口类：或 入口函数：
关键代码：或 核心逻辑：
调用路径：
输入参数：或 输入字段：
返回值：或 证据产物：
主要分支：
异常处理：
扩展点：或 调整方式：
测试：或 fixture：或 回归：
源码分析：
业务逻辑：
修改影响：
```

这些标签必须位于当前组件标题与下一个二级至六级标题之间。仅在文档开头列出一次公共模板不能让
任何组件通过。`WorkflowGuideDocSpecChecker` 在设计阶段只检查覆盖、设计摘要长度和准确源码映射；
`WorkflowUserDocsChecker` 在文档生成后执行本节所述的最终逐组件检查。不得因为设计检查已经通过
而省略真实源码、固定标签、关键业务代码分析或最终正文长度。

## 生成来源与陈旧检测

生成器在标题后写入两条不可手工维护的注释：

```markdown
<!-- GENERATED-FROM: .workflow/guidedoc_specs/example.yaml -->
<!-- SPEC-SHA256: <当前 spec 文件内容的 SHA-256> -->
```

Checker 会重新计算 spec 摘要并与生成文档比较。只要 spec 在生成后发生任何修改，旧 Markdown 就会
报告 `stale_generated_documents`。正确处理顺序是修改 spec、重新调用
`WorkflowGuideDocGenerator`、读取新输出确认来源和摘要、运行 `make check_docs`，最后调用 Check。
禁止手工更新摘要，也禁止只修改生成后的 Markdown；这两种操作都会破坏 spec 作为唯一来源的约定。

## 验证

生成后确认：

```bash
make check_docs    # 检查文档存在且章节完整
make check         # 确认注册正确
```

Checker 会验证：
- 文档文件存在且非空
- 所有必需章节存在
- 操作契约标记完整
- 每份用户文档具有至少 200 个有效正文字符
- 每个工具和 Checker 都有准确命名的独立标题及至少 300 个有效正文字符
- 每个组件都引用实际注册路径、类和方法，并包含与真实源码逐字匹配的连续代码片段
- 每个真实代码片段后都有源码、业务含义和修改影响分析
