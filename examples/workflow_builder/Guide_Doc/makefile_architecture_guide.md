# Makefile 架构原理与调整指南

## 1. 整体设计

CWF（子工作流）的 Makefile 由 MWF（母工作流）的 WorkflowBuilder 自动生成。Makefile 是连接用户输入、UCAgent 运行时和 config.yaml 配置的枢纽。理解它的变量体系和目标依赖链是正确调整工作流行为的基础。

## 2. 核心变量体系

```
用户输入层                  Makefile 变量层              UCAgent 运行时层
───────────                ────────────────             ────────────────
input/<TARGET>/            TARGET  (纯目标名)    →     {DUT}  (目标名)
                           OUT  (输出根目录)     →     {OUT}  (输出根)
                           WORKFLOW_WORKSPACE    →     UCAgent workspace

output/.runtime_targets/   RUNTIME_DUT           →     prepare_runtime
  <TARGET>/__init__.py     (隐藏 Python 包路径)         (创建 __init__.py)
```

### 2.1 关键变量说明

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `TARGET` | (空，必须显式传入) | 纯目标名，例如 `example`。也是 UCAgent 的 `{DUT}` 值 |
| `OUT` | `output` | 输出根目录，对应 UCAgent 的 `{OUT}` |
| `WORKFLOW_WORKSPACE` | `$(CURDIR)` | 当前工作流根目录，作为 UCAgent 的 workspace 参数 |
| `RUNTIME_DUT` | `$(OUT)/.runtime_targets/$(TARGET)` | 隐藏的运行时 Python 包路径，仅 `prepare_runtime` 使用 |
| `SMOKE_TARGET` | `example` | smoke 测试专用目标名 |
| `MCP_SERVER_PORT` | `-1` (不启动) | MCP 服务端口，`-1` 表示禁用 |

### 2.2 TARGET vs RUNTIME_DUT 的分离

这是 2026-07 修复的核心设计决策：**TARGET 是纯目标名，RUNTIME_DUT 是隐藏的运行时路径，两者分离。**

修复前的问题：
```
RUNTIME_DUT = output/.runtime_targets/example
DUT = output/.runtime_targets/example    (传入 UCAgent)
{OUT}/{DUT} = output/output/.runtime_targets/example  ← 双重嵌套！
```

修复后：
```
WORKFLOW_WORKSPACE = /path/to/workflow       (传入 UCAgent workspace)
TARGET = example
DUT = example                            (传入 UCAgent)
{OUT}/{DUT} = output/example             ← 正确！
RUNTIME_DUT = output/.runtime_targets/example  (仅供 __init__.py)
```

**原则**：UCAgent 的第一个参数必须是显式工作区 `$(WORKFLOW_WORKSPACE)`，第二个参数才是纯目标名 `$(TARGET)`。所有输出路径通过 config 中的 `{OUT}/{DUT}` 自然解析为 `output/<TARGET>/`。隐藏的 `__init__.py` 由 `prepare_runtime` 独立管理，不污染 DUT 语义。

## 3. 目标依赖链

```
make run / run_tui / smoke / run_inc
  └── prepare_runtime
        └── prepare_input
              └── check_target   ← 校验 TARGET 合法（仅含字母数字下划线）
```

### 3.1 check_target

```makefile
check_target:
    @case "$(TARGET)" in ""|*[!A-Za-z0-9_]*) echo "unsafe TARGET"; exit 2;; esac
```

拒绝空值和含特殊字符的 TARGET。所有需要 TARGET 的目标都通过 `prepare_input` 间接依赖它。

### 3.2 prepare_input

```makefile
prepare_input: check_target
    @test -f "input/$(TARGET)/resource.json" || ...
    @test -f "input/$(TARGET)/suggestion.md" || ...
    @$(PYTHON) -m json.tool "input/$(TARGET)/resource.json" >/dev/null
```

校验 `input/<TARGET>/` 下的必需文件存在且格式正确。必需文件列表由 `runtime_contract.required_input` 定义。

### 3.3 prepare_runtime

