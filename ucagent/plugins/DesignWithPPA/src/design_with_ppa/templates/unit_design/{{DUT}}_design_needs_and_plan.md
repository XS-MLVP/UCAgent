
# {{DUT}} 设计需求与计划

## 输入基线

- README: `{{DUT}}/README.md`
- Specs: `{{DUT}}/spec/**/*.md`

## 功能范围

待依据全部输入文档填写。

## 验证与交付要求

记录 API、fixture、用例数量、coverage、性能报告等流程要求；这些内容不创建普通功能 CK。

## TDD 顺序

1. 稳定 architecture 与 FG/FC/CK。
2. Python executable spec 和统一 UT 全部通过。
3. {{RTL_LANGUAGE}} 源码通过 Check/Complete 运行同一套 UT。
4. 建立性能合同、波形和 base PPA。
5. 按 Pareto 接受门禁（保护类别内指标不得回退，至少一项指标改善）迭代并交付最后 accepted RTL。

## Final RTL synchronization

```yaml
rtl_synchronization:
  schema_version: "1.0"
  status: pending-final-rtl-sync
  rtl_language: {{RTL_LANGUAGE_ID}}
  top_module: {{DUT}}
  source_files: []
  rtl_source_sha256: replace-from-final-check
  all_test_cases_passed: false
  test_case_count: 0
  test_source_sha256: replace-from-final-check
  toffee_report_sha256: replace-from-final-check
```
