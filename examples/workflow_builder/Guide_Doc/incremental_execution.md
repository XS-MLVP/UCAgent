# 增量工作流执行契约

## 目的

本文是增量 Agent 的执行契约。修复开始前必须先按
`Guide_Doc/incremental_workflow_discovery.md` 阅读最小架构基线，并形成
`tmp/inc_runs/current.json` 指向的本轮 context 报告。详细评估规则仍保存在
`Guide_Doc/incremental_evaluation.md`，由 Checker 静态检查；评估报告不能代替对正式
配置和文档原文的阅读。受批准项影响的源码、规格和测试在后续计划与部署阶段深入读取。

## 修复前认知基线

1. 每次增量运行都必须重新执行 `understand_generated_workflow`，不得因存在旧候选跳过。
2. 完整读取固定的主配置、增量配置、workflow spec、验收规则和环境安装入口。
3. 只读取 README、输入输出、步骤检查及两份开发者文档，不递归读取全部 `Guide_Doc/` 与 `docs/`。
4. 只读取 `res/common.json`（和存在时的 `res/index.json`），不在此时加载全部用户资源或输入 manifest。
5. 从中心规范、配置和开发者文档了解工具及 Checker 的总体职责，不逐个审查源码、spec 或测试。
6. 为每个核心文件记录当前 SHA256、简要作用、关键契约和必要同步关系。
7. 受批准项影响的源码、规格、绑定、测试、必要文档片段和相关用户资源只在该批准批次部署前完整读取。
8. 认知阶段只输出理解报告，不创建候选、不部署文件、不改变评估或审批状态。
9. 后续计划、部署和验证阶段都必须读取同一份已通过检查的认知报告。
10. finding 只说明观察到的问题，不是修改文件清单；计划阶段只切分小批次，实际影响面在各批次深读时推导。
11. 使用 `IncrementalContextInventory` 的 initialize、update、validate 操作原子维护认知报告，禁止直接编辑 JSON，也禁止用 RunTestCases 执行临时哈希脚本。
12. 认知阶段不得运行 make、pytest、Verilator、业务工具或其他行为测试；这些只属于验证阶段。

## 授权

1. 使用 `StructuredJsonStore` 读取 `eval/approvals.json`。
2. 只接受 `decision=approved` 且来源指纹仍与当前 finding 或用户条目一致的决定。
3. `rejected`、`deferred`、撤回条目、已解决 finding 和过期指纹都不授权修改。
4. 计划记录批准 ID、来源 ID、目标组件和简短修改意图，不复制 finding 全文。
5. 没有有效批准时记录 `no_change`，不得自行寻找其他问题修改。

## 计划报告

1. `eval/incremental_report.json` 只能通过 `StructuredJsonStore` 修改。
2. 禁止使用 `EditTextFile` 或 `ReplaceStringInFile` 直接修改任何 `eval/*.json`。
3. 计划 run 使用 `tmp/inc_runs/current.json` 中已经分配的唯一 `run_id`，禁止另造报告 run_id。
4. 摘要记录 approved、deferred、rejected 数量和候选目录。
5. 详细批准内容保留在 `eval/approvals.json`，报告只引用 ID。
6. 计划必须列出全部当前有效 `decision=approved` 的 ID，并为每个 ID 分配一个批次或明确同批关联项；不得只记录第一个批准项后结束。报告必须同时记录 `approved_total`、`planned_approval_ids` 和尚未部署的 ID，便于部署阶段逐项出队。
7. 写入完成后立即结束计划阶段，不在同一阶段创建全部候选。

## 运行、批次与尝试隔离

1. `make run_inc` 和 `make run_inc_cli` 每次启动都会创建唯一 `run_id`，并写入 `tmp/inc_runs/current.json`。
2. 本轮关键文件统一位于 `tmp/inc_runs/<run_id>/`；认知报告放在 `context/`，命令回执放在 `checks/`，版本备份放在 `history/`。
3. 每个批准批次必须有稳定 `batch_id`，每次候选修复必须有递增且唯一的 `attempt_id`。
4. 候选必须位于 `tmp/inc_runs/<run_id>/batches/<batch_id>/attempts/<attempt_id>/candidate/`，部署器拒绝其他运行、批次或尝试的 source。
5. 同一次尝试可以同步部署多个关联文件，但不同批次和不同尝试不得共享候选目录。
6. 创建新尝试时重新读取正式目标当前全文，并调用 `IncrementalCandidateStager` 按相对路径把所有已有目标逐字节暂存到本次 candidate；禁止用普通 `CopyFile` 跨越写边界，也禁止从摘要、旧候选或 YAML 解析结果重新生成完整文件。
7. YAML 使用解析器验证，Python 使用语法检查或受控确定性检查验证，所有输出都保存在本轮目录。
8. 新一轮运行不删除历史运行目录；历史只能由用户通过版本管理界面或专用接口显式删除。

