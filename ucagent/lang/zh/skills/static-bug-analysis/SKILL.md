---
name: static-bug-analysis
description: RTL源码静态Bug分析阶段专属技能,用于指导{DUT}_static_bug_analysis.md文件的编写以及格式规范
---

# 静态Bug分析

## 按照以下步骤完成{DUT}的静态Bug分析任务，并将结果记录到{OUT}/{DUT}_static_bug_analysis.md中：

### 步骤1: 文件拷贝

创建 {OUT}/{DUT}_static_bug_analysis.md 文件(若已经存在,则清空里面已有内容), 并将 Guide_Doc/dut_static_bug_analysis.md 中的内容复制到 {OUT}/{DUT}_static_bug_analysis.md 中(必须是创建新文件并拷贝文件内容,禁止直接拷贝文件)，此步骤禁止添加额外的文件,以及禁止修改 {OUT}/{DUT}_static_bug_analysis.md 中任何内容。

### 步骤2: 逐源文件分析

对于{DUT}_RTL目录下的所有RTL源文件,逐一按照以下子步骤进行(分析并记录完一个源文件再进行下一个)：

#### 步骤2.1: 模块分析

读取源文件，理解模块功能与架构（模块层次、关键信号、状态机、数据流）,将分析结果(务必简洁)写进{OUT}/{DUT}_static_bug_analysis.md中对应的`架构概述`部分或在已有内容上进行追加.
更新{OUT}/{DUT}_static_bug_analysis.md中的`审查范围`一栏,在`审查文件列表`一栏中添加当前分析的源文件路径.

#### 步骤2.2: 逐检测点分析

结合{OUT}/{DUT}_functions_and_checks.md中的功能组,功能点和检测点，逐个<CK-*>检查RTL实现,系统排查常见设计缺陷：
- 状态机逻辑：状态枚举是否完整，转移条件是否正确，是否有孤立/死锁状态，default分支是否缺失
- 边界与溢出：算术运算溢出/下溢、位宽截断、有符号/无符号类型不匹配
- 时序逻辑：复位条件完整性、异步信号同步、竞争冒险、亚稳态
- 接口协议：valid/ready握手时序、数据有效窗口、读写使能逻辑
- 控制逻辑：优先级、互斥条件、未处理的输入组合

对于存在潜在Bug的检测点<CK-*>,以下述结构记录其细节:
- `FG`: <CK-*>所属的<FG-*>, 必须是FG-前缀. 示例: FG-BASIC-ARITHMETIC
- `FC`: <CK-*>所属的<FC-*>, 必须是FC-前缀. 示例: FC-SPECIAL-ADD
- `CK`: 存在潜在Bug的检测点<CK-*>, 必须是CK-前缀. 示例: CK-ADD-ZERO-INPUT
- `BG`: Bug标签，格式为BG-STATIC-NNN-NAME，其中NNN为三位数字递增(001开始,保持序号的连续)，NAME为简要描述. 示例: BG-STATIC-001-CARRY-INPUT
- `Bug_DESCRIPTION`: 潜在Bug的简要描述
- `FILE`: 潜在Bug涉及的源文件路径和相关代码的行数范围，格式为"Adder_RTL/文件.v:L1-L2",其中L1和L2分别是起始行和结束行,可以是单行或多行. 示例: "Adder_RTL/Adder.v:10-14"(代码务必高度相关且简洁,只列出与潜在Bug相关的代码)
- `CONFIDENCE`: Bug置信度,描述对该Bug存在的确信程度. 示例: "高"、"中"、"低"

#### 步骤2.3: Bug记录

每分析完一个RTL源文件,针对记录的潜在Bug的检测点<CK-*>,使用`CallSkillScript`工具,执行下述命令行(若有10个Bug,则列出10条命令,其中参数值替换为每个Bug记录内容,`DUT`为DUT名称,`target_file_path`为{OUT}/{DUT}_static_bug_analysis.md的路径):
```bash
python3 .ucagent/skills/static-bug-analysis/format.py -DUT DUT -TARGET_MD target_file_path -FG FG -FC FC -CK CK -BG BG -FILE FILE -Bug_DESCRIPTION Bug_DESCRIPTION -CONFIDENCE CONFIDENCE
python3 .ucagent/skills/static-bug-analysis/format.py -DUT DUT -TARGET_MD target_file_path -FG FG -FC FC -CK CK -BG BG -FILE FILE -Bug_DESCRIPTION Bug_DESCRIPTION -CONFIDENCE CONFIDENCE
...
```
使用`CallSkillScript`工具时,若有10个Bug待记录,前5个Bug的命令行执行正常,成功记录,但第6条命令执行失败时,根据反馈信息修改第6条命令以及后续命令中存在的相同问题,并且使用`CallSkillScript`工具重新执行第6条命令以及后续命令,已经成功的命令不需要重新执行,只需要执行未完成的命令,直至所有Bug记录完毕.

