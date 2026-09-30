
# Web Master 使用指南

本文给出 UCAgent Web Master 的完整操作流：

1. 进入 Master 仪表盘查看 Agent 状态
2. 在 Launch 页面创建并编译任务
3. 在 Task 页面管理任务生命周期
4. 在 Agent 页面执行阶段批量操作与结果复盘

---

## 1. 功能概览

Web Master 不只是状态展示，而是完整的任务管理入口，核心能力包括：

1. Dashboard：Agent 列表、筛选、排序、分页、离线策略
2. Launch：工作区创建、文件导入/上传、模块解析、编译、启动参数预览
3. Task：托管任务列表、状态筛选、日志查看、停止/删除
4. Agent：阶段快捷操作（HM/Skip/LFail/LPass）、阶段文件查看、Diff 对比
5. Web Terminal：在线终端访问（可与本地终端并行）

---

## 2. 快速开始

### 2.1 启动 Master

Master 保留本地 PDB 控制台，用于执行 Master API、任务、终端、状态和文件管理命令，但不会初始化、探测或调用 API/命令行模型后端。执行 `loop`、`chat`、`next_round` 等模型工作命令时，`BlankBackend` 会直接返回不支持，不会调用模型。

```bash
# 推荐：持久化模式
ucagent --as-master-persist --as-master
```

默认访问地址：

```text
http://localhost:8800
```

如需密码保护：

```bash
ucagent --as-master-persist --as-master --as-master-password "your_password"
```

Master 启动本身不要求模型地址、API Key 或模型名称。若需要从 Launch 页面启动子 Agent，可在 Master 进程环境中配置模型变量；它们只用于构造子 Agent 的启动环境。

Master 模式下的 `--backend` 用于设置 Launch 页启动子 Agent 时的默认 backend；Master 当前进程始终使用无模型 backend。

### 2.2 连接 Agent 到 Master

```bash
ucagent ./output Adder --master 127.0.0.1:8800 your_key
```

示例：

```bash
ucagent ./output Adder --master 127.0.0.1:8800
```

---

## 3. Dashboard（总览页）

### 3.1 常用操作

1. 搜索 Agent（ID/Host/Mission）
2. 按状态过滤（online/offline）
3. 按字段排序（last_seen/progress 等）
4. 分页浏览大规模 Agent 列表
5. 批量删除离线 Agent

### 3.2 离线清理策略

可启用 Auto-delete offline 并设置检查间隔与阈值时间，减少僵尸实例对面板的干扰。

建议：

1. 开发环境：阈值较短（例如 5-10 分钟）
2. 共享环境：阈值较长（例如 30-60 分钟）

---

## 4. Launch（任务创建页）

### 4.1 标准流程

1. 创建 Launch Workspace
2. 上传或导入 RTL/Spec/Requirement/Config 文件
3. 标记主 RTL 并解析模块
4. 选择 DUT 名称与模块后执行编译
5. 检查命令预览并启动托管任务

### 4.2 建议实践

1. 每次调整主模块后重新编译
2. 保留 Requirement 与 Config 的版本标签，便于回溯
3. 启动前先看 Command Preview，确认 backend/master/export-cmd-api 参数

### 4.3 以 Bug Review 注册一个任务

Bug Review 任务使用普通 Master Launch 流程创建，但输入准备发生在启动 Master 之前。先让 LLM 执行 `bug-review-orchestrator` 的 `prepare-input` Skill，完成输入复制、旧报告重分析和 `prepare_manifest.json` 校验；确认 `bug_reports.reanalysis_required` 为空后，再在 Master 中选择生成的 `workspace_<DUT>/launch.yaml`。Master 不调用 `skills/bug-review-orchestrator/scripts/prepare_inputs.py`，也不在启动时修补缺失报告。

用户需要提供一个例子目录，至少包含 `launch.yaml`、UnityTest 文档和测试文件；RTL 可以由 `launch.yaml` 引用服务器上的绝对路径或 filelist。

推荐目录布局如下：

