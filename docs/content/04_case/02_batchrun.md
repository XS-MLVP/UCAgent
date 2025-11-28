# 批处理执行模式

## 概述

批处理模式（Batch Run）允许 UCAgent 在无人值守的情况下自动完成一系列验证任务。

## 核心特性

### 1. 自动退出机制

UCAgent 正常运行时，完成任务后会保持运行状态以便查看结果。批处理模式通过 `--exit-on-completion` 参数实现任务完成后自动退出，便于串联执行多个任务。

### 2. 自动继续机制

在 MCP 模式下，通过 Code Agent 的 Hooks 功能，可以在 LLM 停止时自动发送"继续"指令，实现任务的自动推进。

### 3. 任务编排

支持通过 Makefile 或脚本编排多个验证任务的执行顺序，实现复杂的批处理流程。

## 使用方式

### API 模式批处理

API 模式下的批处理最为简单，通过 `--exit-on-completion` 参数让 UCAgent 在完成任务后自动退出。

#### 基本用法

```bash
# 单个 DUT 的批处理验证
ucagent output/ Adder \
  -s -l \
  --exit-on-completion \
  --no-embed-tools \
  --config config.yaml
```

参数说明：

- `-s, --stream-output`：实时输出日志
- `-l, --loop`：启动后立即进入循环执行
- `--exit-on-completion, -eoc`：任务完成后自动退出
- `--no-embed-tools`：禁用嵌入式检索工具（节省资源）

#### 串联多个任务

使用 shell 脚本串联执行：

```bash
#!/bin/bash
# batch_verify.sh

DUTS=("Adder" "Mux" "FSM" "ALU")
FAILED=()

for dut in "${DUTS[@]}"; do
    echo "========================================="
    echo "开始验证: $dut"
    echo "========================================="

    if ucagent output/ $dut -s -l --exit-on-completion --no-embed-tools; then
        echo "✓ $dut 验证成功"
    else
        echo "✗ $dut 验证失败"
        FAILED+=("$dut")
    fi

    # 保存结果到独立目录
    if [ -d "output" ]; then
        mkdir -p results/$dut
        cp -r output/* results/$dut/
        rm -rf output
    fi
done

# 输出汇总
echo ""
echo "========================================="
echo "批处理验证完成"
echo "========================================="
echo "成功: $((${#DUTS[@]} - ${#FAILED[@]}))/${#DUTS[@]}"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "失败的 DUT: ${FAILED[*]}"
    exit 1
fi
```

#### Makefile 方式

在 `examples/BatchRun/Makefile` 中提供了完整的批处理示例：

```makefile
APORT=5001
OPORT=5000

clean:
	rm output -rf

init: clean
	mkdir -p output

api_batch: init
	make -C ../../ clean
	make -C ../../ test_Adder ARGS="-eoc --no-embed-tools"
	cp -r ../../output output/Adder
	make -C ../../ clean
	make -C ../../ test_Mux ARGS="-eoc --no-embed-tools"
	cp -r ../../output output/Mux
	make -C ../../ clean
	make -C ../../ test_FSM ARGS="-eoc --no-embed-tools"
	cp -r ../../output output/FSM
```

使用方法：

```bash
cd examples/BatchRun
make api_batch
```

这个命令会依次验证 Adder、Mux、FSM 三个模块，并将结果保存到 `output/` 目录的对应子目录中。

### MCP 模式批处理

MCP 模式下需要配合 Code Agent 的 Hooks 功能实现自动继续。

#### 工作原理

1. **UCAgent MCP Server**：以 `--exit-on-completion` 参数启动
2. **Code Agent Hooks**：在 LLM 停止时触发自动继续
3. **自动推进**：通过 tmux 发送命令实现无人值守

#### Hook 消息机制

UCAgent 提供了 `--hook-message` 参数，用于获取配置中定义的提示词：

```bash
# 查看继续提示词
ucagent --hook-message continue

# 查看完成提示词
ucagent --hook-message quit

# 从配置文件读取（格式：[config.yaml::]key[|stop_key]）
ucagent --hook-message config.yaml::continue_key|complete_key
```

工作机制：

- 检查 UCAgent 状态（通过 `.ucagent_info.json`）
- 如果任务未完成，返回 `continue_key` 对应的提示词
- 如果任务已完成，返回 `stop_key` 对应的提示词（如果提供）
- 通过退出码 0 表示成功，非 0 表示失败

#### iFlow CLI 配置

在 `~/.iflow/settings.json` 中配置 Hooks：

```json
{
	"mcpServers": {
		"unitytest": {
			"httpUrl": "http://localhost:5001/mcp",
			"timeout": 10000
		}
	},
	"hooks": {
		"Stop": [
			{
				"hooks": [
					{
						"type": "command",
						"command": "M=`ucagent --hook-message 'continue|quit'` && (tmux send-keys $M; sleep 1; tmux send-keys Enter)",
						"timeout": 3
					}
				]
			}
		]
	}
}
```

