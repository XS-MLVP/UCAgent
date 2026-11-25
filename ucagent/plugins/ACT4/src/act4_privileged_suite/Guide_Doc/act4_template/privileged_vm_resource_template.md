<!-- SPDX-License-Identifier: Apache-2.0 -->

# ACT4 Privileged VM / Resource Contract 模板

适用阶段：03_vm_resources，供 generator 和 build 复核。
输出 `{OUT}/{DUT}/{DUT}_vm_resource_contract.yaml`，并维护 switch audit 和
`experimental/{DUT}_experimental_assets.yaml`。本模板按 consumer 填写资源，不能按
扩展名自动开启页表。使用约定见 [README](README.md)。

## 1. 目标与 profile 骨架

以下 YAML 展示字段，示例使用待确认 RV64 的 host Bare profile。`experimental` 表示
该示例尚无正式运行证据；真实 profile 的决定须重新评估，不能照抄默认值。

```yaml
schema_version: 1
suite: "{DUT}"
supported_xlens: [64]
selected_target:
  name: "待填写已选择 target"
  test_config: "riscv-arch-test/待填写/test_config.yaml"
  udb_config: "riscv-arch-test/待填写 UDB 路径"
  XLEN: 64
decision: scoped_profiles
profiles:
  - profile_id: host_operation_positive
    coverage_targets: [cp_operation_context]
    decision: experimental
    resource_mode: bare_or_csr_only
    execution_context: host_execution
    requires_page_tables: false
    XLEN: 64
    required_extensions:
      names: []  # 填入实际 ISA 依赖
      evidence: []  # 填入配置/规范证据
    capability_dependencies: []  # 填入所消费 capability，不能漏掉直接依赖
    address_symbols: []
    address_domains: {satp: Bare, vsatp: Bare, hgatp: Bare}
    privilege_entry: "待填写已审计进入与返回流程"
    expected_result: "待填写实际操作与可判定结果"
    unresolved_resources: ["待填写尚未证实的能力或资源"]
    blocked_reason: null
```

`selected_target` 是当前接口，不使用 `target` 别名。
`execution_context` 取 `host_execution`、`explicit_guest_memory_access` 或
`guest_execution`，与 `resource_mode` 是不同维度。无页表需求可使用显式 `decision: no_vm`；
仍建议按行为维护 profile，以保留模式进入、异常和生成范围的可追踪性。

## 2. 按资源模式增加字段

| resource_mode | requires_page_tables | translation 必需分支 | 主要控制 |
| --- | --- | --- | --- |
| bare_or_csr_only | false | 不创建虚假页表分支 | Bare / 未使用 |
| single_stage | true | s_stage | satp、sfence.vma |
| g_stage_only | true | g_stage | hgatp、G-stage fence |
| two_stage | true | vs_stage、g_stage | vsatp/hgatp、各自 fence |

所有使用页表的 profile 还需 `translation.activation_order`、
`translation.bare_restore_order`。每个实际 stage 分别填写：

| 字段/描述 | 必须回答的问题 |
| --- | --- |
| mode、levels | CTP/manual 是否需要且目标是否支持该模式和层数？ |
| root_alignment、address_symbols | root/child 页来自哪些链接符号，如何保证模式要求的对齐？ |
| address_domains | GVA/GPA/PA 分别是什么？identity 时是否显式 GPA=PA？ |
| canonical_va、vpn_indices | 地址是否合法，各级 index 如何计算？ |
| page_selection、pte_policy | 页大小、PPN、R/W/X/U/A/D、保留位符合哪条规范？ |
| activation_order | 何种模式下构表，何时写 CSR、fence、进入被测上下文？ |
| bare_restore_order | 正常/异常两条路径如何恢复翻译、CSR、特权级和 signature 指针？ |

G-stage 映射 VS page-walk 页与 payload。只有实际执行 guest code 时才增加其 code、
trap vector/stack 等直接资源；host signature 不应被无理由要求映射进 guest。
PPN 从链接符号计算，不把本次 ELF 地址抄成平台常数。

## 3. capability 与局部 blocker

每项依赖记录 capability、consumer、required_for、源码/配置证据和影响范围。
switch audit 的 `required_capabilities` 关联 required_by，controls 的 affected_profiles
列出消费者；contract 描述这些消费者具体需要什么资源。

仅在直接执行依赖无法实现时，给对应 profile 填 `decision: blocked`，并追加：

```yaml
blocked_reason: "待填写此子场景无法实现的直接原因"
blocking_dependencies:
  - capability: "待填写缺失服务"
    required_for: ["待填写具体操作或异常子场景"]
    evidence: ["待填写精确源码或失败证据"]
    reason: "待填写为何是直接依赖"
    upstream_action: "待填写独立上游所需动作"
alternative_analysis:
  evaluated:
    - suite_local_resources
    - positive_subset
    - native_entrypoint
    - generation_vs_validation_scope
  conclusion: "逐项解释为何不可行，以及为什么只影响本 profile"
```

该片段是 blocked 决策完成后的结构，不是预填结论。覆盖后端或参考模型缺失通常只降低
验证置信度；能静态生成的候选保留到实验目录。正式流程已能运行的正向子集继续保留。

## 4. coverage disposition

顶层 `coverage_disposition` 逐个主 target 记录：

```yaml
coverage_disposition:
  - target: cp_operation_context
    planned_status: partial
    generated_profiles: [host_operation_positive]
    blocked_profiles: [host_operation_fault]
    blocked_subcases: ["待填写直接依赖不可用服务的 fault 子场景"]
```

该示例仅用于同一 target 已有 allowed 正向 profile 且 fault profile 确认 blocked 的情况；
不能直接与上面的 experimental 骨架拼接。纯 allowed 为 required，全部适用正式 profile
blocked 才为 blocked。实验资产不进入主流程生成集合。目标有 allowed 与 blocked 两种
profile 时是 partial，不能把整个 target 删除。

## 5. 实验清单与交接

没有实验项时也创建：

```yaml
schema_version: 1
suite: "{DUT}"
assets: []
```

存在实验项时，每项含 `id/path/kind/validation_status/limitations/promotion_requirements/
affected_targets`。path 相对实验清单目录且不能越界，必须指向已存在文件；kind 可为
generator_fragment、assembly_candidate、auxiliary_config、coverage_candidate 或 analysis。
运行未确认可用 runtime_blocked，覆盖未确认用 coverage_blocked；不要伪造 ELF/signature。

阶段 03 直接执行 SwitchCapability 和 AIReview，VM contract 的结构/集合还将在
04 Asset 与 05/06 TestAsset 中继续检查。当前 checker 不模拟页表遍历或验证每条恢复路径，
因此后续必须结合生成 .S、nm/readelf/objdump 和实际参考模型日志审查。
