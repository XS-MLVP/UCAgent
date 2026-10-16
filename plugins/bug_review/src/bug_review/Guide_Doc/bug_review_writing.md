
# Bug Review 写作与原因分析

## 统一对象与报告结构

一个 ROOT 对应一个 Bug 详情页；其成员 BugRecord 是现象记录，现象关联精确 case 和执行证据。不要把根因、现象、场景标题、测试函数或一次执行当成同一种身份。

正文依次为“DUT 功能概述”“关联功能与验证目标”“缺陷场景分析”“异常与 RTL 根因分析”。由你阅读当前工作区材料生成概述和解释，再填写结构化记录；生成器不替你猜功能或根因。只默认解释缺陷相关条件及 RTL 传播，不逐个讲解完整 case/API 流程。准备条件不放进预期／实际判定表。右侧一个较大真实波形和关键依据，事件入口简短，收据和下载按快照去重；原报告与分析原文只在右侧按需查看。

## 页面所需的分析内容

- `case_triage`：由你读取 DUT／接口文档，在索引 `dut_context` 填写 `text`（不超过 400 字符）和 `source_refs`。说明模块处理什么输入、提供什么结果；材料不足时不要生成通用概述，填写具体 `unavailable_reason`。使用完整索引草稿和 `UpdateReviewRecord`，不改输入文档。
- `root_correlation`：在 ROOT 的 `affected_behavior` 解释本缺陷涉及的接口／功能，沿用相同的来源或缺口字段。填写至多 6 个 `causal_steps`，每步只写一个传播环节的 `summary`、真实 `rtl_refs`。`evidence_ids` 仅关联该 ROOT 成员已有的实际事件；没有时留空，页面将其作为静态 RTL 推导，不补造时刻。
- 成员现象的 `scenario.summary/conditions` 只保留会改变触发条件的操作。普通复位、API 等待和完整操作日志保存在 case 及 scenario.setup/stimulus，默认折叠。`spec_expected.summary` 与 `actual.summary` 分别给出行为预期和观测偏差，配置取值不冒充行为判定。
- `signal_explanations` 解释至少一个缺陷相关 RTL 原名及含义，填写 `rtl_name/meaning/source_refs`。测试别名写在 `test_name`；只有从该现象签名信号中核实的完整路径才能填写 `signal_path`。不把 API 字典字段、解码字段或日志变量当成独立 RTL 信号。
- 事件 `description` 只写观察事实，不拼入 BG ID、完整 case 路径或签名收据。时刻及所属 case 从自身事件派生；同一收据的多个事件共享下载入口。

完整的 DUT 概述、场景和 ROOT 传播记录示例见 `Guide_Doc/bug_review_example_ptw.md`。这些说明由 LLM 根据来源生成；代码只校验字段、引用和身份，不能自动证明自然语言因果解释正确。

## 如何写清楚

写出谁向谁发什么、这个命令完成什么功能、具体原名和值、顺序、等待条件，以及前一次事务的状态是否保留。`phase A` 不是协议状态，先解释它实际执行的动作。信号、寄存器、配置、字段、API 原名逐字保留，中文只解释含义。

不清楚：“开启自动门控后连续两次读出，phase B 不 work。”

改写：“将 `R_ErdecCfg` 的 `Auto_clkgate`（bit 13）置为 1；先发送 `RAID_CMD=2, R_TAG=0x31`，暂停消息接收后恢复；不复位 DUT，再发送 `RAID_CMD=2, R_TAG=0x33`，这次暂停数据接收。接收器记录称第二条输出消息仍带第一条标签。”

`Auto_clkgate=1` 不证明实际停钟。`R_TAG` 是从所属总线解码的字段，不是独立信号。测试接收器清理与 DUT 复位分别说明。未到达的步骤写 `not_reached`，不要描述为已经通过。每个 `scenario_steps` 项保存真实 `execution_id`；事件只引用自身执行下的步骤，baseline 与定向复跑的到达状态分别记录。

