---
name: static-bug-analysis
description: RTL源码静态Bug分析阶段专属技能,用于指导 static_bug_analysis.md 文件的编写以及格式规范
---

# 静态Bug分析

## 分析步骤：

对于 {DUT}_RTL 目录下的所有源文件(.v,.sv,.scals)，按照以下步骤，依次对每个源文件进行静态Bug分析：

### 步骤1: 逐检测点分析

对于待分析的一个源文件，结合{OUT}/{DUT}_functions_and_checks.md中的功能组<FG-*>,功能点<FC-*>和检测点<CK-*>,逐个<CK-*>检查源文件实现,系统排查常见设计缺陷：
- 状态机逻辑：状态枚举是否完整，转移条件是否正确，是否有孤立/死锁状态，default分支是否缺失
- 边界与溢出：算术运算溢出/下溢、位宽截断、有符号/无符号类型不匹配
- 时序逻辑：复位条件完整性、异步信号同步、竞争冒险、亚稳态
- 接口协议：valid/ready握手时序、数据有效窗口、读写使能逻辑
- 控制逻辑：优先级、互斥条件、未处理的输入组合
- 若源文件分析未发现潜在Bug，则跳过

对于存在潜在Bug的检测点<CK-*>,以下述结构记录其细节:
- `FG`: <CK-*>所属的<FG-*>, 必须是FG-前缀. 示例: FG-BASIC-ARITHMETIC
- `FGD`: 功能组描述,可直接复用{OUT}/{DUT}_functions_and_checks.md中的描述(10字以内)
- `FC`: <CK-*>所属的<FC-*>, 必须是FC-前缀. 示例: FC-SPECIAL-ADD
- `FCD`: 功能点描述,可直接复用{OUT}/{DUT}_functions_and_checks.md中的描述(10字以内)
- `CK`: 存在潜在Bug的检测点<CK-*>, 必须是CK-前缀. 示例: CK-ADD-ZERO-INPUT
- `CKD`: 检测点描述,可直接复用{OUT}/{DUT}_functions_and_checks.md中的描述(10字以内)
- `BG`: Bug标签，格式为BG-STATIC-NNN-NAME，其中NNN为三位数字递增(001开始,保持序号的连续)，NAME为简要描述. 示例: BG-STATIC-001-CARRY-INPUT
- `BD`: 潜在Bug的简要描述,描述中不允许存在空格
- `FILE`: 潜在Bug涉及的源文件路径和相关代码的行数范围，格式为"Adder_RTL/文件.v:L1-L2",其中L1和L2分别是起始行和结束行,可以是单行或多行. 示例: "Adder_RTL/Adder.v:10-14"(代码务必高度相关且简洁,只列出与潜在Bug相关的代码)
- `CL`: Bug置信度,描述对该Bug存在的确信程度. 示例: "高"、"中"、"低"

### 步骤2: Bug记录

分析完一个源文件后，使用内置文本编辑工具按下方文档结构一次性记录该文件的所有潜在Bug，并同步维护汇总、详情和进度三个分区。若`RunSkillScript`可用，也可以用`record_static_bug.py`完成相同的批量写入；脚本不是创建或更新报告的前置条件。可选命令如下（其他参数值替换为每个Bug记录内容）:
```text
["unitytest/static-bug-analysis", "record_static_bug.py", "-FG 'FG' -FGD 'FGD' -FC 'FC' -FCD 'FCD' -CK 'CK' -CKD 'CKD' -BG 'BG' -FILE 'FILE' -BD 'BD' -CL 'CL'"]
["unitytest/static-bug-analysis", "record_static_bug.py", "-FG 'FG' -FGD 'FGD' -FC 'FC' -FCD 'FCD' -CK 'CK' -CKD 'CKD' -BG 'BG' -FILE 'FILE' -BD 'BD' -CL 'CL'"]
...
```

## 核心原则
- 1.**只改不删**: 检查发现错误需要进行修改时,只修改格式错误的部分,不能将格式错误的条目删除,只能修改(因为已经分析出了有潜在Bug,所以不能删除这个条目,只能这个条目的格式有错误需要修改)
- 2.**结构完整**: {OUT}/{DUT}_static_bug_analysis.md中共有3个栏目,唯一机器边界依次是`<STATIC-BUG-SUMMARY>`、`<STATIC-BUG-DETAILS>`、`<STATIC-BUG-PROGRESS>`。每个标记必须独占一行、恰好出现一次且顺序固定；中文标题只是展示文本，可以本地化。每次修改只在对应标记范围内追加或修改，不要删除、复制、改名或调换标记.
- 3.**一致性**: `潜在Bug汇总`和`详细分析`下的内容要相互一致,如果`潜在Bug汇总`中已经有了某个BG条目,则`详细分析`中必须有对应的BG条目,反之亦然.
- 4.**等价写入**: 首次创建完整报告时使用`EditTextFile(path, content)`；对已有报告添加或修正BG条目时使用`ReplaceStringInFile(path, old_string, new_string)`。也可使用可选脚本。无论采用哪种方式，都必须同步维护三个固定分区，重新读取目标段确认一致后再调用Checker.

