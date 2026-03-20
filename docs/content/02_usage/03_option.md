# 参数说明

## 参数与选项

UCAgent 的使用方式为：

```bash
ucagent <workspace> <dut_name> {参数与选项}
```

### 输入

- workspace：工作目录：
  - workspace/<DUT_DIR>: 待测设计（DUT），即由 picker 导出的 DUT 对应的 Python 包 <DUT_DIR>，例如：Adder
  - workspace/<DUT_DIR>/README.md: 以自然语言描述的该 DUT 验证需求与目标
  - workspace/<DUT_DIR>/\*.md: 其他参考文件
  - workspace/<DUT_DIR>/\*.v/sv/scala: 源文件，用于进行 bug 分析
  - 其他与验证相关的文件（例如：提供的测试实例、需求说明等）
- dut_name: 待测设计的名称，即 <DUT_DIR>，例如：Adder

### 输出

- workspace：工作目录：
  - workspace/Guide_Doc：验证过程中所遵循的各项要求与指导文档
  - workspace/uc_test_report： 生成的 Toffee-test 测试报告
  - workspace/unity_test/tests： 自动生成的测试用例
  - workspace/\*.md： 生成的各类文档，包括 Bug 分析、检查点记录、验证计划、验证结论等

> 对输出的详细解释可以参考[快速开始的结果分析](../01_start/02_quickstart.md/#结果分析)

### 位置参数

| 参数      | 必填 | 说明                                                         | 示例     |
| :-------- | :--: | :----------------------------------------------------------- | :------- |
| workspace |  否  | 运行代理的工作目录；使用 `--as-master` 或 `--upgrade` 时可选 | ./output |
| dut       |  否  | DUT 名称（工作目录下的子目录名）；使用 `--as-master` 或 `--upgrade` 时可选 | Adder    |

### 执行与交互

| 选项                 | 简写 | 取值/类型                  | 默认值   | 说明                                                          |
| :------------------- | :--- | :------------------------- | :------- | :------------------------------------------------------------ |
| --stream-output      | -s   | flag                       | 关闭     | 流式输出到控制台                                              |
| --human              | -hm  | flag                       | 关闭     | 启动时进入人工输入/断点模式                                   |
| --interaction-mode   | -im  | standard/enhanced/advanced | standard | 交互模式；enhanced 含规划与记忆管理，advanced 含自适应策略    |
| --tui                |      | flag                       | 关闭     | 启用终端 TUI 界面                                              |
| --web-console        |      | [base_url:port[:password]] | 关闭     | 启用浏览器 Web UI（独立模式）。默认 `localhost:8000`。**注意：仅提供 Web 界面，不提供本地命令行交互** |
| --web-terminal       |      | [host[:port]][ passwd]     | 关闭     | 启动 Web Terminal 服务器。默认 `127.0.0.1:8818`。**同时提供 Web 终端和本地命令行交互** |
| --loop               | -l   | flag                       | 关闭     | 启动后立即进入主循环（可配合 --loop-msg），适用于直接使用模式 |
| --loop-msg           |      | str                        | 空       | 进入循环时注入的首条消息                                      |
| --seed               |      | int                        | 随机     | 随机种子（未指定则自动随机）                                  |
| --sys-tips           |      | str                        | 空       | 覆盖系统提示词                                                |
| --icmd               |      | str（可多次）              | []       | 启动时执行的初始命令，可多次使用                              |
| --no-history         |      | flag                       | 关闭     | 禁用从工作目录加载历史记录                                    |
| --exit-on-completion | -eoc | flag                       | 关闭     | 任务完成后自动退出代理（Exit 工具调用成功后）                 |

#### --web-console 与 --web-terminal 区别

| 特性                | --web-console                              | --web-terminal                                    |
| :------------------ | :----------------------------------------- | :------------------------------------------------ |
| 运行模式            | 独立模式（standalone）                     | 伴随模式（与 Agent 同时运行）                     |
| 本地命令行交互      | ❌ 不提供                                  | ✅ 同时提供                                       |
| Web 浏览器访问      | ✅ 提供                                    | ✅ 提供                                           |
| 默认地址            | `localhost:8000`                           | `127.0.0.1:8818`                                  |
| 密码格式            | `base_url:port:password`（冒号分隔）       | `host[:port] passwd`（空格分隔）                  |
| 适用场景            | 纯 Web 远程访问，无需本地终端               | 需要同时使用本地终端和 Web 访问                   |

**使用建议：**
- 如果只需要通过浏览器远程访问 Agent，使用 `--web-console`
- 如果需要在本地终端操作的同时提供 Web 访问入口，使用 `--web-terminal`

**示例：**
```bash
# 仅 Web 访问（无本地交互）
ucagent --web-console
ucagent --web-console 0.0.0.0:8000:mysecret

# 同时提供 Web 和本地交互
ucagent ./output Adder --web-terminal
ucagent ./output Adder --web-terminal '0.0.0.0:8818 mysecret'
```

### 配置与模板

| 选项                    | 简写 | 取值/类型                  | 默认值     | 说明                                                            |
| :---------------------- | :--- | :------------------------- | :--------- | :-------------------------------------------------------------- |
| --config                |      | path                       | 无         | 配置文件路径，如 `--config config.yaml`                         |
| --template-dir          |      | path                       | 无         | 自定义模板目录                                                  |
| --template-overwrite    |      | flag                       | 否         | 渲染模板到 workspace 时允许覆盖已存在内容                       |
| --template-cfg-override |      | path（可多次）             | []         | 从 YAML 文件覆盖模板配置，可多次使用                            |
| --output                |      | dir                        | unity_test | 输出目录名                                                      |
| --override              |      | A.B.C=VALUE[,X.Y=VAL2,...] | 无         | 以"点号路径=值"覆盖配置；字符串需引号，其它按 Python 字面量解析 |
| --gen-instruct-file     | -gif | file                       | 无         | 在 workspace 下生成外部 Agent 的引导文件（存在则覆盖）          |
| --guid-doc-path         |      | path（可多次）             | 无         | 使用自定义 Guide_Doc 目录（默认使用内置拷贝）                   |
| --use-skill             |      | [path]                     | 否         | 启用技能 SKILL；不添加参数为禁用，`--use-skill` 为使用默认路径，`--use-skill=path` 为额外使用指定路径 |
| --backend               |      | str                        | 无         | 指定后端（覆盖配置文件设置）                                    |
| --emulate-config        |      | flag                       | 否         | 仅模拟配置过程，不实际运行各阶段                                |

### 计划与 ToDo

| 选项             | 简写 | 取值/类型 | 默认值 | 说明                                                             |
| :--------------- | :--- | :-------- | :----- | :--------------------------------------------------------------- |
| --force-todo     | -fp  | flag      | 否     | 在 standard 模式下也启用 ToDo 工具，并在每轮提示中附带 ToDo 信息 |
| --use-todo-tools | -utt | flag      | 否     | 启用 ToDo 相关工具（不限于 standard 模式）                       |

### ToDo 工具概览与示例 给模型规划的，小模型关闭，大模型自行打开

说明：ToDo 工具是用于提升模型规划能力的工具，用户可以利用它来自定义模型的 ToDo 列表。目前该功能对模型能力要求较高，默认处于关闭状态。

启用条件：任意模式下使用 `--use-todo-tools`；或在 standard 模式用 `--force-todo` 强制启用并在每轮提示中附带 ToDo 信息。

约定与限制：步骤索引为 1-based；steps 数量需在 2~20；notes 与每个 step 文本长度 ≤ 100；超限会拒绝并返回错误字符串。

工具总览

| 工具类            | 调用名            | 主要功能                         | 参数                                         | 返回                      | 关键约束/行为                                        |
| :---------------- | :---------------- | :------------------------------- | :------------------------------------------- | :------------------------ | :--------------------------------------------------- |
| CreateToDo        | CreateToDo        | 新建当前 ToDo（覆盖旧 ToDo）     | task_description: str; steps: List[str]      | 成功提示 + 摘要字符串     | 校验步数与长度；成功后写入并返回摘要                 |
| CompleteToDoSteps | CompleteToDoSteps | 将指定步骤标记为完成，可附加备注 | completed_steps: List[int]=[]; notes: str="" | 成功提示（完成数）+ 摘要  | 仅未完成步骤生效；无 ToDo 时提示先创建；索引越界忽略 |
| UndoToDoSteps     | UndoToDoSteps     | 撤销步骤完成状态，可附加备注     | steps: List[int]=[]; notes: str=""           | 成功提示（撤销数）+ 摘要  | 仅已完成步骤生效；无 ToDo 时提示先创建；索引越界忽略 |
| ResetToDo         | ResetToDo         | 重置/清空当前 ToDo               | 无                                           | 重置成功提示              | 清空步骤与备注，随后可重新创建                       |
| GetToDoSummary    | GetToDoSummary    | 获取当前 ToDo 摘要               | 无                                           | 摘要字符串 / 无 ToDo 提示 | 只读，不修改状态                                     |
| ToDoState         | ToDoState         | 获取状态短语（看板/状态栏）      | 无                                           | 状态描述字符串            | 动态显示：无 ToDo/已完成/进度统计等                  |

调用示例（以 MCP/内部工具调用为例，参数为 JSON 格式）：

```json
{
	"tool": "CreateToDo",
	"args": {
		"task_description": "为 Adder 核心功能完成验证闭环",
		"steps": [
			"阅读 README 与规格，整理功能点",
			"定义检查点与通过标准",
			"生成首批单元测试",
			"运行并修复失败用例",
			"补齐覆盖率并输出报告"
		]
	}
}
```

```json
{
	"tool": "CompleteToDoSteps",
	"args": { "completed_steps": [1, 2], "notes": "初始问题排查完成，准备补充用例" }
}
```

```json
{ "tool": "UndoToDoSteps", "args": { "steps": [2], "notes": "第二步需要微调检查点" } }
```

```json
{ "tool": "ResetToDo", "args": {} }
```

```json
{ "tool": "GetToDoSummary", "args": {} }
```

```json
{ "tool": "ToDoState", "args": {} }
```

### 外部与嵌入工具

| 选项             | 简写 | 取值/类型        | 默认值 | 说明                                      |
| :--------------- | :--- | :--------------- | :----- | :---------------------------------------- |
| --ex-tools       | -et  | name1[,name2...] | 无     | 逗号分隔的外部工具类名列表（如：SqThink），可多次使用 |
| --no-embed-tools |      | flag             | 否     | 禁用内置的检索/记忆类嵌入工具             |

### 日志

| 选项       | 简写 | 取值/类型 | 默认值 | 说明                             |
| :--------- | :--- | :-------- | :----- | :------------------------------- |
| --log      |      | flag      | 否     | 启用日志                         |
| --log-file |      | path      | 自动   | 日志输出文件（未指定则使用默认） |
| --msg-file |      | path      | 自动   | 消息日志文件（未指定则使用默认） |

### MCP Server

| 选项                       | 简写 | 取值/类型 | 默认值    | 说明                              |
| :------------------------- | :--- | :-------- | :-------- | :-------------------------------- |
| --mcp-server               |      | flag      | 否        | 启动 MCP Server（含文件工具）     |
| --mcp-server-no-file-tools |      | flag      | 否        | 启动 MCP Server（无文件操作工具） |
| --mcp-server-host          |      | host      | 127.0.0.1 | Server 监听地址                   |
| --mcp-server-port          |      | int       | 5000      | Server 端口；使用 -1 自动选择可用端口 |

### 阶段控制与安全

| 选项                | 简写 | 取值/类型       | 默认值 | 说明                                          |
| :------------------ | :--- | :-------------- | :----- | :-------------------------------------------- |
| --force-stage-index |      | int             | 0      | 强制从指定阶段索引开始                        |
| --skip              |      | int（可多次）   | []     | 跳过指定阶段索引，可重复提供                  |
| --unskip            |      | int（可多次）   | []     | 取消跳过指定阶段索引，可重复提供              |
| --no-write          | -nw  | path1 path2 ... | 无     | 限制写入目标列表；必须位于 workspace 内且存在 |
| --ref               |      | str（可多次）   | []     | 指定阶段需读取的参考文件，格式：`[stage_index:]file_path1[,file_path2]` |
| --append-py-path    | -app | path（可多次）  | []     | 添加 Python 路径或文件用于模块加载            |

### Master API 与分布式

| 选项                | 简写 | 取值/类型     | 默认值 | 说明                                                              |
| :------------------ | :--- | :------------ | :----- | :---------------------------------------------------------------- |
| --as-master         |      | [ip[:port]]   | 关闭   | 作为 Master API 服务器启动；不指定地址则使用默认值                |
| --master            |      | host[:port] [key] | [] | 连接到 Master API 服务器，可指定 access_key，可多次使用           |
| --as-master-key     |      | str           | 无     | 客户端注册时需提供的访问密钥（配合 --as-master 使用）             |
| --as-master-password|      | str           | 无     | HTTP Basic Auth 密码保护 Master API（配合 --as-master 使用）      |
| --export-cmd-api    |      | [ip[:port]][ passwd] | 关闭 | 启动 CMD API 服务器，默认 `127.0.0.1:8765`，可指定密码启用 HTTP Basic Auth |

### 上下文管理

| 选项                          | 简写 | 取值/类型 | 默认值 | 说明                                              |
| :---------------------------- | :--- | :-------- | :----- | :------------------------------------------------ |
| --enable-context-manage-tools |      | flag      | 关闭   | 启用上下文管理工具，适用于 API 模式运行           |

### 版本与检查

| 选项          | 简写 | 取值/类型   | 默认值 | 说明                                                    |
| :------------ | :--- | :---------- | :----- | :------------------------------------------------------ |
| --check       |      | flag        | 否     | 检查默认配置、语言目录、模板与 Guide_Doc 是否存在后退出 |
| --version     |      | flag        |        | 输出版本并退出                                          |
| --upgrade     |      | [pip_args]  | 否     | 从 GitHub main 分支升级 UCAgent，可选传递 pip 额外参数  |
| --hook-message|      | str         | 无     | Hook continue/complete key 用于自定义提示处理（Code Agent 使用） |

### 示例

```bash
python3 ucagent.py ./output Adder \
  \
  -s \
  -hm \
  -im enhanced \
  --tui \
  -l \
  --loop-msg 'start verification' \
  --seed 12345 \
  --sys-tips '按规范完成Adder的验证' \
  \
  --config config.yaml \
  --template-dir ./templates \
  --template-overwrite \
  --output unity_test \
  --override 'conversation_summary.max_tokens=16384,'\
             'conversation_summary.max_summary_tokens=2048,'\
             'conversation_summary.context_management_strategy=TrimAndSummaryMiddleware,lang="zh",openai.model_name="gpt-4o-mini"' \
  --gen-instruct-file GEMINI.md \
  --guid-doc-path ./output/Guide_Doc \
  \
  --use-todo-tools \
  \
  --ex-tools 'SqThink,AnotherTool' \
  --no-embed-tools \
  \
  --log \
  --log-file ./output/ucagent.log \
  --msg-file ./output/ucagent.msg \
  \
  --mcp-server-no-file-tools \
  --mcp-server-host 127.0.0.1 \
  --mcp-server-port 5000 \
  \
  --force-stage-index 2 \
  --skip 5 --skip 7 \
  --unskip 6 \
  --nw ./output/Adder ./output/unity_test

```

- 位置参数
  - ./output：workspace 工作目录
  - Adder：dut 子目录名
- 执行与交互
  - -s：流式输出
  - -hm：启动即人工可介入
  - -im enhanced：交互模式为增强（含规划与记忆）
  - --tui：启用 TUI
  - --web-console：启用浏览器 Web Console；可写 `--web-console 0.0.0.0:18000[:password]`
  - --web-terminal：启用 Web Terminal；可写 `--web-terminal '0.0.0.0:8818 mysecret'`
  - -l：启动后立即进入循环
  - --loop/--loop-msg：进入循环注入首条消息
  - --seed 12345：固定随机种子
  - --sys-tips：自定义系统提示
  - --icmd：启动时执行的初始命令
  - --no-history：禁用历史记录加载
  - --exit-on-completion：任务完成后自动退出
- 配置与模板
  - --config config.yaml：从`config.yaml`加载项目配置
  - --template-dir ./templates：指定模板目录为`./templates`
  - --template-overwrite：渲染模板时允许覆盖
  - --template-cfg-override：从 YAML 文件覆盖模板配置
  - --output unity_test：输出目录名`unity_test`
  - --override '...': 覆盖配置键值（点号路径=值，多项用逗号分隔；字符串需内层引号，整体用单引号包裹以保留引号），示例里设置了会话摘要上限、启用裁剪、文档语言为"中文"、模型名为 gpt-4o-mini
  - -gif/--gen-instruct-file GEMINI.md：在 `<workspace>/GEMINI.md` 下生成外部协作引导文件
  - --guid-doc-path ./output/Guide_Doc：自定义 Guide_Doc 目录为`./output/Guide_Doc`
  - --use-skill：启用技能 SKILL
  - --backend：指定后端
  - --emulate-config：仅模拟配置过程
- 计划与 ToDo
  - --use-todo-tools：启用 ToDo 工具及强制附带 ToDo 信息
- 外部与嵌入工具
  - --ex-tools 'SqThink,AnotherTool'：启用外部工具`SqThink,AnotherTool`
  - --no-embed-tools：禁用内置嵌入检索/记忆工具
- 日志
  - --log：开启日志文件
  - --log-file ./output/ucagent.log：指定日志输出文件为`./output/ucagent.log`
  - --msg-file ./output/ucagent.msg：指定消息日志文件为`./output/ucagent.msg`
- MCP Server
  - --mcp-server-no-file-tools：启动 MCP（无文件操作工具）
  - --mcp-server-host：Server 监听地址为`127.0.0.1`
  - --mcp-server-port：Server 监听端口为`5000`
- 阶段控制与安全
  - --force-stage-index 2：从阶段索引 2 开始
  - --skip 5 --skip 7：跳过阶段 5 和阶段 7
  - --unskip 7：取消跳过阶段 7
  - --nw ./output/Adder ./output/unity_test：限制仅`./output/Adder`和`./output/unity_test`路径可写
  - --ref：指定阶段参考文件
  - --append-py-path：添加 Python 路径
- Master API 与分布式
  - --as-master：作为 Master API 服务器启动
  - --master：连接到 Master API 服务器
  - --as-master-key：设置访问密钥
  - --as-master-password：设置 HTTP Basic Auth 密码
  - --export-cmd-api：导出 CMD API
- 上下文管理
  - --enable-context-manage-tools：启用上下文管理工具
- 版本与检查
  - --check 与 --version 会直接退出，未与运行组合使用
  - --upgrade：升级 UCAgent

## 环境变量说明

UCAgent 支持通过环境变量配置各类参数，环境变量优先级高于配置文件设置。

### 模型配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `OPENAI_MODEL` | OpenAI 对话模型名称 | 无（需配置） |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 无（需配置） |
| `OPENAI_API_BASE` | OpenAI API 基础 URL | 无（需配置） |
| `OPENAI_TEMPERATURE` | OpenAI 模型 temperature 参数 | 未设置 |
| `OPENAI_TOP_P` | OpenAI 模型 top_p 参数 | 未设置 |
| `ANTHROPIC_MODEL` | Anthropic Claude 模型名称 | `claude-3-7-sonnet-20250219` |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | 无（需配置） |
| `GOOGLE_GENAI_MODEL` | Google Gemini 模型名称 | `gemini-2.5-pro` |
| `GOOGLE_GENAI_API_KEY` | Google 生成式 AI API 密钥 | 无（需配置） |

### 嵌入模型配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `EMBED_MODEL` | 向量嵌入模型名称 | 无（需配置） |
| `EMBED_OPENAI_API_KEY` | 嵌入模型 OpenAI API 密钥 | 无（需配置） |
| `EMBED_OPENAI_API_BASE` | 嵌入模型 OpenAI API 基础 URL | 无（需配置） |

### Langfuse 监控配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `ENABLE_LANGFUSE` | 是否启用 Langfuse 追踪监控 | `false` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse 公钥 | 无（需配置） |
| `LANGFUSE_SECRET_KEY` | Langfuse 密钥 | 无（需配置） |
| `LANGFUSE_URL` | Langfuse 服务地址 | `http://localhost:3000` |

### 对话摘要配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `SUMMARY_MAX_CTX_TOKEN` | 会话上下文最大 token 数 | `51200` |
| `SUMMARY_MAX_SUM_TOKEN` | 生成摘要的最大 token 数 | `1024` |
| `SUMMARY_MAX_KEEP_MSG` | 内存中保留的最大消息数 | `100` |
| `SUMMARY_TAIL_KEEP_MSG` | 传递给 LLM 的最近消息保留数 | `10` |

### LLM 限流配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `ENABLE_LLM_RATE_LIMIT` | 是否启用 LLM 请求限流 | `false` |
| `LLM_MAX_RPS` | LLM 最大每秒请求数 | `10` |

### LLM 辅助建议配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `ENABLE_LLM_FAIL_SUGGESTION` | 是否启用阶段失败智能建议 | `false` |
| `FAIL_SUGGESTION_MODEL` | 失败建议使用的模型名称 | 无（需配置） |
| `FAIL_SUGGESTION_API_KEY` | 失败建议 API 密钥 | 无（需配置） |
| `FAIL_SUGGESTION_API_BASE` | 失败建议 API 基础 URL | 无（需配置） |
| `FAIL_SUGGESTION_MFCOUNT` | 触发失败建议的最小失败次数 | `3` |
| `FAIL_SUGGESTION_TEMPERATURE` | 失败建议模型 temperature 参数 | 未设置 |
| `FAIL_SUGGESTION_TOP_P` | 失败建议模型 top_p 参数 | 未设置 |
| `ENABLE_LLM_PASS_SUGGESTION` | 是否启用阶段通过智能评审 | `false` |
| `PASS_SUGGESTION_MODEL` | 通过评审使用的模型名称 | 无（需配置） |
| `PASS_SUGGESTION_API_KEY` | 通过评审 API 密钥 | 无（需配置） |
| `PASS_SUGGESTION_API_BASE` | 通过评审 API 基础 URL | 无（需配置） |
| `PASS_SUGGESTION_TEMPERATURE` | 通过评审模型 temperature 参数 | 未设置 |
| `PASS_SUGGESTION_TOP_P` | 通过评审模型 top_p 参数 | 未设置 |

### 流程控制配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `HUMAN_CHECK_CK` | 验证复杂 DUT 时是否开启检测点人工检查 | `false` |
| `UC_ENV_CMD_BACKEND_EX_ARGS` | 命令行后端执行时的额外参数 | 无 |

### 测试工具配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `UC_TEST_RCOUNT` | 测试用例重复执行次数 | `3` |
| `UC_IS_IMP_TEMPLATE` | 是否为实现层测试模板 | `false` |
  - --hook-message：Hook 消息处理
- 说明
  - --mcp-server 与 --mcp-server-no-file-tools 二选一；此处选了后者带路径参数（如 --template-dir/--guid-doc-path/--nw 的路径）需实际存在，否则会报错
  - --override 字符串值务必带引号，并整体用单引号包住以避免 shell 吃掉引号（示例写法已处理）
