
# 文件行与检查点映射

## 背景说明

在验证活动中，仅依靠文档或用例列表难以确保功能覆盖到位。通过“文件行 ↔ 功能检查点 (CK)” 映射，我们可以：
- 快速定位某个 CK 对应的 RTL/文档行段；
- 评估哪些代码尚未映射到任何 CK；
- 在回归或评审中追踪缺口、忽略项与待办事项。

该映射既适用于 RTL 文件，也可扩展到第三方交付件、说明文档或脚本。映射文件通常与 `{DUT}_functions_and_checks.md` 搭配使用，形成从需求 → 功能点 → 检测点 → 代码行的完整闭环。

## 文件格式规范

映射文件可使用任意文本后缀。建议为每个目标文件维护独立映射，例如 `Adder_line_func_map.txt`。典型结构如下：

```bash
# Adder_line_func_map.txt
# 注释以 # 开头，空行自动忽略

# 语法: FG-NAME/FC-NAME/CK-NAME: start-end, start-end, ...
# 行号区间包含起止值；同一 CK 可对应多个离散区间，可分行重复书写。

FG-BASIC/FC-NORMADD/CK-OVERFLOW: 10-15, 20-20, 50-60
FG-BASIC/FC-NORMADD/CK-OVERFLOW: 100-200
FG-CARRY/FC-ADDCARR/CK-CARRY: 220-230

# IGNORE: 需说明忽略原因
IGNORE/FC-COMMENTS/CK-NONEDD: 500-600, 701-701 # 无效注释
IGNORE/FC-BLANK/CK-JUSTIGNOR: 801-810          # 空白区
IGNORE/FC-NONEED/CK-NOTCOMPLETE: 900-910       # 暂不关注

# MISSMT: 记录待补齐的检查点
MISSMT/FC-FUNC1/CK-EXPECTED: 1011-1022         # TODO: 补齐功能点
MISSMT/FC-FUNC2/CK-ASSERT:   1030-1042         # TODO: 补充断言
```

> **提示**：CK 命名应与 `dut_functions_and_checks.md` 保持一致；若出现临时命名，需明确标记处置计划。

注意：
- 行号区间统一写作 `start-end`（包含端点），多个离散区间用逗号分隔，例如 `100-200` 或 `100-200, 300-400, 679-890`。
- 单行映射也使用相同格式，例如 `12-12` 表示仅覆盖第 12 行；不允许省略结束值。
- 以下写法视为非法：仅写单个数字（如 `1`）、起止颠倒（如 `200-10`）、包含非数字字符或混合不同分隔符。

### 批处理行块与进度标记

逐行查漏补缺阶段使用 `UnityChipBatchTask` 将目标文件切分为行块。每个映射区间最多覆盖 100 行，超过该上限必须拆分为多个区间；空白或仅包含空白字符的行可以不映射，其他行不能遗漏。每个目标文件使用独立的映射文件，默认放在 `{OUT}/line_map/`，文件名由源文件相对路径安全化后加 `_line_func_map.txt` 后缀生成。

每完成一个行块，需要在 `{OUT}/{DUT}_line_map_progress.md` 中保留唯一进度标记。标记内容包含源文件和物理行范围：

```markdown
| <file>path/to/file.md:1-100</file> | 97 | 完成 |
```

进度标记只有在对应映射文件通过行范围、CK 标签和非空白行覆盖校验后才有效。源文件内容或行数变化会使受影响的旧行块失效，必须重新分析。`MISSMT/...` 只能用于中间记录，不能作为最终完成结果；`IGNORE/FC-*/CK-*` 必须在行末注释中说明具体忽略原因。逐行覆盖目标完全由 checker 的 `file_list` 决定；`Guide_Doc/` 只作为格式参考，不应配置到该列表中。

`Check` 和批次尚未全部完成时的 `Complete` 返回值会附带 `current_line_block_contents`，批次推进时还会附带 `next_line_block_contents`。两者都是行块列表，每个行块包含 `line_block`、`file`、`start_line`、`end_line` 和 `content`。`content` 是按物理行号升序排列的有序映射，键为物理行号，值为该行原文；空白行的值为空字符串。转换为 YAML 后示例如下：

```yaml
current_line_block_contents:
  - line_block: path/to/file.md:1-3
    file: path/to/file.md
    start_line: 1
    end_line: 3
    content:
      1: 第一行原文
      2: ''
      3: 第三行原文
```

未覆盖校验还会返回 `uncovered_lines`。`uncovered_blocks` 汇总连续物理行区间，`uncovered_content` 则按物理行号保存当前行块内全部未覆盖非空白行的原文：

```yaml
uncovered_lines:
  - line_block: path/to/file.md:1-100
    uncovered_line_count: 3
    uncovered_blocks:
      - 12-13
      - 20-20
    uncovered_content:
      12: 第十二行原文
      13: 第十三行原文
      20: 第二十行原文
```

`invalid_mappings[].details.error` 会按 Checker 的 `max_example_lines` 限制展示“物理行号: 原文”摘录，避免错误字符串过长；结构化的 `uncovered_content` 不受该摘录上限影响。通常可直接使用这些内容补齐映射，无需再次读取源文件。只有判断功能含义依赖跨行块的标题层级、表格表头、术语定义或前置说明时，才需要读取 `file` 指向的完整文件。

这些结构不为每行重复创建 `line` 和 `content` 字段，并避免把整个行块序列化成包含换行转义的长字符串。它们用于减少重复读取，但映射判断仍必须以源文件实际内容为准。

