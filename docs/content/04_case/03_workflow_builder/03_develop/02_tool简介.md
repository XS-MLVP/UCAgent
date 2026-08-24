# 母工作流 Tool 生成子系统二次开发

本篇说明如何二次开发母工作流的 Tool 生成子系统，即修改 `tools/workflow_tool_generator/`、其 UCTool 包装、母配置注册和相关回归，使未来生成的任意业务工作流获得新的工具模板、spec 字段、写入策略或注册能力。它不是教业务 Agent如何调用某个具体工具。

Tool 是母工作流向 UCAgent 暴露的确定性能力，也是母工作流生成给子工作流的交付物类型。开发者需要同时理解“生成器自身的 UCTool”和“生成器产出的业务 Tool”，但实际修改应落在前者的源码、spec 契约和模板上。

## 二次开发目标

适合在本子系统完成的任务包括：增加通用工具模板、扩展 tool spec schema、修改 preserve/replace 策略、增强路径安全、调整 config 注册、增加工具测试基线或修复生成状态。业务专有算法若只服务一个生成工作流，应由中心 spec 提供内联源码或业务模板，不应硬编码进所有工作流共享的母生成器。

## 母工作流修改入口

- `tools/workflow_tool_generator/core.py`：spec 校验、生成状态、写入和注册。
- `tools/workflow_tool_generator/templates.py`：内置工具与通用源码 renderer。
- `tools/workflow_tool_generator/uc_tools.py`：给母 Agent调用的参数模型和 UCTool。
- 根 `config.yaml`：哪个母阶段调用生成器、传哪些 spec。
- `Guide_Doc/stages/`：告诉母 Agent怎样准备 spec 和批量生成。
- `regression/`：工具描述、交付契约和稳定性验证。

后文中的 DOCX 工具案例应理解为“如何验证母生成器扩展是否能支持一种业务”，不是要求开发者把 DOCX 逻辑写入 WorkflowToolGenerator。

## 真实生成链路

工具生成入口位于 `tools/workflow_tool_generator/`。中心 `workflow_build.yaml` 中的 tool spec 先声明名称、目的、参数、输出、错误、调用阶段和测试，再由生成器写入业务工作流的 `tools/` 并更新注册。母构建器的核心协调逻辑位于 `tools/workflow_builder/core.py`；该文件也生成通用环境、README 和固定骨架。

开发者调整工具协议时，应同时搜索：

```bash
rg -n "tool_spec|GeneratedTools|tools\." workflow_builder workflow_tool_generator regression
```

不要只修改某次 `workspace_x/workspace/workflow/tools/` 的生成结果，那不会改善下一次构建。

## 接口结构

一个工具应具有稳定名称、清晰 docstring、可序列化参数和结构化返回值。推荐返回：

```python
{
    "ok": True,
    "data": {"output_path": "output/example/document.docx"},
    "errors": [],
    "warnings": [],
    "meta": {"tool": "BuildDocument", "version": 1},
}
```

失败时 `ok` 必须为 `False`，`errors` 应包含稳定错误码、可行动消息和相关字段或路径。不能捕获异常后仍返回成功，也不能只打印终端文本让 Agent 猜测结果。

## 关键业务代码分析要求

生成的 `docs/04开发者文档-tools.md` 必须逐工具引用真实源码片段，而不是伪代码。每个工具至少分析：

1. 工具入口函数或类如何接收参数并进行类型、路径和业务前置校验。
2. 核心算法或第三方库调用如何把输入转为业务产物。
3. 写文件时如何限制到允许目录、使用临时文件和处理部分失败。
4. 异常如何映射为结构化错误，哪些错误允许重试。
5. 注册代码如何让 UCAgent 找到工具，配置参数与 Python 签名是否一致。
6. 正常、边界和失败测试分别覆盖哪条分支。

源码引用应注明相对路径和符号名。片段后必须解释关键变量和控制流，不能只粘贴整文件。若工具由模板生成，也要标出模板来源和生成后的真实文件差异。

## 写入和命令边界

Tool 只能在业务工作流允许的目录写入。构建过程的临时数据进入工作区 `tmp/`，不应在 `wfgen/` 散落调试脚本。执行 batch 或外部程序时必须使用白名单、参数数组、超时和返回码，不允许把用户输入拼接成任意 shell。

路径校验应在解析和规范化后完成，防止 `..`、符号链接和绝对路径逃逸。输出目录存在不等于产物有效，工具还应校验大小、格式或可重新解析性。

