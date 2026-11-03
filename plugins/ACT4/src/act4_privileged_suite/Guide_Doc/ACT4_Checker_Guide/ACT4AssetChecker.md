
# ACT4AssetChecker

显式限定某 extension 的 coverage 集合时，可设置 `discover_coverage: false`，使空
`coverage_files` 保持为空；默认自动发现 ACT4 原生 coverage 路径。显式配置的文件或
patterns 仍会检查，不把其他 extension 的默认 coverage 集合当成本轮目标。

适配器：`act4_privileged_suite/checkers/act4_asset_checker.py`

核心：`act4_privileged_suite/checkers/act4_asset_consistency.py`

## 作用

该 checker 在阶段 01、02、04 分别验证 coverage、norm mapping 和 generator。它建立
Sheet/testplan、metadata rules、SystemVerilog coverage symbols、mapping targets、Python
generator testcase linkage 和 VM scope 之间的静态集合关系，是资产结构一致性的主 gate。

## 主要输入与输出

- 输入可组合配置：suite、ACT4 root、mapping、规范化 CSV、normative metadata、coverage
  文件、generator 文件、CTP 文件、coverage intent 和 VM/generator scope contract。
- `checker_type`、`coverage_comparison_mode`、`require_*` 开关控制当前阶段启用的子检查。
- `output_dir` 启用时写出 `*.asset-consistency.json` 和 Markdown 摘要；报告包含扫描数量、
  mapping、coverage、generator、CTP 和 findings。

## 代码实现原理

1. `ACT4AssetChecker` 负责 UCAgent 参数、workspace/ACT4 路径解析和报告落盘，把确定性
   工作交给 `run_asset_checks()`。
2. 核心用 YAML/JSON/CSV parser 读取结构化资产，验证 schema、rule 名、waiver 和集合
   完整性。
3. SystemVerilog scanner 去除注释后分析 covergroup、coverpoint、cross、bin、条件和
   文件归属。语义子检查只实现 cross 输入 default bin、$onehot 按位置分箱等有限规则；
   intent 检查比较 required_cross_members、required_conditions、required_bins 和
   required_expression_terms，最后一项是表达式子串包含检查。
4. Python generator scanner 使用 `ast`，追踪注册装饰器、常量/有限符号传播、testcase
   调用、coverage target 字符串、`TestChunk` 生命周期及分文件参数。
5. 通过集合差比较发现未映射 rule、悬空 target、coverage/generator 缺口、跨 suite
   ownership 和 scope contract 不一致。

## 当前局限

- 这是静态 checker，不运行 SystemVerilog 预处理、仿真或 coverage database；它不能证明
  bin 被命中，也不能验证 RVVI 信号时序。
- SV scanner 不是完整编译器，宏展开、include 顺序、复杂 generate/表达式可能超出其
  解析能力。
- Python AST 只做有限常量传播。动态拼接、反射、间接 helper 或运行期生成的 target
  可能产生 warning、漏报或需要 AI/人工复核。
- target linkage 证明 generator 声明/引用了 coverpoint，不证明 testcase 激励和观测在
  架构语义上足以覆盖该目标。
- parser 接受的语法是当前工作流契约，不自动代表所有 ACT4 版本的合法写法。

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_asset_consistency.py`。核心和 UCAgent 适配层
应保持解耦，便于 CLI、单元测试和工作流共享同一套规则。

## 实现定位与判定示例

核心入口 `run_asset_checks()`；扫描函数为 `scan_systemverilog()`、
`scan_python_generator()`、`parse_canonical_sheet()`；generator gate 在
`_validate_priv_generator_api()`，阈值由 `_read_priv_testcase_limit()` 读取。
阶段 01 启用 coverage intent，02 比较 mapping targets，04 另外启用 scoped targets、
TestChunk API、自动拆分及 mapping linkage。

如报 `coverage_intent_cross_members`，检查缺失的真实语义维度；如报
`generator_discarded_assembly`，将返回汇编追加到 chunk 并检查实际输出。
`fail_on_warning` 默认 false。

当前 checker 拒绝同一 suite 多个可解析注册；冻结 ACT4 registry 文档允许多个注册，
因此这是本工作流静态 gate 的限制，不能写成 ACT4 普遍限制。

intent 由作者声明，checker 不从规范推导 selector/operation/outcome 的正确性；
同时写错 SV 和 intent 仍可能通过。AST lifecycle 检查不能证明所有执行路径返回 TestChunk，
也不能完整验证 CSR 数据流。静态检查须结合[generator 模板](../act4_template/privileged_test_generator_template.md)
要求的源码和运行审查。