## 原因分析怎么建立

先独立核查测试有效性与 Spec 预期，再说明该执行实际观察到的偏差，最后把 RTL 首错、传播和外部结果连接起来。相同 RTL 行或相似超时不证明相同根因。根因的共性写在 ROOT，成员的输入、握手、失败位置与缺口写在自己的现象／case。

`ReviewEvent` 将波形观察与软件记录分开。波形事件保留精确执行、receipt、原始时间、全路径、有效条件和原始位串；软件记录引用它自己的保存文件与行段，不填写伪波形坐标。`EvidenceBinding.role=direct` 需要该现象自己的 `first_deviation` 波形事件；正常对照或最终断言不能代替它。ROOT 用 `primary_evidence_id` 显式选择一条主要预览，但不使其他现象自动获得证据。

静态预览最多显示六个真实信号。签名窗口较长时，预览自动截取事件前后各 64 个原始时间刻度，并与签名窗口取交集，保留局部窗口的每次跳变；图旁标出实际预览范围。点击仍打开原始签名窗口和同一快照，不改写收据或以删减跳变代替真实波形。

## 完整 case 与现象记录示例

以下是完整的 v9 结构示例。文件、执行 ID 和行号是教学示意；实际必须来自当前运行，不可复制为签名证据。由于只有断言记录，结果保持未定。

```json
{
  "schema": "bug_review.v9",
  "record_type": "case",
  "case_id": "tests/test_message.py::test_message",
  "bug_ids": [
    "MSG-OWNERSHIP"
  ],
  "replay": {
    "status": "failed",
    "invocation_success": false,
    "baseline_id": "example-baseline",
    "invocation_id": "example-execution",
    "report_node_id": "tests/test_message.py::test_message",
    "failure_phase": "",
    "reruns": [],
    "not_run_reason": "",
    "result": ""
  },
  "test_review": {
    "classification": "inconclusive",
    "correctness_confirmed": false,
    "exact_input": "",
    "specification_expected": "",
    "test_expected": "",
    "dut_actual": "",
    "driver_timing_review": "",
    "rationale": ""
  },
  "failure_analysis": {
    "category": "insufficient_evidence",
    "phase": "assertion",
    "scenario": {
      "summary": "不复位 DUT 连续提交两条读结果命令，分别暂停接收消息和数据。",
      "setup": [],
      "stimulus": [],
      "conditions": [],
      "source_refs": []
    },
    "spec_expected": {
      "summary": "输出消息应保留当前读命令的完整内容。",
      "requirement": "",
      "rtl_expectation": [],
      "source_refs": []
    },
    "test_expected": {
      "summary": "第二轮完整输出消息应等于第二条输入读命令。",
      "assertion": "assert omsg_b == msg_b",
      "completion_condition": [],
      "timeout": "",
      "source_refs": []
    },
    "actual": {
      "summary": "测试记录称第二轮仍收到第一条命令的标签。",
      "observations": [],
      "window": "",
      "first_deviation": "",
      "evidence_refs": []
    },
    "rationale": {
      "test_validity": "",
      "attribution_reason": "",
      "remaining_gap": "没有覆盖第二轮输出握手的波形；还需检查接收器行为和测试长度适用性。"
    },
    "unresolved": ""
  },
  "waveform": {
    "conclusion": "inconclusive",
    "receipt_id": "",
    "analysis_window": {},
    "signal_groups": {},
    "viewer_url": "",
    "alignment_evidence": "",
    "observed_behavior": "",
    "source_correlation": "",
    "diagnostic": ""
  },
  "additional_waveforms": [],
  "scenario_steps": [
    {
      "step_id": "read-1",
      "action": "RAID_CMD=2, R_TAG=0x31",
      "receiver_setting": "feh_raidd_cready=0，之后恢复为 1",
      "expected": "返回第一条命令的完整消息",
      "status": "reached",
      "source_refs": [
        "unity_test/tests/test_message.py:10-20"
      ],
      "execution_id": "example-execution"
    },
    {
      "step_id": "read-2",
      "action": "不复位 DUT，发送 RAID_CMD=2, R_TAG=0x33",
      "receiver_setting": "feh_raidd_cready=1, feh_raidd_wready=0",
      "expected": "返回第二条命令的完整消息",
      "status": "failed",
      "source_refs": [
        "unity_test/tests/test_message.py:21-30"
      ],
      "execution_id": "example-execution"
    }
  ],
  "events": [
    {
      "event_id": "assert-message",
      "execution_id": "example-execution",
      "step_id": "read-2",
      "kind": "assertion",
      "source_kind": "test_record",
      "source_ref": "verification_review/run/test_report/failure.txt:1-3",
      "description": "接收器记录称收到 R_TAG=0x31，完整消息一致性断言失败",
      "expected": "R_TAG=0x33",
      "condition": "",
      "receipt_id": "",
      "time": null,
      "signal_path": "",
      "raw_value": "",
      "fields": [],
      "rtl_refs": []
    }
  ]
}
```

