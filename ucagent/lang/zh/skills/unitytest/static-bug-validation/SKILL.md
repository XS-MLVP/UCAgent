---
name: static-bug-validation
description: 静态分析Bug验证与动态关联阶段专属技能,用于指导建立静态 Bug 与动态 Bug 的标签级追踪链接
---

# 静态分析Bug验证与动态关联

## 目标

本阶段的目标是逐个处理`{OUT}/{DUT}_static_bug_analysis.md`中的`<LINK-BUG-[BG-TBD]>`占位标签,通过动态测试给出验证结论,并将静态Bug与动态Bug建立稳定的一一或一对多追踪关系.

本技能提供两个脚本:
- `recordbug.py`: 将新证实的动态Bug按规范写入`{OUT}/{DUT}_bug_analysis.md`
- `linkbug.py`: 将静态Bug与动态Bug的关联关系回填到`{OUT}/{DUT}_static_bug_analysis.md`

这两个脚本分工如下:
- `recordbug.py`负责创建或更新动态Bug记录
- `linkbug.py`负责把静态Bug条目下的`<LINK-BUG-[BG-TBD]>`替换成最终结论

也就是说:
- 若当前静态Bug已经有可直接复用的动态Bug记录,可以直接调用`linkbug.py`
- 若当前静态Bug还没有动态Bug记录,则必须先调用`recordbug.py`,再调用`linkbug.py`

## 执行步骤

### 步骤1: 扫描待验证静态Bug

操作:
- 读取`{OUT}/{DUT}_static_bug_analysis.md`
- 列出所有仍然带有`<LINK-BUG-[BG-TBD]>`的`<BG-STATIC-*>`条目
- 明确每个静态Bug当前对应的:
  - 功能组`<FG-*>`
  - 功能点`<FC-*>`
  - 检测点`<CK-*>`
  - 源码定位`<FILE-*>`

注意:
- 只处理当前确认过的静态Bug,不要一次性随意修改整个文档
- 若某个静态Bug已经是`<LINK-BUG-[BG-NA]>`或已经关联到真实`BG-*`,说明它已经有结论,除非结论有误,否则不要重复处理

### 步骤2: 检查是否已有可复用的动态验证结果

操作:
- 检查`{OUT}/{DUT}_bug_analysis.md`
- 检查已有测试用例,尤其是Fail测试
- 判断当前静态Bug是否已经被某个动态Bug记录证实

判定规则:
- 若已经存在可以直接对应的动态Bug记录,则无需重复补写测试,直接进入步骤5进行链接回填
- 若尚无对应动态Bug记录,则进入步骤3编写或补充动态验证测试

注意:
- “可以直接对应”不是看名字像不像,而是要基于功能点、触发条件、失败现象、源码根因是否一致来判断
- 多个静态Bug允许对应同一个动态Bug
- 一个静态Bug也允许最终对应多个动态Bug

### 步骤3: 编写或补充动态验证测试

操作:
- 针对仍未确认的静态Bug,编写动态验证测试用例
- 测试文件写入`{OUT}/tests/test_{DUT}_static_verify_*.py`
- 测试函数命名格式为`test_static_{DUT}_<BugId>`
- 通过`from {DUT}_api import *`导入env fixture和API
- 若该静态Bug对应明确的`<CK-*>`,则在测试函数起始位置添加功能覆盖标记

注意:
- 测试目标是验证静态分析提出的缺陷是否真实存在
- 若验证结果是Fail且Fail合理,应保留该测试为Fail
- 不允许为了让测试通过而修改断言或弱化测试
- 若某个静态Bug本身是误报,则测试结果应支持其为误报的结论

### 步骤4: 形成动态Bug结论并写入动态Bug文档

操作:
- 运行动态验证测试
- 结合测试结果、功能预期、源码分析形成结论

结论分为两类:

1. Bug已证实
- 在`{OUT}/{DUT}_bug_analysis.md`中补充完整动态Bug记录
- 动态Bug标签形如`BG-XXX-90`
- 若一个静态Bug对应多个动态Bug,则应先把这些动态Bug都记录完整

2. 静态分析误报
- 不在`bug_analysis.md`中新增虚假的动态Bug
- 该静态Bug在`static_bug_analysis.md`中的关联标签应改为`BG-NA`

注意:
- 先有动态Bug记录,再回填静态Bug链接
- 不能先把静态Bug链接改掉,再回头补`bug_analysis.md`

当Bug已证实时,使用`RunSkillScript`执行`recordbug.py`,命令格式如下:

