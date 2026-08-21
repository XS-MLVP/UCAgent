# Stage 00: extract_requirements_and_plan

## 阶段目标

提取完整需求清单、输入示例契约和工作流实现计划。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{DESC_FILE}`

## 详细执行步骤

1. 第1步（必须首先执行）：只调用 ReadTextFile 读取 {DESC_FILE}。{DESC_FILE} 是唯一需求入口，禁止读取、引用或复制 wfgen/guide.md。如果尚未成功读取 {DESC_FILE}，禁止读取其他参考文档、禁止 SearchText、禁止 RunTestCases、禁止 Check。
2. 第1.1步：确认已经读取 {DESC_FILE} 后，调用当前 MCP 实际提供的 PathList(path='{TEST_INPUT_DIR}', depth=-1) 和 GetFileInfo 建立示例输入的完整路径、类型与大小清单；禁止调用不存在的 ListFiles。prepare_input 已保证 {TEST_INPUT_DIR}/ 存在；如果 PathList 报告不存在，必须报告外层输入准备错误并停止本阶段，禁止误判为“用户未提供示例”或回退 self_contained。只读取运行契约要求的文本文件、示例入口和其直接引用；知识库、大型文本、素材说明和代码按相关性每批最多两个文件读取并立即写入摘要，不能为了清单完整性而全文读取所有文件。{TEST_INPUT_DIR} 是只读用户输入，禁止创建、修改或补写其中任何内容。
3. 第1.2步：{DESC_FILE} 是唯一需求来源；本文件只是只读流程指导，不能作为业务需求或覆盖证据。另有动态只读输入目录 {TEST_INPUT_DIR}/。禁止读取 wfgen/guide.md、workflow_builder/uc_checkers.py、Guide_Doc/stage_check_guide.md、workflow_build_schema.yaml 或 workflow_build_yaml_guide.md；构建配置的 schema 和模板规则由下一阶段负责，避免需求规划与实现细节互相污染。
4. 第2步：创建 {WFGEN_DIR}/requirements_manifest.yaml，完整列出 required_stages、required_tools、required_checkers、required_guidedocs、required_user_docs、required_templates、required_configs、required_make_targets、required_deliverables、required_python_dependencies、required_system_dependencies 和 minimum_counts；不得只提取 smoke 子集。required_tools 先列出当前需求明确需要的业务工具，后续若发现合理的新工具需求，允许同步更新 manifest、实现计划、spec、配置注册、测试和开发者文档，不得只留下游离源码。required_user_docs 固定至少包含 docs/README.md、docs/01快速启动.md、docs/02输入输出.md、docs/03步骤及检查.md、docs/04开发者文档-tools.md 和 docs/05开发者文档-checkers.md；禁止生成已取消的 quickstart.md 或 QUICKSTART.md。required_configs 固定包含 config.yaml 和 config/inc.yaml；只有需求确实需要独立评估流程时才加入 eval.yaml，禁止加入 config/default.yaml 或 config/empty.yaml。required_make_targets 固定包含 help、configure、configure-check、check、check_config、check_inc_config、check_example、test_tools、test_checkers、test_mcp、plan、run、run_inc、clean 和 package。
5. 第3步：manifest 的 source_requirement、requirement_sections、section_coverage、全部 required_*、minimum_counts 和 milestones 必须直接位于 YAML 根级，禁止放入 metadata 或其他包装字段。
6. 第4步：requirement_sections 必须是非空列表，每项使用字符串或包含 name 的对象；section_coverage 必须是根级映射，并为 requirement_sections 中每个同名章节提供非空证据列表。交付类 required_* 必须存在且为列表，每项使用字符串或包含 name/path 的对象。required_stages 每项必须是包含非空 name、label、config 的 mapping；config 是该阶段真实注册位置，必须逐字匹配 required_configs 中某个 path。标准流程写 config.yaml，独立评估流程写 config/eval.yaml，增量流程写 config/inc.yaml；即使标准阶段可以被最终 Checker 默认分配到 config.yaml，也禁止省略 config 依赖隐式默认值。required_user_docs、required_configs 和 required_deliverables 每项必须是包含 path 的 mapping，禁止使用说明文字、数量摘要或笼统名称冒充文件路径；required_templates 只列最终用户可复用模板的交付路径，不是 files.*[].template 的 Builder 模板标识符，需求没有用户模板时必须为空列表；required_python_dependencies 和 required_system_dependencies 必须存在且为列表，没有额外系统依赖时后者允许为空。required_deliverables 至少包含 README.md、setup.py、config/environment.schema.yaml、requirements.txt、ucagent_setup.sh、Makefile、install.py、.install/README.md、.install/manifest.json、上述六份 docs、config.yaml 和 config/inc.yaml。minimum_counts 不得自行降低固定契约：user_docs 至少 6、configs 至少 2、make_targets 至少 14、deliverables 至少 17；其他计数必须忠实反映需求。
7. 第5步：source_requirement 必须严格写成 {DESC_FILE}，禁止写 wfgen/guide.md 或其他需求路径；逐个需求章节列出其对应的阶段、工具、checker、GuideDoc、模板或交付物，任何章节都不得无覆盖证据。required_make_targets 还必须包含 check_config 和 check_inc_config，并在 minimum_counts.make_targets 中按实际清单计数。
8. 第5.1步：required_guidedocs 每项必须是 mapping，至少包含 path，并用 stage、stages 或 scope 声明它覆盖的步骤。总览文档可写 scope=all；复杂工作流中每个非豁免业务阶段必须至少有一份 stage-specific GuideDoc，禁止只用 overview.md/operation.md 覆盖全部阶段。stage 必须是 required_stages 中某项的 精确 name；stages 必须是这些 name 组成的 YAML 列表，禁止填写中文显示名、逗号拼接字符串或阶段说明。 一份业务 GuideDoc 可以通过 stages 同时覆盖多个相关阶段，不要求每阶段单独创建一份文档。禁止把 WFB 自身的 Guide_Doc/tool_generation.md 或 Guide_Doc/checker_generation.md 作为子工作流默认 GuideDoc； 只有需求明确要求面向最终使用者的工具扩展或 checker 扩展说明时，才允许生成对应业务文档。 无论业务类型如何，都必须包含 Guide_Doc/environment_setup.md，并以 scope=environment 说明它用于跨系统配置， 但该文档不能替代任何业务阶段的 stage-specific GuideDoc。
9. 第6步：单独提取输入语义与派生责任。需求中描述为原始内容、原始数据、素材、可用资源或参考资料的输入，只能作为运行时原料；不得把页数、结构、设计参数、分析结论、资源选择或其他应由工作流产生的派生信息反向加入用户输入格式。
10. 第6.1步：把每个必需用户输入原样写入 runtime_contract.required_input。文件使用 path/type=file，可附 example_content；目录使用 path/type=directory。禁止固定添加 data/__init__.py、DUT、RTL 或其他与当前需求无关的输入。
11. 第6.2步：创建 {WFGEN_DIR}/input_example_manifest.yaml，专门描述 bundled example 的来源和复制规则。若 {TEST_INPUT_DIR}/ 存在，source_dir 必须是 {TEST_INPUT_DIR}，target_dir 必须是 input/example，copy_mode 必须是 copy_tree； required_input 必须与 runtime_contract.required_input 在语义和类型上对齐，但路径必须相对于 source_dir： runtime_contract 中的 input/<TARGET>/requirements.md 和 input/<TARGET>/rtl 分别写成 requirements.md 和 rtl，禁止原样复制 input/<TARGET>/ 前缀，也禁止重复 source_dir 前缀。 如果 runtime_contract.required_input 中的任何文件 内部引用了其他文件路径（例如 JSON 中的 path 字段、Markdown 中的图片链接），必须在 resource_paths 中声明这些 路径的映射关系。若 declared 路径是运行时格式（例如 input/<TARGET>/x.png），而 test_input 下实际文件位于其他 相对路径（例如 source/x.png），resource_paths 每项使用 mapping，字段为 `declared_path`（运行时路径）和 `source_path`（相对于 source_dir 的内部路径，例如 rtl/counter.v，禁止重复写 input/test_input/rtl/counter.v 或 source_dir 自身前缀）。注意：不要假设输入文件一定叫 resource.json；文件存在性和名称以 runtime_contract.required_input 为准。若不存在 test_input，才允许声明 copy_mode=self_contained，并说明每个示例文件的生成内容。
12. 第7步：manifest 增加 milestones：smoke_ready=false、feature_complete=false、release_ready=false；最终阶段会逐项更新。
13. 第7.1步：创建 {WFGEN_DIR}/workflow_implementation_plan.md，必须包含工作流概述、输入输出契约、阶段设计、工具设计、Checker设计、GuideDoc设计、用户文档设计、环境配置设计、运行模式与依赖。计划不是复述用户需求，而要把用户描述扩展成可直接实施的工程设计：明确数据流、阶段依赖、文件协议、工具调用链、Checker 判定链、失败传播和测试策略，并标出由需求推导出的技术决策。每个 required_stage 必须使用包含其精确英文 name 的三级标题建立独立段落，正文至少包含 200 个有效中英文或数字字符，并逐字出现“目的、输入、输出、失败”四个标记；段内必须引用至少一个 requirements_manifest 已声明的精确工具名和 Checker 名。每个 required_tool 以及固定基础设施 `run_command_tool` 都使用含精确工具名的三级标题，正文至少 300 个有效字符，必须覆盖作用、使用阶段、输入、输出、失败、实现文件或入口类、调用链、核心逻辑或算法、测试与扩展点。每个 Checker 使用含精确 Checker 名的三级标题，正文至少 300 个有效字符，必须覆盖使用阶段、检查对象、结构化检查内容、通过条件、失败条件、实现文件和入口类或 do_check、关键分支、异常与失败传播、正反 fixture、回归测试和扩展点。
14. 第7.2步：实现计划的逐组件解析非常严格。解析器从包含精确组件名称的三级标题之后开始取正文，并在遇到下一个二至六级标题时立即结束。因此阶段、工具或 Checker 的正文内部禁止使用 `##`、`###`、`####`、`#####` 或 `######` 子标题，内部结构必须使用 `**关键分支**：...` 这类加粗行内标记或普通段落。Checker 标记必须逐字命中以下别名之一：“使用阶段/绑定阶段”“检查对象”“检查内容/验证内容/结构化字段/证据字段”“通过条件”“失败条件”“实现文件/入口类/do_check”“关键分支/判定流程/检查流程”“异常/错误处理/失败传播”“测试/fixture/回归”“扩展点/调整方式/可配置”。例如“关键判定分支”虽然语义接近，但不包含连续的“关键分支”，不能作为必需标记。禁止只把用户原话拆成段落，禁止用通用模板替代具体字段、函数、证据和判断。有效字符只统计中英文和数字，Markdown 标记、标点、空白和路径分隔符不提供可靠余量；正文应超过硬下限至少 50 个有效字符。
15. 第7.3步：环境配置设计必须说明 setup.py、environment.schema.yaml、Makefile/ucagent_setup.sh 受控区块、本机配置隔离和移植后的重新配置步骤，并分析 schema 默认值、路径展开、依赖探测、代理开关、非交互更新、敏感值处理和失败回滚是否合理。计划必须与 requirements_manifest 逐项一致，后续设计变化时只能通过新的阶段记录追加说明。
16. 第8步：三份 output_files 全部写完后，先用 PathList(path='{WFGEN_DIR}', depth=1) 确认 requirements_manifest.yaml、input_example_manifest.yaml 和 workflow_implementation_plan.md 均存在，再用 YAML parser 确认两个 YAML 可解析，并逐项核对实现计划覆盖 manifest 中声明的阶段、工具、Checker、GuideDoc 和用户文档。对实现计划逐个组件进行字符数与精确标记自审，确保正文内没有会提前截断当前组件的二至六级子标题。在三份文件齐全且预检查通过之前禁止调用 Check，避免把尚未生成产物计为实现失败。不要在本阶段创建 workflow_build.yaml，也不要提前实现 Checker 源码。
17. 第8.1步：只有实现计划架构正文完全定稿后，才允许调用 `WorkflowPlanAppender` 追加 Stage 00 记录。Appender 的“前序内容 SHA256”覆盖记录开始之前的每一个字节；追加成功后不得再编辑、替换、格式化或补写其前面的正文，也不得手动修改摘要。如果首次 Check 仍报告架构正文错误，只允许完整删除尚未通过的当前末尾 Stage 00 记录，修正架构正文后重新调用 Appender；不得删除或修改任何已经通过阶段的历史记录。不得声称“重写正文不会使 SHA 失效”。
18. 第9步：使用 SetCurrentStageJournal 记录需求数量、章节覆盖、输入语义、示例来源和计划路径，然后 Complete。

