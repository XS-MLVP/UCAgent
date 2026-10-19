
# ACT4 privileged workflow checker 总览

本目录说明 `privileged-suite-generation.yaml` 当前实际注册的 8 类 checker。说明以
`act4_privileged_suite/checkers` 中的实现为准，重点回答：checker 阻止什么错误、怎样从输入得到结论、
输出怎样解释，以及哪些结论仍需运行或人工审查。

## Checker 清单

| Checker | 主要阶段 | 证据层 | 说明 |
| --- | --- | --- | --- |
| `ACT4CTPReferenceChecker` | 01 | 来源与计划 | [CTP reference](ACT4CTPReferenceChecker.md) |
| `ACT4ManualReferenceChecker` | 01 | 规范来源 | [Manual reference](ACT4ManualReferenceChecker.md) |
| `ACT4AssetChecker` | 01、02、04 | 静态资产关系 | [Asset consistency](ACT4AssetChecker.md) |
| `ACT4SwitchCapabilityChecker` | 01、03、04、05 | 控制入口与能力 | [Switch capability](ACT4SwitchCapabilityChecker.md) |
| `ACT4AIReviewChecker` | 01-07 | 审查状态 | [AI review](ACT4AIReviewChecker.md) |
| `ACT4TestAssetChecker` | 05、06 | 生成、构建与参考模型证据 | [Test asset](ACT4TestAssetChecker.md) |
| `ACT4FileManifestChecker` | 01、04-07 | 资产账本与框架完整性 | [File manifest](ACT4FileManifestChecker.md) |
| `ACT4FinalReportChecker` | 07 | 人类报告入口 | [Final report](ACT4FinalReportChecker.md) |

`act4_asset_consistency.py` 是 `ACT4AssetChecker` 的确定性核心，不是工作流中单独注册的
checker，因此与适配器合并说明。插件不携带其他 ITGen 流程的 checker。

## 共同运行模型

每个 checker 接收 YAML 中配置的参数，由 UCAgent 设置 workspace 后调用
`do_check(timeout=..., is_complete=...)`。返回值第一项决定 gate 是否通过，第二项是包含
`summary`、`checks` 和 `findings` 的结构化结果（Asset/TestAsset 返回值可能包在 report 下）。
`Check` 运行并报告；`Complete` 会再次
运行 checker，全部通过后才推进阶段。

ManualReference 和 FileManifest 会查询本地 Git HEAD。Checker 不负责下载 CTP、选择规范、
编译、启动 simulator 或运行 coverage backend。
通过结果必须和实际命令、validation state、AI review 及最终报告一起解释。

## 维护建议

- 修改工作流 schema 时，同时更新 checker、配置、指南和对应单元测试。
- 新增严格规则前准备一个通过 fixture 和至少一个针对该规则的失败 fixture。
- 将结构错误设为 error；环境缺失、未运行的可选 coverage 或可解释的静态分析盲区应由
  工作流按 limitation 表达，避免把局部不确定性扩散成整 suite blocker。
- 不要在 checker 中写死会随 ACT4 版本变化的 generator 阈值、模型路径或 target 能力；
  应从冻结源码、配置或显式 contract 中读取。

## 当前配置执行顺序

下表按`workflows/privileged-suite-generation.yaml`实际顺序列出。
类名省略 ACT4 前缀和 Checker 后缀；同一类的不同实例可开启不同检查。

| 阶段 | 执行顺序 | 本配置落盘的 checker 报告 |
| --- | --- | --- |
| 01 | CTPReference -> ManualReference -> Asset(coverage) -> SwitchCapability -> FileManifest(integrity_only) -> AIReview | act4_coverage_check 下 JSON/Markdown |
| 02 | Asset(mapping) -> AIReview | act4_norm_mapping_check 下 JSON/Markdown |
| 03 | SwitchCapability -> AIReview | 无；VM contract 是作者产物 |
| 04 | Asset(generator) -> SwitchCapability -> FileManifest(integrity_only) -> AIReview | act4_generator_check 下 JSON/Markdown |
| 05 | TestAsset -> SwitchCapability -> FileManifest(integrity_only) -> FileManifest(inventory) -> AIReview | act4_test_asset_check/test-assets.json |
| 06 | TestAsset(require_contribution_ready) -> AIReview -> FileManifest(completeness) | 无新配置的 output_dir，使用工具结果 |
| 07 | AIReview -> FinalReport -> FileManifest(completeness) | 无新配置的 output_dir，使用工具结果 |

SwitchCapability 支持可选 output_dir，本工作流未开启。Check/Complete 可能刷新报告，
不能把 Check 描述为无写入操作，也不能为其他 checker 伪造 JSON。
先收集实际输出、补齐 manifest，再运行 completeness。

## 证据与实现边界

配置中的任务要求通常比静态算法更强。完成阶段保持不变、CSR 保存恢复、profile 实际进入、
coverage 语义等要求，不能仅凭 checker 没报错就视为全部证明。
配套[阶段模板](../act4_template/README.md)随工作流复制到 Guide_Doc，供按阶段显式阅读。
