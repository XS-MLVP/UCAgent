# 评估工作流紧凑执行契约

## 目的

本文件是 `eval_tools.yaml`、`eval_checkers.yaml`、`eval_flow.yaml`、`eval_env.yaml` 和
`eval_run.yaml` 唯一的运行时指导文档。它把评估工作拆成可独立取证的小单元，避免把完整
规则库、所有源码、所有规格和所有测试同时放进一次模型上下文。

`evaluation_contract.md` 与 `eval_*.md` 是维护者使用的详细规则目录。它们仍由
`EvaluationGuideCoverageChecker` 静态验证行数、规则 ID 和严重度定义，但运行 Agent 不得将
它们作为 `reference_files` 全文读取，也不得为了“完整性”重新枚举其内容。需要核对某个
规则时，只依据本文件中的检查 ID、静态审计证据和当前组件的直接契约；详细规则库由后续
维护者离线维护，不是每次运行都要重读的上下文负担。

## 共同边界

1. 评估只读：不得修改 `workflow/`、`res/` 或已有 eval JSON；报告只能通过
   `StructuredJsonStore` 写入，临时文件只能写入根级 `tmp/`。
2. 除 `eval_run` 外，禁止启动任何 UCAgent 子工作流。`eval_run` 每次只能启动用户请求的
   一个 `default` 或 `inc` 子流程，并在结束时停止它。
3. 先调用 `StaticEvaluationAudit`，读取其结构化 finding 和受检文件索引。审计没有 finding
   不等于其余检查自动通过；它只决定后续源码深读的优先顺序和范围。
4. 所有表述性文字使用中文；规则 ID、字段、路径、命令、类名、函数名和真实源码保持原文。
5. finding 必须有精确 path、location、expected、actual、severity_reason、confidence、
   requirement_refs 和结构化 evidence。无法证实的问题写为 `info/suspected`，不能猜测成
   high 或 critical。

## 上下文预算与批处理

1. 先读本文件、当前 report、对应 `res/<type>.json`、`res/common.json` 和静态审计 JSON；
   不在开始阶段读取详细规则库或业务源码树。
2. 从 `workflow_spec`、配置和审计结果得到组件索引后，每次只选择一个组件或一个紧密相关
   配置组。读取该组件的实现、对应 spec、注册/绑定和直接测试；取得证据后立刻将简短结论
   写入当前 report run，再进入下一个组件。
3. 完成的组件只在后续上下文保留：组件 ID、路径、SHA256 或版本、检查 ID、结论、finding ID
   与验证命令返回码。禁止重新粘贴其全文源码、测试输出或长报告。
4. 发现上下文接近限制时，先提交已完成组件的结构化证据并结束当前工具调用。下一轮从 report
   中读取摘要继续，不得重新读取已完成组件，不能用压缩后补读全部资料的方式恢复。
5. 同一事实最多读取两次：首次取证一次，提交 finding 前反证一次。第二次仍无法定位时记录
   证据不足，不得无限重读。

## 通用执行顺序

1. 通过 `StructuredJsonStore` 读取当前报告历史、公共资源和本类型资源；使用 `template`
   创建一个 contract_version=2 的运行记录。
2. 运行 `StaticEvaluationAudit`，将所有 critical/high finding 原样转入同名或相应的检查证据。
3. 建立轻量组件队列。队列项只包含组件名称、直接文件、关联检查 ID 和预期验证命令。
4. 按队列逐项取证、反证、写入 report。一个工具、Checker、配置文件或环境入口完成后不再
   保留其全文。
5. 执行允许的确定性命令；报告保存真实 command、argv、returncode、stdout_tail、stderr_tail。
6. 最后补齐本类型规定的十个 check。没有发现不是 `skipped` 的理由；每项必须说明审查对象、
   证据和结论。再调用 `StructuredJsonStore` 结束运行。

## 工具评估