## 并行和性能

独立工具可以由 Agent 并行生成或测试，但共享注册文件和中心 spec 的写入必须串行协调。生成阶段不应规定“每次回复只能调用一个工具”；真正约束应是避免并发修改同一文件，并在批量生成后一次运行综合检查。

## 修改清单

- 更新中心 tool spec 和 requirements manifest。
- 更新生成器模板或通用实现，而非仅修单个产物。
- 更新注册、GuideDoc 和开发者文档生成规则。
- 增加正向、负向、边界和路径逃逸测试。
- 运行工具生成器回归及总 `make regression`。

## Tool spec 到源码的完整数据流

业务工具不是直接根据自然语言写入 `tools/`。首阶段先在 requirements manifest 和实现计划中明确工具责任，设计阶段再把稳定字段写入中心 tool spec。生成器读取 spec、验证路径和接口、渲染源码、更新注册并保存生成状态。最终业务 config 通过动态适配器向 UCAgent 暴露工具。

一个可维护 spec 至少需要名称、描述、入口文件、类名、输入 schema、输出 schema、错误、调用阶段、实现模板或内联源码、测试和已有文件策略。描述必须回答工具在业务流程中解决什么问题，不能只复述类名。输入字段需要类型、必选性和含义；输出字段要能让后续 Agent 与 Checker稳定读取。

## 路径安全代码分析

源码位置：`tools/workflow_tool_generator/core.py`，符号 `_safe_resolve()`。

```python
def _safe_resolve(root: Path, rel_path: str) -> Path:
    candidate = Path(rel_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ToolGenerationError(...)
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        raise ToolGenerationError(...)
    return target
```

第一层拒绝绝对路径和显式 `..`，第二层在 `resolve()` 后检查真实父目录，因此符号链接或路径规范化也不能逃出工作流根。所有 spec、生成文件、配置和测试路径都应走这一入口。新增“复制资源”之类的工具时，不能在自己的分支重新用字符串前缀判断，因为 `/root/workflow-old` 可能错误匹配 `/root/workflow`。

路径安全验证只证明生成器写入位置安全，不等于生成出来的业务工具运行时安全。运行时工具仍需对用户传入路径相对于业务 workspace 重新规范化，并限制允许读写根。

## 生成状态与覆盖策略

源码位置：`tools/workflow_tool_generator/core.py`，符号 `_load_generation_state()`、`_write_generated_file()` 和 `_normalize_existing_policy()`。

生成器保存文件内容哈希和测试基线，用于区分三种情况：文件仍是上一轮生成内容、文件已经被用户或增量流程修改、文件第一次出现。已有文件策略不能只用一个布尔 `overwrite` 表达，因为自动覆盖手工维护代码可能造成数据丢失，而一律 skip 又会让 spec 更新永远不生效。

```python
policy = _normalize_existing_policy(existing_policy, overwrite)
if target.exists() and policy == "preserve":
    report.skipped_files.append(relative)
    return
...
state["files"][relative] = {"sha256": _sha256_text(content), ...}
```

开发者增加策略时必须定义：目标不存在、目标与上次哈希一致、目标已漂移、强制覆盖分别如何处理；report 如何记录；失败是否留下新的 state。状态文件必须在实际写入成功后更新，并采用安全持久化，不能先记录新哈希再写文件。

## spec 校验代码分析

源码位置：`tools/workflow_tool_generator/core.py`，符号 `_validate_tool_spec()`。

该函数检查 spec 顶层 mapping、工具名、描述、入口文件和类、输入输出、实现类型与测试。验证顺序应先结构后语义：如果 `entry` 不是 mapping，不应继续读取 `entry.file`。工具描述、参数说明和错误契约属于可维护接口，而不是可选装饰。

spec 中声明内联源码时还应进行 Python AST 或编译检查，并确认入口类真实存在。模板工具则由 `render_tool_from_spec()` 生成，但同样要在写入后通过 tool static checker 和 direct runner，防止模板字符串语法正确但运行协议错误。

## 通用模板渲染代码分析

源码位置：`tools/workflow_tool_generator/templates.py`，符号 `_schema_from_inputs()`、`_output_schema_from_spec()` 和 `_render_generic_tool()`。

```python
def render_tool_from_spec(spec):
    template = spec.get("template")
    if template in BUILTIN_RENDERERS:
        return BUILTIN_RENDERERS[template](spec)
    return _render_generic_tool(spec)
```