配置说明：

- **Stop 触发器**：在 LLM 每次停止工作时触发
- **command 执行**：
  - `ucagent --hook-message 'continue|quit'`：获取提示词
  - `tmux send-keys $M`：将提示词发送到当前 tmux 窗口
  - `sleep 1; tmux send-keys Enter`：按下回车键
- **timeout**：命令执行超时时间（秒）

!!! tip "提示词配置"
`continue` 和 `quit` 可以是：

    - 配置文件中的键名（如 `config.yaml::continue_prompt`）
    - 环境变量名（如 `$CONTINUE_MSG`）
    - 直接的提示词文本

#### 单次 MCP 批处理

单个 DUT 的 MCP 批处理流程：

```bash
#!/bin/bash
# mcp_batch_one.sh

DUT=$1
PORT=${2:-5001}

# 1. 启动 UCAgent MCP Server
tmux new-session -d -s ucagent_$DUT
tmux send-keys -t ucagent_$DUT "ucagent output/ $DUT --mcp-server-port $PORT -eoc --tui --no-embed-tools" C-m

# 2. 等待 Server 就绪
while [ ! -f "output/Guide_Doc/dut_fixture.md" ]; do
    sleep 5
done

# 3. 配置 iFlow
mkdir -p output/.iflow
cp ~/.iflow/settings.json output/.iflow/settings.json
sed -i "s/5000\/mcp/$PORT\/mcp/" output/.iflow/settings.json

# 4. 启动 iFlow CLI（自动继续）
cd output
npx -y @iflow-ai/iflow-cli@latest -y

# 5. 等待完成
while [ ! -f "exited.txt" ]; do
    sleep 5
done

echo "✓ $DUT 验证完成"
```

#### 批量 MCP 执行

在 `examples/BatchRun/Makefile` 中提供了完整的批处理实现：

```makefile
mcp_one_%:
	@echo "Selected MCP port: $(APORT)"
	make -C ../../ clean
	make -C ../../ mcp_$* ARGS="-eoc --mcp-server-port=$(APORT)"
	cp -r ../../output output/$*
	@while [ ! -f "../../output/exited.txt" ]; do \
		sleep 5; \
	done
	make -C ../../ clean

mcp_batch: init
	@$(MAKE) mcp_one_Adder
	@$(MAKE) mcp_one_Mux
	@$(MAKE) mcp_one_FSM

iflow_once:
	@while [ -f "../../output/.ucagent_info.json" ]; do \
		sleep 5; \
	done
	@while [ ! -f "../../output/Guide_Doc/dut_fixture.md" ]; do \
		sleep 5; \
	done
	mkdir -p ../../output/.iflow
	cp ~/.iflow/settings.json ../../output/.iflow/settings.json
	sed -i "s/$(OPORT)\/mcp/$(APORT)\/mcp/" ../../output/.iflow/settings.json
	(sleep 10; tmux send-keys `ucagent --hook-message cagent_init`; sleep 1; tmux send-keys Enter)&
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y && (echo true > exited.txt)
	sleep 30

iflow_batch:
	@$(MAKE) iflow_once # Adder
	@$(MAKE) iflow_once # Mux
	@$(MAKE) iflow_once # FSM

iflow_batch_auto_tmux:
	tmux kill-session -t my_batch_iflow_session_$(APORT) || true
	tmux new-session -d -s my_batch_iflow_session_$(APORT)
	tmux send-keys -t my_batch_iflow_session_$(APORT):0.0 "make mcp_batch" C-m
	tmux split-window -h -t my_batch_iflow_session_$(APORT):0.0
	tmux send-keys -t my_batch_iflow_session_$(APORT):0.1 "make iflow_batch" C-m
	tmux attach-session -t my_batch_iflow_session_$(APORT)
```

使用方法：

```bash
cd examples/BatchRun

# MCP 模式批处理（需要先登录 iFlow）
make iflow_batch_auto_tmux
```

工作流程：

1. **左侧窗格**：依次启动 UCAgent MCP Server（Adder → Mux → FSM）
2. **右侧窗格**：依次启动 iFlow CLI 并自动继续
3. **同步机制**：通过 `exited.txt` 标记文件确保顺序执行
4. **结果收集**：每个 DUT 的结果保存到独立目录

## 其他 Code Agent 支持

### Claude Code

Claude Code 也支持 Hooks 功能，配置方式类似：

参考文档：[Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide)

配置示例：

```json
{
	"hooks": {
		"onStop": {
			"command": "ucagent --hook-message continue",
			"type": "shell"
		}
	}
}
```

### Gemini CLI

Gemini CLI 同样支持 Hooks：

