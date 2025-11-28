# 模板文件与生成产物

## 模板文件

在完整的完成一个验证任务之后，最终的结果都在`output`文件夹中，其中的内容如下：

  ```bash
  .
  ├── Adder  # 打包好的python DUT
  ├── Guide_Doc # 各种模板文件
  ├── uc_test_report # 跑完的测试报告，包含可以直接网页运行的index.html
  └── unity_test # 各种生成的文档和测试用例文件
      └── tests # 测试用例及其依赖
  ```

### Guide_Doc

`Guide_Doc`文件夹下是事先写好的模板文件，大模型会读取它来生成最后的代码和文档，可按照实际需要自行修改。

  - Guide_Doc：这些文件是“规范/示例/模板型”的参考文档，启动时会从`ucagent/lang/zh/doc/Guide_Doc`复制到工作区的 `Guide_Doc/`（当前以 output 作为 workspace 时即 `output/Guide_Doc/`）。它们不会被直接执行，供人和 AI 作为编写 unity_test 文档与测试的范式与规范，并被语义检索工具读取，在 UCAgent 初始化时复制过来。

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

## 生成产物

### uc_test_report

  - uc_test_report：由 toffee-test 生成的 index.html 报告，可直接使用浏览器打开。

    - 这个报告包含了 Line Coverage 行覆盖率，Functional Coverage 功能覆盖率，测试用例的通过情况，功能点标记具体情况等内容。

### unity_test/tests

由大模型根据`Guide_Doc`文件夹下的模板文件生成。生成的文件名前缀依据模块不同而不同，以下以`Adder`举例。

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

### unity_test/*.md

该目录下的各种.md文件也是大模型根据模板文件生成的。

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