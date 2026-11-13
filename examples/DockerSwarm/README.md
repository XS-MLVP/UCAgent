
# Docker Swarm Master 示例

完整的 2-3 节点集群规划、网络端口、worker 加入、Master Web 启动、任务检查和
故障排查请参阅 [Docker Swarm 部署指南](../../docs/content/02_usage/11_docker_swarm.md)。

从仓库根目录执行最小启动流程：

```bash

# 1. 在 manager 上初始化或加入现有 Swarm，并确认节点为 Ready/Active
docker node ls

# 2. 设置模型变量（启动 Master Web 本身不强制要求，但 Launch 任务通常需要）
export OPENAI_API_BASE="https://<your-openai-compatible-endpoint>/v1"
export OPENAI_API_KEY="<your-api-key>"
export OPENAI_MODEL="<your-model>"

# 3. 创建 Master service，并将 Launch 默认模式设为 docker_swarm
make swarm_master \
  SWARM_MASTER_HOST=<browser-reachable-manager-ip-or-dns> \
  ARGS="--override launch.default_args.backend=codex --override launch.default_args.mcp_server_no_file_tools=True"
```

`make swarm_master` 默认使用 `ucagent_master` service、`ucagent_net` overlay
网络、`8800` Web 端口和 `/tmp/ucagent_master` 持久化目录。常用排查命令：

```bash
docker service ls
docker service ps ucagent_master --no-trunc
docker service logs -f ucagent_master
```

只清理本次演练的 service：

```bash
docker service rm ucagent-<task-id>
docker service rm ucagent_master
```
