
# ACT4SwitchCapabilityChecker

实现：`act4_privileged_suite/checkers/act4_switch_capability_checker.py`

## 作用

该 checker 贯穿阶段 01、03、04、05，验证 `{DUT}_switch_capability_audit.yaml`。它防止
把 suite opt-in 当成 DUT 能力、把参考模型存在当成 coverage 可用，或为了启用一个宏
修改受保护框架。

## 主要输入与输出

- 输入：audit YAML、expected suite、baseline manifest、必需 capability 名称，以及是否
  验证 audited source path。
- 输出：control 数量、verified_source_paths 和 findings，并校验声明的分类摘要。
  可选 output_dir 写 switch-capability-audit.json；本工作流未配置。
- 它不执行被审计命令；命令结果必须作为 audit evidence 由工作流事先记录。

## 代码实现原理

1. 验证顶层 schema、suite、ACT4 Git HEAD、audited sources、required capabilities、
   controls 和 decision summary。
2. 对每个 control 校验 class、defined_by、owner 对应关系、effective state、native
   entrypoint、permitted action、baseline edit、decision、evidence、affected profiles、
   limitations 和 blocked reason。
3. 强制关键不变量：`allowed` 需要原生入口且不要求 baseline edit；limited/blocked 必须
   说明限制或原因；DUT capability 允许 udb、dut_config、framework 三种 owner。framework
   可以记录 undef/guard 的最终处理，不表示 suite 可以定义能力事实。
4. 若配置要求，检查 file 型 audited source 无 glob，对识别到的工作区路径检查存在性，并与 manifest
   baseline Git HEAD 建立一致性。
5. 重算 decision summary，检查 allowed、limited 和 blocked 名单没有漏项或虚假项。

## 当前局限

- checker 验证“审计记录自洽”，不解析任意源码的完整预处理顺序，也不证明宏在编译时
  一定达到记录的 effective state。
- command/tool_result evidence 是文本记录；checker 不重放命令或验证外部工具版本输出
  的真实性。
- 文件存在不代表引用的行号或自然语言证据足以支持结论，仍需 reviewer 抽查源码。
- owner/class 规则覆盖当前工作流定义的控制类型；ACT4 新增入口时需同步扩充枚举和规则。
- `framework_blocked` 表示特定 consumer 的入口缺口，checker 本身无法防止作者在 contract
  中把影响范围写得过粗，需和 VM contract、AI review 联合检查。

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_switch_capability_checker.py`。

## 实现定位与实际检查范围

`_validate_control()` 执行 owner/decision 不变量；`_validate_required_capabilities()`
检查 required_by/evidence 及配置指定的能力名；`_validate_audited_sources()` 验证证据结构。
`do_check()` 对照 decision_summary 与 baseline 中声明的 HEAD，不查询实际 Git HEAD。

路径存在性只识别以 `riscv-arch-test/` 或 `unity_test/` 开头的部分文本，
即使 verify_audited_source_paths=true，也不代表所有绝对路径、其他前缀或行号都验证过。
当前 03/04/05 要求 reference_model_executable、signature_self_checking_execution、
sail_rvvi_coverage_backend 三项 capability；01 没有该固定名称列表。

`framework_blocked` 且如实填 none action、affected_profiles、blocked_reason 可通过 audit gate。
checker 不扫描 generator 或预处理输出来证明实际动作都遵守审计；消费者范围和四项替代
分析继续在 [VM contract](../act4_template/privileged_vm_resource_template.md) 中落实。
