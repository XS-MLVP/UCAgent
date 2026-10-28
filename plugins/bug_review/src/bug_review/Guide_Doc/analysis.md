
# 原 Bug 定向复核

## 目标与输入

核实原报告中的每条 Bug 声明，不修改原报告、测试、断言、fixture、参考模型、规格或 RTL。
原始文档可以是表格、列表或普通段落，不要求 BG 标签或固定文件名。原文根因和置信度都是待核实主张，不能替代独立证据。

输出目录由 `{OUT}` 指定：`inputs/` 保留原 UnityTest，`review.json` 统一保存模块背景、输入清单、原声明、逐 Case 执行与分析、裁决和根因，`runs/` 保存执行副本及真实报告，`report/` 保存最终可读报告。
来源引用使用 `inputs/文件:起始行-结束行`、`runs/文件:起始行-结束行`，外部规格及 RTL 使用工作区相对路径和行号。规格引用还需核验来源：原验证生成的基本信息、计划和检查点不能单独作为独立规格；通用规范库原文同样可作为独立规格；缺项目专用已审核 Spec 不构成自动判未定的理由。

所有 `source_refs/spec_refs/rtl_refs` 都必须是具体文件与行号，不能填说明文字；`inputs/`、`runs/` 前不加 `{OUT}/`。


## 通用规范依据

每次 PrepareReviewInputs 都将完整规范源文档及图片、表格等资源归档到 `{OUT}/inputs/review_standards/`，无需网络或 Skill。先读 `inputs/review_standards/catalog.json`，再按 entry_points 和关键词检索原文；不要整库阅读。

- **香山**：完整 kunminghu-v2r2a、kunminghu-v3 设计文档，以及 UnityChipForXiangShan 全部验证文档。按 DUT 版本、参数和端口选择适用分支，不能把其他版本的非阻塞行为套到当前阻塞端口。
- **RISC-V**：官方 GitHub 最新 main 的完整手册源码及配套资源；具体 revision、commit_time 和子模块版本固定在本次 catalog 中。按章节状态、版本和 DUT 支持的扩展选择规范性条款；未采用的草案、可选扩展、允许或未定义行为不构成违例。
- **Chisel**：完整文档及网站源目录。区分 DecoupledIO 和 IrrevocableIO；ready&&valid 表示传输，但不能给 DecoupledIO 额外套用背压时 valid/bits 必须保持的约束。

满足适用规范条款、合法测试及真实执行证据时，违反上述任一依据即可确认 Bug，不要求额外提供项目专用 Spec。引用示例：`inputs/review_standards/riscv/src/priv/supervisor.adoc:1-6`；用实际条款行号填写 spec_refs，在 specification_expected 和 reasoning 说明要求、适用范围及违例。规范原文是依据，catalog 仅用于来源与版本追溯。没有明确周期上限时，不能仅凭等待固定拍数确认永久无法完成；需要结合实现证明或其他充分证据。

只在版本/配置适用性、激励合法性或实际证据仍有具体缺口时判未定，写清待确认条款，不能笼统写“缺独立规格”。


## 常用规范导航

先定位与当前 Case 对应的条款，按行读取；不需要为每项重新遍历整库。

| 主题 | inputs/review_standards 下的原文 |
| --- | --- |
| ready/valid、DecoupledIO、IrrevocableIO | `chisel/docs/src/explanations/interfaces-and-connections.md`；FAQ 补充为 `chisel/docs/src/resources/faqs.md` |
| SFENCE.VMA 的 rs1/rs2、叶子/非叶子失效范围 | `riscv/src/priv/supervisor.adoc` |
| HFENCE.VVMA/GVMA、两阶段翻译 | `riscv/src/priv/hypervisor.adoc` |
| PageCache 查询、refill、bypass、HPTW、fence | `xiangshan-kunminghu-v2r2a/docs/zh/memblock/MMU/L2TLB/PageCache.md`；版本与配置适用性以本次 DUT 为准 |

