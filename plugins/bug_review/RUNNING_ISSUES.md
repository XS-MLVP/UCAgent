# Bug Review 运行问题与集成记录

更新日期：2026-10-25。本文供插件、UCAgent 核心和 Swarm 集成维护者使用；不是工作流给模型执行的操作指令。后续复现和修复应继续更新对应条目，避免把临时绕过当作已修复。

## 本次验证范围

在独立 `UCAgent-bug-review-next` worktree，通过插件 Make 入口启动 RAID ENC、DEC，后端为 Codex，使用既有 native DUT 和测试输入的隔离副本。未修改原始 RTL、测试、断言，也未修改 Swarm 当前 launcher。插件版本为开发中的 0.4.6，配套 UCAgent 核心修改尚未提交。

本地证据位于仓库根目录的 `output/raid-codex-20261025/`（生成目录，不随 Git 分发）：

- `input-provenance.json`：输入来源与文件哈希。
- `processes.json`：当前启动信息和此前尝试。
- `raid_enc_top.log`：首次端口冲突；`raid_enc_top-attempt2.log`、`raid_dec_top.log`：测试收集路径错误。
- `raid_{enc,dec}_top-rootdir-fix.log`：修复后的实际运行日志。
- `regression.log`：相关回归 275 passed、1 skipped；不代表真实 RAID 分析已完成。
- `status.json`、`watch.log`：本地监控快照与日志。检查快照时间，不能把陈旧快照当作实时状态。

截至本次记录，两项任务均已导入全量重跑结果：ENC 122 passed、112 failed，正在第一阶段收尾；DEC 113 passed、91 failed，已进入第二阶段 `case_triage`。两者尚无最终报告验收结论。pytest 的 failed 是待复核测试失败数，不是已确认 DUT Bug 数。

## 已复现的问题

| 编号 | 问题与影响 | 当前处理 | 归属与后续验收 |
| --- | --- | --- | --- |
| BR-RUN-01 | 同时启动两个 MCP 服务，自动端口 `-1` 都选到 5001，其中一个绑定失败。 | 临时为 ENC、DEC 显式分配 51371、51372；未修复自动分配竞争。 | UCAgent 核心负责安全绑定/分配；Swarm 或本地 launcher 在修复前应分配不同端口。并发启动验收须确认每个后端连接到自己的 MCP，而非仅检查端口可访问。 |
| BR-RUN-02 | 工作区位于 UCAgent 仓库内，输入没有 `.pytest.ini` 时，pytest 继承上层项目根目录，node ID 带 `output/...` 前缀，收集阶段无法映射 Case。 | 已修复插件 collection：显式 `--rootdir=.`；Make 入口通过 `PYTEST_ADDOPTS` 为定向复跑固定测试根目录。真实收集 ENC 234、DEC 204 个 Case，node ID 为 `tests/...`。 | 插件负责收集目标；非 Make 的 UCAgent/Swarm launcher 也须落实相同测试根目录。已补父目录存在配置的回归；平台入口尚未联调验收。 |
| BR-RUN-03 | 数字结尾的独立 Case 波形可能被误认为另一 Case 的 dump 序号，例如 `test_wframe_n129.fst` 被选给 `test_wframe_n`。 | 已在核心 WaveInfo 按完整 Case 索引判定归属，插件配置该索引并校验收据归属；同名/含糊映射明确阻塞。 | 核心与插件必须配套升级。单元测试及历史 ENC 文件选择检查通过；跨 invocation 的完整波形来源映射仍未完成，文件名不能证明执行归属。 |
| BR-RUN-04 | 原生 DUT 依赖 Python ABI、动态库和仿真运行环境，切换解释器或混用安装版本可能无法导入/执行。 | 本次使用已验证的 Python 3.12 环境，保留 native 包哈希，设置 `--forked` 隔离原生仿真；未重新编译 DUT。 | 启动器应绑定解释器、核心、插件与 native 输入身份，并先做导入检查。这是本次环境约束，不是本轮新复现的 ABI 崩溃。 |
| BR-RUN-05 | Codex 日志反复出现 `OutputTextDelta without active item`，容易被误判为任务失败。 | 本轮 smoke 与实际 MCP 工具调用在该日志后仍成功；暂记为待定位的流事件诊断，不据此重启。 | 后端/网关适配层调查。需要关联请求结束状态、进程退出和实际工具进展，不能仅按日志关键字判断成功或失败。 |
| BR-RUN-06 | 本地 watcher 读取初始化记录中 `review_path: null` 时异常退出。 | 已修复本次生成的 `watch.py`，容忍未初始化路径并重启监控。 | 仅本地辅助脚本修复，尚未产品化；Swarm 状态读取同样应容忍合法的中间态。 |
| BR-RUN-07 | 约 15:09，DEC 在第二阶段出现 Codex `Reconnecting... 1/5`；MCP 调用从 15:08:43 至 15:12:42 间断约 4 分钟，同期 ENC 仍正常提交。 | 原 Make/UCAgent/Codex 进程保持存活，未重启；15:12:42 已恢复 `PatchCaseDraft` 调用，继续观察正式记录提交。 | Codex 后端/连接链路待排查；本次是自动恢复，不代表连接问题已修复。不能直接归因为插件或整个服务不可用；进程存活与 TCP ESTABLISHED 均不能单独证明任务有进展。 |
| BR-RUN-08 | 第二阶段长会话的请求输入持续增长。15:19 检查 Codex 会话 `last_token_usage`：ENC input_tokens=271970、DEC=373144；DEC 该请求 cached_input_tokens=6912。 | 记录真实会话用量作为性能线索，未修改运行中会话或猜测服务端故障原因。 | 后续评估按阶段/已提交批次压缩上下文、减少重复工具输出，恢复时由正式记录和工作队列重建必要上下文。需要对比延迟、缓存命中与结果质量，不能仅据输入量认定网络错误原因。 |

