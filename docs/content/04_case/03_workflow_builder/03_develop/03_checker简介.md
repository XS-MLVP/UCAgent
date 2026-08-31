# 母工作流 Checker 生成子系统二次开发

本篇说明如何修改母工作流的 Checker 规划、生成、模板、fixture 和注册系统，使后续生成的业务工作流拥有正确 Checker。读者是维护 `tools/workflow_checker_generator/`、Builder 中心 spec 和母阶段验收的开发者，不是被 Checker检查的子 Agent。

Checker 决定母阶段或生成业务阶段是否满足契约。二次开发时要区分两类：根 config 注册的母 Checker验证 `wfgen/` 和构建进度；`workflow_build.yaml` 规划的业务 Checker由生成器物化到 `workflow/`。两类都继承 UCAgent Checker 协议，但修改源和交付位置不同。

## 二次开发目标

典型任务包括新增通用 rule type、增强 AST/docstring 校验、改变自动 fixture、修复注册参数、增加路径规范化或完善 Checker direct runner。业务专属判定优先由中心 spec 内联 source 表达，只有多个业务共享且规则稳定时才进入公共模板。

## 母工作流修改入口

- `tools/workflow_checker_generator/core.py`：spec、源码、fixture、注册和报告。
- `tools/workflow_checker_generator/templates.py`：通用规则 renderer。
- `tools/workflow_builder/core.py`：从中心 workflow spec 直接物化业务 Checker。
- 根 `config.yaml` 和母 Checker模块：母阶段自身验收。
- `Guide_Doc/stage_check_guide.md` 与阶段 GuideDoc：失败说明和修复方向。
- `regression/run_checker_description_regression.py` 及 delivery contract：协议回归。

## 真实生成链路

Checker 的中心规划位于 `workflow_build.yaml` 的 workflow spec。构建阶段应直接从该设计生成 Checker 源码、fixture 和注册，避免等到后期再猜每个阶段需要什么检查。相关实现主要位于 `tools/workflow_checker_generator/`、`tools/workflow_builder/core.py` 和 `tools/workflow_evaluation_control/uc_checkers.py`。

```bash
rg -n "Checker|checker_spec|workflow_spec" workflow_builder workflow_checker_generator regression
```

## docstring 和构造参数

UCAgent 会读取 Checker 描述，因此 Checker 类必须提供非空、具体的 docstring。`"Check output"` 这类描述不能解释检查对象。docstring 应说明读取哪些文件或字段、核心通过条件和失败意义。

配置注册中的参数名、必选性和默认值必须与 Python 构造函数一致。多一个参数会在实例化时失败，漏掉必需参数也会令阶段无法运行。目录参数只有在 Checker 设计明确支持目录遍历时才合理；工作流阶段的 `reference_files` 仍必须是具体文件。

## 判定语义

Checker 应区分：

- 文件不存在或不可解析。
- 结构字段缺失或类型错误。
- 结构正确但业务语义不满足。
- 依赖条件尚未成立，例如未来章节或可选输出尚不存在。
- Checker 自己遇到异常。

可选输入不能在早期阶段被当成强制文件。版本或进度检查要基于当前阶段真实语义，例如“最新快照章节等于当前章节时版本必须一致”，不能用始终成立不了的全局等式制造误报。

## 关键业务代码分析要求

生成的 `docs/05开发者文档-checkers.md` 必须对每个 Checker 提供真实源码和分析：

1. 类定义、构造函数和 `check`/调用入口。
2. 输入路径、字段及规范化规则。
3. 主要条件分支和错误码对应关系。
4. 为什么这些条件能证明用户需求，而不是只证明格式存在。
5. 正向 fixture、单一错误负向 fixture 和边界 fixture。
6. config 中的注册片段及参数映射。
7. 修改阈值、字段或依赖后必须同步调整的阶段和测试。

片段必须来自最终生成的真实文件，标注相对路径和关键行附近的符号。分析应指出业务规则的来源；若需求没有规定，必须说明这是首阶段计划补充的设计决策。

## 防止误报和漏报

最小 fixture 只改变一个条件，使失败原因可定位。一个负向 fixture 同时破坏五个字段，会让开发者无法知道 Checker 是否验证了目标规则。Checker 不得依赖不稳定时间、随机顺序或绝对路径。路径比较应规范化后比较，不得因为 `.//workflow/x` 与 `workflow/x` 字符串不同误判。

