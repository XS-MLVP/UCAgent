
# ACT4 工作流环境准备指南

每个 ACT4 工作流从 `prepare_environment` 开始。用户选择 ACT4、规范和目标源码版本；
先阅读该版本的依赖清单与 CI 安装说明，再探测、安装缺项并复验。环境准备不是测试验证，
不得把“工具已安装”写成“资产已通过构建/运行”。

## 1. 操作顺序

1. 检查当前 host probes。已存在且版本/能力满足选定输入的工具直接复用。
2. 只阅读当前工作流输入中依赖软件的安装说明；审查工作流此时不读取 CTP、coverpoints、testgen 或用例。
3. 创建下面完整 schema 的 `plan.yaml`，为每项写明版本依据、实测探测和复验规则。
4. 对缺失的公开软件提供安装命令并实际执行；无公开安装介质、许可证或平台支持时写明原因。
5. 检查 `receipt.json`、日志和摘要；安装后探测不匹配时不得标为可用。
6. 完成环境阶段后再进入本工作流下一阶段。所有 shell 命令先 source 本工作流输出中的 `activate.sh`。

## 2. 安装计划格式

文件路径：`{OUT}/{DUT}/environment/plan.yaml`。`tools` 必须列出 python、bash、git、curl、make、uv、compiler、reference、lint；可添加由所选 workflow CI 或依赖文档要求的公开工具。`bin_dirs` 相对 `{PREFIX}`。命令使用 argv 数组，不使用 shell 字符串。`{PREFIX}` 是独立版本安装目录，`{PYTHON}` 是当前 UCAgent 所用 Python。

下面是结构完整的格式示例。版本、正则和安装 argv 是示意输入，不是可照抄的依赖结论；必须根据本轮冻结的 ACT4、香山源码或本地资产依赖说明替换。已匹配的 host 工具可以 `install: []`；无法获得的可选 lane 使用 `unavailable_reason`。

```yaml
schema_version: 1
tools:
  - id: python
    version: "Python 3."
    basis: "Current UCAgent runtime; Python is reused, not replaced"
    probe: ["{PYTHON}", --version]
    expected_output: "Python 3\\."
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: bash
    version: "采用的最低或精确版本及来源"
    basis: "当前输入的依赖文档/CI 文件及版本行"
    probe: [bash, --version]
    expected_output: "GNU bash"
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: git
    version: "采用版本及来源"
    basis: "当前输入的版本要求"
    probe: [git, --version]
    expected_output: "git version"
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: curl
    version: "采用版本及来源"
    basis: "当前输入的版本要求"
    probe: [curl, --version]
    expected_output: "curl"
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: make
    version: "GNU Make 版本及来源"
    basis: "当前输入的版本要求"
    probe: [make, --version]
    expected_output: "GNU Make"
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: uv
    version: "ACT4 锁文件/CI 采用版本"
    basis: "当前输入的 uv 管理配置"
    probe: [uv, --version]
    expected_output: "uv [0-9]"
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: compiler
    version: "当前 test_config 所需 RISC-V GCC 版本"
    basis: "当前输入的 test_config 与 CI 编译步骤"
    probe: [riscv64-unknown-elf-gcc, --version]
    expected_output: "riscv64-unknown-elf-gcc"
    install: []
    bin_dirs: [bin]
    storage: persistent
  - id: reference
    version: "当前 test_config 选用参考模型的版本"
    basis: "当前输入的 test_config 及模型安装说明"
    probe: [sail_riscv_sim, --help]
    expected_output: "用该版本真实输出编写的匹配正则"
    install: []
    bin_dirs: [bin]
    storage: persistent
    unavailable_reason: "填写没有安装介质/权限/平台支持的具体原因与替代验证路径"
  - id: lint
    version: "当前工作流使用的 lint 版本"
    basis: "当前输入的 CI lint 步骤"
    probe: [ruff, --version]
    expected_output: "ruff [0-9]"
    install:
      - ["{PYTHON}", -m, pip, install, --prefix, "{PREFIX}", "ruff==<CI pin>"]
    bin_dirs: [bin]
    storage: persistent
```

安装命令必须来自选定版本的官方依赖说明/CI，尊重 `{PREFIX}`，不得调用 sudo、全局 pip，
不得升级系统 Python、覆盖系统编译器、修改 shell 启动文件或运行无范围系统升级。
软件不兼容另一 workflow 时，使用 `storage: temporary` 隔离；配方变更会生成新的版本目录，
不覆盖旧工具。路径型 `bin_dirs` 只允许前缀内相对目录。不要安装 Questa/VCS/Xcelium；
它们以及香山 emu 是独立的可选能力。

## 3. 验收和恢复

准备期间使用 `StdCheck` 查看真实安装日志，必要时 `KillCheck` 中断当前进程组。取消、网络故障、
权限拒绝和超时都留下日志；修正计划后重新运行 `Check(stage_args={"action":"prepare"})`。
共享目录安装由锁串行化；若另一任务正在安装，等待后重试。只复用可执行文件仍存在且校验值一致、
版本探测匹配的安装。

成功的 `Check` 返回 `prepared` 或 `prepared_with_limitations`。只要计划明确记录缺失能力和影响，
环境阶段可继续；后续依赖该工具的 build/run 必须保留其自身失败或未验证结果。只给出安装失败日志
而未说明影响不构成最终报告。将 `{OUT}/{DUT}/environment/summary.md` 纳入最终报告。

`activate.sh` 仅为后续 shell 命令提供 PATH，不改 UCAgent 主进程环境。插件内部 review 和 handoff
命令从验证后的收据加载同一 PATH；Python 项目依赖仍在隔离工作副本通过锁文件准备。

模板和检查器使用与本指南一致的 schema；不可为兼容旧计划而自动转换其它字段名。