```text
examples/LoadUnit/
├── launch.yaml
└── unity_test/
    ├── bosc_LoadUnit_basic_info.md
    ├── bosc_LoadUnit_bug_analysis.md
    ├── bosc_LoadUnit_functions_and_checks.md
    ├── bosc_LoadUnit_verification_needs_and_plan.md
    └── tests/
        ├── bosc_LoadUnit.ignore
        ├── bosc_LoadUnit_api.py
        └── test_*.py
```

`launch.yaml` 需要声明 DUT、顶层模块、主 RTL、RTL 依赖和验证资料。例如：

```yaml
task_name: LoadUnit
dut: bosc_LoadUnit
module: bosc_LoadUnit
output: unity_test

files:
  main_rtl: /nfs/home/songfangyuan/work/XSV/skills/third-party/xscore_ap/rtl/bosc_LoadUnit.sv
  filelist:
    - /nfs/home/songfangyuan/work/XSV/skills/third-party/xscore_ap/rtl/filelist.f
  requirement: unity_test/bosc_LoadUnit_basic_info.md
  doc:
    - unity_test/bosc_LoadUnit_functions_and_checks.md
    - unity_test/bosc_LoadUnit_verification_needs_and_plan.md

bug_review_tests:
  - unity_test/tests/bosc_LoadUnit.ignore
  - unity_test/tests/bosc_LoadUnit_api.py
  - unity_test/tests/bosc_LoadUnit_function_coverage_def.py
  - unity_test/tests/test_bosc_LoadUnit_api_basic.py
  - unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py
```

`files` 中的普通文件按 Master 的常规类别导入。`bug_review_tests` 是 Bug Review 的目录保留入口，文件会继续使用相对于 `launch.yaml` 的路径，例如 `unity_test/tests/test_bosc_LoadUnit_scalar_pipeline.py` 不会被压平到上传目录。需要纳入本次复核的每个测试、fixture、覆盖率定义和 `.ignore` 文件都应列出。

注册和启动步骤：

1. 重启 Master，使当前配置和插件可用。
2. 打开 **Launch** 页面，在 **Select On Server** 中选择 prepare-input 生成目录里的 `launch.yaml`，例如 `plugins/bug_review/inputs/workspace_bosc_LoadUnit/launch.yaml`，不要重新选择未准备的原始 examples 文件。
3. 确认 YAML 解析出的主 RTL、filelist、需求文档和测试文件；如果测试文件没有出现在 `unity_test/tests` 层级，先检查 `bug_review_tests` 路径是否相对于 YAML 文件正确。
4. 确认 DUT 为 `bosc_LoadUnit`，Module 为 `bosc_LoadUnit`，然后点击 **Compile bosc_LoadUnit**。
5. 编译必须成功后才能启动任务。使用 prepare-input 生成的当前 DUT 编译 workspace；不要依赖以前生成的 Picker 包。
6. 在 **Launch Settings** 中选择 preset `bug_review`。该 preset 会使用当前 Master 的 backend 和子 Agent 启动配置，并选择 `bug_review:analysis` workflow。
7. 检查 **Config Path** 为 `bug_review`，确认 backend、Launch Mode、Master 地址和环境变量后点击 **Launch Task**。
8. 在 Task 页面确认子 Agent 已注册并开始运行；在任务详情中查看 command、stdout/stderr 和阶段状态。

启动 Bug Review 时，Master 从已经准备好的输入建立本次复核的隔离执行快照。运行目录中应出现：

```text
<bug-review-run>/
├── review_job.json
└── results/
    ├── tests/
    │   └── workspace_bosc_LoadUnit/
    │       └── unity_test/tests/
    └── inputs/
        └── workspace_bosc_LoadUnit/
```

`results/tests` 是实际执行测试的副本，`results/inputs` 是只读输入和报告关联副本，`review_job.json` 保存本次复核元数据。它们由运行时从已准备好的 workspace 生成，不需要用户手动创建，也不应把它们预先放进例子的 `inputs` 目录。若 canonical 报告缺失或 manifest 仍有待重分析项，应停止启动，回到 prepare-input Skill 修复后重新准备。

### 4.4 Bug Review 注册失败时的检查顺序

