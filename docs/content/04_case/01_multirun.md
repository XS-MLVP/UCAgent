# 多 UCAgent 并发执行

## 背景

在实际验证工作中，经常需要同时对多个 DUT 进行并发验证以提升效率。UCAgent 支持在同一节点上运行多个实例，实现并发验证。本文档介绍如何在不同模式下实现多 UCAgent 并发执行。

## 实现方式

UCAgent 支持两种并发执行方式：

1. **API 模式并发**：基于独立工作区的多实例运行
2. **MCP 模式并发**：基于端口隔离的 MCP Server + Code Agent 协作

## API 模式并发

### 原理说明

在 API 模式下，不同 workspace 下的 UCAgent 实例是完全独立的，因此可以在多个终端窗口中同时运行，互不干扰。

### 基本用法

#### 准备工作

在运行 UCAgent 之前，需要先准备好 DUT 文件和工作目录。如果你克隆了 UCAgent 仓库，Makefile 会自动完成这些初始化工作（`init_Adder` 目标）：

1. 创建 RTL 目录并复制设计文件（.v/.sv/.scala 等）
2. 使用 picker 工具生成波形配置文件
3. 复制相关文档和环境文件

如果你是通过 pip 安装的 ucagent，需要手动准备工作目录：

```bash
# 创建工作目录
mkdir -p output/Adder output/Adder_RTL

# 复制你的 RTL 设计文件到 RTL 目录
cp /path/to/your/Adder.v output/Adder_RTL/

# （可选）如果有 filelist.txt
cp /path/to/your/filelist.txt output/Adder_RTL/

# 使用 picker 生成 DUT 配置（如果安装了 picker）
picker export output/Adder_RTL/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst

# 复制其他必要文件（README、环境脚本等）
cp /path/to/your/*.py output/Adder/ 2>/dev/null || true
```

在不同工作区的 `config.yaml` 中配置好模型、API_KEY 和 API_BASE 之后，就可以启动 UCAgent 了。
**注：`config.yaml` 文件可从 UCAgent 官方仓库根目录获取。**

#### 多终端窗口方式

准备好工作目录后，最简单的方式是在不同终端窗口中分别启动 UCAgent：

```bash
# 终端窗口 1
cd workspace_A
ucagent output/ Adder --config config.yaml -s -hm --tui -l

# 终端窗口 2
cd workspace_B
ucagent output/ Mux --config config.yaml -s -hm --tui -l
```

### 使用 Tmux 管理多实例

为了更方便地管理多个并发实例，推荐使用 tmux 工具（ Debian / Ubuntu 可直接 apt 安装）。tmux 允许在单个终端中创建和管理多个会话窗口。

#### 完整流程（包含初始化）

```bash
# 进工作目录
cd your_workspace

# 配置环境变量（模型、API_KEY 和 API_BASE），下面是iflow的例子
export OPENAI_MODEL=glm-4.6
export OPENAI_API_KEY=<your_key>
export OPENAI_API_BASE=https://apis.iflow.cn/v1

# 清理旧输出
rm -rf output

# 初始化工作目录 A (Adder)
mkdir -p output/A output/A_RTL
cp /path/to/examples/Adder/*.v output/A_RTL/ 2>/dev/null
cp /path/to/examples/Adder/*.sv output/A_RTL/ 2>/dev/null
cp /path/to/examples/Adder/filelist.txt output/A_RTL/ 2>/dev/null
# 导出python包
picker export output/A_RTL/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/A/Adder.fst 2>/dev/null
cp /path/to/examples/Adder/*.md output/A/ 2>/dev/null
cp /path/to/examples/Adder/*.py output/A/ 2>/dev/null

# 初始化工作目录 B (Mux)
mkdir -p output/B output/B_RTL
cp /path/to/examples/Mux/*.v output/B_RTL/ 2>/dev/null
cp /path/to/examples/Mux/*.sv output/B_RTL/ 2>/dev/null
cp /path/to/examples/Mux/filelist.txt output/B_RTL/ 2>/dev/null
picker export output/B_RTL/Mux.v --rw 1 --sname Mux --tdir output/ -c -w output/B/Mux.fst 2>/dev/null
cp /path/to/examples/Mux/*.md output/B/ 2>/dev/null
cp /path/to/examples/Mux/*.py output/B/ 2>/dev/null

# 杀掉可能存在的旧会话
tmux kill-session -t my_multi_api_session 2>/dev/null

# 创建新的 tmux 会话
tmux new-session -d -s my_multi_api_session

# 在第一个窗格启动 Adder 验证（如果使用了虚拟环境，需要在tmux窗口里手动激活）
tmux send-keys -t my_multi_api_session:0.0 "ucagent output/A/ Adder --config config.yaml -s -hm --tui -l --no-embed-tools" C-m

# 水平分割窗口
tmux split-window -h -t my_multi_api_session:0.0

# 在第二个窗格启动 Mux 验证（延迟 10 秒避免同时启动冲突，如果使用了虚拟环境，需要在tmux窗口里手动激活）
tmux send-keys -t my_multi_api_session:0.1 "sleep 10 && ucagent output/B/ Mux --config config.yaml -s -hm --tui -l --no-embed-tools" C-m

# 附加到 tmux 会话查看
tmux attach-session -t my_multi_api_session
```

