
# PTW 场景与 RTL 分析的完整记录示例

## 示例范围与生成职责

下面是参考 PTW 场景改写的教学记录，路径、ID 和行号均为示例，不是可复用的签名证据。实际运行必须先独立检查当前项目的测试、文档、RTL 和 WaveInfo 结果，由 LLM 撰写下面的说明，再通过普通工具提交；不能复制示例推断 DUT 有相同缺陷。未执行的后续断言不能写成实际结果。

LLM 在 case_triage 生成模块级 dut_context，在 root_correlation 生成 affected_behavior、signal_explanations 和 causal_steps。渲染代码只使用结构化字段，校验来源与关联，不猜测模块功能，不根据模块名拼接解释。缺少模块资料时填写空 text/source_refs 和具体 unavailable_reason，页面显示缺口且交付状态 incomplete；不得用其他 DUT 的介绍填空。

## 完整索引

索引通过 UpdateReviewRecord(target_path="verification_review/analysis/review_index.json", draft_path=...) 提交。实际修改需保留活动索引的全部身份与路径字段；本例是一个独立的最小完整索引，不是覆盖已有索引的模板。

```json
{
  "schema": "bug_review.v9",
  "record_type": "index",
  "workspace": {
    "name": "example_PTW"
  },
  "source_files": {
    "readme": "example_PTW/README.md"
  },
  "dut_context": {
    "text": "PTW 为地址转换读取页表项，并向上游返回转换结果。此介绍只覆盖当前项目文档明确描述的职责。",
    "source_refs": [
      "example_PTW/README.md:1-8"
    ]
  },
  "stage_status": {
    "case_triage": "pending"
  },
  "bug_order": [
    "BG-BITMAP-GATE"
  ],
  "bugs": {
    "BG-BITMAP-GATE": {
      "origin": "reported",
      "case_ids": [
        "tests/test_bitmap.py::test_disabled"
      ]
    }
  },
  "cases": {
    "tests/test_bitmap.py::test_disabled": {
      "replay_target": "tests/test_bitmap.py::test_disabled",
      "waveform_test_case_name": "tests/test_bitmap.py::test_disabled",
      "record_path": "cases/disabled.json"
    }
  }
}
```

## 完整现象记录

该记录需对应自己的 CaseRecord：其中 scenario_steps 保留准备和刺激的完整顺序、精确 execution_id 及 reached/failed/not_reached；events 中 bitmap-valid-rise 必须是自身签名收据支持的 first_deviation，包含原始时间、完整信号和 raw_value。完整 CaseRecord 字段示例见 Guide_Doc/bug_review_writing.md。这里不虚构 receipt 或 viewer URL。

配置名 BME、CMODE 是测试 API 的参数，解释时给出其到 io_csr_mbmc_BME、io_csr_mbmc_CMODE 的来源映射，不能当作波形信号。含义以当前 RTL 的表达式为限，不自行扩展缩写的标准含义；Auto_clkgate 等原名保持原文。signal_path 只有在该现象自己的签名信号中存在时才能填写。

```json
{
  "schema": "bug_review.v9",
  "record_type": "bug",
  "bug_id": "BG-BITMAP-GATE",
  "case_ids": [
    "tests/test_bitmap.py::test_disabled"
  ],
  "phenomenon": {
    "scenario": {
      "summary": "bitmap_enable=0 时，已接收的请求仍要求进入 bitmap 分支。",
      "conditions": [
        "io_csr_mbmc_BME=0、io_csr_mbmc_CMODE=0，因此 bitmap_enable=0。",
        "io_req_bits_bitmapCheck_jmp_bitmap_check=1；io_req_bits_req_info_s2xlate 不为 2。",
        "io_bitmap_req_ready=0，只检查请求是否被提出，不声称 bitmap 接收方已接受。"
      ],
      "source_refs": [
        "unity_test/tests/test_bitmap.py:40-63"
      ]
    },
    "spec_expected": {
      "summary": "bitmap 功能关闭时，不应提出 bitmap 请求；io_bitmap_req_valid 应保持 0。",
      "source_refs": [
        "unity_test/example_PTW_functions_and_checks.md:429-436"
      ]
    },
    "actual": {
      "summary": "首个异常时刻 io_bitmap_req_valid=1。",
      "first_deviation": "s_bitmap_check 由 1 清为 0，同时 io_bitmap_req_valid 上升。",
      "window": "签名窗口 0–19，首个异常位于原始波形时间 19。"
    },
    "bug_root_cause": "bitmap 请求有效条件没有受 bitmap_enable 约束。",
    "signal_explanations": [
      {
        "rtl_name": "bitmap_enable",
        "test_name": "config_mbmc(BME=0, CMODE=0)",
        "meaning": "当前 RTL 的 bitmap 功能允许条件，等于 io_csr_mbmc_BME & ~io_csr_mbmc_CMODE。",
        "source_refs": [
          "example_PTW_RTL/example_PTW.sv:484"
        ]
      },
      {
        "rtl_name": "io_bitmap_req_valid",
        "meaning": "DUT 向 bitmap 接收方提出请求；是否被接受还需同时检查 io_bitmap_req_ready。",
        "signal_path": "TOP.example_PTW.io_bitmap_req_valid",
        "source_refs": [
          "example_PTW_RTL/example_PTW.sv:1976"
        ]
      }
    ]
  },
  "decision": {
    "verdict": "confirmed",
    "review_confidence": 0.9,
    "root_id": "ROOT-BITMAP-GATE",
    "rationale": "自身首个异常、项目检查点和 RTL 传播一致；此处仅演示记录格式。",
    "spec_ref": "unity_test/example_PTW_functions_and_checks.md:429-436",
    "rtl_ref": "example_PTW_RTL/example_PTW.sv:1976",
    "first_error": "bitmap 请求有效条件没有受 bitmap_enable 约束。",
    "causal_chain": "请求进入 bitmap 分支 -> s_bitmap_check 清零 -> io_bitmap_req_valid 置一。"
  },
  "evidence_bindings": [
    {
      "evidence_id": "bitmap-first-deviation",
      "case_id": "tests/test_bitmap.py::test_disabled",
      "event_id": "bitmap-valid-rise",
      "role": "direct",
      "reason": "此现象自己的 first_deviation 事件。"
    }
  ]
}
```

