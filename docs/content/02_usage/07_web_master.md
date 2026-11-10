
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

Master 保留本地 Console 控制台，用于执行 Master API、任务、终端、状态和文件管理命令，但不会初始化、探测或调用 API/命令行模型后端。执行 `loop`、`chat`、`next_round` 等模型工作命令时，`BlankBackend` 会直接返回不支持，不会调用模型。

```bash
# 源码仓库：临时工作区
make as_master

# 推荐：持久化工作区
make as_master_persist

# 安装后的命令
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
3. 按字段排序（last_seen/阶段位置等）
4. 分页浏览大规模 Agent 列表
5. 批量删除离线 Agent

列表和 Detail 中的进度条按已完成及跳过的阶段数计算，分别显示 completed 和 skipped 数量；开始最后一个阶段不会自动显示满条。缺少阶段状态的旧记录显示完成情况不可用，不根据当前阶段序号猜测完成数量。

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
4. 选择 DUT 名称、模块与 Picker 仿真器后执行编译
5. 检查命令预览并启动托管任务

编译区的 **Picker Simulator** 使用横向单选勾选项，按 `launch.default_args.simulator` 列表顺序显示，默认勾选第一个可用仿真器。默认优先级为 `[verilator, vcs, gsim, uvs]`；例如优先使用 VCS，可配置：

```yaml
launch:
  default_args:
    simulator: [vcs, verilator, gsim, uvs]
```

列表必须非空、名称不能重复，只显示并自动选择列表中配置的仿真器。页面根据 Master 进程的 `PATH` 检测 `picker` 与各仿真器可执行程序；不可用项置灰禁选，悬停显示原因，点击 **Refresh** 可重新检测。刷新会保留仍可用的手动选择；当前选择不可用时，改选优先级最高的可用项。全部不可用时不勾选任何项，并禁用编译。编译在 Master 环境执行；许可证和工具链是否就绪以编译日志为准。

| 仿真器 | 自动波形后缀 | 访问模式 |
| --- | --- | --- |
| Verilator | `.fst` | MEM_DIRECT（`--rw 1`） |
| GSim | `.fst` | DPI（`--rw 0`） |
| VCS | `.fsdb` | DPI（`--rw 0`） |
| UVS | `.usdb` | DPI（`--rw 0`） |

仿真器选择适用于单任务和批量编译。批量运行期间，每个编译与启动请求均使用开始时勾选的仿真器。切换仿真器后须重新编译才能启动任务。任务启动与 Relaunch 复用已有编译产物记录的仿真器，不再检测编译工具是否可用。单任务 YAML 导入使用顶层 `simulator: vcs`，编译 API 使用字符串请求字段 `simulator`，省略时按配置顺序选择第一个可用项；批量任务统一使用表单选择。附加 `picker_args` 用于其他参数，不能覆盖 `--sim`、`--rw` / `--access-mode` 或 `-w` / `--wave_file_name`。

### 4.2 建议实践

1. 每次调整主模块后重新编译
2. 保留 Requirement 与 Config 的版本标签，便于回溯
3. 启动前先看 Command Preview，确认 backend/master/export-cmd-api 参数

### 4.3 并行任务上限与等待队列

`master_api.max_task_count` 控制 Master 同时执行的最大任务数，默认 100：

1. 达到上限后再启动的任务进入 waiting 状态，不占用执行额度
2. 有任务结束释放额度后，等待任务按启动顺序自动启动
3. 等待任务只在 Task 页的 Launch Queue 面板中列出（含任务 ID、DUT、创建与入队时间等信息），主任务列表不显示等待任务
4. Launch Queue 面板支持拖拽或 ▲▼ 按钮调整等待任务的启动顺序，重新提交的任务排在队尾
5. Master 页的 Waiting 统计与 TOTAL/ONLINE/OFFLINE 同级展示当前等待任务数
6. Task 页摘要栏常驻显示当前最大并发数（`master_api.max_task_count`）
7. 等待任务可在 Launch Queue 面板撤销（Cancel），撤销会删除任务记录及其工作区目录

---

## 5. Task（托管任务页）

### 5.1 页面能力

1. 按状态、关键字、DUT 过滤（waiting 任务仅在 Launch Queue 面板显示，见 4.3）
2. 分页查看任务
3. 查看任务详情（命令、注册状态、PID）
4. 查看 stdout/stderr 日志
5. 停止任务与删除记录
6. 在 Launch Queue 面板调整等待任务的启动顺序并撤销等待任务（见 4.3）

### 5.2 典型排障路径

1. 任务卡在 starting：先看 command 与环境变量展开结果
2. 任务 failed：优先看 stderr，再看 workspace 与 DUT 参数
3. Agent 未注册：检查 --master 地址、key、网络连通性
4. 任务一直 waiting：并行任务已达到 `master_api.max_task_count` 上限，详情页可见队列位置，等待自动启动或撤销任务

若启动报 `HTTP listeners failed to start`，错误信息会标明服务名称及冲突的 TCP 地址或 Unix socket 路径。默认自动生成的 socket 路径遇到占用时会改用唯一名称，并通过服务状态和心跳公布实际路径；显式指定的 `--sock` 路径冲突仍会报错，已有路径不会被自动删除。

---

## 6. Agent 页面高级操作

左侧依次显示阶段信息、工具调用次数和 Agent Status。三块区域独立滚动，拖动它们之间的横向分隔栏可以调整高度；高度比例会自动保存，Reset UI 可恢复默认布局。Agent Status 按可用宽度在同一行排列多项信息。

### 6.1 阶段快捷控制

阶段列表和 Master Detail 用绿色表示完成、红色表示当前阶段、黄色表示跳过，并附状态文字、阶段序号、失败次数和耗时。完成工作区使用相同的展示规则。

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

### 6.4 执行信息与系统日志

右下角 Output 默认显示 **Activity（执行信息）**：模型/后端输出、工具调用与结果、阶段检查进展和命令输出。HTTP 访问记录与服务诊断归入 **System logs（系统日志）**；警告或错误会在页签上提示。**Raw output（原始输出）** 保留当前进程捕获的控制台原文，用于排查问题。长工具结果及最近的命令结果可以展开查看。

Web 与 TUI 可以同时显示模型消息，打开或关闭 TUI 不会使 Web 丢失模型输出。向上滚动时暂停跟随，点击新内容提示回到底部；Clear 只清空当前浏览器的当前视图，不删除公共日志或其他终端的内容。各视图独立限制记录数量和文本大小，缓冲淘汰、超长记录截断及服务重启都会明确提示。

这里显示的是后端实际输出的消息，不是完整模型请求上下文。外部命令行后端尚未区分的回答与诊断保留为 Backend 输出。分类记录仅保存在当前进程内存中；历史子工作区显示暂无保存的执行信息，不借用 Master 的实时日志。托管任务已有的进程日志仍可在 Task 页查看。

升级后需要重启对应 UCAgent 进程并刷新页面。仅刷新页面不会让运行中的旧进程具备分类接口。

---

## 7. Web Terminal 与访问模式

### 7.1 两种常见模式

1. web-console：浏览器控制台模式（独立 Web 入口）
2. web-terminal：Web 终端模式（可与本地终端并行）

### 7.2 多会话建议

启用多个终端会话时，建议通过不同 URL/页签区分任务，避免误操作。

Agent 页面内的 Runtime 命令栏按页面和工作区保存独立目录；切换工作区时回到目标工作区根目录。路径补全跟随当前会话目录，含空格的候选会保留完整命令并自动加引号。

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
