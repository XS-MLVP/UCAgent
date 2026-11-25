
# 分阶段的验证工件与门禁

## 阶段顺序与已有工程

`toffee-ut:ut` 逐项保留原工作流的 20 个顶层职责和相应的子阶段。阶段不因缺文档而
合并：`runtime_options.ut_document_mode=provided` 时复核现有独立规格，`derive` 时只
写 `inferred`/`open` 候选，直到取得独立依据才可写 `confirmed`。已有 schema2 工程使用
原 `workspace.json`、`ucv.json`、fixture 和测试，不创建平行实现。
首次接手局部任务可先使用 `toffee-ut:adopt`，格式见 `Guide_Doc/ut-adoption.md`。
主流程默认仍为完整配置；显式 `ut_task` 与 `ut_task_stages` 只选择本次工作时，
不要求认证所有未涉及阶段，也不把它们算作完成。所选检查依赖未满足时报告并确认，
不要自动扩大任务或放松验收；只选子阶段不包含父阶段汇总工作。
未发现可逐物理行审阅的原始文档时，逐行映射子阶段保留但明确标记跳过，父阶段仍核对
功能点与检查点；补充文本规格后重新启动并执行该子阶段。PDF 可作为需求来源，但
不能按二进制字节生成物理文本行号；先提供可追溯的 `.md`、`.txt` 或 `.rst` 文本版本。

`runtime_options.ut_line_coverage` 默认 `true`，原生行覆盖必须有当前数据与逐缺口复核，
不会因为未采集而自动跳过。只有本次任务明确不要求时才显式关闭或在任务选择中不涉及。
`ut_reference_model`、`ut_mock_components`、`ut_human_env_spec_review` 和
`ut_human_env_review` 默认 `false`；如任务需要在运行前显式启用。所有阶段节点保留。
启用人工阶段时还需要实际人工审核，文本记录不代替批准。

职责与主要机器验收如下；每阶段都要运行 `Check`，修复诊断后才 `Complete`。Skill 可选，
不用它仍按 Guide_Doc、现有资料、代码和真实运行完成相同义务。

| 阶段 | 对应产物与实际验收 |
|---|---|
| 需求分析与规划 | `UTProject inspect/scaffold` 的输入盘点与可继续维护的设计规格 |
| DUT 功能理解 | 有来源的要求、已登记 DUT 环境、接口/位宽/时序缺口 |
| 功能规格分析及四个子阶段 | `behavior_groups`、`checkpoints`、原始文档物理行映射 |
| 规格细化 | 验证规格中完整的类别 × 结果域矩阵与场景处置 |
| 静态 Bug 分析 | `Guide_Doc/ut-static-review.md` 的每份 RTL 来源哈希及候选 |
| DUT 创建与 fixture | 真实 DUT 包、根 fixture、注册与生命周期；不认纯 Python 替身为 RTL |
| 覆盖组、覆盖点与批量检查 | 按 `Guide_Doc/ut-coverage.md` 建有语义的 bin 和观察路径 |
| 环境及子阶段 | Bundle、唯一驱动、监视器、env 和有区分性的独立自检；Mock/人工审核依任务启用 |
| 事务 API | 定义实际接受/完成而非 raw pins 的入口 |
| 模型与模型 fixture | 独立答案或性质、模型自检，不照抄实现 |
| API 功能测试 | 带真实原生 DUT 注册的定向结果 |
| 模板 | 每个 active 场景有测试入口，未实现模板不能意外 PASS |
| 全面测试与分批实现 | 真正执行比较和完成义务，保留原始 FAIL |
| 用例复核 | 逐需求回查断言、合法域、覆盖与实际执行 |
| 静态候选动态验证 | 每个候选给当前证据、缺证据或反证，不把静态怀疑称作动态缺陷 |
| 原生覆盖提升 | 有真实 LCOV 时审阅零命中、责任及补例；没有原件不能自称全覆盖 |
| 约束随机 | 适用时用真实 DUT 与可复现 seed；不适用给明确理由 |
| 全局复核 | 核对完整选择、问题分类、残余和同轮原件 |
| Bug 归档 | `UTProject summary` 生成报告；`rtl` 问题逐节点校验 WaveInfo 观察和根因分析 |