BR-RUN-07 后续：DEC 再次出现自动重连，15:18:05 恢复 `UpdateCaseRecords`，随后正式记录从 35 个增加至 40 个，15:20:16 再次提交。ENC 从 15:12:52 起暂未出现新工具调用，截至 15:20 原进程仍存活。两者的连接等待与分析进度应分开记录。

ENC 在 15:28:43 恢复 `PatchCaseDraft`，工具调用间隔约 16 分钟，未手动重启，尚未达到默认 1200 秒空闲超时。此段时间没有 pytest 执行或未完成的 MCP 工具调用，不能计作 RTL/波形分析耗时；具体模型请求等待原因仍待服务端证据。

## 取证阶段观察

15:40 DEC 进入第三阶段。波形盘点能够解析失败 Case 的已有 FST，例如 `test_api_raid_dec_top_mem_write_read_basic` 的窗口为 0..27；这只证明文件可读，不证明断言后的操作执行过。

首个 WaveInfo 调用出现两次可恢复的参数错误：传 `signal_groups` 却遗漏事件 `pattern`；随后将 `raidd_mem_mread && raidd_mem_saccept` 表达式作为 `signal_groups.protocol`，而该字段要求精确完整信号路径。诊断返回后模型自行改正，15:42:20 收到 `events_found`。后续可在工具参数示例中更明确地区分事件条件与信号路径，减少试错；当前校验正确拒绝非法参数，不应放宽为猜测匹配。仍须核验最终 `evidence_usable`、签名收据附着与实际事件记录，不能仅凭 `events_found` 宣称取证完成。

15:44 抽查首个 DEC Case 正式记录：收据已附着，事件 `mem-write-accept` 用真实时间 11、`raidd_mem_saccept=1` 记录正常写请求接受，却标为 `first_deviation`。这是语义问题，签名测量只能证明信号值，不能证明该值违反规格。最终审核必须重新检查事件：正常接受应是触发/正常参考；只有具备条件、预期和实际冲突的事件才可标首错。当前运行仍在补充分析，尚未修改其正式记录；需在后续阶段核实是否纠正，不能因此接受误导性的首错标题。该 Case 的场景地址文字也需与原测试和收据对齐，避免初步描述与后续分析相互矛盾。

