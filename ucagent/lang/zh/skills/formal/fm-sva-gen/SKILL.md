---
name: fm-sva-gen
description: 在 YAML 中编写 SVA 属性检测代码
---

# SVA 断言编写工作流

本技能指导如何将 `.formal_records.yaml` 中的 `sva_body` 占位符翻译为完整的 SVA 断言代码。

> **SVA 编码规范参见 `Guide_Doc/sva_property.md`**

## 核心原则：数据驱动同步

UCAgent 采用 **YAML 作为唯一事实来源 (SSOT)** 的架构。
1. **禁止直接修改 `.sv` 文件**：`checker.sv` 和 `wrapper.sv` 是由系统自动根据 YAML 渲染生成的只读产物。
2. **通过 YAML 更新代码**：使用 `update_sva_body.py` 技能脚本更新检测点的实现代码。
3. **自动同步**：当你调用 `Check` 工具进行验证时，系统会自动将 YAML 中的代码渲染到 `.sv` 文件中。

## 步骤

### 1. 逐条编写 SVA 代码

针对 `.formal_records.yaml` 中标记为 `[LLM-TODO]` 的 `sva_body` 字段，构思对应的 SVA 逻辑。

确认注释中标注的 Style（Assume / Seq / Comb / Cover），选择 `Guide_Doc/sva_property.md` 中对应的代码模板。

### 2. 使用工具更新 YAML

使用 `update_sva_body.py` 脚本将代码注入 YAML。

```bash
python3 .ucagent/skills/formal/fm-sva-gen/scripts/update_sva_body.py <CK-ID> "<SVA_CODE_BODY>"
```

**示例：**
```bash
python3 .ucagent/skills/formal/fm-sva-gen/scripts/update_sva_body.py CK-ADD-CORE-EQUATION "##0 ({cout, sum} == a + b + cin);"
```

### 3. 调用 Check 工具验证

调用 `ucagent.checkers.formal.PropertyStructureChecker`。
- 如果仍有检测点未填写，Checker 会报错并列出缺失项。
- 如果全部填写完成，Checker 会自动渲染生成最新的 `checker.sv` 和 `wrapper.sv` 供后续 EDA 工具使用。

## 核心规则

1. **禁止直接编辑 SV 文件**：任何手动对 `checker.sv` 的修改都会在下次 Check 时被覆盖。
2. **属性语法**：只需提供 `property` 内部的逻辑体，外层的 `property ... endproperty` 和标签实例化由模板自动生成。
3. **禁止 `|-> 1'b1` 占位符断言**：必须实现真实逻辑。
4. 每个逻辑行以 `;` 结尾。
5. **白盒信号处理**：如果需要引用内部信号，请先确保这些信号在 RTL 解析阶段已正确识别或在模板中已处理。
