
# 参数说明

## 参数与选项

UCAgent 的使用方式为：

```bash
ucagent <workspace> <dut_name> [options]
```

## 输入与输出

- workspace：工作目录。`workspace/<DUT_DIR>` 应是由 picker 导出的 DUT Python 包目录，并包含 README 和验证所需的源文件；例如 `workspace/Adder/`。
  - `workspace/<DUT_DIR>/README.md`：DUT 验证需求与目标
  - `workspace/<DUT_DIR>/*.md`：其他参考文件
  - `workspace/<DUT_DIR>/*.{v,sv,scala}`：源文件，用于进行 Bug 分析
  - 其他与验证相关的文件（例如：提供的测试实例、需求说明等）
- dut_name: 待测设计的名称，即 <DUT_DIR>，例如：Adder

### 输出

- 工作流会在工作区准备 `Guide_Doc/`，并按阶段生成 `<output>/tests/`、文档和测试报告；`uc_test_report/` 需要实际运行相应测试后才会出现。`<output>` 由 `--output` 指定，未指定时取工作流声明的 `output`（默认工作流为 `unity_test`）。

> 对输出的详细解释可以参考[结果分析与流程总结](../01_start/06_summary.md#工作区结构)

### 位置参数

| 参数      | 必填 | 说明                                                         | 示例     |
| :-------- | :--: | :----------------------------------------------------------- | :------- |
| workspace | 普通任务必填 | 工作目录，也可传本地 `.tar.gz` 或 HTTP(S) 压缩包 URL | ./output |
| dut | 普通任务必填 | DUT 名称（工作目录下的子目录名）；信息查询等入口无需指定 | Adder |

### 执行与交互

| 选项                 | 简写 | 取值/类型                  | 默认值   | 说明                                                          |
| :------------------- | :--- | :------------------------- | :------- | :------------------------------------------------------------ |
| --stream-output      | -s   | flag                       | 关闭     | 流式输出到控制台                                              |
| --human              | -hm  | flag                       | 关闭     | 启动时进入人工输入/断点模式                                   |
| --interaction-mode   | -im  | standard/enhanced/advanced | standard | 交互模式；enhanced 含规划与记忆管理，advanced 含自适应策略    |
| --tui                |      | flag                       | 关闭     | 启用终端 TUI 界面                                              |
| --web-console        |      | [host[:port]] [password]   | 关闭     | 启用浏览器 Web UI（独立模式）。默认 `localhost:8000`。**注意：仅提供 Web 界面，不提供本地命令行交互** |
| --web-terminal       |      | [host[:port]] [password]   | 关闭     | 启动 Web Terminal 服务器。默认 `127.0.0.1:8818`。**同时提供 Web 终端和本地命令行交互** |
| --loop               | -l   | flag                       | 关闭     | 启动后立即进入主循环（可配合 --loop-msg） |
| --loop-msg           |      | str                        | 空       | 进入循环时注入的首条消息                                      |
| --seed               |      | int                        | 随机     | 随机种子（未指定则自动随机）                                  |
| --sys-tips           |      | str                        | 空       | 覆盖系统提示词                                                |
| --icmd               |      | str（可多次）              | []       | 启动时执行的初始命令，可多次使用                              |
| --no-history         |      | flag                       | 关闭     | 禁用从工作目录加载历史记录                                    |
| --exit-on-completion | -eoc | flag                       | 关闭     | 任务完成后自动退出代理（Exit 工具调用成功后）                 |

`--web-console` 提供独立 Web 会话；`--web-terminal` 可与本地终端同时使用。例如：

```bash
ucagent --web-console '127.0.0.1:8000 mysecret'
ucagent ./output Adder --web-terminal '127.0.0.1:8818 mysecret'
```

Master 的 Dashboard、Launch、Task 和 Agent 页面见 [Web Master 使用指南](07_web_master.md)。

### 配置与模板

| 选项                    | 简写 | 取值/类型                  | 默认值     | 说明                                                            |
| :---------------------- | :--- | :------------------------- | :--------- | :-------------------------------------------------------------- |
| --workspace-base | | path | /tmp/ucagent_workspace_base | 压缩包工作区的解压基目录；有效工作区为 `<base>/<archive-name>/workspace` |
| --config                |      | path                       | 无         | 配置文件路径，如 `--config config.yaml`                         |
| --plugin                |      | name/path（可多次）        | []         | 激活已安装插件 ID 或本地插件项目路径                            |
| --plugin-workflow       |      | [plugin:]workflow          | 无         | 使用已激活插件声明的工作流配置层；可与 `--config` 同时使用      |
| --list-plugins          |      | flag                       | 否         | 列出 entry point 和 `plugin.search_paths` 可发现的插件后退出    |
| --validate-plugin       |      | name/path（可多次）        | []         | 校验插件清单、兼容性、依赖、命令和资源后退出                    |
| --template-dir          |      | path                       | 无         | 自定义模板目录                                                  |
| --template-overwrite    |      | flag                       | 否         | 渲染模板到 workspace 时允许覆盖已存在内容                       |
| --template-cfg-override |      | path（可多次）             | []         | 从 YAML 文件覆盖模板配置，可多次使用                            |
| --output                |      | dir                        | 工作流 `output` 声明 | 输出目录名                                                      |
| --override              |      | A.B.C=VALUE[,X.Y=VAL2,...] | 无         | 以点号路径覆盖配置，可重复使用；值按 Python 字面量解析，布尔值写 `True/False`，未解析的值作为字符串 |
| --gen-instruct-file     | -gif | file                       | AGENTS.md | 在 workspace 下生成外部 Agent 的引导文件（存在则覆盖）          |
| --guid-doc-path         |      | path（可多次）             | 无         | 选择自定义 Guide_Doc 目录或追加文件                   |
| --use-skill / --no-use-skill | | flag                       | 开启       | 显式启用/关闭技能 SKILL；未指定时使用配置值，内置配置默认开启 |
| --extra-skill-path      |      | path                       | 无         | 除默认 SKILL 外，额外使用指定路径下的 SKILL；不能与 `--no-use-skill` 同时使用 |
| --backend               |      | str                        | 无         | 指定后端（覆盖配置文件设置）                                    |
| --emulate-config        |      | flag                       | 否         | 仅模拟配置过程，不实际运行各阶段                                |

### 计划与 ToDo

| 选项             | 简写 | 取值/类型 | 默认值 | 说明                                                             |
| :--------------- | :--- | :-------- | :----- | :--------------------------------------------------------------- |
| --force-todo     | -fp  | flag      | 否     | 在 standard 模式下也启用 ToDo 工具，并在每轮提示中附带 ToDo 信息 |
| --use-todo-tools | -utt | flag      | 否     | 启用 ToDo 相关工具（不限于 standard 模式）                       |

ToDo 工具用于记录计划，不替代阶段验收。步骤索引从 1 开始，新建计划需要 2–20 步；工具用途见[工具列表](../03_develop/06_tool_list.md)。

### 外部与嵌入工具

| 选项             | 简写 | 取值/类型        | 默认值 | 说明                                      |
| :--------------- | :--- | :--------------- | :----- | :---------------------------------------- |
| --ex-tools       | -et  | name1[,name2...] | 无     | 逗号分隔的外部工具类名列表（如：SqThink），可多次使用 |
| --no-embed-tools |      | `true_or_false`（可省略值） | `true` | 禁用内置的检索/记忆类嵌入工具；裸参数或 `true` 表示禁用，传 `false` 才启用 |

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
| --mcp-server-no-file-tools |      | flag      | 否        | 启动 MCP Server，省略文件操作工具组；保留基础 `ReadTextFile` |
| --mcp-server-host          |      | host      | 127.0.0.1 | Server 监听地址                   |
| --mcp-server-port          |      | int       | 5000      | Server 端口；使用 -1 自动选择可用端口 |

### 阶段控制与安全

| 选项                | 简写 | 取值/类型       | 默认值 | 说明                                          |
| :------------------ | :--- | :-------------- | :----- | :-------------------------------------------- |
| --force-stage-index |      | int             | 0      | 指定运行时阶段索引；回退会重置该阶段及之后的已保存数据                        |
| --skip              |      | int（可多次）   | []     | 跳过指定阶段索引，可重复提供                  |
| --unskip            |      | int（可多次）   | []     | 取消跳过指定阶段索引，可重复提供              |
| --no-write          | -nw  | path1 path2 ... | 无     | 禁止写入指定文件或目录；路径必须位于 workspace 内，非通配路径必须已存在 |
| --ref               |      | str（可多次）   | []     | 指定阶段需读取的参考文件，格式：`[stage_index:]file_path1[,file_path2]` |
| --append-py-path    | -app | path（可多次）  | []     | 添加 Python 路径或文件用于模块加载            |

### Master API 与分布式

| 选项                | 简写 | 取值/类型     | 默认值 | 说明                                                              |
| :------------------ | :--- | :------------ | :----- | :---------------------------------------------------------------- |
| --as-master         |      | [ip[:port]]   | 关闭   | 作为 Master API 服务器启动；不指定地址则使用默认值                |
| --master            |      | host[:port] [key] | [] | 连接到 Master API 服务器，可指定 access_key，可多次使用           |
| --as-master-persist |      | [path]         | /tmp/ucagent_master | Master 使用持久化工作区目录（配合 --as-master 使用）   |
| --as-master-key     |      | str           | 无     | 客户端注册时需提供的访问密钥（配合 --as-master 使用）             |
| --as-master-password|      | str           | 无     | HTTP Basic Auth 密码保护 Master API（配合 --as-master 使用）      |
| --client-id         |      | str           | 无     | 连接 Master 时使用的客户端标识（配合 --master 使用）              |
| --export-cmd-api    |      | [ip[:port]][ passwd] | 关闭 | 启动 CMD API 服务器，默认 `127.0.0.1:8765`，可指定密码启用 HTTP Basic Auth |

### 上下文管理

| 选项                          | 简写 | 取值/类型 | 默认值 | 说明                                              |
| :---------------------------- | :--- | :-------- | :----- | :------------------------------------------------ |
| --enable-context-manage-tools |      | flag      | 关闭   | 启用上下文管理工具；适用于 API 模式等需要显式管理上下文的场景 |

### 版本与检查

| 选项          | 简写 | 取值/类型   | 默认值 | 说明                                                    |
| :------------ | :--- | :---------- | :----- | :------------------------------------------------------ |
| --check       |      | flag        | 否     | 检查默认配置、语言目录、模板与 Guide_Doc 是否存在后退出 |
| --version     |      | flag        |        | 输出版本并退出                                          |
| --upgrade     |      | [pip_args]  | 否     | 从 GitHub main 分支升级 UCAgent，可选传递 pip 额外参数  |
| --hook-message|      | str         | 无     | Hook continue/complete key 用于自定义提示处理（Code Agent 使用） |

### 示例

直接运行已准备的 DUT：

```bash
ucagent ./output Adder -s -hm --tui --loop
```

使用命令行后端，通过 MCP 调用验证工具：

```bash
ucagent ./output Adder --mcp-server-no-file-tools \
  --backend opencode -s -hm --tui --loop
```

临时覆盖配置：

```bash
ucagent ./output Adder --config config.yaml \
  --override 'runtime_options.need_ref_model=True' \
  --override 'conversation_summary.max_tokens=16384'
```

`--override` 在 YAML 加载之后处理，布尔值使用 Python 的 `True/False`；YAML 中则使用 `true/false`。每个参数内的逗号用于分隔赋值，不适合传入包含逗号的列表或字符串，这类值应写入配置文件。配置优先级和列表替换规则见[工作流配置](../03_develop/03_workflow.md#3-配置加载和模板变量)。

## 环境变量说明

UCAgent 支持通过环境变量配置各类参数。环境变量用于覆盖内置配置文件中的默认值；用户配置文件中显式写入的键以配置文件为准。

### 模型配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `OPENAI_MODEL` | OpenAI 对话模型名称 | 无（需配置） |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 无（需配置） |
| `OPENAI_API_BASE` | OpenAI API 基础 URL | 无（需配置） |
| `OPENAI_CONTEXT_SIZE` | 命令行后端所用模型的上下文窗口大小（token 数），渲染进各后端的上下文窗口配置；未设置时使用后端默认值 | 未设置 |
| `OPENAI_OUTPUT_SIZE` | 命令行后端所用模型的单次响应输出上限（token 数），仅 opencode/kilo 后端在已声明上下文窗口时生效 | 未设置 |
| `OPENAI_API_MODE` | LangChain 后端使用的 OpenAI API 模式：`auto`、`responses` 或 `chat_completions` | `auto` |
| `OPENAI_RESPONSES_PROBE_TIMEOUT` | 启动时 Responses API 能力探测超时秒数，必须为正数 | `10` |
| `OPENAI_REASONING_EFFORT` | LangChain 后端的思考程度；按当前 OpenAI 或兼容模型服务支持的字符串原样传递 | `xhigh` |
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
| `SUMMARY_MAX_CTX_TOKEN` | 触发压缩的预估上下文 token 上限；`0` 表示禁用该触发条件 | `204800` |
| `SUMMARY_MAX_SUM_TOKEN` | 每次生成摘要的输出 token 上限，必须大于 `0` | `8192` |
| `SUMMARY_MAX_KEEP_MSG` | 独立触发压缩的上下文消息数上限；`0` 表示禁用该触发条件 | `100` |
| `SUMMARY_TAIL_KEEP_MSG` | 传递给 LLM 的最近消息保留数 | `1` |

`SUMMARY_MAX_CTX_TOKEN` 和 `SUMMARY_MAX_KEEP_MSG` 是两个独立触发条件，任意一个超限都会压缩。上下文 token 在模型调用前属于预估值；运行过程中若模型服务返回 usage，LangChain 后端会使用最近一次实际输入 token 校准后续估算。`status` 中的 `ProviderTokens` 以 `input/output/total` 显示服务端累计 token，`Context` 显示当前预估值与阈值，`Compression` 显示最近一次压缩的原因和前后规模。

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

`ucagent/setting.yaml`中的`loop_settings.max_stalled_rounds`控制外部 Agent 循环的停滞保护，默认值为`0`（关闭）。只有人为通过配置文件或`--override loop_settings.max_stalled_rounds=VALUE`将它设为正整数时才会启用。启用后，只有一轮内实际调用了 Check/Complete，且阶段、Checker和Checker显式结构化诊断均与上一计数轮相同时才累计；阶段或批次推进、检查通过、诊断变化都会清零，无新检查的轮次不计数。达到阈值后 UCAgent 暂停`--loop`并等待人工处理，不退出任务、不修改产物，也不向`status`增加字段。其他值必须是非负整数。

### 测试工具配置

| 环境变量名 | 说明 | 默认值 |
| :-------- | :--- | :----- |
| `UC_TEST_RCOUNT` | 测试用例重复执行次数 | `3` |
| `UC_IS_IMP_TEMPLATE` | 是否为实现层测试模板 | `false` |
| `UC_SEED_MODEL` | 随机测试种子的获取模式：`manual`原样返回`test_utils.get_seed(seed)`传入的字面值；`random`返回全新随机种子；`time`按当前时间生成；`uniform:<min>:<max>`在闭区间内均匀取值；`normal:<mu>:<sigma>`按高斯分布取值并钳位到`[0, 2^31-1]`。非法取值会直接报错 | `manual` |
