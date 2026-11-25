
# 功能与原生覆盖复盘

## 覆盖组和真实检查

读取 `Guide_Doc/ut-contracts.md` 的需求、行为类别、结果域矩阵和场景。按当前 DUT
实际复杂度在 `testbenches/<testbench>/coverage.py` 或同名包定义 `CoverGroupDef`、
`CoverPointDef`、`Bin`，必要时定义交叉。由 monitor 真实快照触发采样，不能在用例
定义时人为 sample 取得全绿；selftest 共享覆盖组显式 `capture=False`。

每个 bin 至少要给合法激励入口、真实采样沿和比较器/断言。功能 bin 的 reached、
场景标记、实际字段 checked 是三个不同的证据层级，不能互相替代。自检里反转预期
或输入映射的错误控制须在承诺的比较点失败，而不是仅 setup error。环境和 DUT 构建
要与本轮运行收据关联。

## 原生覆盖与不适用

运行 `RunToffee` 后用 `CoverageInfo()` 读取本轮已校验的原生覆盖；缺数据要报告未采集，
不能计 100%。逐个 `SF:` 的 `DA:<line>,<count>` 分析零命中点与适用配置。
未命中项属于缺用例、不可达、出本层责任或观测受限，分别给独立依据、承接、影响和
下一实验；补用例后重跑。LCOV 的 line 计数不自动证明 branch/toggle 或语义正确，
报告需区分原生行/分支覆盖与 Toffee 功能覆盖。

`CoverageInfo(metric="branch")` 和 `CoverageInfo(metric="toggle")` 分别查看独立计数。
未采集就是 `not_collected`，不是 0% 或 100%，也不从波形变化或物理行命中反推覆盖。
本阶段需处置全部已采集 metric 的零点，缺数据、缺复核和任何 `gap` 仍阻止阶段及必需的
最终覆盖验收；不是要求所有指标机械达到 100%。

## 原生覆盖补测的全量预检

先用 `RunToffee(targets=["项目相对路径::实际节点"])` 定向执行同一批受影响的精确节点；
在现有阶段日志列出预期新命中、受影响且不得回零的点，以及定向无法覆盖的范围。
此阶段请求全量时提交 `coverage_batch`：`baseline` 是改动前签名全量，`targeted` 是当前
输入的签名定向，`expect_hits` 是本批要验证的原精确零点，`retain_hits` 列出该定向
应保住的既有命中。两份回执须同 DUT、构建和请求 seed；定向必须覆盖实际原生 DUT
节点，且每个所选节点都通过。点用精确的 `metric/build/source/line/point`，物理行不带
`point`；整行组或无关的净增不能代替预期点。可从原生证据复制点的完整值，不改写身份。

预检只决定是否启动，不签发回执、不改变 `latest.json`、不替代阶段 Check。定向没命中时，
先换刺激、观察或判据；纯审阅复用全量。全量结束后仍按全部适用证据做双向差分，不能由定向
推断未执行节点无退化。没有可比基线或确实只能全量验证时，记录具体影响范围和原因，由
操作者决定是否在该工作流配置禁用 `runtime_options.ut_coverage_batch_preflight`；模型没有
跳过预检的调用参数。该配置不改变正式检查、签名或验收标准。

## 自主交接清单（不是覆盖验收）

已到达且启用原生覆盖阶段，或已到达交付阶段时，使用
`{OUT}/docs/reviews/{DUT}-handoff-inventory.md` 对账当前签名全量和余项。
先核对覆盖审阅、报告/缺口清单及设施首错，再登记；没有独立预期的点不可补造。
只改文档不跑仿真。`review_stale`、`selector_mismatch` 和未审零点应先复用签名回执修审阅。
下面是记录格式。保留 Markdown 的 ` ```yaml ` 开头和 ` ``` ` 结束围栏，不能只写裸 YAML；
路径以工作区为基准，哈希用实际文件的 SHA-256。
只有 `run` 例外：逐字复制签名回执里的项目相对路径 `results/...`，不要加输出目录前缀。

```yaml
kind: handoff_inventory
schema_version: 1
dut: Example
run: results/实际全量目录
native_review_sha256: 实际的-stage-evidence.md哈希
scope_review: 指明已复核的报告、用例/设施首错、覆盖缺口和范围
items:
  - id: missing-encoding
    state: external
    source: ut_project/docs/spec/design/Example.md#编码合同
    sha256: 该证据文件的实际哈希
    observation: 该消息的保留字段缺少独立定义
    owner: 协议规格负责人
    missing_input: 带版本号的字段和非法编码处置定义
    impact: 当前不能独立判断该消息的非法编码响应
    native_gaps: [[1, 2]]
```

- `id` 与本任务中唯一的 `StageWork` id 一致。`ready`（独立可做）和 `stalled`（验证侧无进展）都写 `next_action`；`done` 写 `result`、引用完成证据并与 `StageWork(done)` 对账；`external` 写具体 `owner/missing_input/impact`，与 `StageWork(human)` 对账。不把设施修复或“下一轮 UCA”作为外部依赖。
- `native_gaps` 是按**当前已哈希审阅**的 `uncovered` 原序过滤 `status: gap` 后的一基闭区间，不是 RTL 行号。范围可省略，但要交接时，每个现存组都须有明确出处和处置，区间不能重叠；`done` 不可承接现存 gap。无原生审阅时 `native_review_sha256: null`。清单只决定是否应继续处理，不改变任何覆盖状态。
- 原生审阅只证明缺口存在，不是这些组都需要外部输入的独立证据。给 `external` 项指定 `native_gaps` 时，引用能说明该项受哪个外部规格、权限或决定限制的独立材料，不把同一份原生审阅当作唯一的 `source`。把未构造的合法测试、验证环境缺功能和已确认需设计方修复的问题分别登记；不能用一个覆盖收尾决定承接混合缺口。
- 清单用当前回执及审阅核对，不凭 `StageWork(review)` 或报告销项。不确定如何处理且无具体外部输入时按验证侧停滞保留，不重复试同一路。`items: []` 只适用于确已复核且无余项的范围；保留历史清单/报告和旧回执，不改签。

