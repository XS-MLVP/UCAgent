---
name: package-layout
description: 在 testbenches 的六职责中组织事务、端口绑定、唯一驱动、逐拍监视、独立比较和 agent API；先复用 Toffee，再用调用链与负对照验收，不把目录或别名整理当作事务抽象完成。
metadata:
  source: ucv4xs/skills/execution/package-layout.md
  source_sha256: 3fe43f6db32ae35614e1a70722e032105c32a79d4e3a3e3b207f54ffe4acfd59
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 如何组织验证包的 driver/monitor 分层

## 何时使用、准备什么

新建验证工程、把直接操作引脚的用例整理为可复用环境，或复核驱动/观察是否混在测试时
使用。输入是真实实例层次、生成端口、producer/consumer 合同及现有工程，不必先有完整模型。

分层要回答三件事：测试能否只描述事务、同一引脚是否只有一个驱动者、观察是否按合同
持续发生且比较有独立依据。只建目录仍然没有解决这些问题。

## 先确认框架能做什么

| 需求 | 优先复用 | 工程仍负责 |
|---|---|---|
| 引脚绑定与方向检查 | Bundle、Bundle.bind、SignalDriver | 真实端口名、宽度、idle |
| 单/多周期输入与重叠 | SyncSingleCycleDriver、SyncMultiCycleDriver、AsyncDriver 等 | 接受条件、阶段、撤销 |
| 输出采样 | SamplingMonitor 的 lossless/latest、溢出诊断及事件时间 | 有效条件、解码、不可变快照 |
| 装配与关联比较 | Agent、Scoreboard 的 FIFO/key/固定延迟关联 | 参考模型、比较规则与多接口语义 |
| 功能覆盖 | CoverGroupDef、CoverPointDef、CrossDef | 实际采样语义、bin 和目标 |
| 原生覆盖收集 | toffee run；工作流内由 RunToffee 调用 | 实际构建、RTL 映射与报告口径 |
| 事务类型、合法域、独立答案 | 工程合同与实现 | 不由框架猜测 |

先核对当前版本的公开接口；缺能力才自建，并在工程 docs 写清不适用项、保留/缺少的行为、
接受事件/丢拍/覆盖收集差异及关闭条件。不要无说明地重造调度器、队列或 scoreboard。

## 目录与归属

骨架和路径检查交给 `UTProject`；单文件/同名包按复杂度选择，不创建空壳：

```text
<project>/
├── __init__.py
├── conftest.py
├── pytest.ini
├── workspace.json
├── testbenches/<testbench>/
│   ├── __init__.py
│   ├── README.md
│   ├── transactions.py
│   ├── env/                 # agent、bundle、driver、monitor 按需拆分
│   ├── model.py
│   ├── checker.py
│   ├── coverage.py
│   └── tests/               # 场景、自检、fixtures.py 或参数化插件
├── testbenches/shared/      # 真正跨 DUT 使用时才建立，同用六职责
├── tools/                  # 离线命令，按需
└── docs/spec/ 与 docs/bugs/
```

已有 ucv4xs 工程还保留 ucv.json、suites.* 命名空间和配方。参数化实例用 workspace.json
显式登记 testbench，父级组合场景归父 DUT，不复制子模块编码。ROOT 来自项目包，不猜移动后
parents 深度。shared 不登记为 DUT，没有自己的 top/原生库；其实现不反向依赖具体 DUT 或
工程 tools，shared/tests 可检查集成引用。更多路径规则见 `Guide_Doc/ut-project.md`。

## 运行职责

| 层 | 职责 | 禁止混淆 |
|---|---|---|
| harness / fixture | 原生 DUT、时钟、资源所有权和收尾 | 构建成功不等于功能正确 |
| transactions | 单位、身份、必需字段、合法域与互斥校验 | 不从 RTL 内部状态反推答案 |
| bundle | 通道到真实端口的映射、缺项报错 | 不把物理字符串散在测试或默认补零 |
| driver | claim、发射、保持、撤销、重试 | 不能用 DUT 结果反推请求/预期；协议 ready 的读取不受此禁令影响 |
| monitor | 指定相位的公开输出和不可变快照 | 不驱动引脚，不在消费时才读 live DUT |
| checker | 独立 expected、性质、逐身份义务 | reached 不等于 checked |
| agent / env | 装配并公开事务方法和必要精确对齐接口 | 不是原生 set/Step 的同名转发 |
| tests | 场景与事务级断言 | 不复制编码、直接驱动或修改私有模型 |

