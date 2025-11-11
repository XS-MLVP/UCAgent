# 工具介绍

!!! info "说明"
随着芯片设计的愈发复杂，其验证难度和耗时也成倍增长，而近年来大语言模型的能力突飞猛进。于是我们推出了 UCAgent——一个基于大语言模型的自动化硬件验证 AI 代理，专注于芯片设计的单元测试(Unit Test)验证工作。

接下来我将从介绍、安装、使用、工作流、高级这五个方面来说明 UCAgent。

## 介绍

### 背景

- 芯片验证时间已经占据了芯片开发时间的 50-60%，并且设计工程师也将 49%的时间投入了硬件验证工作，但是 2024 年首次流片成功率仅有 14%。
- 随着 LLM 与编程类 Agent 兴起，将“硬件验证”抽象为“软件测试问题”可实现高比例自动化。

### UCAgent 是什么

- 面向芯片设计单元测试(Unit Test)的 AI Agent，基于 LLM 驱动，围绕“阶段化工作流 + 工具编排”自动/半自动完成需求理解、测试生成、执行与报告产出。
- 以用户为主导，LLM 为助理的协作式交互 Agent
- 以 Picker & Toffee 为基础，DUT 以 Python 包形式被测试；可与 OpenHands/Copilot/Claude Code/Gemini-CLI/Qwen Code/ 等通过 MCP 协议深度协作。

### 能力与目标

- 自动/半自动：生成/完善测试代码与文档、运行用例、汇总报告
- 完整：功能覆盖率、代码行覆盖率与文档一致性
- 可集成：支持标准 CLI、TUI；提供 MCP server 接口便于外部 Code Agent 接入
- 目标：有效减少用户在验证过程中的重复工作

## 安装

### 系统要求

