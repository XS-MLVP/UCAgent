
# ROOT 调查：动态对象、首个约束违例与替代解释

本指南属于普通工作流；Skill 未启用时也必须遵守。全量 case 对账、原声明、现象及 ROOT 的关系保持不变。ROOT 是根因单元，case 是执行单元；某一 case 的最终断言不自动等于 RTL 首错。

## 先识别具体对象，再追踪偏差

1. 从自身 case 的请求接受、命令号、tag／ID、队列条目、返回消息或请求地址识别一个实际对象。使用该 DUT 的真实标识；没有 ID 时说明如何以握手和时序界定事务。不能只写“第二次”“phaseA”。配置、信号、字段和 API 名称逐字保留，例如 `Auto_clkgate`。
2. 写出该对象应满足的约束，引用实际 Spec／接口或 RTL 行段。准备、触发、第一次可见偏差和最终检测分开；`valid=1` 只说明请求被提出，只有协议定义的接受条件成立才能写已接收。API 返回的软件变量不是 RTL 信号。
3. 沿触发→状态→输出追踪，`causal_steps` 继续保存 RTL 推导，`evidence_ids` 只引用真实事件。未 dump 的内部组合项只能写静态推导。窗口不足时先明确要补哪个握手、对象身份或状态边界，不盲目延长窗口。
4. 至少检查一个替代解释：驱动／采样先后、接收器缓存、上一笔队列残留、reset、模型、构建或输入身份。没有反证时保留候选，不能靠经验写已排除。

## 根因记录的新增部分

`PrepareReviewInventory` 固定 `review_index.json.investigation_contract=first_violation.v1`。每个 ROOT 填写 `investigation`；不能删除或改写该契约来跳过调查。

- `invariant`：`text/source_refs`，描述应满足的关系，不能仅写模块用途。
- `objects[]`：`object_id` 是本 ROOT 内唯一阅读标识；`case_id` 和 `invocation_id` 逐字来自真实执行。`identity` 使用 `text/source_refs`，身份不足时用 `unavailable_reason` 指出缺失；`evidence_ids` 属于同一 case 和同一 invocation。基线和 rerun 分成不同对象记录，不能拼接成一次事务。
- `first_evidence_id`：本 ROOT 成员的 direct、first_deviation 证据，且只属于一个对象；`detection_evidence_id` 指向检测断言或最终偏差，尚无记录时留空，不制造事件。
- `earliest_status=located`：已按所述范围定位首错；若只看到输出或更早的对象／内部边界未观察，用 `earliest_observed` 并填写 `earlier_boundary_gap`。最早“观察到”不等于证明设计内最早“发生”。
- `alternatives[]`：填写 `explanation/status/basis/reasoning`；`status` 为 `ruled_out` 或 `unresolved`，`basis` 为 `observed/static_inference/unresolved`。动态观察引用自己的 `evidence_ids`，静态推导引用 `source_refs`；未排除项必须填写能区分解释的 `remaining_gap`。

所有证据 ID 复用现有 `evidence_bindings`，不另造收据。需要记录触发或检测时，先在对应 case.events 创建真实来源的事件，再通过其现象的 binding 关联。不能为填写字段重命名旧 invocation、手写 signed token 或冒充 WaveInfo 观察。

## 两个现有场景的方法边界

RCMD-MSG-LATCH：软件接收器拿到旧标签，但没有看到第二笔真实输出握手时，先区分第二笔请求是否被接受、接收器是否返回缓存记录、以及 DUT 输出是否已经有效。只观察到旧软件变量，不能据此确认第二笔 RTL 输出错误，也不能声称延长窗口必然解决。

PTW root41：沿请求接受→`s_bitmap_check` 更新→`io_bitmap_req_valid` 追踪；`bitmap_enable=0` 是相关条件。已有材料中 step 17 的 valid/ready 与内部 step 19 的请求信息采样需要分别说明。step 19 的 `io_bitmap_req_valid=1`、ready=0 表示提出 bitmap 请求，不能写成完成请求。未 dump 的 `_GEN*` 条件仍是 RTL 推导。这些是历史方法示例，不是本轮新 DUT 证据。

## 日志分诊只提供线索

每次 CaptureReplayReport 会保存原始 stdout、`diagnostics/log_triage/*.json` 和 `replay_summary.log_triage_refs`。线索按原始文件行号排序，保留 assertion、stuck、mismatch、ABORT 等全部候选，不用固定类型优先级替代更早错误。条数和长行摘要有上限，完整原文及行号仍可核对。

`source_line_order` 只代表输出文件顺序：pytest 可能重新组织不同 case 的 traceback／captured output，且单独 stderr 没有统一时序。先核对事件时刻和对象，再建立因果关系。脚本退出码、关键词、测试退出 0、指令数量或达到预算，都不能独立决定 DUT 裁决、复现成功或修复有效。

本流程不修改 RTL，也不执行修复验收。报告默认仍为四段，调查细节只在第 04 段按需展开；confirmed 表示原缺陷证据成立，修复验证明确为未执行。