## 候选同步

1. 已存在的正式文件必须先使用 `IncrementalCandidateStager(workflow_root, run_id, batch_id, attempt_id, files)` 初始化；返回的每条记录包含正式来源、候选路径、SHA256 和字节数，`candidate_staging.json` 是本次精确复制回执。
2. `files` 只能使用相对 `workflow_root` 的规范化具体文件路径；目录、绝对路径、`..`、符号链接、重复路径、非当前 run 和隐式覆盖都会被拒绝。候选已经被修改时，不得用 `overwrite=true` 掩盖修改，应创建新的 attempt；只有明确放弃当前候选并重新从正式文件开始时才可显式覆盖。
3. 暂存完成后先比较候选回执 SHA256 与正式文件，再在候选副本上做最小修改。不得重排无关 YAML、截断长文本、移动顶层字段或用新的序列化风格重写整份配置。
4. 工具修改需要同步工具源码、注册清单、直接测试和开发者文档中受影响部分。
5. Checker 修改需要同步中心定义、Checker 源码、阶段绑定、正反 fixture 和开发者文档。
6. 流程配置修改需要同步 `.workflow/workflow_spec.yaml`、`config.yaml`、`config/inc.yaml` 和相关指南；若已批准 finding 的 recommendation 或计划同步类别明确包含这些必要契约，它们属于同一批准范围，不得误报为越权。
7. 环境修改需要同步 Makefile、setup.py、shell、schema 或 requirements 中实际受影响部分。
8. 不要为了形式完整而修改与批准项无关的文件。
9. reference_files 和 output_files 只能包含具体文件，不能包含目录或不确定路径。
10. `.workflow/workflow_spec.yaml` 是阶段 reference_files、output_files 和 Checker
   绑定的权威来源；最终 `config.yaml` 与 `config/inc.yaml` 的同名阶段必须逐字段一致。
11. 修改上述阶段契约时，权威规范和实际运行配置必须进入同一个部署批次。禁止先部署
   workflow_spec、等待后续批次再补 config，因为中间状态已经是不可运行的正式版本。
12. UCAgent 先替换内建 `OUT/DUT/Version`，再读取并替换 `template_overwrite`。
   自定义变量可以包含内建变量，但不能继续引用另一个自定义变量；组合路径时还要确认
   同一内建变量没有被别名和调用位置重复加入。

## 部署

1. 正式工作流文件只能通过 `IncrementalChangeDeployer` 从候选目录部署。
2. 普通文件工具只允许写 `tmp/`；即使尝试写 `workflow/` 也必须被边界拒绝。正式文件到候选目录的精确初始化只能使用 `IncrementalCandidateStager`。
3. 顶层 `approval_ids` 列出本批部署使用的全部当前批准记录 ID。
4. 每个 mapping 必须包含 `source`、`target`、`approval_ids` 和 `rationale`。
5. mapping 的 approval_ids 只能引用直接授权该文件的批准。
6. rationale 至少二十字符，说明该文件修改与批准需求的直接关系。
7. 顶层每个批准必须至少被一个 mapping 使用。
8. source 必须位于本轮、本批、本次 attempt 的 candidate 目录，target 必须相对 `workflow/`。
9. 一次工具调用参数较大时可以按组件分成多个 change_id 部署。
10. 每个批次只引用该批文件实际使用的批准，禁止把全部批准机械附加到每个文件。
11. 部署工具返回成功后记录该批已覆盖的 approval_ids，并继续处理计划队列中的下一批准批次；单批成功不表示当前增量运行完成。
12. 在进入验证阶段前，必须运行 `IncrementalApprovalChecker(require_all_current=true)`。它会比较当前全部有效批准 ID 与 `eval/applied_changes.json` 的逐文件授权记录；任何未覆盖 ID 都必须继续生成和部署对应候选，禁止以“后续处理”“无关文件”或单批成功结束阶段。
13. 新部署会保存 `approval_provenance`，冻结本次部署使用的来源、指纹和决定时间。
14. 新版本覆盖旧版本时会保存 `supersedes.repair_id` 和旧 SHA256，禁止 Agent 自行填写。
15. 部署版本的历史 review 状态不参与覆盖授权；同一有效批准范围内允许连续修复同一目标。
16. 正式文件哈希漂移时先归档当前真实内容，在 `supersedes` 中记录记录哈希、被替换哈希和漂移标志，再执行原子覆盖。
17. 每次覆盖使用新的 attempt_id 和 change_id；不得覆盖、删除或改写已有部署记录。