工具队列按工具名建立。每个工具只读取：工具实现、对应 tool spec、注册位置、直接测试和
一个真实输入/输出例子。先验证存在与注册，再验证签名和错误行为，最后验证需求语义与路径
安全。可以用一次白名单测试取得批量 returncode，但失败 finding 必须回到对应工具的直接
文件取证。`TOOLS-INVENTORY`、`TOOLS-REGISTRATION`、`TOOLS-CONTRACT`、`TOOLS-POSITIVE`、
`TOOLS-NEGATIVE`、`TOOLS-OUTPUT`、`TOOLS-FAILURE`、`TOOLS-SAFETY`、`TOOLS-SEMANTICS` 和
`TOOLS-CHALLENGE` 都必须出现在报告中。

## Checker 评估

Checker 队列按 Checker 名建立。每个 Checker 只读取：实现、对应 checker spec、阶段绑定、
正例和一个最相关反例 fixture。验证构造参数、`do_check`、docstring、正反判定、异常路径和
执行时机。不得默认相信 Checker 自己生成的 fixture，也不得把异常当作通过。报告必须含
`CHECKERS-INVENTORY`、`CHECKERS-REGISTRATION`、`CHECKERS-SIGNATURE`、`CHECKERS-POSITIVE`、
`CHECKERS-NEGATIVE`、`CHECKERS-BINDING`、`CHECKERS-TIMING`、`CHECKERS-SEMANTICS`、
`CHECKERS-FALSE-RESULT` 和 `CHECKERS-CHALLENGE`。

## 流程评估

流程队列按配置文件与中心 spec 的同名阶段建立。先使用静态审计验证 YAML、占位符、路径和
阶段图；只在审计或阶段对比需要时读取相应配置段、workflow_spec 段、绑定工具/Checker 的
直接声明和相关文档片段。严禁为一个路径问题读取全部工具源码。报告必须含 `FLOW-PARSE`、
`FLOW-PLACEHOLDERS`、`FLOW-PATHS`、`FLOW-DAG`、`FLOW-PROVENANCE`、`FLOW-TOOLS`、
`FLOW-CHECKERS`、`FLOW-OUTPUTS`、`FLOW-RETRY`、`FLOW-DOCUMENTATION`、`FLOW-SEMANTICS` 和
`FLOW-CHALLENGE`。

## 环境评估

环境队列固定为 Makefile、setup.py、ucagent_setup.sh、requirements.txt、install.py 和迁移
清单。每项只读取自身和直接引用的配置/文档，白名单命令一次执行后保存真实返回码。检查
可移植性、临时目录边界、清理保护、路径和依赖，不能为了验证而运行子工作流。报告必须含
`ENV-MAKE`、`ENV-SETUP`、`ENV-SHELL`、`ENV-DEPENDENCIES`、`ENV-TOOLCHAIN`、`ENV-PATHS`、
`ENV-TEMP`、`ENV-CLEAN`、`ENV-PORTABILITY`、`ENV-SECRETS` 和 `ENV-CHALLENGE`。

## 运行评估

先读取 run_request、静态审计和运行报告；只启动请求指定的一个模式。监控只保存阶段索引、
失败次数、活跃时间、关键产物变化和终端输出尾部，不把完整终端日志重复放入上下文。相同
失败达到阈值、无进度或超时后停止会话并记录证据。报告必须含 `RUN-PREFLIGHT`、`RUN-START`、
`RUN-PROGRESS`、`RUN-RETRY`、`RUN-STALL`、`RUN-TIMEOUT`、`RUN-CLEANUP`、`RUN-OUTPUTS`、
`RUN-RESULT`、`RUN-SEMANTICS` 和 `RUN-CHALLENGE`。

## 严重度与结束条件

导致 UCAgent、构建、部署或必要检查无法运行，或会造成数据破坏、越权修改、假成功的为
critical；违反用户硬需求、关键语义、注册或绑定契约的为 high；可控的质量、维护或体验问题
为 medium/low；未证实猜测只能为 info。所有 critical/high finding 未消失时报告 status 必须
为 failed。评估完成只表示报告证据完整，不表示问题已修复；修复必须经过用户批准并由增量
工作流处理。
