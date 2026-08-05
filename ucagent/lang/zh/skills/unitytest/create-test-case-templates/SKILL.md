---
name: create-test-case-templates
description: 创建测试用例模板阶段专属技能，用于指导测试用例模板的创建、格式规范，以及在模板检查失败时依据 STDERR 区分模板错误与外部环境、fixture、依赖或配置错误
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
直接使用`RunSkillScript`工具执行`createtemplate.py`脚本来创建所有的测试用例模板,不允许你自己写代码来创建测试用例模板

### 步骤3
使用`Complete`工具推进阶段。若检查成功，结束本阶段；若检查失败，必须先按“检查失败处理”排查并解决非预期错误，再重新使用`Complete`，不得反复提交同一错误结果。

## 检查失败处理（必须）

模板阶段的预期结果是每个非忽略测试用例执行到以下占位断言并失败：

```python
assert False, "Not implemented"
```

对应的预期异常为`AssertionError('Not implemented')`。除此之外的`ERROR`、pytest收集失败或其他异常都不是合格的模板失败。

生成的模板出现非预期错误时，不要直接认定是模板内容写错。错误可能来自模板之外，例如被导入模块、fixture、fake DUT、API、参考模型、仿真环境、外部依赖、构建产物或配置。必须按以下顺序处理：

1. 优先阅读检查结果中的`STDERR`和完整traceback；若`STDOUT`包含更完整的pytest阶段信息，也一并查看。
2. 从最早的有效异常和对应栈帧开始定位真正所属文件或模块，不要只根据最终异常名判断责任归属。
3. 根据pytest阶段缩小范围：
   - collection/import错误：检查测试模块及其导入模块的语法、依赖、插件和配置。
   - setup错误：测试函数主体可能尚未执行，检查fixture、fake DUT或仿真环境初始化、依赖、构建产物和配置。
   - call错误：同时检查模板本身以及它调用的fixture对象、API、参考模型、DUT/仿真器和外部依赖。
   - teardown错误：检查fixture finalizer、资源释放、仿真器关闭和清理逻辑。
4. 仅当traceback明确指向生成的测试模板且违反本技能格式时，才修改模板；保持模板只包含结构、注释、覆盖率标记和末尾占位断言，不得提前实现测试逻辑。
5. 若根因位于模板之外，在当前任务权限内修复真正所属的文件、依赖或配置；无法在本阶段修复时，明确报告根因、关键`STDERR`和阻塞位置，不得通过删除导入、吞掉异常、移动或修改占位断言来掩盖问题。
6. 修复根因后重新运行检查，确认所有非忽略用例均以`AssertionError('Not implemented')`结束，再使用`Complete`推进阶段。

## 注意

- 该阶段dut fixture为fake值，仅用于执行加速，因此请仅仅编写用例模板，不要去测试DUT
- 该阶段不会生成有效代码行覆盖率或真实DUT行为结果，因此可以忽略仅与这些数据无效有关的提示；不得忽略pytest collection/import、fixture、setup/call/teardown异常或`STDERR`
- 该阶段的目标是创建测试用例模板，因此请不要实现测试逻辑，只需要按照模板格式编写好测试用例的结构和注释即可
