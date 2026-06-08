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

分析完一个源文件后，使用`RunSkillScript`工具一次性记录该文件中所有的潜在Bug,命令行如下(其中`script`替换为`recordbug.py`脚本的路径,其他参数值替换为每个Bug记录内容):
```bash
python3 script -FG 'FG' -FGD 'FGD' -FC 'FC' -FCD 'FCD' -CK 'CK' -CKD 'CKD' -BG 'BG' -FILE 'FILE' -BD 'BD' -CL 'CL'
python3 script -FG 'FG' -FGD 'FGD' -FC 'FC' -FCD 'FCD' -CK 'CK' -CKD 'CKD' -BG 'BG' -FILE 'FILE' -BD 'BD' -CL 'CL'
...
```

## 核心原则
- 1.**只改不删**: 检查发现错误需要进行修改时,只修改格式错误的部分,不能将格式错误的条目删除,只能修改(因为已经分析出了有潜在Bug,所以不能删除这个条目,只能这个条目的格式有错误需要修改)
- 2.**结构完整**: {OUT}/{DUT}_static_bug_analysis.md中共有3个栏目(`潜在Bug汇总`,`详细分析`,`批次分析进度`),每次修改只在对应栏目下进行追加或者修改操作,不要修改或删除其他栏目的内容,不要添加新的栏目,不要改变栏目顺序.
- 3.**一致性**: `潜在Bug汇总`和`详细分析`下的内容要相互一致,如果`潜在Bug汇总`中已经有了某个BG条目,则`详细分析`中必须有对应的BG条目,反之亦然.
- 4.**脚本使用**: 仅能使用`RunSkillScript`工具来记录潜在Bug,不允许直接修改`{OUT}/{DUT}_static_bug_analysis.md`文件来添加或修改BG条目,且该文件的创建也必须通过脚本完成.

## 关键规则
- 来源:所有 <FG-*>/<FC-*>/<CK-*> 必须来自 {OUT}/{DUT}_functions_and_checks.md；不存在的须先添加到{OUT}/{DUT}_functions_and_checks.md再使用
- 多Bug:一个 <CK-*> 下可以有多个 <BG-STATIC-*> 标签，每个代表一个独立Bug
- 每个 <BG-STATIC-*>（NULL除外）必须有且仅有一个 <LINK-BUG-[BG-TBD]> 子标签
- 每个 <LINK-BUG-[BG-TBD]> 必须有至少一个 <FILE-path:L1-L2> 子标签，并附上对应RTL源码片段
- FILE格式：<FILE-相对路径/文件.v:L1-L2>（相对workspace根目录，示例：rtl/dut.v:50-56）
- 所有 <FG-*>/<FC-*>/<CK-*> 标签必须与 functions_and_checks.md 中的定义完全一致（区分大小写）
- <BG-STATIC-000-NULL> 是唯一可以没有子标签的Bug条目,且仅用于表示在所有文件中都未发现任何Bug（不能应用于单文件没发现任何Bug）
- `批次分析进度`中必须使用<file>和</file>标签标记文件路径

## `{DUT}_static_bug_analysis.md` 文档结构(供修改参考)

```
# {DUT} RTL 源码静态分析报告

## 一、潜在Bug汇总

| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |
|------|---------|----------|----------|--------|----------|-------------|
| 001 | BG-STATIC-001-NAME | FG-XXX/FC-YYY/CK-ZZZ | Bug描述 | 高 | ALU754_RTL/ALU754.v | LINK-BUG-[BG-TBD] |

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

## 三、批次分析进度

| 源文件 | 发现疑似Bug数 | 状态 |
|--------|---------------|------|
| <file>ALU754_RTL/ALU754.v</file> | 1 | ✅ 完成 |

```

本阶段检查发现问题,需要修改时,依照上述模板的格式进行修改,并且务必遵守核心原则和关键规则,保证文档结构完整,内容一致,格式规范.

## 特殊情况说明

- 若未找到任何RTL源文件（黑盒验证场景），直接在{OUT}/{DUT}_static_bug_analysis.md中说明：无源文件可供静态分析，验证以黑盒方式进行，无需执行上述分析步骤
- 若在所有文件中都未发现任何Bug，使用<BG-STATIC-000-NULL>条目进行记录

## `RunSkillScript`使用说明

1. `RunSkillScript`工具允许一次性输入多条命令,若有多个记录内容,则列出多条命令,命令中只允许使用定义的参数,禁止额外参数,且参数值必须符合格式要求,每个参数必须使用单括号''括起来.
2. 使用`RunSkillScript`工具时,若输入了10条命令行,前5条命令行执行正常,成功记录,但第6条命令执行失败时,根据反馈信息修改第6条命令以及后续命令中存在的相同问题,并且使用`RunSkillScript`工具重新执行第6条命令以及后续命令,已经成功的命令不需要重新执行,只需要执行未完成的命令.
