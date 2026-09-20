
# DesignWithPPA

`DesignWithPPA` 是面向 UCAgent 的可安装插件，提供：

- `AnalyzePPA`：基于 Verilog RTL 和多份 VCD/FST 波形生成面积、时序与功耗报告；
- `RunDesignConsistency`：一键验证 Python reference、RTL、完整测试集、Toffee 报告和 PPA 报告的一致性；
- `unit-design-tdd`：从 README 和设计 Spec 开始，生成并验证 Verilog 或 Chisel 单元模块，并执行 PPA 优化。

Python 发行包名为 `ucagent-design-with-ppa`，插件 ID 为 `design-with-ppa`，要求 Python 3.11 及以上和 `UCAgent>=26.9.2.dev6`。

## 构建与安装

插件随 UCAgent 维护在 `plugins/DesignWithPPA/`，按需安装和启用。先安装 UCAgent 和下文的外部工具，再从仓库根目录安装插件：

```bash
python3 -m pip install ./plugins/DesignWithPPA
ucagent --list-plugins
ucagent --validate-plugin design-with-ppa
```

从源码构建并安装：

```bash
cd plugins/DesignWithPPA
python3 -m pip install build
python3 -m build .
python3 -m pip install dist/ucagent_design_with_ppa-0.4.7-py3-none-any.whl
ucagent --validate-plugin design-with-ppa
```

开发时也可以使用可编辑安装：

```bash
cd plugins/DesignWithPPA
python3 -m pip install -e .
ucagent --validate-plugin design-with-ppa
```

PPA 分析需要环境中的 `yosys` 和 OpenSTA（`sta` 或 `opensta`）。运行设计工作流还需要 `picker`。Chisel 模式使用插件锁定的 Chisel 7.15.0（Scala 2.13.18）工具链，另外需要 JDK 17 及 Mill 0.4.2；Verilog 模式不依赖 Chisel 工具链。

### 安装依赖（Ubuntu）
- [yosys](https://github.com/YosysHQ/yosys) >= 0.68
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA.git) >= 3.1.0

```bash
# yosys（Ubuntu 20.04 及以上，需启用 universe 源）
sudo apt-get update
sudo apt-get install -y yosys

# OpenSTA：universe 源中有 opensta 包（Focal/Jammy 版本为 2019 年快照，较旧）
sudo apt-get install -y opensta
```

universe 源中的 OpenSTA 版本较旧或所在发行版未收录时，可从源码构建当前版本：

```bash
sudo apt-get install -y git cmake tcl-dev swig bison flex libeigen3-dev zlib1g-dev
git clone https://github.com/The-OpenROAD-Project/OpenSTA.git
cd OpenSTA
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j "$(nproc)"
sudo cmake --install build
```

安装后确认 `yosys -V` 正常输出、`sta` 命令在 `PATH` 中（插件对 `sta`/`opensta` 两种命令名都能识别）。Ubuntu 仓库中的 yosys 版本较旧时，也可以改用 [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build) 预编译包或从 [yosys 源码](https://github.com/YosysHQ/yosys) 编译。也可以用 `make check-deps` 一次性检查 picker、yosys、OpenSTA 与 backend 是否就绪。

## Make 命令

在 `plugins/DesignWithPPA` 目录运行：

| 命令 | 用途 |
| :--- | :--- |
| `make help` | 显示所有快捷命令、默认 workspace 和可覆盖变量。 |
| `make validate` | 验证本地插件描述、资源和当前所需依赖。 |
| `make test` | 运行 DesignWithPPA 插件回归测试。 |
| `make package` | 构建 sdist 和 wheel。 |
| `make run` | 以 Verilog 模式运行 `CASE` 指定的内置案例。 |
| `make chisel-toolchain` | 检查 JDK 17 及 Mill 0.4.2。 |
| `make run-chisel` | 以 Chisel 7 模式运行 `CASE` 指定的内置案例。 |
| `make dashboard` | 通过本地 HTTP 服务打开生成的 PPA 看板资源。 |
| `make clean` | 清理插件目录中的输出、构建产物和测试缓存，不依赖 Git。 |

常用示例：

```bash
make validate
make test
make run
CASE=modular_alu_with_ex_verilog make run
make run-chisel
make dashboard
make clean
```

`make run` 和 `make run-chisel` 会优先使用同一仓库中的 UCAgent 源码入口；源码入口不存在时才使用 `PATH` 中已安装的 `ucagent`。默认运行 `LowPrecisionMatMul2x2`，生成内容位于：

```text
output/workspace_LowPrecisionMatMul2x2_verilog
output/workspace_LowPrecisionMatMul2x2_chisel
```

主要覆盖变量如下：

| 变量 | 默认值 | 用途 |
| :--- | :--- | :--- |
| `CASE` | `LowPrecisionMatMul2x2` | 选择 `cases/` 下的案例。 |
| `CASE_SOURCE_ROOT` | `cases` | 指定案例输入根目录。 |
| `WORKSPACE_ROOT` | `output` | 指定生成 workspace 的根目录。 |
| `OUTPUT` | `design` | 指定 workspace 内的设计输出目录。 |
| `BACKEND` | `opencode` | 指定 UCAgent backend。 |
| `ARGS` | 空 | 向 `ucagent` 追加参数。 |
| `PORT` | `8000` | 指定 `make dashboard` 的 HTTP 端口。 |
| `CHISEL_JAVA_HOME` | 用户级 JDK 17 路径 | 指定 Chisel 模式使用的 JDK。 |

例如：

```bash
CASE=LowPrecisionMatMul2x2 BACKEND=opencode ARGS='--override design_with_ppa.min_optimization_iterations=3' make run
PORT=8080 make dashboard
```