16:05，DEC `test_inf_mem` 将 `saccept` 无上升沿解释为“没有协议事件，无法附着最终证据”，只保存诊断收据。该 Case 的 FST 可读，窗口 0..1015，测试失败正是等待 MEM 接受超时；缺少响应边沿不能等同于波形不可用。应检查真实请求边沿或时钟边沿，以实际请求与控制信号建立窗口，测量请求保持期间响应缺失、门控状态和相关 RTL；不能发明不存在的握手。后续检查须确认它没有以 `no_candidate` 代替无法读取文件的签名诊断而结束调查。当前仅记录问题，尚未证明该 Case 的最终归因。

16:09 已把上述两条取证方法要求补充到插件工作流指引及本次两个工作区的 `AGENTS.md`；YAML 解析通过。没有修改正式记录或原始输入，也没有重启任务。已有长会话是否重新读取任务指引仍需验证，不能把文件更新当作运行中问题已修复。

16:11–16:13，DEC `test_inf_outbp` 连续猜测不存在的 `raidd_feh_wready`、`TOP.raid_dec_top_top.clk`、`u_rdec.sys_clk`，还将 `valid_ready` 放入 protocol 路径。工具正确返回 `signal_not_found`/`signal_group_path_not_exact` 与候选路径，但模型未立即使用已返回的真实路径。16:14 已恢复附着新收据。后续优化应优先让信号目录结果直接复用于信号组，而非放宽精确路径检查；同时记录参数修正次数及其耗时，区分模型试错与波形解析成本。

16:23，DEC 调用 `ValidateCaseRecords` 检查两个 Case 返回 success=true。代码核实该工具仅在索引 `stage_status.dut_evidence=complete` 时启用 require_wave；因此在进行中的取证阶段，这个结果不是完整取证验收。16:27 已修复反馈：返回 `validation_scope.completeness` 与 `stage_completion_checked=false`，提示用 `ReviewWorkQueue(stage="dut_evidence")` 查询完整缺口、以 Check/Complete 完成阶段；同步工具描述、Guide 与 Skill。新增回归证明同一个缺少事件的 Case 在增量检查中通过但明确标识未检查取证完整性，声明完成后被拒绝；相关 9 项测试通过。门禁与增量提交语义未放宽，运行中的进程尚未加载该代码更新。

16:35 DEC 完整 Check 返回 154 个字段缺口，其中明确拒绝 `test_inf_mem`、`test_inf_mem_respbp` 的非最终证据，也列出其余未调查项缺少波形或 scenario_steps。验证了完整阶段门禁没有接受上述增量 lint 成功或无边沿说明作为调查完成。DEC 继续取证。ENC 同时通过第三阶段，进入原报告对账；这仍不代表整个 Bug Review 完成。

16:56 复查，DEC 上述两个 Case 已通过真实 mwrite 请求（原始时间 617）定位窗口并附着收据和事件。记录观察为：请求字段有效，clk_ungated 持续变化而 gated clk 无变化，raid_auto_clkgat=1，saccept/svalid 保持 0；后续读回或响应背压操作尚未到达。说明模型在完整检查拒绝后补到了可观察的请求/门控证据，不再以缺少响应边沿结束这两个 Case 的调查。该进展不是全模块或最终因果裁决完成，也不能证明运行会话已读取新增 AGENTS 指引。

## ENC 完成与浏览器验收（17:01 起）

ENC 六阶段完成并正常退出，总耗时 2:16:51，发布成功。15 个现象裁决为 confirmed=2、refuted=11、inconclusive=2，形成 2 个 ROOT 页面；报告 manifest 的 review_status=incomplete 表示仍有 2 项 causality_unresolved，不能误报为任务运行失败，也不能称所有现象已解决。