### 特殊前缀约定

| 前缀      | 适用场景                         | 必须说明的内容                          |
| ---------- | -------------------------------- | --------------------------------------- |
| `FG-*/FC-*/CK-*` | 正常功能、接口、异常等正式检查点 | 关联功能点与行号，必要时补充行为说明        |
| `IGNORE/FC-*/CK-*` | 需排除的行段（版权声明、空白、第三方 IP 等） | 忽略原因、是否会再次验证                  |
| `MISSMT/FC-*/CK-*` | 尚未建立正式 CK 的逻辑（缺口）   | 缺失原因、补齐计划、责任人或跟踪条目         |

## 书写注意事项

- 映射文件使用相对路径心智模型：同一目录下的命名保持统一，便于检索和自动化处理。
- 正式 CK 必须在 `{DUT}_functions_and_checks.md` 中声明；映射文件仅描述其覆盖行段。
- 对 `IGNORE`、`MISSMT` 等特殊条目，注释必须说明缘由与后续动作，避免“沉没成本”。
- 每次提交映射文件前，最好运行校验脚本（语法、行号范围、CK 是否存在），确保构建流程可自动解析。

## 最佳实践指南

### 1. 目录与命名
- 建议统一放置在 `{OUT}/line_map/`；文件命名 `{TargetFile}_line_func_map.txt`。
- 与 Spec、用例、脚本共用仓库管理，保持版本一致性。

### 2. 映射策略
- **自顶向下**：先按模块/功能块划分，再细化到具体逻辑，实现层次化管理。
- **行为导向**：优先覆盖可观测行为（输入、输出、状态变化、时序逻辑），帮助测试快速定位。
- **持续迭代**：先标注核心路径，逐步补齐细枝末节；必要时通过 `MISSMT` 标记待办。
- **忽略有据**：`IGNORE` 条目需说明具体原因（如工具生成、协议保留字段等），为评审提供背景。
- **缺口闭环**：`MISSMT` 条目需记录缺失的 CK 名称、预期补齐时间、负责人或 Issue ID。

### 3. 校验与度量
- 定期运行语法校验与行号有效性检查，避免解析失败。
- 覆盖率与回归报告需同步统计“未映射行块”和 `MISSMT` 清单，推动及时补齐。
- 若工具链支持，可在 CI 中自动提示新增/删除的 CK 是否已更新映射。

### 4. 协作与流程
- 映射文件与 Spec 变更应同步评审，确保功能描述、检查点与代码一致。
- 新增或调整 CK 时，及时更新映射文件，并通知用例/回归负责人调整计划。
- 对 `MISSMT` 条目建立跟踪机制（缺陷系统、自建表格等），直至补齐后移除。

### 5. 常见问题处理
- **重复逻辑**：注明“共享实现”并在 Spec 中解释引用关系，避免误以为缺失映射。
- **宏或生成代码**：必要时针对展开后文件单独建映射，或使用工具映射回原文件。
- **外部 IP**：若不在验证范围内，使用 `IGNORE` 并说明来源；若后续计划覆盖，则以 `MISSMT` 标记并列入计划。

## 示例：Adder 模块映射

```bash
# 文件: unity_test/line_map/Adder_line_func_map.txt
# 目标: 将 Adder.v 的关键行映射到既有 CK 标签，便于覆盖率与回归追踪

# 基本加法逻辑
FG-BASIC/FC-NORMADD/CK-BASIC:  12-28            # 主加法流程
FG-BASIC/FC-NORMADD/CK-ZERO:   29-36            # 输入为 0 的行为
FG-BASIC/FC-NORMADD/CK-NEG:    37-48            # 处理负数输入
FG-BASIC/FC-NORMADD/CK-OVFLW:  55-74, 120-132   # 溢出检测与异常处理

# 参数化配置
FG-PARAM/FC-WIDTH/CK-CONFIG:   85-95            # 数据位宽参数
FG-PARAM/FC-WIDTH/CK-LIMIT:    96-104           # 参数取值限制
FG-PARAM/FC-SIGN/CK-DEFAULT:   105-110          # 有符号/无符号默认

# 接口与复位
FG-IF/FC-HANDSHAKE/CK-READY:   145-166          # ready/valid 握手
FG-IF/FC-RESET/CK-SEQU:        170-188, 210-214 # 复位时序

# 调试与诊断
FG-DIAG/FC-ASSERT/CK-OVERFLOW: 190-203          # Overflow 断言
FG-DIAG/FC-FAULT/CK-INJECT:    204-209          # 错误注入处理

# 忽略区段
IGNORE/FC-COMMENT/CK-LEGAL: 5-10             # 版权声明
IGNORE/FC-GENIP/CK-VENDOR:  230-280          # 第三方 IP 逻辑
IGNORE/FC-DOC/CK-LEGEND:    300-320          # 工具生成文档

# 待补齐区段
MISSMT/FC-SAT/CK-SATURATE:  321-340          # 饱和运算待建 CK
MISSMT/FC-COV/CK-ASSERT:    350-360          # 断言待补齐
```

### 示例亮点
- **结构清晰**：按功能块分组，阅读与维护成本低。
- **注释到位**：每个条目均解释意图或忽略原因，评审时信息充分。
- **闭环管理**：`MISSMT` 清单显式展示缺口，并注明补齐计划。
- **可自动化**：命名规整，便于脚本解析与 CI 集成。

通过上述规范，可实现需求—规格—检查点—代码行的可追溯闭环，帮助团队高效识别覆盖缺口、评估验证质量并落实改进措施。
