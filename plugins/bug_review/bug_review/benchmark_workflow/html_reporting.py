"""HTML report generation for benchmark workflow.

All HTML functions accept a ``lang`` parameter: ``"zh"`` (default) or ``"en"``.
"""
import html
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .gt_defect_reporting import (
    SourceRegistry,
    _GT_DETAIL_EXTRA_CSS,
    _build_modal_html_and_js,
    _short_path,
)
from .matrix_enrichment import attach_matrix_record_evidence

_REPLAY_NOT_EXECUTED_STATUSES = {None, "", "not_run"}
_REPLAY_SUCCESS_STATUSES = {"reproduced"}

# ── i18n string table ──────────────────────────────────────────────
_TEXT = {
    # tier labels
    "tier_replay_confirmed":       {"zh": "重放确认",         "en": "Replay Confirmed"},
    "tier_replay_partial_confirmed": {"zh": "重放部分确认",   "en": "Replay Partial Confirmed"},
    "tier_replay_contradicted":    {"zh": "重放未复现",       "en": "Replay Not Reproduced"},
    "tier_replay_contradicted_review": {"zh": "重放未复现(待复审)", "en": "Replay Not Reproduced (Review)"},
    "tier_replay_snapshot_changed_review": {"zh": "快照变化(待复审)", "en": "Snapshot Changed (Review)"},
    "tier_rtl_supported":          {"zh": "RTL支撑",          "en": "RTL Supported"},
    "tier_waveform_supported":     {"zh": "波形支撑",         "en": "Waveform Supported"},
    "tier_execution_supported":    {"zh": "执行支撑",         "en": "Execution Supported"},
    "tier_coverage_supported":     {"zh": "覆盖率支撑",       "en": "Coverage Supported"},
    "tier_claim_only":             {"zh": "仅有声明",         "en": "Claim Only"},
    "tier_not_found":              {"zh": "未发现",           "en": "Not Found"},
    "tier_excluded_declared":      {"zh": "原声明排除",       "en": "Excluded by Declaration"},
    # audit relation labels
    "audit_different_bugs":        {"zh": "不同 Bug",         "en": "Different Bugs"},
    "audit_related_symptoms":      {"zh": "相关症状",         "en": "Related Symptoms"},
    "audit_insufficient_evidence": {"zh": "证据不足",         "en": "Insufficient Evidence"},
    "audit_same_bug":              {"zh": "同一 Bug",         "en": "Same Bug"},
    # audit page
    "audit_back_to_main":          {"zh": "← 返回 BugReview 主界面", "en": "← Back to BugReview"},
    "audit_page_title":            {"zh": "跨模型语义审计全量明细", "en": "Cross-Model Semantic Audit — Full Detail"},
    "audit_page_desc":             {"zh": "这里展示全部未合并审计条目，不做抽样截断。共完成 <span class=\"hl\">{semantic_total}</span> 对跨模型语义判定，其中 <span class=\"hl\">{audit_total}</span> 对进入 non-merge audit。",
                                    "en": "Full non-merge audit entries without sampling. <span class=\"hl\">{semantic_total}</span> cross-model semantic pairs judged; <span class=\"hl\">{audit_total}</span> entered non-merge audit."},
    "audit_dist_title":            {"zh": "审计分布",         "en": "Audit Distribution"},
    "audit_dist_desc":             {"zh": "按语义关系和模型对统计全量审计条目，口径与主页面保持一致。", "en": "Full audit entries by semantic relation and model pair, consistent with the main report."},
    "audit_back_to_main_short":    {"zh": "返回主界面",       "en": "Back to Main"},
    "audit_nav_title":             {"zh": "导航",             "en": "Navigation"},
    "audit_nav_desc":              {"zh": "如果你是从主报告跳转进来的，这里直接返回。", "en": "Return to the main benchmark report."},
    "audit_th_left_model":         {"zh": "左模型",           "en": "Left Model"},
    "audit_th_pair_id":            {"zh": "Pair ID",          "en": "Pair ID"},
    "audit_th_left_candidate":     {"zh": "左候选 Bug",       "en": "Left Candidate"},
    "audit_th_right_model":        {"zh": "右模型",           "en": "Right Model"},
    "audit_th_right_candidate":    {"zh": "右候选 Bug",       "en": "Right Candidate"},
    "audit_th_relation":           {"zh": "语义关系",         "en": "Semantic Relation"},
    "audit_th_blocking":           {"zh": "阻断原因",         "en": "Blocking Reason"},
    "audit_th_score":              {"zh": "得分",             "en": "Score"},
    # benchmark page — hero
    "bench_title":                 {"zh": "独立 RTL 缺陷发现能力基准评测", "en": "Independent RTL Defect Discovery BugReview"},
    "dut_label":                   {"zh": "被测DUT", "en": "DUT"},
    "bench_hero_desc":             {"zh": "以 <span class=\"hl\">DUT 级独立 RTL 缺陷</span> 为标准答案单位，将模型报告的多个验证现象映射到 GT-RTL 根因并去重，衡量<span class=\"hl\">真实 RTL 缺陷发现能力</span>。现象覆盖度和证据链深度作为辅助参考。",
                                    "en": "The DUT-level <span class=\"hl\">independent RTL defect</span> is the ground-truth unit. Model-reported symptoms are mapped to GT-RTL root causes and deduplicated to measure <span class=\"hl\">real RTL defect discovery</span>. Symptom breadth and evidence depth are auxiliary. Verbatim source evidence may remain in its original language."},
    # stat cards
    "stat_models":                 {"zh": "对比模型",         "en": "Models Compared"},
    "stat_canonical_bugs":         {"zh": "RTL 缺陷总数",     "en": "Total RTL Defects"},
    "stat_rtl_root_bugs":          {"zh": "最终确认独立 RTL 缺陷", "en": "Finalized Independent RTL Defects"},
    "stat_canonical_desc":         {"zh": "DUT 级 GT-RTL 真值集", "en": "DUT-level GT-RTL truth set"},
    "stat_rtl_root_desc":          {"zh": "GT 存档 {archived} 条；待 GT 复核 {pending} 条", "en": "{archived} archived GT entries; {pending} pending GT review"},
    "stat_multi_model":            {"zh": "多模型共有缺陷",   "en": "Defects Shared by Models"},
    "stat_single_model":           {"zh": "单模型独有缺陷",   "en": "Single-Model Defects"},
    "stat_llm_pairs":              {"zh": "LLM 评判对",       "en": "LLM Judged Pairs"},
    "stat_llm_pairs_desc":         {"zh": "过滤后需 LLM 判断的对", "en": "pairs requiring LLM judgment after filtering"},
    "stat_audit":                  {"zh": "未合并审计",       "en": "Non-Merge Audit"},
    "stat_audit_desc":             {"zh": "{audit_pct:.0f}% 确认不合并", "en": "{audit_pct:.0f}% confirmed non-merge"},
    # score section
    "score_title":                 {"zh": "现象覆盖评分对比", "en": "Symptom Score Comparison (Auxiliary)"},
    "score_desc":                  {"zh": "辅助口径：按标准 Bug 现象加权计分（重放确认=5, RTL支撑=4, 波形支撑=3, 执行支撑=2, 覆盖率/声明=1）。满分 = {total_bugs} Bug × 5 = <strong>{max_possible}</strong>，归一化 = 实际/满分。策略: {policy_ver}",
                                    "en": "Auxiliary: weighted symptom-level scoring (Replay=5, RTL=4, Waveform=3, Execution=2, Coverage/Claim=1). Max = {total_bugs} bugs × 5 = <strong>{max_possible}</strong>, normalized = actual / max. Policy: {policy_ver}"},
    "root_score_title":            {"zh": "Bug 总览", "en": "Bug Overview"},
    "root_score_title_replayed":    {"zh": "Bug 总览（已复用 Replay 验证）", "en": "Bug Overview (Replay Verified)"},
    "root_score_title_provisional": {"zh": "Bug 总览（Replay未完成）", "en": "Bug Overview (Replay Incomplete)"},
    "root_score_desc":             {"zh": "按当前已确认的独立 RTL 缺陷展示模型命中。卡片左侧数字为命中 GT/最终确认独立 RTL 缺陷；不重叠 RTL 源码行数为模型命中缺陷对应源码范围的并集。最终确认: {mapped_bug_total}；GT 存档: {verified_bug_total}；待 GT 复核: {pending_bug_total}。策略版本: {policy_ver}",
                                    "en": "Model hits are evaluated against currently finalized independent RTL defects. The left metric is hit GT entries / finalized independent RTL defects; non-overlapping RTL source lines are the union of source ranges for model-hit defects. Finalized: {mapped_bug_total}; archived GT entries: {verified_bug_total}; pending GT review: {pending_bug_total}. Policy: {policy_ver}"},
    "root_card_confirmed":          {"zh": "命中 GT/最终确认独立 RTL 缺陷", "en": "Hit GT / Finalized Independent RTL Defects"},
    "root_card_found":              {"zh": "发现根因", "en": "Roots Found"},
    "root_card_symptoms":           {"zh": "初始报告 Bug", "en": "Initial Reported Bugs"},
    "root_card_evidence":           {"zh": "不重叠 RTL 源码行", "en": "Non-overlapping RTL Source Lines"},
    "root_card_evidence_bar":       {"zh": "RTL 证据行覆盖占比", "en": "Evidence line coverage ratio"},
    "root_card_breadth":            {"zh": "覆盖广度", "en": "Breadth"},
    "root_card_breadth_high":       {"zh": "高", "en": "high"},
    "root_card_breadth_medium":     {"zh": "中", "en": "medium"},
    "root_card_breadth_low":        {"zh": "低", "en": "low"},
    "root_card_breadth_none":       {"zh": "无", "en": "none"},
    "root_card_local_cov":          {"zh": "局部窗口覆盖", "en": "Local Window Coverage"},
    "root_card_local_cov_detail":   {"zh": "{rate}（{count} 个根因窗口）", "en": "{rate} ({count} root windows)"},
    "root_card_best":               {"zh": "最优", "en": "Best"},
    "root_card_verified":           {"zh": "已确认", "en": "Confirmed"},
    "root_card_unverified":         {"zh": "待验证", "en": "Unverified"},
    "root_card_pending_replay":     {"zh": "待回放", "en": "Pending Replay"},
    "root_card_not_reproduced":     {"zh": "未复现", "en": "Not Reproduced"},
    "root_card_blocked":             {"zh": "受阻", "en": "Blocked"},
    "gt_defect_table_title":        {"zh": "GT 缺陷详情", "en": "GT Defect Details"},
    "gt_defect_details_link":       {"zh": "查看 GT 缺陷详情", "en": "View GT Defect Details"},
    "gt_defect_table_desc":         {"zh": "独立 RTL 缺陷 → 现象 → RTL Root 映射链路及模型命中状态", "en": "Independent RTL defect → symptom → RTL root mapping chain and model hit status."},
    "gt_th_id":                     {"zh": "GT ID", "en": "GT ID"},
    "gt_th_location":               {"zh": "RTL 位置", "en": "RTL Location"},
    "gt_th_mode":                   {"zh": "缺陷类型", "en": "Failure Mode"},
    "gt_th_models":                 {"zh": "命中模型", "en": "Hit Models"},
    "gt_th_status":                 {"zh": "回放状态", "en": "Replay Status"},
    "gt_th_chain":                  {"zh": "关联链路", "en": "Mapping Chain"},
    "gt_pending_mapping_review":   {"zh": "待 GT 映射复核", "en": "Pending GT Mapping Review"},
    "gt_legend_confirmed":          {"zh": "「重放确认」：该模型全部症状均通过回放验证", "en": "\u201cReplay Confirmed\u201d: all symptoms passed replay verification."},
    "gt_legend_partial":            {"zh": "「重放部分确认」：该模型至少一个症状未完全通过回放", "en": "\u201cPartial Confirmed\u201d: at least one symptom not fully verified."},
    "gt_legend_pending":            {"zh": "「执行支撑」：该模型至少一个症状仅执行支撑，尚未回放", "en": "\u201cExecution Supported\u201d: at least one symptom pending replay."},
    "gt_legend_rtl":                {"zh": "「RTL支撑」：该模型至少一个症状仅RTL级支撑", "en": "\u201cRTL Supported\u201d: at least one symptom only at RTL level."},
    "gt_legend_both":               {"zh": "多模型命中同一缺陷时，以", "en": "When multiple models hit the same defect, use "},
    "gt_legend_suffix":             {"zh": "区分各模型的回放验证状态", "en": " to distinguish replay status."},
    "gt_not_hit":                   {"zh": "—", "en": "—"},
    "fm_handshake_failure":         {"zh": "握手失败", "en": "Handshake Failure"},
    "fm_reset_state_mismatch":      {"zh": "复位状态不匹配", "en": "Reset State Mismatch"},
    "fm_protocol_violation":        {"zh": "协议违规", "en": "Protocol Violation"},
    "fm_output_mismatch_after_done":{"zh": "完成信号后输出不匹配", "en": "Output Mismatch After Done"},
    "fm_routing_or_selection_failure":{"zh": "路由/选择错误", "en": "Routing or Selection Failure"},
    "fm_done_completion_failure":   {"zh": "完成信号异常", "en": "Done Completion Failure"},
    "fm_ordering_or_concurrency_failure":{"zh": "排序/并发错误", "en": "Ordering or Concurrency Failure"},
    "fm_backpressure_failure":      {"zh": "背压失败", "en": "Backpressure Failure"},
    "fm_x_z_propagation":           {"zh": "X/Z 传播", "en": "X/Z Propagation"},
    "root_replay_bypassed_note":    {"zh": " <span class='note-tag'>临时结构排名：replay 存在 blocked/pending/partial，不能作为最终真实性结论；blocked 不等于未复现。</span>", "en": " <span class='note-tag'>Provisional structural ranking: replay is blocked, pending, or partial. This is not a final authenticity conclusion; blocked is not not-reproduced.</span>"},
    "root_card_replay_note":        {"zh": "<span class='note-tag'>Replay 验证状态</span>", "en": "<span class='note-tag'>Replay status</span>"},
    "root_card_no_rtl_evidence":    {"zh": "缺少 RTL 锚点证据 — {n} 个症状未映射到根因", "en": "No RTL anchor evidence — {n} symptoms not mapped to roots"},
    "symptom_score_title":         {"zh": "现象覆盖评分对比", "en": "Symptom Coverage Score Comparison"},
    "coverage_metrics_title":      {"zh": "验证覆盖指标对比", "en": "Verification Coverage Metrics"},
    "coverage_metrics_desc":       {"zh": "与 RTL 根因发现同级展示，但不计入 Bug 发现主排名。功能覆盖率使用 Toffee bin，行覆盖率使用 RTL 可覆盖行。", "en": "Displayed alongside RTL root discovery but excluded from the bug-discovery ranking. Functional coverage uses Toffee bins; line coverage uses coverable RTL lines."},
    "func_tags_detail_title":      {"zh": "功能覆盖标签明细", "en": "Function Coverage Tag Details"},
    "func_tags_detail_desc":       {"zh": "各模型运行中涉及的具体功能组（FG）、功能类（FC）、覆盖点（CK）及 Bug 组（BG）清单。", "en": "Full listing of functional groups (FG), function categories (FC), checkpoints (CK), and bug groups (BG) used in each model run."},
    "run_source_title":            {"zh": "模型运行来源",       "en": "Model Run Sources"},
    "run_source_desc":             {"zh": "仅纳入明确标记 all_completed=true 的完整运行；没有合格运行时在表中说明排除原因。", "en": "Only runs explicitly marked all_completed=true are admitted; exclusions are explained when no eligible run exists."},
    "run_source_th_model":         {"zh": "模型",              "en": "Model"},
    "run_source_th_dut":           {"zh": "DUT",               "en": "DUT"},
    "run_source_th_run":           {"zh": "运行标识",           "en": "Run"},
    "run_source_th_input":         {"zh": "输入路径",           "en": "Input Path"},
    "run_source_th_reason":        {"zh": "状态 / 原因",        "en": "Status / Reason"},
    "coverage_not_comparable":     {"zh": "覆盖指标不可直接比较", "en": "Coverage metrics not directly comparable"},
    "score_normalized":            {"zh": "归一化",           "en": "Normalized"},
    "diagnostics_title":           {"zh": "结构化诊断模块",     "en": "Structured Diagnostics"},
    "diagnostics_desc":            {"zh": "结构化告警与分流，用于审计复核，不参与排名。", "en": "Structured alerts and routing for audit/review. Not used in ranking."},
    "diagnostics_non_rtl":         {"zh": "非 RTL 声明",       "en": "Non-RTL claims"},
    "diagnostics_total":           {"zh": "告警总数",           "en": "Diagnostics"},
    "diagnostics_quality":         {"zh": "质量条目",           "en": "Quality entries"},
    "diagnostics_code":            {"zh": "诊断码",             "en": "Code"},
    "diagnostics_severity":        {"zh": "级别",               "en": "Severity"},
    "diagnostics_entity":          {"zh": "对象",               "en": "Entity"},
    "diagnostics_message":         {"zh": "说明",               "en": "Message"},
    "diagnostics_empty":           {"zh": "暂无诊断。",         "en": "No diagnostics."},
    "empty_dut_title":             {"zh": "空 DUT 处理结果",   "en": "Empty DUT Result"},
    "empty_dut_desc":              {"zh": "该 DUT 已完成输入发现和 run graph 构建，但没有可参与比较的有效候选 Bug；因此没有 replay contract，重放自动跳过。",
                                    "en": "Input discovery and run graph construction completed for this DUT, but no eligible candidate bugs remained for comparison; no replay contracts were generated, so replay was skipped."},
    "empty_dut_model":             {"zh": "模型",               "en": "Model"},
    "empty_dut_tests":             {"zh": "测试数",             "en": "Tests"},
    "empty_dut_specs":             {"zh": "Spec 数",            "en": "Specs"},
    "empty_dut_candidates":        {"zh": "候选 Bug",           "en": "Candidate Bugs"},
    "empty_dut_replay":            {"zh": "Replay",             "en": "Replay"},
    "empty_dut_replay_skipped":    {"zh": "跳过：无 replay contract", "en": "Skipped: no replay contract"},
    # config section
    "config_semantic_judge":       {"zh": "语义裁判配置",     "en": "Semantic Judge Config"},
    "config_semantic_pairs":       {"zh": "语义配对策略",     "en": "Semantic Pair Strategy"},
    # overlap section
    "overlap_title":               {"zh": "Bug 现象覆盖详情", "en": "Symptom Coverage Detail (Auxiliary)"},
    "overlap_desc":                {"zh": "每个模型在各标准 Bug 中的发现/共有/独占情况。共有 = 至少与另一个模型共同发现，独占 = 仅该模型发现。",
                                    "en": "Found / Shared / Exclusive breakdown per model across canonical bugs. Shared = also found by another model; Exclusive = found only by this model."},
    "overlap_found":               {"zh": "发现 {found} 个",  "en": "Found {found}"},
    "overlap_shared":              {"zh": "共有 {shared} 个", "en": "Shared {shared}"},
    "overlap_exclusive":           {"zh": "独占 {excl} 个",   "en": "Exclusive {excl}"},
    "overlap_not_found":           {"zh": "未发现 {not_found} 个", "en": "Not found {not_found}"},
    # evidence donut section
    "evidence_title":              {"zh": "Bug 现象证据层级分布", "en": "Symptom Evidence Tier Distribution (Auxiliary)"},
    "evidence_desc":               {"zh": "每个模型发现 Bug 的证据强度构成。环形图越偏绿/青 = 证据链越强。",
                                    "en": "Evidence strength composition per model. Greener/cyan arcs = stronger evidence chain."},
    "evidence_found_count":        {"zh": "发现 {found_count} 个", "en": "Found {found_count}"},
    "evidence_total_bugs":         {"zh": "共 {total_all} 标准Bug现象", "en": "of {total_all} canonical bugs"},
    # evidence chain table
    "chain_title":                 {"zh": "Bug 现象证据链深度分析", "en": "Symptom Evidence Chain Depth Analysis (Auxiliary)"},
    "chain_desc":                  {"zh": "青色 = 证据链到达 RTL 定位；红色 = 证据链在 RTL 前断裂；灰色 = 无任何证据。{replay_chain_note}",
                                    "en": "Cyan = evidence chain reaches RTL; Red = chain broke before RTL; Gray = no evidence. {replay_chain_note}"},
    "chain_step_claim":            {"zh": "有 Claim",         "en": "Has Claim"},
    "chain_step_coverage":         {"zh": "有覆盖率",         "en": "Has Coverage"},
    "chain_step_test_exec":        {"zh": "有测试执行",       "en": "Has Test Exec"},
    "chain_step_waveform":         {"zh": "有波形",           "en": "Has Waveform"},
    "chain_step_rtl":              {"zh": "有 RTL 定位",      "en": "Has RTL Loc"},
    "chain_step_replay_candidate": {"zh": "有重放候选",       "en": "Replay Candidate"},
    "chain_step_replay_real":      {"zh": "有真实重放返回",   "en": "Real Replay Result"},
    "chain_step_replay_success":   {"zh": "重放成功复现",     "en": "Replay Reproduced"},
    "chain_note_no_replay":        {"zh": "本次未执行独立重放，因此未展示\"有真实重放返回/重放成功复现\"统计行。",
                                    "en": "Independent replay was not executed; \"Real Replay Result / Replay Reproduced\" rows are hidden."},
    "chain_note_with_replay":      {"zh": "本次已执行独立重放；\"有真实重放返回\"表示已拿到非 `not_run` 的 replay 返回，\"重放成功复现\"仅统计 `reproduced`。",
                                    "en": "Independent replay executed. \"Real Replay Result\" = non-not_run replay response received; \"Replay Reproduced\" = reproduced only."},
    "chain_col_evidence_layer":    {"zh": "证据层",           "en": "Evidence Layer"},
    # bug matrix
    "matrix_title":                {"zh": "Bug 现象矩阵", "en": "Symptom Bug Matrix (Auxiliary)"},
    "matrix_desc":                 {"zh": "&#10003; = 已发现（数字 = 证据得分），— = 未发现。悬停查看详情。",
                                    "en": "&#10003; = Found (number = evidence score), — = Not found. Hover for details."},
    "matrix_details_link":         {"zh": "查看 Bug 证据详情", "en": "View Bug Evidence Details"},
    "root_matrix_title":           {"zh": "RTL 行级 Bug 矩阵", "en": "RTL Root Bug Matrix"},
    "root_matrix_desc":            {"zh": "主评分口径：多个现象级 Bug 如果共享失败模式和 RTL 根因锚点，会归并为一个 RTL 根因 Bug。代表现象复用现象矩阵中的属性描述；仅在分类明确时附带规范失败模式。",
                                    "en": "Primary scoring view: symptom bugs sharing a failure mode and RTL root anchor are folded into one RTL root bug. The representative symptom reuses the property description; a normalized failure mode is appended only when classified."},
    "root_matrix_th_root":          {"zh": "RTL 根因 Bug",     "en": "RTL Root Bug"},
    "root_matrix_th_anchor":        {"zh": "RTL 锚点",         "en": "RTL Anchor"},
    "root_matrix_th_mode":          {"zh": "代表现象",         "en": "Representative Symptom"},
    "root_matrix_th_symptoms":      {"zh": "现象 Bug",         "en": "Symptoms"},
    "root_matrix_found":            {"zh": "✓ {count} 个现象", "en": "✓ {count} symptoms"},
    "root_matrix_not_found":        {"zh": "—",                "en": "—"},
    "matrix_th_bug":               {"zh": "标准 Bug",         "en": "Canonical Bug"},
    "matrix_th_property":          {"zh": "属性描述",         "en": "Property"},
    "matrix_th_signals":           {"zh": "相关信号",         "en": "Signals"},
    "matrix_th_rtl_loc":           {"zh": "RTL 定位",         "en": "RTL Location"},
    "matrix_signals_none":         {"zh": "无",               "en": "none"},
    "matrix_cell_tier":            {"zh": "证据层级",         "en": "Evidence tier"},
    "evidence_supporting":        {"zh": "辅助证据",         "en": "Supporting evidence"},
    "evidence_tag_coverage":      {"zh": "覆盖率",           "en": "coverage"},
    "evidence_tag_waveform":      {"zh": "波形",             "en": "waveform"},
    "evidence_tag_rtl":           {"zh": "RTL",              "en": "RTL"},
    "evidence_tag_replay":        {"zh": "重放",             "en": "replay"},
    "evidence_tag_replay_candidate": {"zh": "重放候选",      "en": "replay candidate"},
    "evidence_tag_reproduced":    {"zh": "已复现",           "en": "reproduced"},
    "evidence_tag_not_reproduced":{"zh": "未复现",           "en": "not reproduced"},
    "evidence_tag_not_run":       {"zh": "未执行",           "en": "not run"},
    "coverage_source_single_test": {"zh": "单测试覆盖",       "en": "single-test coverage"},
    "coverage_source_multi_test":  {"zh": "多测试覆盖",       "en": "multi-test coverage"},
    "coverage_source_merged_run":  {"zh": "合并运行覆盖",     "en": "merged-run coverage"},
    "coverage_source_mixed":       {"zh": "混合覆盖",         "en": "mixed coverage"},
    # audit section (inline in bench page)
    "audit_inline_title":          {"zh": "跨模型语义审计",   "en": "Cross-Model Semantic Audit"},
    "audit_inline_desc":           {"zh": "LLM 评判 <strong>{semantic}</strong> 对跨模型候选，其中 <strong>{audit}</strong> 对被标记为\"相似但不应合并\"。{audit_display_note}",
                                    "en": "LLM judged <strong>{semantic}</strong> cross-model candidate pairs; <strong>{audit}</strong> pairs marked \"similar but should not merge\". {audit_display_note}"},
    "audit_view_full":             {"zh": "查看/导出全量明细", "en": "View / Export Full Detail"},
    "audit_display_all":           {"zh": "当前表格展示全部 {count} 条", "en": "Showing all {count} entries"},
    "audit_display_partial":       {"zh": "当前表格展示 {shown} / {total} 条；优先展示 related symptoms 与高相关项。全量明细见 audit 页面",
                                    "en": "Showing {shown} / {total} entries; related symptoms and high-score items prioritized. Full detail on audit page"},
    "audit_appeal_queue":          {"zh": "复审队列",         "en": "Review Queue"},
    "review_page_title":           {"zh": "复审队列",         "en": "Review Queue"},
    "review_page_desc":            {"zh": "这里集中展示需要复核的候选：LLM 判同一 Bug 但结构分数过低、LLM 判不同 Bug 但结构分数较高，以及 replay 未复现但仍有强结构证据的特殊情况。", "en": "This page collects candidates that need review: LLM same-bug decisions with low structural support, LLM different-bug decisions with high structural support, and replay-not-reproduced cases that still carry strong structural evidence."},
    "review_queue_label":          {"zh": "复审队列",         "en": "Review Queue"},
    "review_note":                 {"zh": "这些条目是复核材料，不是主裁判聚类结果。", "en": "These rows are review material, not primary clustering decisions."},
    "audit_empty":                 {"zh": "暂无审计记录。", "en": "No audit entries."},
    "audit_empty_all_same":         {"zh": "当前所有跨模型候选对（共 {total} 对）均判定为同一缺陷并已自动合并，无分歧阻断项；可访问上方「复审队列」核实成对判定。", "en": "All cross-model candidate pairs ({total} total) were resolved as same bug and merged. No non-merge conflicts recorded. See 'Review Queue' above."},
    "review_kind_appeal":          {"zh": "同一 Bug 低分复审", "en": "same-bug low-score appeal"},
    "review_kind_conflict":        {"zh": "不同 Bug 高分冲突", "en": "different-bug high-score conflict"},
    "review_section_appeal":       {"zh": "同一 Bug 低分复审", "en": "Same-Bug Low-Score Appeals"},
    "review_section_appeal_desc":  {"zh": "筛选条件：relation == same bug 且 score < 2。LLM 认为可能是同一 Bug，但结构化证据暂时不足。", "en": "Filter: relation == same bug and score < 2. The LLM sees a possible same bug, but structural support is weak."},
    "review_section_conflict":     {"zh": "不同 Bug 高分冲突", "en": "Different-Bug High-Score Conflicts"},
    "review_section_conflict_desc":{"zh": "筛选条件：relation == different bugs 且 score >= 4。LLM 认为不是同一 Bug，但本地结构分数很高。", "en": "Filter: relation == different bugs and score >= 4. The LLM says different bugs, but the local structural score is very high."},
    "review_section_replay":       {"zh": "重放未复现复审",   "en": "Replay Not Reproduced Review"},
    "review_section_replay_desc":  {"zh": "筛选条件：replay == not_reproduced 且仍有 RTL / 覆盖率 / 波形 等结构证据。此类候选不直接判 0，而是降分并进入复核。", "en": "Filter: replay == not_reproduced and structural evidence such as RTL / coverage / waveform still exists. These candidates are not forced to 0; they are down-scored and sent for review."},
    "review_no_entries":           {"zh": "暂无条目。",       "en": "No entries."},
    "review_th_id":                {"zh": "复审 ID",          "en": "Review ID"},
    "review_th_status":            {"zh": "状态",             "en": "Status"},
    "review_th_source":            {"zh": "来源",             "en": "Source"},
    "review_th_dut":               {"zh": "DUT",              "en": "DUT"},
    "review_th_pair":              {"zh": "候选 Pair",        "en": "Candidate Pair"},
    "review_th_pair_id":           {"zh": "Pair ID",          "en": "Pair ID"},
    "review_th_candidate":         {"zh": "候选 ID",          "en": "Candidate ID"},
    "review_th_base_score":        {"zh": "结构分数",          "en": "Structural Score"},
    "review_th_base_relation":     {"zh": "初判关系",          "en": "Base Relation"},
    "review_th_review_relation":   {"zh": "复审关系",          "en": "Review Relation"},
    "review_th_confidence":        {"zh": "置信度",            "en": "Confidence"},
    "review_th_supported":         {"zh": "支持合并",          "en": "Merge Supported"},
    "review_th_risk":              {"zh": "合并风险",          "en": "Merge Risk"},
    "review_th_support_risk":      {"zh": "支持/风险",        "en": "Support / Risk"},
    "review_th_evidence":          {"zh": "证据锚点",          "en": "Evidence Links"},
    "review_th_missing":           {"zh": "缺失证据",          "en": "Missing Evidence"},
    "review_th_replay_status":     {"zh": "重放状态",          "en": "Replay Status"},
    "review_th_replay_support":    {"zh": "结构支撑",          "en": "Structural Support"},
    "review_th_replay_reason":     {"zh": "原因",              "en": "Reason"},
    "review_th_replay_rtl":        {"zh": "RTL",              "en": "RTL"},
    "review_th_replay_coverage":   {"zh": "覆盖率",            "en": "Coverage"},
    "appeal_page_title":           {"zh": "跨模型语义复审队列", "en": "Cross-Model Semantic Review Queue"},
    "appeal_page_desc":            {"zh": "这里集中展示需要人工或伪人工复核的争议 pair。", "en": "This page collects disputed pairs that need human or pseudo-human review."},
    "appeal_back_to_main":         {"zh": "← 返回 BugReview 主界面", "en": "← Back to BugReview"},
    "appeal_entries_title":        {"zh": "复审条目",         "en": "Appeal Entries"},
    "appeal_entries_desc":         {"zh": "这些条目是复审队列，不是主裁判结果。", "en": "These entries are appeal records, not primary judge decisions."},
    "appeal_only_note":            {"zh": "只收 relation == same bug 且 score < 2 的 pair。", "en": "Only pairs with relation == same bug and score < 2 are included."},
    "appeal_no_entries":           {"zh": "暂无复审条目。",     "en": "No appeal entries."},
    # model_score_summary page
    "summary_page_title":          {"zh": "BugReview 评分摘要", "en": "BugReview Score Summary"},
    "summary_policy_version":      {"zh": "策略版本",         "en": "Policy Version"},
    "summary_semantic_pairs":      {"zh": "语义配对策略",     "en": "Semantic Pair Strategy"},
    "summary_scoring_policy":      {"zh": "评分策略",         "en": "Scoring Policy"},
    "summary_normalized":          {"zh": "归一化",           "en": "Normalized"},
    "summary_found":               {"zh": "发现",             "en": "Found"},
    "summary_rating":              {"zh": "评级",             "en": "Rating"},
    "summary_basis":               {"zh": "依据",             "en": "Basis"},
    "summary_empty":               {"zh": "无评分数据",       "en": "No scoring data"},
    "summary_policy_empty":        {"zh": "无",               "en": "None"},
    # page titles
    "page_title_benchmark":        {"zh": "BugReview 对比报告", "en": "BugReview Comparison Report"},
    "page_title_audit":            {"zh": "跨模型语义审计 — BugReview", "en": "Cross-Model Semantic Audit — BugReview"},
    "page_title_summary":          {"zh": "BugReview 评分摘要", "en": "BugReview Score Summary"},
}


