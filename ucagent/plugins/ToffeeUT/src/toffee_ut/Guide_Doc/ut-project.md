
# UT 工程与输入

## 当前阶段的操作

1. 调用 `UTProject(action="inspect")`，阅读返回的资料、RTL 和 DUT 映射。
2. 调用 `UTProject(action="scaffold")`。已有文件不覆盖，已登记的工程直接采用原有
   testbench、规格路径和 fixtures，不向真实测试集插入占位用例。
3. 阅读 `results/input_inventory.json`，确认实际 top、参数和可驱动/可观察接口。
   显式配置的路径缺失时修正配置；没有 RTL 输入时请操作者补齐，不编造输入。
   输入指纹包含所选路径内的 `.v`、`.sv`、`.vh`、`.svh` 和 `.scala`；头文件变化也须重新盘点和复验。
4. 按当前阶段处理已有规格或补建候选规格，格式见 `Guide_Doc/ut-contracts.md`。

文档存在只决定从哪里开始阅读。有文档也可能缺协议、版本或独立 expected；无文档
时可以分析 RTL 继续工作，但候选行为保持 inferred/open，不能自动确认正确性。
骨架文档的 `<!-- toffee-ut:unfilled -->` 标记在完成规格后删除。

## 工程归属

以下是一个独立工程的完整布局示例；职责按需要出现，不要求创建全部目录：

```text
ut_project/
├── __init__.py
├── conftest.py
├── pytest.ini
├── requirements.txt
├── README.md
├── workspace.json
├── docs/
│   ├── README.md
│   ├── spec/design/Queue.md
│   ├── spec/verification/Queue.md
│   └── bugs/open/response-order.md
├── testbenches/
│   ├── __init__.py
│   └── queue/
│       ├── __init__.py
│       ├── README.md
│       ├── transactions.py
│       ├── env/
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   ├── bundle.py
│       │   ├── driver.py
│       │   └── monitor.py
│       ├── model.py
│       ├── checker.py
│       ├── coverage.py
│       └── tests/test_response.py
├── rtl/
├── dut/Queue/
└── results/<run-id>/
```

env 负责如何交互，transactions 负责身份/数据，model 负责独立答案，checker 负责
比较与不变量，coverage 负责实际观察的统计，tests 只描述场景。简单职责用同名
`.py`，复杂才展开包；同一职责不能同时存在文件和目录。根 `conftest.py` 是唯一
fixture 注册点，不在 DUT 子目录放另一份 `conftest.py` 或 `pytest.ini`。

真正跨 DUT 共享时才建立 `testbenches/shared/`，同样按六类职责归属，不反向依赖
具体 DUT 的实现。shared 自检不是 DUT 功能通过证据。

## workspace.json 完整示例

```json
{
  "schema": 2,
  "fixtures": "conftest.py",
  "duts": {
    "Queue": {
      "testbench": "queue",
      "environment": "testbenches/queue/env/__init__.py",
      "tests": ["testbenches/queue/tests"],
      "design_spec": "docs/spec/design/Queue.md",
      "verification_spec": "docs/spec/verification/Queue.md"
    }
  }
}
```

已有 ucv4xs 工程保留自己的 `workspace.json`、`ucv.json`、命名空间和构建配方。
规格字段可以是路径列表；在列出的首个 Markdown 文档中维护本 DUT 的结构化合同，
保留其他正文和其他 DUT 的内容。不能另建平行计划 JSON。

新工程需要真实原生包，可由操作者配置 `ut_dut_package` 接入，或对本次实际 RTL
调用 `BuildToffeeDUT(source_file="inputs/Queue.sv", top="Queue")`。已有包不覆盖；
不为验证插件而创建演示 DUT。构建输出只写入当前工程 `dut/<DUT>` 和 `results/build-*`。

构建参数为 `source_file`（必填的工作区相对 `.v/.sv` 路径）、`top=None`（默认采用工程
top）、`filelist=[]`（附加的显式 `.v/.sv` 文件）、`jobs=2`（1–32）、`timing=False`、
`build_timeout=None`（省略时沿用 `ut_timeout`；显式值为 1–14400 的整数秒）、
`rtl_defines=[]` 和 `include_dirs=[]`。例如：

```text
BuildToffeeDUT(source_file="provided/top.sv", top="top",
              filelist=["provided/package.sv", "provided/logic.v"], jobs=2, build_timeout=10800,
              timing=True, rtl_defines=["FEATURE", "WIDTH=32"],
              include_dirs=["provided/include", "provided/shared headers"])
```

`build_timeout` 只调整本次原生构建预算，不改变测试预算、编译选项或输入身份；0 不表示无界。
长构建前请操作者提供足够的调用窗口；若窗口不足，工具会在构建开始前拒绝并给出所需秒数。
超时或取消仍终止本次构建并保留原件，不据此认定 RTL 编译错误。已有部分包仍需操作者授权
归档后才能重建，不能覆盖或绕过本工具执行构建命令。

