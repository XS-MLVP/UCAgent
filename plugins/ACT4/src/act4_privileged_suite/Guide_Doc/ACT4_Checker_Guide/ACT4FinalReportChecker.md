
# ACT4FinalReportChecker

实现：`act4_privileged_suite/checkers/act4_final_report_checker.py`

## 作用

该 checker 是阶段 07 的人类入口 gate。它确认最终 Markdown 报告包含稳定章节、以可点击
本地链接索引所有必需报告，并在 `Final validation state` 的 fenced YAML 中精确复述
validation state 的 contribution readiness 和 generation scope。

## 主要输入与输出

- 输入：final report、required report globs、required section/phrase 列表和 validation state。
- 输出：每个 required pattern 的匹配数、必需文件数、本地链接数、章节列表、最终状态
  摘要和 findings。
- 它通常与 `ACT4AIReviewChecker` 和最终 `ACT4FileManifestChecker` 同时构成 stage 07 gate。

## 代码实现原理

1. 展开 required report glob，要求每个 pattern 至少匹配一个真实文件。
2. 用 Markdown link 正则抽取本地路径，忽略 HTTP/mailto，解析相对路径和 URL encoding，
   确认每个必需文件都被最终报告直接链接。
3. 扫描 Markdown headings，检查工作流配置规定的九个稳定章节；可额外检查固定 phrase。
4. 解析权威 validation state，要求 `contribution_ready` 为 bool、
   `generation_scope.status` 为 complete/partial。
5. 定位 `Final validation state` 章节的首个 YAML fenced block，解析并精确比较
   `source_contribution_ready` 和 `generation_scope_status`。

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

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_final_report_checker.py`。

## 实现定位与判定示例

`_required_files()` 展开输入 glob，`_link_targets()` 解析本地链接，
`_validate_state()` 比较结构化摘要。07 配置九个 required_sections 和权威报告路径，
未额外配置 required_phrases。

只有写出路径文字而没有 Markdown 链接会报 final_report_index；
YAML 块的 source_contribution_ready 与权威 state 不同会报 final_report_state_summary。
权威 state=false/partial 的报告只要准确复述仍可通过这个 checker；
该 checker 不要求贡献就绪，也不代替前面阶段的 readiness gate。

额外非必需链接不存在、外部 URL 无效、锚点错误，当前算法不做通用链接健康检查。
标题存在不证明 chronology/non-claims 段落充分。可按
[最终报告提纲](../act4_template/privileged_validation_handoff_template.md)填写并独立复核内容。