def _t(key: str, lang: str) -> str:
    """Return the translation for *key* in *lang* (``"zh"`` or ``"en"``)."""
    entry = _TEXT.get(key, {})
    return entry.get(lang, entry.get("zh", key))


# ── helpers ────────────────────────────────────────────────────────

def _artifact_evidence_items(record: Dict[str, object]) -> List[Dict[str, object]]:
    artifact_evidence = record.get("artifact_evidence", [])
    if not isinstance(artifact_evidence, list):
        return []
    return [item for item in artifact_evidence if isinstance(item, dict)]


def _primary_artifact_evidence(record: Dict[str, object]) -> Dict[str, object]:
    artifact_evidence = _artifact_evidence_items(record)
    if not artifact_evidence:
        return {}
    for item in artifact_evidence:
        if item.get("waveform_summary") or item.get("waveform_conversion_summary") or item.get("waveform_observations"):
            return item
    return artifact_evidence[0]


def _has_real_replay_result(replay_results: object) -> bool:
    if not isinstance(replay_results, list):
        return False
    return any(
        isinstance(item, dict) and item.get("status") not in _REPLAY_NOT_EXECUTED_STATUSES
        for item in replay_results
    )


def _has_successful_replay_result(replay_results: object) -> bool:
    if not isinstance(replay_results, list):
        return False
    return any(
        isinstance(item, dict) and item.get("status") in _REPLAY_SUCCESS_STATUSES
        for item in replay_results
    )


def _semantic_llm_config_summary(data: Dict[str, object]) -> List[str]:
    config = data.get("semantic_llm_config", {})
    if not isinstance(config, dict):
        return []
    parts = []
    for key in ("provider", "model", "base_url", "api_key"):
        value = config.get(key)
        if key == "api_key":
            parts.append(f"api_key={'set' if value else 'unset'}")
        elif value:
            parts.append(f"{key}={value}")
    return parts


def _semantic_pair_config_summary(data: Dict[str, object]) -> List[str]:
    config = data.get("semantic_pair_config", {})
    if not isinstance(config, dict) or not config:
        config = {"mode": "strict_filter", "budget": 500, "recall": "balanced", "source": "legacy_default_inferred"}
    parts = []
    for key in ("mode", "budget", "recall", "source"):
        value = config.get(key)
        if value is not None and value != "":
            parts.append(f"{key}={value}")
    return parts


def _evidence_tier_label(value: object, lang: str = "zh") -> str:
    tier = str(value or "").strip()
    tier_keys = {
        "replay_confirmed": "tier_replay_confirmed",
        "replay_partial_confirmed": "tier_replay_partial_confirmed",
        "replay_contradicted": "tier_replay_contradicted",
        "replay_contradicted_review": "tier_replay_contradicted_review",
        "replay_snapshot_changed_review": "tier_replay_snapshot_changed_review",
        "rtl_supported": "tier_rtl_supported",
        "waveform_supported": "tier_waveform_supported",
        "execution_supported_pending_replay": "tier_execution_supported",
        "coverage_supported": "tier_coverage_supported",
        "claim_only": "tier_claim_only",
        "not_found": "tier_not_found",
        "excluded_declared_candidate": "tier_excluded_declared",
    }
    key = tier_keys.get(tier)
    if key:
        return _t(key, lang)
    return tier or "n/a"


def _coverage_source_label(value: str, lang: str = "zh") -> str:
    coverage = str(value or "").strip()
    coverage_keys = {
        "single_test": "coverage_source_single_test",
        "multi_test": "coverage_source_multi_test",
        "merged_run": "coverage_source_merged_run",
        "mixed": "coverage_source_mixed",
    }
    if not coverage:
        return coverage
    parts = [part.strip() for part in coverage.split(",") if part.strip()]
    if not parts:
        return coverage
    return "+".join(_t(coverage_keys.get(part), lang) if coverage_keys.get(part) else part for part in parts)


def _evidence_support_tags(record: Dict[str, object], lang: str = "zh") -> List[str]:
    has_coverage = False
    coverage_summary = str(record.get("coverage_evidence_summary") or "").strip()
    if coverage_summary and coverage_summary != "none":
        has_coverage = True

    waveform_present = False
    waveform_summary = record.get("waveform_summary", {})
    if isinstance(waveform_summary, dict) and waveform_summary:
        waveform_present = True
    if record.get("waveform_observation_preview") or record.get("waveform_observations") or record.get("waveform_observation_count"):
        waveform_present = True
    artifact_evidence = _primary_artifact_evidence(record)
    artifact_waveform_summary = artifact_evidence.get("waveform_summary", {}) if artifact_evidence else {}
    if isinstance(artifact_waveform_summary, dict) and artifact_waveform_summary:
        waveform_present = True
    if artifact_evidence and artifact_evidence.get("waveform_observations"):
        waveform_present = True
    rtl_present = bool(record.get("rtl_region_preview") or record.get("rtl_dependency_preview") or record.get("rtl_regions"))

    replay_statuses = []
    for result in record.get("replay_results", []) or []:
        if isinstance(result, dict) and result.get("status"):
            replay_statuses.append(str(result.get("status")))

    tags: List[str] = []
    if replay_statuses:
        tags.append(_t("evidence_tag_replay", lang))

    if rtl_present:
        tags.append(_t("evidence_tag_rtl", lang))

    if waveform_present:
        tags.append(_t("evidence_tag_waveform", lang))

    if has_coverage:
        tags.append(_t("evidence_tag_coverage", lang))

    if record.get("replay_manifests"):
        tags.append(_t("evidence_tag_replay_candidate", lang))

    return tags


def _evidence_support_title(record: Dict[str, object], lang: str = "zh") -> str:
    tags = _evidence_support_tags(record, lang)
    if not tags:
        return _t("evidence_supporting", lang)
    return f"{_t('evidence_supporting', lang)}: " + " · ".join(tags)


def _diagnostic_summary(data: Dict[str, object]) -> Dict[str, object]:
    diagnostics = [item for item in data.get("diagnostics", []) or [] if isinstance(item, dict)]
    non_rtl_claims = [item for item in data.get("non_rtl_claims", []) or [] if isinstance(item, dict)]
    code_counts = defaultdict(int)
    severity_counts = defaultdict(int)
    for item in diagnostics:
        code_counts[str(item.get("code") or "unknown")] += 1
        severity_counts[str(item.get("severity") or "unknown")] += 1
    quality_counts = defaultdict(int)
    for record in data.get("benchmark_records", []) or []:
        if not isinstance(record, dict):
            continue
        quality = record.get("evidence_quality", {})
        if isinstance(quality, dict):
            quality_counts[str(quality.get("qualification") or "unknown")] += 1
    return {
        "diagnostics": diagnostics,
        "non_rtl_claims": non_rtl_claims,
        "code_counts": dict(sorted(code_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "quality_counts": dict(sorted(quality_counts.items())),
    }


_DIAGNOSTIC_MESSAGE_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "RTL regions exist but no dependency preview was attached": {
        "zh": "存在 RTL 区域，但未关联依赖预览",
        "en": "RTL regions exist but no dependency preview was attached",
    },
    "candidate has a replay manifest but no replay result is attached": {
        "zh": "候选 Bug 具有重放清册，但未附加重放结果",
        "en": "candidate has a replay manifest but no replay result is attached",
    },
    "replay contradicted the candidate but structural evidence remains": {
        "zh": "仿真重放与候选 Bug 产生矛盾，但仍存在结构化证据，需要人工复核",
        "en": "replay contradicted the candidate but structural evidence remains",
    },
    "candidate was explicitly excluded by the source declaration": {
        "zh": "候选 Bug 已被原始声明显式排除",
        "en": "candidate was explicitly excluded by the source declaration",
    },
    "claim appears to describe testbench, API, or infrastructure behavior rather than RTL": {
        "zh": "声明似乎描述了测试平台、API 或基础设施行为，而非 RTL 缺陷",
        "en": "claim appears to describe testbench, API, or infrastructure behavior rather than RTL",
    },
}

_DIAGNOSTIC_SEVERITY_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "WARNING": {"zh": "警告", "en": "WARNING"},
    "INFO":    {"zh": "提示", "en": "INFO"},
    "ERROR":   {"zh": "错误", "en": "ERROR"},
}


def _translate_diagnostic_message(msg: object, lang: str = "zh") -> str:
    if msg is None:
        return ""
    text = str(msg).strip()
    entry = _DIAGNOSTIC_MESSAGE_TRANSLATIONS.get(text)
    if entry and lang in entry:
        return entry[lang]
    return text


def _translate_diagnostic_severity(sev: object, lang: str = "zh") -> str:
    if sev is None:
        return ""
    text = str(sev).strip().upper()
    entry = _DIAGNOSTIC_SEVERITY_TRANSLATIONS.get(text)
    if entry and lang in entry:
        return entry[lang]
    return str(sev)


def _diagnostics_section_html(data: Dict[str, object], lang: str = "zh") -> str:
    summary = _diagnostic_summary(data)
    diagnostics = summary["diagnostics"]
    if not diagnostics and not summary["non_rtl_claims"]:
        return ""

    def esc(value: object) -> str:
        if value is None:
            return ""
        return html.escape(str(value))

    cards = [
        "<div class='stat-card'><span class='label'>{}</span><span class='value'>{}</span><span class='hint'>{}</span></div>".format(
            esc(_t("diagnostics_total", lang)),
            len(diagnostics),
            esc(", ".join(f"{k}={v}" for k, v in summary["severity_counts"].items()) or "n/a"),
        ),
        "<div class='stat-card'><span class='label'>{}</span><span class='value'>{}</span><span class='hint'>{}</span></div>".format(
            esc(_t("diagnostics_non_rtl", lang)),
            len(summary["non_rtl_claims"]),
            esc("n/a" if not summary["non_rtl_claims"] else ", ".join(sorted({str(item.get('model') or 'n/a') for item in summary["non_rtl_claims"]}))),
        ),
        "<div class='stat-card'><span class='label'>{}</span><span class='value'>{}</span><span class='hint'>{}</span></div>".format(
            esc(_t("diagnostics_quality", lang)),
            sum(summary["quality_counts"].values()),
            esc(", ".join(f"{k}={v}" for k, v in summary["quality_counts"].items()) or "n/a"),
        ),
    ]
    rows = []
    for item in diagnostics[:20]:
        rows.append(
            "<tr><td>{code}</td><td>{sev}</td><td>{entity}</td><td>{msg}</td></tr>".format(
                code=esc(item.get("code")),
                sev=esc(_translate_diagnostic_severity(item.get("severity"), lang)),
                entity=esc(item.get("entity_id")),
                msg=esc(_translate_diagnostic_message(item.get("message"), lang)),
            )
        )
    if not rows:
        rows.append("<tr><td colspan='4'>{}</td></tr>".format(esc(_t("diagnostics_empty", lang))))
    return """
    <section class="section">
      <div class="section-header">
        <div><h2>{title}</h2><p>{desc}</p></div>
      </div>
      <div class="stat-grid">{cards}</div>
      <div class="matrix-wrap">
        <table class="matrix-table">
          <thead><tr><th>{code}</th><th>{severity}</th><th>{entity}</th><th>{message}</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    """.format(
        title=_t("diagnostics_title", lang),
        desc=_t("diagnostics_desc", lang),
        cards="".join(cards),
        code=_t("diagnostics_code", lang),
        severity=_t("diagnostics_severity", lang),
        entity=_t("diagnostics_entity", lang),
        message=_t("diagnostics_message", lang),
        rows="".join(rows),
    )


def _select_balanced_model_pair_rows(entries: List[Dict[str, object]], limit: int) -> List[Dict[str, object]]:
    if limit <= 0 or not entries:
        return []
    grouped = defaultdict(list)
    for item in entries:
        pair_key = (str(item.get("left_model", "?")), str(item.get("right_model", "?")))
        grouped[pair_key].append(item)
    selected: List[Dict[str, object]] = []
    for pair_key in sorted(grouped.keys()):
        selected.append(grouped[pair_key][0])
        if len(selected) >= limit:
            return selected
    remaining: List[Dict[str, object]] = []
    for pair_key in sorted(grouped.keys()):
        remaining.extend(grouped[pair_key][1:])
    remaining.sort(key=lambda item: item.get("score", 0), reverse=True)
    selected.extend(remaining[: max(0, limit - len(selected))])
    return selected[:limit]