## 关键文件的最小可通过版本

`requirements_manifest.yaml` 至少需要根级需求来源、章节覆盖、全部 required_*、固定最低数量、运行时输入契约和三个里程碑；路径型交付必须使用 mapping：

```yaml
source_requirement: input/guide.md
requirement_sections: ["1. 目标"]
section_coverage:
  "1. 目标": ["stage:analyze", "checker:ResultChecker"]
required_stages: [{name: analyze, label: 分析, config: config.yaml}]
required_tools: [{name: AnalyzeTool}]
required_checkers: [{name: ResultChecker}]
required_guidedocs: [{path: Guide_Doc/analyze.md, stage: analyze}]
required_user_docs:
  - {path: docs/README.md}
  - {path: docs/01快速启动.md}
  - {path: docs/02输入输出.md}
  - {path: docs/03步骤及检查.md}
  - {path: docs/04开发者文档-tools.md}
  - {path: docs/05开发者文档-checkers.md}
required_templates: []
required_configs:
  - {path: config.yaml}
  - {path: config/inc.yaml}
minimum_counts: {user_docs: 6, configs: 2, make_targets: 15, deliverables: 17}
milestones: {smoke_ready: false, feature_complete: false, release_ready: false}
```

存在标准、评估和增量三种运行配置时，阶段必须显式绑定到真实配置文件。下面是常见的多配置片段；`config/eval.yaml` 只有在需求确实要求独立评估流程时才加入 `required_configs`：