- Python 版本： 3.11+
- 操作系统：Linux / macOS
- API 需求：可访问 OpenAI 兼容 API
- 内存：建议 4GB+
- 依赖：[picker](https://github.com/XS-MLVP/picker)（将 Verilog DUT 导出为 Python 包）

### 安装方式

- 方式一：克隆仓库并安装依赖

  ```bash
  git clone https://github.com/XS-MLVP/UCAgent.git
  cd UCAgent
  pip3 install .
  ```

- 方式二（pip 安装）
  ```bash
  pip3 install git+https://git@github.com/XS-MLVP/UCAgent@main
  ucagent --help # 确认安装成功
  ```

## 使用

### 快速开始

1. pip 安装 UCAgent

   ```bash
   pip3 install git+https://git@github.com/XS-MLVP/UCAgent@main
   ```

2. 准备 DUT（待测模块）

   - 创建目录：在`{工作区}`目录下创建`Adder`目录。(`{工作区}`是指当前运行`ucagent`命令的地方，其他的的目录都以`{工作区}`为根目录)
     - `mkdir -p Adder`
   - RTL：使用[快速开始-简单加法器](https://open-verify.cc/mlvp/docs/quick-start/eg-adder/)的加法器，将其代码放入`Adder/Adder.v`
   - 注入 bug：将输出和位宽修改为 63 位（用于演示位宽错误导致的缺陷）。

     - 将`Adder.v`第九行由`output [WIDTH-1:0] sum,`改为`output [WIDTH-2:0] sum,`，`vim Adder/Adder.v`。目前的 verilog 代码为：

       ```verilog
       // A verilog 64-bit full adder with carry in and carry out

       module Adder #(
           parameter WIDTH = 64
       ) (
           input [WIDTH-1:0] a,
           input [WIDTH-1:0] b,
           input cin,
           output [WIDTH-2:0] sum,
           output cout
       );

       assign {cout, sum}  = a + b + cin;

       endmodule
       ```

3. 将 RTL 导出为 Python Module
   > picker 可以将 RTL 设计验证模块打包成动态库，并提供 Python 的编程接口来驱动电路。参照[基础工具-工具介绍](https://open-verify.cc/mlvp/docs/env_usage/picker_usage/)和[picker 文档](https://github.com/XS-MLVP/picker/blob/master/README.zh.md)

   - 直接在`{工作区}`目录下执行命令`picker export Adder/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst`

4. 编写 README

   - 将加法器的说明、验证目标、bug 分析和其他都写在`Adder`文件夹的`README.md`文件中，同时将这个文件向`output/Adder`文件夹复制一份。

     - 将内容写入 readme 中，`vim Adder/README.md`，将下面内容复制到`README.md`中。
     - 复制文件，`cp Adder/README.md output/Adder/README.md`。
     - `Adder/README.md`内容可以是如下：

        ```markdown
        ### Adder 64 位加法器

        输入 a, b, cin 输出 sum，cout
        实现 sum = a + b + cin
        cin 是进位输入
        cout 是进位输出

        ### 验证目标

        只要验证加法相关的功能，其他验证，例如波形、接口等，不需要出现

        ### bug 分析

        在 bug 分析时，请参考源码：examples/MyAdder/Adder.v

        ### 其他

        所有的文档和注释都用中文编写
        ```

5. 安装 Qwen Code CLI

   - 直接使用`npm`全局安装`sudo npm install -g @qwen-code/qwen-code`。（需要本地有[nodejs 环境](https://nodejs.org/zh-cn/download/)）
   - 其他安装方式请参考：[Qwen Code 执行与部署](https://qwenlm.github.io/qwen-code-docs/zh/deployment/)

6. 配置 Qwen Code CLI

   - 修改`~/.qwen/settings.json` 配置文件，`vim ~/.qwen/settings.json`，示例 Qwen 配置文件如下：
   
    ```json
    {
    	"mcpServers": {
    		"unitytest": {
    			"httpUrl": "http://localhost:5000/mcp",
    			"timeout": 10000
    		}
    	}
    }
    ```

7. 启动 MCP Server<a id="命令"></a>

   - 在`{工作区}`目录下：
     ```bash
     ucagent output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
     ```

     ![tui界面](tui.png)



8. 启动 Qwen Code

   - 在`UCAgent/output`目录输入`qwen`启动 Qwen Code，看见 >QWEN 图就表示启动成功。
  
    ![qwen启动界面](qwen.png)

9. 开始验证

   - 在框内输入提示词并且**同意 Qwen Code 的使用工具、命令和读写文件请求**。（通过`j/k`控制上/下）提示词如下：
     > 请通过工具 RoleInfo 获取你的角色信息和基本指导，然后完成任务。请使用工具 ReadTextFile 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

   ![qwen-allow](qwen-allow.png)

   有时候 Qwen Code 停止了，但是我们不确定是否完成了任务，此时可以通过查看 server 的 tui 界面来确认。

   ![tui-pause](tui-pause.png)

   此时 Mission 部分显示阶段还在 13，所以我们还要让 Qwen Code 继续执行任务。

   ![qwen-pause](qwen-pause.png)

   中途停止了，但是任务没有完成，可以通过在输入框里输入“继续”来继续。

10.  结果分析<a id="详细输出"></a>

  最终的结果都在`output`文件夹中，其中的内容如下：

  ```bash
  .
  ├── Adder  # 打包好的python DUT
  ├── Guide_Doc # 各种模板文件
  ├── uc_test_report # 跑完的测试报告，包含可以直接网页运行的index.html
  └── unity_test # 各种生成的文档和测试用例文件
      └── tests # 测试用例及其依赖
  ```

  - Guide_Doc：这些文件是“规范/示例/模板型”的参考文档，启动时会从`vagent/lang/zh/doc/Guide_Doc`复制到工作区的 `Guide_Doc/`（当前以 output 作为 workspace 时即 `output/Guide_Doc/`）。它们不会被直接执行，供人和 AI 作为编写 unity_test 文档与测试的范式与规范，并被语义检索工具读取，在 UCAgent 初始化时复制过来。

    - dut_functions_and_checks.md  
      用途：定义功能分组 FG-、功能点 FC-、检测点 CK-\* 的组织方式与写法规范，要求覆盖所有功能点，每个功能点至少一个检测点。  
      最终要产出的对应物：unity_test/{DUT}\_functions_and_checks.md（如 `Adder_functions_and_checks.md`）。
    - dut_fixture.md  
      用途：说明如何编写 DUT Fixture/Env（包含接口、时序、复位、激励、监视、检查、钩子等），给出标准写法和必备项。  
      对应物：unity_test/DutFixture 与 EnvFixture 相关实现/文档。
    - dut_api_instruction.md  
      用途：DUT API 设计与文档规范（接口命名、参数、返回、约束、边界条件、错误处理、示例）。  
      对应物：unity_test/{DUT}\_api.md 或 API 实现+测试（如 `Adder_api.py`）。
    - dut_function_coverage_def.md  
      用途：功能覆盖（Functional Coverage）定义方法，如何从 FG/FC/CK 推导覆盖项、covergroup/coverpoint/bin 的组织与命名。  
      对应物：coverage 定义文件与生成的覆盖数据、以及相关说明文档，如`Adder_function_coverage_def.py`。

    - dut_line_coverage.md  
      用途：行覆盖采集与分析方法，如何启用、统计、解读未命中行、定位冗余或缺失测试。  
      对应物：行覆盖数据文件与分析笔记（unity_test/{DUT}\_line_coverage_analysis.md，如 `Adder_line_coverage_analysis.md`）。

    - dut_test_template.md  
      用途：测试用例的骨架/模板，给出最小可行的结构与编写范式（Arrange-Act-Assert、前后置、标记/选择器等）。  
      对应物：tests/ 下各具体测试文件的基本结构参考。
    - dut_test_case.md  
      用途：单个测试用例的撰写规范（命名、输入空间、边界/异常、可重复性、断言质量、日志、标记）。  
      对应物：tests/ 中具体 test_xxx.py::test_yyy 的质量基准与填写要求。

    - dut_test_program.md  
      用途：测试计划/测试编排（回归集合、分层/分阶段执行、标记与选择、超时控制、先后顺序、依赖关系）。  
      对应物：回归集配置、命令/脚本、阶段化执行策略文档。

    - dut_test_summary.md  
      用途：测试阶段性/最终总结的结构（通过率、覆盖率、主要问题、修复状态、风险/残留问题、下一步计划）。  
      对应物：unity_test/{DUT}\_test_summary.md（如`Adder_test_summary.md`） 或报告页面（`output/uc_test_report`）。

    - dut_bug_analysis.md  
      用途：Bug 记录与分析规范（复现步骤、根因分析、影响范围、修复建议、验证状态、标签与追踪）。  
      对应物：unity_test/{DUT}\_bug_analysis.md（如`Adder_bug_analysis.md`）。

  - uc_test_report：由 toffee-test 生成的 index.html 报告，可直接使用浏览器打开。

    - 这个报告包含了 Line Coverage 行覆盖率，Functional Coverage 功能覆盖率，测试用例的通过情况，功能点标记具体情况等内容。

  - unity_test/tests：验证代码文件夹

    - `Adder.ignore`  
      作用：行覆盖率忽略清单。支持忽略整个文件，或以“起止行段”形式忽略代码段。  
      被谁使用：`Adder_api.py` 的 `set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("Adder.ignore"))`。

      与 Guide_Doc 的关系：
      对应参考：`dut_line_coverage.md`（说明如何启用/统计/分析行覆盖，以及忽略规则的意义和使用场景）。

    - `Adder_api.py`  
      作用：测试公共基座，集中放 DUT 构造、覆盖率接线与采样、pytest 基础夹具（fixtures）和示例 API。

      - create_dut(request): 实例化 DUT、设置覆盖率文件、可选波形、绑定 StepRis 采样。
      - AdderEnv: 封装引脚与常用操作（Step）。
      - api_Adder_add: 对外暴露的测试 API，完成参数校验、信号赋值、推进、读取结果。
      - pytest fixtures：dut（模块级，负责覆盖率采样/收集交给 toffee_test）、env（函数级，给每个 test 一个全新环境）。

      与 Guide_Doc 的关系：

      - dut_fixture.md：夹具/环境（Fixture/Env）的组织、Step/StepRis 的用法与职责边界。
      - dut_api_instruction.md：API 设计（命名、参数约束、返回、示例、异常）和文档规范。
      - dut_function_coverage_def.md：如何将功能覆盖组接线到 DUT 并在 StepRis 内采样。
      - dut_line_coverage.md：如何设置行覆盖文件、忽略清单，并将数据上报给 toffee_test。

    - `Adder_function_coverage_def.py`  
      作用：功能覆盖定义（Functional Coverage），声明 FG/FC/CK 并给出 watch_point 条件。

      - 定义覆盖组：FG-API、FG-ARITHMETIC、FG-BIT-WIDTH。

    - 每组下定义 FC-_ 和 CK-_ 条件（如 CK-BASIC/CK-CARRY-IN/CK-OVERFLOW 等）。

      - get_coverage_groups(dut): 初始化并返回覆盖组列表，供 Adder_api.py 绑定与采样。

      与 Guide_Doc 的关系：

      - dut_function_coverage_def.md：覆盖组/覆盖点的组织方式与命名规范、watch_point 的表达方式。
      - dut_functions_and_checks.md：FG/FC/CK 的命名体系与映射关系来源，测试中用 mark_function 标记覆盖时需与此保持一致。

    - `test_Adder_api_basic.py`  
      作用：API 层面的基础功能测试，覆盖典型输入、进位、零值、溢出、边界等。

      - 使用 from Adder_api import \* 来获取 fixtures（dut/env）与 API。
      - 在每个测试中通过 env.dut.fc_cover["FG-..."].mark_function("FC-...", <test_fn>, ["CK-..."]) 标注功能覆盖命中关系。
        与 Guide_Doc 的关系：
      - dut_test_case.md：单测结构（目标/流程/预期）、命名与断言规范、可重复性、标记与日志。
      - dut_functions_and_checks.md：FG/FC/CK 的正确引用与标注。
      - dut_test_template.md：docstring 和结构写法的范式来源。

    - `test_Adder_functional.py`  
      作用：功能行为测试（接近“场景/功能项”的角度），比 API 基测覆盖更全面的功能点验证。

      - 同样通过 mark_function 与 FG/FC/CK 标签体系对齐。
        与 Guide_Doc 的关系：
        - dut_test_case.md：功能类测试的编写规范与断言要求。
        - dut_functions_and_checks.md：功能覆盖标注的规范与完整性。
        - dut_test_template.md：测试函数组织的范式。

    - `test_example.py`  
      作用：空白样例（脚手架），用于新增测试文件的最小模板参考。
      与 Guide_Doc 的关系：
      - dut_test_template.md：新建测试文件/函数时的结构、引入方式与标注方法的模板。

  - unity_test/\*.md：验证相关文档

    - Adder_basic_info.md

      - 用途：DUT 概览与接口说明（功能、端口、类型、粗粒度功能分类）。
      - 参考：`Guide_Doc/dut_functions_and_checks.md`（接口/功能分类用语）、`Guide_Doc/dut_fixture.md`（从验证视角描述 I/O 与 Step 时可参考）。

    - Adder_verification_needs_and_plan.md

      - 用途：验证需求与计划（目标、风险点、测试项规划、方法论）。
      - 参考：`Guide_Doc/dut_test_program.md`（编排与选择策略）、`Guide_Doc/dut_test_case.md`（单测质量要求）、`Guide_Doc/dut_functions_and_checks.md`（从需求到 FG/FC/CK 的映射）。

    - Adder_functions_and_checks.md

      - 用途：FG/FC/CK 真源清单，测试标注与功能覆盖定义需与此保持一致。
      - 参考：`Guide_Doc/dut_functions_and_checks.md`（结构/命名）、`Guide_Doc/dut_function_coverage_def.md`（如何落地为覆盖实现）。

    - Adder_line_coverage_analysis.md

      - 用途：行覆盖率结论与分析，解释忽略清单、未命中行、补测建议。
      - 参考：`Guide_Doc/dut_line_coverage.md`；配合同目录 tests 下的 `Adder.ignore`。

    - Adder_bug_analysis.md

      - 用途：缺陷分析报告，按 CK/TC 对应、置信度、根因、修复建议与回归方法撰写。
      - 参考：`Guide_Doc/dut_bug_analysis.md`（结构/要素）、`Guide_Doc/dut_functions_and_checks.md`（命名一致）。

    - Adder_test_summary.md
      - 用途：阶段性/最终测试总结（执行统计、覆盖情况、缺陷分布、建议、结论）。
      - 参考：`Guide_Doc/dut_test_summary.md`，与 `Guide_Doc/dut_test_program.md` 呼应。

11. 流程总结

要做什么：

- 将 DUT（如 Adder）打包为可测的 Python 模块
- 启动 UCAgent（可带 MCP Server），让 Code Agent 协作按阶段推进验证
- 依据 Guide_Doc 规范生成/完善 unity_test 文档与 tests，并以功能覆盖+行覆盖驱动测试
- 发现并分析缺陷，产出报告与结论

做了什么：

- 用 picker 将 RTL 导出为 Python 包（`output/Adder/`），准备最小 README 与文件清单
- 启动 `ucagent`（含 `--mcp-server`/`--mcp-server-no-file-tools`），在 TUI/MCP 下协作
- 在 Guide_Doc 规范约束下，生成/补全：
  - 功能清单与检测点：`unity_test/Adder_functions_and_checks.md`（FG/FC/CK）
  - 夹具/环境与 API：`tests/Adder_api.py`（`create_dut`、`AdderEnv`、`api_Adder_*`）
  - 功能覆盖定义：`tests/Adder_function_coverage_def.py`（绑定 `StepRis` 采样）
  - 行覆盖配置与忽略：`tests/Adder.ignore`，分析文档 `unity_test/Adder_line_coverage_analysis.md`
  - 用例实现：`tests/test_*.py`（标注 `mark_function` 与 FG/FC/CK）
  - 缺陷分析与总结：`unity_test/Adder_bug_analysis.md`、`unity_test/Adder_test_summary.md`
- 通过工具编排推进：`RunTestCases`/`Check`/`StdCheck`/`KillCheck`/`Complete`/`GoToStage`
- 权限控制仅允许写 `unity_test/` 与 `tests`（`add_un_write_path`/`del_un_write_path`）

实现的效果：

- 自动/半自动地产出合规的文档与可回归的测试集，支持全量与定向回归
- 功能覆盖与行覆盖数据齐备，未命中点可定位与补测
- 缺陷根因、修复建议与验证方法有据可依，形成结构化报告（`uc_test_report/index.html`）
- 支持 MCP 集成与 TUI 协作，过程可暂停/检查/回补，易于迭代与复用

典型操作轨迹（卡住时）：

- `Check` → `StdCheck(lines=-1)` → `KillCheck` → 修复 → `Check` → `Complete`
