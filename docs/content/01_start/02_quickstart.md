# 使用

## 快速开始

**注：以下输出目录以`output`为例，可自行修改为其他目录**。

1. pip 安装 UCAgent

   ```bash
   pip3 install git+https://git@github.com/XS-MLVP/UCAgent@main
   ```

2. 安装 Qwen Code CLI

   - 直接使用`npm`全局安装`sudo npm install -g @qwen-code/qwen-code`。（需要本地有[nodejs 环境](https://nodejs.org/zh-cn/download/)）
   - 其他安装方式请参考：[Qwen Code 安装](https://qwenlm.github.io/qwen-code-docs/zh/#%E5%AE%89%E8%A3%85)

3. 准备 DUT（待测模块）

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

   - 当前的目录结构如下：
     ```bash
     {工作区}
     └── Adder
         └── Adder.v
     ```

4. 将 RTL 导出为 Python Module

   > picker 可以将 RTL 设计验证模块打包成动态库，并提供 Python 的编程接口来驱动电路。参照[基础工具-工具介绍](https://open-verify.cc/mlvp/docs/env_usage/picker_usage/)和[picker 文档](https://github.com/XS-MLVP/picker/blob/master/README.zh.md)

   - 直接在`{工作区}`目录下执行命令`picker export Adder/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst`

   - 当前的目录结构如下：
     ```bash
     {工作区}
     ├── Adder
     │   └── Adder.v
     └── output
         └── Adder # picker导出的Adder包
             ├── ...
             └── xspcomm
     ```

5. 编写 README

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

   - 当前的目录结构如下：
     ```bash
     {工作区}
     ├── Adder
     │   ├── Adder.v
     │   └── README.md
     └── output
         └── Adder # picker导出的Adder包
             ├── ...
             └── xspcomm
     ```

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

   - 配置文件解释：
   - `mcpServers`： MCP 服务器列表，这是一个对象，可以包含多个服务器的配置
   - `unitytest`：服务器标识，用于区分不同的 MCP 服务器，此处为 UCAgent 提供的 MCP 服务器
   - `httpUrl`：服务器地址，Qwen 将通过 HTTP 协议与该服务器通信。
     - `5000`为默认端口，可以在 MCP 服务器启动时配置，请参考[参数说明 MCP Server](../02_usage/03_option.md/#mcp-server)

7. 启动 MCP Server<a id="启动-mcp-server"></a>

   - 在`{工作区}`目录下：

   ```bash
   ucagent output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
   ```

   运行命令之后，可以看到“图 1:tui 界面”

   ![tui界面](./tui.png)

8. 启动 Qwen Code

   - **另开一个终端**，在`UCAgent/output`目录输入`qwen`启动 Qwen Code，看见 >QWEN 图就表示启动成功，如“图 2”所示。 ![qwen启动界面](./qwen.png)

9. 开始验证

   - 在框内输入提示词并且**同意 Qwen Code 的使用工具、命令和读写文件请求**。提示词如下：

   > 请通过工具 RoleInfo 获取你的角色信息和基本指导，然后完成任务。请使用工具 ReadTextFile 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

   ![qwen-allow](./qwen-allow.png)

   有时候 Qwen Code 停止了，但是我们不确定是否完成了任务，此时可以通过查看 server 的 tui 界面来确认，参照“图 4：tui‑pause”。

   ![tui-pause](./tui-pause.png)

   此时 Mission 部分显示阶段还在 13，所以我们还要让 Qwen Code 继续执行任务，参照“图 5：qwen‑pause”。

   ![qwen-pause](./qwen-pause.png)

   中途停止了，但是任务没有完成，可以通过在输入框里输入“继续”来继续。

**至此，“快速开始”基本完成，以下是生成内容的“结果分析”和对“快速开始”的整体“流程总结”。
如果需要验证自己的模块，可以参照流程总结中的[需要准备的文件](./02_quickstart.md/#需要准备的文件)**

---

## 结果分析

- 当前的目录结构如下：

  ```bash
  {工作区}
  ├── Adder
  │   ├── Adder.v
  │   └── README.md
  └── output
      ├── Adder # picker导出的Adder包
      │   ├── ...
      │   └── xspcomm
      ├── Guide_Doc # 各种模板文件
      ├── uc_test_report # 跑完的测试报告，包含可以直接网页运行的index.html
      └── unity_test # 各种生成的文档和测试用例文件
          └── tests # 测试用例及其依赖
  ```

  最终的结果都在`output`文件夹中，其中的内容如下：

- Guide_Doc：这些文件是“规范/示例/模板型”的参考文档，启动时会从`ucagent/lang/zh/doc/Guide_Doc`复制到工作区的 `Guide_Doc/`（当前以 output 作为 workspace 时即 `output/Guide_Doc/`）。它们不会被直接执行，供人和 AI 作为编写 unity_test 文档与测试的范式与规范，并被语义检索工具读取，在 UCAgent 初始化时复制过来。
  对文件的详细解读可参照[模板文件 Guide_Doc](../03_develop/00_template.md/#guide_doc)

- uc_test_report：由 toffee-test 生成的 index.html 报告，可直接使用浏览器打开。

  - 这个报告包含了 Line Coverage 行覆盖率，Functional Coverage 功能覆盖率，测试用例的通过情况，功能点标记具体情况等内容。

- unity_test/tests：验证代码文件夹
  对文件的详细解读可参照[生成的代码](../03_develop/00_template.md/#unity_testtests)

- unity_test/\*.md：验证相关文档
  对文件的详细解读可参照[生成的文档](../03_develop/00_template.md/#unity_test.md)

## 流程总结

### 需要准备的文件

- 待验证的源码，`verilog`或`chisel`均可，将其放于`{工作区}/{模块名}`文件夹下
- 源码对应的 SPEC，`md`格式，将其放于`{工作区}/{模块名}`文件夹下

以`Adder`模块举例：

```bash
{工作区}
└── Adder
    ├── Adder.v
    └── README.md
```

### 做了什么

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

### 实现的效果

- 自动/半自动地产出合规的文档与可回归的测试集，支持全量与定向回归
- 功能覆盖与行覆盖数据齐备，未命中点可定位与补测
- 缺陷根因、修复建议与验证方法有据可依，形成结构化报告（`uc_test_report/index.html`）
- 支持 MCP 集成与 TUI 协作，过程可暂停/检查/回补，易于迭代与复用

典型操作轨迹（卡住时）：

- `Check` → `StdCheck(lines=-1)` → `KillCheck` → 修复 → `Check` → `Complete`