```makefile
prepare_runtime: prepare_input
    @runtime="$(RUNTIME_DUT)"; \
    mkdir -p "$$runtime"; \
    touch "$$runtime/__init__.py"
```

在 `output/.runtime_targets/<TARGET>/` 下创建隐藏的 `__init__.py`。该目录不在用户可见的输出路径上，仅用于满足 Python 包导入需求。

### 3.4 运行目标对比

| 目标 | 模式 | config | 说明 |
|------|------|--------|------|
| `run` | loop（非交互） | `config.yaml` | 主工作流，自动完成所有阶段后退出 |
| `run_tui` | TUI（交互） | `config.yaml` | 主工作流，手动操作 |
| `run_inc` | loop（非交互） | `config/inc.yaml` | 增量工作流 |
| `run_inc_tui` | TUI（交互） | `config/inc.yaml` | 增量工作流，手动操作 |
| `smoke` | loop（非交互） | `config.yaml` | smoke 测试，TARGET 自动设为 `$(SMOKE_TARGET)` |

### 3.5 检查目标

```makefile
check: check_config check_inc_config check_layout check_docs check_tool_specs check_tools \
       test_tools check_checker_specs check_checkers test_checkers check_package
```

每个 `check_*` / `test_*` 目标都有对应的 Python checker 脚本在 `.workflow/checkers/` 下。checker 目标可以单独运行，例如：

```bash
make check_tool_specs       # 只检查 tool spec 格式
make test_tools             # 只运行 direct tool tests
make check                  # 全量检查
```

## 4. Config 与 Makefile 的变量对接

### 4.1 变量传递路径

```
Makefile                    UCAgent 命令行                    Config 模板
────────                    ──────────────                    ──────────
TARGET=example      →       ./ $(TARGET)              →       {DUT} = example
OUT=output          →       --output $(OUT)           →       {OUT} = output

Config 中使用:
  {OUT}/{DUT}          = output/example
  input/{DUT}/...      = input/example/...
  tmp/...                 = 根级一次性临时文件，make clean 后清空
```

### 4.2 template_overwrite 的作用

Config 中的 `template_overwrite` 可以在 UCAgent 解析前覆盖变量：

```yaml
template_overwrite:
  INPUT_ROOT: input/{DUT}       # 阶段中可用 {INPUT_ROOT}
  OUTPUT_ROOT: '{OUT}/{DUT}'    # 阶段中可用 {OUTPUT_ROOT}
```

变量解析顺序：`template_overwrite` → 命令行参数 → UCAgent 内置默认值。

### 4.3 生成工具的动态注册

```makefile
GENERATED_TOOLS_CMD := $(PYTHON) -c \
  "from tools.mcp_adapters import ADAPTER_CLASS_NAMES; \
   print(','.join('tools.mcp_adapters.' + name for name in ADAPTER_CLASS_NAMES))"
```

运行时动态读取 `tools/mcp_adapters.py` 中注册的适配器类名，通过 `--ex-tools` 传入 UCAgent。新增工具只需更新 adapter，无需修改 Makefile。

`tools/mcp_adapters.py` 同时用于两种场景：

- `make test_mcp` 启动子 UCAgent 后，通过 MCP `call_tool` 调用生成工具。
- `make run` / `make run_tui` / `smoke` / `run_inc` 通过 `--ex-tools` 把同一批 adapter 注册到真实运行 Agent。

因此 adapter 必须遵守 UCAgent/LangGraph 工具返回协议：动态类只实现 `_run()`，不要覆盖 `BaseTool.run()`，也不要在动态类字典中注册 `"run": run`。`_run()` 可以返回 `json.dumps(result, ensure_ascii=False, sort_keys=True)`；直接运行时 `BaseTool.run()` 会自动把它包装成 `ToolMessage`，MCP 测试再从 ToolMessage 的文本内容解析 JSON。若覆盖 `run()` 并直接返回字符串，生成工作流会在真实运行时报 `Tool <name> returned unexpected type: <class 'str'>`。

## 5. 如何调整

### 5.0 配置当前系统

