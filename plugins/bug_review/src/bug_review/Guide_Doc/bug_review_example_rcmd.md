
# RCMD-MSG-LATCH：完整事务与证据缺口

## 验证目标

SCBD 通过 `scbd_raidd_cmsg` 发 `RAID_CMD=2`，要求 DEC 输出已计算的恢复结果。`raidd_feh_cmsg` 应返回当前读命令的完整 96 bit 消息，结果数据通过 `raidd_feh_wdata` 另行交付。消息被接收的条件是 `raidd_feh_cvalid && feh_raidd_cready`。

## 测试怎样操作

历史 `test_inf_outbp` 将 `R_ErdecCfg.Auto_clkgate`（bit 13）与 `CrcChkDis`（bit 18）设为 1。第一轮准备 P 数据、发送 `R_TAG=0x31`，将 `feh_raidd_cready=0` 保持 30 个周期后恢复，数据正常接收；第二轮准备新的 P 数据、发送 `R_TAG=0x33`，消息正常接收、`feh_raidd_wready=0`。两轮之间不复位 DUT，仅清理接收器记录。`CW_DATA_CYC=8` 的规格适用性需要另行核查。

## 实际异常与原因分析

测试记录称第二轮 `omsg_b == msg_b` 失败，标签仍为 0x31。历史快照窗口 20–130 是第一轮正常对照，文件止于 167，只记录到第二条命令入队，没有第二轮输出握手。这不能证明内部 `slv_msg` 仍保持旧标签，也不能证明实际发生了停钟。

应先检查接收器记录是否与输出握手采样一致、测试长度是否适用，再取得第二轮输出及必要前史。沿真实 `rcmd_queue_out`、`slv_msg_lch`、`slv_msg` 的全层级变化调查是否装载了新消息。长空闲唤醒、双通道受阻分别使用自己的 case、到达点、异常与证据；共同机制成立后才归入同一 ROOT。

## 完整记录形状

下面将历史发现转化为教学用 v9 未定记录，ID、保存日志和行号是示意。它不是历史记录迁移或新签名证据。

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

测试事实与事件的完整配套结构见 `Guide_Doc/bug_review_writing.md`。原报告裁决与本次证据缺口分别保留，补证据产生新执行，不覆盖历史 receipt。
