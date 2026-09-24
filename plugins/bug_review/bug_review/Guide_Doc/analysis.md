
# BugReview 证据分析

输入是已有 UCAgent 验证运行的产物。不要重新编写测试平台或替被评估模型补充 bug 声明。

## 每阶段操作

1. 调用 CurrentTips，阅读任务配置与本指导文档。
2. 调用 BugReviewRunStage，stage 使用当前阶段名。
3. 返回 awaiting_judgments 时调用 BugReviewTasks。messages 包含证据、判断标准和 JSON 输出格式。
4. 阅读完整证据，通过 BugReviewSubmitResponse 提交一轮 response。身份字段逐字使用工具返回值，round 对应 round_index。
5. next_round 表示需要继续投票、申诉或修正格式。再次调用 BugReviewTasks 获取最新问题；对每轮独立思考，不复制前一轮作为新票。
6. 当前批次完成后继续获取待办。队列清空后再次调用 BugReviewRunStage 收尾。
7. Check 通过后记录 SetCurrentStageJournal，再调用 Complete。

## 证据规则

第一阶段根据输入中的真实运行确定分析范围，生成 analysis_scope.json，记录 DUT、模型、运行目录、完成状态、缺失文件和诊断。分析范围以输入中的实际 DUT 与运行为准。
检查该清单后再完成 inputs 阶段。parse 只消费这份冻结清单，不重新扫描并选择运行。不完整运行保留已有证据；缺失测试报告意味着执行结果未知，不是没有失败。无法识别任何运行时第一阶段报错。

通过 UnityTest 直接启动的原始 workspace 可能尚未生成 `run_info.json`、`ucagent_info.json` 或 `toffee_report.json`。每次分析准备都必须创建/刷新独立副本，并通过 UCAgent `RunUnityChipTest` 重新执行全部已有测试，生成本次 `uc_test_report/toffee_report.json` 和测试波形。历史报告、历史失败和历史波形只作参考，不能替代本次执行。

Make 前置阶段不解析 `.dat`、不运行 FST 转换。`parse` 阶段同样只索引 `.dat`/FST 路径，并从 `toffee_report.json` 与覆盖率摘要读取总体指标；逐用例 `.dat` 命中行和波形信号必须在失败复核阶段按需处理。候选级 replay contract 只在 replay 阶段为当前分析运行生成，不得从历史运行复制。

结论必须引用实际提供的字段或源码证据。保持“不足以判断”和“不同根因”的区别。申诉与主判断使用不同的结果格式，以当前 messages 为准。程序负责校验、投票、聚类和持久化。

replay 是分析必经阶段，必须执行真实回放；不得通过关闭 replay 跳过测试重跑。环境错误不能手写成成功。工具失败时记录 error_code、具体任务或文件以及恢复动作。不要直接编辑任务存储、生成 JSON、GT、配置或评分公式。

默认开启 replay。该阶段先使用 UCAgent 的 RunUnityChipTest（RunTestCases 底层实现）在工作区副本中运行全部已有 pytest 用例，生成新的 toffee_report 和测试产生的波形，然后合并原始与本次报告中的失败用例。原输入保持不变；不修改测试预期、不创建替代测试。执行记录和副本位于 tasks/<DUT>/replay/runs/。
pytest 未收集到用例、收集/环境错误、超时或报告缺失时阶段失败，检查 execution.json 中的诊断及 stdout/stderr。不得把这些情况当成零失败并继续发布。波形由原测试的 DUT/fixture 配置生成，pytest 本身不保证每个测试有波形；没有波形时须记录证据不足。

## 全量失败用例归因

解析后先执行 replay，再执行 waveform，之后才进行语义比较和根因聚类。
replay 的待办来自全部失败测试，包含未被模型报告的失败、精确参数化实例及 setup/teardown 错误。
每项必须独立推导规格预期，核对实际输入、测试预期、DUT 输出、参考模型、driver/fixture、复位、握手、采样边沿和响应延迟。

通过 BugReviewSubmitResponse 提交 classification：suspected_dut_bug（疑似 DUT 缺陷）、spec_misunderstanding（规格理解错误）、testbench_issue（测试实现问题）、environment_issue（环境问题）或 inconclusive（证据不足）。
同时填写 correctness_confirmed、exact_input、specification_expected、test_expected、dut_actual、driver_timing_review、rationale 和 evidence_refs。
evidence_refs 使用任务证据内的 / 分隔路径，例如 /case/original_executions/0、/sources/source-ID；缺失信息必须明确说明。
只有测试正确性已经核实才能提交 suspected_dut_bug。回放通过或失败只是执行结果，不能自动判断责任方。
重跑结果必须覆盖全部当前失败；禁止修改被分析模型的测试、预期值或 bug 声明；分析发现的问题和原模型已经报告的问题分别保留。

## 波形分析

waveform 接收本次重跑后的全部失败用例；只有有明确 setup/teardown/collection 诊断的环境失败可免波形，其余失败即使尚未确认 DUT 责任也必须调用 WaveInfo 并完成波形审查。
先调用 BugReviewWaveInfo(task_id=当前任务, query={}) 获取目录和精确 test_case_name，再查询信号。
最终调用必须提供完整时间窗口 start_step/end_step 或 logged_cycle/clock_signal，使用 signal_groups 声明真实时钟或 combinational、相关输入输出、协议控制及关键状态信号。
pattern 只定位事件；不要为了展示上下文把所有信号都设成事件触发条件。
结合规格与测试调用顺序解释请求何时接受、响应何时有效、实际 latency 以及断言对应哪笔事务。Step(1) 不自动意味着输出有效；无效周期的单点 mismatch 不证明缺陷。