生成工作流后先运行 `make configure`，由根目录 `setup.py` 探测并确认 UCAgent、
Python、代理、tmux 以及工作流声明的额外系统工具。`make configure-check` 用于
无交互校验。程序只更新 Makefile 和 `ucagent_setup.sh` 中标记为
`generated by setup.py` 的区块，其他人工内容保持不变。新增可配置工具时修改
`config/environment.schema.yaml`，不要直接在两个受控区块里固化机器路径。

### 5.1 修改必需输入

修改 `runtime_contract.required_input`（在 `wfgen/workflow_build.yaml` 中），然后重新运行 Builder。Makefile 的 `prepare_input` 会自动生成对应的文件校验规则。

### 5.2 添加新 make 目标

在 `workflow_build.yaml` 的 `makefile.targets` 中添加目标名，Builder 会生成骨架。具体实现需要在 Builder 的 `generate_makefile()` 函数中补充。

### 5.3 修改 UCAgent 启动参数

所有运行目标 (`run`, `run_tui`, `smoke`, `run_inc`) 共享相同的 UCAgent 参数模式：

```
$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) \
    --config ./config.yaml \        # 入口配置
    --output $(OUT) \               # 输出根目录
    --guid-doc-path ./Guide_Doc/ \  # 指导文档路径
    --append-py-path . \            # 添加 CWF 根目录到 Python path
    --ex-tools "$$generated_tools" \  # 动态注册生成工具
    --mcp-server-port $(MCP_SERVER_PORT) \
    -s -hm --no-embed-tools ...
```

`WORKFLOW_WORKSPACE` 必须默认等于 `$(CURDIR)`。禁止写成 `$(UCAGENT) ./ $(TARGET)`；当 Makefile 被外层脚本、tmux 或其他目录调用时，`./` 的含义可能漂移，最终验收会把它判为运行契约错误。

需要调整时（例如添加额外的 Python path、修改 loop 行为），直接编辑对应目标的 recipe，但必须保持 `$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET)` 这个参数顺序。

### 5.4 调整 TARGET 校验规则

`check_target` 使用 shell case 模式匹配。如果 TARGET 需要支持更多字符（如连字符），修改 case 模式：

```makefile
# 原始：仅字母数字下划线
@case "$(TARGET)" in ""|*[!A-Za-z0-9_]*) ...;; esac

# 修改后：允许连字符
@case "$(TARGET)" in ""|*[!A-Za-z0-9_-]*) ...;; esac
```

注意：TARGET 会作为 UCAgent 的 DUT 参数、文件路径和目录名使用，扩大字符集可能引入路径安全问题。

## 6. 常见问题

### 6.1 产物输出路径错误

**症状**：产物出现在 `output/output/...`（双重嵌套）或 `.runtime_targets/` 下。

**原因**：Makefile 传入的 workspace 或 DUT 不符合契约。常见错误包括把 workspace 写成 `./`，或者把包含 `output/` 前缀的路径作为 DUT。

**修复**：确保 `run`/`smoke`/`run_tui` 中 UCAgent 的 workspace 参数为 `$(WORKFLOW_WORKSPACE)`，DUT 参数为 `$(TARGET)`（纯目标名），而非 `./` 或 `$(RUNTIME_DUT)`。同时检查 config 中的 `OUTPUT_ROOT` 使用 `{OUT}/{DUT}`。

### 6.2 make check 在 clean 后失败

**症状**：`make check` 报告 checker_specs 或 config 检查失败。

**原因**：`make check` 依赖 `.workflow/` 下的 specs 和 checkers。如果这些由生成器按需创建，在清理后需要重新生成。

**修复**：先运行相关生成器重建 specs，再运行 `make check`。

### 6.3 MCP 测试失败

**症状**：`make test_mcp` 报 "MCP server did not become ready"。

**原因**：可能端口被占用、UCAgent 启动超时、或 adapter 注册不完整。

