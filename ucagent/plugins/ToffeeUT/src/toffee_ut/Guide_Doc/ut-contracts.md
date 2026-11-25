
# 设计合同与验证场景

## 写在哪里、怎么确认

沿用输入盘点返回的 `design_spec` 和 `verification_spec` 路径。在 Markdown 正文中
分别维护一个 `kind: design`、`kind: verification` 的 YAML 块，`dut` 必须等于本次
DUT 名称。共享文档可有其他 DUT 的块，但本 DUT 的同类块只能有一份。

设计要求从适用规格、协议和上下游合同推导，再反查 RTL/端口遗漏；不能从已有测试
名反推需求全集。每条要求写前提、行为、观察和时间关系；正文补充参数、单位、身份、
复位、背压、取消边界、禁止副作用和责任移交。不适用与尚未验证必须分开。

每个输入事务/行为族写本层、出域（谁承接）或未证明的来源映射。行为族、需求 ID、场景、
参数实例与运行判定分开；旧 ID 都有归属不证明应有行为已全。观察点同时对照独立语义、
源码读写者和实际导出端口；消费者需要但端口装不下的字段保持未证明，关闭须有独立依据。

分阶段要求每个要求归到 `behavior_groups` 并关联 `checkpoints`；格式和逐行映射的完整
工件例子见 `Guide_Doc/ut-stages.md`。原有设计/验证合同块仍是同一份来源，不拆出平行计划。

`basis` 只允许：

- `confirmed`：独立依据已核对。source 指向启动时已提供且内容未变化的工作区输入文件
  （可加 `#条款`），先调用 `UTProject(action="inspect")`。HTTP(S) URL 或本轮自写文档
  不构成已确认来源；需要用户提供其本地资料并重启后再确认。仅有 RTL、端口形状或
  本份合同自身，不能作为 confirmed 的来源。
  RTL 头文件也不构成独立依据，改用文档名的符号链接不能改变实际来源身份。
- `inferred`：从实现推断的候选行为。保留实际来源及 `next_action`，不冒充 oracle。
- `open`：关键规则尚未确定。写明缺什么和下一确认动作；不为通过验收伪造依据。

资料与 RTL 冲突时保留两侧证据，不自动按 RTL 改平。关键 expected 无法独立确定
时请用户确认；其他有依据的部分可以继续实现。

## 完整设计规格示例

下例的 `inputs/queue-interface.md` 是本次实际提供的独立接口合同，不是插件生成的
证明。标题和章节可按业务调整，结构化字段和 ID 关联必须保持准确。

````markdown

# Queue 设计规格

## 范围与来源

本 DUT 负责顺序队列的入队和出队，不负责上层仲裁。输入和输出单位均为一个条目。
接口要求来自 inputs/queue-interface.md 的本次交付版本。

| 行为族 | 来源与本层责任 | 关联要求 | 尚未证明或上层承接 |
|---|---|---|---|
| 顺序入队/出队 | 独立 FIFO 合同；本层比较条目与顺序 | Q-ORDER | 上层仲裁不由本 DUT 证明 |
| 在途复位 | 本层可观察复位，但取消语义待负责人确认 | Q-RESET | 终态与生效沿未确认 |

```yaml
kind: design
dut: Queue
behavior_groups:
  - id: G-ORDER
    behavior: 已接受条目按 FIFO 顺序且只返回一次
    source: inputs/queue-interface.md#fifo
    responsibility: 本层 Queue；上层仲裁不属于本 DUT 的功能证据
    requirements: [Q-ORDER]
  - id: G-RESET
    behavior: 在途条目的复位取消边界
    source: pending-owner-confirmation
    responsibility: 本层 Queue 的复位响应；时序待接口负责人确认
    requirements: [Q-RESET]
requirements:
  - id: Q-ORDER
    statement: 已接受条目按 FIFO 顺序且每项恰好返回一次
    precondition: 不发生复位，输入满足有效和许可合同
    observation: 出队握手沿的 payload 与条目顺序
    timing: 仅在出队握手时消费；允许背压
    source: inputs/queue-interface.md#fifo
    basis: confirmed
  - id: Q-RESET
    statement: 复位取消哪些已接受条目尚未确认
    precondition: 有在途条目时发生复位
    observation: 复位前后出队与后续新条目
    timing: 复位生效沿待确认
    source: pending-owner-confirmation
    basis: open
    next_action: 向接口负责人确认复位生效沿和已接受条目的终态
checkpoints:
  - id: C-ORDER
    requirement: Q-ORDER
    stimulus: 合法握手接受相互可区分的不同条目
    observation: 在真实出队握手沿取得 payload、顺序与额外响应快照
    comparison: 与独立输入 FIFO 逐身份比较，再核对所有在途条目已结清
  - id: C-RESET
    requirement: Q-RESET
    stimulus: 合同确认后在有在途条目的状态施加复位
    observation: 待确认复位沿前后输出和新事务身份
    comparison: 待接口负责人确认终态，当前不得算作已完成检查
```

