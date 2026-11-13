
# Docker Swarm 部署

本文说明如何准备一个 2-3 节点的 Docker Swarm 集群，并使用仓库中的
`make/master.mk` 启动 UCAgent Master Web。Master 本身作为一个 Swarm service
运行；从 Master Web 的 Launch 页面创建的验证任务也会作为 Swarm job service
运行。

本文假设使用 Linux 主机和 Docker Engine。Docker Desktop、Colima 或其他远程
Docker context 也可以使用同一组 Make 目标，但挂载 Docker socket、持久化目录
和浏览器访问地址需要按实际 context 调整。

## 1. 节点规划

下面的示例使用 3 台主机；只有 2 台时，可以把 `swarm-worker-2` 步骤省略。

| 节点 | 示例地址 | 角色 | 用途 |
| --- | --- | --- | --- |
| `swarm-manager-1` | `192.168.10.11` | manager | 执行 `make swarm_master`，运行 Master Web |
| `swarm-worker-1` | `192.168.10.12` | worker | 运行 Master Web 启动的验证 job |
| `swarm-worker-2` | `192.168.10.13` | worker | 可选的第二个验证节点 |

所有节点必须能够通过主机名或 IP 互相访问，并使用兼容的 Docker Engine 版本。
验证任务使用的镜像必须能被每个可能运行任务的节点拉取。默认镜像是
`ghcr.nju.edu.cn/xs-mlvp/ucagent:latest`。当前 Make 目标不会自动转发私有仓库认证；
使用私有镜像时，需要在所有可能调度到的节点登录并预先拉取镜像，或将
`SWARM_IMAGE` 改为所有节点都能访问的镜像地址。首次部署
时镜像较大，建议先在 manager 和 worker 上执行 `docker pull <SWARM_IMAGE>`；
对于可变 tag，`swarm_init` 也会在 manager 上重新拉取，以免本地旧 tag 与
Swarm 解析出的当前 digest 不一致。使用固定 digest 可以确保各节点使用同一版本。

在防火墙或云安全组中放行以下端口：

| 端口 | 协议 | 用途 |
| --- | --- | --- |
| `2377` | TCP | Swarm manager 与节点的集群管理 |
| `7946` | TCP/UDP | 节点发现和 gossip |
| `4789` | UDP | overlay 网络的 VXLAN 流量 |
| `8800` | TCP | Master Web；由 `make swarm_master` 发布 |

`8800` 只需要对浏览器所在网络开放；前三个端口需要在所有 Swarm 节点之间
互通。生产环境应按网络边界限制来源，不要把 Docker socket 或 Swarm 管理端口
直接暴露到公网。

## 2. 安装 Docker 并初始化 manager

在三台主机上安装并启动 Docker Engine。以 Ubuntu 为例：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

重新登录，使当前用户获得 Docker 权限，然后在 `swarm-manager-1` 上检查：

```bash
docker version
docker info
```

使用 manager 节点在集群中的可达地址初始化 Swarm：

```bash
docker swarm init --advertise-addr 192.168.10.11
```

`--advertise-addr` 必须是其他节点能访问的 manager 地址。多网卡主机不要直接
依赖 Docker 的自动选择，否则节点可能加入错误的网络。

初始化后检查 manager：

```bash
docker node ls
docker info --format '{{.Swarm.LocalNodeState}} {{.Swarm.ControlAvailable}}'
```

预期结果是本机状态为 `active`、控制能力为 `true`，并且 `docker node ls` 中
manager 为 `Leader` 或 `Reachable`。

## 3. 加入 1-2 个 worker

仍在 manager 上生成 worker join 命令：

```bash
docker swarm join-token worker
```

把命令输出的完整 `docker swarm join --token ... 192.168.10.11:2377` 命令分别
复制到 `swarm-worker-1` 和可选的 `swarm-worker-2` 上执行。不要在 worker 上再次
运行 `docker swarm init`。

在 manager 上确认节点状态：

```bash
docker node ls
```

应看到类似以下的 3 节点结果（节点 ID 和版本会不同）：

```text
ID                            HOSTNAME         STATUS  AVAILABILITY  MANAGER STATUS
... *                         swarm-manager-1  Ready   Active         Leader
...                           swarm-worker-1   Ready   Active
...                           swarm-worker-2   Ready   Active
```

如果节点处于 `Down` 或 `Drain`，先修复 Docker 服务和节点间网络，再继续部署。
验证任务默认没有节点约束，因此可被调度到任一可用 worker 或 manager；若需要
限制任务节点，可在项目配置的 `launch.cluster.swarm_extra_args` 中增加合法的
`docker service create` 参数。

## 4. 准备镜像、环境变量和源码路径

在将要执行 `make swarm_master` 的 manager 上进入 UCAgent 源码根目录，并设置
模型环境变量。Makefile 只转发变量名，实际值由 Docker 从当前 shell 环境读取：