```yaml
required_stages:
  - {name: create_content, label: 生成内容, config: config.yaml}
  - {name: evaluate_content, label: 评估内容, config: config/eval.yaml}
  - {name: update_content, label: 增量修改, config: config/inc.yaml}
required_configs:
  - {path: config.yaml}
  - {path: config/eval.yaml}
  - {path: config/inc.yaml}
```

`input_example_manifest.yaml` 的路径必须相对于 source_dir：

```yaml
source_dir: input/test_input
target_dir: input/example
copy_mode: copy_tree
required_input:
  - {path: requirements.md, type: file}
  - {path: rtl, type: directory}
resource_paths:
  - {declared_path: input/example/rtl/dut.sv, source_path: rtl/dut.sv}
```

`workflow_implementation_plan.md` 必须先给出完整架构基线，再通过 `WorkflowPlanAppender` 添加 Stage 00 记录。下面是 manifest 只包含 `analyze`、`AnalyzeTool` 和 `ResultChecker` 时的最小可通过写法。真实任务必须为 manifest 中的每一个阶段、工具和 Checker 复制并定制对应组件段落；不能只保留本例中的三个组件。示例正文已展示硬性标记，但实际生成时仍应重新统计有效字符，并让阶段超过 250、工具和 Checker 超过 350 个有效字符，以免路径、Markdown 和标点被过滤后低于 200/300 的硬下限。

