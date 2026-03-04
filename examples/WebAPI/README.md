## Web API：CMD API 与 Master 集中管理面板

UCAgent 内置了两套独立的 Web API 服务，均基于 FastAPI + uvicorn，支持 TCP 与 Unix Socket 双监听：

| 服务 | 命令 | 默认地址 | 用途 |
|------|------|---------|------|
| **CMD API** | `cmd_api_start` | `http://127.0.0.1:8765` | 单 Agent 控制与查询 |
| **Master API** | `master_api_start` | `http://0.0.0.0:8800` | 多 Agent 集中监控面板 |

---

## 一、CMD API Server — 单 Agent REST 接口

### 启动

在 UCAgent 交互终端中执行：

```
cmd_api_start                          # TCP 127.0.0.1:8765 + Unix Socket（默认）
cmd_api_start 0.0.0.0 9000             # 自定义 TCP 地址
cmd_api_start --sock /run/uc.sock      # 自定义 Unix Socket 路径
cmd_api_start --sock none              # 仅 TCP，不启用 Socket
cmd_api_start --no-tcp                 # 仅 Unix Socket
```

或通过命令行在启动时自动执行：

```bash
ucagent workspace/ dut.v -icmd "cmd_api_start"
```

### 查看状态 / 停止

```
cmd_api_status    # 显示监听地址及文档链接
cmd_api_stop      # 停止服务
```

### 可用接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | Agent 运行状态 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/task/<index>` | 指定任务详情 |
| GET | `/api/mission` | Mission 进度（原始 ANSI；`?strip_ansi=true` 可去除） |
| GET | `/api/cmds[?prefix=]` | 可用 PDB 命令列表 |
| GET | `/api/help[?cmd=]` | 指定命令的帮助文档 |
| GET | `/api/tools` | 工具列表 |
| GET | `/api/changed_files[?count=10]` | 最近修改的输出文件 |
| POST | `/api/cmd` | 入队单条命令 `{"cmd": "..."}` |
| POST | `/api/cmds/batch` | 批量入队命令 `{"cmds": [...]}` |
| GET | `/docs` | Swagger UI（交互式文档） |

### 使用 Unix Socket 访问

```bash
# 查询 Agent 状态
curl --unix-socket /tmp/ucagent_cmd.sock http://localhost/api/status

# 发送命令
curl --unix-socket /tmp/ucagent_cmd.sock \
     -X POST http://localhost/api/cmd \
     -H 'Content-Type: application/json' \
     -d '{"cmd": "master_api_list"}'

# 查看 Swagger 文档
curl --unix-socket /tmp/ucagent_cmd.sock http://localhost/docs
```

### 使用 TCP 访问

```bash
# 获取 Mission 进度（带 ANSI 颜色）
curl http://127.0.0.1:8765/api/mission

# 获取 Mission 进度（纯文本）
curl "http://127.0.0.1:8765/api/mission?strip_ansi=true"

# 批量发送命令
curl -X POST http://127.0.0.1:8765/api/cmds/batch \
     -H 'Content-Type: application/json' \
     -d '{"cmds": ["ls", "pwd"]}'
```

---

## 二、Master API Server — 多 Agent 集中管理

Master 是一个独立的聚合服务：多个 Agent 通过心跳注册到同一个 Master，Master 提供统一的 Web 面板实时查看所有 Agent 的状态。

### 架构

```
Agent A ──┐
Agent B ──┼──▶  POST /api/register（心跳）──▶  Master API Server
Agent C ──┘                                         │
                                                    ├── GET  /         (Web 面板)
                                                    ├── GET  /api/agents
                                                    └── DELETE /api/agent/{id}
```

### 启动 Master

在任意一台机器的 UCAgent 终端中（或通过 `--as-master` 命令行参数）：

```
master_api_start                       # 默认 0.0.0.0:8800 + Unix Socket
master_api_start 0.0.0.0 9900          # 自定义端口
master_api_start --sock none           # 仅 TCP
master_api_start --no-tcp              # 仅 Unix Socket
master_api_start --timeout 60          # 心跳超时阈值改为 60 秒（默认 30）
```

或使用命令行参数直接开启 Master：

```bash
# 最简：不需要 workspace/dut，自动使用 /tmp/ucagent_master 作为 fake DUT
ucagent --as-master

# 指定监听地址
ucagent --as-master 0.0.0.0:9900

# 在已有 workspace 下随 Agent 一起启动 Master
ucagent workspace/ my_dut.v --as-master
```