```bash
cd /path/to/UCAgent

export OPENAI_API_BASE="https://<openai-compatible-endpoint>/v1"
export OPENAI_API_KEY="<api-key>"
export OPENAI_MODEL="<model-name>"
```

如果使用 Anthropic 兼容入口，也可以显式设置：

```bash
export ANTHROPIC_BASE_URL="$OPENAI_API_BASE"
export ANTHROPIC_AUTH_TOKEN="$OPENAI_API_KEY"
export ANTHROPIC_MODEL="$OPENAI_MODEL"
```

这些变量用于 Master 从 Launch 页面构造子 Agent 的启动环境。
所选 backend 的认证必须在子 Agent 容器内可用；仅在 manager 主机上登录
命令行工具，不会自动把该主机的登录状态传给 Swarm job。

默认情况下 `make swarm_master` 使用已发布的 `SWARM_IMAGE`。如果需要让 Master
容器直接运行当前源码树，可指定源码目录：

```bash
make swarm_master UCAGENT_MASTER_SOURCE=/path/to/UCAgent
```

此目录会以 `/UCAgent` 挂载到 Master 容器，并通过 `python3 /UCAgent/ucagent/cli.py`
启动。Master service 被固定到 manager，因此该路径必须在 manager 上存在；它
不会自动复制到 worker。镜像还必须包含与当前源码兼容的 Python 依赖；旧镜像
挂载新源码可能因缺失模块而反复重启。使用已发布镜像时不要设置这个变量。

## 5. 启动 Swarm Master Web

在 manager 上执行：

```bash
make swarm_master
```

该目标会依次完成以下工作：

1. 检查 Docker CLI、curl、Docker daemon、Docker socket、Swarm active 状态和 manager 权限。
2. 创建名为 `ucagent_net` 的可 attach `overlay` 网络，或检查已有网络的 driver/scope。
3. 拉取 `SWARM_IMAGE`（可变 tag 每次拉取，固定 digest 只在本机不存在时拉取）。
4. 在 manager 节点创建单副本 `ucagent_master` service。
5. 将 `/var/run/docker.sock` 和 `SWARM_MASTER_PERSIST` 挂载到 Master 容器。
6. 监听 `0.0.0.0:8800`，并把默认任务启动模式覆盖为 `docker_swarm`。

`make swarm_master` 会等待 service 达到 1/1 且 Master API 对浏览器地址作出
响应；如果失败，使用 `docker service ps` 和 `docker service logs` 检查启动错误。

常用 Make 目标和变量如下：

| 目标或变量 | 默认值 | 说明 |
| --- | --- | --- |
| `swarm_check` | - | 检查 Docker、socket、Swarm active 状态和 manager 权限 |
| `swarm_init` | - | 执行 `swarm_check`，创建 overlay 网络并确保 Master 镜像存在 |
| `swarm_master` | - | 创建或重建 Master service |
| `swarm_clean` | - | 删除匹配 `ucagent` 的 service，停止匹配的运行中容器 |
| `SWARM_IMAGE` | `ghcr.nju.edu.cn/xs-mlvp/ucagent:latest` | Master 和子 Agent 使用的容器镜像 |
| `SWARM_NETWORK` | `ucagent_net` | attachable overlay 网络名 |
| `SWARM_MASTER_SERVICE` | `ucagent_master` | Master service 名称和容器内回连地址 |
| `SWARM_MASTER_PORT` | `8800` | Master Web 发布端口 |
| `SWARM_MASTER_PERSIST` | `/tmp/ucagent_master` | manager 上的持久化目录 |
| `SWARM_MASTER_HOST` | 自动推导 | HTTP 就绪探测和浏览器访问使用的主机名或 IP |
| `SWARM_MASTER_WAIT_SECONDS` | `300` | 等待 service 达到 1/1 且 Master API 响应的秒数；正整数 |
| `SWARM_DOCKER_SOCK` | `/var/run/docker.sock` | Master 创建子 Agent service 使用的 Docker socket |
| `UCAGENT_MASTER_SOURCE` | 空 | 可选的 manager 源码目录，挂载为 `/UCAgent` |
| `ARGS` | 空 | 追加到 Master CLI 的 UCAgent 参数 |

默认持久化目录是 manager 上的 `/tmp/ucagent_master`。建议为长期运行指定专用
目录，例如：

```bash
sudo mkdir -p /srv/ucagent/master
sudo chown "$USER" /srv/ucagent/master

make swarm_master \
  SWARM_MASTER_PERSIST=/srv/ucagent/master \
  SWARM_MASTER_HOST=192.168.10.11
```

