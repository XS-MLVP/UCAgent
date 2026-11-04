
# PPA 优化候选

Round 0 是第一版全功能通过的 base，不计入候选轮数。每轮先调用 `CurrentTips`，再根据
最近一次 `Check` 返回的 accepted 版本指标、相对变化和主要面积/功耗构成，选择一个范围明确、
能够由当前 `{RTL_LANGUAGE}` 源码修改验证的 hotspot。一次只验证一个核心假设，避免同时修改
多个结构后无法判断收益来源。

为当前轮写 `{OUT}/reports/ppa/candidate_hypothesis.yaml`。`iteration` 必须等于
`CurrentTips` 给出的候选编号，已经评估过的假设内容不能原样复用。随后只修改匹配
`{RTL_SOURCE_GLOB}` 的源码并调用 `Check`；不要自行运行分析命令，也不要编写或修改
Check/Complete 生成的报告、曲线和性能数据。

每次评估都分配一个连续的 `version`，base 为 `version: 0`，第一个候选为
`version: 1`，无论候选最终 accepted、功能失败还是 PPA rejected 都不能跳号。对应的
`{OUT}/reports/ppa/iterations/iteration-XXX.json` 和内部快照使用同一个三位编号；功能
失败的版本只记录拒绝原因和测试证据，不伪造 PPA 指标。这样可以在账本、恢复记录和看板中
完整追踪每个 RTL 版本，同时仍然只把有完整 PPA 证据的版本绘制为指标曲线点。

工作流使用固定 `relative=1e-6`、`absolute=1e-12` 容差。frequency/throughput 越大越好，
delay/latency/area/power 越小越好。候选必须满足全部硬目标，所有可比主指标相对上一
accepted 版本均不退化，并且至少一项严格改善。功能或性能测试失败时先修复当前语言源码；
这类失败不是 PPA 平台期，不消耗连续无改善次数。未满足 Spec 硬性能目标的完整候选也必须
继续修正，不能用它证明没有优化空间。`Check` 返回 accepted/rejected、相对上一 accepted、
base 和当前 best 的逐项指标变化及下一步，之后再次调用
`CurrentTips`。

优化轮数由三个配置项共同决定：`design_with_ppa.min_optimization_iterations`
（默认 5）是必须完成的候选轮数；`design_with_ppa.max_optimization_iterations`
（默认 1000）是防止无限循环的保护上限；`design_with_ppa.no_improvement_patience`
（默认 3）是达到最少轮数后允许连续无改善的次数。达到最少轮数并不会自动完成，
只要候选仍可被接受就继续迭代；连续无改善次数达到 patience 才以
`no_pareto_improvement` 停止，达到最大上限则以 `max_iterations_reached` 停止。
任何 accepted 改善都会将连续无改善计数清零。最终版本由账本中全部完整、功能通过且
accepted 的版本确定，rejected candidate 永远不能成为交付版本。

## 接受门禁

每轮候选相对上一 accepted 版本判定：`design_with_ppa.no_regression_metrics`
配置的指标类别（可选 `performance`、`area`、`timing`、`power`，默认只保护
`performance` 与 `timing`——即在不降低性能与频率/时序的前提下，尽可能优化面积
与功耗）中任何指标回退即拒绝（`pareto_regression`）；保护类别之外指标的回退
不阻塞接受，但仍会记录在候选账本中。没有任何一项主要指标严格改善的候选以
`no_pareto_improvement` 拒绝。硬性能指标未达标的候选以
`hard_performance_target_failed` 拒绝。best 版本在同一组保护类别上按 Pareto
支配关系从全部完整 accepted 版本中确定。

最终曲线还提供一个单一的 `ppa.selection_score`，用于在通过上述门禁的 accepted 版本中
排序并标识 best。base 的 score 固定为 `1.0`，越大越好，计算式为
`timing_efficiency^w_t * area_efficiency^w_a * power_efficiency^w_p`：时序主指标为
frequency 时取 `current/base`，为 critical delay 时取 `base/current`；面积和功耗都取
`base/current`。指数由 `design_with_ppa.score_weights` 配置（`timing`、`area`、`power`
三个键，默认各 `1.0`；设为 `0` 表示把该维度移出 score）。自定义功能性性能指标
（latency/throughput）不设权重：性能维度只由 frequency/critical delay 体现，它与自定义
性能指标呈确定的线性关系，加权即重复计权。frequency 与 critical delay 是等价时序指标，
只能选其中一个，不能重复计权。若面积、功耗或
时序值不是正有限数，score 必须标为 unavailable，不能伪造一个数值。rejected 版本可以显示
诊断 score，便于观察 tradeoff，但不具备 best 选择资格；功能、硬目标、可比性和接受
门禁不能被高 score 抵消。score 相同的 eligible 版本选择编号最新者。

## 完整候选假设示例

```yaml
iteration: 1
hypothesis: Replace the duplicated add/mux cone with one shared adder selected at its inputs.
target_hotspot: duplicated arithmetic and mux logic in the result datapath
expected_metrics:
  - ppa.area.total
  - ppa.timing.maximum_frequency_hz
```

`expected_metrics` 只能列出性能合同或最近一次 `Check` 指标摘要中已有的稳定指标 ID。
`hypothesis` 必须说明具体结构变化，`target_hotspot` 必须能定位到当前语言源码中的模块、
寄存器、运算或选择逻辑，只记录能够由当前源码和公开指标验证的推测。