输入 spec 先被转换为 Pydantic/JSON schema 所需的字段，再写入生成类。输出 schema 不是运行结果本身，而是 Agent 和测试理解 `data` 结构的契约。通用工具模板必须保留 `ok/data/errors/warnings/meta` 的结构，否则上层 Agent 无法统一判断失败。

生成类中业务主体如果只是占位 `NotImplemented` 或无条件成功，静态语法可能通过，但工具不可用。因此中心计划应尽量使用明确模板或提供真实实现源码，并由 direct runner 用正反案例调用。新增模板时应把模板名加入允许集合、实现 renderer、增加 fixture、记录 requirements，并更新开发者文档。

## 注册流程代码分析

源码位置：`tools/workflow_tool_generator/core.py`，符号 `_tool_record_from_spec()` 与 `_register_tool_records()`。

注册记录把 spec 入口转成运行时可加载的模块类路径，并保留工具名、描述、参数 schema 和来源 spec。生成器应批量收集 records 后一次更新 config，避免多个并行工具生成同时覆盖注册文件。

注册必须满足三方一致：Python 类名和入口文件存在；config 中记录的类路径可 import；工具参数模型与 spec 输入字段一致。仅在 `tools/` 创建文件但没有注册，UCAgent 不会调用；只注册不存在的文件则会在启动或首次使用时失败。

批量注册还要处理同名工具。重复名称通常应更新同一记录或明确失败，不能静默生成两个顺序依赖的记录。修改注册结构时要同时检查 `tools/mcp_adapters.py`、tool spec checker、静态 runner 和评估工具注册审查。

## UCTool 包装层代码分析

源码位置：`tools/workflow_tool_generator/uc_tools.py`，符号 `WorkflowToolGeneratorArgs` 与 `WorkflowToolGenerator`。

参数模型负责把 Agent 传入的 JSON 转为稳定 Python 类型。真正的 `run()` 应只做参数归一化、调用 core、捕获 `ToolGenerationError` 并返回结构化结果，不在包装层复制业务生成逻辑。这样 CLI、回归和 UCTool 可以共享同一个 core。

包装层 docstring 会成为 UCAgent 看到的工具说明，必须写出生成位置、spec 要求、覆盖策略和返回内容。参数默认值要谨慎：把 `overwrite=True` 作为默认值可能让 Agent 在没有意识到的情况下覆盖用户维护代码。

## 结构化错误设计

推荐失败结果：

```python
{
    "ok": False,
    "data": {},
    "errors": [{
        "code": "TOOL-GEN-SPEC-004",
        "message": "entry.file must be workflow-relative",
        "location": ".workflow/tool_specs/BuildDoc.yaml:entry.file",
    }],
    "warnings": [],
    "meta": {"generated": [], "skipped": []},
}
```

错误码用于 FAQ、Checker 和 Agent 修复提示的稳定关联；message 说明事实与修复方向；location 指向 spec 字段。不要把完整敏感输入或巨大 stderr 放入错误。外部命令输出应截断并保存在 `tmp/` 日志，返回结构只提供摘要和路径。

## 二次开发案例：让母生成器支持新的业务 Tool

假设要让母工作流稳定生成 DOCX 业务所需的 `DocumentStructurePlanner`。二次开发者首先判断现有 generic renderer 是否足够；如果足够，只需增强母阶段的 spec 规划和校验，不新增公共模板。如果多个业务都会复用结构规划算法，才在 `templates.py` 增加模板 renderer，并在 core 允许该模板名。tool spec 定义 `content_path`、`requirements_path` 和 `assets_index_path`，输出 `plan_path`、章节数量和 warnings。

生成后要验证：缺正文返回稳定错误；未知标题层级形成 warning；资源引用没有路径逃逸；两次相同输入得到稳定计划；注册类可 import；正向 fixture 包含标题、列表和图片，负向 fixture 只缺一个必需文件。GuideDoc 说明调用顺序和失败恢复，`docs/04开发者文档-tools.md` 引用真实规划算法源码。

如果后续改为支持表格，不只修改 Python 实现。还要更新需求能力、spec 输出 schema、测试样例、GuideDoc、用户输入说明和开发者代码分析。若输出字段变化，使用它的 Checker 和后续 DOCX renderer 也要同步。

## 并行生成的正确边界