## 历史版本与恢复

1. 每次部署正式文件前，`IncrementalChangeDeployer` 必须先把目标旧内容保存到 `tmp/inc_runs/<run_id>/history/<change_id>/before/<target>`；旧版 `tmp/change_history/` 继续兼容恢复。
2. `eval/applied_changes.json` 的逐文件记录必须保存 `backup.existed`、`backup.path`、`backup.sha256` 和 `backup.created_at`。
3. 目标在部署前不存在时记录 `backup.existed=false`，不得伪造可以恢复的旧文件。
4. 多文件部署必须先完成全部候选预检，再逐文件归档和替换；任一替换或清单写入失败时必须恢复已经替换的目标。
5. 历史版本只能通过图形界面或受控历史 API 恢复、删除，Agent 和普通文件工具不得直接编辑受保护 history 目录或相关 JSON 字段。
6. 恢复旧版本前必须再次归档当前正式文件，并产生新的 `operation=restore` 部署记录，保证恢复操作本身仍可反向恢复。
7. 恢复需要用户填写理由，记录授权时间、来源修复 ID 和来源 SHA256；历史文件缺失、损坏或哈希不匹配时必须拒绝恢复。
8. 删除历史版本需要用户填写理由。删除只移除所选归档文件，必须永久保留原路径、SHA256、删除时间和删除理由。
9. `tmp/inc_runs/` 与旧版 `tmp/change_history/` 是受保护历史区域；普通 `make clean`、下一轮 inc 和候选清理不得删除。只有用户显式版本删除操作可以移除可恢复内容。
10. 本功能启用前已完成的部署没有替换前快照，只能显示“没有旧版本”，不得用当前文件或候选文件冒充历史版本。
11. `approval_provenance` 表示部署发生时的授权事实，后续评估重跑不会使历史部署变成未授权。
12. `approval_is_current` 只用于决定新的部署能否发生，不用于否定已经完成的历史部署。
13. 新部署的 `supersedes` 只建立版本链，不删除旧记录、旧审批快照或旧文件备份。

## 修改授权与版本管理

1. `eval/approvals.json` 只回答是否授权处理原 finding 或用户建议，是正式修改范围的唯一人工门禁。
2. 部署后的文件版本不再要求批准、拒绝或暂缓；历史 `review` 字段仅为兼容展示，绝不能阻塞后继尝试。
3. 每条部署记录必须绑定 run_id、batch_id、attempt_id、目标路径、正式 SHA256、批准来源和替换前备份。
4. 控制台按版本链展示当前、漂移、缺失和已被替代状态，并允许用户恢复或显式删除旧版本。
5. 恢复前必须备份当前版本，使恢复操作本身也能撤销；恢复不改变原 finding 的批准状态。
6. 最终修复是否成立由正式 `make check` 和重新运行对应评估工作流判断，不由中间版本人工评价判断。

## 上下文控制

1. 认知阶段只完整读取固定最小基线，并把理解压缩到结构化报告；禁止递归读取目录补充“安全感”。
2. 计划阶段不得深读所有批准项；只按批准项或紧密组件组形成轻量批次清单。
3. 部署阶段选择一个批次后才读取该批的当前源码、spec、绑定、测试、必要文档片段和相关资源，并在读完该批后立即创建第一份候选。
4. 每个批次完成候选和部署后，保留 SHA256、批准来源和最小同步结论；后续批次不得重新载入无关源码或全文报告。
5. 每个阶段完成当前职责后立即调用 `Complete`，不要在一次循环包办后续阶段。
6. 候选数量较多时按 tools、checkers、flow、env 分批部署；每个批次只使用直接相关 approval_ids。
7. 每批部署后保留结构化清单，不在对话中回显大段源码或 JSON。
8. 发现上下文接近限制时先完成当前可验证批次，禁止省略该批必读文件或伪造已阅读记录。

