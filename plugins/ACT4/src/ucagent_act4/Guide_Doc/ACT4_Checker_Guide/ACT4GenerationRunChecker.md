
# 来源策略检查

完整输入示例和输出约定见 `Guide_Doc/ACT4_Run_Guide.md`。

## 输入阶段

先完成独立 ISA 计划，再 Check action=discover、编写 selection.yaml、Check action=import。
评估九类，但不要求都有文件。已选源文件关联适用的 I 编号；未选时可留空文件和编号并写原因。共享输入缺失按配置 report/error，不生成替代品。本地缺源默认报错。补丁需精确基线和可应用性验证。
普通 Check/Complete 检查冻结的配置、选择文件、输入基线及原本地文件未变。
缺项时修复明确指出的来源选择，不能直接改 receipt；导入后改变选择必须新建工作区。

## 最终阶段

完成生成复验后，在 final.md 纳入 policies.md 的完整可见表、审查摘要和详细审查链接。
`policies.md` 已根据验收结果生成独立可见行，例如 `Finding scope: partial; fixed: 2; local pending: 1; external pending: 1.`；连同表格纳入报告，不必手算。没有待定项时为 `complete`；dismissed 不计入 fixed。模型实跑和覆盖结果另列，不以阶段全部完成代替问题关闭。
重生成类别不能声明 reuse；当前工作源码必须与复验一致。验证通过后自动发布 changes.patch。
配置只能表示期望，真正结果以九类 checklist 和实际命令证据为准。
