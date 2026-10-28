
# 复核报告写作

## 内容边界

每条原声明保留标题、主张和来源。裁决首先回答是否成立，再解释实际观察、适用规格与测试正确性。原置信度不能替代复核证据。
真实性与根因定位分开；不要为了给出 ROOT 而猜测内部状态。根因 explanation 只定义一次，各声明通过 root_id 关联。

读者需要看到场景、预期与实际、执行来源、复核理由、缺口和下一步。型号、信号、配置值与精确 Case ID 保持原名。
历史结果必须标为 historical，新执行为 rerun。关闭波形时使用测试和日志证据，不写“缺波形所以未完成”这种没有具体调查内容的结论。
正文由 RenderBugReviewReport 生成，不手写 HTML、复制机器字段或编辑原报告。完整 JSON 记录示例见 Guide_Doc/analysis.md 的“完整记录示例”。

## 完整裁决提交示例

此示例对应 Guide_Doc/analysis.md 的完整未定记录。没有确认根因，所以 roots 为空。

```json
{
  "decisions": [
    {
      "claim_id": "B001",
      "verdict": "inconclusive",
      "reasoning": "The test was inspected; no actual execution can be independently checked.",
      "case_ids": [
        "tests/test_demo.py::test_timeout"
      ],
      "source_refs": [
        "inputs/tests/test_demo.py:1-8"
      ],
      "root_id": null,
      "remaining_gap": "Native DUT package and an execution report are absent.",
      "next_action": "Supply the matching runtime package and rerun the linked test.",
      "narrative": {
        "title": "Accepted request has no verified completion",
        "summary": "The original timeout claim cannot yet be independently reproduced.",
        "expected_behavior": "An accepted request completes according to the applicable interface contract; its timing bound is not established.",
        "trigger_steps": [
          "Issue the request described in the linked test.",
          "Wait for completion using the test timeout."
        ],
        "comparisons": [
          {
            "condition": "Accepted request",
            "expected": "Completion according to the applicable contract.",
            "actual": "No imported execution is available.",
            "source_refs": [
              "inputs/tests/test_demo.py:1-8"
            ]
          }
        ],
        "cause_analysis": "The internal cause is unlocated; source text alone cannot prove a DUT defect.",
        "impact": [
          "The reported timeout remains unverified."
        ],
        "scope": "No runtime execution or waveform observation is claimed."
      }
    }
  ],
  "roots": []
}
```

## 完整成稿示例

以下是该记录的完整可读内容顺序，页面标题和链接由工具生成。

```text
demo · Bug Review
原声明 / 关联测试 / 未定声明：1 / 1 / 1

B001 · Accepted request times out
裁决：未定
原声明：已接受请求未能完成。
原文来源：inputs/issues.md:3-5
复核分析：已检查完成断言，但无真实执行结果和独立时限规格，暂不能判定 DUT 违例。
证据来源：inputs/tests/test_demo.py:1-8
证据缺口：缺少匹配运行包和独立时限规格。
下一步：补充运行包及规格后，复跑关联 Case。
关联测试：tests/test_demo.py::test_timeout

测试详情
场景：发出请求，等待完成。
实际结果：尚无独立导入的执行结果。
测试正确性：断言检查完成状态，超时依据待补充。
驱动与采样：需要结合运行环境核对。
复跑阻塞：原生 demo 包缺失，需要匹配当前 Python 的运行包。

原始材料处理清单
inputs/issues.md：claims；已整理其中一条超时主张。
```

## 结构化正文

每条裁决的 narrative 包含 title、summary、expected_behavior、trigger_steps、comparisons、cause_analysis、impact、scope。comparisons 每行包含 condition、expected、actual、source_refs。先讲现象，再解释证据与机制；把观察到的影响与推测风险分开。next_action 必填，已确认项也应给出修复或验证方向。右侧证据来自 Case 的 failure_refs、spec_refs、rtl_refs 和实际执行，不把描述性文字填进引用字段。