## 关键规则
- 来源:所有 <FG-*>/<FC-*>/<CK-*> 必须来自 {OUT}/{DUT}_functions_and_checks.md；不存在的须先添加到{OUT}/{DUT}_functions_and_checks.md再使用
- 多Bug:一个 <CK-*> 下可以有多个 <BG-STATIC-*> 标签，每个代表一个独立Bug
- 每个 <BG-STATIC-*>（NULL除外）必须有且仅有一个 <LINK-BUG-[BG-TBD]> 子标签
- 每个 <LINK-BUG-[BG-TBD]> 必须有至少一个 <FILE-path:L1-L2> 子标签，并附上对应RTL源码片段
- FILE格式：<FILE-相对路径/文件.v:L1-L2>（相对workspace根目录，示例：rtl/dut.v:50-56）
- 所有 <FG-*>/<FC-*>/<CK-*> 标签必须与 functions_and_checks.md 中的定义完全一致（区分大小写）
- <BG-STATIC-NULL> 是唯一可以没有子标签的Bug条目,且仅用于表示在所有文件中都未发现任何Bug（不能应用于单文件没发现任何Bug）
- `批次分析进度`中必须使用<file>和</file>标签标记文件路径

## `{DUT}_static_bug_analysis.md` 文档结构(供修改参考)

```
# {DUT} RTL 源码静态分析报告

<STATIC-BUG-SUMMARY>

## 一、潜在Bug汇总

| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |
|------|---------|----------|----------|--------|----------|-------------|
| 001 | BG-STATIC-001-NAME | FG-XXX/FC-YYY/CK-ZZZ | Bug描述 | 高 | ALU754_RTL/ALU754.v | LINK-BUG-[BG-TBD] |

<STATIC-BUG-DETAILS>

## 二、详细分析

### <FG-XXX> 功能组描述
#### <FC-YYY> 功能点描述
##### <CK-ZZZ> 检测点描述
  - <BG-STATIC-001-NAME> Bug描述
    - <LINK-BUG-[BG-TBD]>
      - <FILE-ALU754_RTL/ALU754.v:xx-yy>
        ```verilog
        xx: ...
        yy: ...
        ```

<STATIC-BUG-PROGRESS>

## 三、批次分析进度

| 源文件 | 发现疑似Bug数 | 状态 |
|--------|---------------|------|
| <file>ALU754_RTL/ALU754.v</file> | 1 | ✅ 完成 |

```

本阶段检查发现问题需要修改时，依照上述模板使用文本编辑工具直接修正即可；可选脚本不是前置条件。务必遵守核心原则和关键规则，保证文档结构完整、内容一致、格式规范.

## 特殊情况说明

- 若未找到任何RTL源文件（黑盒验证场景），直接在{OUT}/{DUT}_static_bug_analysis.md中说明：无源文件可供静态分析，验证以黑盒方式进行，无需执行上述分析步骤
- 若在所有文件中都未发现任何Bug，使用<FG-NULL><FC-NULL><CK-NULL><BG-STATIC-NULL>链进行记录

## 可选`RunSkillScript`使用说明

1. `RunSkillScript`工具允许一次性输入多条命令,若有多个记录内容,则列出多条命令,命令中只允许使用定义的参数,禁止额外参数,且参数值必须符合格式要求,每个参数必须使用单括号''括起来.
2. 使用`RunSkillScript`工具时,若输入了10条命令行,前5条命令行执行正常,成功记录,但第6条命令执行失败时,根据反馈信息修改第6条命令以及后续命令中存在的相同问题,并且使用`RunSkillScript`工具重新执行第6条命令以及后续命令,已经成功的命令不需要重新执行,只需要执行未完成的命令.

没有`RunSkillScript`时，直接按Guide_Doc/dut_bug_analysis.md中的第 7.2 节和本技能的文档结构编辑报告；不得等待脚本、跳过批次或只写展示标题。
