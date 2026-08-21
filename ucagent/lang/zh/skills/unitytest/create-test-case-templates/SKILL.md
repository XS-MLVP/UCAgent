---
name: create-test-case-templates
description: 创建测试用例模板阶段专属技能，用于通过标准脚本生成正确的pytest参数签名、覆盖率标记和未实现占位断言，并依据STDERR区分模板错误与fixture、Mock、参考模型、依赖或配置错误
---

# 测试用例模板创建

## 模板参数契约

使用`RunSkillScript`执行`createtemplate.py`。脚本会自动生成正确的pytest函数签名；生成结果是本阶段的参数契约，不要自行推断或在生成后批量增加、删除、交换fixture参数。

普通DUT模板可能采用`def test_xxx(env):`或`def test_xxx(env, ref_model):`。若脚本生成了`ref_model`，它必须保持为第二个参数。普通DUT测试始终从`env`访问真实DUT；`mock_dut`只用于`test_api_{DUT}_mock_*`形式的Mock组件独立单元测试。本阶段不创建、不修改Mock测试，也不能把普通测试的`env`替换为`mock_dut`。

## 已提供基础设施的只读边界

本阶段只创建或修正普通测试模板。`{OUT}/tests/{DUT}_api.py`、`{OUT}/tests/{DUT}_function_coverage_def.py`以及其中的`create_dut`、`dut/env` fixture、`ucagent.is_imp_test_template()` fake DUT分支、`get_coverage_groups(dut)`、`dut.fc_cover`绑定、采样回调和coverage上报均是上游阶段已经完成的基础设施契约，禁止在本阶段修改、复制、替换或绕过。

尤其禁止下列做法：

- 在测试文件中重新定义`dut`/`env` fixture，或构造自定义fake DUT、空`fc_cover`、假CovGroup
- 为消除`KeyError`、setup错误或未标记CK而删除/延后`mark_function`，或把它包进忽略异常的代码
- 修改API模板、fake DUT返回路径、覆盖组名称、`fc_cover`绑定、`StepRis`采样或`set_func_coverage`，使Checker表面通过

`mark_function`失败时，先核对模板中的FG/FC/CK字符串是否逐字存在于当前功能文档和覆盖率定义，并读取最早traceback定位责任行。若证据明确指向上游基础设施，应报告准确文件、行号和不变量缺失，并回到对应API/fixture/覆盖率阶段修复；不得在本阶段就地改造提供的模板。

模板示例：

```python
def test_basic_addition(env):
    """测试基本加法功能。"""
    env.dut.fc_cover["FG-ADD"].mark_function(
        "FC-BASIC", test_basic_addition, ["CK-NORM"]
    )

    # TASK: 实现基本加法测试逻辑
    assert False, "Not implemented"
```

## 执行步骤

1. 阅读`reference_files`和当前批次CK，确认每个模板的测试意图。
2. 使用`RunSkillScript`执行`createtemplate.py`一次性生成模板；不允许自行编写另一套生成逻辑。
3. 检查生成结果：保留脚本生成的参数及顺序，确认覆盖率路径准确、TODO具体、最后一条语句为占位断言。
4. 使用`Complete`推进阶段；失败时先按下述流程定位真实原因。

## 模板边界

- 只写测试结构、docstring、具体TODO、`mark_function`和末尾占位断言。
- 不调用DUT API，不调用参考模型，不实现激励或预期计算。
- 所有非忽略模板必须执行到`assert False, "Not implemented"`并以`AssertionError('Not implemented')`结束。
- 不生成`test_api_{DUT}_*`和`test_api_{DUT}_mock_*`测试；这些测试属于此前独立阶段。
- 不能在普通模板中直接使用`mock_dut`或单独实例化Mock组件。
- 不修改`{DUT}_api.py`、`{DUT}_function_coverage_def.py`或任何已有fixture来适配新模板。

## 检查失败处理

除预期占位断言外，`ERROR`、pytest收集失败和其他异常都不是合格模板结果。

1. 先读`STDERR`、完整traceback和必要的`STDOUT`。
2. 从最早的有效异常定位责任文件，不要只看最终异常类型。
3. collection/import错误：检查测试模块、API模块、参考模型、Mock模块、依赖和配置。
4. setup错误：先检查新模板的导入、参数和FG/FC/CK字面量，再读取`env`、`ref_model`、fake DUT和覆盖组初始化的最早异常；这些文件可用于定位，但不得在本阶段改写。
5. call错误：确认失败是否确实来自末尾`Not implemented`；其他异常必须修复。
6. teardown错误：检查fixture finalizer、资源释放和清理逻辑。
7. 参数门禁失败时，重新运行`createtemplate.py`并保留其生成的fixture参数；不要手工改签名或规避Checker。
8. 修复后重新检查，直到所有非忽略模板只以预期占位断言失败。

## 完成条件

- 每个目标CK至少被一个准确模板关联。
- 所有普通模板保留`createtemplate.py`生成的`env[, ref_model]`参数契约。
- 普通DUT测试与Mock组件独立测试没有混用fixture类别。
- 提供的API模板、fake DUT路径、fixture和覆盖率定义保持不变，`env.dut.fc_cover`由原有fixture正常提供。
- 不存在导入、fixture、setup、teardown或配置错误。
- 没有提前实现测试，也没有移动、删除或吞掉占位断言。