严重程度不是 Checker 自己随意决定的装饰。会阻止 UCAgent 启动、导致无限重试、破坏正式文件或错误宣称完成的缺陷最危险；文档措辞、非关键提示和可选优化不应升级为阻断阶段的问题。

## 修改清单

- 同步更新中心 checker spec、生成模板、注册和阶段参数。
- 保证 docstring 解释真实检查内容。
- 增加实例化测试和参数注册一致性测试。
- 为每项业务规则提供正反证据。
- 验证 Checker 自身异常不会伪装成业务失败。
- 运行 Checker 生成回归和相关完整流程检查。

## Checker spec 的中心地位

Checker spec 是判定实现、fixture、测试与阶段注册的共同来源。`workflow_build.yaml` 中每个 Checker 应完整携带名称、描述、入口、规则或源码、fixture、tests 和 register。Builder 先把中心定义写成 `.workflow/checker_specs/<name>.yaml`，再调用 checker generator 物化，避免阶段 config、Python 文件和测试由不同步骤各写一套事实。

Checker 描述要说明“什么证据证明什么业务条件”。例如“检查报告”没有对象、字段和失败意义；“读取 validation_report.json 的 status、missing_assets 和 output_sha256，确认 DOCX 可解析且没有缺失必需素材”才足以指导 Agent和评估者。

## spec 结构校验代码分析

源码位置：`tools/workflow_checker_generator/core.py`，符号 `_validate_spec()`。

该函数先确认顶层 mapping、名称、详细描述和 entry，再验证 rule type、register、fixture 与 tests。路径必须经过 `_safe_resolve()`，测试参数必须是 mapping，`expected_pass` 必须是布尔值。重复或缺失字段应在生成源码之前失败，防止留下半套 Checker。

如果 spec 提供 `source`，验证器不能因为“用户已经写了代码”就跳过结构检查。source 和 entry 仍要一致，测试仍然必需，注册参数仍需验证。规则模板和内联源码只是产生实现的两种方式，不代表不同质量标准。

## AST 与 docstring 校验

源码位置：`tools/workflow_checker_generator/core.py`，符号 `_validate_inline_source()`。

```python
tree = ast.parse(source)
class_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == entry["class_name"]
)
if not any(base.id == "Checker" ... for base in class_node.bases):
    raise CheckerGenerationError(...)
method = next(node for node in class_node.body if node.name == entry["method"])
if method is None or not ast.get_docstring(method):
    raise CheckerGenerationError(...)
```

AST 校验比文本搜索可靠：注释中的类名不会被误认为实现，别名或属性基类可以显式处理，方法 docstring 能通过语法树取得。它仍不是运行测试，不能证明 import 依赖存在、构造参数匹配或检查逻辑正确，所以后面还需要 static checker 和 direct runner。

当前验证要求检查方法具有 docstring，是因为 UCAgent 和诊断工具需要说明。类级 `description` 与方法 docstring责任不同：description 面向阶段和用户解释业务检查，方法 docstring 面向维护者说明调用和返回。二者都不能为空。

## 自动 fixture 生成分析

源码位置：`tools/workflow_checker_generator/core.py`，符号 `_materialize_auto_tests()`。

```python
if rule_type == "json_required_keys":
    fixtures[valid_path] = json.dumps({key: 0 for key in keys})
    fixtures[invalid_path] = json.dumps({key: 0 for key in keys[:-1]})
    tests = [
        {"expected_pass": True, ...},
        {"expected_pass": False, ...},
    ]
```

自动测试为通用规则建立最小正反样例。required keys 的负向样例只删除最后一个键，因此失败原因单一；numeric range 的负向值只越过上界；file exists 创建一个文件并保证另一路径不存在；command exit code 使用允许命令产生 0 与非 0。

自动 fixture 适合证明模板基本行为，不能替代业务 fixture。一个“字段存在” Checker 可能还需要验证字段间语义，这时应提供显式 fixture 或内联 Checker。不要不断给通用模板增加业务特例，否则模板难以理解且所有工作流都承担额外复杂度。

## 模板代码分析：JSON 必需字段

源码位置：`tools/workflow_checker_generator/templates.py`，符号 `_render_json_required_keys()`。

```python
target = self._resolve()
if not target.is_file():
    return False, {"error": "CHECKER-DATA-001: JSON result file not found"}
data = json.loads(target.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    return False, {"error": "CHECKER-DATA-002: JSON top-level must be mapping"}
missing = [key for key in self.required_keys if key not in data]
```

