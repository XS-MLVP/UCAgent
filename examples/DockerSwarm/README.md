# Docker Swarm Master

本文说明如何用 Docker Swarm 启动 UCAgent Master，并在 Web 界面中用
Swarm 模式启动任务容器。

## 1. 安装并初始化 Docker Swarm

先在作为 Swarm manager 的机器上安装 Docker Engine。Ubuntu 上可使用：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

执行 `usermod` 后需要重新登录 shell，或者临时用 `sudo` 执行 Docker
命令。

检查 Docker 是否可用：

```bash
docker version
docker info
```

单机测试时直接初始化 Swarm：

```bash
docker swarm init
```

如果机器有多个网卡，建议显式指定其它节点和浏览器可访问的地址：

```bash
docker swarm init --advertise-addr <manager-ip>
```

多节点 Swarm 中，在 worker 节点执行 `docker swarm init` 输出的 join
命令。忘记 join 命令时可重新查看：

```bash
docker swarm join-token worker
```

检查集群状态：

```bash
docker node ls
docker info --format '{{.Swarm.LocalNodeState}}'
```

运行 `make swarm_master` 的节点必须是 Swarm manager，并且 Swarm 状态应为
`active`。

## 2. 设置 LLM 环境变量

启动 master 前先在当前 shell 中设置模型 endpoint 和密钥。Makefile 会把这些
变量传入 Swarm master 容器；master 再根据 `launch.default_env` 把必要环境
传给后续启动的 worker agent。

OpenAI-compatible endpoint：

```bash
export OPENAI_API_BASE="https://<your-openai-compatible-endpoint>/v1"
export OPENAI_API_KEY="<your-api-key>"
export OPENAI_MODEL="<your-model>"
```

对于ANTHROPIC会自动进行一下映射：
```bash
ANTHROPIC_BASE_URL=$OPENAI_API_BASE
ANTHROPIC_AUTH_TOKEN=$OPENAI_API_KEY
ANTHROPIC_MODEL=$OPENAI_MODEL
```

## 3. 通过项目 Makefile 启动 Master

在仓库根目录执行：

```bash
make swarm_master \
  ARGS="--backend codex --override launch.default_args.backend=codex"
```

该命令会创建名为 `ucagent_master` 的 Docker Swarm service，将 Master Web UI
发布到 `8800` 端口，并把 Master 的默认任务启动模式设置为 `docker_swarm`。
后续在 Web UI 中创建任务时，worker agent 会作为 Swarm service 启动。

其中 `ARGS` 会追加到 master 的 `ucagent` 启动命令：

- `--backend codex` 设置 master 自身运行使用的 backend。
- `--override launch.default_args.backend=codex` 设置 Web UI 启动新任务时的
  默认 backend。

启动成功后，终端会打印外部访问地址。若自动推导出的地址不可从浏览器访问，
可以显式指定：

```bash
make swarm_master \
  SWARM_MASTER_HOST=<reachable-manager-ip-or-dns> \
  ARGS="--backend codex --override launch.default_args.backend=codex"
```

## 4. 查看和清理

查看 Swarm service：

```bash
docker service ls
docker service ps ucagent_master --no-trunc
docker service logs -f ucagent_master
```

清理 UCAgent 相关 Swarm service 和容器：

```bash
make swarm_clean
```

单机测试结束后，如需退出 Swarm：

```bash
docker swarm leave --force
```

## 注意事项

- `make swarm_master` 需要访问 `/var/run/docker.sock`，因为 master 会通过
  Docker Swarm 创建 worker service。
- Master service 默认约束在 manager 节点运行。
- 浏览器访问地址应使用 manager 节点可达 IP 或 DNS，不一定是 `127.0.0.1`。
- Swarm overlay 网络内部，worker agent 通过 service name
  `ucagent_master` 访问 master。
- `ARGS="--backend codex --override launch.default_args.backend=codex"` 用于设置
  master 自身 backend 和 Web UI 默认任务 backend；也可以把 `codex` 换成
  `claude`、`qwen`、`opencode`、`kilo` 等其它已配置 backend。
- `ARGS="..."` 可继续追加其它 UCAgent CLI 参数。