## 原生零点选择器

最近一次如果是定向，或新运行未写出 `latest.json`，可用 `CoverageInfo(run="results/<run-id>")`
读取守卫指出的签名归档。它重新核对签名、产物、构建和当前输入，返回 `full_selection`，不会改写
`latest.json`。只能复用其实际覆盖数据；不能据此忽略更新的失败或中断，不能代替正式阶段检查。

`docs/spec` 是签名输入。最终用例、场景、判据或规格有必要变更时，先合并这些变更，再跑一次正式全量；
全量后把 run ID、实际计数、结果和附带复核写在 `docs/reviews` 或交付报告，不回填 `docs/spec`。
否则仅写入新 run ID 也会让该 run 过期，并形成「写回编号 → 回执过期 → 再跑」的循环。

先用 `CoverageInfo(metric="toggle", view="groups", offset=0, limit=50)` 分页查询
目录。每项包含精确 `metric/build/source/line`、真实 `zero_points` 数及 `selector`，
`groups_total`、`uncovered_total` 和 `next_offset` 分别表示目录项数、零点总数和下一页。
branch 同样查询；line 的目录项仍是一条物理行，不允许合并行范围。
`view="points"` 为默认精确零点视图，保留原始 `point`。可用精确 `build`、`source`、
`line` 筛选任一视图，例如 `CoverageInfo(metric="toggle", build="<actual-build-id>",
source="rtl/queue.sv", line=42)`；不支持 glob，也不规范化 source 拼写。
分页仅控制返回量，不改变计数或审阅范围。无有效 source/line 的目录项不提供组 selector，
仍可用精确 point 处置。
错误诊断中的超长身份仅显示有界预览，未复核总数不变；不要把诊断预览当作 selector，
精确身份仍从 points/groups 查询取得。预览不改变原始值的匹配或审阅范围。

`uncovered` 只使用以下两种表示，二者可混用但不能重叠：

- **精确点**：`source`、`line`、`status: gap/justified`、非空 `reason`；物理行省略
  `metric` 即表示 `line`。branch/toggle 必须带 `metric` 和工具原样返回的 `point`。
- **显式位置组**：仅 branch/toggle，复制目录的 `selector`，即 `metric`、`source`、
  正整数 `line`、`group: {scope: source-line}`，再写 `status` 和 `reason`。它仅覆盖
  当前 run、对应 build 和该位置的全部**零计数点**，不覆盖命中点或其他位置。

多构建时每条处置都必须带精确 `build`；单构建可省略。未知位置、空组、未知 selector
字段、范围、重复或 point/group 交叠都无效；遗漏零点仍未完成。组不能带 `point`。
同位置可能包含多个 instance、信号和 bit，不代表同一语义：**只有独立依据适用于整组
每一点才能统一 `justified`**；否则整组保持 `gap`，或删除该组改为逐 point 处置。
“blocked by known RTL bug”只能说明未解决缺口，不是 `justified` 理由。工具校验集合和
理由非空，不替项目批准理由、修改覆盖目标、原始百分比或硬件 verdict。

对上述分析使用 `Guide_Doc/ut-stages.md` 中的完整 `kind: stage_evidence` 工件示例，
在 `line_coverage` 条目里引用实际 LCOV 或当前规格，明确缺口与补法。原始计数由
`RunToffee`、汇总由 `UTProject(action="summary")` 生成，禁止手写 PASS 或改 manifest。

## 完整复核示例

下面是已完成逐缺口复核的工件形状。run、source 和 hash 必须使用本次实际原件；
justified 的理由必须由独立合同支持，不能为取得绿色结果临时缩小适用范围。

````markdown

# Queue 原生覆盖复核

## 当前观察与范围

本轮已查询实际原生计数。下面形状同时给出一个物理行和 branch/toggle 的位置组；
只有对应真实零集合存在且独立依据覆盖每一点时才能使用，未采集指标不得虚构条目。

```yaml
kind: stage_evidence
dut: Queue
reviews:
  line_coverage:
    run: results/<actual-run-id>
    source: inputs/queue-interface.md
    sha256: <actual-source-sha256>
    observation: 已核对当前计数、适用配置和实际零命中点，不以行覆盖代替行为检查
    next_action: 保留独立排除依据；后续配置或受验输入变化时重新复核
    uncovered:
      - source: rtl/queue.sv
        line: 42
        build: <actual-build-id>
        status: justified
        reason: 接口合同明确本配置禁用扩展响应，该行仅属于扩展模式；由扩展配置验证承接
      - metric: branch
        build: <actual-build-id>
        source: rtl/queue.sv
        line: 42
        group: {scope: source-line}
        status: justified
        reason: 已逐点核对该位置全部分支零点，均仅属合同禁用的扩展模式；其他配置另行验证
      - metric: toggle
        build: <actual-build-id>
        source: rtl/queue.sv
        line: 42
        group: {scope: source-line}
        status: justified
        reason: 已核对该位置所有instance和bit零点，独立合同规定本配置扩展输出恒定；扩展模式另行验证
```

## 剩余工作

本结论只说明本次覆盖复核完成，不替代 DUT 功能或根因验收。
````
