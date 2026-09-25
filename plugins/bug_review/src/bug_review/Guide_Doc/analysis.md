
# Bug Review 分析指导

## 工作区与输入

每个输入工作区的原始路径记录在 `review_job.json` 的 `source_runs`。准备阶段不会整体复制输入工作区，只把 Markdown/HDL/line-map 文本、UnityTest cases 目录及共享 helper/fixture、按工作区约定可导入的 DUT 仿真 Python 包和运行库放入 Agent 工作区。报告目录、coverage、历史波形、二进制构建产物和 `.ucagent` 不复制。Spec 和 RTL 通过镜像路径直接阅读；JSON 始终记录其原始工作区相对路径。

输入报告在 `{OUT}/inputs/<workspace>/unity_test/<DUT>_bug_summary.md` 和 `{OUT}/inputs/<workspace>/unity_test/<DUT>_bug_analysis.md`。测试运行根为 `{OUT}/tests/<workspace>/unity_test/tests`。测试 target 相对于 `{OUT}/tests`，例如 `<workspace>/unity_test/tests/test_x.py::test_case`。只运行 JSON 中选定的确切 TC，不要运行与 Bug 声明无关的全量测试套件，也不要修改原始或复制的测试、fixture、Spec、RTL 或模型。

## 阶段与唯一产物

每个工作区只有一个权威文件 `{OUT}/workspaces/<workspace>/bug_review.json`，采用 `bug_review.v3`。五个阶段都更新这个 JSON；HTML 直接从它渲染，不创建另一个 report data JSON。每阶段更新完本阶段字段后，将 `stage_status.<stage>` 设为 `complete`，运行 Check，通过后记录阶段日志并 Complete。

Skill 可用时按 CurrentTips 读取当前阶段 Skill；Skill 不可用时按本指导和阶段任务完成同一 JSON 契约。专用 Skill 的路径分别为 `ext/bug_review/inventory-review`、`ext/bug_review/replay-review`、`ext/bug_review/waveform-review`、`ext/bug_review/evidence-correlation` 和 `ext/bug_review/report-publication`。只有启用 Skill 时才按 UCAgent 要求登记 Skill 使用证据。

## JSON 结构完整示例

以下示例展示单一工作区完整的 Bug、case、执行、测试正确性、WaveInfo 结果和根因结构。示例波形为未定结果，没有伪造收据。实际报告用源文件中的准确路径、行号、node ID 和工具返回值替换示例值。

```json
{
  "schema": "bug_review.v3",
  "workspace": {
    "name": "workspace_example_dut",
    "dut": "example_dut",
    "source_path": "/project/inputs/workspace_example_dut"
  },
  "source_files": {
    "bug_summary": "/project/inputs/workspace_example_dut/unity_test/example_dut_bug_summary.md",
    "bug_analysis": "/project/inputs/workspace_example_dut/unity_test/example_dut_bug_analysis.md"
  },
  "stage_status": {
    "inventory": "complete",
    "replay": "complete",
    "waveform": "complete",
    "correlate": "complete",
    "publish": "pending"
  },
  "suspected_bugs": [
    {
      "bug_id": "BUG-OUTPUT-HOLD",
      "origin": "reported",
      "bug_summary": {
        "summary_item_present": true,
        "raw": "| BUG-OUTPUT-HOLD | major | ... |",
        "text": "输出背压期间数据必须保持稳定。",
        "severity": "major",
        "check_points": ["FG-OUTPUT/FC-DATA/CK-HOLD"],
        "rtl_candidates": ["example_dut_RTL/output_ctrl.v:80-88"],
        "source": {
          "path": "unity_test/example_dut_bug_summary.md",
          "line": 12
        }
      },
      "reported_confidence": 0.8,
      "analysis_claims": [
        {
          "summary": "ready 拉低期间输出 data 发生变化。",
          "source": {
            "path": "unity_test/example_dut_bug_analysis.md",
            "line_start": 44,
            "line_end": 49
          }
        }
      ],
      "evidence": {
        "test_points": [
          {
            "ref": "unity_test/tests/test_example_dut_output.py::test_data_hold",
            "purpose": "检查输出背压时数据保持"
          }
        ],
        "check_points": ["FG-OUTPUT/FC-DATA/CK-HOLD"],
        "case_ids": ["unity_test/tests/test_example_dut_output.py::test_data_hold"],
        "spec": [
          {
            "ref": "example_dut/SPEC.md:42-48",
            "status": "candidate"
          }
        ],
        "rtl": [
          {
            "ref": "example_dut_RTL/output_ctrl.v:80-88",
            "status": "candidate"
          }
        ],
        "root_candidates": [],
        "open_questions": ["确认 ready/valid 窗口与数据变化的事务归属"]
      },
      "decision": {
        "verdict": "inconclusive",
        "review_confidence": null,
        "rationale": "尚未取得有效事务窗口中的可用波形证据。",
        "root_id": null
      }
    }
  ],
  "cases": {
    "unity_test/tests/test_example_dut_output.py::test_data_hold": {
      "nodeid": "unity_test/tests/test_example_dut_output.py::test_data_hold",
      "bug_ids": ["BUG-OUTPUT-HOLD"],
      "source_nodeid": "unity_test/tests/test_example_dut_output.py::test_data_hold",
      "replay_target": "workspace_example_dut/unity_test/tests/test_example_dut_output.py::test_data_hold",
      "waveform_test_case_name": "results/tests/workspace_example_dut/unity_test/tests/test_example_dut_output.py::test_data_hold",
      "replay": {
        "status": "reproduced",
        "invocation_success": true,
        "test_count": 1,
        "failed_count": 1,
        "result": "Assertion failed: output data changed while stalled"
      },
      "test_review": {
        "classification": "suspected_dut_bug",
        "correctness_confirmed": true,
        "exact_input": "valid=1, ready=0, data=0x31",
        "specification_expected": "data remains stable until transfer",
        "test_expected": "data remains 0x31 while ready is low",
        "dut_actual": "data changed to 0x32 before transfer",
        "driver_timing_review": "valid remained asserted; no request transfer occurred",
        "rationale": "Test and protocol window are consistent with the specification."
      },
      "waveform": {
        "conclusion": "inconclusive",
        "receipt_id": "",
        "result": {
          "error": "Waveform file unavailable for this run"
        },
        "signal_groups": {},
        "alignment_evidence": "No waveform window was available.",
        "observed_behavior": "Not observed",
        "source_correlation": "Pending RTL review"
      }
    }
  },
  "root_causes": []
}
```