模板阶段可以保留显式失败入口；进入实现验收后，测试体仅含立即 `pytest.fail(...)`、
`assert False`、`raise AssertionError(...)`、`pass`、常量断言或 `return None`（可带说明文档）的已知空模板不能获得
场景实现或批次完成信用。即使 fixture 注册过 native DUT、原始结果是 FAIL，也须先
实际实现合法刺激、比较和完成义务，不能只更名错误消息或问题分类。已执行场景后
暴露的正确 FAIL 仍保留，不因本检查删断言或变成 PASS。该语法检查仅拒绝已知空体，
不证明其他测试已合法驱动、使用独立 oracle 或结清全部义务，仍需语义复核。
文件/函数/普通类命名沿用工程 `pytest.ini` 的规则；默认同时识别 `test_*.py`、
`*_test.py` 和 `test` 前缀函数。显式文件路径与目录采用相同实现检查，参数 ID 只作
数据处理；明确不收集的辅助类、`__test__ = False` 类及已重绑定的错误 API 不按空模板误报。

API 功能与随机阶段可接受 PASS，或保留经核验的原始 call 阶段 FAIL：节点须关联已声明
场景及其 confirmed 要求，在当前运行的 `docs/bugs/open/` 中有对应 rtl 问题，并按
`Guide_Doc/ut-results.md`、`Guide_Doc/ut-waveform.md` 为每个问题节点提供通过验证的
WaveInfo 收据和事件级分析。失败节点的实际 native class/source 还须匹配本 DUT 的
manifest 构建身份；仅写 rtl 分类或登记其他 native DUT 不足以通过。角色、随机场景
和 seed 条件不变，原始 FAIL 不改为 PASS。ERROR、INCOMPLETE、未确认或缺证据的 FAIL
不能使用此接受路径，已知设施错误须先修复；环境、模型和 Mock 自检仍须整体 PASS。
当前失败节点仍须通过已知空模板检查，问题归因记录不能替代场景实现；只核对本次节点，
不要求定向 API 验收前完成未选中的后续模板。
API 定向执行不额外要求完整回归、覆盖达标或关闭无关残余；最终交付门禁保持不变。

## 结构化设计规格

在既有 `kind: design` 块中增加 `behavior_groups` 与 `checkpoints`，不要另建运行前计划：

```yaml
behavior_groups:
  - id: G-ORDER
    behavior: 已接受的条目按合同顺序返回
    source: inputs/queue-interface.md#fifo
    responsibility: 本层 DUT；上层仲裁不在本次范围
    requirements: [Q-ORDER]
checkpoints:
  - id: C-ORDER
    requirement: Q-ORDER
    stimulus: 按合法握手提交不同身份的条目
    observation: 在有效出队握手沿保存输出快照
    comparison: 与独立输入 FIFO 按身份、payload 和顺序比较，并结清在途条目
```

这只是新增字段的形状；完整 `kind: design` 工件和 `basis` 状态见
`Guide_Doc/ut-contracts.md` 的完整设计规格示例。每个要求都需要行为归属和检查点，
源码行映射只能指向已声明的检查点。

已有非空输入文档时，在 `docs/spec/verification/<DUT>-line-map.md` 中按实际盘点路径
记录每条非空物理行；映射可指检查点 ID 或 `IGNORE` 并说明理由。一次区间不超过 100
物理行，内容变化后更新哈希与行号。没有输入文档时不制造行映射证据，仍须核对设计依据。

完整行映射示例（哈希仅说明格式；使用本次文件的真实 SHA-256）：

````markdown

# Queue 来源逐行映射

## 关联与残余

本次对 inputs/queue-interface.md 的非空物理行逐行归类；不存在的行为不作覆盖信用。