不同工具源码和独立 fixture 可以并行准备，因为它们写不同文件。中心 tool spec、生成状态、config 注册和综合报告属于共享资源，必须由单一协调步骤提交。推荐流程是并行生成候选内容，串行调用生成器写入并注册，最后一次运行 tool static/direct/MCP 综合检查。

禁止“每次只能调用一个工具”的全局规则，因为它会把无依赖工作强制串行。也不能无约束并行调用多个会重写同一 config 的生成器。并行策略应根据写集合是否相交，而不是根据工具数量决定。

## 扩展点、修改影响与回归矩阵

| 修改 | 必须检查 |
| --- | --- |
| 新增 spec 字段 | schema、校验、模板、控制台视图、旧 spec 默认值 |
| 修改路径规则 | safe resolve、符号链接、绝对路径、Windows/Posix 表达、写入边界回归 |
| 修改返回结构 | UCTool、Agent 指导、direct runner、评估工具可用性检查 |
| 修改覆盖策略 | generation state、哈希、用户漂移、重复运行和增量兼容 |
| 新增模板 | renderer、requirements、正反 fixture、注册和开发者文档 |
| 修改注册 | import 测试、MCP adapter、config generator 和 eval_tools |

目标测试通过后还要运行总回归。真实业务验证时应让子 Agent 调用生成工具完成阶段，开发者不能手工放置最终工具后把 Checker 通过当作生成器成功。

## 母工作流 UCTool 完整清单

下表以当前源码中真正继承 `UCTool` 的类为准。“注册上下文”表示哪类配置会将它暴露给 Agent，不表示每个配置都使用全部工具。修改类名、参数模型或返回结构后，必须搜索 `config.yaml`、`inc.yaml`、`eval_*.yaml` 中的 `ex_tools` 并同步 GuideDoc 和回归。

| Tool | 源码 | 注册上下文 | 核心责任与副作用 |
| --- | --- | --- | --- |
| `WorkflowBuilder` | `tools/workflow_builder/uc_tools.py` | 主 `config.yaml` | 读取中心构建设计，物化子工作流骨架、固定配套文件和报告；是构建 core 的受控入口。 |
| `WorkflowCommandRunner` | `tools/workflow_builder/uc_tools.py` | 主 `config.yaml` | 在构建工作区内运行白名单命令，限制 cwd、超时、参数和输出；不应演变为任意 shell。 |
| `WorkflowArtifactInspector` | `tools/workflow_builder/uc_tools.py` | 主 `config.yaml` | 结构化查询文件、目录树、摘要和局部内容，用于证据收集；只读且要限制大小。 |
| `WorkflowEnvironmentPreflight` | `tools/workflow_builder/uc_tools.py` | 主 `config.yaml` | 检查 Python、Make、UCAgent、路径、依赖和可选外部命令，输出可区分“缺失”与“可选跳过”的环境报告。 |
| `WorkflowPlanAppender` | `tools/workflow_builder/uc_tools.py` | 主 `config.yaml` | 以阶段标记追加实施计划，保留前序阶段内容；负责 living plan 的不覆盖约束。 |
| `WorkflowToolGenerator` | `tools/workflow_tool_generator/uc_tools.py` | 主流程和 `inc.yaml` | 验证 tool spec，生成业务 Tool 源码、fixture、测试和注册，维护生成状态与覆盖策略。 |
| `WorkflowCheckerGenerator` | `tools/workflow_checker_generator/uc_tools.py` | `inc.yaml` | 从 checker spec 生成或更新 Checker、fixture 和注册；主构建中部分 Checker 也可由 Builder 直接物化。 |
| `WorkflowConfigGenerator` | `tools/workflow_config_generator/uc_tools.py` | 主流程和 `inc.yaml` | 根据 workflow spec 生成或更新 `config.yaml` 与 `inc.yaml`，注入 Tool、Checker、GuideDoc 和阶段契约。 |
| `WorkflowGuideDocGenerator` | `tools/workflow_guidedoc_generator/uc_tools.py` | 主流程和 `inc.yaml` | 验证文档 spec，生成 GuideDoc 和用户/开发者文档，只对 Agent 需要的指导执行注册。 |
| `ChildWorkflowSupervisor` | `tools/workflow_child_supervisor/uc_tools.py` | 主流程有限验证和 `eval_run.yaml` | 通过独立 tmux session 启动、查询、截取或停止子工作流，返回 run id 和可观察状态；不应在静态 eval_tools/checkers/flow/env 中注册。 |
| `IncrementalContextInventory` | `tools/workflow_evaluation_control/uc_tools.py` | `inc.yaml` | 在受控阅读预算下盘点子工作流、报告、批准和资源，产生本轮认知索引而非复制全文。 |
| `StructuredJsonStore` | `tools/workflow_evaluation_control/uc_tools.py` | 全部评估和 `inc.yaml` | 对允许的 `eval/*.json` 与 `res/*.json` 执行带 schema、revision 和审计的 CRUD；是结构化文件的唯一常规写入通道。 |
| `EvaluationCommandRunner` | `tools/workflow_evaluation_control/uc_tools.py` | 全部静态评估和 `inc.yaml` | 运行评估/回归白名单命令，保存返回码和截断证据；不允许静态评估通过它启动子工作流。 |
| `StaticEvaluationAudit` | `tools/workflow_evaluation_control/uc_tools.py` | 全部评估和 `inc.yaml` | 对 Tool、Checker、config、GuideDoc、环境和写入边界执行确定性审计，输出规则 id 和证据。 |
| `EvaluationControl` | `tools/workflow_evaluation_control/uc_tools.py` | 控制 API/兼容入口 | 封装聚合、批准、建议和增量运行控制；当前并非所有 YAML 的 `ex_tools` 都注册它，修改时不能假定 Agent 必然可见。 |
| `IncrementalCandidateStager` | `tools/workflow_evaluation_control/uc_tools.py` | `inc.yaml` | 把正式 `workflow/` 中获批准目标安全复制到当前 run/batch/attempt 候选目录，并记录源哈希。 |
| `IncrementalChangeDeployer` | `tools/workflow_evaluation_control/uc_tools.py` | `inc.yaml` | 验证候选映射与当前批准，备份旧版，原子替换正式文件，失败时回滚并写 `applied_changes.json`。 |
| `ReadTextFileMCPTool` | `tools/workflow_builder/core.py` | 生成的子工作流 MCP | 读取业务工作区内文本，带路径边界和分段参数；它是生成源模板，不是母 Agent 构建阶段的普通工具。 |
| `WriteTextFileMCPTool` | `tools/workflow_builder/core.py` | 生成的子工作流 MCP | 在业务允许根内写文本，需维持输出和临时文件边界。 |
| `RunCommandMCPTool` | `tools/workflow_builder/core.py` | 生成的子工作流 MCP | 为子工作流提供有限命令执行；允许集合应由业务设计与环境配置决定。 |