这里把不存在、解析/类型和字段缺失分成不同错误码，使 Agent 能采取不同修复。`_resolve()` 把 path 限制在 workspace 内，防止 Checker 借阶段参数读取任意系统文件。返回值是 `(passed, evidence)`，evidence 中保留 path 和 missing keys，而不是只返回 False。

注意“键存在”不验证值类型或含义。若业务要求 `status == completed` 或哈希非空，必须选择更合适规则或写业务 Checker。把所有条件塞进 required keys 的描述会形成文档与实现不一致。

## 模板代码分析：数值范围与命令

numeric range 模板显式排除 bool，因为 Python 中 `bool` 是 `int` 子类。上下界为闭区间，修改为开区间会改变业务语义，必须同步 spec 和 fixture。字段不存在与非数字当前共用同一错误分支；若 Agent 修复需要区分，可以新增错误码和单一负向案例。

command exit code 模板只允许 `self.command[0]` 出现在 `allowed_commands`，使用参数数组调用 `subprocess.run()`，设置 cwd、capture、text 和 timeout。它不通过 shell 拼接，因此用户参数不会变成管道或重定向。stdout/stderr 被截断到尾部，避免 Checker 返回巨大上下文。

命令白名单需要精确到可执行程序，但仅验证程序名仍可能允许危险参数。适合 `python -m py_compile`、特定 `make check` 等可控命令；处理用户可控任意参数时应增加参数模式、工作目录和输出路径限制。

## 注册代码分析

源码位置：`tools/workflow_checker_generator/core.py`，符号 `_register_checker()`。

```python
expected = {
    "name": spec["name"],
    "clss": f"{module_path}.{spec['entry']['class_name']}",
    "args": args if isinstance(args, dict) else {},
}
existing = next(item for item in checker_list if item.get("name") == spec["name"])
```

UCAgent 配置字段使用 `clss`，不是通常拼写的 `class`。生成器负责从文件路径去掉 `.py`、把斜杠转为点，再拼接类名。手工注册很容易漏掉这一细节。已有同名项被更新而不是重复追加，保证阶段调用顺序稳定。

注册前查找目标 stage；stage 不存在必须失败，不能退回第一个阶段。`args` 需要与 Checker `__init__` 一致。评估流程应 import 类、检查签名并尝试实例化，才能发现 config 多传或少传参数。

## Checker 物化主链

源码位置：`tools/workflow_checker_generator/core.py`，符号 `generate_checkers_from_specs()`。

主链依次解析每份 spec、结构校验、生成自动测试、写显式 fixture、选择内联 source 或模板 renderer、写 Checker 源码，最后可选注册。每个动作更新 `CheckerGenerationReport`。任何一步失败都应指出当前 spec，避免批量生成时不知道哪项出错。

Builder 调用时通常设置 `update_config=False`，因为中心阶段契约之后由 config generator统一注入；独立维护工具则可以注册。开发者修改该开关语义时要检查是否产生重复注册或缺失注册。

## 二次开发案例：扩展业务 Checker 生成能力

DOCX 工作流的 `DocumentIntegrityChecker` 需要证明输出不是仅有 `.docx` 后缀的空壳。构造参数包括 workflow-relative 文档路径、必需章节清单和最少图片数。检查方法使用 `zipfile` 或 `python-docx` 解析文件，验证 ZIP 完整性、正文段落、标题、关系文件和图片引用，并返回每项证据。

正向 fixture 是最小合法 DOCX；负向 fixture 分开覆盖损坏 ZIP、缺章节、图片关系丢失和文档路径逃逸。spec 注册到生成文档后的阶段，reference 指向具体 DOCX 和结构化报告。开发者文档引用真实解析代码，说明为什么不能只检查文件存在和大小。

若后续增加“页眉必须包含版本”，应更新需求引用、Checker 构造参数或规则、fixture、阶段任务、开发文档和 eval_checkers 业务覆盖。不能只在描述中加一句而不改代码。

## 误报诊断方法

遇到阶段连续失败时，先用 Checker 注册参数在独立 direct runner 中复现。然后依次检查：输入是否在当前阶段已经生成；路径规范化后是否相同；可选文件是否被强制；fixture 是否代表当前 schema；Checker 自己是否捕获了 import/解析异常；失败证据是否对应实际分支。

曾出现 `.//workflow/x` 与 `workflow/x` 按字符串比较误判，这类问题应在路径生成和比较层规范化，而不是要求 Agent按某个奇怪字符串读取。也曾出现“最新快照版本必须总等于当前版本”在批内更新阶段误报，应把条件限定为相同章节或相同检查点语义。