## 可观察性与剩余范围

payload 可从实际输出端口完整观察。Q-RESET 未确认，不计入通过范围；确认后补齐
复位期间与复位后新身份事务的检查，不能把队列清空现象当作正确性依据。
````

## 场景与完成义务

先按事务/历史类别 × 响应结果域划分行为矩阵，再实现定向边界和有区分性的组合。
每个场景有唯一 id 和一个已声明 requirement，写清合法 stimulus、独立 expected、
oracle 来源和 completion；正文补充观察点、禁止副作用、checker/模型位置及覆盖 bin。
需要多个需求时拆成明确关联的场景，不使用含义不明的“其他”兜底。

矩阵逐格区分 pass/fail/gap/na/out-of-domain；已运行的结果引用 run/nodeid，gap 写缺什么
与怎么补，na/出域写依据与承接，尚未分类的输入/字段/历史单列。结果域只取本合同适用项。
关键样本应让正确规则与代表性错误产生不同观察，不能仅靠用例标题声称覆盖优先级。
在验证规格的 `behavior_matrix` 中逐场景记录 `scenario`、`outcome` 和
`status: planned/gap/na/out-of-domain`；后面三种要有 `reason`，未执行的计划不标 PASS。
新增类别/结果域时，同步现有 coverage 实现和 tests 内的一致性自检；机械检查由代码完成，
通过只证明资料关联一致，不证明 oracle、实际比较或行为全集正确。

`status` 为 `active`、`deferred` 或 `out-of-domain`；后两种必须有非空 reason，说明
缺口、关闭条件和承接方。每条需求至少有一个场景或显式处置，至少有一个 active 场景。
排除不等于通过，inferred/open、未完成覆盖和排除范围会保持 INCOMPLETE。

## 完整验证规格示例

````markdown

# Queue 验证规格

## 行为划分

顺序行为分空队列、单条、连续条目与背压后恢复；本次先实现单条和背压顺序。
expected 来自输入历史和接口 FIFO 合同，不读取 DUT 内部队列作为答案。

| 行为族 × 结果域 | 正常完成 | 复位取消 |
|---|---|---|
| 顺序入队/出队 | gap：Q-ONE/Q-BACKPRESSURE 待接入真实运行与比较 | na：复位历史由下一行单列 |
| 在途复位 | gap：复位后新条目的顺序须在合同确认后补例 | gap：Q-RESET-OUTSTANDING 待确认终态与生效沿 |

当前示例不包含其他上游事务族，不能据此声明完整范围；新增项必须重新分类，而非放入
“其他”。一致性自检对账行为族、结果域、场景 ID 及实际 collection，不以自检 PASS 代替仿真。

```yaml
kind: verification
dut: Queue
behavior_matrix:
  - scenario: Q-ONE
    outcome: 单条正常完成
    status: planned
  - scenario: Q-BACKPRESSURE
    outcome: 背压后的有序完成
    status: planned
  - scenario: Q-RESET-OUTSTANDING
    outcome: 在途复位取消
    status: gap
    reason: 复位生效沿和已接受条目的终态未确认；取得接口合同后补定向比较
scenarios:
  - id: Q-ONE
    requirement: Q-ORDER
    stimulus: 合法复位后接受一个非零条目，在允许出队时读取
    expected: 恰好返回该条目，字段逐项相同，无额外响应
    oracle: 输入条目历史与 inputs/queue-interface.md#fifo
    completion: 观察一次真实出队并比较，随后检查无未偿还条目
    status: active
  - id: Q-BACKPRESSURE
    requirement: Q-ORDER
    stimulus: 接受多条不同 payload，出队背压后恢复
    expected: 按原顺序返回全部条目，无重复或丢失
    oracle: 独立软件 FIFO 与已确认的有效条件
    completion: 已接受与已比较条目逐身份对账，有限观察窗口内无额外响应
    status: active
  - id: Q-RESET-OUTSTANDING
    requirement: Q-RESET
    stimulus: 在途条目存在时施加复位
    expected: 等待复位取消合同确认后定义
    oracle: 尚无独立依据
    completion: 确认合同并补充成对实验后才能关闭
    status: deferred
    reason: 接口负责人需确认生效沿和条目终态；本轮不声称已验证该行为
```

## 实现与检查

tests/test_response.py 调用环境事务 API。checker 使用独立输入历史逐项比较；覆盖
组统计实际观察且已比较的 single/backpressure，场景标签不代替采样。

## 退出与残余

全部 active 场景应真实执行，保留原生 DUT 和覆盖产物。Q-RESET-OUTSTANDING 在确认
前保持未证明；结果不能写为整个 Queue 已通过。
````

实现测试时使用 `@pytest.mark.scenario("Q-ONE")` 关联 ID。标签只能声明关联；
真实比较与完成性由环境和用例执行，不能靠加标签或覆盖命中创造验证信用。
