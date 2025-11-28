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

| 参数      | 必填 | 说明                             | 示例     |
| :-------- | :--: | :------------------------------- | :------- |
| workspace |  是  | 运行代理的工作目录               | ./output |
| dut       |  是  | DUT 名称（工作目录下的子目录名） | Adder    |

### 执行与交互

| 选项               | 简写 | 取值/类型                  | 默认值   | 说明                                                          |
| :----------------- | :--- | :------------------------- | :------- | :------------------------------------------------------------ |
| --stream-output    | -s   | flag                       | 关闭     | 流式输出到控制台                                              |
| --human            | -hm  | flag                       | 关闭     | 启动时进入人工输入/断点模式                                   |
| --interaction-mode | -im  | standard/enhanced/advanced | standard | 交互模式；enhanced 含规划与记忆管理，advanced 含自适应策略    |
| --tui              |      | flag                       | 关闭     | 启用终端 TUI 界面                                             |
| --loop             | -l   | flag                       | 关闭     | 启动后立即进入主循环（可配合 --loop-msg），适用于直接使用模式 |
| --loop-msg         |      | str                        | 空       | 进入循环时注入的首条消息                                      |
| --seed             |      | int                        | 随机     | 随机种子（未指定则自动随机）                                  |
| --sys-tips         |      | str                        | 空       | 覆盖系统提示词                                                |

### 配置与模板

| 选项                 | 简写 | 取值/类型                  | 默认值     | 说明                                                            |
| :------------------- | :--- | :------------------------- | :--------- | :-------------------------------------------------------------- |
| --config             |      | path                       | 无         | 配置文件路，如--config config.yaml 径                           |
| --template-dir       |      | path                       | 无         | 自定义模板目录                                                  |
| --template-overwrite |      | flag                       | 否         | 渲染模板到 workspace 时允许覆盖已存在内容                       |
| --output             |      | dir                        | unity_test | 输出目录名                                                      |
| --override           |      | A.B.C=VALUE[,X.Y=VAL2,...] | 无         | 以“点号路径=值”覆盖配置；字符串需引号，其它按 Python 字面量解析 |
| --gen-instruct-file  | -gif | file                       | 无         | 在 workspace 下生成外部 Agent 的引导文件（存在则覆盖）          |
| --guid-doc-path      |      | path                       | 无         | 使用自定义 Guide_Doc 目录（默认使用内置拷贝）                   |

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
| --ex-tools       |      | name1[,name2...] | 无     | 逗号分隔的外部工具类名列表（如：SqThink） |
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
| --mcp-server-port          |      | int       | 5000      | Server 端口                       |

### 阶段控制与安全

| 选项                | 简写 | 取值/类型       | 默认值 | 说明                                          |
| :------------------ | :--- | :-------------- | :----- | :-------------------------------------------- |
| --force-stage-index |      | int             | 0      | 强制从指定阶段索引开始                        |
| --skip              |      | int（可多次）   | []     | 跳过指定阶段索引，可重复提供                  |
| --unskip            |      | int（可多次）   | []     | 取消跳过指定阶段索引，可重复提供              |
| --no-write / --nw   |      | path1 path2 ... | 无     | 限制写入目标列表；必须位于 workspace 内且存在 |

### 版本与检查

| 选项      | 简写 | 取值/类型 | 默认值 | 说明                                                    |
| :-------- | :--- | :-------- | :----- | :------------------------------------------------------ |
| --check   |      | flag      | 否     | 检查默认配置、语言目录、模板与 Guide_Doc 是否存在后退出 |
| --version |      | flag      |        | 输出版本并退出                                          |

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
             'conversation_summary.use_uc_mode=True,lang="zh",openai.model_name="gpt-4o-mini"' \
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
  - -l：启动后立即进入循环
  - --loop/--loop-msg：进入循环注入首条消息
  - --seed 12345：固定随机种子
  - --sys-tips：自定义系统提示
- 配置与模板
  - --config config.yaml：从`config.yaml`加载项目配置
  - --template-dir ./templates：指定模板目录为`./templates`
  - --template-overwrite：渲染模板时允许覆盖
  - --output unity_test：输出目录名`unity_test`
  - --override '...': 覆盖配置键值（点号路径=值，多项用逗号分隔；字符串需内层引号，整体用单引号包裹以保留引号），示例里设置了会话摘要上限、启用裁剪、文档语言为“中文”、模型名为 gpt-4o-mini
  - -gif/--gen-instruct-file GEMINI.md：在 `<workspace>/GEMINI.md` 下生成外部协作引导文件
  - --guid-doc-path ./output/Guide_Doc：自定义 Guide_Doc 目录为`./output/Guide_Doc`
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
- 说明
  - --check 与 --version 会直接退出，未与运行组合使用
  - --mcp-server 与 --mcp-server-no-file-tools 二选一；此处选了后者带路径参数（如 --template-dir/--guid-doc-path/--nw 的路径）需实际存在，否则会报错
  - --override 字符串值务必带引号，并整体用单引号包住以避免 shell 吃掉引号（示例写法已处理）
