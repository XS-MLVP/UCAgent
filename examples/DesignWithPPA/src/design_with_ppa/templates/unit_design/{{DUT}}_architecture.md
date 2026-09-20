
# {{DUT}} 架构设计

先依据全部 Spec 修订机器合同，不能把模板默认值当作需求。同步 reset 使用
`sample_edge: posedge|negedge`；异步 reset 使用
`assertion_edge: posedge|negedge` 和非空 `deassertion` 策略。

## 机器合同

```yaml
architecture:
  schema_version: "1.0"
  top_module: {{DUT}}
  parameters: []
  ports:
    - name: input_i
      direction: input
      width: 1
      signed: false
      role: replace-from-spec
    - name: output_o
      direction: output
      width: 1
      signed: false
      role: replace-from-spec
  design_intent: combinational
  clock_reset:
    clocks: []
    resets: []
    rationale: Replace from Spec.
  timing:
    transaction_accept: Replace from Spec.
    response: Replace from Spec.
    handshake: Replace from Spec; use none when no handshake exists.
    latency_cycles: 0
    backpressure: Replace from Spec.
  illegal_inputs:
    policy: Replace from Spec.
  multi_clock_cdc:
    clock_domains: 0
    policy: Replace from Spec.
  synthesis_constraints:
    synthesizable_only: true
    no_latch: true
    no_unknown_outputs: true
    no_initial_delay: true
    forbidden_constructs: [delay, force, release, simulation-system-task]
  acceptance_criteria:
    - Replace with a measurable requirement.
```

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