## 验证

1. 只验证已经部署到 `workflow/` 的文件，不把候选副本当最终产物。
2. 必须使用 `EvaluationCommandRunner(workflow_root='workflow', command='make_check')`
   在正式工作流根目录执行完整 `make check`，并保存真实 `argv`、`returncode`、
   `stdout_tail` 和 `stderr_tail`。不得根据部分 PASS 行推断命令成功。
3. 先调用 `StaticEvaluationAudit`，再检查 Python 语法、YAML 解析、注册一致性、
   路径契约和受影响的直接测试。
4. 不启动 UCAgent 子工作流。
5. `incremental_report` 必须包含十个规定的 `INC-*` check。
6. 没有变更不等于没有验证。已部署且哈希未漂移的 `no_change` 必须重新核验十项
   INC 检查并写为 `passed`；只有客观条件导致无法执行时才能使用 `skipped`。
7. 干净的 no_change 复核全部通过时报告为 passed；任何检查失败或存在确定性
   critical/high finding 时报告为 failed。
7.1 在写入 passed 前，必须再次运行 `IncrementalApprovalChecker(require_all_current=true)`；当前有效批准集合与逐文件部署记录必须完全覆盖。报告证据必须列出 `current_approved_ids`、`covered_approval_ids` 和空的未覆盖集合，不能只报告单个 change_id。
8. 部署成功只能标记 `fix_applied_pending_recheck`。
9. 不得直接把原 finding 标记为 resolved。
10. 完成后必须重新运行对应 tools、checkers、flow 或 env 评估确认问题是否真正修复。
11. 静态审计当前仍能复现的每条问题必须分别记录为 `status=open`，并逐条保存精确
    rule_id、path 和 location。只有本轮确实部署且该问题已不再复现时，相关旧 finding
    才能标记 `fix_applied_pending_recheck`。
12. `make check` 的 `returncode` 只有等于 `0` 才算通过。任何非零返回码、超时、
    命令工具错误或缺失返回码都必须使 `INC-REGRESSION`、`INC-RECHECK` 和整体增量
    验收失败；即使其余测试全部通过，也不得写成 `passed` 或 `passed_with_findings`。
13. 当前批准范围覆盖失败原因时，必须根据完整错误输出修复候选、通过部署器更新正式
    文件并重新运行 `make check`，直到返回码为零。失败原因超出批准范围时不得越权
    修复，但必须保留失败状态并生成待用户批准的新 finding。
14. “预存问题”“测试期望问题”“低严重程度”只能解释问题来源，不能豁免全量门禁。
    禁止通过降低 finding 严重程度或者把失败测试描述为无回归来伪造通过。

## 强制全量检查闭环

增量流程的成功条件不是“本轮改动看起来合理”，而是部署后的正式工作流保持可验证。
因此每次部署完成后都必须运行完整 `make check`。第一次返回非零时，先区分失败是否由
本轮修改引入、是否为批准项要求修复的旧问题，以及是否存在测试与实现契约不一致。
这种分类只决定下一步修改权限，不改变命令失败的事实。

如果失败属于当前批准范围，读取失败目标、用例名、期望值、实际值和输出尾部，回到
对应源码、规格、fixture、配置或 Checker 形成候选。修改测试期望必须能追溯到用户需求、
工具契约或权威格式规范；禁止仅因为现有实现返回某个值就把期望改成该值。部署候选后
以新的 attempt_id 重新执行静态审计、完整 `make check` 和受影响专项测试。只要失败仍在
当前批准范围内，就持续修复，不设置固定重试次数，也不得因旧版本未验收而停止。

如果失败不在当前批准范围，增量 Agent 必须停止扩展修改范围，在报告中记录独立 open
finding、真实返回码、复现命令和建议审批范围。此时整体状态必须为 failed，留给用户
批准后再次运行增量流程。summary 必须记录 `blocking_reason_code=outside_approved_scope`
和产生该结论的 `make_check_receipt`，随后允许 Complete 结束本轮，避免在外部状态未变化时重复检查。命令无法启动、依赖缺失等外部阻塞使用 `external_execution_block`。`passed_with_findings` 仅适用于所有强制命令均返回零、但仍有
不影响门禁的 medium/low 观察项，绝不适用于真实测试失败。

