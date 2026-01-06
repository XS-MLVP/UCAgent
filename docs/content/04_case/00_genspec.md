# 规范生成

## 工作流介绍

规范生成是 UCAgent 自定义工作流的一个案例,专门用于从分散的设计资料(如源码、文档、注释等)中提取、整理和生成结构化的功能规范文档。
通过修改`config.yaml`中的流程定义，达到了一个规范生成的效果。

如果有其他的自定义工作流的需求，可以参考[定制工作流（增删阶段/子阶段）](../03_develop/03_workflow.md#定制工作流增删阶段子阶段)来自定义阶段从而满足实际的需要。

### 应用场景

- **规范文档缺失**:芯片设计项目中常见源码完善但规范文档缺失或过时的情况
- **文档整合需求**:将分散在多处的设计说明、注释、会议记录等整合为统一规范
- **模块理解辅助**:通过自动生成的规范文档快速理解复杂设计模块
- **验证前准备**:在进行单元测试验证前,先生成完整的功能规范作为验证基准

### 工作流程

本流程采用六阶段流水线式工作流,每个阶段专注于特定的文档生成任务:

```
收集现有资料 → 源码增强 → 完善子规范 → 人工检查 → 功能规范分析 → 功能行映射
```

**`OUT`可自行配置，默认为`unity_test`**

#### 1. collect_existing_assets (收集现有资料，搭建主Spec)

**目标**:扫描并收集项目中所有可用的设计文档和说明材料

- 检查并读取 README.md、设计文档、注释等
- 将现有资料整理为初始规范框架
- 输出:`{OUT}/{DUT}_spec.md` 初始版本

**Checker**: `MarkDownHeadChecker` - 验证生成文档的 Markdown 标题结构是否规范

#### 2. augment_with_code (源码增强补全细节)

**目标**:逐个分析源码文件,从代码中提取设计意图并补充到规范文档

- 使用 `WalkFilesOneByOne` 策略逐文件分析
- 提取接口定义、状态机、关键逻辑等信息
- 将源码分析结果融入规范文档

**Checker**: `WalkFilesOneByOne` - 确保每个源文件都被遍历分析

#### 3. complete_subspecs (批量完善子规范)

**目标**:针对复杂模块,生成更细粒度的子模块规范文档

- 识别需要独立说明的子模块
- 在 `{OUT}/{DUT}/` 目录下生成子规范文档
- 批量验证所有子规范的结构完整性

**Checker**: `BatchMarkDownHeadChecker` - 批量检查所有子规范文档的标题结构

#### 4. human_check (人工综合检查)

**目标**:暂停流程,由人工审核并修正规范文档

- 支持编辑 `{DUT}_spec.md` 和子规范文档
- 人工补充 AI 可能遗漏的设计意图
- 修正 AI 理解偏差
- 最后在 TUI 中输入 `hmcheck_pass` 继续流程

**Checker**: `HumanChecker` - 等待用户确认后继续

#### 5. functional_specification_analysis (功能规范分析，提炼功能点与检测点)

**目标**:从规范文档中提取结构化的功能点标签

- 分析规范文档,生成 FG/FC/CK 功能标签体系
- 标注功能分组、功能点和检查点
- 输出:`{OUT}/unity_test/{DUT}_functions_and_checks.md`

**Checker**: `UnityChipCheckerLabelStructure` - 验证功能标签的结构和命名规范

#### 6. ref_function_line_map_generation (功能行映射生成，参考检查点新检查点差异分析)

**目标**:建立功能点与源码行的对应关系

- 分析源码,将功能点映射到具体代码行
- 生成可追溯的功能-代码映射表
- 用于后续覆盖率分析和测试规划

**Checker**: `FileLineMapChecker` - 验证映射文件的差异和完整性

## 使用规范生成流程

### 前置条件

**`workspace`为工作目录，可自行选择**

1. **准备设计模块**

   - 将待分析的 RTL 代码放入 `workspace/{DUT}/` 目录
   - 将现有的各种文档放入`{DUT}/docs/` 或 README 中
   - 新生成的 `spec` 文档会输出到 `workspace/{OUT}/`

2. **创建 GenSpec 配置**
   - 在模块目录下创建 `genspec.yaml` 配置文件
   - 也可使用默认配置直接启动

### 快速开始

以下命令均在`examples`目录。
执行为`ucagent`是已经安装为命令后。
如果未安装命令，则执行命令（项目内运行）应为：

```bash
python3 ../ucagent.py ...
```

以 Adder 模块为例:

```bash
# 1.准备环境（创建output目录和现有模块与文档）
mkdir output

# 2.移动现有RTL和文档
cp -r examples/GenSpec/Adder output/

# 3. 启动 GenSpec 流程 (使用 MCP 集成模式)
ucagent output/ Adder --config examples/GenSpec/genspec.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools --guid-doc-path examples/GenSpec/SpecDoc/dut_spec_template.md 

# 或者直接启动 TUI 模式
ucagent output/ Adder --config examples/GenSpec/genspec.yaml -hm --tui -s --no-embed-tools -l --guid-doc-path examples/GenSpec/SpecDoc/dut_spec_template.md 
```

### 规范生成流程配置说明

规范生成流程使用独立的 `genspec.yaml` 配置文件自定义了一套规范生成流程，主要配置项包括:

```yaml
# 任务使命描述
mission: |
  根据提供的 {DUT} 源码和现有文档,生成完整的功能规范文档

# 禁用默认模板 (GenSpec 不需要测试代码框架)
template: ""

# 写保护目录 (防止误修改源码)
un_write_dirs:
  - "{DUT}/"

# TUI 配置
tui:
  output_lines: 50
  messages_height: 20
  layout_ratio: [3, 2]

# 阶段定义
stages:
  - name: collect_existing_assets
    label: 1-收集现有资料
    checker:
      - MarkDownHeadChecker:
          mode: check
          glob_or_file_path: "{OUT}/{DUT}_spec.md"
    # ... (其他配置)

  - name: augment_with_code
    label: 2-源码增强
    checker:
      - WalkFilesOneByOne:
          dir: "{DUT}"
    # ... (其他配置)

  # ... (其他阶段)
```

### 关键配置项说明

- **mission**: 定义 GenSpec 的总体任务目标,会影响各阶段的执行策略
- **template**: 设为空字符串,因为 GenSpec 专注于文档生成而非测试代码
- **un_write_dirs**: 保护源码目录不被修改,仅允许在输出目录生成文档
- **stages**: 定义六个阶段的执行顺序、Checker 和提示词模板

### GenSpec 输出结构

执行完成后,输出目录 (`output/`) 结构如下:

```
output/
├── {DUT}_spec.md              # 主规范文档
├── {DUT}/                     # 源码目录(只读)
│   ├── *.v / *.sv / *.scala  # RTL 源文件
│   └── ...
├── {DUT}/                     # 子规范目录(可选)
│   ├── submodule1_spec.md    # 子模块规范
│   └── submodule2_spec.md
└── unity_test/                         # 功能标签输出
    ├── {DUT}_functions_and_checks.md   # FG/FC/CK 标签清单
    ├── {DUT}_line_func_map.md          # 行与功能映射文档
    ├── {DUT}_line_map_analysis.md      # 行映射分析报告
    ├── {DUT}_spec_summary.md           # 文档检查摘要
    └── {DUT}_spec.md                   # 主规范文档

```

### 与 MCP Client 协作

GenSpec 支持通过 MCP 协议与外部 Code Agent 协作:

1. **配置 MCP Client** (以 Qwen Code 为例)

  ```json
  {
	  "mcpServers": {
		  "genspec": {
			  "httpUrl": "http://localhost:5000/mcp",
			  "timeout": 10000
		  }
	  }
  }
  ```

2. **启动 MCP Server**

  ```bash
  ucagent output/ Adder --config examples/GenSpec/genspec.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools --guid-doc-path examples/GenSpec/SpecDoc/dut_spec_template.md 
  ```

3. **在 MCP Client 中启动协作**

  在`output`文件夹启动code agent，然后输入提示词：

  ```
  > 请通过工具 RoleInfo 获取你的角色信息和基本指导,然后完成任务。使用工具 ReadTextFile 读取文件。你需要在当前工作目录进行文件操作,不要超出该目录。
  ```

4. **流程监控**

  在 UCAgent TUI 界面中可以实时查看:

  - 当前执行阶段
  - 工具调用情况
  - 文档生成进度


## 高级用法

### 自定义阶段提示词

在 `genspec.yaml` 中可以为每个阶段自定义提示词模板:

```yaml
stages:
  - name: collect_existing_assets
    doc: |
      **阶段目标**: 收集 {DUT} 的所有现有设计文档

      **执行步骤**:
      1. 读取 {DUT}/README.md
      2. 扫描 {DUT}/ 目录下的所有文档文件
      3. 整理为初始规范框架

      **输出要求**:
      - 文件路径: {OUT}/{DUT}_spec.md
      - 格式: Markdown,包含以下章节:
        - # 概述
        - # 功能描述
        - # 接口说明
        - # 设计细节
```

### 跳过特定阶段

使用环境变量控制阶段跳过:

```yaml
stages:
  - name: human_check
    skip: $(SKIP_HUMAN_CHECK: false)
```

启动时设置环境变量:

```bash
SKIP_HUMAN_CHECK=true make spec_Adder
```



## 常见问题

### Q1: 生成的规范不完整怎么办?

**A**: 规范生成流程设计了 `human_check` 阶段专门用于人工补充:

1. 在 `human_check` 阶段暂停时,手动编辑 `output/{DUT}_spec.md`
2. 补充 AI 遗漏的关键信息(如特殊约束、边界条件)
3. 在 TUI 中输入 `hmcheck_pass` 继续流程

### Q2: 如何提高规范生成质量?

**A**: 建议提供更丰富的输入材料:

- 在源码中添加详细注释
- 提供完善的 README.md 说明模块功能
- 如有设计文档(Word/PDF),转换为 Markdown 放入模块目录
- 在 `genspec.yaml` 的 `mission` 中明确特殊要求

### Q3: 支持哪些 HDL 语言?

**A**: 规范生成流程支持常见的硬件描述语言:

- Verilog (.v)
- SystemVerilog (.sv)
- Chisel/Scala (.scala)
- VHDL (.vhd, .vhdl)

源码分析依赖于 LLM 的代码理解能力,对语法无严格限制。

### Q4: 规范生成流程和默认的验证生成流程有什么区别?

**A**:

都是在 UCAgent 这个大框架下的工作流。只是一个用于文档生成，一个用于验证生成。可以通过修改`config.yaml`自行转换或者同时使用。

| 特性     | 规范生成      | 验证生成          |
| -------- | ------------------ | ---------------------------- |
| 目标     | 生成功能规范文档   | 生成并执行测试用例           |
| 输出     | Markdown 规范文档  | Python 测试代码 + 覆盖率报告 |
| 模板     | 无 (template: "")  | unity_test 模板              |
| 阶段数   | 6 (文档生成流水线) | 14+ (验证完整流程)           |
| 适用场景 | 规范缺失/文档整理  | 单元测试验证                 |

典型工作流: **先用规范生成流程生成规范 → 再用验证生成流程进行验证**

### Q5: 如何复用规范生成流程配置?

**A**:

1. **通用配置模板**: `examples/GenSpec/genspec.yaml` 可作为模板复用
2. **项目级配置**: 将 `genspec.yaml` 放在项目根目录,所有模块共享
3. **模块级定制**: 在 `examples/{DUT}/genspec.yaml` 中覆盖特定配置

优先级: 模块级 > 项目级 > 默认配置

### Q6: 规范生成流程能否增量更新规范?

**A**: 当前规范生成流程采用全量生成模式。增量更新建议流程:

1. 保存旧版本规范: `cp output/{DUT}_spec.md output/{DUT}_spec.md.backup`
2. 重新运行规范生成流程生成新规范
3. 使用 `diff` 或 Copilot Chat 比较变更:
   ```bash
   diff output/{DUT}_spec.md.backup output/{DUT}_spec.md
   ```
4. 手动合并保留的内容



