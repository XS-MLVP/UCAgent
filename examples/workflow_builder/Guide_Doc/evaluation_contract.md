# 评估与增量工作流总契约

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
- 静态审计规则身份必须写在 finding.rule_id，审计对象必须保留在 finding.path 或结构化 evidence 中。requirement_refs 只追踪被违反的需求、合同或指导规则，不能承担 finding 身份匹配职责。
- Checker 应按结构化身份字段比较审计与报告，禁止依赖 JSON 字段顺序、原始文件哈希或包装层级；允许报告在不改变 rule_id/path 语义的前提下增加分析字段。
- source证据至少包含kind、path、location、observation；command证据至少包含kind、command、returncode、observation。
- artifact证据至少包含kind、path、observation；timeline证据至少包含kind、time、observation。
- 任一critical/high或强制检查失败时报告状态必须为failed。
- 仅有medium/low时状态使用passed_with_findings。
- 证据不足时状态使用blocked。

## 规则目录
### 01. CONTRACT-SCOPE-001：职责越界
- CONTRACT-SCOPE-001检查对象：评估类型、允许工具和禁止操作。
- CONTRACT-SCOPE-001风险说明：如果该规则失败，可能出现“静态评估启动子工作流或直接修改被评估工程”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-SCOPE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-SCOPE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-SCOPE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-SCOPE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“静态评估启动子工作流或直接修改被评估工程”。
- CONTRACT-SCOPE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-SCOPE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“职责越界”。
- CONTRACT-SCOPE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“评估类型、允许工具和禁止操作”已经得到验证。
- CONTRACT-SCOPE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-SCOPE-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-SCOPE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-SCOPE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 02. CONTRACT-INPUT-001：输入清单不完整
- CONTRACT-INPUT-001检查对象：guide、res、配置、规范、源码、测试和历史报告。
- CONTRACT-INPUT-001风险说明：如果该规则失败，可能出现“未读取关键输入就形成结论”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-INPUT-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-INPUT-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-INPUT-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-INPUT-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“未读取关键输入就形成结论”。
- CONTRACT-INPUT-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-INPUT-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“输入清单不完整”。
- CONTRACT-INPUT-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“guide、res、配置、规范、源码、测试和历史报告”已经得到验证。
- CONTRACT-INPUT-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-INPUT-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-INPUT-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-INPUT-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 03. CONTRACT-INVENTORY-001：对象清点遗漏
- CONTRACT-INVENTORY-001检查对象：声明、注册、实现、绑定、测试和产物的双向清单。
- CONTRACT-INVENTORY-001风险说明：如果该规则失败，可能出现“只从单一入口向下检查造成孤立项漏检”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-INVENTORY-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-INVENTORY-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-INVENTORY-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-INVENTORY-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“只从单一入口向下检查造成孤立项漏检”。
- CONTRACT-INVENTORY-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-INVENTORY-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“对象清点遗漏”。
- CONTRACT-INVENTORY-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“声明、注册、实现、绑定、测试和产物的双向清单”已经得到验证。
- CONTRACT-INVENTORY-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-INVENTORY-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-INVENTORY-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-INVENTORY-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 04. CONTRACT-EVIDENCE-001：证据无法定位
- CONTRACT-EVIDENCE-001检查对象：文件、字段、行号、命令、返回码和内容摘要。
- CONTRACT-EVIDENCE-001风险说明：如果该规则失败，可能出现“只写主观判断或模糊路径”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-EVIDENCE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-EVIDENCE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-EVIDENCE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-EVIDENCE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“只写主观判断或模糊路径”。
- CONTRACT-EVIDENCE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-EVIDENCE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“证据无法定位”。
- CONTRACT-EVIDENCE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“文件、字段、行号、命令、返回码和内容摘要”已经得到验证。
- CONTRACT-EVIDENCE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-EVIDENCE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-EVIDENCE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-EVIDENCE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 05. CONTRACT-EVIDENCE-002：证据已经过期
- CONTRACT-EVIDENCE-002检查对象：报告目标版本和被引用文件指纹。
- CONTRACT-EVIDENCE-002风险说明：如果该规则失败，可能出现“代码变化后继续复用旧证据”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-EVIDENCE-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-EVIDENCE-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-EVIDENCE-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-EVIDENCE-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“代码变化后继续复用旧证据”。
- CONTRACT-EVIDENCE-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-EVIDENCE-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“证据已经过期”。
- CONTRACT-EVIDENCE-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“报告目标版本和被引用文件指纹”已经得到验证。
- CONTRACT-EVIDENCE-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-EVIDENCE-002默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-EVIDENCE-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-EVIDENCE-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 06. CONTRACT-CONFIDENCE-001：猜测被写成事实
- CONTRACT-CONFIDENCE-001检查对象：confirmed、probable、suspected 的使用。
- CONTRACT-CONFIDENCE-001风险说明：如果该规则失败，可能出现“未复现问题却标为 confirmed”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-CONFIDENCE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-CONFIDENCE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-CONFIDENCE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-CONFIDENCE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“未复现问题却标为 confirmed”。
- CONTRACT-CONFIDENCE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-CONFIDENCE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“猜测被写成事实”。
- CONTRACT-CONFIDENCE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“confirmed、probable、suspected 的使用”已经得到验证。
- CONTRACT-CONFIDENCE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-CONFIDENCE-001默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-CONFIDENCE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-CONFIDENCE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 07. CONTRACT-SEVERITY-001：阻塞运行风险低估
- CONTRACT-SEVERITY-001检查对象：启动、配置解析、死锁、无限重试和破坏性行为。
- CONTRACT-SEVERITY-001风险说明：如果该规则失败，可能出现“导致无法运行的问题未标 critical”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-SEVERITY-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-SEVERITY-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-SEVERITY-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-SEVERITY-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“导致无法运行的问题未标 critical”。
- CONTRACT-SEVERITY-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-SEVERITY-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“阻塞运行风险低估”。
- CONTRACT-SEVERITY-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“启动、配置解析、死锁、无限重试和破坏性行为”已经得到验证。
- CONTRACT-SEVERITY-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-SEVERITY-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-SEVERITY-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-SEVERITY-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 08. CONTRACT-SEVERITY-002：语义欺骗风险低估
- CONTRACT-SEVERITY-002检查对象：核心需求、真实产物和完成声明。
- CONTRACT-SEVERITY-002风险说明：如果该规则失败，可能出现“核心需求未实现却标为低风险”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-SEVERITY-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-SEVERITY-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-SEVERITY-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-SEVERITY-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“核心需求未实现却标为低风险”。
- CONTRACT-SEVERITY-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-SEVERITY-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“语义欺骗风险低估”。
- CONTRACT-SEVERITY-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“核心需求、真实产物和完成声明”已经得到验证。
- CONTRACT-SEVERITY-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-SEVERITY-002默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-SEVERITY-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-SEVERITY-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 09. CONTRACT-SEVERITY-003：一般缺陷风险夸大
- CONTRACT-SEVERITY-003检查对象：可恢复契约问题和非关键兼容性。
- CONTRACT-SEVERITY-003风险说明：如果该规则失败，可能出现“把不影响正确性的风格问题标 high”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-SEVERITY-003使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-SEVERITY-003操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-SEVERITY-003操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-SEVERITY-003通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“把不影响正确性的风格问题标 high”。
- CONTRACT-SEVERITY-003失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-SEVERITY-003正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“一般缺陷风险夸大”。
- CONTRACT-SEVERITY-003常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“可恢复契约问题和非关键兼容性”已经得到验证。
- CONTRACT-SEVERITY-003证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-SEVERITY-003默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-SEVERITY-003误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-SEVERITY-003修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 10. CONTRACT-STATUS-001：报告状态与发现冲突
- CONTRACT-STATUS-001检查对象：checks、findings、severity 和终态。
- CONTRACT-STATUS-001风险说明：如果该规则失败，可能出现“存在 critical/high 却写 passed”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-STATUS-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-STATUS-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-STATUS-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-STATUS-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“存在 critical/high 却写 passed”。
- CONTRACT-STATUS-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-STATUS-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“报告状态与发现冲突”。
- CONTRACT-STATUS-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“checks、findings、severity 和终态”已经得到验证。
- CONTRACT-STATUS-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-STATUS-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-STATUS-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-STATUS-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 11. CONTRACT-CHECK-001：必检规则缺失
- CONTRACT-CHECK-001检查对象：对应评估类型的 REQUIRED_CHECK_IDS。
- CONTRACT-CHECK-001风险说明：如果该规则失败，可能出现“跳过规则仍提交完整报告”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-CHECK-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-CHECK-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-CHECK-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-CHECK-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“跳过规则仍提交完整报告”。
- CONTRACT-CHECK-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-CHECK-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“必检规则缺失”。
- CONTRACT-CHECK-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“对应评估类型的 REQUIRED_CHECK_IDS”已经得到验证。
- CONTRACT-CHECK-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-CHECK-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-CHECK-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-CHECK-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 12. CONTRACT-CHECK-002：检查记录空泛
- CONTRACT-CHECK-002检查对象：check summary 和 evidence。
- CONTRACT-CHECK-002风险说明：如果该规则失败，可能出现“写已检查但没有说明对象与结果”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-CHECK-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-CHECK-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-CHECK-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-CHECK-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“写已检查但没有说明对象与结果”。
- CONTRACT-CHECK-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-CHECK-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“检查记录空泛”。
- CONTRACT-CHECK-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“check summary 和 evidence”已经得到验证。
- CONTRACT-CHECK-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-CHECK-002默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-CHECK-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-CHECK-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 13. CONTRACT-FINDING-001：发现字段不完整
- CONTRACT-FINDING-001检查对象：expected、actual、impact、recommendation 和 repro。
- CONTRACT-FINDING-001风险说明：如果该规则失败，可能出现“无法理解期望与实际差异”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-FINDING-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-FINDING-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-FINDING-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-FINDING-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“无法理解期望与实际差异”。
- CONTRACT-FINDING-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-FINDING-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“发现字段不完整”。
- CONTRACT-FINDING-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“expected、actual、impact、recommendation 和 repro”已经得到验证。
- CONTRACT-FINDING-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-FINDING-001默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-FINDING-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-FINDING-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 14. CONTRACT-SEMANTIC-001：只审语法不审需求
- CONTRACT-SEMANTIC-001检查对象：用户需求到阶段、工具、Checker、产物的追踪。
- CONTRACT-SEMANTIC-001风险说明：如果该规则失败，可能出现“文件合法但功能并未实现”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-SEMANTIC-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-SEMANTIC-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-SEMANTIC-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-SEMANTIC-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“文件合法但功能并未实现”。
- CONTRACT-SEMANTIC-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-SEMANTIC-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“只审语法不审需求”。
- CONTRACT-SEMANTIC-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“用户需求到阶段、工具、Checker、产物的追踪”已经得到验证。
- CONTRACT-SEMANTIC-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-SEMANTIC-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-SEMANTIC-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-SEMANTIC-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 15. CONTRACT-TRUTH-001：伪造完成未识别
- CONTRACT-TRUTH-001检查对象：随机值、固定成功、空模板和永真断言。
- CONTRACT-TRUTH-001风险说明：如果该规则失败，可能出现“无真实工作仍宣称完成”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-TRUTH-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-TRUTH-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-TRUTH-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-TRUTH-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“无真实工作仍宣称完成”。
- CONTRACT-TRUTH-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-TRUTH-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“伪造完成未识别”。
- CONTRACT-TRUTH-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“随机值、固定成功、空模板和永真断言”已经得到验证。
- CONTRACT-TRUTH-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-TRUTH-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-TRUTH-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-TRUTH-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 16. CONTRACT-CHALLENGE-001：缺少反证审查
- CONTRACT-CHALLENGE-001检查对象：每个候选 finding 的替代解释和复核。
- CONTRACT-CHALLENGE-001风险说明：如果该规则失败，可能出现“把合法架构差异当作缺陷”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-CHALLENGE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-CHALLENGE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-CHALLENGE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-CHALLENGE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“把合法架构差异当作缺陷”。
- CONTRACT-CHALLENGE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-CHALLENGE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“缺少反证审查”。
- CONTRACT-CHALLENGE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“每个候选 finding 的替代解释和复核”已经得到验证。
- CONTRACT-CHALLENGE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-CHALLENGE-001默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-CHALLENGE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-CHALLENGE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 17. CONTRACT-FALSEPOS-001：搜索片段造成误报
- CONTRACT-FALSEPOS-001检查对象：完整源码上下文与实际数据流。
- CONTRACT-FALSEPOS-001风险说明：如果该规则失败，可能出现“只看关键词就推断行为”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-FALSEPOS-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-FALSEPOS-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-FALSEPOS-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-FALSEPOS-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“只看关键词就推断行为”。
- CONTRACT-FALSEPOS-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-FALSEPOS-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“搜索片段造成误报”。
- CONTRACT-FALSEPOS-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“完整源码上下文与实际数据流”已经得到验证。
- CONTRACT-FALSEPOS-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-FALSEPOS-001默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-FALSEPOS-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-FALSEPOS-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 18. CONTRACT-FALSENEG-001：正例替代拒错测试
- CONTRACT-FALSENEG-001检查对象：错误、缺失、空值、边界和恶意输入。
- CONTRACT-FALSENEG-001风险说明：如果该规则失败，可能出现“只跑 happy path 就判定可靠”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-FALSENEG-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-FALSENEG-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-FALSENEG-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-FALSENEG-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“只跑 happy path 就判定可靠”。
- CONTRACT-FALSENEG-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-FALSENEG-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“正例替代拒错测试”。
- CONTRACT-FALSENEG-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“错误、缺失、空值、边界和恶意输入”已经得到验证。
- CONTRACT-FALSENEG-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-FALSENEG-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-FALSENEG-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-FALSENEG-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 19. CONTRACT-HISTORY-001：历史报告被覆盖
- CONTRACT-HISTORY-001检查对象：runs 追加语义和 latest_run_id。
- CONTRACT-HISTORY-001风险说明：如果该规则失败，可能出现“新评估删除旧运行记录”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-HISTORY-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-HISTORY-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-HISTORY-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-HISTORY-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“新评估删除旧运行记录”。
- CONTRACT-HISTORY-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-HISTORY-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“历史报告被覆盖”。
- CONTRACT-HISTORY-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“runs 追加语义和 latest_run_id”已经得到验证。
- CONTRACT-HISTORY-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-HISTORY-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-HISTORY-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-HISTORY-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 20. CONTRACT-JSON-001：结构化文件被直接编辑
- CONTRACT-JSON-001检查对象：StructuredJsonStore 与审计事件。
- CONTRACT-JSON-001风险说明：如果该规则失败，可能出现“Agent 用普通写文件工具修改 eval JSON”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-JSON-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-JSON-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-JSON-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-JSON-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“Agent 用普通写文件工具修改 eval JSON”。
- CONTRACT-JSON-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-JSON-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“结构化文件被直接编辑”。
- CONTRACT-JSON-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“StructuredJsonStore 与审计事件”已经得到验证。
- CONTRACT-JSON-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-JSON-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-JSON-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-JSON-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 21. CONTRACT-TEMP-001：临时文件越界
- CONTRACT-TEMP-001检查对象：tmp 下的日志、fixture、候选和缓存。
- CONTRACT-TEMP-001风险说明：如果该规则失败，可能出现“临时内容污染 wfgen、workflow 或 eval”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-TEMP-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-TEMP-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-TEMP-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-TEMP-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“临时内容污染 wfgen、workflow 或 eval”。
- CONTRACT-TEMP-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-TEMP-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“临时文件越界”。
- CONTRACT-TEMP-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“tmp 下的日志、fixture、候选和缓存”已经得到验证。
- CONTRACT-TEMP-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-TEMP-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-TEMP-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-TEMP-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 22. CONTRACT-RES-001：用户知识被修改
- CONTRACT-RES-001检查对象：res 只读约束。
- CONTRACT-RES-001风险说明：如果该规则失败，可能出现“评估 Agent 改写专业知识以迎合结果”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-RES-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-RES-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-RES-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-RES-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“评估 Agent 改写专业知识以迎合结果”。
- CONTRACT-RES-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-RES-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“用户知识被修改”。
- CONTRACT-RES-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“res 只读约束”已经得到验证。
- CONTRACT-RES-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-RES-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-RES-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-RES-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 23. CONTRACT-APPROVAL-001：未批准修改
- CONTRACT-APPROVAL-001检查对象：审批来源、决定和指纹。
- CONTRACT-APPROVAL-001风险说明：如果该规则失败，可能出现“开放 finding 被自动实施”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-APPROVAL-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-APPROVAL-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-APPROVAL-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-APPROVAL-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“开放 finding 被自动实施”。
- CONTRACT-APPROVAL-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-APPROVAL-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“未批准修改”。
- CONTRACT-APPROVAL-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“审批来源、决定和指纹”已经得到验证。
- CONTRACT-APPROVAL-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-APPROVAL-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-APPROVAL-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-APPROVAL-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 24. CONTRACT-APPROVAL-002：过期批准复用
- CONTRACT-APPROVAL-002检查对象：source fingerprint 和当前报告。
- CONTRACT-APPROVAL-002风险说明：如果该规则失败，可能出现“目标变化后仍使用旧批准”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-APPROVAL-002使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-APPROVAL-002操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-APPROVAL-002操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-APPROVAL-002通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“目标变化后仍使用旧批准”。
- CONTRACT-APPROVAL-002失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-APPROVAL-002正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“过期批准复用”。
- CONTRACT-APPROVAL-002常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“source fingerprint 和当前报告”已经得到验证。
- CONTRACT-APPROVAL-002证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-APPROVAL-002默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-APPROVAL-002误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-APPROVAL-002修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 25. CONTRACT-BLOCK-001：证据不足仍给结论
- CONTRACT-BLOCK-001检查对象：blocked 状态与缺失原因。
- CONTRACT-BLOCK-001风险说明：如果该规则失败，可能出现“环境不可用时猜测 passed 或 failed”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-BLOCK-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-BLOCK-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-BLOCK-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-BLOCK-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“环境不可用时猜测 passed 或 failed”。
- CONTRACT-BLOCK-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-BLOCK-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“证据不足仍给结论”。
- CONTRACT-BLOCK-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“blocked 状态与缺失原因”已经得到验证。
- CONTRACT-BLOCK-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-BLOCK-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-BLOCK-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-BLOCK-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 26. CONTRACT-REPRO-001：复现步骤不可执行
- CONTRACT-REPRO-001检查对象：受控命令、输入和预期输出。
- CONTRACT-REPRO-001风险说明：如果该规则失败，可能出现“建议无法被下一位开发者验证”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-REPRO-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-REPRO-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-REPRO-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-REPRO-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“建议无法被下一位开发者验证”。
- CONTRACT-REPRO-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-REPRO-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“复现步骤不可执行”。
- CONTRACT-REPRO-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“受控命令、输入和预期输出”已经得到验证。
- CONTRACT-REPRO-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-REPRO-001默认严重程度：medium；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-REPRO-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-REPRO-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 27. CONTRACT-SECURITY-001：敏感信息进入报告
- CONTRACT-SECURITY-001检查对象：令牌、代理凭据、主机路径和用户数据。
- CONTRACT-SECURITY-001风险说明：如果该规则失败，可能出现“证据原样泄漏秘密”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-SECURITY-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-SECURITY-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-SECURITY-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-SECURITY-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“证据原样泄漏秘密”。
- CONTRACT-SECURITY-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-SECURITY-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“敏感信息进入报告”。
- CONTRACT-SECURITY-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“令牌、代理凭据、主机路径和用户数据”已经得到验证。
- CONTRACT-SECURITY-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-SECURITY-001默认严重程度：critical；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-SECURITY-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-SECURITY-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

