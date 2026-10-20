
# 普通模式

普通模式由一个 UCAgent 进程完成一个验证任务。默认后端是 `langchain`，UCAgent 直接连接模型；人工操作在当前终端的 PDB/TUI 控制台完成，不需要外部 Code Agent 或 MCP。

本章使用一个有意截断 `sum` 位宽的 64 位加法器示例。示例用于说明流程，实际项目应替换为自己的 RTL 和验证需求。

## 2.1 准备 DUT

在项目目录中创建 RTL 输入目录（稍后使用它下面的 `output/` 作为 UCAgent 工作区）：

```bash
mkdir -p Adder
```

`Adder/Adder.v`：

```verilog
module Adder #(
    parameter WIDTH = 64
) (
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              cin,
    output [WIDTH-2:0] sum,
    output             cout
);
    assign {cout, sum} = a + b + cin;
endmodule
```

同时准备 `Adder/README.md`，明确期望行为，例如：

```markdown

# Adder 验证需求

验证一个无时钟、无复位的 64 位无符号组合加法器。

- 输入：`a`、`b` 各 64 位，`cin` 为 1 位进位输入。
- 期望输出：`sum` 为 64 位结果低位，`cout` 为第 65 位进位。
- 运算规则：完整结果等于无符号 `a + b + cin`，不能丢失结果位。
- 验证范围：零值、最大值、进位、边界组合及随机输入。
```

这里的 RTL 有意少提供一位 `sum`，用于演示发现与规格不一致的问题。实际项目应写清接口、时序和约束；README 是工作流输入，不能让 Agent 自行猜测规格。

## 2.2 导出 Python DUT 包

picker 将 RTL 导出为可由 Python 驱动的 DUT 包。下面的命令把包写入 `output/Adder/`，并设置仿真时的波形输出路径：

```bash
picker export Adder/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst
cp Adder/README.md output/Adder/README.md
cp Adder/Adder.v output/Adder/Adder.v
```

准备完成后的最小结构：

```text
<project>/
├── Adder/
│   ├── Adder.v
│   └── README.md
└── output/            # 本例的 workspace
    └── Adder/          # picker 导出的 Python 包
        └── xspcomm/
```

先验证生成的 Python 包可以加载和驱动：

```bash
PYTHONPATH=output python3 - <<'PYTHON'
from Adder import DUTAdder

dut = DUTAdder()
dut.a.value = 0
dut.b.value = 0
dut.cin.value = 0
dut.Step(1)
assert dut.sum.value == 0 and dut.cout.value == 0
dut.Finish()
print("DUT import and zero-input simulation passed")
PYTHON
```

这一步失败时先修复 picker 或仿真环境，再启动 UCAgent。源码仓库的 Makefile 还提供另一条路径，会自动复制 `examples/<DUT>` 并运行 picker，见下节。

## 2.3 配置模型

LangChain 后端使用 OpenAI 兼容接口。最小配置是：

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

也可以在 `config.yaml` 中写入 `openai.model_name`、`openai.openai_api_key` 和 `openai.openai_api_base`。配置加载顺序和覆盖规则见[工作流配置](../03_develop/03_workflow.md#3-配置加载和模板变量)。

内置配置默认将 `--no-embed-tools` 视为开启，即禁用嵌入/检索工具。需要使用这些工具时显式传入：

```bash
--no-embed-tools false
```

这只影响嵌入工具，不影响普通文件和测试工具。

## 2.4 启动验证

继续使用本章手动准备的 `output/Adder/`，在项目目录中启动：

```bash
ucagent output/ Adder -s -hm --tui -l
```

也可以在 UCAgent 源码根目录使用仓库自带的 `examples/Adder/`，跳过本章的手动准备步骤：

```bash
make test_Adder
```

Makefile 使用独立工作区 `output/workspace_Adder/`，执行的核心命令为：

```bash
python3 ucagent.py output/workspace_Adder/ Adder \
  --config config.yaml -s -hm --tui -l
```

`-l/--loop` 使任务立即进入模型循环；省略它时，启动后在控制台输入 `loop` 才会继续。普通模式不启动 MCP，因此不会自动运行 opencode 等外部 Code Agent。

## 2.5 运行中干预

在 TUI 底部输入 `status` 查看阶段状态，输入 `current_tips` 查看当前阶段指导。需要暂停时按 `Ctrl+C`，修复文件或环境后使用 `tool_invoke Check` 检查，再输入 `loop` 继续。完整命令和人工审核流程见[人机协同验证](../02_usage/02_assit.md)与[TUI](../02_usage/04_tui.md)。

## 2.6 结果位置

默认输出目录是工作区下的 `unity_test/`，测试报告通常位于 `uc_test_report/`。Makefile 示例的工作区是 `output/workspace_Adder/`，因此产物位于该目录下；直接 CLI 示例的产物位于 `output/unity_test/`。文件用途见[结果分析与流程总结](06_summary.md)。