实际浏览器检查首页与两个 ROOT 页面均返回 HTTP 200。波形 FST、转换器及 WASM 均能下载，外部接口曲线能显示，但两个 ROOT 的 Surfer 深链最终报目标信号不可用，未完成目标窗口/游标定位。涉及内部数组 `memif_pmem_wr_l.memif_pmem_wr_l[0]` 及后续 `memif_pmem_rd`；转换所得 VCD 中两个完整路径实际存在。初始 10 秒看到的“转换完成”遮罩是等待深链信号就绪，30 秒检查才能看见报错。应核对 AddVariables 的数组引用语义及部分添加失败，不可仅以 HTTP 200、canvas 存在或外部曲线可见判定波形验收通过。当前排查中。


17:11–17:12 DEC 再次出现 `Reconnecting... 1/5`，17:12:43 恢复 CreateCaseDraft；未手动重启，后续仍需核实正式记录继续增长。

17:17 波形跳转修复通过真实浏览器复测。根因是 deep-link 把 `mem[0][3:0]` 的数组下标当成单个位索引，而 Surfer/Wellen 将该数组组织成 `mem` 作用域下的 `[0]` 变量。数组引用失败还使同批后续信号未显示。已修复核心 `deep-link.js`：带 packed range 的数组元素映射为嵌套 scope/元素名，普通总线和独立位索引保持原语义；原始签名 token、快照和事件元数据未改动。新增数组引用与 applyWhenReady 回归，两个 JS 测试脚本及 5 项服务集成测试通过，git diff --check 通过。同步 ENC 报告静态资源后重新发布校验通过；两页 HTTP 200、无 pageerror，内部数组曲线可见，事件面板分别定位到 87、75，窗口缩放正确，遮罩和错误页消失。截图与机器记录在运行目录 `enc-surfer-{0,1}.png`、`browser-wave-check.json`。这是本地报告验证，尚不代表 Swarm 服务已升级。

17:24 通过只读 ReviewWorkQueue(stage=dut_evidence) 实查，DEC 尚有 65 个 Case 存在完整性缺口，主要为最终波形证据及 scenario_steps；不是只差一个阶段声明。17:26 正式记录继续增加，UpdateCaseRecords 调用约 0.05 秒，最近工具调用间通常间隔十几至几十秒。阶段耗时需区分单工具执行与模型每轮响应/分析开销；可评估在保证各 Case 独立取证的前提下批量提交与复用已读取的 Spec/RTL，不应直接共享收据或降低完成门禁。17:18 复查首个 MEM Case 仍将正常 saccept=1 标为 first_deviation，最终语义审查仍是未完成事项。

17:32–17:33 监控到宿主机资源竞争：16 个逻辑 CPU，一分钟 loadavg 约 26，可用内存约 0.6 GiB、无 swap；RSS 主要来自既有 qemu 与并行 rustc/ld，DEC UCAgent/Codex 各约 198/249 MiB。此时 DEC 仍在成功调用工具，完整队列缺口从 65 降到 64，未见退出。没有停止或修改其他会话的工作，也不能据此解释此前全部模型等待；后续若有解析超时或 OOM，应关联该资源快照。

18:16–18:19 DEC 再次出现 Codex Reconnecting 1/5、2/5。最后一次调用在 18:15:25，18:19:04 已恢复 ReviewCaseContext，期间未手动重启；进程持续存活，但该间隔不计为已完成的分析进展。后续仍需确认正式记录提交。18:14 的完整待办队列为 27 个 Case。

18:35 DEC 未完成退出：Codex 模型列表刷新与 pre-sampling compact 请求收到 HTTP 429 Too Many Requests，CLI 重试至 5/5 后退出码 1；UCAgent 达到 max_continue_fails=3 后退出。不是 pytest/波形解析崩溃。此时 stage_index=2、all_completed=false、is_agent_exit=true，无 report_manifest；已保留 37 个 Case 收据、36 个事件、38 个波形说明。需冷却后从既有检查点受控恢复，不重跑基线、不提高无限重试上限。已确认 verify_agent 从保存的 stage_index 恢复，原 Make 命令保存在 processes.json。watcher 随两个 Make 进程退出而结束，续跑时也需恢复监控进程。