```json
{
  "schema": "bug_review.v9",
  "record_type": "bug",
  "bug_id": "MSG-OWNERSHIP",
  "phenomenon": {
    "scenario": {
      "summary": "不复位 DUT 连续提交两条读结果命令，分别暂停接收消息和数据。",
      "setup": [],
      "stimulus": [],
      "conditions": [],
      "source_refs": []
    },
    "spec_expected": {
      "summary": "输出消息应保留当前读命令的完整内容。",
      "requirement": "",
      "rtl_expectation": [],
      "source_refs": []
    },
    "actual": {
      "summary": "测试记录称第二轮仍收到第一条命令的标签。",
      "observations": [],
      "window": "",
      "first_deviation": "",
      "evidence_refs": []
    },
    "bug_root_cause": ""
  },
  "case_ids": [
    "tests/test_message.py::test_message"
  ],
  "spec_refs": [],
  "rtl_refs": [],
  "decision": {
    "verdict": "inconclusive",
    "review_confidence": null,
    "rationale": "异常只有测试记录，缺少直接波形支持。",
    "root_id": null,
    "spec_ref": "",
    "rtl_ref": "",
    "first_error": "",
    "causal_chain": ""
  },
  "evidence_bindings": [
    {
      "evidence_id": "record-message",
      "case_id": "tests/test_message.py::test_message",
      "event_id": "assert-message",
      "role": "reported_only",
      "reason": "仅引用该次执行的断言记录。",
      "remaining_gap": "没有覆盖第二轮输出握手的波形；还需检查接收器行为和测试长度适用性。"
    }
  ]
}
```

## 内容自查与工具

不打开源码，读者能否回答操作、预期、哪一步偏离、来源是什么，以及打开哪个快照在哪个时刻能看到？缺少回答时修订事实或标明缺口。中文解释不能替代实际名称。

以 `DescribeReviewSchema` 获取当前模型，用 `UpdateCaseRecords` 提交自己的步骤／事件，`CommitAttribution` 维护现象↔case，`SubmitReviewDecisions` 校验全部现象、证据和 ROOT 的一致修订。根因不明时保持 null ROOT，不能为了页面制造占位根因。缺口没有时使用空字符串。

进一步参见 `Guide_Doc/bug_review_example_rcmd.md`、`Guide_Doc/bug_review_example_monitor.md` 与 `Guide_Doc/bug_review_example_root.md`。


## 调查细节的展示边界

按 `Guide_Doc/bug_review_investigation.md` 填写 ROOT.investigation，复用本 ROOT 的事件及来源。正文保持既定四段；动态对象身份、约束、检测位置、替代解释及反证默认折叠到第 04 段。没有内部波形时明确哪些是静态推导，保留未排除解释和更早边界缺口。confirmed 不表示修复已通过，本次 Bug Review 不生成修复验收结论。
