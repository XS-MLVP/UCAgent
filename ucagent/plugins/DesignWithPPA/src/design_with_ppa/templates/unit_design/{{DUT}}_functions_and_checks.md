
# {{DUT}} 功能与检测点

## 待细化功能组

<FG-DESIGN>

### 待细化功能

<FC-BEHAVIOR>

#### 待细化检测点

<CK-EXPECTED>

根据 Spec 替换本检测点，并为每个可由 DUT 公共接口观测的独立行为、边界、reset、时序和非法输入增加精确 CK。测试框架、用例数量、coverage 和报告流程写入设计计划，不创建功能 CK。

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