## 构建控制工具的二次开发

`WorkflowBuilder` 的参数层只应接收 workspace-relative 设计路径、覆盖策略和可选阶段范围，真正物化必须委托 `tools/workflow_builder/core.py`。增加一类固定交付物时，需同时改 BuildReport、初始骨架、requirements manifest 覆盖、delivery contract 和产物二次开发文档。不能在 `run()` 内临时写一份未被 core 记录的文件。

`WorkflowCommandRunner` 与 `EvaluationCommandRunner` 的名称相近，权限却不同。前者服务于构建工作区的生成和检查，后者服务于评估证据与增量回归。增加允许命令时必须在对应执行器的白名单增加精确参数规则，不能因为一处需要 `make check` 就允许任意 `make <target>`。回归要包含非白名单、超时、越界 cwd、非零返回码和输出过长。

`WorkflowArtifactInspector` 用于减少 Agent 为建立认识而全文扫描。新增查询类型时，应返回文件数、大小、哈希、匹配项和截断标记，而不是无上限展开内容。`WorkflowEnvironmentPreflight` 的检查项应同时声明 required/optional、确认命令和安装建议；不能把可选 Verilator 缺失与 Python 无法启动设为同级阻断。

`WorkflowPlanAppender` 必须使用稳定的 begin/end marker 查找当前阶段区块，并拒绝覆盖其他阶段。扩展计划字段时，要检查旧计划无新字段的兼容读取、同阶段重试的幂等性和 `WorkflowLivingPlanChecker` 的对应规则。

## 四类生成器 Tool 的二次开发

`WorkflowToolGenerator`、`WorkflowCheckerGenerator`、`WorkflowConfigGenerator` 和 `WorkflowGuideDocGenerator` 使用相同的包装原则：Pydantic Args 保证 Agent JSON 的基本类型，core 完成路径规范化和业务验证，UCTool 将预期异常转换为结构化失败。如果新字段只加到 Args 却没有传入 core，Agent 会误以为参数已生效；如果只改 core，Agent 又无法构造该参数。

