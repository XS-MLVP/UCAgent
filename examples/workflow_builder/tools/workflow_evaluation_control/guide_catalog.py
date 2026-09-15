# -*- coding: utf-8 -*-
"""Generate the detailed evaluation guides from a reviewable rule catalog."""

from __future__ import annotations

from pathlib import Path


CATALOG_TEXT = {
    "evaluation_contract.md": """
CONTRACT-SCOPE-001|职责越界|评估类型、允许工具和禁止操作|静态评估启动子工作流或直接修改被评估工程|critical
CONTRACT-INPUT-001|输入清单不完整|guide、res、配置、规范、源码、测试和历史报告|未读取关键输入就形成结论|high
CONTRACT-INVENTORY-001|对象清点遗漏|声明、注册、实现、绑定、测试和产物的双向清单|只从单一入口向下检查造成孤立项漏检|high
CONTRACT-EVIDENCE-001|证据无法定位|文件、字段、行号、命令、返回码和内容摘要|只写主观判断或模糊路径|high
CONTRACT-EVIDENCE-002|证据已经过期|报告目标版本和被引用文件指纹|代码变化后继续复用旧证据|high
CONTRACT-CONFIDENCE-001|猜测被写成事实|confirmed、probable、suspected 的使用|未复现问题却标为 confirmed|medium
CONTRACT-SEVERITY-001|阻塞运行风险低估|启动、配置解析、死锁、无限重试和破坏性行为|导致无法运行的问题未标 critical|critical
CONTRACT-SEVERITY-002|语义欺骗风险低估|核心需求、真实产物和完成声明|核心需求未实现却标为低风险|high
CONTRACT-SEVERITY-003|一般缺陷风险夸大|可恢复契约问题和非关键兼容性|把不影响正确性的风格问题标 high|medium
CONTRACT-STATUS-001|报告状态与发现冲突|checks、findings、severity 和终态|存在 critical/high 却写 passed|critical
CONTRACT-CHECK-001|必检规则缺失|对应评估类型的 REQUIRED_CHECK_IDS|跳过规则仍提交完整报告|high
CONTRACT-CHECK-002|检查记录空泛|check summary 和 evidence|写已检查但没有说明对象与结果|high
CONTRACT-FINDING-001|发现字段不完整|expected、actual、impact、recommendation 和 repro|无法理解期望与实际差异|medium
CONTRACT-SEMANTIC-001|只审语法不审需求|用户需求到阶段、工具、Checker、产物的追踪|文件合法但功能并未实现|high
CONTRACT-TRUTH-001|伪造完成未识别|随机值、固定成功、空模板和永真断言|无真实工作仍宣称完成|high
CONTRACT-CHALLENGE-001|缺少反证审查|每个候选 finding 的替代解释和复核|把合法架构差异当作缺陷|medium
CONTRACT-FALSEPOS-001|搜索片段造成误报|完整源码上下文与实际数据流|只看关键词就推断行为|medium
CONTRACT-REACHABILITY-001|合成输入被冒充为真实缺陷|生产者、写入边界、artifact 与失败状态的可达路径|随意篡改字段类型后将不可达异常定为正式缺陷|medium
CONTRACT-FALSENEG-001|正例替代拒错测试|错误、缺失、空值、边界和恶意输入|只跑 happy path 就判定可靠|high
CONTRACT-HISTORY-001|历史报告被覆盖|runs 追加语义和 latest_run_id|新评估删除旧运行记录|high
CONTRACT-JSON-001|结构化文件被直接编辑|StructuredJsonStore 与审计事件|Agent 用普通写文件工具修改 eval JSON|high
CONTRACT-TEMP-001|临时文件越界|tmp 下的日志、fixture、候选和缓存|临时内容污染 wfgen、workflow 或 eval|high
CONTRACT-RES-001|用户知识被修改|res 只读约束|评估 Agent 改写专业知识以迎合结果|critical
CONTRACT-APPROVAL-001|未批准修改|审批来源、决定和指纹|开放 finding 被自动实施|critical
CONTRACT-APPROVAL-002|过期批准复用|source fingerprint 和当前报告|目标变化后仍使用旧批准|high
CONTRACT-BLOCK-001|证据不足仍给结论|blocked 状态与缺失原因|环境不可用时猜测 passed 或 failed|high
CONTRACT-REPRO-001|复现步骤不可执行|受控命令、输入和预期输出|建议无法被下一位开发者验证|medium
CONTRACT-SECURITY-001|敏感信息进入报告|令牌、代理凭据、主机路径和用户数据|证据原样泄漏秘密|critical
CONTRACT-CLOSURE-001|跨阶段问题无人负责|专项报告、summary、审批和增量复评|问题在工作流间丢失|high
""",
    "eval_tools.md": """
TOOLS-INVENTORY|工具清单不闭合|配置注册、workflow_spec、manifest、spec、源码和测试|声明与实现之间存在缺失、孤立或重复项|high
TOOLS-REGISTRATION|工具注册无效|模块路径、导出集合、工具名和类名|运行器无法导入或名称不一致|critical
TOOLS-CONTRACT|UCTool契约错误|继承或适配器、name、description、args_schema 和 _run|实现不符合UCAgent调用协议|high
TOOLS-PARAM-001|必需参数遗漏|spec、Pydantic字段、_run签名和配置调用|调用时必然缺参或多参|high
TOOLS-PARAM-002|参数类型不一致|schema类型、默认值、枚举和运行转换|合法输入被拒绝或非法输入进入核心逻辑|high
TOOLS-DESC-001|工具描述不足|description中的用途、边界、输入和产物|Agent无法选择正确工具或误用工具|medium
TOOLS-POSITIVE|正常调用不可用|最小合法输入、外部依赖和预期产物|工具不能完成基本业务路径|high
TOOLS-NEGATIVE|错误输入未拒绝|缺文件、空值、错误格式、越界值和不支持选项|错误数据仍返回成功|high
TOOLS-OUTPUT|输出契约不匹配|返回JSON、文件内容、文件名和下游消费者|产物存在但无法被下一阶段使用|high
TOOLS-FAILURE|异常处理失真|非零返回码、异常、超时、stderr和部分产物|错误被吞掉或包装成成功|high
TOOLS-SAFETY|写入或命令越界|工作区边界、允许目录、argv和路径解析|修改输入、工作区外写入或shell注入|critical
TOOLS-SEMANTICS|产物不满足用户需求|guide、res、需求清单和真实输出|工具功能与用户语义偏离|high
TOOLS-CHALLENGE|工具发现缺少反证|完整调用链、适配器和框架约定|合法适配实现被误报为未继承|medium
TOOLS-FAKE-001|随机结果冒充检测|随机模块、概率分支和结果来源|相同输入产生无依据结论|high
TOOLS-FAKE-002|固定成功冒充执行|常量passed、固定返回和未调用核心引擎|没有实际工作却报告成功|high
TOOLS-FAKE-003|占位产物冒充结果|TODO、stub、空模板、永真断言和示例文本|产物格式存在但没有业务价值|high
TOOLS-MATCH-001|脆弱字符串判断|PASS、error等子串与结构化状态|误把NOT PASS或日志文本当成功|high
TOOLS-IDEMPOTENT-001|重复执行污染|旧产物、缓存、追加文件和确定性|第二次运行结果依赖第一次残留|medium
TOOLS-PATH-001|相对路径基准错误|cwd、workspace、workflow_root和目标目录|换目录后读取或写入错误位置|high
TOOLS-PATH-002|路径遍历未阻断|绝对路径、..、符号链接和解析后边界|用户参数可以逃离工作区|critical
TOOLS-FILE-001|输入文件被修改|只读输入哈希和执行前后差异|验证工具破坏用户源码|critical
TOOLS-TEMP-001|临时文件位置错误|tmp目录、日志、fixture和缓存|临时内容进入正式交付目录|medium
TOOLS-EXTERNAL-001|外部命令调用不可靠|argv、超时、返回码、编码和工具存在性|命令挂起或失败后仍继续|high
TOOLS-PORTABLE-001|机器环境被硬编码|用户名、绝对路径、平台命令和Python版本|移植到其他系统即失败|medium
TOOLS-SCALE-001|扫描或内存无界|目录深度、文件数量、单文件大小和输出上限|大工程导致卡死或资源耗尽|critical
TOOLS-LOG-001|诊断信息不足|错误码、组件、输入摘要和建议|失败后无法定位或复现|medium
TOOLS-TEST-001|测试与实现同源失真|独立fixture、预期值来源和负例|测试复刻实现错误而同时通过|high
TOOLS-DOWNSTREAM-001|下游消费未经验证|阶段任务、Checker和解析器|工具单测通过但工作流衔接失败|high
""",
    "eval_checkers.md": """
CHECKERS-INVENTORY|Checker清单不闭合|workflow_spec、spec、源码、注册、绑定、fixture和测试|存在遗漏、孤立、重复或名称漂移|high
CHECKERS-REGISTRATION|Checker注册无效|模块路径、类名、类docstring和do_check docstring|UCAgent无法发现或解释Checker|critical
CHECKERS-SIGNATURE|构造签名不匹配|配置args、__init__参数、默认值和kwargs|绑定时缺参、多参或类型错误|high
CHECKERS-POSITIVE|正确产物被拒绝|最小正确fixture和真实正确产物|误报导致工作流无法前进|high
CHECKERS-NEGATIVE|错误产物被接受|缺失、空文件、畸形格式和语义错误fixture|漏报让错误工作流通过|high
CHECKERS-BINDING|Checker绑定错误|阶段、目标文件、参数和主要产物|Checker检查了错误目录或辅助文件|high
CHECKERS-TIMING|检查时机错误|产物生成阶段、引用顺序和执行时点|读取未来文件或半成品|critical
CHECKERS-SEMANTICS|未验证用户语义|需求、关键字段、行为和覆盖指标|只验证存在或格式就宣称完成|high
CHECKERS-FALSE-RESULT|判定结果失真|布尔值、异常分支、宽松条件和日志解析|永真、异常默认通过或脆弱子串判断|high
CHECKERS-CHALLENGE|Checker发现缺少反证|完整实现、框架基类和真实绑定|把可选参数或合法适配误报为缺陷|medium
CHECKERS-DOC-001|描述未说明检查目标|类和do_check文档字符串|注册失败或开发者不知道判据|high
CHECKERS-ARGS-001|注册参数缺失|配置给出的业务参数和构造函数|Checker初始化必然失败|critical
CHECKERS-ARGS-002|多余参数被静默吞掉|kwargs和未使用配置字段|配置看似生效但实际无作用|high
CHECKERS-FILE-001|只检查文件存在|文件内容、结构、范围和语义|空文件也能通过|high
CHECKERS-FORMAT-001|只检查格式不检查内容|schema之后的业务不变量|合法JSON包含错误结果仍通过|high
CHECKERS-EXCEPTION-001|异常时默认通过|try/except和fallback返回|解析失败被当成成功|critical
CHECKERS-HARDCODE-001|案例特征被硬编码|模块名、固定路径、特定数值和fixture文本|换输入后Checker失效|high
CHECKERS-FIXTURE-001|缺少独立负例|错误类型矩阵和预期失败原因|拒错能力没有证明|high
CHECKERS-FIXTURE-002|fixture由Checker生成|样例来源和断言独立性|实现与测试共享同一错误假设|high
CHECKERS-FIXTURE-003|无来源的畸形字段造成误报|真实生产者、用户输入边界、artifact 契约和 reachability 证据|将字段随意改为 null 或错误容器类型后把不可达异常定为业务缺陷|medium
CHECKERS-INTEGRATION-001|正例未使用真实生产者产物|注册生产者、实际 artifact、Checker 绑定和判定结果|自带 fixture 与错误实现相互印证而掩盖产销契约不一致|high
CHECKERS-SCOPE-001|关键产物没有Checker|stage output与checker消费图|主要结果完全未验证|high
CHECKERS-SCOPE-002|重复检查掩盖空白|各Checker覆盖的字段和需求|多个Checker检查同一格式却遗漏语义|medium
CHECKERS-ERROR-001|失败消息不可诊断|错误字段、实际值、期望值和路径|Agent只能盲目重试|medium
CHECKERS-TIMEOUT-001|检查可能永久阻塞|子进程、文件等待和timeout参数|工作流卡死|critical
CHECKERS-PATH-001|路径基准或类型错误|文件与目录、cwd和workspace|等价路径被误判或目录被当文件|high
CHECKERS-STATE-001|依赖历史残留|旧产物、缓存和执行顺序|干净工作区失败而脏工作区通过|high
CHECKERS-SECURITY-001|Checker执行危险命令|shell、删除、网络和工作区外访问|验证阶段破坏或泄漏数据|critical
CHECKERS-COVERAGE-001|需求追踪缺失|每个用户验证要求到Checker规则|无法证明验收需求被覆盖|high
CHECKERS-RESULT-001|返回协议错误|tuple布尔值、details类型和异常|UCAgent无法解释检查结果|critical
""",
    "eval_flow.md": """
FLOW-PARSE|配置解析失败|主配置、增量配置、规范和可选配置|YAML无效、重复键或顶层类型错误|critical
FLOW-PLACEHOLDERS|运行时符号不闭合|所有字符串字段、内建变量和template_overwrite|存在未知、拼错、循环或残留占位符|high
FLOW-PATHS|文件路径契约错误|reference_files、output_files和checker参数|目录、不确定路径、越界路径或错误基准|high
FLOW-DAG|阶段依赖图错误|阶段顺序、显式输出和隐式前置条件|循环、自依赖或顺序无法满足|critical
FLOW-PROVENANCE|引用来源不可证明|固定交付、运行输入和前序输出|读取未来产物或从未生成的文件|high
FLOW-TOOLS|阶段工具不可用|ex_tools、tools注册、任务调用和实现|阶段要求的工具没有注册或参数错误|critical
FLOW-CHECKERS|检查绑定不合理|checker注册、args、时机和产物|Checker必然初始化失败或检查错误对象|high
FLOW-OUTPUTS|输出契约冲突|阶段输出、重复路径和下游消费|覆盖无增量语义或关键输出无人消费|high
FLOW-RETRY|失败恢复无法终止|重试次数、恢复动作和Checker反馈|相同失败无限重试或无进展|critical
FLOW-DOCUMENTATION|文档与实现不一致|Guide_Doc、docs、README和Makefile|命令、路径、输入输出或能力声明错误|medium
FLOW-SEMANTICS|流程偏离用户需求|需求清单到阶段、工具、Checker和产物|语法正确但核心目标未实现|high
FLOW-CHALLENGE|流程发现缺少反证|路径归一化、顺序覆盖和框架语义|把等价路径或明确 refinement 误报|medium
FLOW-YAML-001|字段层级错误|mission、stage、checker和template字段|字段存在但运行器不会读取|high
FLOW-YAML-002|字段类型错误|列表、映射、字符串和布尔字段|解析成功但运行时类型不符|high
FLOW-VAR-001|符号仅在文档出现|占位符声明表和实际配置|说明了变量却没有template声明|high
FLOW-VAR-002|符号大小写漂移|声明键与引用名称|Linux环境中替换失败|high
FLOW-VAR-003|嵌套替换顺序错误|template值之间的依赖图|单次替换后仍保留花括号|high
FLOW-PATH-001|父工作流前缀泄漏|子工作流内部相对路径|生成.//workflow或workflow/workflow路径|high
FLOW-PATH-002|文件和目录混用|reference与output条目类型|ReadTextFile接收到目录|high
FLOW-PATH-003|二进制文件进入文本引用|图片、PDF、归档和文本读取工具|阶段必然无法正确读取|high
FLOW-STAGE-001|任务描述不可执行|输入、工具、输出、检查和恢复|只有目标口号没有操作步骤|medium
FLOW-STAGE-002|阶段名称重复|所有stage name|状态追踪和报告绑定混乱|high
FLOW-STAGE-003|阶段没有可验证输出|output_files和checker|无法判断本阶段是否完成|high
FLOW-CHECK-001|关键输出未绑定Checker|主要业务产物和验收要求|错误产物可以直接进入下一阶段|high
FLOW-MODE-001|主增量模式混淆|workflow.mode、Make目标和配置路径|运行错误流程或修改错误对象|critical
FLOW-WRITE-001|写目录过宽|write_dirs和un_write_dirs|Agent可修改输入、res或工作区外文件|critical
FLOW-CONFIG-001|规范与生成配置漂移|workflow_spec和config/inc|计划的Checker、路径或阶段未落地|high
FLOW-COMPLETE-001|完成声明没有需求证据|最终阶段、coverage和报告|遗漏核心需求却宣称交付完成|high
""",
    "eval_env.md": """
ENV-MAKE|Make入口不可用|目标、依赖、变量、工作目录和返回码|用户命令无法启动正确流程|critical
ENV-SETUP|环境配置程序不可用|setup.py首次配置、更新、校验和幂等性|无法迁移或重复运行破坏环境|high
ENV-SHELL|环境脚本不安全|ucagent_setup.sh语法、受控块和重复source|覆盖用户内容、执行失败或重复污染|high
ENV-DEPENDENCIES|依赖声明不完整|requirements.txt和非Python安装注释|缺包或外部命令导致运行失败|high
ENV-TOOLCHAIN|外部工具链不可用|Verilator、编译器、make和版本检查|仿真或编译阶段无法执行|critical
ENV-PATHS|环境路径不可移植|绝对路径、用户名、HOME和相对基准|换机器或换工作区即失败|high
ENV-TEMP|临时目录边界错误|tmp、缓存、日志、fixture和案例|临时文件污染正式交付|medium
ENV-CLEAN|清理目标具有破坏性|input、eval、res、tmp和输出|clean删除用户输入或历史报告|critical
ENV-PORTABILITY|系统兼容性不足|Linux发行版、shell、Python和命令差异|支持范围内平台无法安装运行|medium
ENV-SECRETS|敏感配置泄漏|令牌、代理、用户名、主机和环境转储|秘密进入脚本、报告或迁移包|critical
ENV-CHALLENGE|环境发现缺少反证|明确支持矩阵、配置覆盖和用户约束|把已声明的平台限制误报为缺陷|low
ENV-MAKE-001|工作区变量未传递|WS、WFB_WORKSPACE、TARGET、OUT和子make|流程运行在错误目录|critical
ENV-MAKE-002|TUI参数组合错误|--tui、--loop、--no-history和mcp端口|界面消失或流程没有自动开始|high
ENV-MAKE-003|目标依赖产生副作用|prepare、eval、clean和session依赖|只查看报告也重置运行状态|medium
ENV-SETUP-001|配置更新覆盖手工内容|受控标记和文件重写策略|用户自定义设置丢失|high
ENV-SETUP-002|无交互环境永久等待|isatty、默认值和非交互模式|CI或远程运行卡死|critical
ENV-SCHEMA-001|环境schema与程序漂移|字段、类型、默认值和必填性|setup写出的配置无法被Make使用|high
ENV-REQ-001|标准库错误列为依赖|Python import与包分发名称|安装命令失败或误导用户|low
ENV-REQ-002|非Python依赖缺安装方法|系统包名和发行版命令|用户无法准备仿真环境|medium
ENV-SHELL-001|shell语法或引用错误|路径空格、变量展开和set选项|source后环境错误或脚本中断|high
ENV-SHELL-002|受控区块重复|开始结束标记和更新算法|每次setup追加重复变量|medium
ENV-CLEAN-001|tmp没有彻底清空|日志、案例、缓存和候选|旧状态污染新评估|medium
ENV-CLEAN-002|清理越过符号链接|find、rm和路径解析|删除工作区外内容|critical
ENV-MIGRATE-001|迁移包包含本机状态|绝对路径、日志、缓存、eval历史和秘密|交付不可复现或泄漏数据|high
ENV-PROXY-001|代理状态未传递|父shell、tmux和子进程环境|联网依赖在会话内失败|medium
ENV-CONCURRENT-001|并发会话互相覆盖|tmux名称、端口、日志和状态目录|两个评估破坏彼此结果|high
ENV-RETURN-001|命令返回码被忽略|Make recipe管道和tee|底层失败但目标返回成功|high
ENV-COLOR-001|终端能力配置不一致|TERM、COLORTERM和FORCE_COLOR|TUI可读性或绘制异常|low
""",
    "eval_run.md": """
RUN-PREFLIGHT|运行前置条件缺失|run_request、输入契约、配置、环境和静态审计|明知无法启动仍进入昂贵运行|high
RUN-START|子工作流未正确启动|mode、Make目标、tmux会话、PID和首个状态|命令返回但任务没有运行|critical
RUN-PROGRESS|进度监控不完整|stage index、标题、状态、fail_count和活动时间|无法判断推进、失败或卡住|high
RUN-RETRY|重复失败没有归因|错误指纹、重试次数和恢复动作|Agent无限重复相同操作|critical
RUN-STALL|停滞没有及时终止|最后活动、阶段变化和stall阈值|工作流长时间卡死|critical
RUN-TIMEOUT|总运行时限失效|max_runtime、开始时间和终止动作|子流程无界占用资源|critical
RUN-CLEANUP|结束后遗留进程|tmux、子进程、端口和stop结果|后台流程继续写文件或占资源|critical
RUN-OUTPUTS|真实产物不完整|output_files、最终文件和内容质量|界面完成但交付缺失|high
RUN-RESULT|多种状态来源矛盾|TUI、UCAgent状态、Checker和文件系统|假成功或假失败未识别|high
RUN-SEMANTICS|运行结果偏离需求|用户验收、真实输出和报告声明|流程跑完但核心目标未达到|high
RUN-CHALLENGE|运行发现缺少反证|完整时间线、外部中断和环境变化|把用户停止或监控延迟误报为程序缺陷|medium
RUN-REQUEST-001|default和inc混在同轮|mode和目标选择|结果无法归因且状态相互污染|high
RUN-REQUEST-002|目标输入不存在|runtime_contract.required_input和target|启动后必然失败|high
RUN-START-001|工作区变量错误|实际cwd、WS、workflow_root和TARGET|运行了错误工程或错误输入|critical
RUN-START-002|命令启动但未进入loop|终端首屏、loop参数和agent活动|TUI存在但流程没有开始|high
RUN-TUI-001|界面消失但进程存活|tmux pane、PID和日志|用户无法监督且流程状态不明|high
RUN-FAIL-001|fail_count异常增长|每次失败消息和Checker结果|工作流或Checker存在系统性问题|high
RUN-FAIL-002|业务失败被自动修补掩盖|评估边界和修改记录|评估者代替被测Agent修复产物|high
RUN-LOG-001|终端证据被截断|首个错误、最后错误和关键上下文|无法定位失败根因|medium
RUN-ACTIVITY-001|日志输出冒充进度|阶段状态和文件变化|重复打印让stall检测失效|high
RUN-PROCESS-001|子进程脱离监督|进程树、session和进程组|stop无法终止全部任务|critical
RUN-DISK-001|输出无界增长|日志大小、临时文件和剩余空间|磁盘耗尽导致系统故障|critical
RUN-STATE-001|依赖旧运行残留|干净运行和重复运行对比|脏工作区通过而首次运行失败|high
RUN-CHECK-001|Checker未实际执行|阶段check状态和调用证据|产物未经验证就完成|high
RUN-CHECK-002|Checker永远无法通过|失败条件与Agent可修改范围|工作流陷入无解重试|critical
RUN-STOP-001|超时后没有finally清理|异常、取消和超时分支|失败运行留下tmux和端口|critical
RUN-REPORT-001|时间线与终态不一致|started、events、finished和status|报告无法审计真实过程|medium
RUN-REPRO-001|复现命令缺少环境|命令、变量、目标和输入|后续开发者无法复现|medium
""",
    "incremental_evaluation.md": """
INC-AUTHORIZATION|修改没有明确批准|approvals决定、理由和来源|开放问题或建议被自动实施|critical
INC-PROVENANCE|批准来源不可追溯|source_kind、report、run_id、source_id和fingerprint|无法确认用户批准的具体内容|high
INC-FRESHNESS|批准已经过期|当前来源指纹与批准指纹|对象变化后仍沿用旧决定|high
INC-SCOPE|修改范围超过授权|批准描述、允许文件和禁止项|顺便重构或改变未批准行为|high
INC-CANDIDATE|候选文件位置错误|tmp/inc_candidates下的source|直接修改workflow或把候选放正式目录|critical
INC-SOURCE-SYNC|只修改生成副本|spec、模板、注册、测试和最终文件|下次生成重新出现同一问题|high
INC-REGRESSION|受影响检查未执行|变更映射到静态和direct测试|修复引入新的流程故障|high
INC-DEPLOYMENT|部署证据不完整|source、target、approval_ids和SHA256|无法证明部署内容与候选一致|high
INC-RECHECK|修复被提前标记解决|pending_recheck和专项复评|没有独立验证就关闭finding|high
INC-CHALLENGE|增量建议缺少反证|根因、替代方案和最小范围|实施表面修复或无关修改|medium
INC-APPROVAL-001|旧版批准直接使用|来源字段和决定时间|无追踪记录驱动实际修改|high
INC-APPROVAL-002|拒绝项仍被实施|最新decision和历史|违反用户明确决定|critical
INC-APPROVAL-003|暂缓项被当批准|deferred与approved区分|用户尚未决定却发生修改|critical
INC-SUGGEST-001|建议自动提升为缺陷|用户建议状态和审批|建议未经批准直接实施|high
INC-SUGGEST-002|用户建议被改写语义|原始标题、描述和最终计划|修改内容偏离用户意图|high
INC-DEDUP-001|同一问题重复实施|fingerprint、历史change和当前状态|产生冲突修改和重复报告|medium
INC-PLAN-001|计划没有文件白名单|mappings和不修改项|Agent可无限扩大修改范围|high
INC-PLAN-002|计划没有受影响测试|组件依赖和验证目标|部署后无法确认回归风险|medium
INC-TMP-001|临时备份污染交付|候选、日志、fixture和案例|临时内容进入workflow根|medium
INC-DEPLOY-001|目标路径逃逸|相对路径、..、绝对路径和符号链接|覆盖工作区外文件|critical
INC-DEPLOY-002|目标带重复workflow前缀|workflow_root相对target|文件部署到错误嵌套目录|high
INC-HASH-001|部署后哈希不一致|source、target和记录摘要|记录与实际文件不一致|critical
INC-TOOL-001|工具修改未同步契约|tool spec、manifest、源码、测试和文档|注册或下游调用仍使用旧接口|high
INC-CHECKER-001|Checker修改未同步绑定|workflow_spec、spec、源码、fixture和config|新Checker没有实际生效|high
INC-CONFIG-001|配置修改未同步规范|workflow_spec、主配置和增量配置|计划与运行配置继续漂移|high
INC-DOC-001|行为变化未更新文档|Guide_Doc、用户文档和开发者文档|用户按旧命令或旧契约操作|medium
INC-ROLLBACK-001|失败没有回滚建议|已部署文件、哈希和恢复路径|部分修改留下不可运行状态|high
INC-STATUS-001|no_change记录不完整|批准扫描、原因和checks|无法证明为何没有修改|medium
""",
}


