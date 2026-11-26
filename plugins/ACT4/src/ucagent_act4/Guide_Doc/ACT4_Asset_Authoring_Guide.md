
# ACT4 资产设计与原生生成约定

生成、review 修复和香山补缺共用本指南。先读固定 ACT checkout 的 `docs/DeveloperGuide.md`，
再核对相关原生源码；文档与实际接口不同，记录具体差异，不凭扩展名字或历史经验推断。
本指南不替代 ISA 原文，也不要求创建额外报告。设计写入当前工作流已有的
design_review、AI review 或 repair_plan；香山仅把适用的设计与限制带入 TESTS.md。

## 1. 按测试结构选择路线

| 条件 | 原生资产 | 工作流入口 |
| --- | --- | --- |
| 单指令、寄存器/操作数矩阵，测试不发生 trap | CSV、coverpoint template、formatter、decoder | unprivileged-suite-generation |
| 状态序列、CSR、异常或需要 trap handler，即使指令属于非特权 ISA | 行为计划、priv coverage、suite generator | privileged-suite-generation |
| 已有资产存在缺陷或遗漏 | 保留原生组织方式，增量修复源资产并再生 | 对应生成入口的 improve 策略 |
| 已有生成器但缺少 .S | 运行固定版本的原生生成入口 | 上游复用，不新建 AI 生成任务 |

“非特权 ISA”不等于“适合表驱动测试”。原生表驱动环境不设置 trap handler，意外 trap
可能表现为挂起；不要靠延长超时掩盖。DeveloperGuide 以 ZicsrF 说明非规则化的非特权
测试也可使用 priv-style。跨路线的需求分开说明，不能把需要异常检查的用例改成不检查异常。
香山的 `generation_style: table` / `scenario` 分别选择上表两个生成入口，eligibility
解释指令结构、trap 需求和可用原生接口；已有 suite 修改仍走 review，不借补缺覆盖输入。

## 2. 从规则到可观察结果

逐项回答：规则及条件是什么、用什么状态和操作触发、观察什么结果、如何区分错误实现、
如何恢复环境、哪些参数改变适用性。把规则关联到实际 covergroup/coverpoint，再关联到
testcase descriptor、生成的 .S 和目标配置，而不是仅在多个文件中重复相同名称。
`Guide_Doc/act4_template/native_asset_design_template.md` 给出完整的设计记录示例；
其中设计不代表已执行证据，实际文件和行号须从本轮输入获取。

coverage 的采样表达式要能观察意图，不能把“执行过指令”当作“所有结果均正确”。
反过来，signature 检查通过也不证明覆盖点的每个 bin 都命中。组合场景不一定都有独立
norm tag，但必须说明来源与意图，不能发明规则编号。实现参数记录在 `coverpoints/param/`
映射及 CTP 中；参数适用性与测试头的筛选条件保持一致。

## 3. 原生扩展点与生成纪律

- 表驱动：`testplans/<Suite>.csv` 的 Type、XLEN、ExtraExtensions、coverpoint variant
  决定生成链。新点同时补 SV template 和 `@add_coverpoint_generator`；新 Type 同时补
  `sample_<TYPE>.sv`、`@add_instruction_formatter` 和 `InstructionTypeConfig`。
  修改共享点时列出实际消费者，安排相关 suite 回归，不能只验证新 suite。
- 解码：核对 `framework/src/act/fcov/disassemble.svh`；没有普通指令计划行的指令还需核对
  `testplans/coverage/instruction_formats.csv`。编码来自生成的 decode package；
  禁止手改 `RISCV_imported_decode_pkg.svh`，缺编码应修正原生编码来源并重新生成。
- 生成器：先读所选 checkout 的 registry、TestData、TestChunk 与相邻实现。
  priv 和 special generators 通过 begin/end chunk 组织 code/data 并返回 TestChunk 列表；
  普通 coverpoint 优先使用 format_single_testcase 等原生 formatter，不能混用返回接口。
  `test_data.add_testcase` 放在真实测试入口附近，comment_banner 说明 coverpoint 意图。
