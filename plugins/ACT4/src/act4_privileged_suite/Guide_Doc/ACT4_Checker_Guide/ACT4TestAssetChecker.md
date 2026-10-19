
# ACT4TestAssetChecker

实现：`act4_privileged_suite/checkers/act4_test_asset_checker.py`

## 作用

该 checker 在阶段 05 验证生成/构建结果，在阶段 06 验证 contribution readiness。它检查
每个生成 `.S` 是否具有同 stem 的最终 ELF、signature、results 和完整参考模型日志，并
把这些证据与 XLEN、VM contract、generation scope、experimental manifest、首选模型及
fallback 记录对齐。

## 主要输入与输出

- 输入：source/ELF/signature/results/log 的显式路径或 glob，source markers、禁止占位符、
  validation state、VM contract、experimental manifest 和多项 `require_*` gate。
- 可从冻结 ACT4 `constants.py` 读取 privileged testcase 分文件上限。
- `check_testcase_reachability=true` 时，检查 `.S` 中 testcase 描述符与入口标签的关联，
  并用只读 `nm` 统计所选 ELF 中实际保留的测试标签；`nm_executable` 可指定工具路径。
- `output_dir` 启用时写 `test-assets.json`；输出包括 artifact 计数、stem、完整运行数、
  signature progress、XLEN evidence、generation scope、contribution state 和
  `testcase_reachability`。

## 代码实现原理

1. 枚举配置的文件，读取 `.S` header/marker/testcase descriptor，拒绝空文件和占位符。
   超过派生 ACT4 分文件阈值时记 warning，审查是否存在不可拆分 chunk；显式配置的
   `max_testcases_per_source` 硬性上限仍可报错。
2. 读取 ELF identification 的 class 得到 RV32/RV64，结合源码 MARCH 模板、VM contract
   target XLEN 和同 stem ELF 建立 XLEN 证据。
3. 从 validation state 的 `self_checking.command` 读取 `CONFIG_FILES`、`WORKDIR`，结合
   test_config 的 `name` 将 ELF/signature/results/log 限定在同一构建目录，再按 stem 与
   source 匹配。配置了 validation state 且要求日志、区间完整性或 progress 检查时，
   选择信息缺失或无法解析会报错，不回退到其他配置的历史产物；独立显式路径模式仍可用。
4. 在日志中要求对应 `RVCP-SUMMARY: TEST SIGRUN`、恰好一个终态 `SUCCESS`、无常见异常
   终止标记，并读取 begin/end 地址。signature granularity 优先来自日志；当前 ACT4
   原生签名命令按 XLEN/8 传参，新版模型未回显粒度时，可使用同一构建下匹配最终 ELF
   的 EI_CLASS。缺少日志粒度且无唯一匹配 ELF，或日志与 ELF 宽度冲突时仍报错，
   禁止从记录数反推粒度。
5. 启用区间完整性检查时，根据 signature 区间计算应有 record 数，与 `.sig` 非空行和
   `.results` 的 `.word/.quad` 操作数对照。signature 每条记录必须为十六进制值，长度
   不超过 granularity 对应位数，允许省略前导零；results 必须为整数数据记录，允许
   标签、空白、注释、逗号分隔操作数和 `.word/.quad` 混用，不强制按 XLEN 选择指令。
   不比较两个文件的数值；可用 sentinel 做最低 testcase progress 诊断。
6. 验证 validation state 的 self-checking、Sail coverage、contribution_ready、generation
   scope；coverage 与 signature 允许使用独立配置/模型，分别审查证据。
   验证首选模型尝试、failure diagnosis、fallback 不缩减范围；再与 VM contract
   和 experimental disposition 做集合比较。
   同一 attempt 内同一 target 的 diagnosis outcome 不得冲突；不同 attempt 可体现修复
   和后续失败，按记录顺序使用该目标最近的 diagnosis outcome 做最终范围一致性检查。