def _semantic_pair_id_map(data: Dict[str, object]) -> Dict[tuple, str]:
    pair_ids: Dict[tuple, str] = {}
    for index, item in enumerate(data.get("semantic_judgements", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        left_id = item.get("left_candidate_id")
        right_id = item.get("right_candidate_id")
        if not left_id or not right_id:
            continue
        pair_id = f"LLM-P{index:04d}"
        pair_ids[(left_id, right_id)] = pair_id
        pair_ids[(right_id, left_id)] = pair_id
    return pair_ids


def _rtl_location_label(region: Dict[str, object]) -> str:
    path = str(region.get("path") or "").strip()
    base = path.rstrip("/").split("/")[-1] if path else "unknown"
    start = region.get("line_start")
    end = region.get("line_end")
    if start and end:
        return f"{base}:{start}-{end}"
    if start:
        return f"{base}:{start}"
    return base


def _matrix_rtl_locations(row: Dict[str, object], model_names: List[str], records_by_key: Dict[tuple, Dict[str, object]]) -> tuple:
    seen = set()
    display_items: List[str] = []
    hover_items: List[str] = []
    canonical_bug = row.get("canonical_bug")
    for model in model_names:
        record = records_by_key.get((canonical_bug, model), {})
        if not isinstance(record, dict) or record.get("status") != "found":
            continue
        for region in record.get("rtl_regions", []) or []:
            if not isinstance(region, dict):
                continue
            label = _rtl_location_label(region)
            if not label or label in seen:
                continue
            seen.add(label)
            display_items.append(label)
            full_path = str(region.get("path") or label)
            reason = str(region.get("reason") or "").strip()
            hover = f"{model}: {full_path}"
            if region.get("line_start") and region.get("line_end"):
                hover += f":{region.get('line_start')}-{region.get('line_end')}"
            elif region.get("line_start"):
                hover += f":{region.get('line_start')}"
            if reason:
                hover += f" ({reason})"
            hover_items.append(hover)
    if not display_items:
        for region in row.get("rtl_regions", []) or []:
            if isinstance(region, dict):
                label = _rtl_location_label(region)
                if label and label not in seen:
                    seen.add(label)
                    display_items.append(label)
                    hover_items.append(str(region.get("path") or label))
    return display_items, hover_items


def _property_description_for_lang(
    row: Dict[str, object],
    records_by_key: Dict[tuple, Dict[str, object]],
    model_names: Sequence[str],
    lang: str,
) -> Tuple[str, str]:
    """Return (display_text, tooltip_text) for a matrix property description."""
    import re
    canonical_bug = row.get("canonical_bug")
    prop = str(row.get("property_text") or "").strip()

    # Step 1: Recover prop from claim_sources if missing in matrix row
    if not prop:
        for m in model_names:
            rec = records_by_key.get((canonical_bug, m), {})
            if isinstance(rec, dict):
                for cs in rec.get("claim_sources", []):
                    if isinstance(cs, dict) and cs.get("summary"):
                        prop = str(cs["summary"]).strip()
                        break
                if prop:
                    break

    # Candidate IDs collection
    candidate_ids = list(row.get("candidate_ids") or [])
    if not candidate_ids:
        for m in model_names:
            rec = records_by_key.get((canonical_bug, m), {})
            if isinstance(rec, dict) and rec.get("candidate_ids"):
                candidate_ids.extend(rec["candidate_ids"])

    parsed_ck = ""
    for cid in candidate_ids:
        m = re.search(r'fg_([^_]+(?:_[^_]+)*?)_fc_([^_]+(?:_[^_]+)*?)_ck_(.+)$', str(cid))
        if m:
            fg, fc, ck = m.groups()
            ck_clean = re.sub(r'_[0-9a-f]{4,}$|_other$', '', ck).replace("_", " ").strip().title()
            parsed_ck = f"{ck_clean} ({fg})"
            break

    # If Chinese requested
    if lang == "zh":
        if prop:
            return prop, prop
        if parsed_ck:
            return f"检查项: {parsed_ck}", f"基于测试候选生成的属性检查: {parsed_ck}"
        fail_mode = str(row.get("failure_mode") or "")
        if fail_mode and fail_mode != "unknown":
            return f"故障模式: {fail_mode}", f"未解析到详细声明，关联故障模式: {fail_mode}"
        return "n/a", "n/a"

    # If English requested
    if row.get("property_text_en"):
        en_val = str(row["property_text_en"]).strip()
        tip = f"{en_val} [原始声明: {prop}]" if prop else en_val
        return en_val, tip

    if parsed_ck:
        tip = f"{parsed_ck} [Original Claim: {prop}]" if prop else parsed_ck
        return parsed_ck, tip

    translations = [
        ("再次使能重新装载", "Rearm Reload Delay Timeout"),
        ("到零触发", "Trigger When Counter At Zero"),
        ("低字节写掩码", "Low-Byte Write Mask Updates"),
        ("高字节写掩码", "High-Byte Write Mask Updates"),
        ("写掩码", "Write Mask Updates"),
        ("握手失败", "Handshake Protocol Failure"),
        ("延迟超时", "Delay Timeout Violation"),
        ("复位保持", "Reset Hold State Violation"),
        ("状态机转换", "FSM State Transition Anomaly"),
    ]
    for zh_pat, en_pat in translations:
        if zh_pat in prop:
            return en_pat, f"{en_pat} [Original Claim: {prop}]"

    fail_mode = str(row.get("failure_mode") or "")
    if fail_mode and fail_mode != "unknown":
        en_mode = fail_mode.replace("_", " ").title()
        tip = f"{en_mode} [Original Claim: {prop}]" if prop else en_mode
        return en_mode, tip

    return prop or "n/a", prop or "n/a"


def _build_audit_rows(entries: List[Dict[str, object]], pair_id_map: Dict[tuple, str] = None) -> str:
    def esc(value: object, max_len: int = 0) -> str:
        if value is None:
            return ""
        s = html.escape(str(value))
        if max_len and len(s) > max_len:
            return "<span title='{}'>{}{}</span>".format(s, s[:max_len], "&hellip;")
        return s

    def trunc(s: str, n: int) -> str:
        if len(s) > n:
            return "<span title='{}'>{}{}</span>".format(html.escape(s, quote=True), html.escape(s[:n]), "&hellip;")
        return html.escape(s)

    audit_rows = ""
    pair_id_map = pair_id_map or {}
    for a in entries:
        left_id = trunc(str(a.get("left_candidate_id", "?")), 40)
        right_id = trunc(str(a.get("right_candidate_id", "?")), 40)
        pair_id = pair_id_map.get((a.get("left_candidate_id"), a.get("right_candidate_id")), "")
        rel = str(a.get("semantic_relation", "?"))
        reasons = ", ".join(a.get("blocking_reasons", [])[:3])
        score = a.get("score", 0)
        rel_cls = "rel-diff" if "different" in rel else ("rel-related" if "related" in rel else "rel-insuf")
        audit_rows += (
            "<tr><td class='pair-id-cell'>{pair_id}</td>"
            "<td class='am'>{lm}</td><td class='cid-cell' title='{lt}'>{lc}</td>"
            "<td class='am'>{rm}</td><td class='cid-cell' title='{rt}'>{rc}</td>"
            "<td class='{rcls}'>{rel}</td><td class='ar'>{reasons}</td>"
            "<td class='as'>{score}</td></tr>"
        ).format(
            pair_id=esc(pair_id or "n/a"),
            lm=esc(a.get("left_model", "?")), lt=esc(a.get("left_candidate_id", "")),
            lc=left_id, rm=esc(a.get("right_model", "?")),
            rt=esc(a.get("right_candidate_id", "")), rc=right_id,
            rel=rel, rcls=rel_cls, reasons=esc(reasons, 60), score=score,
        )
    return audit_rows


def _benchmark_page_css(audit_full: bool = False) -> str:
    extra = """
    .audit-wrap-full {{
      max-height: none;
      overflow: visible;
    }}
    """ if audit_full else ""
    css = ("""
    :root {{
      --bg: #f8fafc; --card: #ffffff; --ink: #1e293b; --muted: #64748b;
      --border: #e2e8f0;
      --radius: clamp(10px, 1.2vw, 18px); --radius-sm: clamp(6px, 0.8vw, 12px);
      --gap: clamp(8px, 1vw, 18px);
      --accent: #06b6d4;
      --accent-2: #b45309;
      --accent-3: #0369a1;
      --warn: #f59e0b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "PingFang SC","Noto Sans SC",-apple-system,"Segoe UI",sans-serif;
      color: var(--ink); background: var(--bg); line-height: 1.6;
      font-size: clamp(13px, 1vw, 16px);
    }}
    .page {{
      width: min(98%, 1800px); margin: 0 auto;
      padding: clamp(12px, 1.5vw, 36px) clamp(10px, 1.8vw, 40px);
    }}
    h1 {{ font-size: clamp(18px, 1.8vw, 32px); font-weight: 700; letter-spacing: -0.02em; }}
    h2 {{ font-size: clamp(14px, 1.3vw, 22px); font-weight: 700; }}
    h3 {{ font-size: clamp(12px, 1.1vw, 18px); font-weight: 600; }}

    .hero, .section {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: var(--radius); box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }}
    .hero {{
      padding: clamp(16px, 2vw, 40px) clamp(18px, 2.5vw, 48px);
      margin-bottom: var(--gap);
    }}
    .hero h1 {{ margin: 0 0 clamp(4px, 0.5vw, 12px); font-size: clamp(18px, 1.8vw, 32px); line-height: 1.2; }}
    .hero p {{
      margin: 0; color: var(--muted); font-size: clamp(11px, 0.95vw, 16px); line-height: 1.7; max-width: 60em;
    }}
    .hl {{ color: var(--accent); font-weight: 600; }}
    .dut-badge {{
      float: right; padding: 0.15em 0.6em;
      background: #e0f2fe; color: #0369a1; border-radius: 999px;
      font-size: inherit; font-weight: 700;
    }}
    .section {{
      padding: clamp(14px, 1.8vw, 32px);
      margin-bottom: var(--gap);
    }}
    .section-header {{
      display: flex; align-items: flex-start; justify-content: space-between;
      gap: 16px; margin-bottom: clamp(10px, 1vw, 18px);
    }}
    .section-header h2 {{
      margin: 0 0 6px; font-size: clamp(14px, 1.3vw, 22px); letter-spacing: -0.02em;
    }}
    .section-header p {{
      margin: 0; color: var(--muted); font-size: clamp(10px, 0.8vw, 14px); line-height: 1.6;
    }}
    .top-nav {{
      display: flex; justify-content: space-between; align-items: center;
      gap: 12px; margin-bottom: clamp(10px, 1vw, 18px);
    }}
    .mini-link, .back-link {{
      display: inline-flex; align-items: center; gap: 8px;
      text-decoration: none; color: var(--accent-3); font-weight: 700;
      background: var(--card); border: 1px solid var(--border);
      border-radius: 999px; padding: 8px 12px; white-space: nowrap;
    }}
    .mini-link:hover, .back-link:hover {{
      border-color: rgba(14,165,233,0.32); background: #f0f9ff;
    }}
    .meta-text {{
      color: var(--muted); font-size: clamp(12px, 0.85vw, 15px);
    }}
    .audit-rel {{
      display: flex; flex-wrap: wrap; gap: clamp(6px, 1vw, 18px);
      margin-bottom: clamp(10px, 1.2vw, 24px);
    }}
    .audit-rel-item {{
      background: #f8fafc; border: 1px solid var(--border);
      padding: clamp(6px, 0.7vw, 14px) clamp(10px, 1.2vw, 22px);
      border-radius: var(--radius-sm); font-size: clamp(11px, 0.85vw, 16px);
    }}
    .audit-rel-item b {{ color: var(--accent); font-size: clamp(14px, 1.2vw, 24px); }}
    .audit-wrap {{
      max-height: clamp(300px, 40vh, 600px); overflow-y: auto;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: #f8fafc;
    }}
    """ + extra + """
    .audit-table {{
      width: 100%; border-collapse: collapse;
      font-size: clamp(9px, 0.7vw, 13px);
    }}
    .audit-table thead {{ position: sticky; top: 0; z-index: 2; }}
    .audit-table th {{
      padding: clamp(5px, 0.5vw, 11px) clamp(6px, 0.6vw, 14px);
      text-align: left; background: #f8fafc;
      border-bottom: 2px solid #e2e8f0;
      font-size: clamp(8px, 0.6vw, 11px); color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap;
    }}
    .audit-table td {{
      padding: clamp(4px, 0.5vw, 9px) clamp(6px, 0.6vw, 14px);
      border-bottom: 1px solid #f1f5f9;
      max-width: clamp(80px, 10vw, 180px);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      vertical-align: top;
    }}
    .audit-table tbody tr:hover {{ background: #f0fdfa; }}
    .review-table {{
      table-layout: fixed;
      min-width: 1100px;
    }}
    .review-table th,
    .review-table td {{
      white-space: normal; overflow: visible; text-overflow: clip;
      overflow-wrap: anywhere; word-break: break-word;
      max-width: none; line-height: 1.45;
    }}
    .review-table th {{
      font-size: clamp(9px, 0.68vw, 12px); letter-spacing: 0.015em;
    }}
    .review-table .review-pair-id-col {{ width: 6%; font-family: "SFMono-Regular",Consolas,monospace; font-size: clamp(8px, 0.62vw, 11px); color: var(--accent); font-weight: 700; }}
    .review-table .review-id-col {{ width: 14%; font-family: "SFMono-Regular",Consolas,monospace; font-size: clamp(8px, 0.62vw, 11px); color: var(--accent-3); }}
    .review-table .review-status-col {{ width: 6%; }}
    .review-table .review-source-col {{ width: 9%; }}
    .review-table .review-dut-col {{ width: 7%; }}
    .review-table .review-pair-col {{ width: 20%; font-family: "SFMono-Regular",Consolas,monospace; font-size: clamp(8px, 0.62vw, 11px); }}
    .review-table .review-score-col {{ width: 5%; text-align: center; }}
    .review-table .review-relation-col {{ width: 7%; }}
    .review-table .review-compact-col {{ width: 6%; }}
    .review-table .review-wide-col {{ width: 8%; }}
    .cid-cell {{
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(9px, 0.68vw, 12px);
      color: var(--accent-3); font-weight: 500;
    }}
    .pair-id-cell {{
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(9px, 0.68vw, 12px);
      color: var(--accent); font-weight: 700; white-space: nowrap;
    }}
    .bug-id {{
      display: inline-block; background: var(--accent); color: #fff;
      font-size: clamp(9px, 0.68vw, 12px); font-weight: 700;
      padding: 2px 8px; border-radius: 4px; margin-right: 8px;
      font-family: "SFMono-Regular",Consolas,monospace;
    }}
    .am {{ font-weight: 600; }}
    .ar {{ color: var(--muted); }}
    .as {{ font-weight: 700; text-align: center; }}
    .rel-diff {{ color: #d97706; font-weight: 600; }}
    .rel-related {{ color: #8b5cf6; font-weight: 600; }}
    .rel-insuf {{ color: #dc2626; font-weight: 600; }}
    .lang-switch {{
      display: inline-flex; gap: 4px; background: #e2e8f0; padding: 2px;
      border-radius: 6px; vertical-align: middle;
    }}
    .lang-btn {{
      border: none; background: transparent; padding: 3px 10px;
      border-radius: 4px; font-size: 12px; cursor: pointer; color: #64748b;
      font-weight: 500; text-decoration: none; display: inline-block; transition: all 0.2s;
    }}
    .lang-btn.active {{
      background: #ffffff; color: #0284c7; font-weight: 700;
      box-shadow: 0 1px 2px rgba(0,0,0,0.08);
      cursor: default;
    }}
    @media (max-width: 800px) {{
      .page {{ width: calc(100vw - 10px); padding: 8px; }}
      .section-header, .top-nav {{ flex-direction: column; align-items: stretch; }}
    }}
    """)
    return css.replace("{{", "{").replace("}}", "}")


def _lang_switch_html(lang: str = "zh") -> str:
    is_zh = lang == "zh"
    if is_zh:
        return """<div class="lang-switch" style="float: right; margin-left: 12px;">
  <span class="lang-btn active">中文</span>
  <a href="../en/index.html" class="lang-btn" onclick="try{const p=window.location.pathname.split('/').pop()||'index.html';window.location.href='../en/'+p;return false;}catch(e){}">English</a>
</div>"""
    else:
        return """<div class="lang-switch" style="float: right; margin-left: 12px;">
  <a href="../zh/index.html" class="lang-btn" onclick="try{const p=window.location.pathname.split('/').pop()||'index.html';window.location.href='../zh/'+p;return false;}catch(e){}">中文</a>
  <span class="lang-btn active">English</span>
</div>"""


# ── model display order ─────────────────────────────────────────────

def _model_display_order(data: Dict[str, object], model_names: List[str]) -> List[str]:
    """Sort model_names by confirmed RTL root count (GT-aware, same as the RTL
    root card best badge), falling back to score ranking, then alphabetical."""
    root_scoring = data.get("rtl_root_scoring", {}) if isinstance(data.get("rtl_root_scoring"), dict) else {}
    root_ranking = root_scoring.get("ranking", []) if isinstance(root_scoring.get("ranking"), list) else []
    ground_truth = data.get("ground_truth_rtl_defects", {})
    ground_truth = ground_truth if isinstance(ground_truth, dict) else {}
    ground_truth_defects = ground_truth.get("defects", [])
    ground_truth_defects = ground_truth_defects if isinstance(ground_truth_defects, list) else []
    if ground_truth_defects and root_ranking:
        gt_hits = {
            str(r.get("model") or ""): sum(
                1 for d in ground_truth_defects
                if isinstance(d, dict) and str(r.get("model") or "") in d.get("models", [])
            )
            for r in root_ranking
        }
        if any(gt_hits.values()):
            return sorted(model_names, key=lambda m: gt_hits.get(m, 0), reverse=True)
    if root_ranking:
        confirmed = {
            str(r.get("model") or ""): int(r.get("root_bugs_confirmed", 0) or 0)
            for r in root_ranking
        }
        return sorted(model_names, key=lambda m: confirmed.get(m, 0), reverse=True)
    ranking = (data.get("model_score_summary", {}) or {}).get("ranking", [])
    if ranking:
        rank_order = {item["model"]: i for i, item in enumerate(ranking) if isinstance(item, dict)}
        if rank_order:
            return sorted(model_names, key=lambda m: rank_order.get(m, len(ranking)))
    return sorted(model_names)


# ── HTML report functions ──────────────────────────────────────────

def benchmark_audit_html(
    data: Dict[str, object],
    main_report_href: str = "index.html",
    lang: str = "zh",
) -> str:
    """Cross-model non-merge audit page."""
    audit_entries = data.get("cross_model_non_merge_audit", [])
    audit_total = len(audit_entries)
    semantic_total = len(data.get("semantic_judgements", []))
    model_names = _model_display_order(data, data.get("model_names", []))

    def esc(value: object) -> str:
        if value is None:
            return ""
        return html.escape(str(value))

    audit_relation_labels = {
        "different bugs": _t("audit_different_bugs", lang),
        "related symptoms": _t("audit_related_symptoms", lang),
        "insufficient evidence": _t("audit_insufficient_evidence", lang),
        "same bug": _t("audit_same_bug", lang),
    }
    audit_relation_counts = {}
    for a in audit_entries:
        rel = a.get("semantic_relation", "?")
        audit_relation_counts[rel] = audit_relation_counts.get(rel, 0) + 1
    audit_relation_html = ""
    for key, label in audit_relation_labels.items():
        cnt = audit_relation_counts.get(key, 0)
        if cnt:
            audit_relation_html += "<span class='audit-rel-item'><b>{}</b> {}</span> ".format(cnt, label)

    audit_pair_counts = defaultdict(int)
    for a in audit_entries:
        pair_label = "{} ↔ {}".format(a.get("left_model", "?"), a.get("right_model", "?"))
        audit_pair_counts[pair_label] += 1
    audit_pair_html = ""
    for pair_label, count in sorted(audit_pair_counts.items()):
        audit_pair_html += "<span class='audit-rel-item'><b>{}</b> {}</span> ".format(count, esc(pair_label))

    pair_id_map = _semantic_pair_id_map(data)
    audit_rows = _build_audit_rows(audit_entries, pair_id_map=pair_id_map)
    if not audit_rows:
        if semantic_total > 0 and audit_total == 0:
            audit_rows = "<tr><td colspan='8' class='muted' style='text-align:center; padding:18px;'>{}</td></tr>".format(
                esc(_t("audit_empty_all_same", lang).format(total=semantic_total))
            )
        else:
            audit_rows = "<tr><td colspan='8' class='muted' style='text-align:center; padding:18px;'>{}</td></tr>".format(
                esc(_t("audit_empty", lang))
            )

    desc_text = _t("audit_page_desc", lang).format(semantic_total=semantic_total, audit_total=audit_total)

    return """<!DOCTYPE html>
<html lang="{lang_code}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="page">
    <div class="top-nav">
      <a class="back-link" href="{main_report_href}">{back_text}</a>
      <div class="meta-text">{model_text}: {model_names}</div>
    </div>
    <section class="hero">
      <h1>{title}</h1>
      <p>{desc}</p>
    </section>
    <section class="section">
      <div class="section-header">
        <div><h2>{dist_title}</h2><p>{dist_desc}</p></div>
        <div><a class="mini-link" href="{main_report_href}">{back_short}</a></div>
      </div>
      <div class="audit-rel">{audit_relation_html}</div>
      <div class="audit-rel">{audit_pair_html}</div>
      <div class="audit-wrap audit-wrap-full">
        <table class="audit-table">
          <thead><tr>
            <th>{th_pair_id}</th><th>{th_left_model}</th><th>{th_left_cand}</th><th>{th_right_model}</th><th>{th_right_cand}</th>
            <th>{th_rel}</th><th>{th_blocking}</th><th>{th_score}</th>
          </tr></thead>
          <tbody>{audit_rows}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-header">
        <div><h2>{nav_title}</h2><p>{nav_desc}</p></div>
        <div><a class="back-link" href="{main_report_href}">{back_text}</a></div>
      </div>
    </section>
  </div>
</body>
</html>
""".format(
        lang_code="zh-CN" if lang == "zh" else "en",
        css=_benchmark_page_css(audit_full=True),
        page_title=_t("page_title_audit", lang),
        main_report_href=main_report_href,
        back_text=_t("audit_back_to_main", lang),
        model_text=_t("stat_models", lang),
        model_names=", ".join(str(m) for m in model_names),
        title=_t("audit_page_title", lang),
        desc=desc_text,
        dist_title=_t("audit_dist_title", lang),
        dist_desc=_t("audit_dist_desc", lang),
        back_short=_t("audit_back_to_main_short", lang),
        audit_relation_html=audit_relation_html or "<span class='audit-rel-item'>—</span>",
        audit_pair_html=audit_pair_html or "<span class='audit-rel-item'>—</span>",
        audit_rows=audit_rows or "<tr><td colspan='8' class='muted'>—</td></tr>",
        th_pair_id=_t("audit_th_pair_id", lang),
        th_left_model=_t("audit_th_left_model", lang),
        th_left_cand=_t("audit_th_left_candidate", lang),
        th_right_model=_t("audit_th_right_model", lang),
        th_right_cand=_t("audit_th_right_candidate", lang),
        th_rel=_t("audit_th_relation", lang),
        th_blocking=_t("audit_th_blocking", lang),
        th_score=_t("audit_th_score", lang),
        nav_title=_t("audit_nav_title", lang),
        nav_desc=_t("audit_nav_desc", lang),
    )


def rtl_manual_audit_queue_html(
    data: Dict[str, object],
    main_report_href: str = "index.html",
    lang: str = "zh",
) -> str:
    """RTL manual semantic audit queue page."""
    queue = data.get("rtl_manual_audit_queue", []) or []
    model_names = _model_display_order(data, data.get("model_names", []))

    def esc(value: object) -> str:
        if value is None:
            return ""
        return html.escape(str(value))

    title = "RTL 人工语义审计队列" if lang == "zh" else "RTL Manual Semantic Audit Queue"
    back_text = "← 返回 BugReview 主界面" if lang == "zh" else "← Back to BugReview"
    back_short = "返回主界面" if lang == "zh" else "Back to Main"
    status_label = "待人工定性" if lang == "zh" else "Pending human adjudication"
    model_text = "模型" if lang == "zh" else "Models"
    no_data = "暂无待审计条目" if lang == "zh" else "No pending audit entries"

    rows = []
    for item in queue:
        a = item.get("rtl_anchor") or {}
        anchor = f"{a.get('file') or ''}:{a.get('line_start') or ''}-{a.get('line_end') or ''}"
        rows.append(
            ("<tr id='{audit_id}'><td><code>{audit_id}</code></td>"
             "<td><code>{root_id}</code></td>"
             "<td><code>{anchor}</code></td>"
             "<td>{symptoms}</td>"
             "<td>{models}</td>"
             "<td>{status}</td></tr>"
             ).format(
                audit_id=esc(item.get("audit_id")),
                root_id=esc(item.get("rtl_root_bug_id")),
                anchor=esc(anchor),
                symptoms=esc(", ".join(map(str, item.get("symptoms", [])))),
                models=esc(", ".join(item.get("models", []))),
                status=esc(item.get("review_status", status_label)),
            )
        )

    body = "".join(rows) if rows else f"<tr><td colspan='6' class='muted'>{no_data}</td></tr>"
    audit_total = len(queue)

    return """<!DOCTYPE html>
<html lang="{lang_code}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="page">
    <div class="top-nav">
      <a class="back-link" href="{main_report_href}">{back_text}</a>
      <div class="meta-text">{model_text}: {model_names}</div>
    </div>
    <section class="hero">
      <h1>{title}</h1>
      <p>DUT: {dut} &mdash; {audit_total} {status_label}</p>
    </section>
    <section class="section">
      <div class="section-header">
        <div><h2>{queue_title}</h2><p>{queue_desc}</p></div>
        <div><a class="mini-link" href="{main_report_href}">{back_short}</a></div>
      </div>
      <div class="audit-wrap audit-wrap-full">
        <table class="audit-table">
          <thead><tr>
            <th>Audit ID</th><th>RTL Root</th><th>Anchor</th><th>Symptoms</th><th>Models</th><th>Status</th>
          </tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-header">
        <div><h2>{nav_title}</h2><p>{nav_desc}</p></div>
        <div><a class="back-link" href="{main_report_href}">{back_text}</a></div>
      </div>
    </section>
  </div>
</body>
</html>
""".format(
        lang_code="zh-CN" if lang == "zh" else "en",
        css=_benchmark_page_css(audit_full=True),
        page_title=esc(title),
        main_report_href=main_report_href,
        back_text=back_text,
        model_text=model_text,
        model_names=", ".join(str(m) for m in model_names),
        title=title,
        dut=esc(str(data.get("dut") or "")),
        audit_total=audit_total,
        status_label=status_label,
        queue_title=title,
        queue_desc="RTL roots with undetermined failure mode requiring human semantic classification." if lang == "en" else "failure_mode 未确定的 RTL 根因，需人工语义定性。",
        back_short=back_short,
        body=body,
        nav_title="导航" if lang == "zh" else "Navigation",
        nav_desc="返回主报告查看完整矩阵与证据。" if lang == "zh" else "Return to the main report for the full matrix and evidence.",
    )


_COV_DRAWER_CSS = """
/* Coverage interactive submodules drawer */
.cov-line-interactive {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 3px 8px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  transition: all 0.15s ease;
  user-select: none;
}
.cov-line-interactive:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.cov-val-num {
  font-weight: 600;
  color: #0f172a;
}
.cov-submod-toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 7px;
  background: #e2e8f0;
  color: #1e293b;
  border-radius: 4px;
  font-weight: 500;
  border: 1px solid #cbd5e1;
}
.cov-submod-toggle-chip .cov-arrow {
  font-size: 9px;
  color: #0284c7;
  font-weight: bold;
  display: inline-block;
  transition: transform 0.15s ease;
}
.cov-submod-drawer-row td {
  background: #f8fafc !important;
  padding: 12px 16px !important;
  border-bottom: 2px solid #cbd5e1 !important;
}
.cov-submod-drawer-box {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 12px 16px;
  box-shadow: 0 2px 5px rgba(0,0,0,0.04);
}
.cov-submod-drawer-title {
  margin-bottom: 10px;
  font-size: 13px;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 6px;
}
.cov-submod-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.cov-submod-table th {
  background: #f1f5f9;
  color: #334155;
  padding: 7px 10px;
  text-align: left;
  border: 1px solid #cbd5e1;
  font-weight: 600;
}
.cov-submod-table td {
  background: #ffffff !important;
  padding: 7px 10px;
  border: 1px solid #e2e8f0;
  color: #1e293b;
}
.submod-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
}
.role-top { background: #e0e7ff; color: #3730a3; border: 1px solid #c7d2fe; }
.role-wrapper { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
.role-ext { background: #e0f2fe; color: #075985; border: 1px solid #bae6fd; }
.role-sub { background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; }
.submod-src-btn {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  color: #15803d;
  border-radius: 3px;
  cursor: pointer;
  text-decoration: none;
  font-weight: 500;
}
.submod-src-btn:hover {
  background: #dcfce7;
  border-color: #4ade80;
  color: #166534;
}
"""


def _resolve_dut_submodules(
    dut_name: str,
    base_dirs: Optional[List[Path]] = None,
    line_coverage: Optional[Dict[str, object]] = None,
) -> List[Dict[str, Any]]:
    if not dut_name:
        return []
    clean = dut_name[4:] if dut_name.startswith("dut_") else dut_name
    candidates = []
    if base_dirs:
        for bd in base_dirs:
            candidates.extend([
                bd / f"{clean}_RTL",
                bd / clean / f"{clean}_RTL",
                bd / f"dut_{clean}" / f"{clean}_RTL",
                bd / "inputs" / "xiangshan" / "ucagent" / clean / f"{clean}_RTL",
                bd / "inputs" / "xiangshan" / "ucagent" / f"dut_{clean}" / f"{clean}_RTL",
            ])
    candidates.extend([
        Path(f"inputs/xiangshan/ucagent/{clean}/{clean}_RTL"),
        Path(f"inputs/xiangshan/ucagent/dut_{clean}/{clean}_RTL"),
        Path(f"workspace_clean/{clean}_RTL"),
    ])

    rtl_dir = None
    for c in candidates:
        if c.is_dir():
            rtl_dir = c
            break

    if not rtl_dir:
        return []

    submodules = []
    filelist = rtl_dir / "filelist.txt"
    files = []
    if filelist.exists():
        for line in filelist.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                p = rtl_dir / line
                if p.is_file():
                    files.append(p)
    if not files:
        files = sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))

    # Optional file line map
    file_cov_map: Dict[str, Dict[str, int]] = defaultdict(lambda: {"hit": 0, "total": 0})
    if isinstance(line_coverage, dict) and isinstance(line_coverage.get("line_map"), list):
        for lm in line_coverage["line_map"]:
            if isinstance(lm, dict):
                f_key = _short_path(str(lm.get("file") or ""))
                file_cov_map[f_key]["total"] += 1
                if int(lm.get("count") or 0) > 0:
                    file_cov_map[f_key]["hit"] += 1

    clean_norm = clean.lower().replace("_", "")
    for f in files:
        if not f.is_file():
            continue
        try:
            lines = len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            lines = 0
        fname = f.name
        fname_norm = fname.lower().replace("_", "")
        if "wrapper" in fname_norm or "dpic" in fname_norm or "dummy" in fname_norm:
            role = "DPI-C / 仿真接口封装"
            role_cls = "role-wrapper"
        elif "diffext" in fname_norm or "ext" in fname_norm or "event" in fname_norm:
            role = "扩展逻辑 / 辅助事件"
            role_cls = "role-ext"
        elif clean_norm in fname_norm:
            role = "顶层核心 DUT 模块"
            role_cls = "role-top"
        else:
            role = "子逻辑模块"
            role_cls = "role-sub"

        f_short = _short_path(str(f))
        cov_info = None
        if f_short in file_cov_map and file_cov_map[f_short]["total"] > 0:
            h = file_cov_map[f_short]["hit"]
            t = file_cov_map[f_short]["total"]
            r = round(h / t * 100, 1)
            cov_info = f"{r}% ({h}/{t} 行)"

        submodules.append({
            "name": fname,
            "path": str(f),
            "short_path": f_short,
            "lines": lines,
            "role": role,
            "role_cls": role_cls,
            "cov_info": cov_info,
        })
    return submodules