**修复**：
1. 检查 `lsof -i :<port>` 确认端口空闲
2. 确认 `tools/mcp_adapters.py` 的 `ADAPTER_CLASS_NAMES` 包含所有已生成工具
3. 手动运行 `make smoke` 确认 UCAgent 基本启动正常

### 6.4 run_inc 找不到输入

**症状**：`make run_inc TARGET=example` 报 "missing input/..."

**原因**：`run_inc` 使用与 `run` 相同的 TARGET 和输入目录，增量工作流期望输入已存在。

**修复**：增量工作流的 TARGET 必须与主工作流一致。增量修改的上下文在 `evaluation/` 目录下，不改变 `input/<TARGET>/`。

### 6.5 output/ 目录被 Agent 写入了脚本等非产物文件

**症状**：`output/` 根目录下出现了 `.py` 脚本、临时文件等不属于任何 TARGET 子目录的文件。

**原因**：`config.yaml` 的 `write_dirs: [output]` 过于宽泛。Agent 可以在 `output/` 下任意位置写入文件。当 Agent 判断调用已有工具不如手写代码更可控时，会选择 improvisation——写一个独立脚本放在 `output/` 下。

**根本预防**：收窄 `write_dirs` 到 `{OUT}/{DUT}`，让 UCAgent 只能在目标子目录下写文件：

```yaml
# 错误：允许在 output/ 下任意写
write_dirs:
  - output

# 正确：只允许在 output/<TARGET>/ 下写
write_dirs:
  - '{OUT}/{DUT}'
```

这样即使 Agent 想写脚本，也只能放在 `output/example/` 内，不会污染 `output/` 根目录。

### 6.6 产物路径出现 output/output/ 双重嵌套

**症状**：产物出现在 `output/output/.runtime_targets/example/` 或类似的嵌套路径下。

**原因**：两重因素叠加：
1. Makefile 的 `RUNTIME_DUT`（=`output/.runtime_targets/$(TARGET)`）被作为 DUT 传给 UCAgent
2. Config 中使用 `{OUT}/{DUT}`，而 `{DUT}` 已经是含 `output/` 前缀的完整路径

结果为 `output/output/.runtime_targets/example/`。

**修复**：保持 DUT 为纯目标名 `$(TARGET)`，详见第 2.2 节「TARGET vs RUNTIME_DUT 的分离」。

## 7. write_dirs 约束原理

### 7.1 为什么 write_dirs 很重要

UCAgent 的 `write_dirs` 不是建议，而是硬约束。Agent 只能在这些目录（及其子目录）下创建和修改文件。配合 `un_write_dirs`，形成「允许写入」与「禁止写入」的双层沙盒：

```
write_dirs:  [{OUT}/{DUT}]     → 只能写 output/example/
un_write_dirs: [tools/, ...]   → 禁止写 tools/ 等源码目录
```

Agent 在收到写文件指令时，UCAgent 框架会检查目标路径是否在 `write_dirs` 内且不在 `un_write_dirs` 内。越界写入会被框架拒绝。

### 7.2 Agent Improvisation 的触发条件

Agent 会在以下情况选择 improvisation（手写脚本而非调用工具）：

1. **工具不存在**：所需工具尚未生成或未注册
2. **工具加载失败**：`--ex-tools` 传入失败（如 Python 版本不兼容导致 import 崩溃）
3. **工具接口不匹配**：工具的 input schema 与阶段需求差距太大，Agent 判断无法通过参数传递实现目标
4. **Mission 过于开放**：prompt 强调"自主决策"时，Agent 可能认为手写是实现复杂度需求的最优路径

前三种情况的修复方向是确保工具正确生成、可加载、接口匹配。第四种需要在 mission prompt 中明确约束：「必须使用已注册的工具完成任务，不得创建新的 Python 脚本或绕过工具直接操作文件」。

### 7.3 如何在 config spec 中指定 write_dirs

在 `.workflow/config_specs/main.yaml` 中：

```yaml
write_dirs:
  - '{OUT}/{DUT}'
```

`workflow_config_generator` 会保留 spec 中指定的 `write_dirs`。如果 spec 未指定，默认使用 `{OUT}/{DUT}`。