## inventory：原始声明与证据骨架

读取两份输入报告，调用 `inventory-review` Skill 的 `create_review_json.py` 创建 JSON 骨架。脚本保留摘要行、详细分析主张、原始 Bug ID 和已引用的 TC/CK 候选；Bug 的语义解释、候选关联确认和证据内容由你阅读源报告后填充。摘要中的每一项必须对应一个 `origin: reported` 的 `suspected_bugs` 项。仅在详细分析出现的声明也要保留，并在 `analysis_claims` 中注明其原文位置。

每个 Bug 的 `evidence` 包含 Spec 引用、测试点、检查点、用例 ID、RTL 引用、根因候选及未决问题。一个 Bug 可关联多个 TC/CK，一个 TC 也可服务多个 Bug。路径和行范围必须能回到输入源文件；阅读 `{OUT}/inputs/<workspace>/` 下的镜像副本时，JSON 中仍保存源工作区相对路径。不要复制整个 DUT 工作区。

## replay：选择性重跑与测试审查

从 `cases` 中选择能直接验证声明的最小用例集合，只调用 `RunTestCases` 重跑这些节点。原始测试节点用 `replay_target` 选择；WaveInfo 使用本次 RunTestCases 报告中的完整 `waveform_test_case_name`。每次执行都在同一 case 记录中保存真实返回的成功状态、用例数量、Pass/Fail 结果和状态。可以逐例或小批执行；没有被选择的 case 保持 `not_selected`。

逐个失败用例独立推导 Spec 预期，检查精确输入、测试期望、DUT 实际值、API/driver、fixture、参考模型、复位、协议接受条件、采样边沿与响应延迟。只有正确测试的可复现 DUT 失败才能标为 `suspected_dut_bug`。测试、环境、收集或运行错误不能算作 DUT Bug；一次失败不等于结论。

## waveform：默认 WaveInfo 取证

只对复现且测试正确、可能由 DUT 造成的失败调用默认 `WaveInfo`。先确认测试和规格，再用准确 node ID、真实信号路径、事件 pattern 和显式 step 窗口或日志时钟对齐调用最终 WaveInfo。时序 DUT 列出真实时钟；组合逻辑声明 `combinational` 且不虚构时钟。完整 signal groups 还覆盖相关输入、输出、请求接受、响应有效及至少一条功能选择/状态/错误传播路径。同一 TC 关联多个 Bug 时覆盖其信号并集。

在 case 的 `waveform` 中保存原始 receipt、完整工具 result、viewer、信号组、事务窗口、日志与波形对齐、观测和 RTL/Spec 关联。没有 receipt 时保留真实错误并标为 `inconclusive`。receipt 必须来自本工作区默认 WaveInfo 工具；Checker 会验证签名 receipt 和最终信号组/viewer。

## correlate：裁决与根因合并

为每个报告 Bug 与新发现 Bug 更新 `decision`。`confirmed` 使用 `0 < review_confidence <= 1`；`refuted` 必须使用 `0`；`inconclusive` 必须使用 `null`。不得删除原始 Bug、原摘要、原置信度或关联证据。

同一个 TC 或相似标题不代表同一个根因。只有 RTL 首错与失效因果链相同才合并到 `root_causes`；确认的每个 Bug 只属于一个 root，排除和未定 Bug 的 `root_id` 为 null。每个 root 保存稳定 ID、RTL 首错引用、首错描述、传播链和 `bug_ids` 成员。

## publish：从 JSON 渲染 HTML

报告 Skill 的 `render_report.py` 直接读取每个 `bug_review.json`，生成 `bug_0001.html` 等详情页、工作区 `index.html` 和 `{OUT}/index.html` 总索引。页面来源、case、replay、WaveInfo、Spec/RTL、裁决和根因均从 JSON 读取。不要再生成独立 `report_data.json`。渲染后检查总索引中的所有工作区链接、每个 Bug 详情页、波形 viewer 和源文件引用，再将 `stage_status.publish` 设为 `complete` 并运行 Check。