后续同类 Case 可通过 ReviewContext 复用已完成项的公共驱动与采样审查，以及它指向的原始引用；已有复核结论不是独立规范。一个 Case 已有充分依据或明确的具体缺口时先用 UpdateCaseAnalysis 保存，不要等待全部 Case 的内部机制都研究完。

## 阶段与工具

1. **input_inventory**：PrepareReviewInputs 归档输入并列出文档。只盘点，不要求先收集测试或导入 DUT。
2. **claim_inventory**：阅读全部文档，以 SubmitReviewClaims 提交 context、声明及 source_reviews。每份文档说明 claims/no_claims/supporting/unreadable 及原因。重复声明合并时保留各处 source_refs、source_labels 和 mapping_reason；不同现象不凭标签相似就合并。
3. **targeted_review**：先 ReviewContext 查看已导入的执行；已有结果直接分析，仅对需要首次执行或补充真实缺失证据的项用 CollectReviewCases 得到精确 target 后 RunTestCases，再 CaptureReplayReport(invocation_id=返回ID)。默认仅关联用例；全量模式由启动选项明确启用。按原声明关联的一组 Case 检查公共测试 helper、fixture、API、独立规格及 RTL，再核对每项实际日志和差异，用 UpdateCaseAnalysis 批量更新分析；失败用 failure_refs 引用所选执行的报告或日志具体行。此阶段不调用波形工具。
4. **waveform_review**：默认跳过。开启后只对必要 Case 取证；不需要或无法取证的项用 SetWaveformReviewNote 说明。正常请求接受不等于首错，响应没有边沿不等于波形不可读。
5. **decisions**：SubmitReviewDecisions 为每个原声明填写 confirmed/refuted/inconclusive。同时填写 narrative（标题、摘要、正常行为、触发步骤、预期/实际对照、原因分析、影响、适用范围）与 next_action。共同根因只在 roots 定义一次，声明引用 root_id；内部根因未定位时可为 null。
6. **publish**：RenderBugReviewReport 生成报告，再 verify_only=true 核验页面和引用，Check 后记录日志并 Complete。

可用 Skill 只辅助执行；没有 `.ucagent/skills` 时用相同工具和本指南完成全部要求。无需创建草稿、计算哈希或手工设置完成状态。保存分析成功不等于阶段通过，用 ReviewWorkQueue 查询缺口，以 Check/Complete 验收。

## 取证与裁决

首次定向复跑可一次执行全部已关联用例。导入后用 ReviewWorkQueue(stage="targeted_review") 获取 next_group：同一原 Bug 下最多五个待完成 Case、执行指针、缺失字段，以及最多两个已完成项的 reusable_evidence。组内公共规格、helper、驱动和采样只审查一次；各项分别核实输入、参数、分支、预期和实际失败点。同组可以有不同分类，不能把一个失败推广成全部 Case 都存在 DUT 缺陷。

ReviewContext(claim_id="B001", offset=0, limit=5) 分页返回该组待处理项；pending_only=false 可查看已完成项。超过五项分批保存，已完成的重叠 Case 不在其他组重复分析；未关联的全量回归 Case 由队列作为无 claim_id 的一组返回。case_progress 由实际验收条件计算，无第二套进度表；next_group 为空时仍须处理其他诊断并 Check/Complete。

UpdateCaseAnalysis(cases=[...], shared={...}) 的 shared 仅限 specification_expected、test_validity、timing_review、source_refs、spec_refs、rtl_refs。非空的 Case 专属文本优先，引用去重合并；保存时展开进每个 Case 的 analysis，仍只有一张 review.json。分类、场景、实际结果、推理、selected_execution 和 failure_refs 各项单独填写，不能共享失败证据或自动复制结论。shared 不适用的 Case 单独分批提交。

公共分析及引用已经保存在组内完成项，不另建知识文件。reusable_evidence 只是已有分析摘要和原始引用导航，不能代替原始证据；范围不足时按原始行号补读，文本截断以 reasoning_truncated 标明。队列不返回波形、源码正文或完整执行历史；单项 ReviewContext 和 ReviewRefCheck 用于补足具体缺口。保存一批后再取队列，不要为每个字段反复查询进度。已有充分功能证据就保存；内部根因未定位不阻塞真实功能违例，确有缺口时记录具体 remaining_gap/next_action，不能仅因调查时间长就判未定。