## 操作步骤

1. 为 producer 请求和可观察响应定义事务，注明单位、字段宽度、有效条件、身份和终态。
   构造器/fixture 边界拒绝非法编码和缺字段。
2. 按通道建立端口组，不按用例分组；被生成器裁掉的端口单独登记，不静默补 0。
3. 由 driver 统一发射、保持和撤销。按合同撤销整个会生效的 payload；只清 valid 可能
   留下 override/flag 的副作用，不能一概假定 valid 门控所有字段。
4. monitor 在合同采样点抓取全部字段。用有效条件 trigger 控制哪些事件交付；不要假定
   SamplingMonitor 的 capture 返回 None 就会自动过滤事务。负对照也走同一观察/解码路径。
5. 连接独立 oracle/checker；内部信号可做身份和不变量证据，但不能自证 payload expected。
6. agent 收口为事务、快照和有合同依据的精确对齐接口，不能把整套场景/断言藏进不透明调用。
7. 工程根 conftest.py 唯一注册 fixtures/插件；DUT 专用实现和参数生成归其 tests，真正
   通用插件归 shared/env。默认逐例独立初态；复用、工厂或不同配置需显式声明，不能按测试
   文件路径偷偷换模型，也不能按 fixture 函数数量推导 DUT 覆盖。
8. 加合法与错误控制：重复 claim、缺端口、未知键、错 expected、错序/错范围都应在约定
   边界失败。自检标 selftest，辅助组 capture=False，不计硬件功能信用。

## 产出和验收

产出职责表、双向事务/端口映射、所有权清单、driver 发射/保持/撤销时序、monitor 相位/有效
域、独立 expected 和负对照节点，以及静态筛查和真实运行结果。

- 功能测试仅调用公开事务 API；直接 agent.ports、私有 driver、物理别名、raw_dut/xport
  或手工编码仍是基础设施耦合。不可改个名字、加转发壳或改标 selftest 来取绿。
- 静态字符串筛查交给已有审计/搜索工具；零命中不证明采样、所有权和 oracle 已合格，
  普通不可变事务的 value 也不能机械误判为引脚访问。
- 即使是零沿 persistent level 输入，也须遵循真实 signal claim；set 不表示已接受。
- 同引脚重复驱动在边界失败；错误 expected 被比较器拒绝；关闭 monitor 后依赖它的
  功能场景不得静默通过。PASS 能追到真实刺激、采样、比较，FAIL 能归属到具体层。
- 不在控制进程的 pytest_configure 中切 cwd。若执行期需要隔离输出，验证串行/xdist 的
  有序 collection、实际执行和 cwd 恢复；保留模型选择、fixture 注册及原始判定。

## 常见坑与案例

特别复核：只清 valid、不同来源寄存级不同、快照被下次覆盖、多通道 ready 互相清零、内部
数据当答案、根 fixture 接线不全、用路径选择模型。保持有界历史，不用无限日志掩盖漏采。

源案例位置（历史经验，非本轮结果）：

- `ucv4xs/suites/frontend/ftq/docs/spec/verification/architecture.md`。
- `ucv4xs/suites/frontend/bpu/testbenches/ras/` 与 `ubtb/`。
- `ucv4xs/docs/lessons/ifu-harness-integrity-20261029.md`。
- `ucv4xs/docs/history/transaction-goal-component-boundary-20261102.json` 与
  `transaction-goal-icache-level-ownership-20261102.json`。

相关方法：[合法激励](../legal-stimulus/SKILL.md)、[独立 oracle](../independent-oracle/SKILL.md)、
[checker](../checker-and-runtime/SKILL.md)、[追溯](../traceability-and-implementation/SKILL.md)。