参考文档：[Gemini CLI Configuration - Hooks](https://geminicli.com/docs/get-started/configuration/#hooks)

配置示例：

```yaml
hooks:
  stop:
    - type: command
      command: "M=$(ucagent --hook-message continue) && echo $M"
```

### Qwen Code

Qwen Code 的 Hooks 配置：

```json
{
	"hooks": {
		"onModelStop": [
			{
				"type": "command",
				"command": "ucagent --hook-message continue"
			}
		]
	}
}
```

## 配置提示词

### 默认提示词

UCAgent 内置了默认的继续提示词，可以通过 `--hook-message` 查看：

```bash
# 查看默认的继续提示词
ucagent --hook-message continue
# 输出：继续完成任务

# 查看默认的退出提示词
ucagent --hook-message quit
# 输出：任务已完成，可以退出
```

### 自定义提示词

在项目的 `config.yaml` 中自定义提示词：

```yaml
# 批处理相关提示词
batch_prompts:
  continue_key: |
    请继续执行验证任务。如果遇到问题，先尝试解决，然后继续。

  complete_key: |
    所有验证任务已完成，可以退出了。感谢使用 UCAgent！

  init_key: |
    请通过工具 RoleInfo 获取你的角色信息和基本指导，然后完成任务。
    使用工具 ReadTextFile 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。
```

使用自定义提示词：

```bash
# 从配置文件读取
ucagent --hook-message config.yaml::batch_prompts.continue_key

# 指定继续和退出的键
ucagent --hook-message "batch_prompts.continue_key|batch_prompts.complete_key"
```

### 环境变量方式

也可以通过环境变量定义提示词：

```bash
export CONTINUE_MSG="继续执行下一个验证任务"
export COMPLETE_MSG="批处理验证全部完成"

# 使用环境变量
ucagent --hook-message "\$CONTINUE_MSG|\$COMPLETE_MSG"
```


## 故障排查

### 问题 1：任务未自动退出

**现象**：使用 `--exit-on-completion` 后，UCAgent 仍未退出

**可能原因**：

1. Exit 工具未被成功调用
2. 任务未真正完成
3. 存在后台线程阻止退出

**解决方法**：

```bash
# 查看 UCAgent 状态
cat output/.ucagent_info.json

# 检查是否有残留进程
ps aux | grep ucagent

# 强制清理
pkill -9 -f ucagent
```

### 问题 2：Hook 未触发

**现象**：配置了 Hooks 但自动继续功能不工作

**排查步骤**：

1. 检查 Code Agent 配置文件语法

   ```bash
   # iFlow
   cat ~/.iflow/settings.json | jq .
   ```

2. 验证 Hook 命令

   ```bash
   # 手动测试
   M=$(ucagent --hook-message continue) && echo $M
   ```

3. 查看 Code Agent 日志
   ```bash
   # iFlow 日志通常在
   cat ~/.iflow/logs/latest.log
   ```

### 问题 3：批处理中断

**现象**：批处理执行到一半停止

**可能原因**：

1. 某个任务耗时过长
2. 系统资源耗尽
3. 网络问题（API 调用失败）

**解决方法**：

```bash
# 添加超时和重试
timeout 7200 ucagent output/ DUT -s -l -eoc --no-embed-tools || {
    echo "任务超时或失败，等待 30 秒后重试..."
    sleep 30
    ucagent output/ DUT -s -l -eoc --no-embed-tools
}
```

### 问题 4：结果文件冲突

**现象**：多个任务的结果相互覆盖

**解决方法**：为每个任务使用独立的工作目录

```bash
#!/bin/bash
for dut in Adder Mux FSM; do
    # 创建独立工作目录
    WORK_DIR="batch_work_${dut}_$$"
    mkdir -p $WORK_DIR

    # 在独立目录中执行
    (cd $WORK_DIR && ucagent ../output/ $dut -s -l -eoc --no-embed-tools)

    # 收集结果
    mkdir -p results/$dut
    cp -r $WORK_DIR/output/* results/$dut/
    rm -rf $WORK_DIR
done
```

## 示例项目

完整的批处理示例位于 `examples/BatchRun/` 目录：

```
examples/BatchRun/
├── Makefile           # 批处理任务定义
├── README.md          # 说明文档
└── (生成的输出)
    └── output/
        ├── Adder/     # Adder 验证结果
        ├── Mux/       # Mux 验证结果
        └── FSM/       # FSM 验证结果
```

快速开始：

```bash
# 进入示例目录
cd examples/BatchRun

# API 模式批处理
make api_batch

# MCP 模式批处理（需要 iFlow 认证）
make iflow_batch_auto_tmux
```

## 相关文档

- [多实例并发执行](./01_multirun.md) - 同时运行多个 UCAgent 实例
- [API 直接使用模式](../02_usage/01_direct.md) - UCAgent 基础使用方法
- [MCP 集成模式](../02_usage/00_mcp.md) - 与 Code Agent 集成
- [TUI 使用指南](../02_usage/04_tui.md) - 终端界面使用
