
# ACT4FinalReportChecker

## 作用

该 checker 是阶段 07 的人类入口 gate。它确认最终 Markdown 报告包含稳定章节、以可点击
本地链接索引所有必需报告，并在 `Final validation state` 的 fenced YAML 中精确复述
validation state 的 contribution readiness 和 generation scope。

## 主要输入与输出

- 输入：final report、required report globs、required section/phrase 列表和 validation state。
- 输出：每个 required pattern 的匹配数、必需文件数、本地链接数、章节列表、最终状态
  摘要和 findings。
- 它通常与 `ACT4AIReviewChecker` 和最终 `ACT4FileManifestChecker` 同时构成 stage 07 gate。

## 提交前检查

1. 读取当前阶段要求的实际报告，每个必需路径或 glob 都应有真实文件。
2. 在 `Report index` 中逐个使用相对 Markdown 链接，说明用途及当前/历史身份；
   只写文件路径文字不能替代链接。
3. 保留下面完整示例中的九个固定章节，填写本轮事实，不能把示例当成执行证据。
4. 从权威 validation state 复制 `contribution_ready` 和 `generation_scope.status`。
5. `Final validation state` 的 YAML 使用 `source_contribution_ready: true|false` 与
   `generation_scope_status: complete|partial`。布尔值不能写成 `1`、`0` 或引号字符串。

## 当前局限

- Markdown parser 采用正则而非完整 CommonMark AST；引用式链接、HTML link、复杂嵌套或
  非标准 fence 可能无法识别。
- 章节检查主要匹配 heading 文本，required phrase 也是大小写不敏感的包含判断，不能
  评估论证质量或确认每个链接的用途/权威性描述正确。
- 结构化状态只强制比对两个关键字段。self-checking、coverage database、DUT execution
  等 non-claim 主要依赖 AI review 和人工阅读。
- required report glob 可能同时匹配历史/等价文件；checker 确认它们被链接，但不自动
  判断报告是否把旧结论正确标为 superseded。
- 通过不代表人工批准，只代表最终入口结构完整且两个关键状态与权威 YAML 一致。

## 失败后修复

`final_report_index`：补齐被指出的报告链接；
`final_report_state_summary`：读取权威 YAML，修正字段类型和值后再次调用 `Check`。
权威 state=false/partial 的报告只要准确复述仍可通过这个 checker；
该 checker 不要求贡献就绪，也不代替前面阶段的 readiness gate。

额外非必需链接不存在、外部 URL 无效、锚点错误，当前算法不做通用链接健康检查。
标题存在不证明 chronology/non-claims 段落充分。可按
[最终报告提纲](../act4_template/privileged_validation_handoff_template.md)填写并独立复核内容。

## 完整报告示例

以下为 H 的示例报告，假定所链接文件均真实存在，且权威状态为 true/partial。
本例展示全部章节及索引；实际命令、版本、限制和文件必须替换为本轮证据。

````markdown

# H Final Summary

## Executive conclusion

The generated host subset is contribution-ready. Guest profiles remain blocked;
this is not complete architectural certification or a DUT pass.

## Final validation state

```yaml
source_contribution_ready: true
generation_scope_status: partial
```

## Workflow summary

Stages 01-07 produced the source assets and their review records. The host subset
passed the selected reference run; guest work remains outside the delivered scope.

## Report index

- [Validation state](H_validation_state.yaml): current readiness and scope.
- [AI review](H_ai_review.yaml): cumulative stage conclusions.
- [File manifest](H_file_manifest.yaml): source inventory and integrity evidence.
- [Switch audit](H_switch_capability_audit.yaml): allowed and blocked controls.
- [CTP provenance](H_ctp_reference_provenance.yaml): plan source and snapshot.
- [Manual provenance](H_manual_reference_provenance.yaml): selected normative sources.
- [VM contract](../H_vm_resource_contract.yaml): generated and blocked profiles.
- [Experimental manifest](../experimental/H_experimental_assets.yaml): isolated work.
- [Coverage check](act4_coverage_check/H.asset-consistency.json): static source checks.
- [Mapping check](act4_norm_mapping_check/H.asset-consistency.json): rule linkage.
- [Generator check](act4_generator_check/H.asset-consistency.json): source consistency.
- [Test asset check](act4_test_asset_check/test-assets.json): selected run evidence.

## Coverage scope

Host source generation and reference-model evidence are available. No Sail/RVVI
coverage hits, external DUT execution or remote CI pass are claimed.

## Evidence chronology

Earlier not-run findings are historical and superseded only for targets with new
evidence in the current validation state. Guest limitations remain current.

## Limitations and non-claims

Guest profiles are blocked. Optional dynamic coverage is unavailable. No human
approval, external DUT pass or full certification is claimed.

## Human inspector checklist

Start with validation state, inspect the source-to-run evidence, then review
the blocked profiles, contribution inventory and framework integrity.

## Reproduction

Use the executed command and its selected configuration in validation state,
with the frozen ACT4 HEAD and the exact recorded source and tool versions.
No additional reproduction command is claimed to have run in this example.
````
