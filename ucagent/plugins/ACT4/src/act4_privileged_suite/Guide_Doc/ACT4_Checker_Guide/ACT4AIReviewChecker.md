
# ACT4AIReviewChecker

实现：`act4_privileged_suite/checkers/act4_ai_review_checker.py`

## 作用

该 checker 在七个阶段都运行，验证统一的 `{DUT}_ai_review.yaml` 是否保留先前阶段、包含
当前阶段规定的检查项，并使 review status、check status、confidence、limitation 和
blocking issue 彼此一致。

## 主要输入与输出

- 输入：review file、expected stage、required check names、required artifacts 和 required
  prior stages。
- 输出：各相关阶段状态、error/warning 和 findings。
- `approved_with_limitations` 会产生预期 warning，但只要没有 error，gate 可以通过。

## 代码实现原理

1. 用 glob 确认 required artifacts 存在，再解析 YAML，要求 `schema_version: 1` 和
   `reviewer: ai`，明确拒绝伪造 human reviewer。
2. 验证每个 check 的 name、status、confidence、evidence、conclusion 和
   `workflow_blocking`；非 passed 或非 confirmed 时要求 limitation。
3. 检查当前阶段 required check names 无缺失/重复，artifacts 非空，prior stages 存在且
   schema 有效。
4. 计算状态一致性：`approved` 只能包含 passed/confirmed 且无 limitation；blocked check
   或 blocking issue 必须对应 `review_status: blocked`；blocked 阶段让 checker 失败。
5. 对当前阶段的 `approved_with_limitations` 输出 warning，确保限制在最终结果中可见。

06_contribution 的配置要求 `local_ci_reproduction`，用于记录最终贡献集的本地 CI
复现范围、命令和失败处置。缺少该项会失败；suite 错误未修复时应阻塞贡献阶段；
纯工具或上游模型限制可使用带 limitation 的 `warning/not_run` 继续整理已有资产。
该项复用原有 schema 和校验逻辑，不执行 CI，也不保证 `passed` 声明与日志一致。
具体命令和修复流程见[工作流指南第 10.1 节](../ACT4_Privileged_Suite_Workflow_Guide.md#101-本地运行相关-ci-并修复错误)。

## 当前局限

- 它校验报告结构和内部一致性，不验证 evidence 文本所述命令真的执行过，也不重新计算
  文件 hash、运行模型或理解规范语义。
- required artifact 检查主要是 glob 存在性，文件可能存在但内容不正确；内容由其他
  checker 负责。
- checker 能确认 prior stage 仍存在，不能仅靠 YAML 判断已经完成的历史段落是否被恶意
  改写；需要版本控制/manifest change events 辅助审计。
- `confidence: confirmed` 是报告声明，不是自动证明。没有对应确定性 checker 或原始日志
  时，人工 reviewer 仍应挑战该置信度。
- warning 不是 coverage 或 DUT 失败，只表示当前阶段保留了非阻塞证据限制。

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_ai_review_checker.py`。

## 实现定位与配置关系

`_validate_check()` 校验单项，`_validate_stage()` 推导状态一致性，
`do_check()` 检查当前阶段及配置指定的 prior stages。required_check_names 从 YAML
实例读取；不是每份报告自行定义。required_artifacts 是 glob 存在性，不验证完整 inventory。

`approved + not_run` 会失败；`approved_with_limitations + not_run + limitation`
且 workflow_blocking=false 可通过。即使 workflow_blocking=false，check status=blocked
仍使阶段属于阻塞，不能用它表示可选 coverage 未运行。

commands/evidence 为报告声明，不会执行或核验其历史；reviewer=ai 约束也不扫描整个自然语言
报告中的“人工审批”表述。与[验证交付模板](../act4_template/privileged_validation_handoff_template.md)
中的真实命令和其他 checker 证据共同审查。
