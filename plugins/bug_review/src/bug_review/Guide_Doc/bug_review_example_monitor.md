
# 监视器记录：软件统计与真实波形

## 验证目标与操作

完整解释输入命令、结果类型、接收条件和等待期限。以 ENC 监视器为例，`out_msgs` 是 Python 消息列表，`out_data_beats` 是数据拍列表；它们不是 dump 中的独立 RTL 信号。

## 观察与机制边界

“out_msgs 为空”说明软件没有记录消息，不能直接改写成 DUT 某端口一直为 0。核查监视器何时采样、何时清理、是否只在 valid && ready 时记录，再映射到经过核实的真实输出端口及实例路径。只有实际输出缺失或内容错误的动态证据，才能进一步解释对应 RTL 路径。

## 完整 case 示例

操作与软件映射来自历史 ENC 输入的 `unity_test/tests/test_raid_enc_top_cmd.py:924-949` 与 `unity_test/tests/raid_enc_top_api.py:577-601`。`out_msgs` 由 `StepRis` 回调在 `raide_scbe_cvalid && scbe_raide_cready` 时追加 `raide_scbe_cmsg`；`out_data_beats` 在 `raide_scbe_wvalid && scbe_raide_wready` 时记录数据，尾拍增加 `out_done_cnt`。`clear_outputs()` 清理三个 Python 记录，不复位 DUT。

下面的失败执行、执行 ID 和日志是明确标示的教学假设，不宣称历史 case 已产生该异常。Spec 及真实 dump 实例全路径尚需独立核验；软件事件没有伪信号、波形时间或 receipt。

```json
{
  "schema": "bug_review.v9",
  "record_type": "case",
  "case_id": "tests/test_raid_enc_top_cmd.py::test_msghs_ready",
  "bug_ids": [
    "OUTPUT-MISSING"
  ],
  "replay": {
    "status": "failed",
    "invocation_success": false,
    "baseline_id": "example-baseline",
    "invocation_id": "example-execution",
    "report_node_id": "tests/test_raid_enc_top_cmd.py::test_msghs_ready",
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
      "summary": "先用 cmd=0、w_tag=0xB2 发送 sid=28、offset=1、n=132 的数据帧；不等待帧完成便提交 cmd=2、w_tag=0xE3。",
      "setup": [],
      "stimulus": [],
      "conditions": [],
      "source_refs": [
        "unity_test/tests/test_raid_enc_top_cmd.py:924-949"
      ]
    },
    "spec_expected": {
      "summary": "本例尚未核验 ENC Spec 对该并发顺序的要求，不能将测试预期直接作为规格结论。",
      "requirement": "",
      "rtl_expectation": [],
      "source_refs": []
    },
    "test_expected": {
      "summary": "等待完成计数达到 1 后，out_msgs 中 w_tag=0xE3 的消息应恰好有一条。",
      "assertion": "assert len(msgs) == 1",
      "completion_condition": [],
      "timeout": "",
      "source_refs": [
        "unity_test/tests/test_raid_enc_top_cmd.py:946-949"
      ]
    },
    "actual": {
      "summary": "假设一次执行在消息数量断言处失败：软件记录不能单独证明 DUT 没有输出。",
      "observations": [],
      "window": "",
      "first_deviation": "",
      "evidence_refs": []
    },
    "rationale": {
      "test_validity": "",
      "attribution_reason": "",
      "remaining_gap": "教学假设，未提供实际执行；需核验 Spec、StepRis 采样、raide_scbe_cvalid && scbe_raide_cready 以及相应 raide_scbe_cmsg 波形。"
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
      "step_id": "wait-output",
      "action": "提交 cmd=2、w_tag=0xE3 并等待输出完成",
      "receiver_setting": "需核查 scbe_raide_cready 实际设置与采样",
      "expected": "out_msgs 中 w_tag=0xE3 的消息恰好一条",
      "status": "failed",
      "source_refs": [
        "unity_test/tests/test_raid_enc_top_cmd.py:942-949"
      ],
      "execution_id": "example-execution"
    }
  ],
  "events": [
    {
      "event_id": "monitor-timeout",
      "execution_id": "example-execution",
      "step_id": "wait-output",
      "kind": "assertion",
      "source_kind": "log",
      "source_ref": "verification_review/run/test_report/failure.txt:1-2",
      "description": "教学假设：按 unpack_msg(m)[\"w_tag\"] == 0xE3 筛选后，len(msgs) 不等于 1。",
      "expected": "筛选出的消息恰好一条",
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

原因分析继续按 `Guide_Doc/bug_review_writing.md`，并区分测试错误、规格歧义和 DUT 缺陷。