```bash
python3 script -BG 'BG-ADD-SPECIAL-VALUE-90' -TC 'TC-unity_test/tests/test_ALU754_arithmetic.py::test_add_special' -BD '+INF 与 -INF 相加时未返回 NaN，而是错误输出 0x00000000。' -ROOT '根因分析内容' -FILE 'ALU754_RTL/ieee_add.v:33-64' -FIX '修复建议内容'
```

其中:
- `script`替换为`recordbug.py`脚本路径
- `-BG`是动态Bug标签
- `-TC`是用于证实该Bug的失败测试用例标签
- `-BD`是Bug简述
- `-ROOT`是根因分析
- `-FILE`是关联源码位置
- `-FIX`是修复建议

注意:
- `recordbug.py`会把记录写入`{OUT}/{DUT}_bug_analysis.md`
- `linkbug.py`在写回真实`BG-*`前,会检查这些`BG-*`是否已经真实存在于`bug_analysis.md`
- 因此,若`recordbug.py`尚未成功执行,`linkbug.py`会拒绝把`BG-*`写回静态报告

### 步骤5: 使用脚本回填静态Bug链接

操作:
- 当某个静态Bug已经确定最终对应的动态Bug标签后,使用`RunSkillScript`执行`linkbug.py`
- 该脚本会同步更新两个位置:
  - `## 一、潜在Bug汇总`表格中的“动态Bug关联”列
  - `## 二、详细分析`中该`<BG-STATIC-*>`条目下的`<LINK-BUG-[...]>`标签

命令格式如下:

```bash
python3 script -SBG 'BG-STATIC-001-XXX' -LBG 'BG-ADD-XXX-90'
python3 script -SBG 'BG-STATIC-002-YYY' -LBG 'BG-NA'
python3 script -SBG 'BG-STATIC-003-ZZZ' -LBG 'BG-FSM-DEAD-92,BG-FSM-DEFAULT-85'
```

其中:
- `script`替换为`linkbug.py`脚本路径
- `-SBG`表示`static_bug_analysis.md`中原始静态Bug标签,必须是`BG-STATIC-*`
- `-LBG`表示要写回的链接目标:
  - 若Bug已证实,填写一个或多个真实动态Bug标签`BG-*`
  - 若静态Bug是误报,填写`BG-NA`
  - 若有多个动态Bug,使用英文逗号`,`分隔,脚本会写成`<LINK-BUG-[BG-1][BG-2]>`

执行`linkbug.py`前,脚本会做以下校验:
- `-SBG`必须真实存在于`{OUT}/{DUT}_static_bug_analysis.md`的汇总表和详细分析中
- 若`-LBG`不是`BG-NA`,则其中每个动态Bug标签都必须真实存在于`{OUT}/{DUT}_bug_analysis.md`
- 若任一校验失败,脚本会报错并停止,不会修改静态报告

### 步骤6: 检查替换结果

操作:
- 执行脚本后,重新检查目标静态Bug对应的两个位置是否已一致更新:
  - 汇总表的最后一列
  - 详细分析中的`<LINK-BUG-[...]>`

注意:
- 这两个位置必须完全一致
- 若脚本报错,根据报错修正参数后重试
- 已成功回填的静态Bug不需要重复执行

### 步骤7: 完成阶段收尾

操作:
- 重复步骤1到步骤6,直到所有`<LINK-BUG-[BG-TBD]>`都被替换
- 确认阶段结束时:
  - `static_bug_analysis.md`中不再存在任何`<LINK-BUG-[BG-TBD]>`
  - 所有已证实静态Bug都能在`bug_analysis.md`中找到对应动态Bug记录
  - 所有误报静态Bug都被标记为`BG-NA`

## 核心原则

- 1.**先验证,后回填**: 先确认动态验证结论,再更新静态Bug链接
- 2.**只改链接,不改Bug主体**: `linkbug.py`只修改指定静态Bug的链接标签与汇总表关联列,不改动其余正文
- 3.**两处同步**: 汇总表和详细分析中的链接结果必须保持一致
- 4.**真实关联**: 只有在`bug_analysis.md`中已有完整记录的动态Bug,才能写回真实`BG-*`
- 5.**误报显式标记**: 误报必须写为`BG-NA`,不能保留`BG-TBD`
- 6.**先记动态Bug,再回填静态Bug**: 新发现的动态Bug必须先通过`recordbug.py`写入`bug_analysis.md`,再通过`linkbug.py`建立关联
- 7.**脚本唯一入口**: `bug_analysis.md`中的新增动态Bug记录必须通过`recordbug.py`, `static_bug_analysis.md`中的链接回填必须通过`linkbug.py`,不要手工直接编辑

