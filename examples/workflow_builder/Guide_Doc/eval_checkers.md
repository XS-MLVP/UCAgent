# Checker评估详细指导

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

## 规则目录
### 01. CHECKERS-INVENTORY：Checker清单不闭合
- CHECKERS-INVENTORY检查对象：workflow_spec、spec、源码、注册、绑定、fixture和测试。
- CHECKERS-INVENTORY风险说明：如果该规则失败，可能出现“存在遗漏、孤立、重复或名称漂移”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-INVENTORY使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-INVENTORY操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-INVENTORY操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-INVENTORY通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“存在遗漏、孤立、重复或名称漂移”。
- CHECKERS-INVENTORY失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-INVENTORY正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“Checker清单不闭合”。
- CHECKERS-INVENTORY常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“workflow_spec、spec、源码、注册、绑定、fixture和测试”已经得到验证。
- CHECKERS-INVENTORY证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-INVENTORY默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-INVENTORY误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-INVENTORY修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 02. CHECKERS-REGISTRATION：Checker注册无效
- CHECKERS-REGISTRATION检查对象：模块路径、类名、类docstring和do_check docstring。
- CHECKERS-REGISTRATION风险说明：如果该规则失败，可能出现“UCAgent无法发现或解释Checker”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-REGISTRATION使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-REGISTRATION操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-REGISTRATION操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-REGISTRATION通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“UCAgent无法发现或解释Checker”。
- CHECKERS-REGISTRATION失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-REGISTRATION正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“Checker注册无效”。
- CHECKERS-REGISTRATION常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“模块路径、类名、类docstring和do_check docstring”已经得到验证。
- CHECKERS-REGISTRATION证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-REGISTRATION默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-REGISTRATION误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-REGISTRATION修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 03. CHECKERS-SIGNATURE：构造签名不匹配
- CHECKERS-SIGNATURE检查对象：配置args、__init__参数、默认值和kwargs。
- CHECKERS-SIGNATURE风险说明：如果该规则失败，可能出现“绑定时缺参、多参或类型错误”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-SIGNATURE使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-SIGNATURE操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-SIGNATURE操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-SIGNATURE通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“绑定时缺参、多参或类型错误”。
- CHECKERS-SIGNATURE失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-SIGNATURE正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“构造签名不匹配”。
- CHECKERS-SIGNATURE常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“配置args、__init__参数、默认值和kwargs”已经得到验证。
- CHECKERS-SIGNATURE证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-SIGNATURE默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-SIGNATURE误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-SIGNATURE修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 04. CHECKERS-POSITIVE：正确产物被拒绝
- CHECKERS-POSITIVE检查对象：最小正确fixture和真实正确产物。
- CHECKERS-POSITIVE风险说明：如果该规则失败，可能出现“误报导致工作流无法前进”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-POSITIVE使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-POSITIVE操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-POSITIVE操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-POSITIVE通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“误报导致工作流无法前进”。
- CHECKERS-POSITIVE失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-POSITIVE正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“正确产物被拒绝”。
- CHECKERS-POSITIVE常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“最小正确fixture和真实正确产物”已经得到验证。
- CHECKERS-POSITIVE证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-POSITIVE默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-POSITIVE误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-POSITIVE修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 05. CHECKERS-NEGATIVE：错误产物被接受
- CHECKERS-NEGATIVE检查对象：缺失、空文件、畸形格式和语义错误fixture。
- CHECKERS-NEGATIVE风险说明：如果该规则失败，可能出现“漏报让错误工作流通过”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-NEGATIVE使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-NEGATIVE操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-NEGATIVE操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-NEGATIVE通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“漏报让错误工作流通过”。
- CHECKERS-NEGATIVE失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-NEGATIVE正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“错误产物被接受”。
- CHECKERS-NEGATIVE常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“缺失、空文件、畸形格式和语义错误fixture”已经得到验证。
- CHECKERS-NEGATIVE证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-NEGATIVE默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-NEGATIVE误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-NEGATIVE修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 06. CHECKERS-BINDING：Checker绑定错误
- CHECKERS-BINDING检查对象：阶段、目标文件、参数和主要产物。
- CHECKERS-BINDING风险说明：如果该规则失败，可能出现“Checker检查了错误目录或辅助文件”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-BINDING使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-BINDING操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-BINDING操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-BINDING通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“Checker检查了错误目录或辅助文件”。
- CHECKERS-BINDING失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-BINDING正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“Checker绑定错误”。
- CHECKERS-BINDING常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“阶段、目标文件、参数和主要产物”已经得到验证。
- CHECKERS-BINDING证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-BINDING默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-BINDING误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-BINDING修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 07. CHECKERS-TIMING：检查时机错误
- CHECKERS-TIMING检查对象：产物生成阶段、引用顺序和执行时点。
- CHECKERS-TIMING风险说明：如果该规则失败，可能出现“读取未来文件或半成品”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-TIMING使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-TIMING操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-TIMING操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-TIMING通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“读取未来文件或半成品”。
- CHECKERS-TIMING失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-TIMING正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“检查时机错误”。
- CHECKERS-TIMING常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“产物生成阶段、引用顺序和执行时点”已经得到验证。
- CHECKERS-TIMING证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-TIMING默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-TIMING误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-TIMING修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 08. CHECKERS-SEMANTICS：未验证用户语义
- CHECKERS-SEMANTICS检查对象：需求、关键字段、行为和覆盖指标。
- CHECKERS-SEMANTICS风险说明：如果该规则失败，可能出现“只验证存在或格式就宣称完成”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-SEMANTICS使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-SEMANTICS操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-SEMANTICS操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-SEMANTICS通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“只验证存在或格式就宣称完成”。
- CHECKERS-SEMANTICS失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-SEMANTICS正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“未验证用户语义”。
- CHECKERS-SEMANTICS常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“需求、关键字段、行为和覆盖指标”已经得到验证。
- CHECKERS-SEMANTICS证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-SEMANTICS默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-SEMANTICS误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-SEMANTICS修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 09. CHECKERS-FALSE-RESULT：判定结果失真
- CHECKERS-FALSE-RESULT检查对象：布尔值、异常分支、宽松条件和日志解析。
- CHECKERS-FALSE-RESULT风险说明：如果该规则失败，可能出现“永真、异常默认通过或脆弱子串判断”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-FALSE-RESULT使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-FALSE-RESULT操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-FALSE-RESULT操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-FALSE-RESULT通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“永真、异常默认通过或脆弱子串判断”。
- CHECKERS-FALSE-RESULT失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-FALSE-RESULT正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“判定结果失真”。
- CHECKERS-FALSE-RESULT常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“布尔值、异常分支、宽松条件和日志解析”已经得到验证。
- CHECKERS-FALSE-RESULT证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-FALSE-RESULT默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-FALSE-RESULT误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-FALSE-RESULT修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 10. CHECKERS-CHALLENGE：Checker发现缺少反证
- CHECKERS-CHALLENGE检查对象：完整实现、框架基类和真实绑定。
- CHECKERS-CHALLENGE风险说明：如果该规则失败，可能出现“把可选参数或合法适配误报为缺陷”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-CHALLENGE使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-CHALLENGE操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-CHALLENGE操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-CHALLENGE通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“把可选参数或合法适配误报为缺陷”。
- CHECKERS-CHALLENGE失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-CHALLENGE正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“Checker发现缺少反证”。
- CHECKERS-CHALLENGE常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“完整实现、框架基类和真实绑定”已经得到验证。
- CHECKERS-CHALLENGE证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-CHALLENGE默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-CHALLENGE误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-CHALLENGE修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 11. CHECKERS-DOC-001：描述未说明检查目标
- CHECKERS-DOC-001检查对象：类和do_check文档字符串。
- CHECKERS-DOC-001风险说明：如果该规则失败，可能出现“注册失败或开发者不知道判据”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-DOC-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-DOC-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-DOC-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-DOC-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“注册失败或开发者不知道判据”。
- CHECKERS-DOC-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-DOC-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“描述未说明检查目标”。
- CHECKERS-DOC-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“类和do_check文档字符串”已经得到验证。
- CHECKERS-DOC-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-DOC-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-DOC-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-DOC-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 12. CHECKERS-ARGS-001：注册参数缺失
- CHECKERS-ARGS-001检查对象：配置给出的业务参数和构造函数。
- CHECKERS-ARGS-001风险说明：如果该规则失败，可能出现“Checker初始化必然失败”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-ARGS-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-ARGS-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-ARGS-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-ARGS-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“Checker初始化必然失败”。
- CHECKERS-ARGS-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-ARGS-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“注册参数缺失”。
- CHECKERS-ARGS-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“配置给出的业务参数和构造函数”已经得到验证。
- CHECKERS-ARGS-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-ARGS-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-ARGS-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-ARGS-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 13. CHECKERS-ARGS-002：多余参数被静默吞掉
- CHECKERS-ARGS-002检查对象：kwargs和未使用配置字段。
- CHECKERS-ARGS-002风险说明：如果该规则失败，可能出现“配置看似生效但实际无作用”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-ARGS-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-ARGS-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-ARGS-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-ARGS-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“配置看似生效但实际无作用”。
- CHECKERS-ARGS-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-ARGS-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“多余参数被静默吞掉”。
- CHECKERS-ARGS-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“kwargs和未使用配置字段”已经得到验证。
- CHECKERS-ARGS-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-ARGS-002默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-ARGS-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-ARGS-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 14. CHECKERS-FILE-001：只检查文件存在
- CHECKERS-FILE-001检查对象：文件内容、结构、范围和语义。
- CHECKERS-FILE-001风险说明：如果该规则失败，可能出现“空文件也能通过”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-FILE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-FILE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-FILE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-FILE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“空文件也能通过”。
- CHECKERS-FILE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-FILE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“只检查文件存在”。
- CHECKERS-FILE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“文件内容、结构、范围和语义”已经得到验证。
- CHECKERS-FILE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-FILE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-FILE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-FILE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 15. CHECKERS-FORMAT-001：只检查格式不检查内容
- CHECKERS-FORMAT-001检查对象：schema之后的业务不变量。
- CHECKERS-FORMAT-001风险说明：如果该规则失败，可能出现“合法JSON包含错误结果仍通过”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-FORMAT-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-FORMAT-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-FORMAT-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-FORMAT-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“合法JSON包含错误结果仍通过”。
- CHECKERS-FORMAT-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-FORMAT-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“只检查格式不检查内容”。
- CHECKERS-FORMAT-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“schema之后的业务不变量”已经得到验证。
- CHECKERS-FORMAT-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-FORMAT-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-FORMAT-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-FORMAT-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 16. CHECKERS-EXCEPTION-001：异常时默认通过
- CHECKERS-EXCEPTION-001检查对象：try/except和fallback返回。
- CHECKERS-EXCEPTION-001风险说明：如果该规则失败，可能出现“解析失败被当成成功”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-EXCEPTION-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-EXCEPTION-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-EXCEPTION-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-EXCEPTION-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“解析失败被当成成功”。
- CHECKERS-EXCEPTION-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-EXCEPTION-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“异常时默认通过”。
- CHECKERS-EXCEPTION-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“try/except和fallback返回”已经得到验证。
- CHECKERS-EXCEPTION-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-EXCEPTION-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-EXCEPTION-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-EXCEPTION-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 17. CHECKERS-HARDCODE-001：案例特征被硬编码
- CHECKERS-HARDCODE-001检查对象：模块名、固定路径、特定数值和fixture文本。
- CHECKERS-HARDCODE-001风险说明：如果该规则失败，可能出现“换输入后Checker失效”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-HARDCODE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-HARDCODE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-HARDCODE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-HARDCODE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“换输入后Checker失效”。
- CHECKERS-HARDCODE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-HARDCODE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“案例特征被硬编码”。
- CHECKERS-HARDCODE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“模块名、固定路径、特定数值和fixture文本”已经得到验证。
- CHECKERS-HARDCODE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-HARDCODE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-HARDCODE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-HARDCODE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 18. CHECKERS-FIXTURE-001：缺少独立负例
- CHECKERS-FIXTURE-001检查对象：错误类型矩阵和预期失败原因。
- CHECKERS-FIXTURE-001风险说明：如果该规则失败，可能出现“拒错能力没有证明”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-FIXTURE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-FIXTURE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-FIXTURE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-FIXTURE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“拒错能力没有证明”。
- CHECKERS-FIXTURE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-FIXTURE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“缺少独立负例”。
- CHECKERS-FIXTURE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“错误类型矩阵和预期失败原因”已经得到验证。
- CHECKERS-FIXTURE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-FIXTURE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-FIXTURE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-FIXTURE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 19. CHECKERS-FIXTURE-002：fixture由Checker生成
- CHECKERS-FIXTURE-002检查对象：样例来源和断言独立性。
- CHECKERS-FIXTURE-002风险说明：如果该规则失败，可能出现“实现与测试共享同一错误假设”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-FIXTURE-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-FIXTURE-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-FIXTURE-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-FIXTURE-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“实现与测试共享同一错误假设”。
- CHECKERS-FIXTURE-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-FIXTURE-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“fixture由Checker生成”。
- CHECKERS-FIXTURE-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“样例来源和断言独立性”已经得到验证。
- CHECKERS-FIXTURE-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-FIXTURE-002默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-FIXTURE-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-FIXTURE-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 20. CHECKERS-SCOPE-001：关键产物没有Checker
- CHECKERS-SCOPE-001检查对象：stage output与checker消费图。
- CHECKERS-SCOPE-001风险说明：如果该规则失败，可能出现“主要结果完全未验证”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-SCOPE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-SCOPE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-SCOPE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-SCOPE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“主要结果完全未验证”。
- CHECKERS-SCOPE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-SCOPE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“关键产物没有Checker”。
- CHECKERS-SCOPE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“stage output与checker消费图”已经得到验证。
- CHECKERS-SCOPE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-SCOPE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-SCOPE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-SCOPE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 21. CHECKERS-SCOPE-002：重复检查掩盖空白
- CHECKERS-SCOPE-002检查对象：各Checker覆盖的字段和需求。
- CHECKERS-SCOPE-002风险说明：如果该规则失败，可能出现“多个Checker检查同一格式却遗漏语义”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-SCOPE-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-SCOPE-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-SCOPE-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-SCOPE-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“多个Checker检查同一格式却遗漏语义”。
- CHECKERS-SCOPE-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-SCOPE-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“重复检查掩盖空白”。
- CHECKERS-SCOPE-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“各Checker覆盖的字段和需求”已经得到验证。
- CHECKERS-SCOPE-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-SCOPE-002默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-SCOPE-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-SCOPE-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 22. CHECKERS-ERROR-001：失败消息不可诊断
- CHECKERS-ERROR-001检查对象：错误字段、实际值、期望值和路径。
- CHECKERS-ERROR-001风险说明：如果该规则失败，可能出现“Agent只能盲目重试”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-ERROR-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-ERROR-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-ERROR-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-ERROR-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“Agent只能盲目重试”。
- CHECKERS-ERROR-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-ERROR-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“失败消息不可诊断”。
- CHECKERS-ERROR-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“错误字段、实际值、期望值和路径”已经得到验证。
- CHECKERS-ERROR-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-ERROR-001默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-ERROR-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-ERROR-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 23. CHECKERS-TIMEOUT-001：检查可能永久阻塞
- CHECKERS-TIMEOUT-001检查对象：子进程、文件等待和timeout参数。
- CHECKERS-TIMEOUT-001风险说明：如果该规则失败，可能出现“工作流卡死”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-TIMEOUT-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-TIMEOUT-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-TIMEOUT-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-TIMEOUT-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“工作流卡死”。
- CHECKERS-TIMEOUT-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-TIMEOUT-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“检查可能永久阻塞”。
- CHECKERS-TIMEOUT-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“子进程、文件等待和timeout参数”已经得到验证。
- CHECKERS-TIMEOUT-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-TIMEOUT-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-TIMEOUT-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-TIMEOUT-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 24. CHECKERS-PATH-001：路径基准或类型错误
- CHECKERS-PATH-001检查对象：文件与目录、cwd和workspace。
- CHECKERS-PATH-001风险说明：如果该规则失败，可能出现“等价路径被误判或目录被当文件”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-PATH-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-PATH-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-PATH-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-PATH-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“等价路径被误判或目录被当文件”。
- CHECKERS-PATH-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-PATH-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“路径基准或类型错误”。
- CHECKERS-PATH-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“文件与目录、cwd和workspace”已经得到验证。
- CHECKERS-PATH-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-PATH-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-PATH-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-PATH-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 25. CHECKERS-STATE-001：依赖历史残留
- CHECKERS-STATE-001检查对象：旧产物、缓存和执行顺序。
- CHECKERS-STATE-001风险说明：如果该规则失败，可能出现“干净工作区失败而脏工作区通过”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-STATE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-STATE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-STATE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-STATE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“干净工作区失败而脏工作区通过”。
- CHECKERS-STATE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-STATE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“依赖历史残留”。
- CHECKERS-STATE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“旧产物、缓存和执行顺序”已经得到验证。
- CHECKERS-STATE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-STATE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-STATE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-STATE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 26. CHECKERS-SECURITY-001：Checker执行危险命令
- CHECKERS-SECURITY-001检查对象：shell、删除、网络和工作区外访问。
- CHECKERS-SECURITY-001风险说明：如果该规则失败，可能出现“验证阶段破坏或泄漏数据”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-SECURITY-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-SECURITY-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-SECURITY-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-SECURITY-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“验证阶段破坏或泄漏数据”。
- CHECKERS-SECURITY-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-SECURITY-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“Checker执行危险命令”。
- CHECKERS-SECURITY-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“shell、删除、网络和工作区外访问”已经得到验证。
- CHECKERS-SECURITY-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-SECURITY-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-SECURITY-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-SECURITY-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 27. CHECKERS-COVERAGE-001：需求追踪缺失
- CHECKERS-COVERAGE-001检查对象：每个用户验证要求到Checker规则。
- CHECKERS-COVERAGE-001风险说明：如果该规则失败，可能出现“无法证明验收需求被覆盖”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-COVERAGE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-COVERAGE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-COVERAGE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-COVERAGE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“无法证明验收需求被覆盖”。
- CHECKERS-COVERAGE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-COVERAGE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“需求追踪缺失”。
- CHECKERS-COVERAGE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“每个用户验证要求到Checker规则”已经得到验证。
- CHECKERS-COVERAGE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-COVERAGE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-COVERAGE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-COVERAGE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 28. CHECKERS-RESULT-001：返回协议错误
- CHECKERS-RESULT-001检查对象：tuple布尔值、details类型和异常。
- CHECKERS-RESULT-001风险说明：如果该规则失败，可能出现“UCAgent无法解释检查结果”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CHECKERS-RESULT-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CHECKERS-RESULT-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CHECKERS-RESULT-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CHECKERS-RESULT-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“UCAgent无法解释检查结果”。
- CHECKERS-RESULT-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CHECKERS-RESULT-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“返回协议错误”。
- CHECKERS-RESULT-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“tuple布尔值、details类型和异常”已经得到验证。
- CHECKERS-RESULT-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CHECKERS-RESULT-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CHECKERS-RESULT-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CHECKERS-RESULT-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

## 报告提交前复核
- 重新计算强制规则ID集合，缺一项都不能提交为通过。
- 对每条高危发现执行反证，并确认严重程度理由与真实影响一致。
- 检查报告状态是否由checks和findings推导，而不是由评估者主观选择。
- 检查所有临时文件位于tmp，所有结构化状态由受控工具更新。
- 检查用户需求中的每个动词和交付物都有明确评估结论。