#### 步骤2.4: 进度更新

每完成一个源文件的分析工作,根据找到的潜在Bug对应的<CK-*>数量,更新{OUT}/{DUT}_static_bug_analysis.md中的`批次分析进度`一栏，记录源文件的分析结果.
`批次分析进度`一栏格式如下(源文件路径左右的`<file>`和`</file>`标签必须加上,不能遗漏!):
```
| <file>源文件路径</file> | 潜在Bug数量 | ✅ 完成 |
```

## 核心原则
- 原则1(**只改不删**): 检查发现错误需要进行修改时,只修改格式错误的部分,不能将格式错误的条目删除,只能修改(因为已经分析出了有潜在Bug,所以不能删除这个条目,只能这个条目的格式有错误需要修改)
- 原则2(**结构完整**): {OUT}/{DUT}_static_bug_analysis.md中共有5个栏目(`架构概述`,`审查范围`,`潜在Bug汇总`,`详细分析`,`批次分析进度`),每次修改只在对应栏目下进行追加或者修改操作,不要修改或删除其他栏目的内容,不要添加新的栏目,不要改变栏目顺序.
- 原则3(**一致性**): `潜在Bug汇总`和`详细分析`下的内容要相互一致,如果`潜在Bug汇总`中已经有了某个BG条目,则`详细分析`中必须有对应的BG条目,反之亦然.

## 关键规则
- 来源:所有 <FG-*>/<FC-*>/<CK-*> 必须来自 {OUT}/{DUT}_functions_and_checks.md；不存在的须先添加到{OUT}/{DUT}_functions_and_checks.md再使用
- 多Bug:一个 <CK-*> 下可以有多个 <BG-STATIC-*> 标签，每个代表一个独立Bug
- 每个 <BG-STATIC-*>（NULL除外）必须有且仅有一个 <LINK-BUG-[BG-TBD]> 子标签
- 每个 <LINK-BUG-[BG-TBD]> 必须有至少一个 <FILE-path:L1-L2> 子标签，并附上对应RTL源码片段
- FILE格式：<FILE-相对路径/文件.v:L1-L2>（相对workspace根目录，示例：rtl/dut.v:50-56）
- 所有 <FG-*>/<FC-*>/<CK-*> 标签必须与 functions_and_checks.md 中的定义完全一致（区分大小写）
- <BG-STATIC-000-NULL> 是唯一可以没有子标签的Bug条目

## `{DUT}_static_bug_analysis.md` 文档结构(供修改参考)

```markdown
# {DUT} RTL 源码静态分析报告

## 一、架构概述

（简要描述模块层次、数据流、关键设计单元）

## 二、审查范围

- 审查文件列表：...
- 对应功能测试点文档：{OUT}/{DUT}_functions_and_checks.md

## 三、潜在Bug汇总

| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |
|------|---------|---------|---------|--------|---------|------------|
| 001 | BG-STATIC-001-NAME | FG-XXX/FC-YYY/CK-ZZZ | Bug描述 | 高 | ALU754_RTL/ALU754.v | LINK-BUG-[BG-TBD] |

## 四、详细分析

### <FG-XXX> 功能组描述
####  <FC-YYY> 功能点描述
##### <CK-ZZZ> 检测点描述
  - <BG-STATIC-001-NAME> Bug描述
    - <LINK-BUG-[BG-TBD]>
      - <FILE-ALU754_RTL/ALU754.v:xx-yy>
        ```verilog
        xx: ...
        yy: ...
        ```
...（依次列出所有潜在Bug的详细分析）...
## 五、批次分析进度

| 源文件 | 发现疑似Bug数 | 状态 |
|--------|-------------|------|
| <file>ALU754_RTL/ALU754.v</file> | 4 | ✅ 完成 |

```

本阶段检查发现问题,需要修改时,依照上述模板的格式进行修改,并且务必遵守核心原则和关键规则,保证文档结构完整,内容一致,格式规范.