## 扩展点、修改影响与回归矩阵

| 修改 | 同步范围 |
| --- | --- |
| 新 rule type | spec 校验、renderer、自动 fixture、文档和回归 |
| 修改构造参数 | template、register args、config、实例化测试 |
| 修改路径规则 | `_safe_resolve`、模板 `_resolve`、符号链接和越界 fixture |
| 修改错误码 | FAQ、阶段修复提示、评估证据和负向测试 |
| 修改 `clss` 注册 | UCAgent 加载、配置生成、静态 import 回归 |
| 修改业务语义 | 用户需求、中心 spec、正反 fixture、阶段和开发文档 |

Checker 回归必须同时证明该通过的通过、该失败的失败。只跑正向样例会让无条件 `return True` 的错误实现通过全部测试。

## 母构建 Checker 完整索引

以下类定义在 `tools/workflow_builder/uc_checkers.py`。大部分类继承 `WorkflowBuildConfigChecker`，共享 workspace 路径规范化、YAML/JSON 读取和证据结构，但每个类的业务证明对象不同。

| Checker 类 | 检查对象 | 主要失败意义 | 二次开发注意 |
| --- | --- | --- | --- |
| `WorkflowBuildConfigChecker` | `workflow_build.yaml` 的基本结构、路径与核心契约 | 中心设计不可解析或无法驱动后续生成 | 是共享基类，修改通用路径/读取行为会影响几乎全部母 Checker。 |
| `WorkflowInputExampleManifestChecker` | `input_example_manifest.yaml` 的用户样例清单、文件存在性和归类 | 输入契约对真实样例认知不完整 | 新增样例类型要保持未知/可选分类可表达，不要把特定业务扩展名硬编码。 |
| `WorkflowBuildOutputChecker` | Builder 初始产物、目录与报告 | Builder 返回成功但固定交付物缺失 | 新交付物需同步 BuildReport 和 delivery regression。 |
| `WorkflowMinimalInitChecker` | 烟雾工作流的最小可运行骨架 | 尚未到完整实现就无法进行生成闭环 | 最小不等于空壳，应只检查本阶段已承诺的文件。 |
| `WorkflowEnvironmentSetupChecker` | 生成的 Makefile、`ucagent_setup.sh`、`setup.py`、schema 和 requirements | 子工作流不可移植或配置无法生效 | 要区分 Python 依赖与非 Python 注释安装说明，测试 dry-run 与重复执行。 |
| `WorkflowMCPToolIntegrationChecker` | 工具源码、config 注册、import、参数和直接/MCP 调用 | 工具文件存在但 UCAgent 不可用 | 新返回结构或 adapter 必须同时改 direct 和 MCP 证据。 |
| `WorkflowGeneratedCheckerChecker` | 生成 Checker 源码、docstring、fixture、注册和正反运行 | Checker 无法加载、参数错或判定无效 | 必须防止无条件通过，同时不用未来产物误报当前阶段。 |
| `WorkflowGeneratedConfigChecker` | 生成 config/inc 的语法、必需字段与基本注册 | 运行配置不可加载 | 新 schema 字段需先定义兼容默认，再改生成器和此 Checker。 |
| `WorkflowRuntimeConfigAuditChecker` | 阶段 reference/output 具体文件、可达性、占位符、Tool/Checker/GuideDoc 闭包 | 配置能解析却会在运行时卡死或读不到文件 | 路径比较要规范化；reference/output 禁止目录；不得只为某个 `{INPUT}` 表象写特例。 |
| `WorkflowGeneratedGuideDocChecker` | 生成 GuideDoc 的语义章节、操作证据、注册与详细度 | Agent 虽能读文档却无法依步骤执行 | 标题多语言应通过稳定 section id 处理，不要硬编码中文标题。 |
| `WorkflowMigrationPackageChecker` | 迁移包文件清单、相对路径、哈希、可解压与迁移后检查 | 开发机成功但交付到新系统失败 | 必须在新临时根验证，不可因绝对路径偶然存在而通过。 |
| `WorkflowToolGenerationChecker` | tool spec、生成状态、基础源码/测试结构 | 生成闭环未建立 | 是工具类 Checker 基类，通用规则不应包含某业务文件名。 |
| `WorkflowGeneratedToolChecker` | 单个烟雾业务 Tool 的源码、spec、fixture 与运行结果 | 代表性 Tool 不可用，后续批量生成不可信 | 检查参数应由当前 spec 提供，不假设 `diag_checker*.py` 等偶然文件。 |
| `WorkflowBusinessToolGenerationChecker` | 全部规划业务 Tool 的数量、生成、注册、测试与需求覆盖 | 只有烟雾 Tool，业务能力交付不完整 | 允许后续新增 Tool，但每个必须回到 manifest/spec 和测试证据。 |
| `WorkflowGuideDocSpecChecker` | 文档 spec 的目标路径、类型、section id、详细度与注册计划 | 未经规划就批量生成文档 | 要区分 GuideDoc 和 human docs，字数规则不能靠代码块灌水绕过。 |
| `WorkflowRequirementCoverageChecker` | requirements manifest 中需求到 Tool、Checker、config、GuideDoc、docs 的可追踪映射 | 产物形式完整但偏离用户需求 | 同一类以多个 alias 在不同时间点使用，阈值应随阶段递进而非一开始要求最终产物。 |
| `WorkflowImplementationPlanChecker` | 初始实施计划的阶段、Tool、Checker、GuideDoc、产物和作用描述 | 母 Agent 未先建立可执行蓝图 | 类/方法 docstring 与计划正文详细度都要测；最小示例要标明不满足正文字数。 |
| `WorkflowLivingPlanChecker` | 每阶段标记、追加内容和前序保留 | 后续阶段与前序设计断联或覆盖历史 | 修改 marker 后同步 appender、FAQ、UI 解析和 living-plan regression。 |
| `WorkflowUserDocsChecker` | README、01–05 用户/开发文档、目录、字数、真实源码分析 | 生成工作流无法被人使用或继续开发 | 格式要求要保持内容自由度；源码片段必须来自真实生成文件。 |
| `WorkflowDependencyChecker` | `requirements.txt` 的 Python 依赖、非 Python 工具注释与安装方法 | 用户无法还原运行环境 | 不得伪造未验证版本；可选系统工具需说明降级行为。 |