!!! info "关于 Makefile 自动化"
如果你克隆了 UCAgent 仓库，`Makefile` 中的 `test_Adder` 目标会自动完成上述初始化步骤（通过 `init_Adder` 依赖）：

- 创建 `output/Adder_RTL` 目录并复制 RTL 文件
- 使用 picker 生成波形配置文件
- 复制相关文档和环境文件

在 `examples/MultiRun/Makefile` 中提供了完整的自动化实现：

```bash
cd examples/MultiRun
make api_mul  # 自动初始化并启动 tmux 多实例
```

等效于手动执行：`make test_Adder ARGS='--no-embed-tools' CWD=output/A`

tmux 常用快捷键：

- `Ctrl+b %`：水平分割窗格
- `Ctrl+b "`：垂直分割窗格
- `Ctrl+b 方向键`：在窗格间切换
- `Ctrl+b d`：分离会话（后台运行）
- `Ctrl+b x`：关闭当前窗格

## MCP 模式并发

### 原理说明

MCP 模式下通过端口隔离实现并发。核心思路是：

1. 为每个 UCAgent 实例分配一个独立的可用端口
2. 使用该端口启动 UCAgent MCP Server
3. 配置 Code Agent 连接到对应端口
4. 多个 "UCAgent + Code Agent" 组合可以并发运行

### 端口分配策略

为了避免端口冲突，需要自动获取可用端口。在 `examples/MultiRun/Makefile` 中提供了自动获取可用端口的实现：

```makefile
APORT != bash -c '\
for try in $$(seq 1 100); do \
	cand=$$(shuf -i 2000-65000 -n 1); \
	if ! ss -ltn | awk '\''{print $$4}'\'' | grep -Eq "[.:]$${cand}$$"; then \
		echo $$cand; \
		exit 0; \
	fi; \
done; \
exit 1'
```

这段代码会：

1. 在 2000-65000 范围内随机选择一个端口号
2. 使用 `ss -ltn` 检查端口是否被占用
3. 返回第一个可用端口
4. 最多尝试 100 次

### 基本使用流程

#### 1. 启动 UCAgent MCP Server

使用 `--mcp-server-port` 参数指定端口：

```bash
# 使用端口 5001
ucagent output/Adder_5001/ Adder -s -hm --tui \
  --mcp-server-port 5001 \
  --mcp-server-no-file-tools \
  --no-embed-tools
```

参数说明：

- `--mcp-server-port 5001`：指定 MCP Server 监听端口为 5001
- `--mcp-server-no-file-tools`：不暴露文件操作工具（安全考虑）
- `--no-embed-tools`：不启用嵌入式检索工具（节省资源）

#### 2. 配置 Code Agent

以 iFlow CLI 为例，需要修改 MCP Server 配置指向正确的端口。

创建工作区专属配置：

```bash
# 创建工作区的 iFlow 配置目录
mkdir -p output/Adder_5001/.iflow

# 复制默认配置
cp ~/.iflow/settings.json output/Adder_5001/.iflow/settings.json

# 修改端口配置
sed -i 's/5000\/mcp/5001\/mcp/' output/Adder_5001/.iflow/settings.json
```

配置文件示例（`output/Adder_5001/.iflow/settings.json`）：

```json
{
	"mcpServers": {
		"unitytest": {
			"httpUrl": "http://localhost:5001/mcp",
			"timeout": 10000
		}
	}
}
```

#### 3. 启动 Code Agent

在对应工作目录启动 Code Agent：

```bash
# 进入工作目录
cd output/Adder_5001

# 启动 iFlow CLI（会自动读取当前目录的 .iflow/settings.json）
npx -y @iflow-ai/iflow-cli@latest -y
```

#### 4. 开始验证

在 Code Agent 中输入提示词开始验证：

```
请通过工具 RoleInfo 获取你的角色信息和基本指导，然后完成任务。使用工具 ReadTextFile 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。
```

### 使用 Tmux 管理 MCP 并发

推荐使用 tmux 同时管理 UCAgent Server 和 Code Agent：

```bash
# 创建 tmux 会话
tmux new-session -d -s mcp_5001

# 在第一个窗格启动 UCAgent MCP Server
tmux send-keys -t mcp_5001:0.0 "ucagent output/Adder_5001/ Adder --mcp-server-port 5001 -hm --tui --mcp-server-no-file-tools --no-embed-tools" C-m

# 分割窗口
tmux split-window -h -t mcp_5001:0.0

# 在第二个窗格启动 Code Agent
tmux send-keys -t mcp_5001:0.1 "cd output/Adder_5001 && npx -y @iflow-ai/iflow-cli@latest -y" C-m

# 附加到会话
tmux attach-session -t mcp_5001
```

### Makefile 自动化示例

在 `examples/MultiRun/Makefile` 中提供了完整的自动化实现：

