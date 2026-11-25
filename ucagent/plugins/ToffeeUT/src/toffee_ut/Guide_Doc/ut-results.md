
# 执行、失败归因与交付

## 使用真实结果

调用 `RunToffee()` 执行当前 DUT 的声明测试及 shared 自检。定向调用可传 targets、
keyword 或 markers；交付前空选择再跑一轮。源码、规格或构建改变后重跑，不沿用历史绿灯。

每次结果保存在新的 `results/<run-id>/`：cases.json 保留精确 nodeid 和 setup/call/
teardown，manifest.json 列真实覆盖产物，stdout.log/stderr.log 留下执行诊断。JUnit
只是辅助视图，不能用来重建全部 pytest 身份或替换完整阶段判定。失败运行也可能
正常提交覆盖；提交成功不代表测试通过。

cases 的阶段可附 `captured_diagnostics`，仅保存 pytest 当前阶段标准 Captured stdout/
stderr/log 原始文本，顺序和重复段不变；不是新检查接口，不解析文本为比较、完成或种子
证明。成功用例也可保留诊断；捕获关闭、没有输出或字段缺失均不证明已检查或没有行为。
每段最多保留前 6000 个 Unicode 字符（Python 字符串码点计数），每阶段总共最多 12000
字符、12 段；空段也占段数。`original_chars`、`retained_chars`、`truncated` 标明每段裁剪；
`omitted_sections`/`omitted_chars` 统计完全省略的标准文本段及其原始字符数，不含已保留段
的裁剪尾部。限额及计数单位写入同一可选字段，不改变判定或问题归因；不得回填历史收据。

| 判定 | 处置 |
|---|---|
| PASS | 本用例按当前判据通过，不等于所有行为均已证明 |
| FAIL / ERROR | 保留真实失败；先修复设施、采样、oracle 和输入合法性错误 |
| XPASS / XFAIL / SKIP | 审查标记原因，不能当作功能 PASS |
| UNCERTAIN | 用例真实执行且检查通过，但依据不足；不计 PASS，通常仍返回退出码 0 |
| 运行中断/证据不完整 | 修复后重跑，不能改标 UNCERTAIN |

需要 UNCERTAIN 时使用 `@pytest.mark.uncertain(reason="...", reference="...")`；
真实断言失败和清理错误仍优先成为 FAIL/ERROR。不可观察或未运行的范围留在规格中，
不制造一个 UNCERTAIN 用例代替验证。

## 失败归因

先保存失败，再沿“实际执行 → 合法激励 → 正确采样/完成 → 实际比较 → 独立 oracle
→ DUT 合同”反查。用邻近合法控制和单一变量实验排除其他解释。改时序后变绿只证明
相关性，不能直接确认根因。真实合法输入下的设计失败保留 FAIL，不放宽断言。

问题归 `docs/bugs/open/`；复验完成后保留原文并移到 closed，不删除原始运行。分类为
rtl、verification、unconfirmed、out-of-domain 或 ruled-out；证据不足使用 unconfirmed。
rtl 分类还须给出 `requirement`，指向已确认要求；setup/teardown 错误不能分类成 rtl。
closed 的历史记录不能替代当前失败的 open 处置。验证设施错误必须修复后再交付。
`rtl` 分类必须按 `Guide_Doc/ut-waveform.md` 为每个失败节点引用真实 `WaveInfo`
观察及事件级根因分析；缺少证据时保持原始 FAIL，记录缺失与下一实验，不能直接写
`rtl` 或降级结论来冒充已经完成根因任务。
静态候选另在 `docs/reviews/<DUT>-static-review.md` 逐项复核，未确认候选在交付范围
中披露，不得因测试全绿而悄然消失。

## 完整问题记录示例

````markdown

# 背压恢复后的响应顺序待确认

## 现象与依据

本次第二条返回值与独立输入历史不一致。已经检查 nodeid 确实执行，仍需排除 monitor
把两个采样沿交换的可能。当前不能宣称 RTL 缺陷已确认。