> `--as-master`（无 workspace/dut）会自动在 `/tmp/ucagent_master/` 下创建 fake DUT，并以交互模式（`-hm`）启动，仅用于托管 Master 服务，不做任何验证任务。

### Web 面板

Master 启动后，在浏览器访问 `http://<host>:8800/` 即可看到实时 Web 面板，支持：

- 统计卡片：在线 / 离线 Agent 数量、任务完成情况
- 可搜索 / 过滤的 Agent 列表（ID、Host、Mission、Stage 等）
- 点击 **Detail** 查看单个 Agent 完整信息，含 ANSI 彩色任务进度
- 点击 **↻ Refresh** 手动拉取最新数据（不关闭弹窗）
- Raw JSON 折叠展示
- 批量 / 单个删除 Agent
- 自动每 5 秒刷新

### Master REST 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web 面板（HTML） |
| GET | `/api/agents` | 所有 Agent（`?include_offline=true`，`?strip_ansi=false`） |
| GET | `/api/agent/{id}` | 单个 Agent 详情 |
| DELETE | `/api/agent/{id}` | 删除 Agent（下次心跳时客户端会收到通知） |
| POST | `/api/register` | Agent 注册 / 心跳（由客户端自动调用） |
| GET | `/docs` | Swagger UI |

### 命令行查询已注册的 Agent

在任意 UCAgent 终端中（本地 Master 在线则自动使用）：

```
master_api_list            # 仅在线 Agent
master_api_list --all      # 包含离线 Agent
master_api_list --master http://192.168.1.10:8800   # 查询远程 Master
```

---

## 三、Agent 连接到 Master（心跳客户端）

每个 Agent 端执行以下命令，即开始向 Master 定期发送心跳（默认间隔 5 秒）：

```
connect_master_to 192.168.1.10            # 连接到远程 Master（默认端口 8800）
connect_master_to 192.168.1.10 9900       # 自定义端口
connect_master_to 127.0.0.1 --interval 10 # 10 秒心跳间隔
connect_master_to 127.0.0.1 --id my-agent # 指定 Agent ID
```

命令行参数形式（启动 UCAgent 时自动连接）：

```bash
ucagent workspace/ dut.v --master 192.168.1.10:8800
```

> `--master host[:port]` 等价于在启动后执行 `connect_master_to host [port]`。

断开连接：

```
connect_master_close
```

**删除后重连**：如果 Agent 在 Master 面板中被手动删除，再次执行 `connect_master_to`（或 `--master`）时，客户端会自动以 `force=True` 方式重新注册，Master 将解除黑名单并接受该 Agent。

---

## 四、日志

Master 服务端会在终端打印带时间戳的运行日志：

```
[Master 2026-03-04 15:00:00] Agent 'desktop-xxx' joined  host=172.27.101.55
[Master 2026-03-04 15:02:00] Agent 'desktop-xxx' removed by operator
[Master 2026-03-04 15:03:10] Agent 'desktop-xxx' went offline  (no heartbeat for 42s, host=172.27.101.55)
[Master 2026-03-04 15:04:00] Agent 'desktop-xxx' rejoined  host=172.27.101.55
```

---

## 五、典型使用场景

### 场景 A：单机调试，通过 REST 控制 Agent

```bash
# 启动 Agent 并自动开启 CMD API
ucagent workspace/ my_dut.v -icmd "cmd_api_start"

# 另一个终端：查询 Mission 进度
curl http://127.0.0.1:8765/api/mission

# 发送命令
curl -X POST http://127.0.0.1:8765/api/cmd \
     -H 'Content-Type: application/json' \
     -d '{"cmd": "master_api_list"}'
```

### 场景 B：多机分布式，统一监控

```bash
# 机器 A（监控机）：单独运行 Master（不跑验证任务）
ucagent --as-master

# 指定监听地址（让验证机能访问）
ucagent --as-master 0.0.0.0:8800

# 机器 B/C/D（验证机）：运行验证任务并连接 Master
ucagent workspace_b/ dut.v --master 192.168.1.10:8800
ucagent workspace_c/ dut.v --master 192.168.1.10:8800

# 在浏览器打开面板
# http://192.168.1.10:8800/
```

### 场景 C：单机多任务，Master 与 Agent 在同一进程

```bash
# Agent 自己既是 Master 又是 Client
ucagent workspace/ dut.v -icmd "master_api_start" -icmd "connect_master_to 127.0.0.1"

# 或分两步在 UCAgent 终端输入
master_api_start
connect_master_to 127.0.0.1
```