## 完整根因记录

causal_steps 中没有 evidence_ids 的步骤标记为 RTL 推导，有 evidence_ids 的步骤引用本 ROOT 成员的实际事件。不能把同 ROOT 下另一个现象的事件写成当前现象的直接证据；每个 confirmed 现象仍需自身 direct 绑定。提交时将全部现象和根因放入 CreateDecisionDraft 产生的草稿，先 SubmitReviewDecisions(dry_run=true)，再正式提交。

```json
{
  "schema": "bug_review.v9",
  "record_type": "roots",
  "roots": [
    {
      "root_id": "ROOT-BITMAP-GATE",
      "title": "bitmap 请求缺少功能使能约束",
      "bug_ids": [
        "BG-BITMAP-GATE"
      ],
      "rtl_ref": "example_PTW_RTL/example_PTW.sv:1976",
      "first_error": "bitmap 请求有效条件没有受 bitmap_enable 约束。",
      "causal_chain": "请求进入 bitmap 分支 -> s_bitmap_check 清零 -> io_bitmap_req_valid 置一。",
      "primary_evidence_id": "bitmap-first-deviation",
      "affected_behavior": {
        "text": "bitmap 请求接口把需要检查的请求交给 bitmap 接收方。项目资料未完整说明 bitmap 的业务用途，此处仅解释有依据的接口约束。",
        "source_refs": [
          "unity_test/example_PTW_functions_and_checks.md:425-436"
        ]
      },
      "causal_steps": [
        {
          "summary": "请求的 jmp_bitmap_check 标志决定进入 bitmap 分支，该选择条件没有检查 bitmap_enable。",
          "rtl_refs": [
            "example_PTW_RTL/example_PTW.sv:498-499",
            "example_PTW_RTL/example_PTW.sv:818"
          ]
        },
        {
          "summary": "进入该分支后 s_bitmap_check 被清零。此处是 RTL 条件传播推导。",
          "rtl_refs": [
            "example_PTW_RTL/example_PTW.sv:1305-1307"
          ]
        },
        {
          "summary": "io_bitmap_req_valid=~s_bitmap_check；首个异常事件显示功能关闭时 valid 仍为 1。",
          "rtl_refs": [
            "example_PTW_RTL/example_PTW.sv:1976"
          ],
          "evidence_ids": [
            "bitmap-first-deviation"
          ]
        }
      ]
    }
  ]
}
```

## 默认正文与按需展开

正文依次是 DUT 功能概述、关联功能与验证目标、缺陷场景分析、异常与 RTL 根因分析。场景只列造成差异的配置、请求条件和相关接收条件。预期/实际表只比较功能关闭时 valid 的判定，不把复位或配置过程塞入表中。常规准备、完整 API 顺序和 case 路径放在展开内容。

右侧主波形使用 primary_evidence_id 指定的真实快照；入口用现象、case、事件类型、原始时间短标题。快照和下载按 receipt 去重。源码按实际类型归类，原分析原文只保留一个入口。原始波形时间 19 不能直接写成第 19 个时钟周期。ready=0 时 valid=1 只说明提出请求，不表示发生了握手或完成了检查。对照 case 若还改变了 vpn、source 等输入，不能宣称是严格单变量对照。
