---
name: create-test-case-templates
description: 创建测试用例模板阶段专属技能,用于指导测试用例模板的创建以及格式规范
---

# 测试用例模板创建

## 测试用例模板示例
``` python
def test_basic_addition(env):
    """测试 基本加法功能

    测试场景:
        两个整数相加,例如: 2 + 3, -10+5, 0+0等

    """
    env.dut.fc_cover["FG-ADD"].mark_function("FC-BASIC", test_basic_addition, ["CK-NORM"])

    # TASK: 实现基本加法测试逻辑
    # 覆盖率模型约束

    assert False, "Not implemented"
```

## 执行步骤

### 步骤1
阅读`reference_files`中列举的文件

### 步骤2
直接使用`RunSkillScript`工具执行`create_template.py`脚本来创建所有的测试用例模板,不允许你自己写代码来创建测试用例模板

### 步骤3
直接使用`Complete`工具推进阶段,不要进行额外分析

## 注意

- 该阶段dut fixture为fake值，仅用于执行加速，因此请仅仅编写用例模板，不要去测试DUT
- 该阶段不会生成有效代码行覆盖率数据、测试报告等，因此请忽略相关错误提示
- 该阶段的目标是创建测试用例模板，因此请不要实现测试逻辑，只需要按照模板格式编写好测试用例的结构和注释即可