```yaml
kind: issue
run: results/20261110T120000Z-1234abcd
nodeids:
  - testbenches/queue/tests/test_response.py::test_order_after_backpressure
classification: unconfirmed
evidence: cases.json 的 call 阶段记录了第二条 payload 不符，原执行日志保留同一事务身份
next_action: 使用独立同拍快照对照 monitor 解码，保持原失败断言并重跑同一 nodeid
```

## 对照与剩余范围

尚未完成采样相位对照和波形分析。当前记录只支持“真实运行失败、根因待定”；没有
波形观察的内容不得写成已验证证据。后续实验使用新运行目录并引用原 run。
````

需要定位时调用 `WaveInfo` 读取本次实际 DUT 的对应节点与窗口，按
`Guide_Doc/ut-waveform.md` 保存观察和分析。不得借用另一运行/另一 DUT 的波形；
工具读取成功不自动证明根因推理正确。

## 生成交付报告

调用 `UTProject(action="summary")` 更新 `docs/README.md` 的生成区块，保留其他人工
说明的原始字节；不要手写测试计数、诊断或编辑原始产物。报告给出 PASS、FAIL 或
INCOMPLETE、完整选择与真实 run、raw/功能候选/selftest 分层计数、范围缺口、当前问题
记录链接和可折叠的精确 case。功能候选只表示非 selftest，不能自动说明已实现或已检查。
失败 case 数与问题记录数都不是独立根因数；不按相同报错去重，每个 case 可关联多份
问题记录，未归因失败仍列出。issue 不增加新的必填字段。
场景到 case 表保留全部维护场景，包括无 call 候选、deferred 和 out-of-domain 项，
展示要求/basis、范围与理由及原始结果。一个 case 可承接多个场景，不按表行累计通过数；
标签和已记录的 call 结果不证明实际字段比较、原生执行或完成义务。

逐例 setup/call/teardown 和诊断来自 cases；scenario 的 stimulus/expected/oracle/
completion 与 requirement 来源/basis 是维护的计划合同，不证明运行时到达、比较、逐 UID
完成或 oracle 独立性。没有逐事务实际值就明确未证明，不能补造 expected/observed。
requested seed 与 declared_native_seed 不证明原生种子实际生效，也不保证跨版本同刺激。
构建、源码映射、runtime、选择及原始 receipt/manifest/cases 链接用于身份追溯；只有
收据已有的 runtime 字段才是本次运行证据。报告链接相对 docs/README.md，results 使用
`../results/`。final 检查完整自动区块，手改人读统计或诊断同样拒绝；重新调用 summary 修复。

完整交付入口如下。该例是工具合成输入，非真实 DUT 结果；自动区块和 JSON 均由同一
渲染器生成，所有路径、声明种子、计数和签名只作格式示范，不得复制成运行证据：

````markdown

# Verification report

## 人工复核说明

说明本次责任边界、关键结论的依据和未完成实验。原始日志与构建身份以生成结果为准。

<!-- toffee-ut-summary:start -->

## ToffeeUT result

**Delivery status: INCOMPLETE**

- Run: [results/synthetic](../results/synthetic)
- Full selection: true
- Requested seed: 17

Counts are exact pytest nodeids, not requirements, iterations, transactions or RTL defects. Non-selftest means functional-candidate selection, not proof of implementation or checking. Committed artifacts, exit code 0 and coverage hits are not hardware PASS.

| Case population | Total | Raw outcomes |
|---|---:|---|
| all | 1 | {&quot;PASS&quot;: 1} |
| functional | 1 | {&quot;PASS&quot;: 1} |
| selftest | 0 | {} |

### Scope and evidence gaps

- problems: &#91;&#93;
- missing&#95;scenarios: &#91;&#93;
- unconfirmed&#95;requirements: &#91;&quot;R1&quot;&#93;
- scope&#95;exclusions: &#91;&#93;
- unregistered&#95;cases: &#91;&#93;
- unclassified&#95;failures: &#91;&#93;
- static&#95;candidates: &#91;&#93;
- Functional coverage target met: true
- Native coverage required: false; review state: missing
- Native line collection: not&#95;collected; coverage: not recorded (not functional proof)
- Native branch collection: not&#95;collected; coverage: not recorded (not functional proof)
- Native toggle collection: not&#95;collected; coverage: not recorded (not functional proof)