ReviewContext(case_id=精确ID) 的 source_context 提供最多 60 行测试首尾片段与静态 helper 行号；用 ReviewRefCheck 批量读取相关 helper，避免反复搜索。片段截断或定义无法定位时按 diagnostics/next_action 检查原文件；静态引用不证明相关分支已经执行。

- Case 使用 `tests/文件.py::函数` 精确身份。参数化用例由 pytest 收集确认，不猜测参数 ID；工具扩展到实际子用例。
- 原报告缺测试关联时保留声明，case_ids 为空并说明 missing_information。不要为凑关联制造测试。
- 只有真实测试报告由 CaptureReplayReport 导入结果。历史报告用 historical_path 指向 inputs 下的 JSON；不得说成本次已复现。
- 无法运行时写明 replay_blocker，缺证据的分析用 unresolved，填写 remaining_gap 和 next_action。原报告自称失败不等于工具已导入真实失败。
- 确认 DUT 违例需要适用的独立规格、真实失败以及对输入合法性、断言、驱动与采样的审查。报告原文不能作为它自身的独立规格。
- 复合响应的总 valid 有效，不代表所有分支字段同时有意义。核对字段的选择条件及消费者使用条件；不能凭字段名称猜测，也不能把未选中分支的残留值或跨分支不一致直接判为 Bug。
- 排除需要实际反证：预期错误、非法激励或环境故障等。一次通过不能证明原 Bug 不存在。
- 已确认外部功能违例可以没有内部根因；不要将缺根因降格为“未观察到异常”。静态推导写 static_inference，实际波形支持才写 waveform_observation。
- 无波形时不要求 receipt、事件、波形说明或预览。未定项只需真实调查和明确缺口，不制造首错事件。

## 分组提交示例

以下为 UpdateCaseAnalysis 的完整调用参数示例。两个 Case 使用相同驱动和采样方法，但逐项记录执行、失败位置与推理。实际引用必须来自本次归档与执行；有适用规范时还需填写具体条款和 specification_expected。

```json
{
  "shared": {
    "test_validity": "Both tests use the same request helper; its payload setup still needs independent verification.",
    "timing_review": "The shared response sampler was inspected; the launch-edge ordering remains unverified.",
    "source_refs": ["inputs/tests/helpers.py:1-20"]
  },
  "cases": [
    {
      "case_id": "tests/test_demo.py::test_timeout_a",
      "analysis": {
        "category": "unresolved",
        "scenario": "Request A waits for completion.",
        "test_expected": "Completion before the test timeout.",
        "actual": "The imported execution records a timeout for A.",
        "reasoning": "The timeout is real; payload setup and the applicable latency bound remain unchecked.",
        "source_refs": ["inputs/tests/test_demo.py:1-8"],
        "selected_execution": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "failure_refs": ["runs/reports/invocations/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/stdout.log:1-3"],
        "remaining_gap": "Verify A's payload and the applicable completion requirement.",
        "next_action": "Inspect the helper setup and the original timing requirement for A."
      }
    },
    {
      "case_id": "tests/test_demo.py::test_timeout_b",
      "analysis": {
        "category": "unresolved",
        "scenario": "Request B uses a different address and waits for completion.",
        "test_expected": "Completion before the test timeout.",
        "actual": "The imported execution records a timeout for B.",
        "reasoning": "B has its own timeout; A's failure does not prove the same mechanism for B.",
        "source_refs": ["inputs/tests/test_demo.py:10-18"],
        "selected_execution": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "failure_refs": ["runs/reports/invocations/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/stdout.log:5-7"],
        "remaining_gap": "Verify B's address applicability and latency requirement.",
        "next_action": "Inspect B's address setup and the original completion requirement."
      }
    }
  ]
}
```

ReviewRefCheck 每条引用最多返回 40 行、2000 字符，truncated=true 时缩小行范围补读。无需为共用条款或 helper 重复搜索整个文件。

## 可选波形工具