工具返回 evidence_id 后，通过 BugReviewSubmitResponse 提交 conclusion、evidence_id、alignment_evidence、observed_behavior、source_correlation、rationale 和 evidence_refs。
conclusion 使用 dut_bug、spec_misunderstanding、testbench_issue、environment_issue 或 inconclusive。
dut_bug 必须关联工具生成的完整签名波形证据；即使没有可用波形也要调用工具记录具体错误，保留 inconclusive，不能编造波形、receipt 或 viewer 链接。
同一用例的多个模型声明共享波形记录。波形复核发现测试或理解错误时应修正分类；所有待办完成后再次 BugReviewRunStage 收尾。

GT 归因审查在回放与波形证据合并后执行，审查范围限于当前模型已有证据支持的 GT 命中。证据分析报告包括逐用例失败归因、波形复核、声明、根因、语义审查、排除项和原始覆盖率，不输出模型总分。

## 报告数据契约

`publish_analysis` 在渲染 HTML 之前构造 `benchmark_report_data.v1`，并写入每个 DUT 发布目录的 `report_data.json` 与 `data/report_data.json`。报告页面只消费这份结构化数据；样式、源码折叠和页面导航属于渲染职责，事实、计数与裁决不得只写在 HTML 模板中。

报告数据包含以下内容。报告面向疑似 Bug 分析；登记簿数据只作为背景参考或评分输入，不能隐藏未匹配的疑似 Bug。

1. `verification_status`：代码覆盖率、功能覆盖率、回放总数、失败数、疑似 Bug 总数及 high/medium/low 置信度计数、失败归因分类计数和状态摘要。
2. `suspected_bugs`（兼容字段 `final_bugs`）：每条疑似 Bug 都必须有唯一 `bug_id`、`confidence`（`high`/`medium`/`low`）、标题、摘要、影响、复现用例、验证场景、验证目标、预期、实际、缺陷机理、规格依据、修复建议、证据边界和详情入口。
3. `final_bugs[].cases[].waveform`：裁决证据 ID、FST 路径与格式、文件大小、完整信号数量、采集时间、是否为最新 session、选择规则、分析窗口和 Web 波形查看器元数据；详情页可另外生成裁决信号的轻量预览。同一用例只暴露按 latest session、FST 优先、最大数字后缀和最新 mtime 选出的一个波形。
4. `review_items`：低置信度或仍待复核的疑似 Bug 兼容视图。它们仍然出现在疑似 Bug 表和详情页中，不得因为没有 GT registry 匹配而删除。
5. `failed_cases`：仅包含失败用例，使用 `bug`、`needs_review`、`false_positive`、`environment` 四种简化最终类型，并记录依据、回放状态与失败表现。成功用例不在报告表格中展示。
6. `presentation`：详情章节顺序、失败表位置和是否展示成功用例等展示约束。

可由证据确定的 DUT、疑似 Bug 身份、用例、计数、FST 和信号元数据必须从 `analysis.json`、逐用例审查及波形结果生成。覆盖率口径、场景说明、根因解释和证据边界等无法可靠自动推导的内容，放在版本控制下的 `bug_review/configs/report_profiles/<DUT>.json`，由发布阶段合并；profile 的内容变化会形成新的报告发布版本。

`suspected_dut_bug + correctness_confirmed` 表示测试通过了初步正确性检查并进入疑似 Bug 分析。根据证据完整度设置置信度：有清晰 transaction ownership、采样时序、Spec 预期、RTL 机制和当前波形支持时为 high；缺少一项关键闭环但已有明确 DUT 迹象时为 medium；只有部分失败现象或存在重要反证时为 low。多个用例若指向同一 RTL 根因，可以合并到同一疑似 Bug，但每个 Case 的波形和证据引用必须保留。

每条疑似 Bug 详情必须回答：问题是什么、合法输入是什么、规格预期是什么、实际第一分歧是什么、哪段 RTL 可能造成该分歧、关联哪些 Case、Spec 和波形支持到什么程度、还有哪些不确定性。详情页应提供关键波形预览图片，并保留原始完整 FST/波形查看入口。

发布目录采用单版本保留策略：新的 sealed 报告切换为活动版本后，删除旧报告版本和残留临时发布目录，只保留 `current` 指向的版本。`tasks/` 下的审查 JSON 和证据工作区不属于报告版本，不随报告清理。

## 恢复与交付

中断后启动相同 workspace，调用 BugReviewStatus。程序复用已经校验的任务。输入发生变化应准备新 workspace，保留旧版本供复核。

最终交付 analysis/analysis_manifest.json、analysis/index.html，以及各 DUT 的 analysis.json、report_data.json、data/report_data.json 和 index.html。首页保留覆盖率和验证状态，主要展示疑似 Bug 表与失败 Case 表；疑似 Bug 详情页关联 Case、RTL、Spec、波形简析和完整波形入口。将清单传给独立评分工作流。