## 关键规则

- `-SBG`必须是`BG-STATIC-*`格式
- `-LBG`必须是以下两种之一:
  - 单个`BG-*`
  - 多个`BG-*`用英文逗号分隔
  - 或者`BG-NA`
- 汇总表中写入格式为:
  - `LINK-BUG-[BG-XXX-90]`
  - `LINK-BUG-[BG-XXX-90][BG-YYY-85]`
  - `LINK-BUG-[BG-NA]`
- 详细分析中写入格式为:
  - `<LINK-BUG-[BG-XXX-90]>`
  - `<LINK-BUG-[BG-XXX-90][BG-YYY-85]>`
  - `<LINK-BUG-[BG-NA]>`
- 一个`<BG-STATIC-*>`条目下应当只有一个`<LINK-BUG-[...]>`标签
- 若脚本发现目标静态Bug不存在,或者该条目下没有唯一可替换的`LINK-BUG`标签,必须报错并停止
- 若`-LBG`为真实动态Bug标签,则这些标签必须先存在于`bug_analysis.md`

## `RunSkillScript`使用说明

1. 允许一次输入多条命令,可以先执行若干条`recordbug.py`,再执行对应的`linkbug.py`
2. 若前几条命令执行成功,后续某条失败,只需要修正失败命令以及其后未执行完成的命令,不需要重复执行已成功命令
3. 参数值必须使用单引号包裹,尤其是`-LBG`中有逗号时更需要加引号
4. 若一个静态Bug最终对应多个动态Bug,多个BG标签必须在同一条命令的`-LBG`里一次性给出
5. 若本轮需要新建动态Bug记录,推荐顺序是:
   - 先执行`recordbug.py`
   - 再执行`linkbug.py`

## 示例

### 示例1: 证实为单个动态Bug

```bash
python3 recordbug.py -BG 'BG-MUL-OVERFLOW-THRESHOLD-85' -TC 'TC-unity_test/tests/test_ALU754_arithmetic.py::test_mul_overflow' -BD '最大规格化数乘以 2.0 时未拉高 overflow，也未输出 +INF。' -ROOT '根因分析内容' -FILE 'ALU754_RTL/ieee_mul.v:47-50' -FIX '修复建议内容'
python3 script -SBG 'BG-STATIC-007-OVERFLOW-THRESHOLD' -LBG 'BG-MUL-OVERFLOW-THRESHOLD-85'
```

替换效果:
- 汇总表:
  - `LINK-BUG-[BG-TBD]` -> `LINK-BUG-[BG-MUL-OVERFLOW-THRESHOLD-85]`
- 详细分析:
  - `<LINK-BUG-[BG-TBD]>` -> `<LINK-BUG-[BG-MUL-OVERFLOW-THRESHOLD-85]>`

### 示例2: 判定为误报

```bash
python3 script -SBG 'BG-STATIC-003-DENORMAL-LOSS' -LBG 'BG-NA'
```

替换效果:
- 汇总表:
  - `LINK-BUG-[BG-TBD]` -> `LINK-BUG-[BG-NA]`
- 详细分析:
  - `<LINK-BUG-[BG-TBD]>` -> `<LINK-BUG-[BG-NA]>`

### 示例3: 对应多个动态Bug

```bash
python3 recordbug.py -BG 'BG-FSM-DEAD-92' -TC 'TC-unity_test/tests/test_demo.py::test_static_demo_1' -BD '第一个动态Bug描述' -ROOT '根因分析1' -FILE 'rtl/demo.v:10-20' -FIX '修复建议1'
python3 recordbug.py -BG 'BG-FSM-DEFAULT-85' -TC 'TC-unity_test/tests/test_demo.py::test_static_demo_2' -BD '第二个动态Bug描述' -ROOT '根因分析2' -FILE 'rtl/demo.v:30-40' -FIX '修复建议2'
python3 script -SBG 'BG-STATIC-020-FSM-ISSUE' -LBG 'BG-FSM-DEAD-92,BG-FSM-DEFAULT-85'
```

替换效果:
- 汇总表:
  - `LINK-BUG-[BG-FSM-DEAD-92][BG-FSM-DEFAULT-85]`
- 详细分析:
  - `<LINK-BUG-[BG-FSM-DEAD-92][BG-FSM-DEFAULT-85]>`