def benchmark_html(
    data: Dict[str, object],
    lang: str = "zh",
    base_dirs: Optional[List[Path]] = None,
) -> str:
    """Generate a clean, modern HTML dashboard for benchmark comparison results.

    Uses pure CSS (conic-gradient donut charts, bars) — no JavaScript dependency.
    """
    model_names = _model_display_order(data, data.get("model_names", []))
    dut_name = str(data.get("dut", "") or "").strip()
    dut_badge_html = (
        "<span class=\"dut-badge\">{dut_label}: {dut_name}</span>".format(
            dut_label=_t("dut_label", lang), dut_name=html.escape(dut_name),
        )
        if dut_name
        else ""
    )
    revision = data.get("benchmark_revision", {})
    revision = revision if isinstance(revision, dict) else {}
    revision_id = str(revision.get("revision_id") or "")
    report_state = str(revision.get("report_state") or "")
    revision_html = ""
    if revision_id:
        state_label = {
            "finalized": {"zh": "已定稿", "en": "Finalized"},
            "provisional": {"zh": "暂定", "en": "Provisional"},
        }.get(report_state, {}).get(lang, report_state or "unknown")
        revision_html = (
            "<p class='revision-meta'><strong>{state}</strong> · "
            "<code>{revision}</code></p>"
        ).format(state=html.escape(state_label), revision=html.escape(revision_id))
    records = data.get("benchmark_records", [])
    records_by_key = {
        (item.get("canonical_bug"), item.get("model")): item
        for item in records
        if isinstance(item, dict)
    }

    def esc(value: object, max_len: int = 0) -> str:
        if value is None:
            return ""
        s = html.escape(str(value))
        if max_len and len(s) > max_len:
            return "<span title='{}'>{}{}</span>".format(s, s[:max_len], "&hellip;")
        return s

    def trunc(s: str, n: int) -> str:
        if len(s) > n:
            return "<span title='{}'>{}{}</span>".format(html.escape(s, quote=True), html.escape(s[:n]), "&hellip;")
        return html.escape(s)

    mss = data.get("model_score_summary", {})
    ranking = list(mss.get("ranking") or [])
    policy = mss.get("policy", {})
    benchmark_records = data.get("benchmark_records", []) if isinstance(data.get("benchmark_records"), list) else []

    # Fallback: compute per-model symptom ranking if ranking is empty
    if not ranking and benchmark_records and model_names:
        per_model_calc = {}
        def _norm_tier(raw_t):
            s = str(raw_t or "").strip()
            if "reproduced" in s or "confirmed" in s:
                return "replay_confirmed"
            if "partial" in s:
                return "replay_partial_confirmed"
            if "review" in s or "contradicted" in s:
                return "replay_contradicted_review"
            if "rtl" in s:
                return "rtl_supported"
            if "wave" in s:
                return "waveform_supported"
            if "execution" in s:
                return "execution_supported_pending_replay"
            if "coverage" in s:
                return "coverage_supported"
            if "excluded" in s:
                return "excluded_declared_candidate"
            if "claim" in s:
                return "claim_only"
            return s or "claim_only"

        for m_name in model_names:
            m_records = [it for it in benchmark_records if isinstance(it, dict) and it.get("model") == m_name]
            t_score = sum(int(it.get("evidence_score", 0) or 0) for it in m_records)
            m_score = len(m_records) * 5
            t_counts = dict(sorted(Counter(_norm_tier(it.get("evidence_tier")) for it in m_records).items()))
            r_counts = dict(sorted(Counter(str(it.get("score_reason", "unknown")) for it in m_records).items()))
            per_model_calc[m_name] = {
                "total_score": t_score,
                "max_score": m_score,
                "normalized_score": round((t_score / m_score), 4) if m_score else 0.0,
                "found_count": sum(1 for it in m_records if it.get("status") == "found"),
                "tier_counts": t_counts,
                "score_reason_counts": r_counts,
            }
        ranking = [
            {"model": m_name, **per_model_calc[m_name]}
            for m_name in sorted(
                model_names,
                key=lambda name: (
                    -per_model_calc.get(name, {}).get("total_score", 0),
                    -per_model_calc.get(name, {}).get("found_count", 0),
                    name,
                ),
            )
        ]

    root_scoring = data.get("rtl_root_scoring", {}) if isinstance(data.get("rtl_root_scoring"), dict) else {}
    root_ranking = root_scoring.get("ranking", []) if isinstance(root_scoring.get("ranking"), list) else []
    root_total_bugs = len(data.get("rtl_root_bugs", []) or [])
    # Older/fixed-source benchmark payloads may contain the authoritative
    # ``rtl_root_bugs`` list before the optional scoring stage has written a
    # ranking.  Keep the report template useful in that state by deriving the
    # model-level summary from the root records; the root records remain the
    # source of truth for the detail table below.
    if not root_ranking and root_total_bugs:
        derived_models = {}
        for root_bug in data.get("rtl_root_bugs", []) or []:
            if not isinstance(root_bug, dict):
                continue
            for model, info in (root_bug.get("models") or {}).items():
                if not isinstance(info, dict) or not info.get("found"):
                    continue
                entry = derived_models.setdefault(str(model), {
                    "model": str(model), "root_bugs_found": 0,
                    "root_bugs_confirmed": 0, "root_bugs_unverified": 0,
                    "root_bugs_pending_replay": 0, "root_bugs_needs_review": 0,
                    "root_bugs_not_reproduced": 0, "root_bugs_blocked": 0,
                    "symptom_breadth": "none", "root_local_line_coverage_rate": None,
                    "root_local_coverage_root_count": 0,
                })
                entry["root_bugs_found"] += 1
                entry["root_bugs_unverified"] += 1 if info.get("confirmed_symptoms", 0) == 0 else 0
                entry["root_bugs_pending_replay"] += 1 if info.get("confirmed_symptoms", 0) == 0 else 0
        root_ranking = list(derived_models.values())
    raw_gt = data.get("ground_truth_rtl_defects", {})
    if isinstance(raw_gt, list):
        ground_truth = {"defects": raw_gt, "total_rtl_defects": len(raw_gt)}
        ground_truth_defects = raw_gt
    elif isinstance(raw_gt, dict):
        ground_truth = raw_gt
        ground_truth_defects = raw_gt.get("defects", [])
        if not isinstance(ground_truth_defects, list):
            ground_truth_defects = []
    else:
        ground_truth = {}
        ground_truth_defects = []
    has_ground_truth = bool(ground_truth_defects or ground_truth.get("total_rtl_defects"))
    ground_truth_total = int(ground_truth.get("total_rtl_defects", len(ground_truth_defects)) or len(ground_truth_defects))
    mapped_ground_truth_defects = [
        defect for defect in ground_truth_defects
        if isinstance(defect, dict)
        and str(defect.get("root_match_status") or "matched_current_root") == "matched_current_root"
    ]
    pending_ground_truth_defects = [
        defect for defect in ground_truth_defects
        if isinstance(defect, dict)
        and str(defect.get("root_match_status") or "matched_current_root") != "matched_current_root"
    ]
    mapped_ground_truth_total = len(mapped_ground_truth_defects)
    pending_ground_truth_total = len(pending_ground_truth_defects)

    tier_order = [
        "replay_confirmed",
        "replay_partial_confirmed",
        "replay_contradicted_review",
        "rtl_supported",
        "waveform_supported",
        "execution_supported_pending_replay",
        "coverage_supported",
        "claim_only",
        "excluded_declared_candidate",
    ]
    tier_labels = {
        "replay_confirmed": _t("tier_replay_confirmed", lang),
        "replay_partial_confirmed": _t("tier_replay_partial_confirmed", lang),
        "replay_contradicted_review": _t("tier_replay_contradicted_review", lang),
        "rtl_supported": _t("tier_rtl_supported", lang),
        "waveform_supported": _t("tier_waveform_supported", lang),
        "execution_supported_pending_replay": _t("tier_execution_supported", lang),
        "coverage_supported": _t("tier_coverage_supported", lang),
        "claim_only": _t("tier_claim_only", lang),
        "excluded_declared_candidate": _t("tier_excluded_declared_candidate", lang),
        "not_found": _t("tier_not_found", lang),
    }
    tier_colors = {
        "replay_confirmed": "#10b981", "replay_partial_confirmed": "#14b8a6", "replay_contradicted_review": "#f59e0b", "rtl_supported": "#06b6d4",
        "waveform_supported": "#8b5cf6", "execution_supported_pending_replay": "#f59e0b",
        "coverage_supported": "#f97316", "claim_only": "#9ca3af", "excluded_declared_candidate": "#94a3b8",
        "not_found": "#e5e7eb",
    }
    tier_stroke = {
        "replay_confirmed": "#059669", "replay_partial_confirmed": "#0f766e", "replay_contradicted_review": "#d97706", "rtl_supported": "#0891b2",
        "waveform_supported": "#7c3aed", "execution_supported_pending_replay": "#d97706",
        "coverage_supported": "#ea580c", "claim_only": "#6b7280", "excluded_declared_candidate": "#64748b",
        "not_found": "#d1d5db",
    }

    max_score_val = max((r.get("max_score", 1) for r in ranking), default=1)
    total_bugs = len(data.get("matrix", []))
    # A generated GT object is authoritative even when its valid defect set is
    # empty.  Falling back from GT=0 to the unadjudicated root-cluster count
    # made the headline claim N RTL defects while the GT-aware overview showed
    # 0/0.  Raw roots remain visible in the RTL root matrix, but are not a
    # substitute for the independent-defect denominator.
    primary_bug_total = mapped_ground_truth_total if has_ground_truth else (root_total_bugs or total_bugs)
    shared_count = sum(
        1 for row in data.get("matrix", [])
        if sum(1 for m in model_names if row.get("per_model", {}).get(m, {}).get("found")) > 1
    )
    unique_count = total_bugs - shared_count
    semantic_total = len(data.get("semantic_judgements", []))
    audit_total = len(data.get("cross_model_non_merge_audit", []))

    model_exclusive = {}
    model_shared = {}
    model_found = {}
    for m in model_names:
        found = sum(1 for row in data.get("matrix", [])
                    if row.get("per_model", {}).get(m, {}).get("found"))
        shared = sum(1 for row in data.get("matrix", [])
                     if row.get("per_model", {}).get(m, {}).get("found")
                     and sum(1 for m2 in model_names if m2 != m and row.get("per_model", {}).get(m2, {}).get("found")) > 0)
        model_found[m] = found
        model_shared[m] = shared
        model_exclusive[m] = found - shared

    model_list = ("、".join(str(m) for m in model_names) if lang == "zh"
                  else ", ".join(str(m) for m in model_names))
    primary_shared_count = shared_count
    primary_unique_count = unique_count
    primary_exclusive_breakdown = None
    if has_ground_truth:
        primary_shared_count = sum(
            1 for defect in mapped_ground_truth_defects
            if len(defect.get("models", [])) > 1
        )
        primary_unique_count = sum(
            1 for defect in mapped_ground_truth_defects
            if len(defect.get("models", [])) == 1
        )
        primary_parts = []
        for model in model_names:
            n = sum(
                1 for defect in mapped_ground_truth_defects
                if model in defect.get("models", []) and len(defect.get("models", [])) == 1
            )
            if n:
                primary_parts.append("{}: {}".format(esc(model), n))
        primary_exclusive_breakdown = (
            "，".join(primary_parts) if lang == "zh" else ", ".join(primary_parts)
        ) if primary_parts else "—"
    elif root_total_bugs:
        root_model_found = {model: 0 for model in model_names}
        root_model_shared = {model: 0 for model in model_names}
        root_model_exclusive = {model: 0 for model in model_names}
        primary_shared_count = 0
        for root_bug in data.get("rtl_root_bugs", []) or []:
            root_models = root_bug.get("models", {}) if isinstance(root_bug.get("models"), dict) else {}
            found_models = [
                model for model in model_names
                if isinstance(root_models.get(model), dict) and root_models.get(model, {}).get("found")
            ]
            if len(found_models) > 1:
                primary_shared_count += 1
            for model in found_models:
                root_model_found[model] += 1
                if len(found_models) > 1:
                    root_model_shared[model] += 1
                else:
                    root_model_exclusive[model] += 1
        primary_unique_count = root_total_bugs - primary_shared_count
        primary_parts = []
        for model in model_names:
            n = root_model_exclusive.get(model, 0)
            if n:
                primary_parts.append("{}: {}".format(esc(model), n))
        primary_exclusive_breakdown = (
            "，".join(primary_parts) if lang == "zh" else ", ".join(primary_parts)
        ) if primary_parts else "—"
    all_candidates = []
    for rec in data.get("benchmark_records", []):
        if rec.get("status") == "found":
            all_candidates.extend(rec.get("candidate_ids", []))
    candidate_total = len(set(all_candidates))
    primary_stat_label = _t("stat_rtl_root_bugs", lang) if has_ground_truth else _t("stat_canonical_bugs", lang)
    primary_stat_desc = (
        _t("stat_rtl_root_desc", lang).format(
            archived=ground_truth_total,
            pending=pending_ground_truth_total,
        )
        if has_ground_truth
        else _t("stat_canonical_desc", lang).format(candidate_total=candidate_total)
    )
    shared_pct = shared_count / total_bugs * 100 if total_bugs else 0
    audit_pct = audit_total / semantic_total * 100 if semantic_total else 0
    exclusive_parts = []
    for m in model_names:
        n = model_exclusive.get(m, 0)
        if n:
            exclusive_parts.append("{}: {}".format(esc(m), n))
    exclusive_breakdown = ("，".join(exclusive_parts) if lang == "zh" else ", ".join(exclusive_parts)) if exclusive_parts else "—"
    stat_exclusive_breakdown = primary_exclusive_breakdown if primary_exclusive_breakdown is not None else exclusive_breakdown
    stat_shared_pct = primary_shared_count / mapped_ground_truth_total * 100 if mapped_ground_truth_total else 0
    max_possible = total_bugs * 5

    overlap_colors = ["#06b6d4", "#f59e0b", "#8b5cf6"]
    overlap_cards = ""
    for i, m in enumerate(model_names):
        found = model_found.get(m, 0)
        shared = model_shared.get(m, 0)
        excl = model_exclusive.get(m, 0)
        not_found = total_bugs - found
        bh = overlap_colors[i % 3]
        overlap_cards += (
            "<div class='donut-card'>"
            "<div class='overlap-ring' style='background:conic-gradient({bh} {fp}deg, #e5e7eb {fp}deg 360deg)'>"
            "<div class='overlap-hole'><span class='overlap-val'>{found}/{total_bugs}</span></div></div>"
            "<div class='donut-info'><h3 class='donut-name' style='color:{bh}'>{model}</h3>"
            "<div class='donut-legend'>"
            "<div class='dl-item'><span class='dl-dot' style='background:{bh}'></span>{found_text}</div>"
            "<div class='dl-item'><span class='dl-dot' style='background:{bh}99'></span>{shared_text}</div>"
            "<div class='dl-item'><span class='dl-dot' style='background:{bh}44'></span>{excl_text}</div>"
            "<div class='dl-item muted'>{not_found_text}</div>"
            "</div></div></div>"
        ).format(
            bh=bh, fp=found/total_bugs*360 if total_bugs else 0,
            found=found, total_bugs=total_bugs, model=esc(m), shared=shared, excl=excl, not_found=not_found,
            found_text=_t("overlap_found", lang).format(found=found),
            shared_text=_t("overlap_shared", lang).format(shared=shared),
            excl_text=_t("overlap_exclusive", lang).format(excl=excl),
            not_found_text=_t("overlap_not_found", lang).format(not_found=not_found),
        )

    semantic_config_parts = _semantic_llm_config_summary(data)
    semantic_pair_parts = _semantic_pair_config_summary(data)
    semantic_config_html = ""
    if semantic_config_parts or semantic_pair_parts:
        blocks = []
        if semantic_config_parts:
            blocks.append(
                "<div><h2>{title}</h2><p>{content}</p></div>".format(
                    title=_t("config_semantic_judge", lang),
                    content=esc("; ".join(semantic_config_parts)),
                )
            )
        if semantic_pair_parts:
            blocks.append(
                "<div><h2>{title}</h2><p>{content}</p></div>".format(
                    title=_t("config_semantic_pairs", lang),
                    content=esc("; ".join(semantic_pair_parts)),
                )
            )
        semantic_config_html = (
            "<section class='section'><div class='section-header'>{}</div></section>"
        ).format("".join(blocks))

    audit_relations = {
        "different bugs": _t("audit_different_bugs", lang),
        "related symptoms": _t("audit_related_symptoms", lang),
        "insufficient evidence": _t("audit_insufficient_evidence", lang),
        "same bug": _t("audit_same_bug", lang),
    }
    audit_entries = data.get("cross_model_non_merge_audit", [])
    audit_relation_counts = {}
    for a in audit_entries:
        rel = a.get("semantic_relation", "?")
        audit_relation_counts[rel] = audit_relation_counts.get(rel, 0) + 1
    audit_relation_html = ""
    for key, label in audit_relations.items():
        cnt = audit_relation_counts.get(key, 0)
        if cnt:
            audit_relation_html += "<span class='audit-rel-item'><b>{}</b> {}</span> ".format(cnt, label)

    audit_pair_counts = defaultdict(int)
    for a in audit_entries:
        pair_label = "{} ↔ {}".format(a.get("left_model", "?"), a.get("right_model", "?"))
        audit_pair_counts[pair_label] += 1
    audit_pair_html = ""
    for pair_label, count in sorted(audit_pair_counts.items()):
        audit_pair_html += "<span class='audit-rel-item'><b>{}</b> {}</span> ".format(count, esc(pair_label))

    sorted_audit = sorted(
        audit_entries,
        key=lambda a: (0 if a.get("semantic_relation") == "related symptoms" else 1, -(a.get("score", 0) or 0)),
    )
    audit_display_limit = 1000
    if len(sorted_audit) <= audit_display_limit:
        shown_audit = sorted_audit
    else:
        shown_audit = _select_balanced_model_pair_rows(sorted_audit, limit=audit_display_limit)
    pair_id_map = _semantic_pair_id_map(data)
    audit_rows = _build_audit_rows(shown_audit, pair_id_map=pair_id_map)
    if not audit_rows:
        if semantic_total > 0 and audit_total == 0:
            audit_rows = "<tr><td colspan='8' class='muted' style='text-align:center; padding:18px;'>{}</td></tr>".format(
                esc(_t("audit_empty_all_same", lang).format(total=semantic_total))
            )
        else:
            audit_rows = "<tr><td colspan='8' class='muted' style='text-align:center; padding:18px;'>{}</td></tr>".format(
                esc(_t("audit_empty", lang))
            )
    if len(shown_audit) < len(sorted_audit):
        audit_display_note = _t("audit_display_partial", lang).format(shown=len(shown_audit), total=len(sorted_audit))
    else:
        audit_display_note = _t("audit_display_all", lang).format(count=len(shown_audit))

    # ── score bars (root + symptom, always both when root data exists) ──
    bar_colors = ["#06b6d4", "#f59e0b", "#8b5cf6"]
    root_score_section = ""
    symptom_score_section = ""
    coverage_metrics = data.get("per_model", {}) if isinstance(data.get("per_model"), dict) else {}
    coverage_comparability = data.get("coverage_comparability", {}) if isinstance(data.get("coverage_comparability"), dict) else {}

    # ── per-model FG/FC/CK/BG extraction from benchmark_records ──
    benchmark_records = data.get("benchmark_records", []) if isinstance(data.get("benchmark_records"), list) else []
    model_func_tags: Dict[str, Dict[str, set]] = {}
    for rec in benchmark_records:
        if not isinstance(rec, dict):
            continue
        model = str(rec.get("model") or "")
        if model not in model_func_tags:
            model_func_tags[model] = {"fg": set(), "fc": set(), "ck": set(), "bg": set()}
        for cs in (rec.get("claim_sources", []) or []):
            if not isinstance(cs, dict):
                continue
            bi = str(cs.get("bug_identity") or "")
            if bi:
                for part in bi.split("/"):
                    part = part.strip()
                    if part.startswith("FG-"):
                        model_func_tags[model]["fg"].add(part[3:])
                    elif part.startswith("FC-"):
                        model_func_tags[model]["fc"].add(part[3:])
                    elif part.startswith("CK-"):
                        model_func_tags[model]["ck"].add(part[3:])
            bg = str(cs.get("bg_name") or "")
            if bg:
                model_func_tags[model]["bg"].add(bg)

    def _tag_count_cell(tag_set: set, chip_class: str) -> str:
        if not tag_set:
            return "<td class='func-count-cell func-count-empty'>—</td>"
        n = len(tag_set)
        return "<td class='func-count-cell'><span class='root-func-chip {cls}'>{n}</span></td>".format(
            cls=chip_class, n=n,
        )

    def _tags_block(tag_set: set, chip_class: str, label: str) -> str:
        if not tag_set:
            return ""
        chips = "".join(
            "<span class='func-detail-chip {cls}'>{name}</span>".format(
                cls=chip_class, name=esc(name),
            )
            for name in sorted(tag_set)
        )
        return "<div class='tags-block-row'><span class='tags-block-label {cls}'>{label}</span><div class='tags-block-chips'>{chips}</div></div>".format(
            cls=chip_class, label=label, chips=chips,
        )

    registry = SourceRegistry(base_dirs=base_dirs)

    def _coverage_cell(item, hit_key, total_key):
        if not item.get("available"):
            return "n/a ({})".format(esc(item.get("status") or "UNAVAILABLE_COVERAGE"))
        return "{}% ({}/{}, {}; {})".format(
            esc(item.get("rate")), esc(item.get(hit_key)), esc(item.get(total_key)),
            esc(item.get("status")), esc(item.get("source")),
        )

    def _render_line_cell_and_drawer(cur_dut: str, model: str, line_item: Dict[str, Any], drawer_idx: int) -> Tuple[str, str]:
        submodules = _resolve_dut_submodules(cur_dut, base_dirs=base_dirs, line_coverage=line_item)
        if not line_item.get("available"):
            cov_text = "n/a ({})".format(esc(line_item.get("status") or "UNAVAILABLE_COVERAGE"))
        else:
            cov_text = "{}% ({}/{}, {}; {})".format(
                esc(line_item.get("rate")), esc(line_item.get("hit_lines")), esc(line_item.get("total_lines")),
                esc(line_item.get("status")), esc(line_item.get("source")),
            )
        if not submodules:
            return f"<td>{cov_text}</td>", ""

        drawer_id = f"cov-submod-{drawer_idx}"
        toggle_title = "点击展开/折叠 RTL 子模块构成及覆盖详情" if lang == "zh" else "Click to expand/collapse RTL submodules"
        chip_label = f"{len(submodules)} 个子模块" if lang == "zh" else f"{len(submodules)} submodules"

        cell_html = (
            "<td>"
            f"<div class='cov-line-interactive' onclick=\"toggleSubmoduleDrawer('{drawer_id}')\" title='{toggle_title}'>"
            f"<span class='cov-val-num'>{cov_text}</span>"
            f"<span class='cov-submod-toggle-chip'><span id='arrow-{drawer_id}' class='cov-arrow'>▶</span> {chip_label}</span>"
            "</div></td>"
        )

        submod_rows = []
        for sm in submodules:
            role_label = sm["role"] if lang == "zh" else sm["role"].replace("顶层核心 DUT 模块", "Top/Core DUT").replace("DPI-C / 仿真接口封装", "DPI-C / Wrapper").replace("扩展逻辑 / 辅助事件", "Ext/Event Logic").replace("子逻辑模块", "Submodule")
            cov_display = sm.get("cov_info")
            if not cov_display:
                if line_item.get("available"):
                    cov_display = "纳入全局行覆盖" if lang == "zh" else "Included in global coverage"
                else:
                    cov_display = "未运行行覆盖仿真" if lang == "zh" else "No simulation coverage"

            # Register file for modal view
            short_p, _ = registry.register(sm["path"])
            src_btn = (
                f"<button type='button' class='submod-src-btn' data-file='{esc(short_p)}' data-start='0' data-end='0' data-title='{esc(sm['name'])}' onclick=\"openCodeModal(this); event.stopPropagation();\">"
                f"{'查看源码' if lang == 'zh' else 'View source'}</button>"
            )

            submod_rows.append(
                "<tr>"
                f"<td><code>{esc(sm['name'])}</code></td>"
                f"<td><span class='submod-badge {sm['role_cls']}'>{esc(role_label)}</span></td>"
                f"<td>{sm['lines']} 行</td>"
                f"<td>{esc(cov_display)}</td>"
                f"<td>{src_btn}</td>"
                "</tr>"
            )

        drawer_html = (
            f"<tr id='{drawer_id}' class='cov-submod-drawer-row' style='display: none;'>"
            "<td colspan='7'>"
            "<div class='cov-submod-drawer-box'>"
            "<div class='cov-submod-drawer-title'>"
            f"<span>📐 <b>{esc(cur_dut)} RTL {'子模块构成与行级覆盖详情' if lang == 'zh' else 'Submodules & Line Coverage'}</b> ({len(submodules)} {'个模块' if lang == 'zh' else 'modules'})</span>"
            "</div>"
            "<table class='cov-submod-table'>"
            "<thead><tr>"
            f"<th>{'子模块文件名' if lang == 'zh' else 'Submodule'}</th>"
            f"<th>{'模块角色' if lang == 'zh' else 'Role'}</th>"
            f"<th>{'代码行数' if lang == 'zh' else 'Lines'}</th>"
            f"<th>{'覆盖率状态' if lang == 'zh' else 'Coverage Status'}</th>"
            f"<th>{'源码' if lang == 'zh' else 'Source'}</th>"
            "</tr></thead>"
            f"<tbody>{''.join(submod_rows)}</tbody>"
            "</table></div></td></tr>"
        )
        return cell_html, drawer_html

    # Detect nested per_model (multi-DUT: {model: {dut: {func, line}}})
    _first_metrics = next(iter(coverage_metrics.values()), None) if coverage_metrics else None
    _nested = (
        isinstance(_first_metrics, dict)
        and not isinstance(_first_metrics.get("functional_coverage"), dict)
        and not isinstance(_first_metrics.get("line_coverage"), dict)
        and any(isinstance(v, dict) for v in _first_metrics.values())
    )

    coverage_rows = ""
    th_fg = "FG" if lang == "en" else "FG"
    th_fc = "FC" if lang == "en" else "FC"
    th_ck = "CK" if lang == "en" else "CK"
    th_bg = "BG" if lang == "en" else "BG"
    drawer_counter = 0
    if _nested:
        # Multi-DUT: one row per (model, DUT), DUT column removed, FG/FC/CK/BG added
        all_duts = sorted({d for m in coverage_metrics for d in coverage_metrics.get(m, {})})
        for model in model_names:
            model_data = coverage_metrics.get(model, {}) if isinstance(coverage_metrics.get(model), dict) else {}
            tags = model_func_tags.get(model, {})
            for dut in all_duts:
                dut_data = model_data.get(dut, {}) if isinstance(model_data.get(dut), dict) else {}
                functional = dut_data.get("functional_coverage", {}) if isinstance(dut_data.get("functional_coverage"), dict) else {}
                line = dut_data.get("line_coverage", {}) if isinstance(dut_data.get("line_coverage"), dict) else {}
                drawer_counter += 1
                line_td, drawer_tr = _render_line_cell_and_drawer(dut, model, line, drawer_counter)
                coverage_rows += "<tr><td>{}</td><td>{}</td>{}{}{}{}{}</tr>{}".format(
                    esc(model), _coverage_cell(functional, "bin_hit", "bin_total"), line_td,
                    _tag_count_cell(tags.get("fg", set()), "fg-chip"),
                    _tag_count_cell(tags.get("fc", set()), "fc-chip"),
                    _tag_count_cell(tags.get("ck", set()), "ck-chip"),
                    _tag_count_cell(tags.get("bg", set()), "bg-chip"),
                    drawer_tr,
                )
    else:
        # Single-DUT or flat
        for model in model_names:
            metrics = coverage_metrics.get(model, {}) if isinstance(coverage_metrics.get(model), dict) else {}
            functional = metrics.get("functional_coverage", {}) if isinstance(metrics.get("functional_coverage"), dict) else {}
            line = metrics.get("line_coverage", {}) if isinstance(metrics.get("line_coverage"), dict) else {}
            tags = model_func_tags.get(model, {})
            drawer_counter += 1
            line_td, drawer_tr = _render_line_cell_and_drawer(dut_name, model, line, drawer_counter)
            coverage_rows += "<tr><td>{}</td><td>{}</td>{}{}{}{}{}</tr>{}".format(
                esc(model), _coverage_cell(functional, "bin_hit", "bin_total"), line_td,
                _tag_count_cell(tags.get("fg", set()), "fg-chip"),
                _tag_count_cell(tags.get("fc", set()), "fc-chip"),
                _tag_count_cell(tags.get("ck", set()), "ck-chip"),
                _tag_count_cell(tags.get("bg", set()), "bg-chip"),
                drawer_tr,
            )
    coverage_note = ""
    if coverage_metrics:
        incomparable = [
            name for name in ("functional_coverage", "line_coverage")
            if not isinstance(coverage_comparability.get(name), dict) or not coverage_comparability[name].get("comparable")
        ]
        if incomparable:
            coverage_note = " <span class='note-tag'>{}</span>".format(_t("coverage_not_comparable", lang))
    coverage_metrics_section = ""
    if coverage_metrics:
        if _nested:
            coverage_metrics_section = (
                "<section class='section'><div class='section-header'><div><h2>{}</h2><p>{}{}</p></div></div>"
                "<div class='matrix-wrap'><table class='matrix-table'><thead><tr><th>{}</th><th>{}</th><th>{}</th><th class='count-col'>{}</th><th class='count-col'>{}</th><th class='count-col'>{}</th><th class='count-col'>{}</th></tr></thead>"
                "<tbody>{}</tbody></table></div></section>"
            ).format(
                _t("coverage_metrics_title", lang), _t("coverage_metrics_desc", lang), coverage_note,
                "模型" if lang == "zh" else "Model",
                "功能覆盖率 (bin)" if lang == "zh" else "Functional Coverage (bin)",
                "行覆盖率" if lang == "zh" else "Line Coverage",
                th_fg, th_fc, th_ck, th_bg, coverage_rows,
            )
        else:
            coverage_metrics_section = (
                "<section class='section'><div class='section-header'><div><h2>{}</h2><p>{}{}</p></div></div>"
                "<div class='matrix-wrap'><table class='matrix-table'><thead><tr><th>{}</th><th>{}</th><th>{}</th><th class='count-col'>{}</th><th class='count-col'>{}</th><th class='count-col'>{}</th><th class='count-col'>{}</th></tr></thead>"
                "<tbody>{}</tbody></table></div></section>"
            ).format(
                _t("coverage_metrics_title", lang), _t("coverage_metrics_desc", lang), coverage_note,
                "模型" if lang == "zh" else "Model",
                "功能覆盖率 (bin)" if lang == "zh" else "Functional Coverage (bin)",
                "行覆盖率" if lang == "zh" else "Line Coverage",
                th_fg, th_fc, th_ck, th_bg, coverage_rows,
            )

    # ── Tag detail section: per-model FG/FC/CK/BG full name listing ──
    tag_detail_section = ""
    if model_func_tags:
        tag_cards = ""
        for model in model_names:
            tags = model_func_tags.get(model, {})
            if not any(tags.values()):
                continue
            blocks = "".join([
                _tags_block(tags.get("fg", set()), "fg-chip", "FG"),
                _tags_block(tags.get("fc", set()), "fc-chip", "FC"),
                _tags_block(tags.get("ck", set()), "ck-chip", "CK"),
                _tags_block(tags.get("bg", set()), "bg-chip", "BG"),
            ])
            tag_cards += (
                "<div class='tags-card'>"
                "<div class='tags-card-header'><span class='tags-card-model'>{model}</span></div>"
                "<div class='tags-card-body'>{blocks}</div>"
                "</div>"
            ).format(model=esc(model), blocks=blocks)
        if tag_cards:
            tag_detail_section = (
                "<section class='section'>"
                "<div class='section-header'><div><h2>{title}</h2><p>{desc}</p></div></div>"
                "<div class='tags-scroll-wrap'><div class='tags-cards-grid'>{cards}</div></div>"
                "</section>"
            ).format(
                title=_t("func_tags_detail_title", lang),
                desc=_t("func_tags_detail_desc", lang),
                cards=tag_cards,
            )

    if root_ranking:
        reproduced_count = int(data.get("reproduced_replay_count", 0) or 0)
        has_reproduced_tier = any(
            str(r.get("evidence_tier", "")).lower() == "independent_replay_reproduced"
            for r in data.get("benchmark_records", []) if isinstance(r, dict)
        )
        has_replay_results = bool(data.get("replay_results")) or any(
            bool(r.get("replay_results"))
            for r in data.get("benchmark_records", []) if isinstance(r, dict)
        )
        is_replayed = reproduced_count > 0 or has_reproduced_tier or has_replay_results
        replay_available = root_scoring.get("replay_available", True) or is_replayed
        replay_note = "" if replay_available else _t("root_replay_bypassed_note", lang)
        ground_truth = data.get("ground_truth_rtl_defects", {})
        ground_truth = ground_truth if isinstance(ground_truth, dict) else {}
        ground_truth_defects = ground_truth.get("defects", [])
        ground_truth_defects = ground_truth_defects if isinstance(ground_truth_defects, list) else []
        verified_bug_total = int(ground_truth.get("total_rtl_defects", 0) or 0)
        mapped_bug_total = sum(
            1 for defect in ground_truth_defects
            if isinstance(defect, dict)
            and str(defect.get("root_match_status") or "matched_current_root") == "matched_current_root"
        )
        pending_bug_total = sum(
            1 for defect in ground_truth_defects
            if isinstance(defect, dict)
            and str(defect.get("root_match_status") or "matched_current_root") != "matched_current_root"
        )
        rtl_root_bugs = data.get("rtl_root_bugs", []) if isinstance(data.get("rtl_root_bugs"), list) else []

        def model_hits_ground_truth_root(root_bug: Dict[str, object], model_name: str) -> bool:
            root_id = root_bug.get("rtl_root_bug_id")
            return any(
                isinstance(defect, dict)
                and defect.get("source_root_id") == root_id
                and model_name in (defect.get("models") or [])
                for defect in ground_truth_defects
            )

        def verified_rtl_line_count(model_name: str) -> int:
            """Count unique RTL source lines anchored by a model's verified bugs."""
            lines = set()
            for root_bug in rtl_root_bugs:
                if not isinstance(root_bug, dict):
                    continue
                if not model_hits_ground_truth_root(root_bug, model_name):
                    continue
                anchor = root_bug.get("root_anchor", {})
                if not isinstance(anchor, dict):
                    continue
                source_file = str(anchor.get("file") or anchor.get("path") or "")
                try:
                    line_start = int(anchor.get("line_start"))
                    line_end = int(anchor.get("line_end"))
                except (TypeError, ValueError):
                    continue
                if source_file and line_start > 0 and line_end >= line_start:
                    lines.update((source_file, line) for line in range(line_start, line_end + 1))
            return len(lines)

        def local_window_coverage(model_name: str) -> str:
            windows = []
            for root_bug in rtl_root_bugs:
                if not isinstance(root_bug, dict):
                    continue
                if not model_hits_ground_truth_root(root_bug, model_name):
                    continue
                model_evidence = root_bug.get("models", {}).get(model_name, {})
                local = model_evidence.get("root_local_line_coverage", {})
                if isinstance(local, dict):
                    windows.append(local)
            available = [item for item in windows if item.get("available") is True and item.get("rate") is not None]
            if not windows:
                return "—"
            if not available:
                return "n/a ({}/{})".format(0, len(windows))
            average_rate = sum(float(item.get("rate", 0) or 0) for item in available) / len(available)
            return "{:.1f}% ({}/{})".format(average_rate, len(available), len(windows))

        # ---------- RTL root evaluation cards ----------
        ground_truth_hits = {
            str(r.get("model") or ""): sum(
                1
                for defect in ground_truth_defects
                if isinstance(defect, dict) and str(r.get("model") or "") in defect.get("models", [])
            )
            for r in root_ranking
        }
        max_confirmed = max(ground_truth_hits.values(), default=1) if any(ground_truth_hits.values()) else max((int(r.get("root_bugs_confirmed", 0) or 0) for r in root_ranking), default=1)
        max_found = max((int(r.get("root_bugs_found", 0) or 0) for r in root_ranking), default=1)
        rtl_line_counts = {
            str(r.get("model") or ""): verified_rtl_line_count(str(r.get("model") or ""))
            for r in root_ranking
        }
        max_rtl_lines = max(rtl_line_counts.values(), default=1)

        root_ranking = sorted(
            root_ranking,
            key=lambda r: ground_truth_hits.get(str(r.get("model") or ""), int(r.get("root_bugs_confirmed", 0) or 0)),
            reverse=True,
        )

        root_cards = ""
        reported_root_summary = data.get("reported_root_cause_summary", {})
        reported_root_per_model = (
            reported_root_summary.get("per_model", {})
            if isinstance(reported_root_summary, dict) else {}
        )
        reported_bug_summary = data.get("reported_bug_claim_summary", {})
        reported_bug_per_model = (
            reported_bug_summary.get("per_model", {})
            if isinstance(reported_bug_summary, dict) else {}
        )
        # Fixed-source rebuilt payloads record the raw source declaration
        # count in audit provenance.  It is the same pre-clustering level as
        # the normal reported_bug_claim_summary and keeps older rebuilt pages
        # honest without rewriting their immutable audit data.
        if not reported_bug_per_model:
            provenance = data.get("audit_provenance", {})
            selections = provenance.get("source_selection", []) if isinstance(provenance, dict) else []
            reported_bug_per_model = {
                str(item.get("model") or ""): {
                    "available": item.get("raw_candidate_count") is not None,
                    "declared_bug_count": item.get("raw_candidate_count"),
                    "positive_confidence_bug_count": None,
                    "zero_confidence_placeholder_count": None,
                    "reason": "fixed-source raw bug declarations before exclusions and clustering",
                }
                for item in selections if isinstance(item, dict) and item.get("model")
            }

        # Fallback for models missing declared_bug_count in provenance to reported_root_per_model
        for m_name in model_names:
            m_str = str(m_name)
            b_info = reported_bug_per_model.get(m_str)
            if not b_info or not b_info.get("available") or b_info.get("declared_bug_count") is None:
                r_info = reported_root_per_model.get(m_str, {})
                if isinstance(r_info, dict) and r_info.get("available") is True and r_info.get("count") is not None:
                    reported_bug_per_model[m_str] = {
                        "available": True,
                        "declared_bug_count": r_info.get("count", 0),
                        "positive_confidence_bug_count": None,
                        "zero_confidence_placeholder_count": None,
                        "reason": str(r_info.get("reason") or "reported root causes"),
                    }
        for i, r in enumerate(root_ranking):
            model = esc(r.get("model"))
            confirmed = ground_truth_hits.get(str(r.get("model") or ""), int(r.get("root_bugs_confirmed", 0) or 0))
            found = int(r.get("root_bugs_found", 0) or 0)
            unverified = int(r.get("root_bugs_unverified", 0) or 0)
            needs_review = int(r.get("root_bugs_needs_review", 0) or 0)
            pending_replay = int(r.get("root_bugs_pending_replay", 0) or 0)
            not_reproduced = int(r.get("root_bugs_not_reproduced", 0) or 0)
            blocked = int(r.get("root_bugs_blocked", 0) or 0)
            reported_roots = reported_root_per_model.get(str(r.get("model") or ""), {})
            reported_roots = reported_roots if isinstance(reported_roots, dict) else {}
            reported_bugs = reported_bug_per_model.get(str(r.get("model") or ""), {})
            reported_bugs = reported_bugs if isinstance(reported_bugs, dict) else {}
            reported_bug_count = reported_bugs.get("declared_bug_count") if reported_bugs.get("available") is True else None
            reported_bug_display = str(int(reported_bug_count)) if reported_bug_count is not None else "n/a"
            reported_bug_reason = str(reported_bugs.get("reason") or "selected run contains no parseable bug-analysis report")
            positive_bug_count = reported_bugs.get("positive_confidence_bug_count")
            zero_bug_count = reported_bugs.get("zero_confidence_placeholder_count")
            if positive_bug_count is not None:
                reported_bug_reason += f"; positive-confidence={positive_bug_count}"
            if zero_bug_count:
                reported_bug_reason += f"; zero-confidence placeholders={zero_bug_count}"
            reported_bug_title = esc(reported_bug_reason)
            rtl_line_count = rtl_line_counts.get(str(r.get("model") or ""), 0)
            breadth = str(r.get("symptom_breadth", "") or "").lower()
            local_rate = r.get("root_local_line_coverage_rate")
            local_count = int(r.get("root_local_coverage_root_count", 0) or 0)

            confirmed_display = f"{confirmed}<small>/{mapped_bug_total}</small>"

            # highlight best model
            is_best = False
            if replay_available:
                is_best = (confirmed == max_confirmed and confirmed > 0)
            else:
                is_best = (found == max_found and found > 0)

            card_class = "root-card" + (" root-card-best" if is_best else "")
            best_badge = f"<span class='root-best-badge'>{esc(_t('root_card_best', lang))}</span>" if is_best else ""

            # Preserve the existing bar treatment, normalized by verified RTL-line count.
            ev_pct = (rtl_line_count / max(max_rtl_lines, 1)) * 100
            ev_color = "#06b6d4" if rtl_line_count > 0 else "#94a3b8"

            # breadth color
            breadth_colors = {"high": "#0d9488", "medium": "#f59e0b", "low": "#f97316", "none": "#94a3b8"}
            breadth_label = _t(f"root_card_breadth_{breadth}" if breadth in ("high", "medium", "low", "none") else "root_card_breadth_none", lang)

            # local coverage string
            if local_rate is not None:
                local_cov_str = _t("root_card_local_cov_detail", lang).format(
                    rate="{:.1f}%".format(float(local_rate)),
                    count=local_count,
                )
            else:
                local_cov_str = local_window_coverage(str(r.get("model") or ""))

            # verified / unverified breakdown
            confirmed_root = int(r.get("root_bugs_confirmed", 0) or 0)
            status_parts = []
            # ``replay_available`` is a DUT-wide completeness flag used for
            # the provisional heading.  It must not hide roots that have
            # already reached a confirmed state while other roots are still
            # pending replay.
            if confirmed_root > 0:
                status_parts.append(f"{confirmed_root} {esc(_t('root_card_verified', lang))}")
            if pending_replay > 0:
                status_parts.append(f"{pending_replay} {esc(_t('root_card_pending_replay', lang))}")
            if not_reproduced > 0:
                status_parts.append(f"{not_reproduced} {esc(_t('root_card_not_reproduced', lang))}")
            if blocked > 0:
                status_parts.append(f"{blocked} {esc(_t('root_card_blocked', lang))}")
            if needs_review > 0:
                status_parts.append(f"{needs_review} needs review")
            status_line = ""
            if status_parts:
                status_line = "<span class='root-status-note'>" + " · ".join(status_parts) + "</span>"

            # FG/FC/CK/BG tag summary
            tags = model_func_tags.get(r.get("model", ""), {})
            fg_n, fc_n, ck_n, bg_n = len(tags.get("fg", set())), len(tags.get("fc", set())), len(tags.get("ck", set())), len(tags.get("bg", set()))
            func_tag_line = ""
            if fg_n + fc_n + ck_n + bg_n > 0:
                tag_parts = []
                if fg_n:
                    tag_parts.append(f"<span class='root-func-chip fg-chip'>{fg_n} FG</span>")
                if fc_n:
                    tag_parts.append(f"<span class='root-func-chip fc-chip'>{fc_n} FC</span>")
                if ck_n:
                    tag_parts.append(f"<span class='root-func-chip ck-chip'>{ck_n} CK</span>")
                if bg_n:
                    tag_parts.append(f"<span class='root-func-chip bg-chip'>{bg_n} BG</span>")
                func_tag_line = "<div class='root-func-tags'>" + " ".join(tag_parts) + "</div>"

            # RTL evidence missing hint
            rtl_warning = ""
            symptoms_in_matrix = sum(1 for rec in benchmark_records if rec.get("model") == r.get("model") and rec.get("status") == "found")
            if symptoms_in_matrix > 0 and found == 0:
                rtl_warning = "<div class='root-rtl-warn'>{warn_text}</div>".format(
                    warn_text=esc(_t("root_card_no_rtl_evidence", lang)).format(n=symptoms_in_matrix),
                )

            root_cards += (
                "<div class='{card_class}'>"
                "<div class='root-card-header'><span class='root-card-model'>{model}</span>{best_badge}</div>"
                "<div class='root-card-metrics'>"
                "<div class='root-metric'><span class='root-metric-val root-val-primary'>{confirmed_display}</span><span class='root-metric-label'>{label_confirmed}</span></div>"
                "<div class='root-metric' title='{reported_bug_title}'><span class='root-metric-val'>{symptoms}</span><span class='root-metric-label'>{label_symptoms}</span></div>"
                "<div class='root-metric'><span class='root-metric-val'>{rtl_line_count}</span><span class='root-metric-label'>{label_evidence}</span></div>"
                "</div>"
                "<div class='root-ev-bar-wrap'><div class='root-ev-bar' style='width:{ev_pct:.1f}%;background:{ev_color}'></div></div>"
                "<div class='root-ev-bar-caption'>{label_evidence_bar}</div>"
                "{rtl_warning}"
                "<div class='root-card-extra'>"
                "<span class='root-breadth-tag' style='background:{breadth_bg};color:{breadth_fg}'>{label_breadth}: {breadth_label}</span>"
                "<span class='root-local-cov'>{label_local_cov}: {local_cov_str}</span>"
                "{status_line}"
                "</div>"
                "{func_tag_line}"
                "</div>"
            ).format(
                card_class=card_class,
                model=model,
                best_badge=best_badge,
                confirmed_display=confirmed_display, confirmed=confirmed, found=found,
                symptoms=reported_bug_display,
                reported_bug_title=reported_bug_title,
                rtl_line_count=rtl_line_count,
                label_confirmed=esc(_t("root_card_confirmed", lang)),
                label_found=esc(_t("root_card_found", lang)),
                label_symptoms=esc(_t("root_card_symptoms", lang)),
                label_evidence=esc(_t("root_card_evidence", lang)),
                label_evidence_bar=esc(_t("root_card_evidence_bar", lang)),
                label_local_cov=esc(_t("root_card_local_cov", lang)),
                label_breadth=esc(_t("root_card_breadth", lang)),
                breadth_label=esc(breadth_label),
                breadth_bg=breadth_colors.get(breadth, "#94a3b8") + "22",
                breadth_fg=breadth_colors.get(breadth, "#94a3b8"),
                local_cov_str=local_cov_str,
                ev_pct=ev_pct, ev_color=ev_color,
                status_line=status_line,
                rtl_warning=rtl_warning, func_tag_line=func_tag_line,
            )

        # ---------- GT/root defect detail table ----------
        gt_table_html = ""
        table_defects = list(ground_truth_defects)
        root_table_fallback = False
        if not table_defects:
            # A root-clustering report can be complete even when the optional
            # adjudicated GT registry has not been materialized.  Present the
            # four clustered RTL roots in the same table shape so the page
            # never reduces them to a headline count only.
            for root_bug in data.get("rtl_root_bugs", []) or []:
                if not isinstance(root_bug, dict):
                    continue
                anchor = root_bug.get("root_anchor") or {}
                models = [
                    model for model, info in (root_bug.get("models") or {}).items()
                    if isinstance(info, dict) and info.get("found")
                ]
                table_defects.append({
                    "gt_id": root_bug.get("rtl_root_bug_id", "?"),
                    "source_root_id": root_bug.get("rtl_root_bug_id", "?"),
                    "rtl_file": anchor.get("file") or anchor.get("path") or "?",
                    "rtl_line_start": anchor.get("line_start", "?"),
                    "rtl_line_end": anchor.get("line_end", "?"),
                    "failure_mode": root_bug.get("failure_mode", "?"),
                    "symptoms": root_bug.get("symptom_bug_ids", []) or [],
                    "models": models,
                })
            root_table_fallback = bool(table_defects)
        if table_defects:
            matrix_by_bug = {}
            for item in data.get("matrix", []) or []:
                if isinstance(item, dict):
                    matrix_by_bug[str(item.get("canonical_bug", ""))] = item
            symptom_to_root = data.get("symptom_to_rtl_root_bug", {}) or {}

            gt_rows = ""
            for defect in table_defects:
                if not isinstance(defect, dict):
                    continue
                gt_id = esc(str(defect.get("gt_id", "?")))
                rtl_file = esc(str(defect.get("rtl_file", "?")))
                line_s = defect.get("rtl_line_start", "?")
                line_e = defect.get("rtl_line_end", "?")
                location = f"{rtl_file}:{line_s}-{line_e}"
                fm_raw = str(defect.get("failure_mode", "?"))
                fm_label = _t(f"fm_{fm_raw}", lang)
                failure_mode = esc(fm_label if fm_label != f"fm_{fm_raw}" else fm_raw)
                symptoms = defect.get("symptoms", []) or []
                source_root = esc(str(defect.get("source_root_id", "?")))

                # model hit status — split into model names + replay tier per model
                hit_models = [m for m in model_names if m in (defect.get("models") or [])]
                is_shared = len(hit_models) > 1
                model_names_cell = []
                model_status_cell = []
                model_symptom_hits = {}
                for m in model_names:
                    if m not in (defect.get("models") or []):
                        continue
                    tiers = []
                    m_symptom_count = 0
                    for s in symptoms:
                        item = matrix_by_bug.get(str(s), {})
                        pm = (item.get("per_model") or {}).get(m, {}) if isinstance(item.get("per_model"), dict) else {}
                        if isinstance(pm, dict) and pm.get("found"):
                            m_symptom_count += 1
                            t = str(pm.get("evidence_tier", ""))
                            tiers.append(t)
                    model_symptom_hits[m] = m_symptom_count
                    if not tiers:
                        shared_cls = " gt-replay-pending" if is_shared else ""
                        model_names_cell.append(f"<span class='gt-model-name{shared_cls}'>{esc(m)}</span>")
                        model_status_cell.append("<span class='gt-status-tag gt-replay-pending'>—</span>")
                        continue
                    if all(t == "replay_confirmed" for t in tiers):
                        tag = esc(_t("tier_replay_confirmed", lang))
                        cls = "gt-replay-ok"
                    elif any(t in ("replay_confirmed", "replay_partial_confirmed") for t in tiers):
                        tag = esc(_t("tier_replay_partial_confirmed", lang))
                        cls = "gt-replay-partial"
                    elif any(t == "execution_supported_pending_replay" for t in tiers):
                        tag = esc(_t("tier_execution_supported", lang))
                        cls = "gt-replay-pending"
                    elif any(t in ("rtl_supported", "waveform_supported") for t in tiers):
                        tag = esc(_t("tier_rtl_supported", lang))
                        cls = "gt-replay-rtl"
                    else:
                        tag = "—"
                        cls = ""
                    shared_cls = f" {cls}" if is_shared else ""
                    model_names_cell.append(f"<span class='gt-model-name{shared_cls}'>{esc(m)}</span>")
                    model_status_cell.append(f"<span class='gt-status-tag {cls}'>{tag}</span>")

                match_status = str(defect.get("root_match_status") or "matched_current_root")
                if not model_names_cell:
                    model_cell = f"<span class='gt-no-hit'>{esc(_t('gt_not_hit', lang))}</span>"
                    status_label = (
                        _t("gt_pending_mapping_review", lang)
                        if match_status != "matched_current_root"
                        else _t("gt_not_hit", lang)
                    )
                    status_cell = f"<span class='gt-no-hit'>{esc(status_label)}</span>"
                else:
                    model_cell = " ".join(model_names_cell)
                    status_cell = " ".join(model_status_cell)

                # symptom → root chain with count and per-model breakdowns
                total_symptoms = len(symptoms)
                symptom_count_label = f"{total_symptoms} 个现象" if lang == "zh" else f"{total_symptoms} symptoms"
                model_counts_items = [f"{esc(m)}: {cnt}" for m, cnt in model_symptom_hits.items()]
                model_counts_str = f" ({', '.join(model_counts_items)})" if model_counts_items else ""
                symptom_meta_html = f"<div class='gt-chain-meta'><span class='gt-symptom-badge'>{symptom_count_label}</span><span class='gt-model-symptom-counts'>{model_counts_str}</span></div>"

                chain_parts = []
                for s in symptoms:
                    s_str = str(s)
                    chain_parts.append(f"<a class='gt-symptom-link' href='bug_evidence_details.html#{esc(s_str)}'><code>{esc(s_str)}</code></a>")
                chain_links_html = ", ".join(chain_parts)
                if source_root and source_root != "?":
                    root_href = f"suspected_bug_{source_root}.html" if root_table_fallback else f"gt_defect_details.html#{source_root}"
                    chain_links_html += f" <span class='gt-chain-arrow'>→</span> <a class='gt-root-link' href='{root_href}'><code class='gt-root-id'>{source_root}</code></a>"
                chain_html = f"{symptom_meta_html}<div class='gt-chain-scroll'>{chain_links_html}</div>"

                gt_id_raw = str(defect.get("gt_id", "?"))
                gt_id_esc = esc(gt_id_raw)
                detail_href = (
                    f"suspected_bug_{gt_id_esc}.html"
                    if root_table_fallback else f"gt_defect_details.html#{gt_id_esc}"
                )
                gt_id_link = f"<a class='gt-id-link' href='{detail_href}' title='查看 {gt_id_esc} 详细缺陷与证据'>{gt_id_esc}</a>"

                gt_rows += (
                    "<tr><td class='gt-id-cell'>{gt_id}</td>"
                    "<td class='gt-loc-cell'>{location}</td>"
                    "<td class='gt-mode-cell'>{mode}</td>"
                    "<td class='gt-models-cell'>{models}</td>"
                    "<td class='gt-status-cell'>{status}</td>"
                    "<td class='gt-chain-cell'>{chain}</td></tr>"
                ).format(
                    gt_id=gt_id_link, location=location, mode=failure_mode,
                    models=model_cell, status=status_cell, chain=chain_html,
                )

            gt_table_html = (
                "<div class='gt-defect-section'>"
                "<div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;'>"
                "<h3>{title}</h3><a class='mini-link' href='gt_defect_details.html'>{link_btn}</a></div>"
                "<p class='gt-defect-desc'>{desc}</p>"
                "<div class='gt-table-wrap'><table class='gt-table'><thead><tr>"
                "<th>{th_id}</th><th>{th_loc}</th><th>{th_mode}</th><th>{th_models}</th><th>{th_status}</th><th>{th_chain}</th>"
                "</tr></thead><tbody>{rows}</tbody></table></div>"
                "<div class='gt-legend'>{legend_ok} &nbsp; {legend_partial} &nbsp; {legend_pending} &nbsp; {legend_rtl} &nbsp; {legend_both}<span class='gt-legend-dot gt-legend-ok'></span><span class='gt-legend-dot gt-legend-partial'></span><span class='gt-legend-dot gt-legend-pending'></span><span class='gt-legend-dot gt-legend-rtl'></span>{legend_suffix}</div>"
                "</div>"
            ).format(
                title=esc("疑似 Bug 详情" if root_table_fallback and lang == "zh" else _t("gt_defect_table_title", lang)),
                link_btn=esc("查看疑似 Bug 详情" if root_table_fallback and lang == "zh" else _t("gt_defect_details_link", lang)),
                desc=esc("以下条目来自 rtl_root_bugs.json 的 RTL 根因聚类，尚未完成 GT 确权；表格展示疑似 Bug 与关联现象的映射。" if root_table_fallback and lang == "zh" else _t("gt_defect_table_desc", lang)),

                th_id=esc(_t("gt_th_id", lang)),
                th_loc=esc(_t("gt_th_location", lang)),
                th_mode=esc(_t("gt_th_mode", lang)),
                th_models=esc(_t("gt_th_models", lang)),
                th_status=esc(_t("gt_th_status", lang)),
                th_chain=esc(_t("gt_th_chain", lang)),
                rows=gt_rows,
                legend_ok=esc(_t("gt_legend_confirmed", lang)),
                legend_partial=esc(_t("gt_legend_partial", lang)),
                legend_pending=esc(_t("gt_legend_pending", lang)),
                legend_rtl=esc(_t("gt_legend_rtl", lang)),
                legend_both=esc(_t("gt_legend_both", lang)),
                legend_suffix=esc(_t("gt_legend_suffix", lang)),
            )

        root_score_section = (
            "<section class='section'>"
            "<div class='section-header'><div><h2>{title}</h2><p>{desc}{replay_note}</p></div></div>"
            "<div class='root-cards-grid'>{cards}</div>"
            "{aux}"
            "</section>"
        ).format(
            title=_t(
                "root_score_title_replayed" if is_replayed
                else ("root_score_title" if replay_available else "root_score_title_provisional"),
                lang
            ),
            desc=_t("root_score_desc", lang).format(
                verified_bug_total=verified_bug_total,
                mapped_bug_total=mapped_bug_total,
                pending_bug_total=pending_bug_total,
                policy_ver=esc(root_scoring.get("policy_version") or "?"),
            ),
            replay_note=replay_note,
            cards=root_cards,
            aux=gt_table_html,
        )
        # auxiliary: symptom score
        symptom_bars = ""
        for i, r in enumerate(ranking):
            pct = max(1, (r.get("total_score", 0) or 0) / max(max_score_val, 1) * 100)
            symptom_bars += (
                "<div class='bar-row'>"
                "<div class='bar-info'><span class='bar-model'>{model}</span><span class='bar-norm'>{norm_label} {norm:.3f}</span></div>"
                "<div class='bar-track'><div class='bar-fill' style='width:{pct:.1f}%;background:{color}'></div></div>"
                "<span class='bar-val'>{score}<small>/{max_s}</small></span>"
                "</div>"
            ).format(
                model=esc(r.get("model")),
                norm_label=_t("score_normalized", lang),
                norm=r.get("normalized_score", 0),
                pct=pct, color=bar_colors[i % 3],
                score=r.get("total_score", 0), max_s=r.get("max_score", 0),
            )
        symptom_score_section = (
            "<section class='section'>"
            "<div class='section-header'><div><h2>{title}</h2><p>{desc}</p></div></div>"
            "{bars}"
            "</section>"
        ).format(
            title=_t("symptom_score_title", lang),
            desc=_t("score_desc", lang).format(total_bugs=total_bugs, max_possible=max_possible, policy_ver=esc(mss.get("policy_version") or "?")),
            bars=symptom_bars,
        )
    else:
        # fallback: no RTL root data, show symptom score only
        score_bars = ""
        for i, r in enumerate(ranking):
            pct = max(1, (r.get("total_score", 0) or 0) / max(max_score_val, 1) * 100)
            score_bars += (
                "<div class='bar-row'>"
                "<div class='bar-info'><span class='bar-model'>{model}</span><span class='bar-norm'>{norm_label} {norm:.3f}</span></div>"
                "<div class='bar-track'><div class='bar-fill' style='width:{pct:.1f}%;background:{color}'></div></div>"
                "<span class='bar-val'>{score}<small>/{max_s}</small></span>"
                "</div>"
            ).format(
                model=esc(r.get("model")),
                norm_label=_t("score_normalized", lang),
                norm=r.get("normalized_score", 0),
                pct=pct, color=bar_colors[i % 3],
                score=r.get("total_score", 0), max_s=r.get("max_score", 0),
            )
        symptom_score_section = (
            "<section class='section'>"
            "<div class='section-header'><div><h2>{title}</h2><p>{desc}</p></div></div>"
            "{bars}"
            "</section>"
        ).format(
            title=_t("score_title", lang),
            desc=_t("score_desc", lang).format(total_bugs=total_bugs, max_possible=max_possible, policy_ver=esc(mss.get("policy_version") or "?")),
            bars=score_bars,
        )

    # evidence chain
    chain_labels = {
        "claim": _t("chain_step_claim", lang),
        "coverage": _t("chain_step_coverage", lang),
        "test_exec": _t("chain_step_test_exec", lang),
        "waveform": _t("chain_step_waveform", lang),
        "rtl": _t("chain_step_rtl", lang),
        "replay_candidate": _t("chain_step_replay_candidate", lang),
        "replay_real": _t("chain_step_replay_real", lang),
        "replay_success": _t("chain_step_replay_success", lang),
    }
    evidence_chain_data = {}
    for model in model_names:
        evidence_chain_data[model] = {k: 0 for k in chain_labels.values()}
    replay_executed = False
    model_found_total = {}
    for model in model_names:
        model_found_total[model] = sum(1 for rec in records
                                       if rec.get("model") == model and rec.get("status") == "found") or 1
    for rec in records:
        m = rec.get("model")
        if m not in evidence_chain_data or rec.get("status") != "found":
            continue
        stats = evidence_chain_data[m]
        if rec.get("claim_sources"):
            stats[chain_labels["claim"]] += 1
        if rec.get("coverage_evidence_summary") and rec.get("coverage_evidence_summary") != "none":
            stats[chain_labels["coverage"]] += 1
        if rec.get("tests"):
            stats[chain_labels["test_exec"]] += 1
        artifact_evidence = _artifact_evidence_items(rec)
        if any(item.get("waveform_summary") or item.get("waveform_observations") for item in artifact_evidence):
            stats[chain_labels["waveform"]] += 1
        if rec.get("rtl_regions"):
            stats[chain_labels["rtl"]] += 1
        if rec.get("replay_manifests") or rec.get("replay_results"):
            stats[chain_labels["replay_candidate"]] += 1
        replay_results = rec.get("replay_results", [])
        if _has_real_replay_result(replay_results):
            stats[chain_labels["replay_real"]] += 1
            replay_executed = True
        if _has_successful_replay_result(replay_results):
            stats[chain_labels["replay_success"]] += 1

    # 每模型按断裂点着色：从 claim 往下，遇到第一个 0/n 之前为青色，之后（含）为红色，全0为灰色
    chain_step_order = ["claim", "coverage", "test_exec", "waveform", "rtl", "replay_candidate"]
    if replay_executed:
        chain_step_order.extend(["replay_real", "replay_success"])
    model_chain_cls = {}
    for model in model_names:
        claim_label = chain_labels["claim"]
        claim_cnt = evidence_chain_data.get(model, {}).get(claim_label, 0)
        if claim_cnt == 0:
            model_chain_cls[model] = {step: "chain-low" for step in chain_step_order}
        else:
            cls_map = {}
            broken = False
            for step in chain_step_order:
                label = chain_labels[step]
                cnt = evidence_chain_data.get(model, {}).get(label, 0)
                if not broken and cnt > 0:
                    cls_map[step] = "chain-high"
                else:
                    broken = True
                    cls_map[step] = "chain-mid"
            model_chain_cls[model] = cls_map

    chain_html = "<table class='chain-table'><thead><tr><th>{}</th>".format(_t("chain_col_evidence_layer", lang))
    for model in model_names:
        chain_html += "<th>{}</th>".format(esc(model))
    chain_html += "</tr></thead><tbody>"
    for step_key in chain_step_order:
        label = chain_labels[step_key]
        chain_html += "<tr><td class='chain-label'>{}</td>".format(label)
        for model in model_names:
            cnt = evidence_chain_data.get(model, {}).get(label, 0)
            found = model_found_total.get(model, 1)
            pct = cnt / found * 100 if found else 0
            cls = model_chain_cls[model][step_key]
            chain_html += "<td class='{}'>{}/{} ({:.0f}%)</td>".format(cls, cnt, found, pct)
        chain_html += "</tr>"
    chain_html += "</tbody></table>"
    replay_chain_note = (
        _t("chain_note_no_replay", lang) if not replay_executed
        else _t("chain_note_with_replay", lang)
    )

    property_by_bug = {
        str(row.get("canonical_bug")): str(row.get("property_text"))
        for row in data.get("matrix", []) or []
        if isinstance(row, dict) and row.get("canonical_bug") and row.get("property_text")
    }
    root_rows = ""
    for root_bug in data.get("rtl_root_bugs", []) or []:
        anchor = root_bug.get("root_anchor", {}) if isinstance(root_bug.get("root_anchor"), dict) else {}
        if anchor.get("file") and anchor.get("line_start") is not None:
            anchor_text = "{}:{}-{}".format(anchor.get("file"), anchor.get("line_start"), anchor.get("line_end"))
        else:
            anchor_text = "n/a"
        symptom_ids = root_bug.get("symptom_bug_ids", []) or []
        representative = str(root_bug.get("representative_property") or "").strip()
        if not representative:
            representative = next(
                (property_by_bug[str(symptom_id)] for symptom_id in symptom_ids if str(symptom_id) in property_by_bug),
                "",
            )
        mode = str(root_bug.get("failure_mode") or "undetermined")
        if not representative:
            signal = str(root_bug.get("primary_signal") or "").strip()
            representative = (
                ("{} 行为异常" if lang == "zh" else "Abnormal {} behavior").format(signal)
                if signal and signal != "unknown"
                else ("RTL 锚点处行为异常" if lang == "zh" else "Abnormal behavior at RTL anchor")
            )
        mode_suffix = ""
        if mode != "undetermined":
            mode_suffix = "<br><small class='muted'>{}: {}</small>".format(
                "规范模式" if lang == "zh" else "Normalized mode",
                esc(mode),
            )
        symptom_cell = "<span title='{title}'>{text}</span>{suffix}".format(
            title=html.escape(representative, quote=True),
            text=esc(representative, 90),
            suffix=mode_suffix,
        )
        merge_title = str(root_bug.get("merge_rationale") or "")
        if mode == "undetermined":
            merge_title = "RTL 锚点与相关信号聚类" if lang == "zh" else "Clustered by RTL anchor and related signals"
        root_rows += (
            "<tr><td class='cid-cell'>{root_id}</td><td>{anchor}</td><td>{mode}</td><td>{symptoms}</td>"
        ).format(
            root_id=esc(root_bug.get("rtl_root_bug_id")),
            anchor=esc(anchor_text),
            mode=symptom_cell,
            symptoms=esc(len(symptom_ids)),
        )
        models = root_bug.get("models", {}) if isinstance(root_bug.get("models"), dict) else {}
        for model in model_names:
            details = models.get(model, {}) if isinstance(models.get(model), dict) else {}
            if details.get("found"):
                label = _t("root_matrix_found", lang).format(count=details.get("symptom_count", 0))
                local = details.get("root_local_line_coverage", {}) if isinstance(details.get("root_local_line_coverage"), dict) else {}
                local_title = ""
                if local.get("available"):
                    local_title = " | {}: {}% ({}/{}, {}-{})".format(
                        "根因局部行覆盖" if lang == "zh" else "Root-local line coverage",
                        local.get("rate"), local.get("hit_lines"), local.get("total_lines"),
                        local.get("window_start"), local.get("window_end"),
                    )
                elif local:
                    local_title = " | {}: {}".format(
                        "根因局部行覆盖不可用" if lang == "zh" else "Root-local line coverage unavailable",
                        local.get("reason") or local.get("status"),
                    )
                root_rows += "<td class='found' title='{title}'>{label}</td>".format(
                    title=esc("{}{}".format(merge_title, local_title)),
                    label=esc(label),
                )
            else:
                root_rows += "<td class='miss'>{}</td>".format(_t("root_matrix_not_found", lang))
        root_rows += "</tr>"
    if not root_rows:
        root_rows = "<tr><td colspan='{}' class='muted'>n/a</td></tr>".format(4 + len(model_names))
    root_matrix_html = (
        "<div class='matrix-wrap'><table class='matrix-table'><thead><tr>"
        "<th>{root_th}</th><th>{anchor_th}</th><th>{mode_th}</th><th>{symptoms_th}</th>{model_headers}"
        "</tr></thead><tbody>{rows}</tbody></table></div>"
    ).format(
        root_th=_t("root_matrix_th_root", lang),
        anchor_th=_t("root_matrix_th_anchor", lang),
        mode_th=_t("root_matrix_th_mode", lang),
        symptoms_th=_t("root_matrix_th_symptoms", lang),
        model_headers="".join("<th>{}</th>".format(esc(model)) for model in model_names),
        rows=root_rows,
    )

    empty_dut_html = ""
    empty_dut_summary = data.get("empty_dut_summary", {})
    if isinstance(empty_dut_summary, dict) and int(empty_dut_summary.get("candidate_count", 0) or 0) == 0 and total_bugs == 0:
        tests_by_model = dict(empty_dut_summary.get("test_count_by_model", {}) or {})
        specs_by_model = dict(empty_dut_summary.get("spec_count_by_model", {}) or {})
        per_model_data = data.get("per_model", {}) if isinstance(data.get("per_model"), dict) else {}
        empty_rows = ""
        for model in model_names:
            t_cnt = tests_by_model.get(model)
            s_cnt = specs_by_model.get(model)
            if t_cnt is None:
                p_entry = per_model_data.get(model, {})
                t_cnt = len(p_entry.get("tests", [])) if isinstance(p_entry, dict) else 0
            if s_cnt is None:
                s_cnt = 0
            empty_rows += (
                "<tr><td>{model}</td><td>{tests}</td><td>{specs}</td><td>0</td><td>{replay}</td></tr>"
            ).format(
                model=esc(model),
                tests=esc(t_cnt),
                specs=esc(s_cnt),
                replay=esc(_t("empty_dut_replay_skipped", lang)),
            )
        empty_dut_html = (
            "<section class='section'>"
            "<div class='section-header'><div><h2>{title}</h2><p>{desc}</p></div></div>"
            "<div class='matrix-wrap'><table class='matrix-table'><thead><tr>"
            "<th>{model_th}</th><th>{tests_th}</th><th>{specs_th}</th><th>{candidates_th}</th><th>{replay_th}</th>"
            "</tr></thead><tbody>{rows}</tbody></table></div></section>"
        ).format(
            title=esc(_t("empty_dut_title", lang)),
            desc=esc(_t("empty_dut_desc", lang)),
            model_th=esc(_t("empty_dut_model", lang)),
            tests_th=esc(_t("empty_dut_tests", lang)),
            specs_th=esc(_t("empty_dut_specs", lang)),
            candidates_th=esc(_t("empty_dut_candidates", lang)),
            replay_th=esc(_t("empty_dut_replay", lang)),
            rows=empty_rows,
        )

    # ── model run source summary ──
    model_sources_html = ""
    raw_sources = data.get("model_sources", []) if isinstance(data.get("model_sources"), list) else []
    provenance = data.get("audit_provenance", {})
    selections = provenance.get("source_selection", []) if isinstance(provenance, dict) else []
    if not isinstance(selections, list):
        selections = []

    sources_by_model = {}
    for item in raw_sources:
        if isinstance(item, dict) and item.get("model"):
            sources_by_model[str(item["model"])] = dict(item)

    for selection in selections:
        if not isinstance(selection, dict) or not selection.get("model"):
            continue
        m_name = str(selection.get("model"))
        ws_src = selection.get("workspace_source", "")
        r_key = selection.get("run_key", "")
        is_inc = (r_key == "incremental_run") or selection.get("included") is True and "incremental" in str(selection.get("reason", ""))
        default_reason = "增量引入：已纳入" if is_inc else "固定来源审计：已纳入"
        default_reason_en = "Included by incremental run" if is_inc else "Included by fixed-source audit"

        if m_name not in sources_by_model:
            sources_by_model[m_name] = {
                "model": m_name,
                "dut": data.get("dut", ""),
                "run_key": r_key,
                "workspace_name": ws_src or r_key or m_name,
                "workspace_root": ws_src,
                "input_path": ws_src,
                "included": True,
                "reason": default_reason,
                "reason_en": default_reason_en,
            }
        else:
            existing = sources_by_model[m_name]
            if not existing.get("workspace_name") or existing.get("workspace_name") == "?":
                existing["workspace_name"] = ws_src or r_key or m_name
            if not existing.get("workspace_root"):
                existing["workspace_root"] = ws_src
            if not existing.get("input_path"):
                existing["input_path"] = ws_src
            if not existing.get("run_key"):
                existing["run_key"] = r_key
            if not existing.get("reason"):
                existing["reason"] = default_reason
                existing["reason_en"] = default_reason_en

    for m_name in model_names:
        if m_name not in sources_by_model:
            sources_by_model[m_name] = {
                "model": m_name,
                "dut": data.get("dut", ""),
                "run_key": "",
                "workspace_name": m_name,
                "workspace_root": "",
                "input_path": "",
                "included": True,
                "reason": "固定来源审计：已纳入",
                "reason_en": "Included by fixed-source audit",
            }

    model_sources = list(sources_by_model.values())
    if model_sources:
        ms_order = {m: i for i, m in enumerate(model_names)}
        model_sources = sorted(model_sources, key=lambda s: ms_order.get(str(s.get("model", "")), 999))
        source_rows = ""
        for src in model_sources:
            ws_name = src.get("workspace_name_en", src.get("workspace_name", "?")) if lang == "en" else src.get("workspace_name", "?")
            ws_root = src.get("workspace_root", "")
            input_path = src.get("input_path", "")
            reason = src.get("reason_en", src.get("reason", "")) if lang == "en" else src.get("reason", "")
            source_rows += (
                "<tr><td>{model}</td><td>{dut}</td><td class='run-id-cell' title='{ws_root}'>{ws_name}</td>"
                "<td class='path-cell' title='{input_path}'>{input_display}</td>"
                "<td class='path-cell' title='{reason}'>{reason_display}</td></tr>"
            ).format(
                model=esc(src.get("model", "?")),
                dut=esc(src.get("dut", "?")),
                ws_root=esc(ws_root),
                ws_name=esc(ws_name, 50),
                input_path=esc(input_path),
                input_display=esc(input_path, 70),
                reason=esc(reason),
                reason_display=esc(reason, 90),
            )
        model_sources_html = (
            "<section class='section'>"
            "<div class='section-header'><div><h2>{title}</h2><p>{desc}</p></div></div>"
            "<div class='matrix-wrap'><table class='matrix-table'><thead><tr>"
            "<th>{th_model}</th><th>{th_dut}</th><th>{th_run}</th><th>{th_input}</th><th>{th_reason}</th>"
            "</tr></thead><tbody>{rows}</tbody></table></div></section>"
        ).format(
            title=_t("run_source_title", lang),
            desc=_t("run_source_desc", lang),
            th_model=_t("run_source_th_model", lang),
            th_dut=_t("run_source_th_dut", lang),
            th_run=_t("run_source_th_run", lang),
            th_input=_t("run_source_th_input", lang),
            th_reason=_t("run_source_th_reason", lang),
            rows=source_rows,
        )

    # donut charts
    donut_colors = ["#06b6d4", "#f59e0b", "#8b5cf6"]
    donut_html = ""
    for i, r in enumerate(ranking):
        model = r["model"]
        score = r.get("total_score", 0)
        max_s = r.get("max_score", 0)
        norm = r.get("normalized_score", 0)
        tiers = r.get("tier_counts", {})
        found_count = r.get("found_count", 0)
        total = sum(v for k, v in tiers.items() if k != "not_found")
        total_all = total + tiers.get("not_found", 0)
        if total_all == 0:
            total_all = 1

        deg = 0.0
        grad_parts = []
        for tier in tier_order:
            cnt = tiers.get(tier, 0)
            if cnt <= 0:
                continue
            span = cnt / total_all * 360.0
            color = tier_colors.get(tier, "#999")
            grad_parts.append("{} {}deg {}deg".format(color, deg, deg + span))
            deg += span
        nf = tiers.get("not_found", 0)
        if nf > 0:
            span = nf / total_all * 360.0
            grad_parts.append("{} {}deg {}deg".format(tier_colors["not_found"], deg, deg + span))
        if not grad_parts:
            grad_parts.append("#e5e7eb 0deg 360deg")

        conic = ", ".join(grad_parts)
        ac = donut_colors[i % 3]

        leg_items = ""
        for tier in tier_order:
            cnt = tiers.get(tier, 0)
            if cnt <= 0:
                continue
            leg_items += "<div class='dl-item'><span class='dl-dot' style='background:{}'></span>{} <b>{}</b></div>".format(
                tier_colors[tier], tier_labels.get(tier, tier), cnt)

        donut_html += (
            "<div class='donut-card'>"
            "<div class='donut-ring' style='background:conic-gradient({conic})'>"
            "<div class='donut-hole'>"
            "<span class='donut-val'>{score}/{max_s}</span>"
            "<span class='donut-sub'>{norm_label} {norm:.3f}</span>"
            "</div></div>"
            "<div class='donut-info'>"
            "<h3 class='donut-name' style='color:{ac}'>{model}</h3>"
            "<p class='donut-meta'>"
            "<span class='donut-badge' style='background:{ac}15;color:{ac}'>{found_text}</span>"
            "<span class='donut-badge' style='background:{ac}08;color:var(--muted)'>{total_text}</span></p>"
            "<div class='donut-legend'>{leg_items}</div>"
            "</div></div>"
        ).format(
            conic=conic, score=score, max_s=max_s, norm=norm,
            norm_label=_t("score_normalized", lang),
            model=esc(model), ac=ac,
            found_text=_t("evidence_found_count", lang).format(found_count=found_count),
            total_text=_t("evidence_total_bugs", lang).format(total_all=total_all),
            leg_items=leg_items,
        )

    # bug matrix
    compact_rows = ""
    for row in data.get("matrix", []):
        prop_disp_full, prop_tooltip = _property_description_for_lang(row, records_by_key, model_names, lang)
        prop = trunc(prop_disp_full, 90)
        # Collect signals from row, with fallback to per-model records
        row_sigs = list(row.get("signals") or [])
        if not row_sigs:
            for m in model_names:
                rec = records_by_key.get((row.get("canonical_bug"), m), {})
                if isinstance(rec, dict):
                    row_sigs.extend(rec.get("signals") or [])
                    row_sigs.extend(rec.get("waveform_focus_signals") or [])
            row_sigs = [s for s in dict.fromkeys(row_sigs) if s and s != "unknown"]
        signals_full = ", ".join(row_sigs) or _t("matrix_signals_none", lang)
        signals = esc(signals_full, 30)

        rtl_locations, rtl_hover = _matrix_rtl_locations(row, model_names, records_by_key)
        rtl_text = ", ".join(rtl_locations[:3]) or "n/a"
        if len(rtl_locations) > 3:
            rtl_text += f" +{len(rtl_locations) - 3}"
        rtl_cell = "<td class='rtl-loc-cell' title='{title}'>{display}</td>".format(
            title=html.escape("\n".join(rtl_hover) or "n/a", quote=True),
            display=esc(rtl_text, 44),
        )
        model_cells = ""
        for m in model_names:
            pm = row.get("per_model", {}).get(m, {})
            if pm.get("found"):
                s = pm.get("evidence_score", 0)
                record = records_by_key.get((row.get("canonical_bug"), m), {})
                aux_source = record if isinstance(record, dict) and record else pm
                title_text = "{}: {} | {}".format(
                    _t("matrix_cell_tier", lang),
                    _evidence_tier_label(pm.get("evidence_tier", ""), lang),
                    _evidence_support_title(aux_source, lang),
                )
                model_cells += "<td class='cell-found' title='{title}'>&#10003;&nbsp;{score}</td>".format(
                    title=esc(title_text),
                    score=s,
                )
            else:
                model_cells += "<td class='cell-miss'></td>"
        compact_rows += (
            "<tr><td class='cid-cell' title='{cid}'><a href='bug_evidence_details.html#{cid_anchor}'>{cid_d}</a></td>"
            "<td class='prop-cell' title='{prop_full}'>{prop}</td>"
            "<td class='sig-cell' title='{sig_title}'>{sig}</td>{rtl_cell}{mcells}</tr>"
        ).format(
            cid=esc(row.get("canonical_bug") or "?"), cid_d=trunc(row.get("canonical_bug") or "?", 24),
            cid_anchor=esc(row.get("canonical_bug") or "?"),
            prop_full=html.escape(prop_tooltip, quote=True),
            prop=prop, sig_title=esc(signals_full), sig=signals, rtl_cell=rtl_cell, mcells=model_cells,
        )

    lang_code = "zh-CN" if lang == "zh" else "en"
    stats_model_title = {"zh": "参与基准评测的 LLM 模型", "en": "LLM models in this benchmark"}
    stats_canonical_title = {"zh": "跨模型聚类去重后的独立 Bug 总数", "en": "Unique bugs after cross-model clustering"}
    stats_shared_title = {"zh": "被 ≥2 个模型同时发现的规范 Bug", "en": "Canonical bugs found by ≥2 models"}
    stats_unique_title = {"zh": "仅被单一模型发现的规范 Bug", "en": "Canonical bugs found by only one model"}
    stats_llm_title = {"zh": "LLM 语义评判的跨模型候选对总数", "en": "Cross-model candidate pairs judged by LLM"}
    stats_audit_title = {"zh": "LLM 判定为不应合并的相似候选对", "en": "Similar pairs LLM decided should not merge"}

    return """<!DOCTYPE html>
<html lang="{lang_code}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{
      --bg: #f8fafc; --card: #ffffff; --ink: #1e293b; --muted: #64748b;
      --border: #e2e8f0;
      --radius: clamp(10px, 1.2vw, 18px); --radius-sm: clamp(6px, 0.8vw, 12px);
      --gap: clamp(8px, 1vw, 18px);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "PingFang SC","Noto Sans SC",-apple-system,"Segoe UI",sans-serif;
      color: var(--ink); background: var(--bg); line-height: 1.6;
      font-size: clamp(13px, 1vw, 16px);
    }}
    .page {{
      width: min(98%, 1800px); margin: 0 auto;
      padding: clamp(12px, 1.5vw, 36px) clamp(10px, 1.8vw, 40px);
    }}
    h1 {{ font-size: clamp(18px, 1.8vw, 32px); font-weight: 700; letter-spacing: -0.02em; }}
    h2 {{ font-size: clamp(14px, 1.3vw, 22px); font-weight: 700; }}
    h3 {{ font-size: clamp(12px, 1.1vw, 18px); font-weight: 600; }}

    .hero {{
      padding: clamp(16px, 2vw, 40px) clamp(18px, 2.5vw, 48px);
      background: var(--card); border: 1px solid var(--border);
      border-radius: var(--radius); box-shadow: 0 2px 8px rgba(0,0,0,0.04);
      margin-bottom: var(--gap);
    }}
    .hero h1 {{ margin-bottom: clamp(4px, 0.5vw, 12px); }}
    .hero p {{ color: var(--muted); font-size: clamp(11px, 0.95vw, 16px); max-width: 60em; }}
    .hero .hl {{ color: #06b6d4; font-weight: 600; }}
    .dut-badge {{
      float: right; padding: 0.15em 0.6em;
      background: #e0f2fe; color: #0369a1; border-radius: 999px;
      font-size: inherit; font-weight: 700;
    }}

    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(clamp(100px, 10vw, 160px), 1fr));
      gap: var(--gap); margin-bottom: clamp(10px, 1.2vw, 28px);
    }}
    .stat-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: clamp(10px, 1.2vw, 22px) clamp(8px, 1vw, 20px); text-align: center;
      box-shadow: 0 1px 4px rgba(0,0,0,0.04); transition: box-shadow 0.2s;
    }}
    .stat-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.08); }}
    .stat-card .label {{
      color: var(--muted); font-size: clamp(9px, 0.7vw, 13px);
      text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .stat-card .value {{
      display: block; margin-top: clamp(2px, 0.3vw, 8px);
      font-size: clamp(18px, 2.2vw, 40px); font-weight: 700; color: var(--ink);
    }}
    .stat-card .hint {{
      display: block; margin-top: clamp(2px, 0.3vw, 6px);
      font-size: clamp(8px, 0.6vw, 11px); color: var(--muted);
    }}

    .overlap-ring {{
      width: clamp(80px, 8vw, 140px); height: clamp(80px, 8vw, 140px); flex-shrink: 0;
      border-radius: 50%; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      display: flex; align-items: center; justify-content: center;
    }}
    .overlap-hole {{
      width: clamp(48px, 5vw, 88px); height: clamp(48px, 5vw, 88px);
      border-radius: 50%; background: #fff;
      display: flex; align-items: center; justify-content: center;
      box-shadow: inset 0 1px 4px rgba(0,0,0,0.08);
    }}
    .overlap-val {{ font-size: clamp(11px, 1.2vw, 20px); font-weight: 700; color: var(--ink); }}

    .section {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
      padding: clamp(14px, 1.8vw, 32px); margin-bottom: var(--gap);
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }}
    .section-header {{
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: clamp(8px, 1vw, 22px);
    }}
    .section-header p {{ color: var(--muted); font-size: clamp(10px, 0.8vw, 14px); }}

    .bar-row {{
      display: flex; align-items: center;
      gap: clamp(6px, 0.8vw, 18px);
      margin: clamp(6px, 0.8vw, 16px) 0;
    }}
    .bar-info {{ width: clamp(80px, 9vw, 140px); flex-shrink: 0; text-align: right; }}
    .bar-model {{ display: block; font-weight: 600; font-size: clamp(11px, 0.95vw, 16px); }}
    .bar-norm {{ display: block; font-size: clamp(9px, 0.7vw, 12px); color: var(--muted); }}
    .bar-track {{
      flex: 1; height: clamp(18px, 2vw, 38px);
      background: #f1f5f9; border-radius: 999px; overflow: hidden;
    }}
    .bar-fill {{
      height: 100%; border-radius: 999px; transition: width 0.6s ease;
      background-size: clamp(12px, 1.4vw, 22px) clamp(12px, 1.4vw, 22px);
    }}
    .bar-fill:hover {{ filter: brightness(1.05); }}
    .bar-val {{
      width: clamp(50px, 6vw, 90px); flex-shrink: 0;
      font-size: clamp(14px, 1.3vw, 24px); font-weight: 700;
    }}
    .bar-val small {{ font-size: clamp(9px, 0.7vw, 14px); font-weight: 400; color: var(--muted); }}

    /* ── RTL root evaluation cards ── */
    .root-cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(clamp(260px, 24vw, 380px), 1fr));
      gap: var(--gap);
    }}
    .root-card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: var(--radius); padding: clamp(14px, 1.4vw, 28px);
      box-shadow: 0 1px 6px rgba(0,0,0,0.04);
      display: flex; flex-direction: column; gap: clamp(8px, 0.9vw, 18px);
    }}
    .root-card-best {{
      border-color: #06b6d4; box-shadow: 0 0 0 1px #06b6d4, 0 4px 16px rgba(6,182,212,0.12);
    }}
    .root-card-header {{
      display: flex; align-items: center; justify-content: space-between;
      gap: clamp(6px, 0.6vw, 12px);
    }}
    .root-card-model {{
      font-size: clamp(14px, 1.2vw, 22px); font-weight: 700; color: var(--ink);
      word-break: break-word;
    }}
    .root-best-badge {{
      flex-shrink: 0; font-size: clamp(9px, 0.65vw, 11px); font-weight: 600;
      padding: 0.15em 0.55em; border-radius: 999px;
      background: #06b6d4; color: #fff;
    }}
    .root-card-metrics {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: clamp(4px, 0.5vw, 12px);
    }}
    .root-metric {{
      text-align: center; padding: clamp(6px, 0.7vw, 14px) 0;
    }}
    .root-metric-val {{
      display: block; font-size: clamp(20px, 2.4vw, 42px); font-weight: 700;
      color: var(--ink); line-height: 1.15;
    }}
    .root-metric-val small {{
      font-size: clamp(12px, 1.4vw, 22px); font-weight: 400; color: var(--muted);
    }}
    .root-val-primary {{ color: #06b6d4; }}
    .root-metric-label {{
      display: block; margin-top: clamp(2px, 0.3vw, 6px);
      font-size: clamp(9px, 0.65vw, 12px); color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.03em;
    }}
    .root-ev-bar-wrap {{
      height: clamp(6px, 0.6vw, 10px); background: #f1f5f9;
      border-radius: 999px; overflow: hidden;
    }}
    .root-ev-bar {{
      height: 100%; border-radius: 999px; transition: width 0.6s ease;
    }}
    .root-ev-bar-caption {{
      text-align: right;
      font-size: clamp(8px, 0.55vw, 10px); color: #94a3b8;
      margin-top: 0;
    }}
    .root-card-extra {{
      display: flex; flex-wrap: wrap; align-items: center;
      gap: clamp(6px, 0.7vw, 14px);
      font-size: clamp(9px, 0.65vw, 12px); color: var(--muted);
    }}
    .root-breadth-tag {{
      padding: 0.15em 0.5em; border-radius: 999px;
      font-weight: 600;
    }}
    .root-local-cov {{
      white-space: nowrap;
    }}
    .root-status-note {{
      color: #f59e0b; font-weight: 500;
    }}
    .root-rtl-warn {{
      margin-top: clamp(6px, 0.6vw, 12px);
      padding: clamp(4px, 0.4vw, 8px) clamp(8px, 0.6vw, 12px);
      background: #fef3c7; border: 1px solid #fbbf24; border-radius: var(--radius-sm);
      font-size: clamp(10px, 0.7vw, 13px); color: #92400e;
    }}
    .root-func-tags {{
      margin-top: clamp(8px, 0.7vw, 14px);
      display: flex; flex-wrap: wrap; gap: clamp(4px, 0.4vw, 8px);
    }}
    .root-func-chip {{
      display: inline-block;
      padding: 0.15em 0.55em; border-radius: 999px;
      font-size: clamp(9px, 0.65vw, 12px); font-weight: 600;
      letter-spacing: 0.02em;
    }}
    .fg-chip {{ background: #e0f2fe; color: #0369a1; }}
    .fc-chip {{ background: #f0fdf4; color: #15803d; }}
    .ck-chip {{ background: #fef3c7; color: #a16207; }}
    .bg-chip {{ background: #f3e8ff; color: #7c3aed; }}
    /* GT defect detail table */
    .gt-defect-section {{
      margin-top: clamp(14px, 1.4vw, 28px);
    }}
    .gt-defect-section h3 {{
      font-size: clamp(14px, 0.9vw, 17px); font-weight: 700;
      color: #0f172a; margin: 0 0 3px;
    }}
    .gt-defect-desc {{
      font-size: clamp(12px, 0.75vw, 14px); color: #475569;
      margin: 0 0 clamp(10px, 0.8vw, 16px);
    }}
    .gt-table-wrap {{
      overflow-x: auto; -webkit-overflow-scrolling: touch;
      border: 1px solid #cbd5e1; border-radius: var(--radius-sm);
      scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent;
    }}
    .gt-table-wrap::-webkit-scrollbar {{ height: 6px; }}
    .gt-table-wrap::-webkit-scrollbar-track {{ background: transparent; }}
    .gt-table-wrap::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
    .gt-table {{
      width: 100%; min-width: 920px; table-layout: fixed; border-collapse: collapse;
      font-size: clamp(12px, 0.8vw, 14px);
      color: #1e293b;
    }}
    .gt-table th {{
      background: #f8fafc; font-weight: 600; text-align: left;
      padding: clamp(7px, 0.55vw, 11px) clamp(10px, 0.7vw, 16px);
      border-bottom: 2px solid #e2e8f0; color: var(--muted);
      position: sticky; top: 0; z-index: 1;
      font-size: clamp(12px, 0.8vw, 14px);
      text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap;
    }}
    .gt-table td {{
      padding: clamp(6px, 0.5vw, 10px) clamp(10px, 0.7vw, 16px);
      border-bottom: 1px solid #e2e8f0; vertical-align: top;
      color: #0f172a; white-space: normal; overflow-wrap: anywhere; word-break: break-word;
    }}
    .gt-id-cell {{ font-family: "SFMono-Regular",Consolas,monospace; font-weight: 700; color: #0d9488; font-size: clamp(12px, 0.8vw, 14px); }}
    .gt-id-link {{ color: #0d9488; text-decoration: none; border-bottom: 1px dashed #0d9488; transition: all 0.2s; }}
    .gt-id-link:hover {{ color: #0f766e; border-bottom-style: solid; background: #f0fdfa; border-radius: 2px; }}
    .gt-loc-cell {{ font-family: "SFMono-Regular",Consolas,monospace; font-size: clamp(12px, 0.8vw, 14px); }}
    .gt-mode-cell {{  }}
    .gt-models-cell {{ line-height: 1.7; }}
    .gt-model-name {{
      display: inline-block; margin: 1px 2px; vertical-align: middle;
      font-weight: 700; color: #0f172a;
      font-size: clamp(12px, 0.8vw, 14px);
    }}
    .gt-model-name.gt-replay-ok {{ color: #0369a1; }}
    .gt-model-name.gt-replay-partial {{ color: #a16207; }}
    .gt-model-name.gt-replay-pending {{ color: #075985; }}
    .gt-model-name.gt-replay-rtl {{ color: #581c87; }}
    .gt-status-cell {{ line-height: 1.7; }}
    .gt-status-tag {{
      display: inline-block; margin: 1px 2px; vertical-align: middle;
      padding: 2px 8px; border-radius: 999px;
      font-weight: 400; font-size: clamp(12px, 0.8vw, 14px);
      white-space: nowrap; color: #0f172a;
    }}
    .gt-status-tag.gt-replay-ok {{ background: #e0f2fe; }}
    .gt-status-tag.gt-replay-partial {{ background: #fef3c7; }}
    .gt-status-tag.gt-replay-pending {{ background: #bae6fd; }}
    .gt-status-tag.gt-replay-rtl {{ background: #e9d5ff; }}
    .gt-no-hit {{ color: #64748b; font-weight: 500; font-size: clamp(12px, 0.8vw, 14px); }}
    .gt-chain-cell {{ vertical-align: middle; }}
    .gt-chain-meta {{ margin-bottom: 4px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .gt-symptom-badge {{
      display: inline-block; padding: 1px 7px; border-radius: 999px;
      background: #f1f5f9; color: #334155; font-size: clamp(10px, 0.65vw, 12px); font-weight: 600;
    }}
    .gt-model-symptom-counts {{
      color: #64748b; font-size: clamp(10px, 0.65vw, 12px); font-family: "SFMono-Regular",Consolas,monospace;
    }}
    .gt-symptom-link {{ text-decoration: none; }}
    .gt-symptom-link:hover code {{ background: #cbd5e1; color: #0f172a; }}
    .gt-root-link {{ text-decoration: none; }}
    .gt-root-link:hover code {{ background: #bae6fd !important; }}
    .gt-chain-scroll {{
      display: flex; flex-wrap: wrap; align-items: baseline; gap: 3px 6px;
      font-size: clamp(11px, 0.7vw, 13px);
    }}
    .gt-chain-scroll code {{
      background: #e2e8f0; padding: 2px 5px; border-radius: 3px;
      font-size: clamp(10px, 0.65vw, 12px); white-space: nowrap;
      color: #0f172a; font-weight: 500;
    }}
    .gt-chain-arrow {{ color: #64748b; font-weight: 800; margin: 0 3px; font-size: clamp(11px, 0.7vw, 13px); }}
    .gt-root-id {{ background: #e0f2fe !important; color: #0369a1 !important; font-weight: 700; }}
    .gt-legend {{
      text-align: right; margin-top: clamp(4px, 0.5vw, 10px);
      font-size: clamp(11px, 0.7vw, 13px); color: #64748b; line-height: 1.8;
    }}
    .gt-legend-dot {{
      display: inline-block; width: 10px; height: 10px; border-radius: 3px;
      vertical-align: middle; margin-right: 2px;
    }}
    .gt-legend-ok {{ background: #e0f2fe; border: 1px solid #7dd3fc; }}
    .gt-legend-partial {{ background: #fef3c7; border: 1px solid #fde68a; }}
    .gt-legend-pending {{ background: #bae6fd; border: 1px solid #38bdf8; }}
    .gt-legend-rtl {{ background: #e9d5ff; border: 1px solid #c084fc; }}
    /* coverage table count cells */
    .func-count-cell {{
      text-align: center; vertical-align: middle;
      padding: clamp(4px, 0.4vw, 8px) !important;
    }}
    .matrix-table th.count-col {{
      text-align: center;
    }}
    .func-count-empty {{ color: var(--muted); font-style: italic; }}
    .func-detail-chip {{
      display: inline-block;
      padding: 1px 6px; margin: 1px 2px;
      border-radius: 999px;
      font-size: clamp(9px, 0.6vw, 11px); font-weight: 500;
      white-space: nowrap;
    }}
    /* tag detail cards */
    .tags-scroll-wrap {{
      max-height: clamp(300px, 40vh, 600px); overflow-y: auto;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: var(--gap);
    }}
    .tags-cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(clamp(300px, 30vw, 520px), 1fr));
      gap: var(--gap);
    }}
    .tags-card {{
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: #fafbfc; box-shadow: 0 1px 4px rgba(0,0,0,0.04);
      max-height: clamp(260px, 32vh, 480px); overflow-y: auto;
    }}
    .tags-card-header {{
      padding: clamp(10px, 0.9vw, 18px) clamp(14px, 1.2vw, 24px);
      background: #f1f5f9; border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 1;
    }}
    .tags-card-model {{
      font-weight: 700; font-size: clamp(13px, 0.9vw, 17px);
      color: var(--heading);
    }}
    .tags-card-body {{
      padding: clamp(10px, 0.9vw, 18px) clamp(14px, 1.2vw, 24px);
      display: flex; flex-direction: column; gap: clamp(10px, 0.9vw, 18px);
    }}
    .tags-block-row {{
      display: flex; align-items: flex-start; gap: clamp(8px, 0.7vw, 14px);
    }}
    .tags-block-label {{
      display: inline-block; min-width: 32px;
      padding: 2px 8px; border-radius: 999px;
      font-size: clamp(10px, 0.7vw, 12px); font-weight: 700;
      text-align: center; white-space: nowrap;
      flex-shrink: 0;
    }}
    .tags-block-label.fg-chip {{ font-size: clamp(10px, 0.7vw, 12px); }}
    .tags-block-label.fc-chip {{ font-size: clamp(10px, 0.7vw, 12px); }}
    .tags-block-label.ck-chip {{ font-size: clamp(10px, 0.7vw, 12px); }}
    .tags-block-label.bg-chip {{ font-size: clamp(10px, 0.7vw, 12px); }}
    .tags-block-chips {{
      display: flex; flex-wrap: wrap; gap: 3px; align-items: flex-start;
      line-height: 1.8;
    }}

    .donut-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 28vw, 420px), 1fr));
      gap: var(--gap);
    }}
    .donut-card {{
      display: flex; align-items: center;
      gap: clamp(12px, 1.5vw, 28px);
      padding: clamp(12px, 1.2vw, 24px);
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: #fafbfc; box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }}
    .donut-ring {{
      width: clamp(90px, 10vw, 170px); height: clamp(90px, 10vw, 170px); flex-shrink: 0;
      border-radius: 50%; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      display: flex; align-items: center; justify-content: center;
    }}
    .donut-hole {{
      width: clamp(50px, 5.8vw, 98px); height: clamp(50px, 5.8vw, 98px);
      border-radius: 50%; background: #fff;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      box-shadow: inset 0 1px 4px rgba(0,0,0,0.08);
    }}
    .donut-val {{ font-size: clamp(13px, 1.6vw, 26px); font-weight: 700; color: var(--ink); line-height: 1.1; }}
    .donut-sub {{ font-size: clamp(7px, 0.6vw, 11px); color: var(--muted); margin-top: 1px; }}
    .donut-info {{ flex: 1; min-width: 0; }}
    .donut-name {{ font-size: clamp(12px, 1.1vw, 18px); font-weight: 700; margin-bottom: 4px; }}
    .donut-meta {{ display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: clamp(4px, 0.6vw, 12px); }}
    .donut-badge {{
      display: inline-block; padding: 2px clamp(6px, 0.6vw, 12px);
      border-radius: 999px; font-size: clamp(9px, 0.65vw, 12px); font-weight: 500;
    }}
    .donut-legend {{
      display: flex; flex-wrap: wrap;
      gap: clamp(2px, 0.3vw, 6px) clamp(6px, 1vw, 18px);
      font-size: clamp(9px, 0.7vw, 13px);
    }}
    .dl-item {{ display: flex; align-items: center; gap: 4px; color: var(--muted); }}
    .dl-item b {{ color: var(--ink); font-size: clamp(10px, 0.75vw, 14px); }}
    .dl-dot {{
      display: inline-block;
      width: clamp(7px, 0.6vw, 10px); height: clamp(7px, 0.6vw, 10px);
      border-radius: 50%; flex-shrink: 0;
    }}

    .chain-table {{
      width: 100%; border-collapse: collapse;
      font-size: clamp(11px, 0.85vw, 15px);
    }}
    .chain-table th, .chain-table td {{
      padding: clamp(6px, 0.6vw, 12px) clamp(8px, 1vw, 18px);
      text-align: center; border-bottom: 1px solid var(--border);
    }}
    .chain-table th {{
      background: #f8fafc; font-weight: 600;
      font-size: clamp(10px, 0.75vw, 14px); color: var(--muted);
    }}
    .chain-table th:first-child, .chain-table td.chain-label {{ text-align: left; font-weight: 600; }}
    .chain-high {{ background: #ecfeff; color: #0891b2; font-weight: 700; }}
    .chain-mid  {{ background: #fef2f2; color: #dc2626; font-weight: 600; }}
    .chain-low  {{ background: #f3f4f6; color: #6b7280; }}

    .audit-rel {{ display: flex; flex-wrap: wrap; gap: clamp(6px, 1vw, 18px); margin-bottom: clamp(10px, 1.2vw, 24px); }}
    .audit-rel-item {{
      background: #f8fafc; border: 1px solid var(--border);
      padding: clamp(6px, 0.7vw, 14px) clamp(10px, 1.2vw, 22px);
      border-radius: var(--radius-sm); font-size: clamp(11px, 0.85vw, 16px);
    }}
    .audit-rel-item b {{ color: #06b6d4; font-size: clamp(14px, 1.2vw, 24px); }}
    .audit-wrap {{
      max-height: clamp(300px, 40vh, 600px); overflow-y: auto;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
    }}
    .audit-table {{
      width: 100%; border-collapse: collapse;
      font-size: clamp(9px, 0.7vw, 13px);
    }}
    .audit-table thead {{ position: sticky; top: 0; z-index: 2; }}
    .audit-table th {{
      padding: clamp(5px, 0.5vw, 11px) clamp(6px, 0.6vw, 14px);
      text-align: left; background: #f8fafc;
      border-bottom: 2px solid #e2e8f0;
      font-size: clamp(8px, 0.6vw, 11px); color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap;
    }}
    .audit-table td {{
      padding: clamp(4px, 0.5vw, 9px) clamp(6px, 0.6vw, 14px);
      border-bottom: 1px solid #f1f5f9;
      max-width: clamp(80px, 10vw, 180px);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .audit-table tbody tr:hover {{ background: #f0fdfa; }}
    .pair-id-cell {{
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(8px, 0.62vw, 11px);
      color: #0369a1;
      font-weight: 700;
      white-space: nowrap;
    }}
    .am {{ font-weight: 500; font-size: clamp(9px, 0.7vw, 13px); }}
    .ar {{ color: var(--muted); font-size: clamp(8px, 0.6vw, 11px); }}
    .as {{ font-weight: 600; text-align: center; }}
    .rel-diff {{ color: #d97706; font-weight: 500; }}
    .rel-related {{ color: #8b5cf6; font-weight: 500; }}
    .rel-insuf {{ color: #dc2626; font-weight: 500; }}

    .matrix-wrap {{
      max-height: clamp(300px, 40vh, 600px); overflow-y: auto;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
    }}
    .matrix-table {{
      width: 100%; border-collapse: collapse;
      font-size: clamp(10px, 0.75vw, 14px);
    }}
    .matrix-table thead {{ position: sticky; top: 0; z-index: 2; }}
    .matrix-table th {{
      padding: clamp(6px, 0.6vw, 13px) clamp(8px, 0.8vw, 16px);
      text-align: left; background: #f8fafc;
      border-bottom: 2px solid #e2e8f0;
      font-size: clamp(8px, 0.6vw, 11px); color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap;
    }}
    .matrix-table td {{
      padding: clamp(5px, 0.5vw, 10px) clamp(8px, 0.8vw, 16px);
      border-bottom: 1px solid #f1f5f9;
      max-width: clamp(80px, 10vw, 180px);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .matrix-table tbody tr:hover {{ background: #f0fdfa; }}
    .cid-cell {{
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(9px, 0.65vw, 12px); color: #06b6d4; font-weight: 500;
    }}
    .run-id-cell {{
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(9px, 0.65vw, 12px); color: #0f766e; font-weight: 500;
    }}
    .path-cell {{
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(8px, 0.6vw, 11px); color: var(--muted);
      max-width: clamp(200px, 22vw, 400px);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .prop-cell {{ color: var(--ink); }}
    .sig-cell {{ color: var(--muted); font-size: clamp(8px, 0.6vw, 12px); }}
    .rtl-loc-cell {{
      color: #0369a1;
      font-family: "SFMono-Regular",Consolas,monospace;
      font-size: clamp(8px, 0.6vw, 12px);
      font-weight: 600;
    }}
    .cell-found {{
      background: #ecfdf5; color: #059669; font-weight: 600; text-align: center;
      font-size: clamp(11px, 0.85vw, 16px);
      white-space: nowrap;
    }}
    .cell-miss {{ text-align: center; color: #d1d5db; }}
    .cell-miss::after {{ content: "—"; }}

    .muted {{ color: var(--muted); }}
    .mini-link {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
      color: #0369a1;
      font-weight: 700;
      background: rgba(255,255,255,0.82);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 8px 12px;
      white-space: nowrap;
    }}
    .mini-link:hover {{
      border-color: rgba(14,165,233,0.32);
      background: rgba(240,249,255,0.95);
    }}

    @media (max-width: 600px) {{
      .page {{ padding: 8px; }}
      .donut-card {{ flex-direction: column; text-align: center; }}
      .donut-row {{ grid-template-columns: 1fr; }}
      .stat-grid {{ grid-template-columns: repeat(3, 1fr); }}
      .bar-info {{ width: 60px; }}
      .bar-val {{ width: 40px; }}
    }}
    /* Language Switcher & Dual i18n display */
    body.lang-zh .i18n-en {{ display: none !important; }}
    body.lang-en .i18n-zh {{ display: none !important; }}
    .lang-switch {{
      display: inline-flex; gap: 4px; background: #e2e8f0; padding: 2px;
      border-radius: 6px; vertical-align: middle;
    }}
    .lang-btn {{
      border: none; background: transparent; padding: 3px 10px;
      border-radius: 4px; font-size: 12px; cursor: pointer; color: #64748b;
      font-weight: 500; transition: all 0.2s;
    }}
    .lang-btn.active {{
      background: #ffffff; color: #0284c7; font-weight: 700;
      box-shadow: 0 1px 2px rgba(0,0,0,0.08);
    }}
    {extra_css}
  </style>
<body class="{body_class}">
  <div class="page">
    <section class="hero">
      {lang_switch}
      <h1>{hero_title}{dut_badge}</h1>
      <p>{hero_desc}</p>
      {revision_html}
    </section>

    <section class="stat-grid">
      <div class='stat-card' title='{stats_models_title}'><span class='label'>{stat_models}</span><span class='value'>{n_models}</span><span class='hint'>{model_list}</span></div>
      <div class='stat-card' title='{stats_canonical_title}'><span class='label'>{stat_canonical}</span><span class='value'>{primary_bug_total}</span><span class='hint'>{stat_canonical_desc}</span></div>
      <div class='stat-card' title='{stats_shared_title}'><span class='label'>{stat_shared}</span><span class='value'>{shared}</span><span class='hint'>{shared_pct:.0f}%{shared_rate_label}</span></div>
      <div class='stat-card' title='{stats_unique_title}'><span class='label'>{stat_unique}</span><span class='value'>{unique}</span><span class='hint'>{exclusive_breakdown}</span></div>
      <div class='stat-card' title='{stats_llm_title}'><span class='label'>{stat_llm}</span><span class='value'>{semantic}</span><span class='hint'>{stat_llm_desc}</span></div>
      <div class='stat-card' title='{stats_audit_title}'><span class='label'>{stat_audit}</span><span class='value'>{audit}</span><span class='hint'>{stat_audit_desc}</span></div>
    </section>

    {empty_dut_html}

    {model_sources_html}

    {coverage_metrics_section}

    {tag_detail_section}

    <!-- ═══ PRIMARY: RTL Root Score (GT Defect Details) ═══ -->
    {root_score_section}

    <!-- ═══ AUXILIARY: Symptom-level detail ═══ -->
    {symptom_score_section}

    <section class="section" id="symptom-matrix">
      <div class="section-header">
        <div><h2>{matrix_title}</h2><p>{matrix_desc}</p></div>
        <div style="display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end;"><a class="mini-link" href="bug_evidence_details.html">{matrix_details_link}</a><a class="mini-link" href="rtl_manual_audit_queue.html">{manual_audit_label}</a></div>
      </div>
      <div class="matrix-wrap">
        <table class="matrix-table">
          <thead><tr>
            <th>{matrix_th_bug}</th><th>{matrix_th_property}</th><th>{matrix_th_signals}</th><th>{matrix_th_rtl_loc}</th>
            {matrix_headers}
          </tr></thead>
          <tbody>{compact_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <div><h2>{chain_title}</h2><p>{chain_desc}</p></div>
      </div>
      {chain_html}
    </section>

    <section class="section">
      <div class="section-header">
        <div><h2>{evidence_title}</h2><p>{evidence_desc}</p></div>
      </div>
      <div class="donut-row">{donuts}</div>
    </section>

    <section class="section">
      <div class="section-header">
        <div><h2>{overlap_title}</h2><p>{overlap_desc}</p></div>
      </div>
      <div class="donut-row">{model_overlap_cards}</div>
    </section>

    <!-- ═══ REVIEW: Diagnostics + Audit + Config ═══ -->
    {diagnostics_html}

    <section class="section" id="cross-model-audit">
      <div class="section-header">
        <div><h2>{audit_inline_title}</h2><p>{audit_inline_desc}</p></div>
        <div style="display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end;">
          <a class="mini-link" href="cross_model_non_merge_audit.html">{audit_view_full}</a>
          <a class="mini-link" href="cross_model_semantic_review.html">{review_queue_label}</a>
        </div>
      </div>
      <div class="audit-rel">{audit_relation_html}</div>
      <div class="audit-rel">{audit_pair_html}</div>
      <div class="audit-wrap audit-wrap-full">
        <table class="audit-table">
          <thead><tr>
            <th>{audit_th_pair_id}</th><th>{audit_th_left_model}</th><th>{audit_th_left_cand}</th><th>{audit_th_right_model}</th><th>{audit_th_right_cand}</th>
            <th>{audit_th_rel}</th><th>{audit_th_blocking}</th><th>{audit_th_score}</th>
          </tr></thead>
          <tbody>{audit_tbl}</tbody>
        </table>
      </div>
    </section>

    {semantic_config_html}
  </div>
  <script>
  function toggleSubmoduleDrawer(rowId) {{
    var row = document.getElementById(rowId);
    var arrow = document.getElementById('arrow-' + rowId);
    if (!row) return;
    if (row.style.display === 'none' || row.style.display === '') {{
      row.style.display = 'table-row';
      if (arrow) arrow.textContent = '▼';
    }} else {{
      row.style.display = 'none';
      if (arrow) arrow.textContent = '▶';
    }}
  }}
  </script>
  {modal_js}
</body>
</html>
""".format(
        extra_css=_COV_DRAWER_CSS + _GT_DETAIL_EXTRA_CSS,
        modal_js=_build_modal_html_and_js(registry),
        lang_code="zh-CN" if lang == "zh" else "en",
        body_class="lang-" + lang,
        lang_switch=_lang_switch_html(lang),
        page_title=_t("page_title_benchmark", lang),
        hero_title=_t("bench_title", lang),
        hero_desc=_t("bench_hero_desc", lang),
        dut_badge=dut_badge_html,
        revision_html=revision_html,
        # stats
        stats_models_title=stats_model_title.get(lang, stats_model_title["zh"]),
        stats_canonical_title=stats_canonical_title.get(lang, stats_canonical_title["zh"]),
        stats_shared_title=stats_shared_title.get(lang, stats_shared_title["zh"]),
        stats_unique_title=stats_unique_title.get(lang, stats_unique_title["zh"]),
        stats_llm_title=stats_llm_title.get(lang, stats_llm_title["zh"]),
        stats_audit_title=stats_audit_title.get(lang, stats_audit_title["zh"]),
        stat_models=_t("stat_models", lang),
        stat_canonical=primary_stat_label,
        stat_canonical_desc=primary_stat_desc,
        stat_shared=_t("stat_multi_model", lang),
        stat_unique=_t("stat_single_model", lang),
        stat_llm=_t("stat_llm_pairs", lang),
        stat_llm_desc=_t("stat_llm_pairs_desc", lang),
        stat_audit=_t("stat_audit", lang),
        stat_audit_desc=_t("stat_audit_desc", lang).format(audit_pct=audit_pct),
        shared_rate_label=" 共享率" if lang == "zh" else " shared",
        n_models=(
            "{}/{}".format(
                sum(1 for item in (data.get("model_sources", []) or []) if isinstance(item, dict) and item.get("included") is True),
                len(model_names),
            )
            if any(isinstance(item, dict) and item.get("included") is False for item in (data.get("model_sources", []) or []))
            else len(model_names)
        ), total_bugs=total_bugs, primary_bug_total=primary_bug_total,
        shared=primary_shared_count, shared_pct=stat_shared_pct,
        unique=primary_unique_count,
        semantic=semantic_total, audit=audit_total, audit_pct=audit_pct,
        model_list=model_list,
        exclusive_breakdown=stat_exclusive_breakdown,
        empty_dut_html=empty_dut_html,
        model_sources_html=model_sources_html,
        # primary: RTL root score
        root_score_section=root_score_section,
        coverage_metrics_section=coverage_metrics_section,
        tag_detail_section=tag_detail_section,
        # auxiliary: symptom score
        symptom_score_section=symptom_score_section,
        diagnostics_html=_diagnostics_section_html(data, lang),
        semantic_config_html=semantic_config_html,
        # overlap
        overlap_title=_t("overlap_title", lang),
        overlap_desc=_t("overlap_desc", lang),
        model_overlap_cards=overlap_cards,
        # evidence donuts
        evidence_title=_t("evidence_title", lang),
        evidence_desc=_t("evidence_desc", lang),
        donuts=donut_html,
        # chain
        chain_title=_t("chain_title", lang),
        chain_desc=_t("chain_desc", lang).format(replay_chain_note=esc(replay_chain_note)),
        chain_html=chain_html,
        root_matrix_title=_t("root_matrix_title", lang),
        root_matrix_desc=_t("root_matrix_desc", lang),
        root_matrix_html=root_matrix_html,
        # matrix
        matrix_title=_t("matrix_title", lang),
        matrix_desc=_t("matrix_desc", lang),
        matrix_details_link=_t("matrix_details_link", lang),
        manual_audit_label="人工审计" if lang == "zh" else "Manual Audit",
        matrix_th_bug=_t("matrix_th_bug", lang),
        matrix_th_property=_t("matrix_th_property", lang),
        matrix_th_signals=_t("matrix_th_signals", lang),
        matrix_th_rtl_loc=_t("matrix_th_rtl_loc", lang),
        matrix_headers="".join("<th>{}</th>".format(esc(m)) for m in model_names),
        compact_rows=compact_rows,
        # audit
        audit_inline_title=_t("audit_inline_title", lang),
        audit_inline_desc=_t("audit_inline_desc", lang).format(
            semantic=semantic_total, audit=audit_total, audit_display_note=esc(audit_display_note)),
        audit_view_full=_t("audit_view_full", lang),
        review_queue_label=_t("review_queue_label", lang),
        audit_relation_html=audit_relation_html, audit_pair_html=audit_pair_html or "—", audit_tbl=audit_rows,
        audit_th_pair_id=_t("audit_th_pair_id", lang),
        audit_th_left_model=_t("audit_th_left_model", lang),
        audit_th_left_cand=_t("audit_th_left_candidate", lang),
        audit_th_right_model=_t("audit_th_right_model", lang),
        audit_th_right_cand=_t("audit_th_right_candidate", lang),
        audit_th_rel=_t("audit_th_relation", lang),
        audit_th_blocking=_t("audit_th_blocking", lang),
        audit_th_score=_t("audit_th_score", lang),
    )


