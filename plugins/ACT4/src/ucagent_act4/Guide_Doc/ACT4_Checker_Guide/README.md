
# ACT4 生成验收指南

按当前阶段 reference_files 阅读验收要求；Check 用于发现具体问题，Complete 用于推进阶段。
完整资产示例和共同操作见 `Guide_Doc/ACT4_Generation_Guide.md`。

## 共同验收

| 验收 | 检查内容 | 操作指南 |
| --- | --- | --- |
| 原生输入 | 固定计划、规范与正式规则快照 | [Generation inputs](ACT4GenerationInputsChecker.md) |
| 原生资产 | 计划、规则/参数、CTP、coverage 与必要生成源码 | [Native assets](ACT4NativeAssetsChecker.md) |
| 原生运行 | 贡献集隔离重生成、hooks、CTP、编译与运行 | [Native validation](ACT4NativeValidationChecker.md) |
| 文件清单 | 贡献集合、基线、文件分类和保护边界 | [File manifest](ACT4FileManifestChecker.md) |
| 最终报告 | 可导航索引、真实结果和贡献补丁 | [Final report](ACT4FinalReportChecker.md) |

## 特权流程附加验收

| 验收 | 检查内容 | 操作指南 |
| --- | --- | --- |
| 静态资产关系 | coverage、规则、generator 和派生计划的关系 | [Asset consistency](ACT4AssetChecker.md) |
| 能力审计 | 控制入口、模型能力、受影响的 target/profile | [Switch capability](ACT4SwitchCapabilityChecker.md) |
| AI 审查 | 阶段结论、证据、限制与阻塞项 | [AI review](ACT4AIReviewChecker.md) |
| 生成测试 | ELF、签名、模型运行、VM scope、可达性 | [Test assets](ACT4TestAssetChecker.md) |

## 结果解释

先完成输入准备和基线，再实现原生资产；原生隔离验证在贡献清单完成后运行，最终阶段
复核当前收据与报告。不要手写运行收据、只修改日志或编辑派生文件来使 Check 通过。

静态结构通过不等于语义正确、动态覆盖或真实 DUT 已通过；所选 native configs 通过也不
等于完整上游 CI。缺工具和未测范围必须保留为限制，AI 自审不替代维护者审批和贡献者签署。