1. **YAML 找不到文件**：所有相对路径都相对于 `launch.yaml` 所在目录；绝对 RTL/filelist 路径必须在 Master 主机上存在。
2. **编译报告缺少模块**：检查 `filelist` 是否包含实例化模块，例如 `bosc_MemTrigger.sv`；只声明主 RTL 文件通常不够。
3. **测试目录缺失**：确认 `bug_review_tests` 至少包含测试 API、fixture、测试文件和 `.ignore`，并且路径以 `unity_test/tests/` 开头。
4. **任务无法启动**：确认编译已经成功、DUT/module 与编译时一致、Config Path 为 `bug_review`，并检查 Task 详情中的完整 command 和 stderr。
5. **输入未准备完成**：检查 prepare-input 生成的 `workspace_<DUT>/prepare_manifest.json`，确认 canonical 报告存在且 `bug_reports.reanalysis_required` 为空；修复后重新运行该 Skill，再重新选择准备好的 `workspace_<DUT>/launch.yaml`。Master 不会调用准备脚本或替旧报告补文件。

普通 UT、Formal 等 preset 不使用 `bug_review_tests`，继续沿用 Master 现有文件导入和启动流程。

---

## 5. Task（托管任务页）

### 5.1 页面能力

1. 按状态、关键字、DUT 过滤
2. 分页查看任务
3. 查看任务详情（命令、注册状态、PID）
4. 查看 stdout/stderr 日志
5. 停止任务与删除记录

### 5.2 典型排障路径

1. 任务卡在 starting：先看 command 与环境变量展开结果
2. 任务 failed：优先看 stderr，再看 workspace 与 DUT 参数
3. Agent 未注册：检查 --master 地址、key、网络连通性

---

## 6. Agent 页面高级操作

### 6.1 阶段快捷控制

页面支持单阶段快捷开关：

1. HM：人工检查开关
2. Skip：跳过开关
3. LF：LLM Fail Suggestion 开关
4. LP：LLM Pass Suggestion 开关

### 6.2 阶段批量控制

可多选阶段后批量设置：

1. HM On/Off
2. Skip/Unskip
3. LFail On/Off
4. LPass On/Off

### 6.3 阶段产物复盘

对阶段输出文件可进行：

1. 内容查看
2. Diff 查看（当前结果与变更对比）
3. 快速定位失败阶段对应产物

---

## 7. Web Terminal 与访问模式

### 7.1 两种常见模式

1. web-console：浏览器控制台模式（独立 Web 入口）
2. web-terminal：Web 终端模式（可与本地终端并行）

### 7.2 多会话建议

启用多个终端会话时，建议通过不同 URL/页签区分任务，避免误操作。

---

## 8. 代理与网络说明

Master 支持统一代理转发到 task/agent 的 cmd、terminal、web-console 访问路径。

当出现连接问题时，按以下顺序排查：

1. Master 页可见但子页面失败：检查代理路径与鉴权
2. 页面可开但 WS 不稳定：检查反向代理/网关是否放通 websocket
3. 本地可连远端不可连：检查绑定地址（127.0.0.1 vs 0.0.0.0）

---

## 9. 安全与权限建议

1. 公网或共享网络务必开启密码保护
2. 对外暴露时配合网关鉴权和 TLS
3. 定期清理离线 Agent 与无效任务记录

---

## 10. FAQ

### Q1：为什么 Launch 编译成功但任务启动失败？

优先检查：

1. backend 是否可用
2. 启动环境变量是否完整
3. master 地址与 key 是否正确

### Q2：为什么 Task 显示 running，但 Agent 页面打不开？

通常是注册延迟或代理链路问题，先看 Task 详情中的注册状态与日志。

### Q3：什么时候用 TUI，什么时候用 Web？

1. TUI：本地快速调试、命令细粒度操作
2. Web：集中管理、多任务运维、远程协作

---

## 11. 版本变更记录（建议维护）

建议在本节按版本持续记录：

1. Launch/Task/Agent 页面能力变化
2. 阶段批量控制与复盘能力变化
3. 代理与 WebSocket 兼容性变化
