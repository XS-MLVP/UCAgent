
# ACT4CTPReferenceChecker

实现：`act4_privileged_suite/checkers/act4_ctp_reference_checker.py`

## 作用

该 checker 是阶段 01 的 CTP/source-boundary gate。它确认冻结的 CTP 页面确实包含当前
suite 的唯一表格和 Google Sheet tab，原始 Sheet 的每个非空 cell 已被分类，并且优化
CSV、人类 testplan、normative table 与 provenance 没有集合漂移。

它重点防止：硬编码错误 Sheet、把登录 HTML 当 CSV、遗漏原始请求、用 `row12_*` 等
位置 ID 替代语义 ID、机器 CSV 与人类文档不一致，以及使用 metadata 中不存在的 rule。

## 主要输入与输出

- 输入：suite、CTP HTML snapshot、CTP provenance、raw CSV、规范化 CSV、人类 Markdown
  testplan、normative rule table 和 normative metadata。
- 可选严格项：`require_request_regions`、`require_full_boundary_review`。
- 输出：error/warning 计数、CTP table/Sheet、source item、testplan 和 rule 集合的结构化结果。
  该 checker 本身不落盘 checker JSON。

## 代码实现原理

1. 使用标准库 `HTMLParser` 读取 table 的 id、caption、表头和链接，要求精确匹配
   `t-{suite}-coverpoints` / `{suite} Coverpoints`，再用 URL parser 提取 Google Sheet
   spreadsheet id 和唯一数字 gid。
2. 使用 `csv` 读取 raw matrix，结合 provenance 中的 request/non-request regions 建立
   cell 级分类；用集合和计数器检查重复、遗漏、越界和语义 source item 声明。
3. 解析规范化 CSV 的固定列，要求 JSON array 字段可解析、source item 恰好消费一次，
   并把 rule 名与 metadata 的 `normative_rule_definitions` 对照。
4. 按 Markdown 标题和表格结构抽取人类 testplan，比较 coverpoint、source request 和
   normative rule 投影。
5. 对 snapshot、raw/optimized/testplan 文件重新计算 SHA-256，与 provenance 声明比较。

## 当前局限

- 它验证冻结 snapshot，不访问网络，也不能证明 snapshot 在检查时仍是上游最新版本。
- HTML parser 针对当前 CTP 表格结构；上游 DOM/caption/Google URL 形式改变时可能需要
  更新解析规则。
- cell 分类和集合闭合不能证明“请求语义被正确理解”，尤其无法判断自然语言合并/拆分
  是否合理，仍需 reviewer 阅读原 Sheet 与 testplan。
- Markdown 检查关注稳定标题、表格和集合，不做完整自然语言语义等价分析。
- SHA-256 证明内容未漂移，不证明来源本身正确或可信。

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_ctp_reference_checker.py`。修改 table 解析、
source boundary 或 Markdown contract 时应同步扩充 fixture。

## 实现定位与判定示例

`_CTPTableParser` / `_google_sheet_parts()` 处理 snapshot；
`_request_region_cells()`、`_declared_source_items()` 处理矩阵边界；
`_optimized_source_contract()`、`_human_testplan_contract()`、
`_normative_table()` 校验派生文件。01 同时开启 require_request_regions 和
require_full_boundary_review。

请求 ID 为 row6_x 会被拒绝；共享标题被多个 source items 引用则合法。
source item 必须在优化 CSV 恰好消费一次，一对多 SV target 展开放到 mapping。
`ctp.fetched_at` 仅要求有值；本地 snapshot、URL 和 hash 一致并不能认证真实下载时间。
按[coverage 模板](../act4_template/privileged_coverpoints_template.md)填六个功能字段，
自然语言摘要与原始请求的语义仍需要审查。
