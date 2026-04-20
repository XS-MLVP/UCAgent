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

