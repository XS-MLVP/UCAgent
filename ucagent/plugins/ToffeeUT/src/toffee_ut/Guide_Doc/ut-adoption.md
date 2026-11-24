
# 按本次任务接入已有工程

## 目标和操作边界

`toffee-ut:adopt` 用于接手已有项目中的一个任务，不是认证所有阶段已完成。
从用户这次要修的问题、要补的覆盖或要继续的工作开始，只读相关代码与资料，维护
`{OUT}/docs/reviews/<DUT>-adoption.md`，最后把阶段安排交用户确认。

不调用 scaffold、构建或仿真，不改已有工程布局、用例或运行原件，也不要求全量基线。
没有资料或工具时如实保留依赖；接入可以形成待处理的交接意见，但不能说问题已修复。
Skill 只帮助分析，不可用时直接按本文件、用户请求和相关工件完成相同工作。

## 三个接入步骤

1. **明确任务**：记录 `task`、`acceptance` 和 `out_of_scope`。用户只要求修漏采时，
   不把它扩成整个 DUT 验收。目标或退出条件不明时询问，不能从现有完成度反推授权。
2. **盘点相关成果**：只列本任务需要的 `assets`。`path` 是工作区相对的实际文件；
   `use` 为 `reuse`、`inspect` 或 `repair`，`note` 说明用途及证据限制。历史 PASS
   不是当前执行证据，文件存在也不证明逻辑正确。缺少的必要前提写 `dependencies`。
3. **选择与交接**：列 `selected_stages` 和 `revalidation`。没有固定可跳过名单，
   可以只选某个子阶段。展示范围、依赖和建议，等待真实人工确认；报告中的文本不等于批准。

每阶段使用 `Check`、`SetCurrentStageJournal` 和 `Complete`。接入检查只核对交接
结构和本地引用，不代替来源语义、执行证据、主流程验收或用户批准。

## 完整交接示例

以下是 Queue 的一项局部修复示例。文件路径和任务必须替换成本次实际内容；示例中的
代码文件应真实存在。即使其他验证工作没有做完，也可以明确不在本次范围，不能标为通过。

````markdown

# Queue 本次任务接入

## 任务与范围

修复 monitor 在同拍多通道 fire 时漏采的问题，复用既有 DUT 和事务环境。
本次不调整设计规格、RTL 或覆盖目标，不要求完成整个 Queue 的全部验证。

```yaml
kind: task_adoption
dut: Queue
project: ut_project
task: 修复 monitor 同拍多通道漏采，并验证受影响路径
acceptance:
  - 在同一检查沿保存全部相关通道快照，之后再更新状态
  - 合法控制与单错误控制在约定比较位置生效，相关复验保留实际结果
out_of_scope:
  - 不修改 RTL、独立预期或覆盖率目标
  - 不新增无关场景，不宣称整个 DUT 已验收
assets:
  - path: ut_project/testbenches/queue/env/monitor.py
    use: repair
    note: 本次问题所在；需核对采样顺序与快照，不能仅凭结构判断漏采已修复
  - path: ut_project/testbenches/queue/tests/test_monitor.py
    use: inspect
    note: 复用相关控制入口；现有结果先视为历史资料，修改后需按影响复验
dependencies: []
selected_stages:
  - env_fixture_implementation
  - evaluate_env_fixture
revalidation:
  - 修复后先运行相关 envcheck 自检，再复验用户指出的受影响节点
  - 不重建未变化的原生 DUT；若发现必须修改协议或扩大回归范围，先交用户确认
```

## 交接与待确认事项

以上是本次阶段安排，不是已完成阶段清单。用户确认后由操作者使用相同 task 与阶段
名单启动主流程；本接入流程不自动切换、不启动另一个 Agent，也不把历史 PASS 迁成新结果。
````

`assets` 可为空，但此时必须在 `dependencies` 说明缺少的必要资料。不要为了表格
完整而捏造文件；也无需给其余 20 个阶段逐一写“完成”结论。

## 主流程的任务选择

确认后可以在主流程配置中使用：

```yaml
runtime_options:
  ut_task: 修复 monitor 同拍多通道漏采，并验证受影响路径
  ut_task_stages:
    - env_fixture_implementation
    - evaluate_env_fixture
```

`ut_task_stages: null` 是默认值，保留完整配置范围。显式列表必须非空，使用主流程的
稳定阶段名，不使用显示序号。选择父阶段包含其已启用子阶段；只选子阶段时父节点仅作
容器，不执行父节点汇总门禁或无关兄弟工作。执行顺序仍采用原流程顺序。

本次未涉及不等于已经完成或通过。选择哪个阶段由用户任务决定，不要求事先认证所有
跳过阶段。所选阶段的现有检查仍保持原要求；缺必要合同或运行证据时报告依赖并确认
处理范围，不能因局部选择而降低标准。已配置关闭或不适用的可选阶段不会被自动开启，
若任务明确需要，应请操作者先确认并调整相应选项。

主流程提供的具体工具与证据格式见 `Guide_Doc/ut-project.md`、
`Guide_Doc/ut-environment.md` 和 `Guide_Doc/ut-results.md`。这里的选择不导入外部
报告为当前证据、不改变已有工程接入约束，也不自动完成全流程验收。

## 循环和流程切换

已有 loop 或当前接入 MCP 的 Agent 负责“当前任务 → 修改/复核 → Check → 继续”。
新增依赖时先解释影响，由用户决定是否扩展本次任务；不要同时启动第二个 Agent 推进。
只补分析说明时不机械重跑，RTL/构建输入变化才需要按实际配方重建。

接入结束不自动切换工作流。不同工作流或不同任务选择不能沿用另一套阶段索引；同一
工作区切换前，操作者应停止旧实例，另存需要保留的 `.ucagent/ucagent_info.json`，
然后显式使用 `--no-history` 启动新流程。该参数只是不加载旧记录，新实例仍会保存
本次进度；它不是历史隔离或自动合并，不能因此删除原工程与运行产物。
