
# BugReview v6 指标评分

本流程只消费已完成的分析清单，并由 Python 计算指标。不要执行 replay、调用额外 LLM 服务、修改原始分析产物或根据期待的排名调整公式。分析清单中的对象是按高/中/低置信度记录的疑似 Bug；评分阶段只使用冻结的疑似 Bug、Case、覆盖率和证据字段。

每阶段先阅读 CurrentTips，再调用 BugReviewRunStage。Check 通过后记录 SetCurrentStageJournal，调用 Complete。任务依次是固定输入、单 DUT 指标、跨 DUT 汇总、报告发布。

v6 的根因召回、真实复现、公共功能、行覆盖、归因吻合、根因精密、现象覆盖和工程质量均使用仓库已有实现。缺失证据遵循 v6 可用性规则，不能手动补零或冒充满分。报告中必须保留缺失契约和验收诊断。疑似 Bug 的置信度用于分析展示和证据分层，不能绕过评分实现或改变评分公式。

清单校验失败时按具体文件和指纹错误处理，不能回退到目录扫描选择另一份数据。需要新的语义审查或回放时，应返回分析工作流补齐，发布新版本后重新准备评分 workspace。

最终交付 scores/overall_model_score.json、scores/overall_model_score.md、scores/dut_metrics.json 和 scores/index.html。重复启动复用已完成阶段。
