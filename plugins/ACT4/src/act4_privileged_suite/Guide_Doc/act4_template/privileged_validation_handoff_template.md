<!-- SPDX-License-Identifier: Apache-2.0 -->

# ACT4 Privileged 验证与交付模板

适用阶段：05_build、06_contribution、07_final_report。
本模板连接已有 generator 与最终人类报告，不执行命令、不预设通过。
完整 schema 和 required check names 以`workflows/privileged-suite-generation.yaml`为准。

## 1. 首选模型与实际命令

在运行生成测试前冻结 preferred 的 model、executable、config_file、selection_basis。
依据是本轮 ACT4 README/test_config、UDB 与实际版本探测；不能从历史 suite 成败推导。
executable 保存 `ref_model_exe` 原始值，config_file 保存命令中 CONFIG_FILES 原值。

以下仅是命令形式；配置路径必须先确认且开关必须已审计：

```sh
WORKDIR=work_itgen_{DUT} CONFIG_FILES=<actual-config>/test_config.yaml EXTENSIONS={DUT} CLEAN_INTERMEDIATES= make
WORKDIR=work_itgen_{DUT} COVERAGE_CONFIG_FILES=<actual-sail-config>/test_config.yaml EXTENSIONS={DUT} make coverage
```

coverage 命令只在对应 Sail/RVVI 与 Questa/VCS 链可用时执行。新鲜工作树可注明后跳过清理；
重跑时先确认本版本原生清理入口，只清理本 suite WORKDIR，再由原生 testgen 重新生成 .S。

## 2. validation state 填写提纲

下面是待填写的未完成状态草稿。它刻意不会通过 build gate；执行后按真实证据更新。

```yaml
source_generated: false
supported_xlens: [64]  # 待核对 target 与 contract
self_checking:
  model: "待填写实际模型"
  executable: "待填写 ref_model_exe 原值"
  config_file: "待填写 CONFIG_FILES 原值"
  passed: false
  command: ""
sail_coverage:
  passed: false
  command: ""
  blocked_reason: "尚未评估当前 coverage 管线"
generation_scope:
  status: complete  # 必须由最终三个集合推导，不能作为通过承诺
  generated_targets: []
  partial_targets: []
  blocked_targets: []
reference_model_evaluation:
  preferred:
    model: "待填写并在运行前冻结"
    executable: "待填写"
    config_file: "待填写"
    selection_basis: []
  attempts: []
  fallback:
    used: false
    model: null
    reason: null
    scope_reduction: false
    affected_targets: []
    evidence: []
contribution_ready: false
```

attempts 每次实际运行或因 tool/version/config 无法运行都单列，包含：
`model/executable/config_file/command/status/tested_targets/passed_targets/failed_targets/
failure_class/evidence/diagnoses`。status 为 passed、failed 或 not_run；失败分类取配置枚举。
passed attempt 不得带 failed_targets；未知根因不能触发 fallback。
同一 attempt 内同一 target 的 diagnosis outcome 不得冲突；不同 attempt 可随修复和重跑
更新诊断，按记录顺序使用该目标最近的 diagnosis outcome 对照最终范围，不删除历史证据。

diagnoses 的两种形式：
- 单目标：target、first_failure、alternatives_evaluated、outcome、evidence。
- 仅 model_capability_gap 可分组：capability、affected_targets、common_cause_evidence，
  再加 first_failure、alternatives_evaluated、outcome、evidence。至少两个失败目标确实
  消费同一缺失能力；不能用整个 guest/VM 类别名替代共同根因。

alternatives_evaluated 包含 suite_local_resources、positive_subset、native_entrypoint、
generation_vs_validation_scope。保留首选成功目标；fallback affected_targets 必须出现在
最终模型的通过 attempt 中，scope_reduction 始终为 false。

generated_targets 是至少一个正式 profile 已生成的目标；partial_targets 是其中同时存在
blocked 子场景的子集；blocked_targets 是没有 allowed profile 的正式目标，不能与 generated
混淆。若 partial 或 blocked 非空则 status 为 partial。experimental 不进入这些集合。
因此 complete 只描述正式生成范围；子场景缺失和实验限制继续记录在现有 VM contract、
experimental manifest 和 AI review，self_checking 与 sail_coverage 分别报告验证状态。
无需为这些维度增加字段或检查步骤，experimental 和 coverage 不可用仍按已有规则处理。

## 3. 每个测试的证据表

| Target/profile | Source stem / .S | .sig.log | .sig / .results | 最终 .elf | 已确认事实与限制 |
| --- | --- | --- | --- | --- | --- |
| 待填 | 实际路径 | 对应 SIGRUN、唯一 SUCCESS、区间/粒度 | 区间 record 数配对 | elfs 下实际文件 | 待填 |

