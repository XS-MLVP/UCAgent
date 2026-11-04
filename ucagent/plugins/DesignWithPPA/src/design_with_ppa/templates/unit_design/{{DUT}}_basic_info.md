
# {{DUT}} 基本信息

## 设计职责

待从 README 和 Spec 提取。

## 输入输出

待与 architecture 机器合同同步填写。

## 时序与协议

待明确 transaction、clock/reset、latency 和 backpressure。

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