Scenario tags and call-phase success do not prove field comparisons, independent oracle use, per-UID accounting or completion obligations were reached. Implementation status, actual accepted stimulus, expected/observed values and per-transaction checked/failed/not-reached/not-checked records are not established by this run receipt. No such results are inferred from test names, assertion text or aggregate counts.

Maintained contracts: [design](spec/design/Block.md); [verification](spec/verification/Block.md); [manual reviews (not runtime proof)](reviews).

### Scenario-to-case traceability

All maintained scenarios remain visible, including those with no matching call-phase candidates and deferred or out-of-domain scope. Matches are non-selftest scenario tags with a recorded passed/failed call phase, not proof of native execution, implementation, field checking or completion. Raw outcomes are case outcomes, not requirement verdicts; rows can share nodeids.

| Planned scenario | Requirement / basis | Maintained scope / reason | Call-phase candidate nodeids | Raw case outcomes |
|---|---|---|---|---|
| S1 | R1 / inferred | active | testbenches/block/tests/test&#95;contract.py::test&#95;value&#91;param&#93; | {&quot;PASS&quot;: 1} |

### Bug / issue records

Failed case count: 0. Current-run issue record count: 0. Independent root-cause count: not established. Neither count is an independent root-cause count; matching diagnostics are not used to merge cases or issues.

| Maintained issue | Classification | State | Run | Source requirement / basis | Case nodeids |
|---|---|---|---|---|---|
| No current-run typed issue records | — | — | — | — | — |

Unattributed failing cases (never hidden by issue grouping): &#91;&#93;.

Classifications and evidence explanations are maintained issue claims, not generated failure diagnostics. See each linked record for evidence, alternatives and next actions.

### Runtime and source / build provenance

Recorded test runtime (only fields present in the signed receipt):

<pre>{
  &quot;python&quot;: &quot;/runtime/bin/python&quot;,
  &quot;toffee_version&quot;: &quot;synthetic&quot;
}</pre>

Recorded selection:

<pre>{
  &quot;keyword&quot;: &quot;&quot;,
  &quot;markers&quot;: &quot;&quot;,
  &quot;targets&quot;: [
    &quot;testbenches/block/tests&quot;
  ]
}</pre>

- Recorded process exit code: 0 (not a hardware verdict)
- Source-map identity: {&quot;files&quot;: 3, &quot;sha256&quot;: &quot;synthetic-source-map-digest&quot;}
- Receipt signature: synthetic-not-a-real-receipt

The source-map digest identifies the sorted source_after mapping; full source hashes and build file identities remain in receipt.json and manifest.json, not duplicated here. Unrecorded tool commits, build options and native seed effectiveness are not proved. Equal requested or declared seeds do not establish identical native stimulus across versions.

Native builds (manifest identities, not a claim that every case used every build):