`timing=True` 只允许编译 RTL 延时，不修改 RTL，不屏蔽 warning。
`rtl_defines` 每项必须是唯一的 `NAME` 或 `NAME=VALUE`，名称是字母或下划线开头的
ASCII 标识符；拒绝空项、空值、重名和控制字符。值只接受可原样传递的单 token RTL
字面量（例如 `WIDTH=32`、`RESET=1'b0`），不接受空白、Make/shell 展开字符或参数分隔符。
宏统一送入 Picker 的 `--rtl-define`，不分别向前端和仿真器追加 `-D`。

`include_dirs` 必须是存在的工作区相对目录；路径可含空格，但不接受会被命令文件或
构建工具重解释的引号、控制字符和元字符。目录及其文件链接不能逃出工作区或形成
目录环。工具生成受控命令文件供前端和仿真器读取；`filelist` 仍不能传入用户命令文件
或任意选项。include 树不能与工程 `dut/results` 输出目录重叠。输入/选项先校验再生成
输出；include 目录内所有文件（含 `.svh/.vh`）和
源码的字面量 `` `include "..." `` 闭包均记录字节指纹和链接目标，并在执行前后复核。
无法静态确定的宏计算 include、绝对 include 和未找到的头文件会明确拒绝；条件分支中
的字面量 include 也须可解析。缺失依赖时补齐受控输入，不到工具外绕过构建。

`results/build-*/build.json` 保存命令、`options`、`inputs`、`input_targets`、
`include_directories`、`generated_inputs`、实际 `timeout` 秒数及执行结果。取消、超时、输入变化或构建失败
都保留 `stdout.log`、`stderr.log` 和明确诊断；部分原生包也不自动删除或覆盖。纯替身
工具回归不能证明实际工具链已构建成功，真实原生重构仍须由已授权执行者调用本工具。

## 历史构建与当前包证据

失败、取消、超时和旧成功的 `results/build-*` 原件必须留在原位置；不能删除、改名到
扫描范围外，或修改 `ok`、输入指纹来取得 wrapper 门禁信用。历史 FAIL 不自动变成
当前包失败，历史成功也不自动证明当前包。文件名、mtime 和未约定的时间字段不是
当前构建选择依据；另一个 DUT 的成功不能替代本 DUT 的证据。

wrapper 保持原有 native class/path 结构守卫，并明确区分三个证据等级：

| `build_evidence.credit` | 适用条件与信用上限 |
|---|---|
| `package-files` | 该 package 的任一 receipt 含 `package_files` 时，只走输出身份模式；当前静态资产必须匹配成功且当前输入/配方有效的 receipt。 |
| `legacy-input-recipe` | 该 package 所有 receipt 均无 `package_files` 时，沿用原 wrapper 的结构、当前输入和配方等级；不要求旧包补构建时输出 SHA。 |
| `receipt-free-adoption` | 没有本 DUT 的 tool receipt，维持已有外部 native-only 接入的 class/path 结构检查，不强制构建。 |

新构建成功后，内部 receipt 的 `package_files` 记录 `__init__.py`、顶层
`.so/.v/.sv/.xscfg` 和存在时的 `build-provenance.json`。这是 SDK 原生身份资产加端口
元数据的字节指纹，不导入或实例化 DUT；波形、覆盖输出和 Python 缓存不属于构建身份。
同 package 一旦有该字段，即使记录失败或当前输出失配，也不能静默使用 legacy 降级。
在新模式下，后续不同 partial 输出无匹配成功就拒绝；失败若未改变已被成功绑定的静态
资产，不凭其发生时间撤销已成立的字节匹配。

两个 receipt 模式均筛选真正成功的终态，核对非空且完整的 source/filelist、字面 include
闭包、include 树成员及链接目标、生成文件、structured options、top/export、package/logs
和实际命令。历史 FAIL、取消和旧 stale 成功保留原路径，不参与当前有效成功投票。
按有效语义配方去重，唯一合同才可通过；不同且当前均有效的 top（含合法显式覆盖）、
宏、timing 或输入合同会报冲突。jobs/timeout 是资源预算，不制造语义冲突；旧版本可以
缺少 timeout。不存在按文件名、mtime 或目录先后选取的“当前”规则。

审计分发和 wrapper checker 的真实结果在 `build_evidence` 返回上述等级、有效 receipt
的 `path`/`sha256` 引用及 `limitations`。legacy 等级明确没有构建时输出 SHA，无法区分
“相同 class/当前输入的成功包仍在”和“相同 class/输入的后来 partial 替换”；通过该
等级不是声称排除了这种风险，更不是新的输出身份或 RTL 功能证明。工具不回填原件。

若报 `No current native build evidence` 或语义冲突，保留现场并据错误中的具体 receipt
检查输入、生成配方、导出与当前配置；需要超出工具观测的归属判断时报告操作者。
不得移动历史来消歧、修改 raw 状态、机械重编或要求普通验证 Agent 填写批准 JSON。
新指纹沿用本地构建原件的可信边界，不是防恶意协同改写的签名；HMAC Run receipt
也不意味着 build receipt 曾经签名。所有等级均不替代后续真实执行与功能验收。

## 验收边界

`Check` 在输入阶段核对实际文件、输入指纹和 pytest 入口；后续阶段检查规格、代码
和真实运行。结构完整不等于功能已证明；初始占位断言必须在实现阶段替换。
每阶段记录 `SetCurrentStageJournal`，检查通过后调用 `Complete`。
