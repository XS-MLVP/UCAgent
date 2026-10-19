
# ACT4ManualReferenceChecker

实现：`act4_privileged_suite/checkers/act4_manual_reference_checker.py`

## 作用

该 checker 是阶段 01 的规范来源 gate。它验证从只读 RISC-V manual 仓库选择的 ADOC
章节和 normative metadata 是否有可复查的发现过程、是否被逐字节冻结，以及 provenance
记录的 Git HEAD 和 SHA-256 是否与当前输入一致。

## 主要输入与输出

- 输入：suite、原始 testplan、manual root、规范副本、metadata 副本和 provenance YAML。
- `require_git_head` 控制是否必须能够确认 manual 仓库 HEAD。
- 输出：rule/tag 数量、选中的源路径及 findings；部分 metadata tag 在选中章节之外但已
  完整披露时产生 warning，而不是无条件失败。

## 代码实现原理

1. 解析 provenance schema，校验 suite、testplan hash、specification/metadata source 和
   copied path。
2. 对 source path 做 root containment 检查，防止 `../` 逃逸；按字节比较源文件与副本，
   并流式计算 SHA-256。
3. 检查 discovery 的 CSV terms、candidate 列表、matched terms 和 selection reason，确认
   选中的源确实出现在候选中。
4. 解析 `normative_rule_definitions` 的 `name/names` 和 `tag/tags`，检查重复 rule；把 tag
   与冻结的规范文本匹配。部分未匹配 tag 必须在 provenance 中精确列出并说明原因。
5. 通过 `git -C <manual_root> rev-parse HEAD` 对照 `manual_git_head`。

## 当前局限

- CSV term 命中和 tag 文本匹配是词法证据，不证明 rule 与所选规范段落的语义完全一致。
- checker 不搜索或排序整个 manual 候选空间，只验证 provenance 声明的候选和选择；遗漏
  更合适章节仍可能需要人工发现。
- 当前 HEAD 校验要求 manual checkout 仍处于冻结提交；在 detached/archive 或无 Git
  元数据环境中需要关闭该 gate 并明确降低置信度。
- warning 允许跨章节 tag 被解释后继续，但解释是否充分仍需 reviewer 判断。
- 它不校验规范版本是否为认证项目最终采用版本，只确认本轮选择和副本一致。

## 测试

当前没有同名独立测试文件，但 `test_act4_priv_workflow_config.py` 已包含三个实现级测试：
`test_manual_reference_checker_accepts_exact_csv_driven_pair`、
`test_manual_reference_checker_rejects_non_exact_copy`、
`test_manual_reference_checker_requires_selected_candidate_evidence`。
不能把“没有独立测试文件”等同于“没有单元测试”；HEAD 异常和部分 tag 披露等分支仍需
按覆盖情况补充 fixture。

## 实现定位与判定示例

`_source_path()` 约束 manual_root 内的选中源；`_check_copy()` 比较字节与 hash；
`_check_candidates()` 验证选中项存在及 matched_terms 非空；
`_rule_names_and_tags()` 提取 metadata。当前 01 配置 require_git_head=true。

零 tag 命中是 error；部分 tag 缺失且精确列出 unmatched_metadata_tags 与解释时是 warning。
这个结果不能推广成“所有规范引用均已证明”：tag 匹配是文本包含，候选 matched_terms
也不逐一到候选源码中重验。Git HEAD 校验不检查 manual dirty status；
未提交源改动可与副本字节一致，但不能因此声称副本是该 commit 的原始内容。