- {&quot;build&#95;id&quot;: &quot;synthetic-build&quot;, &quot;file&#95;count&quot;: 1, &quot;name&quot;: &quot;DUTBlock&quot;, &quot;native&#95;duts&quot;: &#91;{&quot;class&quot;: &quot;DUTBlock&quot;, &quot;source&quot;: &quot;/work/ut&#95;project/dut/Block/&#95;&#95;init&#95;&#95;.py&quot;}&#93;}

Raw run artifacts (the receipt and manifest retain complete identities):

- [results/synthetic/cases.json](../results/synthetic/cases.json)
- [results/synthetic/manifest.json](../results/synthetic/manifest.json)
- [results/synthetic/receipt.json](../results/synthetic/receipt.json)
- [results/synthetic/stdout.log](../results/synthetic/stdout.log)

Coverage artifacts:

- None recorded.

### Detailed cases

Each scenario below is a **planned contract**, not a runtime comparison or completion record. Diagnostics come only from recorded case phases; actual values are not reconstructed from the plan. Captured messages are not parsed into comparisons, completion or effective seed evidence. Native seed declarations are not verified effective seeds.

<details><summary>testbenches/block/tests/test&#95;contract.py::test&#95;value&#91;param&#93; — PASS</summary>

- Exact nodeid: testbenches/block/tests/test&#95;contract.py::test&#95;value&#91;param&#93;
- Run: [results/synthetic](../results/synthetic); raw phases: [results/synthetic/cases.json](../results/synthetic/cases.json)
- selftest: false; roles: &#91;&quot;api&quot;&#93;
- Requested seed: 17; declared_native_seed: 17; effective native seed: not proved by receipt.
- Associated issues: none recorded

| Phase | Outcome | Duration (s) | wasxfail |
|---|---|---:|---|
| setup | passed | 0.01 | not recorded |
| call | passed | 0.01 | not recorded |
| teardown | passed | 0.01 | not recorded |

Recorded phases and diagnostics (verbatim fields; failure text may be bounded at capture):

<pre>{
  &quot;call&quot;: {
    &quot;duration&quot;: 0.01,
    &quot;outcome&quot;: &quot;passed&quot;,
    &quot;wasxfail&quot;: null
  },
  &quot;setup&quot;: {
    &quot;duration&quot;: 0.01,
    &quot;outcome&quot;: &quot;passed&quot;,
    &quot;wasxfail&quot;: null
  },
  &quot;teardown&quot;: {
    &quot;duration&quot;: 0.01,
    &quot;outcome&quot;: &quot;passed&quot;,
    &quot;wasxfail&quot;: null
  }
}</pre>

**call — runtime captured diagnostics, not independent proof**

Optional text from standard pytest sections only. Absence does not prove silence or checking; retained text and truncation metadata do not prove its claims.

<pre>{
  &quot;limits&quot;: {
    &quot;phase_chars&quot;: 12000,
    &quot;section_chars&quot;: 6000,
    &quot;sections&quot;: 12
  },
  &quot;omitted_chars&quot;: 0,
  &quot;omitted_sections&quot;: 0,
  &quot;retention&quot;: &quot;head&quot;,
  &quot;unit&quot;: &quot;unicode_characters&quot;
}</pre>

- Captured stdout call; original_chars: 13; retained_chars: 13; truncated: false

<pre>runtime note
</pre>

Native DUT registrations and matching build identities:

- {&quot;class&quot;: &quot;DUTBlock&quot;, &quot;source&quot;: &quot;/work/ut&#95;project/dut/Block/&#95;&#95;init&#95;&#95;.py&quot;}; matching build IDs: &#91;&quot;synthetic-build&quot;&#93;

Waveform files (links do not prove analysis or continued file availability):

- None recorded.
- Waveform capture diagnostics: &#91;&#93;

#### Scenario contracts (planned, not runtime proof)

- Scenario: S1
  - status: active
  - stimulus: Offer one legal input
  - expected: Same value
  - oracle: Candidate interface contract
  - completion: Compare returned value
  - Requirement: R1; basis: inferred; source: [inputs/interface.md&#35;identity](../../inputs/interface.md#identity)
    - statement: Identity is preserved
    - precondition: Legal input
    - observation: Returned value
    - timing: On response
    - next_action: Confirm source

</details>

### Structured evidence summary

```json
{
  "status": "INCOMPLETE",
  "run": "results/synthetic",
  "tests": {
    "PASS": 1
  },
  "full_selection": true,
  "problems": [],
  "missing_scenarios": [],
  "unconfirmed_requirements": [
    "R1"
  ],
  "scope_exclusions": [],
  "static_candidates": [],
  "unregistered_cases": [],
  "unclassified_failures": [],
  "failing_nodes": [],
  "issues": [],
  "scenarios": {
    "S1": {
      "scope": "active",
      "nodeids": [
        "testbenches/block/tests/test_contract.py::test_value[param]"
      ],
      "outcomes": {
        "PASS": 1
      }
    }
  },
  "functional_coverage": {
    "covered": true,
    "groups": []
  },
  "native_coverage": {
    "required": false,
    "review": {
      "state": "missing"
    },
    "line": {
      "state": "not_collected",
      "coverage": null
    },
    "branch": {
      "state": "not_collected",
      "coverage": null
    },
    "toggle": {
      "state": "not_collected",
      "coverage": null
    }
  },
  "requested_seed": 17,
  "coverage_artifacts": [],
  "receipt_signature": "synthetic-not-a-real-receipt",
  "case_counts": {
    "all": {
      "total": 1,
      "outcomes": {
        "PASS": 1
      }
    },
    "functional": {
      "total": 1,
      "outcomes": {
        "PASS": 1
      }
    },
    "selftest": {
      "total": 0,
      "outcomes": {}
    }
  },
  "case_details": {
    "testbenches/block/tests/test_contract.py::test_value[param]": {
      "status": "PASS",
      "phases": {
        "setup": {
          "outcome": "passed",
          "duration": 0.01,
          "wasxfail": null
        },
        "call": {
          "outcome": "passed",
          "duration": 0.01,
          "wasxfail": null,
          "captured_diagnostics": {
            "unit": "unicode_characters",
            "retention": "head",
            "limits": {
              "section_chars": 6000,
              "phase_chars": 12000,
              "sections": 12
            },
            "sections": [
              {
                "name": "Captured stdout call",
                "text": "runtime note\n",
                "original_chars": 13,
                "retained_chars": 13,
                "truncated": false
              }
            ],
            "omitted_sections": 0,
            "omitted_chars": 0
          }
        },
        "teardown": {
          "outcome": "passed",
          "duration": 0.01,
          "wasxfail": null
        }
      },
      "selftest": false,
      "roles": [
        "api"
      ],
      "scenarios": [
        "S1"
      ],
      "native_duts": [
        {
          "class": "DUTBlock",
          "source": "/work/ut_project/dut/Block/__init__.py"
        }
      ],
      "declared_native_seed": 17,
      "waveforms": [],
      "waveform_errors": []
    }
  },
  "contracts": {
    "design_path": "docs/spec/design/Block.md",
    "verification_path": "docs/spec/verification/Block.md",
    "requirements": {
      "R1": {
        "id": "R1",
        "statement": "Identity is preserved",
        "precondition": "Legal input",
        "observation": "Returned value",
        "timing": "On response",
        "source": "inputs/interface.md#identity",
        "basis": "inferred",
        "next_action": "Confirm source"
      }
    },
    "scenarios": {
      "S1": {
        "id": "S1",
        "requirement": "R1",
        "stimulus": "Offer one legal input",
        "expected": "Same value",
        "oracle": "Candidate interface contract",
        "completion": "Compare returned value",
        "status": "active"
      }
    }
  },
  "provenance": {
    "project_root": "/work/ut_project",
    "workspace_root": "/work",
    "runtime": {
      "python": "/runtime/bin/python",
      "toffee_version": "synthetic"
    },
    "selection": {
      "targets": [
        "testbenches/block/tests"
      ],
      "keyword": "",
      "markers": ""
    },
    "returncode": 0,
    "source_identity": {
      "files": 3,
      "sha256": "synthetic-source-map-digest"
    },
    "native_builds": [
      {
        "name": "DUTBlock",
        "build_id": "synthetic-build",
        "file_count": 1,
        "native_duts": [
          {
            "class": "DUTBlock",
            "source": "/work/ut_project/dut/Block/__init__.py"
          }
        ]
      }
    ],
    "raw_artifacts": [
      "results/synthetic/cases.json",
      "results/synthetic/manifest.json",
      "results/synthetic/receipt.json",
      "results/synthetic/stdout.log"
    ]
  }
}
```

<!-- toffee-ut-summary:end -->
````

上例展示完整自动区块，run、路径、计数和签名由本次 `summary` 填充，不能手动删改。
功能覆盖统计保留 Toffee 的采样语义；first/last metadata 不是完整逐例归因，不代替
逐事务比较或把每个 bin 归给所有标记场景。覆盖目标未达到时保持 INCOMPLETE。

最后调用 `Check` 和 `Complete`。完成交付可以保留有证据的设计 FAIL 或披露未确认
范围的 INCOMPLETE，不得因此把硬件结论改成 PASS。