7. 从实际 `CONFIG_FILES` 解析 `ref_model_exe`，对照声明的模型、可执行文件和配置路径。
8. 若启用了 testcase reachability，保守解释完整的 `#if/#elif/#else/#endif` 条件：只有在
   RV32、RV64 两种 XLEN 下都能证明入口不可达时才产生 `testcase_guard_unsatisfiable` error。
   正常 XLEN/能力排除、未知宏、复杂表达式、缺失符号表和无法关联的描述符只产生
   warning 或 `unverified`，不会被当作生成错误。

`testcase_reachability` 报告至少区分 `source_descriptors`、`impossible_testcases`、每个
ELF 的 `compiled_testcases`、`excluded_labels` 和 `compiled_counts_complete`。已编译标签
不是执行命中，也不是功能覆盖率；最终报告必须把它与 `.sig.log`、DUT 执行和 coverage
backend 证据分开描述。

## 当前局限

- checker 明确是事后静态验证器，不编译也不启动参考模型；它信任已留下的文件，只检查
  文件结构和跨文件一致性。
- 日志关键词和 record 数提供运行链完整性的格式证据，但不能独立证明每个 testcase 的架构断言都
  设计正确。当前 signature 格式缺少精确 testcase-to-slot 元数据，progress 只是启发式。
- ELF class 只能证明位宽，不能完整证明所有链接选项、ISA 扩展或平台配置正确。
- `.sig` 与 `.results` 等长不代表值在真实 DUT 上正确；results 本身来自参考模型流程。
- `SUCCESS` 检查无法替代 simulator exit status 的原始执行记录，也无法识别所有可能的
  模型异常文本。
- Sail self-checking 通过不等于 RVVI/UCDB/VDB coverage 通过，checker 通过单独字段保持
  这两个结论分离。

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_test_asset_checker.py`。

## 当前配置与实现定位

05/06 启用 signature/results/log、区间完整性、XLEN、模型评价、scoped VM、
generation_scope 和实验清单检查，signature_progress_mode=warning。
06 追加 require_contribution_ready=true；05 配置 output_dir，06 没有配置新报告路径。
因此 05 落盘 JSON 不应自动称为 06 最新复查结果，后者使用实际 Check/Complete 返回值。

核心分别在 `_check_reference_model_outputs()`、`_check_signature_progress()`、
`_check_reference_model_identity()`、`_check_reference_model_evaluation()`、
`_check_vm_contract()` 和 `_check_experimental_manifest()`。

还需注意：
- 选定构建目录隔离了其他配置的历史产物，但 stem 匹配不证明同一目录内重复 stem 的
  唯一性或构建时效性；日志也没有完整的双向多余项检查。
- `reference_runs_checked` 是找到匹配日志并进入检查的计数；`complete_reference_runs`
  只统计同时具备 signature/results、通过日志和区间格式检查且无 error 的链路。
  未启用区间完整性检查时，后者为 0；它不表示最终 ELF 已在 DUT 上运行。
- signature 检查验证格式与记录数，不逐值证明 .sig 转换为 .results 的正确性。
  SUCCESS 后允许普通统计输出，不要求 SUCCESS 是物理最后一行。
- 单文件数量与 constants.py 的上限比较，不逐个对照 generator 选的更小阈值。
- CONFIG_FILES 从记录命令解析，模型族按 executable 名推断；不执行该命令、查询版本或
  验证 ELF 与源码构建 hash。复杂 shell/多配置需要额外审查。
- VM checker 检查 contract 字段/集合，不模拟页表或证明生成代码绑定了每个 profile。
- testcase reachability 是保守的静态条件和符号检查，不是完整 C 预处理器；无法证明时保留
  `unverified`，不以猜测替代编译器结果。没有 `nm` 或 ELF 被剥离时，编译数量为未知而不是 0。
- sail_coverage.passed 的一致性检查不读取 UCDB/VDB 来证明命中；当前通过条件还要求
  self_checking.model 含 sail，不能直接表达任意混合后端组合。

使用[验证模板](../act4_template/privileged_validation_handoff_template.md)保留原始执行证据，
区分 signature ELF 运行、最终 ELF 生成和 DUT 执行。