- 寄存器由 allocator 分配并释放，结果通过原生 signature helper 更新；CSR/trap 与恢复
  路径必须有真实观测。循环在 Python 中展开，不生成无法唯一定位 testcase 的汇编循环。
- 分文件：长度拆分不切开单个 chunk；named split 的每个文件都需独立 setup/teardown。
  不跨文件依赖上一文件的 CSR、页表或寄存器状态。保留原生标签、descriptor 与文件命名。
- header/footer、签名和 .S 由匹配版本的 writer 产生。修复 generator 后重新生成，
  不手改生成汇编、生成 SV 或签名来规避失败；仅手写原生资产才直接修复相应源文件。

特权/场景型的 VM、CSR、guard、实验和 AI review 字段仍按
`Guide_Doc/act4_template/privileged_test_generator_template.md` 执行，不因共用本指南而省略。

## 4. 测试头决定哪些目标会运行测试

这是一个完整的原生配置头示例，仅展示语法，不代表任一现成 suite 的完整测试程序：

```asm
// START_TEST_CONFIG
// REQUIRED_EXTENSIONS:
//   - I
//   - Zicsr
//   - [Sm, U]
// FORBIDDEN_EXTENSIONS: [S]
// MARCH: rv${XLEN}i_zicsr
// MIN_HARTS: 1
// NEEDS_SIGNATURE: true
// params:
//   MXLEN: 64
//   NUM_PMP_ENTRIES: '>0'
// END_TEST_CONFIG
```

所有顶层 REQUIRED_EXTENSIONS 条件是 AND，嵌套列表内部是 OR。FORBIDDEN_EXTENSIONS
排除实现了指定扩展的目标。MARCH 是编译器 ISA 字符串，不必与选择扩展逐字相同：S/Sm/U
等特权模式不放入 march。MIN_HARTS 与 params 决定目标适用性；比较约束要保留 YAML 引号。
不能为了让测试被选中而删除真实前置条件。header 必须位于指令之前，注释剥离后仍保留
列表和 params 的缩进；缺字段、重复字段或意外顶层 MXLEN 都是问题。

NEEDS_SIGNATURE 在所选版本的原生解析器支持时使用；默认 true。false 不能作为绕过
自检构建的手段，须有原生测试设计依据。开发者文档的键表可能未列出这个字段，应核对
`framework/src/act/parse_test_constraints.py`，不依据文档遗漏删除合法约束。
本插件的检查提供语法预检，不判断参数值是否真实、目标是否支持指令或测试语义是否正确。
未知字段不能静默忽略；先对照本轮原生解析器确认问题或接口差异。

## 5. 验证与定位

1. 用本轮原生入口重新生成，确认计划、模板、generator 和输出一致。
2. 检查 header 和目标 UDB 筛选；空 ELF 集不是成功。预期有结果却没有执行时，先查
   扩展、XLEN、参数、hart 数、exclude 设置与命名，而不是扩大功能范围或改预期值。
3. 按原生流程编译、参考模型生成签名、重编译自检 ELF，再用配置的 run_cmd 执行最终 ELF。
   `.sig.elf` 是中间阶段；运行日志与最终结果必须对应当前源文件和目标配置。
4. 功能 coverage 需真实 trace 和 coverage 工具。Questa/VCS 等不可用时保留验证限制，
   不阻塞无关的生成、lint、编译和参考模型验证，也不声称已测覆盖率。
5. 调试用该版本 run_tests.py 支持的 DEBUG 与 trace/summary 分离选项，避免 trace 淹没
   RVCP-SUMMARY；把日志留在 intermediate，不复制到最终交付包。工具未支持的选项不猜用。

原生 hooks、CTP 构建与所选配置通过，不等于上游完整 CI、维护者批准或真实 DUT 认证。
贡献 patch 的源码政策、规则/参数映射、CTP 和提交要求见 `Guide_Doc/ACT4_Generation_Guide.md`；
review 把预检结果作为待核对的事实，保留独立 ISA 设计、语义审查和修复后的再验证。
