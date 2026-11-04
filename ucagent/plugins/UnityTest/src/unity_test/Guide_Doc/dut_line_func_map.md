
# 文件行与检查点映射

## 1. 目标与边界

逐行查漏补缺阶段建立“目标文档物理行 -> FG/FC/CK”的可追溯关系，用来发现功能规格和检查点缺口。当前阶段只处理 `Check`/`Complete` 返回的行块：

- 每条有功能意义的非空白行都必须映射到 `{OUT}/{DUT}_functions_and_checks.md` 中已经声明且语义准确的 `FG-*/FC-*/CK-*` 路径。
- 只有确实不描述 DUT 功能、接口、约束、状态、时序、异常或边界行为的非空白行，才能使用 `IGNORE/FC-*/CK-*`，并在同一映射行写明具体原因。
- 空白或只含空白字符的物理行无需映射。
- `MISSMT` 不是本阶段允许的结果。缺少 CK 时，应先依据规格补充正式 CK，再写正式映射。
- 目标文档是只读输入。不得为了通过映射校验而修改、重排、格式化或插入空行。

`Guide_Doc/` 文件只提供格式和方法，不属于逐行覆盖目标。实际目标文件、行号和原文以当前返回的 `current_line_block_contents` 或 `next_line_block_contents` 为准。

## 2. 规范映射格式

每个行块返回的 `map_file` 是该源文档唯一的规范映射文件。一个源文档跨多个批次时，始终累计更新同一个 `map_file`，不得自行创建带 `1_100`、`101_200` 等行号后缀的文件。

正式映射语法：

```text
FG-NAME/FC-NAME/CK-NAME: start-end, start-end
```

忽略映射语法：

```text
IGNORE/FC-NAME/CK-NAME: start-end # 该内容不具有 DUT 功能语义的具体原因
```

格式要求：

- 行号是从 1 开始的物理行号，区间包含起止值。
- 单行也必须写完整区间，例如源位置 `docs/interface.md:10-10` 在映射项中写作 `10-10`，不能只写 `10`。
- 多个离散区间用英文逗号分隔；同一个 CK 也可以分多行书写。
- 每个区间必须位于实际源文件范围内，不得超过当前阶段配置的行范围上限，也不得跨越本次审查的行块边界。
- 正式路径的三个标签必须与 `{OUT}/{DUT}_functions_and_checks.md` 的层级和拼写完全一致。
- 同一源行确实包含多个可独立激励、观测和判定的行为时，可以分别映射到多个准确 CK。
- `#` 开头的整行注释和映射文件中的空行会被忽略。

## 3. 完整规范示例

假设 `Check` 为 `docs/interface.md` 返回的唯一 `map_file` 是 `unity_test/line_map/docs_interface_md_line_func_map.txt`，源文件第 5 行为空白行。下面是该源文件完成全部批次后的完整映射文件；第 5 行不需要建立映射：

```text
# Target: docs/interface.md
# Canonical map_file: unity_test/line_map/docs_interface_md_line_func_map.txt

FG-INTERFACE/FC-REQUEST/CK-REQUEST-ACCEPT: 1-4
FG-INTERFACE/FC-RESPONSE/CK-RESPONSE-LATENCY: 6-8
IGNORE/FC-DOCUMENT/CK-METADATA: 9-9 # 文档修订日期，不描述 DUT 行为或验证约束
FG-RESET/FC-SYNCHRONOUS/CK-RESET-OUTPUT: 10-12
```

该示例只展示当前规范：文件路径来自 `map_file`，每个区间使用 `start-end`，空白源行未映射，`IGNORE` 带具体理由，且不存在临时缺口标签。

## 4. 每批执行流程

1. 读取当前行块的 `file`、`start_line`、`end_line`、`map_file` 和 `content`。`content` 只是当前行块，不是源文件全文。
2. 逐条判断非空白内容的功能语义。只有标题层级、表格表头、术语定义或前置说明不足以判断时，才使用 `ReadTextFile` 读取 `file` 指向的必要上下文。
3. 对功能内容选择 `{OUT}/{DUT}_functions_and_checks.md` 中语义准确的 CK。若规格确实揭示 CK 缺失或错误，先修正功能检查点文档，再同步迁移已有映射和工作区中的下游 CK 引用。
4. 把正式映射或带理由的 `IGNORE` 追加到当前行块指定的 `map_file`，然后调用 `Check`。当前批次通过后只处理返回的下一批；所有批次通过后调用 `Complete`。