ReviewContext 返回精确 waveform_test_case_name；ReviewSignalCatalog 返回真实完整信号路径，供 WaveInfo signal_groups 使用。事件条件放在 pattern，不把表达式放进信号路径。
取得最终收据后调用 ApplyReceiptToCase(case_id, invocation_id, receipt_id, observation, alignment, source_refs)。只使用对应执行批次的波形；ApplyWaveformEvent 从真实快照读取指定时间的完整数值，不接受手填 raw_value。
日志周期与波形时间需按时钟和事务对齐。需要补跑时只运行缺失证据的精确 Case，并导入新 invocation；已有取证不重复运行。完整预览依赖实际波形文件，缺文件不应伪造曲线。

## 完整记录示例

以下展示一个未定声明的完整最终记录。原文只有超时主张，测试环境缺运行包，故报告保留具体阻塞而不制造失败或波形。路径是本示例输入文件；真实复核必须填写当前工作区实际来源。

`review.json`：

```json
{
  "schema_version": "bug_review.v11",
  "module": "demo",
  "options": {
    "waveform_enabled": false,
    "full_regression_enabled": false
  },
  "source_documents": [
    "inputs/issues.md"
  ],
  "source_reviews": [
    {
      "path": "inputs/issues.md",
      "disposition": "claims",
      "reason": "One timeout claim"
    }
  ],
  "input_gaps": [],
  "claims": [
    {
      "claim_id": "B001",
      "title": "Accepted request times out",
      "statement": "The original report says an accepted request never completes.",
      "source_refs": [
        "inputs/issues.md:3-5"
      ],
      "source_labels": [],
      "case_ids": [
        "tests/test_demo.py::test_timeout"
      ],
      "mapping_reason": "The original report names this exact test",
      "missing_information": ""
    }
  ],
  "claims_submitted": true,
  "cases": {
    "tests/test_demo.py::test_timeout": {
      "case_id": "tests/test_demo.py::test_timeout",
      "executions": [],
      "analysis": {
        "category": "unresolved",
        "scenario": "The test issues a request and waits for completion.",
        "specification_expected": "",
        "test_expected": "",
        "actual": "No independently imported execution is available.",
        "test_validity": "The assertion checks completion, but the applicable timeout requirement is missing.",
        "timing_review": "Driver sampling needs verification against the runtime environment.",
        "reasoning": "Source text alone cannot establish the reported failure.",
        "source_refs": [
          "inputs/tests/test_demo.py:1-8"
        ],
        "spec_refs": [],
        "rtl_refs": [],
        "remaining_gap": "Missing runtime and independent timing specification.",
        "next_action": "Provide runtime and specification; execute the exact test.",
        "selected_execution": "",
        "replay_blocker": "The native demo package is absent; provide a package matching this Python.",
        "failure_refs": []
      },
      "waveforms": [],
      "events": [],
      "waveform_note": "",
      "case_key": "C0001",
      "waveform_test_case_name": "tests/test_demo.py::test_timeout"
    }
  },
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
  "roots": [],
  "decisions_submitted": true,
  "context": {
    "description": "A request/response hardware module.",
    "scope": "Review only the original timeout claim; timeout applicability remains unverified.",
    "source_refs": [
      "inputs/issues.md:3-5"
    ]
  },
  "execution_issues": []
}
```

## 单表维护与页面生成

- claim_inventory 填写 context.description/scope，以及有依据的版本、配置、限制和来源。
- targeted_review 填写 cases 中的 analysis；failure_refs 必须指向 selected_execution 的实际报告或日志行。执行状态、报告路径、原始波形归属由 CaptureReplayReport 写入，不手填。环境中断单列 execution_issues，不冒充用例失败。
- waveform_review 仅在开启时补充签名观察及事件；关闭时仍可展示导入的原始波形下载与 Surfer 入口，明确未分析。
- decisions 补齐 narrative 和裁决，预期/实际对照可带 source_refs；未知原因和未执行的影响必须明确标注。
- publish 从 review.json 与引用文件生成模块列表、失败分类、Bug 双栏详情及 Case 证据页。无需额外页面草稿，不手改 HTML；改分析后重新提交裁决并渲染。