## 评估与增量 Checker 完整索引

以下类定义在 `tools/workflow_evaluation_control/uc_checkers.py`。它们不判断某个业务文件“好不好”，而是判断评估/增量报告是否按契约收集证据、是否受批准约束以及是否真正完成部署回归。

| Checker 类 | 作用 | 二次开发重点 |
| --- | --- | --- |
| `EvaluationJsonReportChecker` | 验证指定 eval 报告 run 的 schema、status、checks、findings、metrics 与本轮身份 | 新增字段必须为旧 run 提供兼容默认，不能只查 JSON 可解析。 |
| `EvaluationGuideCoverageChecker` | 验证评估/增量 GuideDoc 是否覆盖必需规则、严重度和执行约束 | 新 check id 需同步 GuideDoc 和 coverage 清单，但不应要求每阶段读取全部长文。 |
| `StaticAuditCoverageChecker` | 确认静态审计覆盖本评估域所有必需规则 | 应对比 rule id 和实际 evidence，不能用一个“审计成功”布尔值代替。 |
| `IncrementalAuditCoverageChecker` | 确认增量阶段已做批准新鲜度、候选、边界、部署与回归审计 | 修改状态机后必须同步审计规则，防止正式文件已替换却等待再批准。 |
| `IncrementalContextReportChecker` | 验证当前 inc run 的认知清单、目标批准、索引与阅读预算 | “初步了解”不应被实现为全量文件阅读打卡，要检查导航性而非字节总量。 |
| `IncrementalApprovalChecker` | 验批准/建议的 source、run、fingerprint、decision 及 current 状态 | Agent 不得自批；来源 finding 改变后旧批准必须失效。 |
| `EvaluationStageGateChecker` | 检查评估阶段是否只执行允许操作、写入正确报告并满足完成门槛 | 更改 eval 职责拆分时同步 gate，避免 eval_tools 越界评估环境或启动子流程。 |
| `EvaluationEvidenceChecker` | 检查 finding/check 的证据是否指向具体文件、符号、命令或结果 | 没有证据的判断不能用于欺骗用户“已满足需求”；证据路径必须可追踪且不越界。 |
| `IncrementalApplicationChecker` | 验证 approved target 到 candidate mapping、部署记录、哈希、备份和未完成项映射 | 只生成候选计划不等于已修复；必须核对正式文件结果。 |
| `IncrementalRegressionChecker` | 在 application 证据上额外要求正式 `make check` 及相关目标成功 | 回归失败时不得因已部署而转 pending；应继续在原批准范围修复或回滚。 |