```markdown
# 工作流实现计划

## 工作流概述

本工作流读取用户提供的原始需求文件，调用正式工具形成结构化分析结果，再由独立 Checker 根据真实文件和字段给出通过或失败证据。工作流不把派生分析结果反向要求为用户输入，不使用自然语言“已完成”代替文件证据，并为失败重试、增量修改和最终交付保留稳定契约。

## 输入输出契约

用户只提供 `input/<TARGET>/requirements.md`。工作流派生的分析文件写入 `{OUT}/{DUT}/analysis.json`，其中包含来源路径、来源摘要、结构化结论、警告和错误数组。用户输入保持只读，任何工具不得回写输入目录；失败阶段保留错误码和证据路径，后续阶段只能读取前序已经确认存在的具体文件。

## 阶段设计

### analyze

**目的**：把原始需求转换为可验证的结构化分析，而不是复述需求或假设用户已经提供分析结论。**输入**：读取 `input/<TARGET>/requirements.md`，先确认它是普通非空文件，再把路径和输出位置传给 `AnalyzeTool`。**执行与工具绑定**：调用 `AnalyzeTool` 解析章节、约束和验收条件，统一返回状态、数据、警告、错误与元信息；禁止临时脚本绕过正式工具。**输出**：生成 `{OUT}/{DUT}/analysis.json`，记录来源摘要、章节映射、结论字段和诊断信息。**Checker 绑定**：调用 `ResultChecker` 读取真实 JSON，检查来源、字段、状态与结论是否一致。**失败**：输入缺失、路径逃逸、解析异常、输出未落盘、字段缺失或 Checker 失败都阻止阶段完成；重试时保留原始输入并覆盖同一目标下的派生结果，不能伪造 passed。

## 工具设计

### AnalyzeTool

**作用**：完成需求文件读取、结构解析、字段归一化和分析结果落盘，是 `analyze` 阶段唯一负责业务转换的正式工具。**使用阶段**：绑定 `analyze`，由阶段传入输入文件与目标输出文件，其他阶段只消费其结构化产物。**输入**：参数包含 `source_path`、`output_path` 和可选解析选项；工具必须验证路径位于允许根目录、来源为普通非空文件、输出位于当前目标目录。**输出**：返回 `ok/data/errors/warnings/meta`，并写入包含来源 SHA256、章节、约束、结论和版本信息的 JSON。**失败**：路径非法、编码错误、内容为空、结构无法解析或写入失败时返回稳定错误码且 `ok=false`。**实现文件或入口类**：规划为 `tools/analyze_tool.py` 中 `AnalyzeTool.run`。**调用链**：adapter 校验参数后调用 `run`，`run` 依次执行安全路径解析、内容读取、章节解析、业务归纳、schema 校验和原子写入。**核心逻辑**：从真实文本计算章节与约束，不返回固定模板；成功只有在文件写入并重新读取校验后成立。**测试**：正向 fixture 覆盖完整需求，边界 fixture 覆盖最小非空需求，失败 fixture 覆盖缺失文件、目录路径、非法编码和越界输出，并运行 direct 与 MCP 测试。**扩展点**：新增解析器时同步修改 spec、adapter、注册、fixture、开发者文档和回归命令，保持返回协议兼容。

### run_command_tool

**作用**：在工作区内受限运行审核过的批处理脚本和固定命令，为测试、静态检查和发布验证提供基础设施，不能代替 `AnalyzeTool` 的业务逻辑。**使用阶段**：可用于工具测试、Checker 回归和发布检查，业务阶段只有在指导明确要求外部程序时才能调用。**输入**：接收命令、工作区内相对 `cwd` 和超时；命令必须属于允许列表，脚本必须位于根级 `tmp/`，路径解析后不得逃逸工作区。**输出**：统一返回退出码、标准输出、标准错误、耗时和实际工作目录，不把非零退出码包装成成功。**失败**：拒绝绝对路径、父目录、shell 拼接、内联解释器、未批准命令和超时执行。**实现文件或入口类**：固定为 `tools/run_command_tool.py` 中 `RunCommandTool.run`。**调用链**：先规范化工作目录，再解析 argv、验证命令与脚本后缀，最后以 `shell=False` 启动子进程并捕获证据。**核心逻辑**：安全决策基于解析后的程序和路径，不使用字符串前缀冒充白名单验证。**测试**：正向覆盖 `pwd` 与 `tmp/` 脚本，失败覆盖 `python -c`、路径逃逸、shell 运算符、未知 make 目标和超时。**扩展点**：扩大白名单时必须同步安全审查、spec、adapter、负向 fixture、文档和完整回归，不能只增加字符串。

## Checker设计

### ResultChecker

**使用阶段**：绑定 `analyze` 并作为阶段完成前的强制门禁。**检查对象**：`{OUT}/{DUT}/analysis.json` 及其声明的原始来源文件，只检查真实文件，不接受聊天结论或临时日志代替。**检查内容**：验证目标是非空普通文件、JSON 可解析、schema 版本受支持、`source_path/source_sha256/sections/conclusions/status/errors` 等结构化字段齐全，来源摘要与当前输入重新计算结果一致，成功状态与错误数组不矛盾。**通过条件**：全部必需字段类型正确，至少形成一个有来源依据的结论，来源摘要匹配，`status=passed` 且错误数组为空。**失败条件**：文件缺失、路径逃逸、JSON 非法、字段为空、摘要不一致、结论无依据或状态自相矛盾时返回失败，并列出字段位置和实际值。**实现文件和入口类**：规划为 `checkers/result_checker.py` 中 `ResultChecker.do_check`。**关键分支**：先处理文件不存在和非普通文件，再处理解析异常与 schema 错误，然后比较来源摘要，最后检查业务结论和状态；每个分支都返回确定的结构化证据。**异常与失败传播**：捕获文件、编码和 JSON 异常后返回 `False`，不得吞掉异常、默认通过或把 blocked 当 passed，阶段收到失败后停止 Complete。**正反 fixture 与测试**：正向 fixture 使用真实输入及匹配摘要，反向 fixture 分别覆盖缺失文件、非法 JSON、缺字段、错误摘要和伪 passed；通过直接 runner 和 `make test_checkers` 证明正例通过、反例失败。**扩展点**：新增字段规则时同步更新中心 workflow_spec、checker spec、构造参数、正反 fixture、阶段绑定、docs/05 和回归测试，保持旧报告的兼容策略明确。

## GuideDoc设计

生成 `Guide_Doc/analyze.md`，说明输入契约、AnalyzeTool 的执行顺序、ResultChecker 的检查字段、通过证据和失败恢复；另生成环境配置文档，说明跨系统依赖探测与 setup.py 更新方法。

## 用户文档设计

生成六份固定用户文档。快速启动说明示例输入与运行命令，输入输出文档区分用户原料和工作流派生文件，步骤文档解释 analyze 与 ResultChecker，开发者文档分别分析真实工具和 Checker 源码。

## 环境配置设计

setup.py 支持交互和非交互更新，environment.schema.yaml 声明可迁移配置，Makefile 与 ucagent_setup.sh 只包含唯一受控区块。本机值进入 `.workflow/local/environment.yaml`，敏感值不写入仓库，迁移后重新探测 Python、UCAgent 和代理配置，失败时保留旧配置并报告差异。

## 运行模式与依赖

根级 `config.yaml` 执行主流程，`config/inc.yaml` 只处理批准的增量变化。Python 依赖只列可由 pip 安装的第三方包，系统依赖以注释给出安装方法；Makefile 提供检查、测试、运行、清理和打包目标，所有临时文件只进入根级 `tmp/`。
```

