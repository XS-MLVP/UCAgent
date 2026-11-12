
# 环境与属性结果分析

目标是核对当前工具结果与真实规格，修复错误的属性或环境，保留已复现的DUT缺陷。不能只因为字段齐全、输入合法或属性Fail，就认定RTL有Bug。操作数据完整示例见 `Guide_Doc/formal_data.md`。

## 分析路径

1. 等待RunFormal status显示当前输入已停止；工具错误按诊断处理，不修改验证目标绕行。
2. 技能可用且需要批量操作时，按Guide_Doc/formal_data.md加载ext/formal/data，通过原有RunSkillScript调用`formal_data.py prepare analysis`，取得精确队列、真实witness及ready_update。填写人工分析后写JSON请求文件并调用`update --request-file`，证据由技能验证并绑定。
3. 技能关闭或缺失时，Check协调当前条目，用ReadTextFile读取YAML与RunFormal evidence，再用普通文件工具填写人工字段并原样使用该属性的当前证据引用。不得手动去重、重编号、改机器状态或制造引用。
4. 首次FA分析在`analysis`描述当前观察与分类依据；归为RTL_BUG时一次填写`expected_requirement`及可选`reference_calculations`，用prepare返回的真实信号绑定执行参考计算，不另抄数字答案。结果随update返回，Bug和总结阶段直接复用，不重复读取反例或再执行同一计算；只有证据、参考表达式变化或发现矛盾时重新审阅。一次反例不证明所有输入的影响范围，普遍推断不能写成机器已证明事实。
5. 完成后记录阶段日志并Complete，Check仅用于实际诊断；派生`07_{DUT}_env_analysis.md`不直接编辑。

## 真、静态失败与未解决

| 工具结果 | 要做的工作 |
| --- | --- |
| `TRIVIALLY_TRUE` | 核对工具原因、前提可达性、约束与属性目标；正确恒等式可直接成立，不一律等于过约束 |
| `TRIVIALLY_FALSE` | 检查静态宽度/声明契约与常量传播，区分真实静态失败与错误属性；不强制改写为较弱动态目标 |
| `FALSIFIED` | 核对真实反例输入、参考计算、DUT实际输出和对应断言，完成归因 |
| `COVER_UNREACHABLE` | 核对可达目标是否适用、环境是否排除了合法行为；不可达不是自动RTL Bug |
| `UNPROVEN` | 尚无结论；按运行指南优化、重试或暂缓，不分类为Pass或Bug |

TT根因可选 `ASSUME_TOO_STRONG/SIGNAL_CONSTANT/WRAPPER_ERROR/DESIGN_EXPECTED`。当前正确恒等式可选动作 `ACCEPTED` 并说明 `DESIGN_EXPECTED`；仍出现的当前异常不能仅声明 `FIXED`。有合法组合被错误assume排除才放松约束；没有证据不能为了消除TT随意改写。`ACCEPTED`须说明验证目标仍有效，遵循当前阶段阈值，不靠修改文字制造证明。

## 类型化填写与批量诊断

`prepare analysis`对每个目标返回精确类型契约与最小补丁。FA断言只允许`id/prop_name/analysis/resolution/action_detail`；FA cover使用相同字段，但不能决定`RTL_BUG`。TT只允许`id/prop_name/analysis/root_cause/action/action_detail/related_assume`，不含`resolution`。

FA根因解释是`analysis`里的自由文本，TT的`root_cause`才是枚举；不要把Bug阶段的自由`root_cause`字段复制到FA请求。静态TrivF属于FA，仍依据真实静态失败分析。当前允许的FA决定为assert的`RTL_BUG/ENV_PENDING`、cover的`COVER_EXPECTED_FAIL/ENV_PENDING`。TT只有`DESIGN_EXPECTED`可与`ACCEPTED`配对；其它根因需修输入并重跑。

数据技能自动验证并附上当前证据，机器字段不可编辑。整批有错则不写任何条目，诊断`formal_data_review_invalid`给出各自位置与允许值，不通过重复提交同一个坏对象来试错。修完后重新提交当前哈希版本。一次更新后pending集合可能缩短；始终`prepare analysis --offset 0`重取，旧页偏移不是稳定身份。

## 失败归因

先问属性与参考计算是否正确，再问输入是否符合规格和DUT输出是否正确：

- 属性/参考计算错误：修复属性，重跑至通过，不登记DUT Bug。
- 规格确实禁止的环境输入：按规格补足输入约束，重跑，不能对DUT输出加assume掩盖行为。
- 输入合法、属性正确、DUT输出不符：使用真实工具证据记录 `RTL_BUG`。
- 尚未修复的环境/属性问题：`ENV_PENDING`，阻止推进；修复后取得新的运行结果；当前仍失败的条目不能仅填写 `ENV_FIXED` 冒充修复成功。
- Cover确实不适用或不可达：说明证据后记录 `COVER_EXPECTED_FAIL`，不能假装已经到达。

静态宽度失败可以通过规格与实际声明交叉核对，不需要编造动态witness。多个属性观察到同一缺陷时说明共享根因与各自证据，失败属性数不等于独立Bug数。

## 完整分析对象参考

下面是当前运行下一个已定位但尚未修复的属性问题的完整analysis对象。ID、名称与证据必须使用工具实际返回值；此例不含RTL_BUG，因此不伪造证据引用。

```yaml
analysis:
  tt_entries: []
  fa_entries:
    - id: FA-001
      prop_name: u_checker.A_CK_PACKET_ELIGIBLE
      analysis: 已核对真实输入和输出，当前属性将允许条件取反，与规格不符；该Fail来自属性错误。
      root_cause: null
      action: null
      action_detail: 修正资格条件表达式后重新RunFormal，确认当前目标通过。
      related_assume: null
      prop_type: assert
      sva_code: '(eligible == !request);'
      resolution: ENV_PENDING
```

使用数据技能请求时只提交允许修改的人工字段，`id/prop_name`用于精确定位；`prop_type/sva_code`由当前数据提供，不能在update中改写。最终Check仍会验证原始结果与证据，不能仅靠填写上述对象完成阶段。


## 完整派生报告参考

以下为一个已定位属性问题、尚未修复的完整报告布局。它是格式参考，不是当前任务证据。ENV_PENDING仍阻止阶段推进。

```markdown

# PacketGate 形式化验证环境分析报告

> 本文档由 `.formal_records.yaml` 自动生成，请勿手动编辑。

---

## 1. 验证结果概览

| 类型 | 数量 |
|------|------|
| Assert Pass | 0 |
| Assert TRIVIALLY_TRUE | 0 |
| Assert Fail | 1 |
| Cover Pass | 0 |
| Cover Fail | 0 |

---

## 2. TRIVIALLY_TRUE 属性分析

> 共 0 个 TRIVIALLY_TRUE 属性需要分析。

---

## 3. FALSE 属性分析

> 共 1 个 FALSE 属性需要分析。

### <FA-001> u_checker.A_CK_PACKET_ELIGIBLE

- **属性名**: u_checker.A_CK_PACKET_ELIGIBLE
- **属性类型**: assert
- **解决状态**: ENV_PENDING
- **反例/分析**: 已核对真实输入和输出；当前属性把资格条件取反，与规格不符，Fail来自属性错误。
- **修复说明**: 修正参考表达式，重新RunFormal并核对当前输入结果。
```