def model_score_summary_html(data: Dict[str, object], lang: str = "zh") -> str:
    """Generate the model score summary HTML page."""
    summary = data.get("model_score_summary", {})
    semantic_pair_parts = _semantic_pair_config_summary(data)

    def esc(value: object) -> str:
        if value is None:
            return ""
        return html.escape(str(value))

    policy_empty = _t("summary_policy_empty", lang)
    policy_rows = "".join(
        f"<li><code>{esc(key)}</code>: <strong>{esc(value)}</strong></li>"
        for key, value in summary.get("policy", {}).items()
    ) or f"<li class='muted'>{policy_empty}</li>"

    ranking_empty = _t("summary_empty", lang)
    ranking_cards = "".join(
        (
            "<article class='score-card'>"
            f"<h3>{esc(item.get('model'))}</h3>"
            f"<div class='score'>{esc(item.get('total_score'))}/{esc(item.get('max_score'))}</div>"
            f"<p>{_t('summary_normalized', lang)}={esc(item.get('normalized_score'))}  {_t('summary_found', lang)}={esc(item.get('found_count'))}</p>"
            f"<p>{_t('summary_rating', lang)}={esc(item.get('tier_counts', {}))}</p>"
            f"<p>{_t('summary_basis', lang)}={esc(item.get('score_reason_counts', {}))}</p>"
            "</article>"
        )
        for item in summary.get("ranking", [])
    ) or f"<div class='empty'>{ranking_empty}</div>"

    semantic_pair_html = ""
    if semantic_pair_parts:
        semantic_pair_html = (
            "<section class='policy'>"
            "<h2>{title}</h2>"
            "<ul>{items}</ul>"
            "</section>"
        ).format(
            title=_t("summary_semantic_pairs", lang),
            items="".join(
                f"<li><code>{esc(part.split('=', 1)[0])}</code>: <strong>{esc(part.split('=', 1)[1])}</strong></li>"
                for part in semantic_pair_parts
            ),
        )

    lang_code = "zh-CN" if lang == "zh" else "en"
    return f"""<!DOCTYPE html>
<html lang="{lang_code}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_t('summary_page_title', lang)}</title>
  <style>
    :root {{
      --bg: #faf8f5;
      --panel: #fffefb;
      --ink: #1d1b18;
      --muted: #78716c;
      --line: #e7dfd3;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      font-family: "PingFang SC","Noto Sans SC",-apple-system,"Segoe UI",sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    .page {{ max-width: 1100px; margin: 0 auto; padding: 28px; }}
    .hero, .policy, .score-card, .empty {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      box-shadow: 0 6px 20px rgba(29,27,24,0.04);
    }}
    .hero, .policy {{ padding: 20px; margin-bottom: 20px; }}
    .hero p, .policy p {{ color: var(--muted); }}
    .dut-badge {{
      float: right; padding: 0.15em 0.6em;
      background: #e0f2fe; color: #0369a1; border-radius: 999px;
      font-size: inherit; font-weight: 700;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }}
    .score-card {{ padding: 18px; }}
    .score-card h3 {{ margin: 0 0 8px; }}
    .score-card p {{ margin: 8px 0 0; color: var(--muted); font-size: 14px; }}
    .score {{
      font-size: 30px;
      font-weight: 700;
      color: var(--accent);
    }}
    ul {{ margin: 10px 0 0; padding-left: 20px; }}
    .empty {{ padding: 18px; color: var(--muted); }}
    code {{ font-family: "SFMono-Regular",Consolas,monospace; font-size: 13px; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{_t('summary_page_title', lang)}</h1>
      <p>{_t('summary_policy_version', lang)}: {esc(summary.get('policy_version') or '?')}</p>
    </section>
    {semantic_pair_html}
    <section class="policy">
      <h2>{_t('summary_scoring_policy', lang)}</h2>
      <ul>{policy_rows}</ul>
    </section>
    <section class="cards">
      {ranking_cards}
    </section>
  </div>
</body>
</html>
"""