四类生成器的交付不同：Tool generator 维护工具源码与生成哈希；Checker generator 还需物化正反 fixture；Config generator 要做跨文件引用闭包、占位符和阶段连接审计；GuideDoc generator 需区分 Agent GuideDoc 与人类文档。不应抽象一个只会“读 spec 然后写文件”的通用生成器，因为这会丢失各自的语义校验。

## 评估与增量 Tool 的二次开发

`IncrementalContextInventory` 的产物应是“可导航的认知清单”：配置阶段、工具/检查器索引、目标 finding、直接依赖和按需阅读顺序。它不应将 `docs/`、全部源码和历史报告嵌入一份大报告。扩展盘点项时要设置每文件和总字节预算，并保留 `truncated` 证据，避免评估/增量 Agent 连续压缩后重复读取。

`StructuredJsonStore` 的公开操作包括 list/get/create/update/upsert/delete，必须由 relative document id 选择固定 schema。增加一份结构化文件需要同步 `json_store.py` 允许清单、初始文档、collection/id 规则、CLI、review API、UI 和回归。不能让 Agent 通过 WriteTextFile 绕过 revision 直接覆盖 JSON。

`StaticEvaluationAudit` 返回的每条规则应有稳定 id、scope、passed、severity、evidence 和 remediation。新规则必须属于正确评估域，并提供最小正反 fixture。`EvaluationControl` 若作为新 Agent 入口注册，需要明确它与 CLI/review server 重叠的权限，避免同一批准操作出现三种不一致实现。

`IncrementalCandidateStager` 与 `IncrementalChangeDeployer` 必须分开。Stager 只复制正式文件到本轮候选并记哈希，Deployer 才能验证批准、备份和原子替换。把两者合并会让候选尚未检查就污染正式文件。修改 mapping 格式时要同步 incremental report、applied changes、历史索引、控制台和 rollback 测试。

`ChildWorkflowSupervisor` 的 `start/status/capture/list/stop` 操作由 `tools/workflow_child_supervisor/core.py` 实现，只允许 `run_tui`、`run`、`run_inc` 和 `run_inc_tui` 等明确 Make target。增加 target 时必须先确定它不会绕过评估成本门禁，并为 session 命名、run metadata、启动失败、超时、停止和残留 tmux 清理增加回归。修改 capture 时要继续限制行数，不把整个长期 TUI 日志返回 Agent 上下文。

## 生成产物内置 MCP Tool

`ReadTextFileMCPTool`、`WriteTextFileMCPTool` 和 `RunCommandMCPTool` 定义在 `tools/workflow_builder/core.py` 的生成源中。开发者修改它们时，需要同时阅读生成后的 `tools/mcp_adapters.py`、config 注册、安全边界和 `make test_tools`。它们是子工作流最低级能力，不能因为业务 Tool 不够完整就放开任意命令或越界写入。

这三个类出现在 Builder 源码中，但运行在生成的子工作流中。因此修改后不仅要跑母代码编译，还要生成一个全新业务工作流，从生成目录 import 类并执行越界负例。只在 Builder 源码中 AST 成功不能证明模板字符串生成后可运行。

## 新增或修改 UCTool 的标准步骤

1. 先在上表中确定工具属于母构建、生成器、评估增量还是子产物，明确其可读根、可写根和调用者。
2. 在对应 `uc_tools.py` 增加或修改 Args 模型和具体 Tool，保持 docstring、默认值、core 参数和结构化返回一致。
3. 在 core 实现路径校验、业务逻辑和原子写入，不把大段逻辑放在 UCTool `run()` 里。
4. 只在真正需要它的 YAML `ex_tools` 注册，然后更新该阶段 GuideDoc 中的参数来源、输出、失败恢复和 Checker 证据。
5. 增加 Args 校验、直接调用、越界路径、重复执行、部分失败和配置注册回归，再运行相关组件回归与总回归。

## 继续阅读

工具的输出如何被阶段判定，请继续阅读 [Checker 简介](03_checker简介.md)。若要修改生成出来的子工作流工具，还需结合[工作流产物二次开发指南](07_工作流产物二次开发指南.md)判断修改应回流母生成器还是保留为单个业务扩展。