最终阶段还注册 `IncrementalRegressionChecker` 作为独立门禁。`EvaluationCommandRunner`
会把真实返回码、输出和正式工作流指纹写入本轮 checks 目录；Checker 重新计算当前指纹并
验证回执。文件变化后旧回执立即失效，因此无需对同一版本重复执行一次 `make check`。

## 常见问题：语法和单元测试通过但工作流仍不可运行

`make check` 主要确认 YAML 能解析、源码可导入以及各工具和 Checker 的独立样例通过。
它不能单独证明运行时变量能正确展开，也不能证明中心 workflow_spec 已同步到实际
config。典型错误包括把 `INPUT_ROOT` 定义成 `input/{DUT}` 后又使用
`{INPUT_ROOT}/{DUT}`，以及只在 workflow_spec 中加入输出 Checker、却遗漏
config.yaml 的实际阶段绑定。

验证阶段必须读取本轮 `checks/incremental-static-audit.json`。对于变量，使用 UCAgent
真实的“内建变量一次、自定义变量一次”两步模型展开整个字符串，检查结果中是否仍有
`{NAME}`，并检查路径中同一 `DUT/OUT` 是否因别名组合出现多次；对于阶段契约，按稳定
阶段名比较 reference_files、output_files、Checker 名称和 args。发现差异时不能用
“make check 已通过”覆盖结论，必须把静态 rule_id、文件、字段位置、期望值和实际值
写入增量报告，并将相关检查标记为 failed。

## 常见问题：no_change 为什么仍然需要完整检查

`applied_changes.json` 的 SHA256 只能证明正式文件等于某次部署内容，不能证明那次内容
符合用户需求。旧版本部署器可能只做语法检查，错误也会被稳定记录。因此 no_change
只能表示本轮无需再次替换文件，不能表示无需重新验证。若静态语义审计和确定性测试
全部通过，十项检查写 passed；若发现旧修复仍有问题，报告 failed 并等待用户在评审
界面批准新的修复，不得绕过授权直接覆盖正式文件。

## 常见问题：正式文件在运行时显示只读

增量工作流将普通文件工具的写入范围限制在 `tmp/`。UCAgent 启动阶段可能把
`workflow/config.yaml`、`workflow/Makefile` 等正式文件临时设置为只读，这是阻止
Agent 绕过审批直接改动正式产物的运行期保护，不代表批准的修改不能部署。

`IncrementalChangeDeployer` 必须使用同目录临时文件和原子替换部署候选，不能直接
打开只读目标覆写，也不能通过把 `workflow/` 加入普通 `write_dirs` 来解决权限错误。
原子替换前仍须完成批准来源、逐文件授权、候选路径和语法预检，任何一项失败都不得
改变目标。`make run_inc` 和 `make run_inc_cli` 必须在启动前清理上次异常退出遗留的
只读位，并通过退出 trap 在正常结束、失败或 Ctrl-C 后恢复 `workflow/` 的用户写权限。
若运行结束后文件仍为 `0444`，先确认是否绕过 Makefile 直接启动了 UCAgent，再检查
退出 trap 是否执行；不得用放宽审批边界作为长期修复。

## 常见问题：重新评估后历史部署为什么显示未授权

这是把当前批准有效性和历史授权证据混为一谈造成的。finding 在新评估 run 中可能改变
指纹、编号或被确认已经消失，因此旧 approval 不应再授权一次新的修改；但它仍然证明
旧部署发生时用户曾明确授权。新部署通过 `approval_provenance` 保存不可变快照，
`IncrementalApprovalChecker` 对历史条目检查该快照，而不是要求来源 finding 仍是最新。
启用快照前的 legacy 条目，只要原 approval 记录仍存在、decision=approved、来源字段
完整并且逐文件引用合理，就作为历史凭证接受。这个兼容规则不能用于新部署。

## 常见问题：同一批准范围为什么可以连续覆盖

人工批准约束的是可以处理的问题范围，不是中间实现版本。只要 `make check` 仍能在该范围
内定位失败，Agent 就应创建新的 attempt 并继续修复。部署器每次都会保存被替换的真实字节、
SHA256、批准快照和 supersedes 链，因此连续覆盖不会丢失旧版本。若失败已经超出原批准范围，
则必须生成新 finding 等待批准，不能借连续修复机制扩大修改权限。
