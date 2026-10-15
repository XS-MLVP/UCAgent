
# 一个 ROOT 下的多个现象与执行证据

## 关系与调查

下面是明确标为虚构的教学示例，不是已确认的实际 DUT Bug。`MSG-CONTINUOUS` 与 `MSG-WAKE` 分别描述连续事务和长空闲后的消息归属偏差；先分别核查其协议、异常和首错，证实共同机制后，才放入一个 ROOT。两个现象可以共享同一 case 的不同事件，也可以使用不同 case。

## 完整 ROOT 记录

```json
{
  "schema": "bug_review.v9",
  "record_type": "roots",
  "roots": [
    {
      "root_id": "ROOT-EXAMPLE",
      "rtl_ref": "example_dut/control.v:10-15",
      "first_error": "有效事务到来时没有装载当前消息",
      "causal_chain": "缺少装载 -> 输出旧消息 -> 两个场景分别发生消息归属偏差",
      "bug_ids": [
        "MSG-CONTINUOUS",
        "MSG-WAKE"
      ],
      "title": "输出消息寄存器更新条件错误",
      "primary_evidence_id": "continuous-deviation",
      "affected_behavior": {
        "text": "消息接口向接收方返回当前事务的信息。",
        "source_refs": ["example_dut/README.md:1-5"]
      },
      "causal_steps": [
        {
          "summary": "事务有效时，装载条件没有覆盖当前请求。",
          "rtl_refs": ["example_dut/control.v:10-15"],
          "evidence_ids": []
        },
        {
          "summary": "连续事务场景中，输出保留上一事务的消息。",
          "rtl_refs": ["example_dut/control.v:10-15"],
          "evidence_ids": ["continuous-deviation"]
        }
      ]
    }
  ]
}
```

## 配套证据要求

`continuous-deviation` 必须是成员现象实际 `evidence_bindings` 的 ID，指向其自己的精确 case、执行和 first_deviation。`MSG-WAKE` 也需要自己的直接证据，不因为 ROOT 选了连续事务的预览便继承其标签值或时间。共享 receipt 仍只保存在 case 的中央 WaveReview，额外 receipt 保存在 additional_waveforms；各现象通过事件引用自己的观察。

正式提交前为全部现象填写完整 BugRecord（完整形状见 `Guide_Doc/bug_review_writing.md`），补充自身的 Spec、case 与因果支持并通过 `SubmitReviewDecisions`。此教学 ROOT 单独并不满足动态确认门禁。

## 页面

一个 ROOT 一个规范详情页，正文按现象分别解释目标、操作和实际偏差；右侧一个显式选择的主要预览，下方提供多个标明现象／case 的完整波形入口。现象 ID 定位到同一页内锚点。未确定 ROOT 的现象保留未定入口，不创建假的 ROOT。统计分别计算根因、现象与 case。