完成上述架构正文后，再调用：

```text
WorkflowPlanAppender(
  plan_path='{WFGEN_DIR}/workflow_implementation_plan.md',
  stage_name='extract_requirements_and_plan',
  stage_record='<包含阶段目标、决策与变更、产物与验证证据、问题与处理、后续约束五个三级标题的充分正文>'
)
```

不要从示例复制 `前序内容SHA256` 或手工编写 `WFB-STAGE-PLAN` 标记；摘要和标记只能由 `WorkflowPlanAppender` 根据最终正文生成。

## 常见示例

一次正常执行会先读取唯一需求入口，再读取本指导和真实示例输入，创建三份 Stage 0 产物并完成 YAML、路径及内容预检，然后调用 `WorkflowPlanAppender` 为新建的 `wfgen/workflow_implementation_plan.md` 追加本阶段决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `requirements_manifest_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `workflow_implementation_plan_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `input_example_manifest_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 最终覆盖检查把评估或增量阶段报告为 `config.yaml:stage_name` 缺失，但阶段实际存在于 `config/eval.yaml` 或 `config/inc.yaml` | `requirements_manifest.required_stages` 只写了 name/label，遗漏 config；Checker 无法知道阶段归属并按旧兼容逻辑默认查询 config.yaml | 不要复制阶段到 config.yaml。回到 Stage 0 清单，为每个阶段补充具体 config，并确认该路径逐字存在于 required_configs；重新运行 manifest Check，必须在进入构建阶段前消除此类错误 |
| 实现计划连续多轮报告 `stage_detail_errors`、`tool_detail_errors` 或 `checker_detail_errors` | 初始规划没有按逐段解析契约一次写全，常见遗漏是阶段不足 200 字、工具或 Checker 不足 300 字、标题缺精确英文名、组件正文缺精确标记 | 按 manifest 建立阶段、工具、Checker 三张清单；仿照最小可通过示例逐项使用三级标题和加粗行内标记，正文预留至少 50 个有效字符余量，再调用 Check |
| Checker 明明写了详细内容，仍报告缺少关键分支、异常、测试或扩展点 | 在组件正文中使用了 `#### 关键分支` 等二至六级子标题，解析器在该标题前已经截断；或者只写了不被接受的“关键判定分支” | 删除组件内部所有二至六级标题，改成 `**关键分支**：`、`**异常与失败传播**：`、`**正反 fixture 与测试**：`、`**扩展点**：`；必须使用指导列出的精确别名 |
| `living_plan_update_check` 报告 `previous-content SHA256 does not match` | 调用 WorkflowPlanAppender 后又编辑、格式化或重写了记录前面的架构正文；SHA 覆盖记录前的每一个字节 | 若当前阶段尚未通过，只完整删除末尾的当前阶段记录，修正架构正文后重新调用 Appender；不得手填摘要，不得修改任何已通过阶段记录 |
| 计划正文需要修正，但 Stage 00 记录已经追加 | Appender 调用过早，正文还未完成逐项字符数和标记自审 | 只对尚未通过的当前末尾记录执行“删除整块、修正文、重新 Appender”；下一次运行必须先按最小示例自审，全部定稿后再追加 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误、记录过短或 SHA 链失效 | 保留已通过的历史记录；只使用 WorkflowPlanAppender 追加新的合法记录，当前未通过末尾记录按上一条恢复 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