## 配置 alias 与实现类映射

配置中的 Checker `name` 是阶段语义 alias，`clss` 才是 Python 实现。同一类可在多个阶段使用不同 args 和 alias。开发者调整类签名时必须查找以下全部映射，不能只修第一个搜索结果。

| 实现类 | 当前主配置 alias |
| --- | --- |
| `WorkflowLivingPlanChecker` | `living_plan_update_check` |
| `WorkflowRequirementCoverageChecker` | `requirements_manifest_check`、`initial_build_requirement_coverage`、`initial_template_requirement_coverage`、`smoke_manifest_check`、`final_requirement_coverage` |
| `WorkflowImplementationPlanChecker` | `workflow_implementation_plan_check` |
| `WorkflowInputExampleManifestChecker` | `input_example_manifest_check` |
| `WorkflowBuildConfigChecker` | `workflow_build_config_check` |
| `WorkflowBuildOutputChecker` | `workflow_builder_output_check` |
| `WorkflowToolGenerationChecker` | `workflow_tool_generation_check` |
| `WorkflowGeneratedToolChecker` | `workflow_business_tool_spec_check`、`workflow_generated_tool_check`、`workflow_generated_tool_strengthened_check` |
| `WorkflowMinimalInitChecker` | `workflow_minimal_init_check` |
| `WorkflowEnvironmentSetupChecker` | `workflow_environment_setup_check` |
| `WorkflowMCPToolIntegrationChecker` | `workflow_mcp_tool_integration_check`、`full_mcp_tool_integration_check` |
| `WorkflowRuntimeConfigAuditChecker` | `runtime_config_reference_audit` |
| `WorkflowGuideDocSpecChecker` | `guidedoc_spec_check` |
| `WorkflowGeneratedGuideDocChecker` | `generated_guidedoc_check` |
| `WorkflowUserDocsChecker` | `generated_user_docs_check` |
| `WorkflowDependencyChecker` | `generated_dependency_check` |
| `WorkflowMigrationPackageChecker` | `generated_migration_package_check`、`final_migration_package_check` |

`inc.yaml` 中，`generated_workflow_context_complete` 映射 `IncrementalContextReportChecker`；`approved_changes_deployed` 映射 `IncrementalApplicationChecker`；`applied_changes_have_approval` 和 `all_current_approvals_deployed` 映射 `IncrementalApprovalChecker`；`incremental_report_complete` 映射 `EvaluationJsonReportChecker`；`incremental_guide_complete` 映射 `EvaluationGuideCoverageChecker`；`incremental_static_audit_covered` 映射 `IncrementalAuditCoverageChecker`；`incremental_make_check_passed` 映射 `IncrementalRegressionChecker`。

各 `eval_*.yaml` 的报告 alias `tools_report_complete`、`checkers_report_complete`、`flow_report_complete`、`env_report_complete`、`run_report_complete` 映射 `EvaluationJsonReportChecker`；指导 alias `tools_guide_complete`、`checkers_guide_complete`、`flow_guide_complete`、`env_guide_complete`、`run_guide_complete` 及 `evaluation_contract_complete` 映射 `EvaluationGuideCoverageChecker`；`deterministic_audit_covered` 映射 `StaticAuditCoverageChecker`。`EvaluationStageGateChecker` 与 `EvaluationEvidenceChecker` 属于可组合门禁能力；若在配置中新注册，必须补充 alias、args 实例化和阶段证据回归。

## 修改 Checker 的标准步骤

1. 先用一句可证明命题写清“它通过时究竟证明什么”，再确定这是母构建、评估增量还是生成的业务 Checker。
2. 列出本阶段已经存在的具体文件和字段，将未来输出设为后阶段检查或明确可选，禁止用目录代替 reference 文件。
3. 实现稳定 docstring、构造参数、路径规范化、分支错误码和有意义 evidence；不捕获所有异常后伪装成业务失败。
4. 从所有 YAML 搜索对应 `clss` 和 alias，验证 args 名称、类型、必选性和默认值与签名一致。
5. 添加最小正向 fixture、每次只破坏一个条件的负向 fixture、边界 fixture、import/实例化测试和配置集成测试。

## 继续阅读

Checker 告诉 Agent “什么算完成”，GuideDoc 则告诉 Agent “怎样可重复地做到”。请继续阅读[指导文档简介](04_指导文档简介.md)，了解阶段指导、FAQ、最小样例与 Checker 语义如何保持一致。