区分链路 `test.S -> build/*.sig.elf -> *.sig -> *.results -> elfs/*.elf`：
参考模型运行 signature ELF 并生成预期数据；最终 self-checking ELF 生成完成不证明其已
在 DUT/testbench 上执行。日志格式/record 数检查也不证明每个 target 的语义正确或 bin 命中。
05/06 checker 根据 self_checking.command 的 `CONFIG_FILES`、`WORKDIR` 和 test_config 的
`name` 自动限定所选构建目录；选择信息无法解析时报错，不使用其他配置的旧产物。
signature/results 检查十六进制/整数数据格式和区间记录数，允许标签、空白、注释、逗号
操作数及 `.word/.quad` 混用，不比较数值；SUCCESS 后可以有普通统计输出。
`reference_runs_checked` 是进入日志检查的数量；`complete_reference_runs` 仅计入日志、
signature/results 格式和区间检查均无 error 的链路，不表示最终 ELF 已在 DUT 上执行。

## 4. AI review、manifest 与检查器顺序

05-07 同样使用[工作流指南第 4.2 节](../ACT4_Privileged_Suite_Workflow_Guide.md)的共用约定：
读完当前阶段依赖后，在 stage journal 中明确工作项、依赖、操作/路径、产物、现有验收
依据与进度，再按项执行。完成工作项、调整方案或发生失败时更新实际证据与下一步；
复用已有报告中的完整命令和日志，不另建计划文件或增加检查。

累计 AI review 中每阶段含 review_status、summary、checks、limitations、blocking_issues、
artifacts、commands；checker 的 status/confidence 与真实证据一致。
未运行 coverage 通常用 not_run/unverified、workflow_blocking=false，并写 limitation。
`approved` 只用于所有项 passed/confirmed 且没有限制的情况。

| 阶段 | required_check_names |
| --- | --- |
| 05_build | generated_assets, self_checking_evidence, reference_model_coverage, vm_runtime_readiness, switch_capability_consistency, file_manifest_update, framework_integrity |
| 06_contribution | artifact_inventory, prior_reviews, contribution_state, local_ci_reproduction, limitations_summary, switch_capability_consistency, file_manifest_completeness, framework_integrity |
| 07_final_report | report_index, state_consistency, evidence_chronology, limitations_and_nonclaims, human_review_entrypoint, file_manifest_update, framework_integrity |

manifest v2 逐个记录实际 .S、最终 .elf、.sig、.results、.sig.log、内部 contract、辅助配置、
报告和 checker 输出；贡献集合只包含实际 ACT4 源文件。基线、每次事件和最终 file hash
分别记录，不能用最终快照声称拥有完整历史。

manifest 自身 sha256_after=null，hash_note 写 self-referential；最终报告必须有稳定 hash。
受保护对象比较只证明当前与基线一致；已发生后恢复的关键写入仍要记录 policy_violation。
先运行会落盘的 checker、登记其真实输出，再执行最终 completeness，避免遗漏新报告。

05 的顺序是 TestAsset -> Switch -> integrity-only -> manifest -> AIReview；
06 是 TestAsset(readiness) -> AIReview -> manifest(completeness)；
07 是 AIReview -> FinalReport -> manifest(completeness)。将 Check 反馈和修复关联到现有
工作项，Complete 前保存完整的当前 journal，汇总实际结果、计划偏差和交接限制，再调用
Complete。检查通过的版本与最终交付文件须一致；不预写 Complete 的成功结果。

## 5. 最终报告提纲

输出 `{OUT}/{DUT}/reports/{DUT}_final_summary_report.md`，采用以下九个固定标题。
下方用四反引号包住模板，保留最终 Markdown 内部的 YAML fence：

````markdown

# {DUT} Final Summary

## Executive conclusion

填写本次 scope、可贡献性与关键限制；不预设 passed。

## Final validation state

从最终 validation state 复制真实值，替换下面的待填字符串与布尔值。
`source_contribution_ready` 必须为 YAML 布尔值 `true` 或 `false`，不能写成数值或字符串。
```yaml
source_contribution_ready: false
generation_scope_status: complete
```

## Workflow summary

从 AllStageJournal 和当前 journal 汇总 01-07 的计划目标、实际结果、主要偏差与遗留限制，
引用工作项 ID 及已有证据。只写已实际执行的内容，不把计划或待执行的 Complete 写成完成。

## Report index

用相对 Markdown 链接列出每份权威文件的用途、阶段、当前/历史身份。

## Coverage scope

分别说明 source generation、参考模型运行、RVVI trace、UCDB/VDB 及 DUT 执行状态。

## Evidence chronology

旧报告如被新实现取代，标为 historical/superseded 并链接对应新证据。
重要计划调整说明原因、处置和影响，保留关键失败证据；没有事前计划的旧记录注明恢复时整理。

## Limitations and non-claims

列出未运行、未证明、partial/blocked/experimental 范围和影响。

## Human inspector checklist

给出阅读顺序、需要人工确认的语义/边界、复现入口。

## Reproduction

仅列实际执行的完整命令、工作目录、版本和预期产物；建议命令另标未执行。
````

Report index 至少链接 validation state、AI review、manifest、switch audit、CTP/manual
provenance、VM contract、experimental manifest 和实际 `reports/act4_*_check/*.json`。
不虚构未落盘 checker JSON，也不重复要求同一个 checker 的 Markdown 副本。
最终三项 checker 通过后更新 journal 的执行结果与剩余事项，再调用 Complete；全部阶段完成后 Exit。