### 28. CONTRACT-CLOSURE-001：跨阶段问题无人负责
- CONTRACT-CLOSURE-001检查对象：专项报告、summary、审批和增量复评。
- CONTRACT-CLOSURE-001风险说明：如果该规则失败，可能出现“问题在工作流间丢失”，评估者必须分析它对启动、进度、产物和用户语义的真实影响。
- CONTRACT-CLOSURE-001使用工具：优先使用YAML/JSON解析器、Python AST、受控静态审计工具和EvaluationCommandRunner；禁止用模糊关键词搜索代替结构化检查。
- CONTRACT-CLOSURE-001操作步骤一：从中心规划或用户需求定位声明，再向配置绑定、源码实现、测试和实际产物正向追踪。
- CONTRACT-CLOSURE-001操作步骤二：从最终产物或运行入口反向追踪到生产者，确认没有孤立实现、隐式假设或未声明依赖。
- CONTRACT-CLOSURE-001通过条件：声明、实现、调用、产物与验证相互一致，并有独立证据证明不会发生“问题在工作流间丢失”。
- CONTRACT-CLOSURE-001失败条件：发现确定矛盾、最小反例可复现，或者关键证据缺失到无法证明工作流可正确完成。
- CONTRACT-CLOSURE-001正确示例：报告列出精确文件和字段、预期行为、实际结果、受控命令返回码，并解释为什么满足“跨阶段问题无人负责”。
- CONTRACT-CLOSURE-001常见错误示例：仅写“看起来正常”或只引用搜索片段；这种记录不能证明“专项报告、summary、审批和增量复评”已经得到验证。
- CONTRACT-CLOSURE-001证据要求：至少给出一个可定位源码或配置证据；涉及行为时再给出独立fixture、命令结果或产物内容证据。
- CONTRACT-CLOSURE-001默认严重程度：high；若会导致无法启动、卡死、破坏或假成功，升级为critical；若证据不足则标blocked或suspected。
- CONTRACT-CLOSURE-001误报排除：检查框架允许的适配器、路径归一化、明确的顺序refinement和用户声明的支持边界，不得把架构偏好当缺陷。
- CONTRACT-CLOSURE-001修复方向：指出最小责任模块、需要同步的规范/实现/测试/文档以及复评规则，不在评估阶段直接代替工作流修复。

## 报告提交前复核
- 重新计算强制规则ID集合，缺一项都不能提交为通过。
- 对每条高危发现执行反证，并确认严重程度理由与真实影响一致。
- 检查报告状态是否由checks和findings推导，而不是由评估者主观选择。
- 检查所有临时文件位于tmp，所有结构化状态由受控工具更新。
- 检查用户需求中的每个动词和交付物都有明确评估结论。