INTRO = """# {title}

## 文档目的
本指导用于执行可审计的工作流评估。规则不是关键词搜索清单，而是从声明、实现、调用、产物、检查和用户需求建立闭环。
评估者必须读取完整文件和上下文，不能根据搜索片段直接下结论，也不能为通过评估而修改被评估工程。
每条规则都要保留可复现证据。无法获得证据时使用 blocked 或 suspected，不允许猜测通过。

## 严重程度
- critical：导致UCAgent无法启动、必然卡死、无限重试、破坏文件、越界访问、泄漏秘密或用假成功掩盖整体失败。
- high：核心用户需求没有实现、关键工具不可用、关键Checker漏检、重要产物错误或工作流欺骗用户已经完成。
- medium：部分覆盖不足、可恢复契约错误、限定环境的兼容问题或具有条件性的错误结果风险。
- low：不影响正确运行的文档、维护性和非关键一致性问题。
- info：经过核实的观察项，不构成当前缺陷。

## 证据与反证
- confirmed必须有确定性复现或能直接证明结论的源码与数据流证据。
- probable至少需要两项相互独立的证据，并明确尚未完成的验证。
- suspected只进入待确认记录，不得直接成为正式finding。
- 每个candidate finding提交前都要尝试寻找合法替代解释，并重读精确源码、配置字段和调用方。
- 检查通过也要记录对象、方法和证据，禁止只写“已检查”。

## 最小可通过报告
- contract_version必须为2。
- checks必须包含本评估类型全部强制ID。
- 每个check必须包含id、status、summary和非空evidence。
- finding必须包含expected、actual、severity_reason、confidence、requirement_refs和结构化evidence。
- source证据至少包含kind、path、location、observation；command证据至少包含kind、command、returncode、observation。
- artifact证据至少包含kind、path、observation；timeline证据至少包含kind、time、observation。
- 任一critical/high或强制检查失败时报告状态必须为failed。
- 仅有medium/low时状态使用passed_with_findings。
- 证据不足时状态使用blocked。
"""