```makefile
mcp_mul: clean
	# 获取可用端口
	@echo "Selected MCP port: $(APORT)"
	tmux kill-session -t my_multi_mcp_session_$(APORT) || true

	# 在 tmux 中启动 MCP Server
	tmux new-session -d -s my_multi_mcp_session_$(APORT)
	tmux send-keys -t my_multi_mcp_session_$(APORT):0.0 "$(mcp_cmd) ARGS='--mcp-server-port=$(APORT)' CWD=$(mcp_cwd)" C-m

	# 配置 iFlow 并启动
	mkdir -p ../../$(mcp_cwd)/.iflow
	cp $(ifw_cfg) ../../$(mcp_cwd)/.iflow/settings.json
	sed -i "s/$(ifw_prt)\/mcp/$(APORT)\/mcp/" ../../$(mcp_cwd)/.iflow/settings.json

	tmux split-window -h -t my_multi_mcp_session_$(APORT):0.0
	tmux send-keys -t my_multi_mcp_session_$(APORT):0.1 "cd ../../$(mcp_cwd);$(bash_iflow_wait)" C-m
	tmux attach-session -t my_multi_mcp_session_$(APORT)
```

使用方法：

```bash
# 进入 examples/MultiRun 目录
cd examples/MultiRun

# 配置 API Key（编辑 IFLOW_env.bash）
vim IFLOW_env.bash

# 执行 MCP 模式并发验证
make mcp_mul
```

每次执行 `make mcp_mul` 会：

1. 自动分配一个可用端口
2. 创建独立的工作目录（如 `output/Adder_5001`）
3. 启动 UCAgent MCP Server
4. 配置并启动 iFlow CLI
5. 使用 tmux 进行会话管理

可以在多个终端中运行多次 `make mcp_mul`，每次会获得不同的端口和独立的工作环境。

## 配置说明

### 环境变量配置文件

在 `examples/MultiRun/IFLOW_env.bash` 中配置 API 相关信息：

```bash
export OPENAI_MODEL=glm-4.6
export OPENAI_API_KEY=<your_key>
export OPENAI_API_BASE=https://apis.iflow.cn/v1
```

使用前需要替换 `<your_key>` 为实际的 API Key。

### Makefile 变量说明

```makefile
# MCP Server 启动命令
mcp_cmd = make -C ../../ mcp_Adder

# 工作目录（包含端口号以区分）
mcp_cwd = output/Adder_$(APORT)

# iFlow 配置文件路径
ifw_cfg = ~/.iflow/settings.json

# iFlow 默认端口（用于替换）
ifw_prt = 5000
```

可根据实际项目需求修改这些变量。

## 其他 Code Agent 支持

除了 iFlow CLI，其他支持 MCP 的 Code Agent 也可以使用相同的方式：

### Qwen Code

配置文件路径：`~/.qwen/settings.json`

```json
{
	"mcpServers": {
		"unitytest": {
			"httpUrl": "http://localhost:5001/mcp",
			"timeout": 10000
		}
	}
}
```

启动方式：

```bash
cd output/Adder_5001
qwen
```

### Claude Code

参考：[Claude Code MCP 配置文档](https://code.claude.com/docs/en/mcp-guide)

### Gemini CLI

参考：[Gemini CLI MCP 配置文档](https://geminicli.com/docs/get-started/mcp/)

### VS Code Copilot

参考：[VS Code MCP 扩展配置](https://marketplace.visualstudio.com/items?itemName=modelcontextprotocol.mcp)

## 故障排查

### 端口被占用

**现象**：启动 UCAgent MCP Server 时提示端口已被占用

**解决方法**：

```bash
# 查找占用端口的进程
lsof -i :5001

# 或使用 ss 命令
ss -tlnp | grep 5001

# 终止占用端口的进程
kill -9 <PID>
```

### Code Agent 连接失败

**现象**：Code Agent 无法连接到 MCP Server

**排查步骤**：

1. 确认 UCAgent MCP Server 已正常启动

   ```bash
   curl http://localhost:5001/mcp
   ```

2. 检查配置文件中的端口号是否正确

   ```bash
   cat output/Adder_5001/.iflow/settings.json
   ```

3. 检查防火墙设置
   ```bash
   sudo ufw status
   ```

### tmux 会话丢失

**现象**：退出终端后 tmux 会话消失

**说明**：tmux 会话在系统重启或用户登出后可能丢失。

**解决方法**：

1. 使用 `systemd` 或 `screen` 等工具保持会话
2. 使用 tmux 插件 `tmux-resurrect` 保存和恢复会话
3. 编写启动脚本并添加到系统服务

### 内存不足

**现象**：系统响应变慢，出现 OOM (Out of Memory) 错误

**解决方法**：

1. 减少并发实例数量
2. 使用 `--no-embed-tools` 禁用嵌入式工具节省内存
3. 为系统配置 swap 空间
4. 使用 `ulimit` 限制单个进程内存使用

## 相关文档

- [API 直接使用模式](../02_usage/01_direct.md)
- [MCP 集成模式](../02_usage/00_mcp.md)
- [批处理执行](../04_case/02_batchrun.md)
- [TUI 使用指南](../02_usage/04_tui.md)