18:40 冷却约五分钟后仅恢复 DEC：新 Make PID1960399，从保存的 stage_index=2 续跑，未重新执行 baseline；使用新的 Codex 会话，仍在模型列表与模型请求上立即返回 429，三次后端调用退出码均为 1，18:40:30 再次退出。说明失败不只发生于旧会话压缩。停止再次拉起，等待服务额度/限流恢复或用户提供可用模型/provider；不提高失败上限。原分析与状态备份 `dec-before-429-resume.tar.gz`（权限 0600），新日志 `raid_dec_top-after-429.log`，processes.json 保留 previous_attempt 链。ENC 已发布报告不受影响，DEC 仍没有最终报告。

续跑退出后，逐文件比较冷却前备份与当前 DEC 的 216 个非草稿 analysis 文件，内容哈希全部一致；当前两个 Make 进程均已结束。ENC all_completed=true 且报告 HTTP 200；DEC all_completed=false、stage_index=2、无 report_manifest。已向用户请求模型服务恢复信息或可用的 Codex 模型/provider，不索取 API Key，不继续重复启动。

## 配套修复的边界

LangChain transport 已补充 502/503/504 的有限重试，相关同步/异步回归通过；它不会重试工具执行，也不处理 Codex CLI 内部的网络请求。本次采用 Codex 后端，不能用本次运行证明 LangChain 重试解决了 Codex 断流。

早先发现的 assert 后场景未执行、波形不足和最终未定问题，需要本次逐 Case 取证后继续评估。测试收集恢复、波形文件能打开、报告能渲染，都不能证明这些问题已经解决。不能为获得确定结论而放宽断言或证据门禁。

## UCAgent 与 Swarm 共用插件的接入约定

以下是后续接入与验收要求，并非已经完成的平台改造。

1. **版本与环境**：每个任务固定核心/插件版本、Python 路径和输入哈希；源码运行也记录 commit 与未提交修改。插件 0.4.6 的波形归属修复依赖配套核心，不可只升级插件 wheel。
2. **隔离与寻址**：独立任务使用不同工作区、输出目录和 MCP 端口；后端显式连接该任务的地址。恢复任务先核实原工作区、版本与输入身份，再使用检查点，不能误接另一任务。
3. **测试身份**：全量收集与定向重跑必须使用一致的 pytest 根目录、Case node ID、解释器和输入。保留 invocation 报告，定向重跑不得覆盖全集基线统计。
4. **权限与发布**：输入副本只读，运行输出、检查点和发布目录可写。发布阶段单独记录失败，保留已完成的分析，避免分析成功但复制失败时丢失可恢复产物。历史只读目录回传问题仍需在平台入口复验。
5. **状态与超时**：区分 pytest 子进程执行、工具等待、模型响应等待、阶段校验、发布失败。`not_run` 在全量报告导入前不能解释为 pytest 未执行；进程存活也不代表持续进展。阶段超过 30 分钟先检查新产物、调用进度与真实缺口；重复相同错误应修复，持续有效分析可延长。
6. **完成与展示**：同时核实工作流全部完成、最终校验和报告清单有效。发布结果须可打开根因 HTML 与波形入口；平台按清单展示用户报告，运行日志和内部 JSON 作为排查材料。不得用退出码、模型声明或 pytest 通过数单独宣布 Bug Review 完成。

## 下一轮验收

- ENC、DEC 分别推进六阶段，记录阶段耗时、实际失败项、调查完成情况、确认/未定数量及具体未定原因。
- 抽查数字后缀 Case 的波形、invocation 与实际事件；检查 assert 失败处是否足以支撑当前结论，区分未执行场景与损坏文件。
- 对最终 ROOT 报告核实「根因—现象—Case」关联、预期/实际、真实信号名、RTL 来源，以及 HTTP 下 Surfer 的跳转与定位。
- 在 UCAgent 直接入口与 Swarm 入口分别验证双任务并发、定向复跑路径、断点恢复和发布失败恢复。本轮 Make 验证不能替代这两种入口的验收。