`SWARM_MASTER_HOST` 用于 HTTP 就绪探测和命令最后打印的浏览器地址；它应填写
运行 Make 的主机和浏览器都能访问的 manager IP 或 DNS 名称。Colima 使用
host 发布模式时，默认值为 `127.0.0.1`；远程 Docker context 或其他网络拓扑应
显式设置这个变量。Master 与子 Agent 在 overlay 网络中使用服务名
`ucagent_master:8800` 回连，因此不要把 `SWARM_MASTER_HOST` 填入子 Agent 的
内部地址配置。

启动时需要调整默认 backend 或其他 CLI 参数时，通过 `ARGS` 追加：

```bash
make swarm_master \
  SWARM_MASTER_HOST=192.168.10.11 \
  ARGS="--override launch.default_args.backend=codex --override launch.default_args.mcp_server_no_file_tools=True"
```

`codex` 等非 LangChain backend 需要通过 MCP 与子 Agent 通信；这里启用不暴露文件工具的 MCP 服务。

命令成功后会打印两种地址：

- `http://ucagent_master:8800`：只适用于同一 overlay 网络中的容器。
- `http://192.168.10.11:8800`：浏览器访问地址，应使用实际输出的 manager 地址。

打开浏览器访问后，Master Web 的 Launch 页面默认会选择 `Docker Swarm`。创建
工作区、上传 RTL、完成 Compile，再点击 **Launch Task**，即可创建一个名称类似
`ucagent-<task-id>` 的 Swarm job。子 Agent 通过 `ucagent_master:8800` 注册回
Master；任务镜像和 overlay 网络必须在调度到的节点上可用。

## 6. 验证 service 和任务

在 manager 上查看 Master：

```bash
docker service ls
docker service ps ucagent_master --no-trunc
docker service logs -f ucagent_master
```

Master Web 启动任务后，使用任务详情中的 service 名称检查子 Agent：

```bash
docker service ls --filter name=ucagent-
docker service ps ucagent-<task-id> --no-trunc
docker service logs -f ucagent-<task-id>
```

若任务没有达到运行状态，先查看 `docker service ps ... --no-trunc` 的错误，再
检查目标节点是否能拉取 `SWARM_IMAGE`、是否能访问 overlay 网络，以及工作区的
同步和挂载配置。Master 的 Task 页面也会保留 stdout/stderr 和 Swarm service
状态。

service 达到 1/1、子 Agent 注册成功只说明部署链路可用；完整验收还需确认
验证阶段推进、最终完成状态和工作区内的实际测试及报告产物。

## 7. 更新、停止和清理

重复执行 `make swarm_master` 会删除同名 Master service 后重新创建它；持久化
目录不会被 Makefile 删除。只清理本次演练的任务和 Master service：

```bash
docker service rm ucagent-<task-id>
docker service rm ucagent_master
```

删除 UCAgent 相关 service 并停止匹配的运行中容器：

```bash
make swarm_clean
```

`swarm_clean` 会在 service 和容器列表的整行输出中匹配 `ucagent`，也可能匹配
镜像名。使用前确认不会影响同一 Docker daemon 上的其他项目。

测试集群不再使用时，在各节点执行：

```bash

# worker 节点
docker swarm leave

# 最后处理 manager；单 manager 集群需要强制离开
docker swarm leave --force
```

## 8. 常见问题

### `make swarm_master` 报 Swarm is not active

在当前 Docker context 上执行 `docker info` 和 `docker node ls`。该命令必须在
active 的 manager 节点执行；worker 不能创建 Master service。

### overlay 网络已存在但类型不对

Makefile 要求 `ucagent_net` 的 driver 为 `overlay`、scope 为 `swarm`。检查：

```bash
docker network inspect ucagent_net
```

删除或改用其他网络名后重试：

```bash
make swarm_master SWARM_NETWORK=ucagent_verification_net
```

### Master Web 能打开，但 Launch 任务无法启动

确认所有可调度节点都能拉取 `SWARM_IMAGE`，并检查 Master service 是否挂载了
可用的 Docker socket：

```bash
docker service ps ucagent_master --no-trunc
docker service logs ucagent_master
```

如果使用了 `UCAGENT_MASTER_SOURCE`，确认 manager 上的路径仍然存在。若任务需要
访问额外的本地工具或目录，在 Launch cluster 配置中声明 `extra_mounts`，并确保
每个可能的节点都有相同的源路径。

### 子 Agent 已注册，但验证阶段没有推进

先检查 Task 页输出和所选 backend 在子 Agent 容器内的认证状态；确认模型所需的
环境变量或凭据实际进入了任务容器。Master Web 能启动或 Swarm service 显示
`1/1`，都不能代替一次完成的模型调用和阶段验证。

### 浏览器无法访问打印的地址

使用 manager 的可达 IP 或 DNS 重新执行：

```bash
make swarm_master SWARM_MASTER_HOST=<browser-reachable-manager-ip-or-dns>
```

检查主机防火墙和云安全组是否放行 TCP `8800`。`127.0.0.1` 只适用于浏览器与
Docker manager 在同一台主机上的情况。