```yaml
kind: line_map
dut: Queue
sources:
  - path: inputs/queue-interface.md
    sha256: <source-current-sha256>
    lines:
      - start: 1
        end: 1
        checkpoint: C-ORDER
      - start: 2
        end: 2
        checkpoint: IGNORE
        reason: 仅为文档标题，不包含 DUT 行为或接口约束；有功能意义的标题须关联检查点
```
````

逐行脚本检查范围和哈希，人工仍须复核每行关联的语义；不能把一整份规范一律标 IGNORE。
机械清单、哈希和未映射行归工具，不用 Skill 代算。

## 主观复核的来源

人工审阅的环境、代码覆盖、约束随机和最终复核写到既有工程
`docs/reviews/<DUT>-stage-evidence.md`，不写 PASS 计数。每项引用真实工作区内
文件的当前 SHA-256。检查器核对引用、字节及同轮执行产物；文字不能代替真实运行。

以下是完整工件示例，哈希/观察内容是格式说明，必须换成当前实际文件的事实。只添加
本任务真正执行的阶段条目，未执行的阶段不可事后伪造。

````markdown

# Queue 分阶段复核证据

## 来源与范围

对当前源码、原生构建与运行进行复核。无法独立确认的要求保留残余。

```yaml
kind: stage_evidence
dut: Queue
reviews:
  line_coverage:
    run: results/<actual-run-id>
    observation: 当前 native 报告的零命中路径已逐项归因
    source: ut_project/docs/spec/verification/Queue.md
    sha256: <source-current-sha256>
    next_action: 补充合法激励并重跑 DUT；若合同排除则记录依据
    uncovered:
      - source: inputs/queue.sv
        line: 42
        status: gap
        reason: 合法的在途复位场景尚未执行，需先澄清复位合同
      - metric: toggle
        build: <actual-build-id>
        source: inputs/queue.sv
        line: 42
        group: {scope: source-line}
        status: gap
        reason: 该位置所有零点仍需按instance和bit核对，不能因属于同一行便统一豁免
```
````

同一条目可记录 `env_spec_review`、`env_review`、`line_coverage`、`random`、`review`。
人工复核阶段默认跳过，只有明确启用才需真实人工反馈；不得仅写评语即声称人工已批准。
`refine_tests` 还需写本轮 signed run 的 `run`、逐场景断言与完成性复核的 `observation`；
`review` 也需要当前 `run`。

随机阶段的 `random` 条目对每个已声明场景增加 `strategies`；`not-applicable` 需
`reason`，`tested` 需当前运行中带 `@pytest.mark.random` 的真实 DUT `nodeid`，且
原生 fixture 的已声明 seed 与请求值一致。声明值仍不能独自证明 native argv 生效。
原生覆盖阶段的 `line_coverage` 条目增加 `uncovered` 数组：本轮 LCOV 每个零计数
`SF:`/`DA:` 仍逐物理行记录 `source`、`line`、`status: gap/justified` 与独立 `reason`。
全部已采集 branch/toggle 零点也需处置，可用精确 `metric/point`，或显式
`metric/source/line/group: {scope: source-line}` 组。先用
`CoverageInfo(metric="toggle", view="groups")` 的分页目录取得真实零点数及 selector，
再按 `Guide_Doc/ut-coverage.md` 的完整合同和示例审阅，不需先将所有 point 读入上下文。
没有任何已采集零点时使用空数组，不能因为没有 LCOV 就填空数组冒充全覆盖。
`line_coverage.run` 必须对应当前运行；未复核、失效或仍为 `gap` 的必验缺口阻止该阶段
完成，并进入最终报告，不会通过“已经列出缺口”变成 PASS。使用 `CoverageInfo` 查询
实际计数及位置；多构建时所有条目必须用返回的精确 `build` 区分。任何空组、未知位置、
重复或交叠均无效。整组理由不足时保持 `gap` 或改为精确 point，不能凭同一行统一豁免。