PREAMBLES = {
    "evaluation_contract.md": """
- 静态审计规则身份必须写在 finding.rule_id，审计对象必须保留在 finding.path 或结构化 evidence 中。requirement_refs 只追踪被违反的需求、合同或指导规则，不能承担 finding 身份匹配职责。
- Checker 应按结构化身份字段比较审计与报告，禁止依赖 JSON 字段顺序、原始文件哈希或包装层级；允许报告在不改变 rule_id/path 语义的前提下增加分析字段。
""",
}


TITLES = {
    "evaluation_contract.md": "评估与增量工作流总契约",
    "eval_tools.md": "工具评估详细指导",
    "eval_checkers.md": "Checker评估详细指导",
    "eval_flow.md": "流程配置评估详细指导",
    "eval_env.md": "环境与配套设施评估详细指导",
    "eval_run.md": "运行行为评估详细指导",
    "incremental_evaluation.md": "评估驱动增量修改详细指导",
}


def _parse(text: str) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for line in text.strip().splitlines():
        parts = tuple(part.strip() for part in line.split("|"))
        if len(parts) != 5:
            raise ValueError(f"invalid guide catalog row: {line}")
        rows.append(parts)
    return rows


def _render_rule(index: int, row: tuple[str, str, str, str, str]) -> str:
    rule_id, title, target, failure, severity = row
    return f"""### {index:02d}. {rule_id}：{title}
- {rule_id}检查对象：{target}。
- {rule_id}风险说明：如果该规则失败，可能出现“{failure}”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- {rule_id}使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- {rule_id}操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- {rule_id}操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- {rule_id}通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“{failure}”。
- {rule_id}失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- {rule_id}正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“{title}”。
- {rule_id}常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“{target}”已经得到验证。
- {rule_id}证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- {rule_id}默认严重程度：{severity}；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- {rule_id}误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- {rule_id}修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。
"""


