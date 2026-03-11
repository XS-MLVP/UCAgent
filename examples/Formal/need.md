# 需求：统一 Formal 验证工作流中的 CK 标签格式

## 背景

UCAgent 的核心标签解析器（`ucagent/util/functions.py` 中的 `get_unity_chip_doc_marks`）已统一使用 `<CK-` 前缀（横杠分隔）解析文档侧的检测点标签。然而 Formal 验证工作流中仍存在大量历史遗留的 `CK_`（下划线分隔）标签，导致文档侧标签与代码侧标签的一致性检查逻辑无法正确匹配。

**核心矛盾**：
- **文档侧（Markdown）**：UCAgent 标签体系要求使用 `<CK-XX>` 或 `<CK-XX-XX>` 格式。
- **代码侧（SystemVerilog/SVA）**：SV 标识符不支持横杠 `-`，必须继续使用 `CK_XX` 或 `CK_XX_XX`。
- **现状**：`formal_checkers.py` 中的 `PropertyStructureChecker` 直接用 `CK_` 正则表达式同时匹配文档和代码，无法处理这种差异。

## 目标

完成从 `CK_` 前缀到 `CK-` 前缀的文档侧迁移，并升级一致性匹配逻辑，使之在对比文档标签和代码实现时能正确进行名称转换。

---

## 详细变更范围

### 1. 标签格式定义

| 侧面 | 格式 | 示例 | 原因 |
|------|------|------|------|
| 文档侧 (Markdown) | `CK-` 前缀 + 横杠分隔 | `<CK-DATA-STABILITY>` | 与 UCAgent `<FG-*>`, `<FC-*>` 标签体系保持一致 |
| 代码侧 (SV/SVA) | `CK_` 前缀 + 下划线分隔 | `property CK_DATA_STABILITY;` | SystemVerilog 标识符不支持横杠 |

### 2. 一致性匹配逻辑升级

**修改文件**: `examples/Formal/scripts/formal_checkers.py`

#### 2.1 `PropertyStructureChecker._extract_property_details()`
- **当前**: 正则 `r'property\s+(CK_[A-Za-z0-9_]+)\s*;'` — 仅匹配 `CK_` 格式
- **保持不变**: 此方法解析 `.sv` 文件，代码侧始终使用 `CK_`，无需修改

#### 2.2 `PropertyStructureChecker.do_check()` 中的 Spec 解析
- **当前**: 正则 `r'<(CK_[A-Za-z0-9_]+)>'` — 仅匹配文档中的 `CK_` 格式
- **修改为**: `r'<(CK[-_][A-Za-z0-9_-]+)>'` — 同时兼容 `CK-` 和 `CK_`（向后兼容）

#### 2.3 名称标准化匹配
- 在对比文档标签（Spec）与代码实现（Implementation）时，增加标准化步骤：
  - 提取标签的核心内容（`CK-` 或 `CK_` 之后的部分）
  - 将文档标签中的 `-` 统一替换为 `_` 后，再与代码中的标签进行比对
- **示例**: 文档 `<CK-DATA-STABILITY>` → 标准化为 `CK_DATA_STABILITY` → 成功匹配代码中的 `property CK_DATA_STABILITY;`

### 3. 工作流配置更新

**修改文件**: `examples/Formal/formal.yaml`

需要将工作流描述文本中残留的 `<CK_...>` 引用统一替换为 `<CK-...>` 格式。受影响位置：

| 行号 | 当前内容 | 修改后 |
|------|----------|--------|
| L267 | `<CK_检查点>` | `<CK-检查点>` |
| L268 | `<CK_ADD_BASIC>` | `<CK-ADD-BASIC>` |
| L325 | `<CK_...>` | `<CK-...>` |
| L326 | `<CK_...>` 形式 | `<CK-...>` 形式 |

> **注意**: L225 `<CK-检测点名>` 已经是正确格式，无需修改。

### 4. 指导文档模板更新

#### 4.1 `FormalDoc/dut_functions_and_checks.md`

- 标签系统描述部分（L32-44, L50）：已经使用 `<CK-*>` 格式 ✅
- 但以下部分仍使用 `CK_` 格式，需要迁移：
  - L9, L54：`<CK_...>` 引用 → `<CK-...>`
  - L105-116：文档模板示例 `<CK_CHECK_A1_1>` → `<CK-CHECK-A1-1>`
  - L176-180：命名规范示例 `<CK_NORM_*>` → `<CK-NORM-*>`
  - L190-327：所有高级模式示例和 FIFO 完整示例中的 `<CK_...>` → `<CK-...>`

#### 4.2 `FormalDoc/dut_property_template.md`

- L3-4, L12, L49, L63 等：SVA 模板中引用 `<CK_NAME>` 的注释行
- **处理策略**: 注释中的 `<CK_NAME>` 改为 `<CK-NAME>`；代码中的 `property CK_NAME;` 和 `A_CK_NAME:` 保持不变

#### 4.3 `scripts/templates/checker_template.sv`

- 注释中的标签引用（如 L30 `<CK_FV_IDX_STABLE>`）改为 `<CK-FV-IDX-STABLE>`
- 代码中的 `property CK_FV_IDX_STABLE;` 和 `M_CK_FV_IDX_STABLE:` 保持不变

### 5. 其余 Checker 类影响评估

| Checker 类 | 是否需修改 | 说明 |
|------------|-----------|------|
| `EnvSyntaxChecker` | ❌ | 仅做 SV 语法检查，不涉及标签匹配 |
| `WrapperTimingChecker` | ❌ | 仅检查 clk/rst_n 端口 |
| `FormalScriptChecker` | ❌ | 仅检查 TCL 命令关键字 |
| `TclExecutionChecker` | ❌ | 仅执行 TCL 并检查日志 |
| `BugReportConsistencyChecker` | ⚠️ 可能 | L484 正则匹配 bug report 中的属性名，使用的是 `A_CK_XXX` 格式（代码侧），无需修改 |
| `CoverageAnalysisChecker` | ❌ | 仅解析 fanin.rep 覆盖率数据 |
| `EnvironmentDebuggingChecker` | ❌ | 使用 `parse_avis_log()` 解析日志，处理的是代码侧名称 |
| `ScriptGenerationChecker` | ⚠️ 间接 | 内部调用 `PropertyStructureChecker`，随其更新自动生效 |

---

## 执行计划

1. **修改 `scripts/formal_checkers.py`**：更新 `PropertyStructureChecker.do_check()` 中的 Spec 正则和匹配逻辑，增加 `-` → `_` 名称标准化
2. **修改 `formal.yaml`**：将 stage 描述文本中的 `<CK_...>` 替换为 `<CK-...>`
3. **修改 `FormalDoc/dut_functions_and_checks.md`**：将所有文档标签示例从 `<CK_...>` 迁移为 `<CK-...>`
4. **修改 `FormalDoc/dut_property_template.md`**：更新注释中的标签引用
5. **修改 `scripts/templates/checker_template.sv`**：更新注释中的标签引用（代码不变）
6. **验证修改**：确保 `get_unity_chip_doc_marks` 能正确解析新格式，`PropertyStructureChecker` 能正确匹配文档与代码的标签