修改 CK 是有条件的语义修复。映射文件缺失、语法错误、区间错误或 `IGNORE` 缺理由时，只修复诊断指出的映射问题，不应借此无关地重写 CK。

## 5. Checker 能确认和不能确认的内容

Checker 会机械确认：

- 映射文件是否为返回的规范 `map_file`；
- 映射语法、标签形状、物理行范围和区间长度是否合法；
- 正式 CK 是否存在于 `{OUT}/{DUT}_functions_and_checks.md`；
- `IGNORE` 是否带有行内理由；
- 当前行块的每个非空白物理行是否至少被覆盖一次；
- 已完成行块是否仍与当前源文档和映射一致。

Checker 不能确认：

- 一个形式上存在的 CK 是否真正对应源行语义；
- CK 描述是否遗漏触发条件、边界、状态、时序或预期可观测结果；
- `IGNORE` 理由是否符合真实规格；
- 同一行中的多个独立行为是否都映射到了各自 CK。

这些语义结论必须依据 Spec 和权威接口文档作出。实现可以帮助定位信号和可观测行为，但实现与 Spec 冲突时不能把 CK 改成迎合错误实现。

## 6. 失败诊断与确定修复

`Check`/`Complete` 失败时，先处理顶部 `failure_summary`，不要在文件未变化时重复调用。常用字段如下：

- `error_code`：稳定的问题类型。
- `artifact` 和 `location`：要修改的文件及准确位置；单行位置写作 `path:10-10`。
- `observed` 和 `expected`：实际问题与必须满足的条件。
- `next_action`：针对当前确定问题的直接修复动作。
- `uncovered_blocks` 和 `uncovered_content`：未覆盖区间及其全部非空白原文，仅在逐行覆盖缺口时出现。

按错误类型执行明确修复：

| `error_code` | 直接修复 |
| --- | --- |
| `LINE_MAP_FILE_MISSING` | 创建 `artifact` 指向的规范 `map_file`，写入当前行块映射。 |
| `LINE_MAP_IGNORE_REASON_MISSING` | 在 `location` 指向的映射行末添加 `#` 和具体忽略理由。 |
| `LINE_MAP_UNKNOWN_CK` | 核对标签拼写和层级；若规格确有缺口，先在功能检查点文档补充正式 CK，再替换映射路径。 |
| `LINE_MAP_UNCOVERED_LINES` | 使用 `uncovered_blocks` 和 `uncovered_content` 为全部非空白行补充准确 CK 或有理由的 `IGNORE`。 |
| `LINE_MAP_RANGE_FORMAT_INVALID`、`LINE_MAP_RANGE_INVALID` | 在 `location` 把区间改为合法且包含端点的 `start-end`。 |
| `LINE_MAP_RANGE_TOO_LARGE`、`LINE_MAP_RANGE_OUT_OF_BOUNDS` | 按返回的行块边界拆分或收窄 `location` 中的区间。 |
| `LINE_MAP_MISSMT_FORBIDDEN` | 补充或选定正式 CK，并用正式 `FG/FC/CK` 路径替换该项。 |
| `LINE_MAP_UNEXPECTED_FILE` | 将有效内容合并到 `expected` 指定的规范文件，再删除错误的分块命名文件。 |
| `LINE_MAP_PROGRESS_STATE_INVALID` | 重新读取受影响的当前源行块，修复规范映射后重新 `Check`。 |

错误详情中的文本摘录可能有界；`uncovered_content` 保留该诊断涉及的全部未覆盖非空白原文。只有语义依赖行块外上下文时才需要再次读取源文件。

## 7. 完成标准

本阶段完成时必须同时满足：所有返回的行块都已通过；每条非空白内容都有语义准确的正式 CK 映射或有事实依据的 `IGNORE`；不存在临时缺口标签、未知 CK、错误映射文件或失效进度；最后一次 `Complete` 成功。