def render_guides(root: Path) -> list[str]:
    """Regenerate all detailed guide documents."""
    guide_dir = root / "Guide_Doc"
    written = []
    for filename, text in CATALOG_TEXT.items():
        rows = _parse(text)
        body = INTRO.format(title=TITLES[filename])
        preamble = PREAMBLES.get(filename, "").strip()
        if filename == "evaluation_contract.md" and preamble:
            body = body.replace(
                "- source证据至少包含kind、path、location、observation；",
                preamble + "\n- source证据至少包含kind、path、location、observation；",
            )
        elif preamble:
            body += "\n" + preamble + "\n"
        body += "\n## 规则目录\n"
        body += "\n".join(_render_rule(index, row) for index, row in enumerate(rows, 1))
        body += """
## 报告提交前复核
- 重新计算强制规则ID集合，缺一项都不能提交为通过。
- 对每条高危发现执行反证，并确认严重程度理由与真实影响一致。
- 检查报告状态是否由checks和findings推导，而不是由评估者主观选择。
- 检查所有临时文件位于tmp，所有结构化状态由受控工具更新。
- 检查用户需求中的每个动词和交付物都有明确评估结论。
"""
        path = guide_dir / filename
        path.write_text(body, encoding="utf-8")
        written.append(str(path))
    return written


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    for output in render_guides(project_root):
        print(output)
