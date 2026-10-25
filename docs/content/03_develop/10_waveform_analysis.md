
# 波形分析格式与扩展

`WaveInfo` 根据文件扩展名自动选择读取器，内置支持 FST、VCD、FSDB。文件清单、信号查询、事件分析和证据重放使用同一套格式配置。此配置只影响分析时搜索和选择已有波形，不改变模拟器、`SetWaveform` 或测试 fixture 生成的格式。

## 测试产物的默认后缀

真实 VCS fixture 使用新版 toffee-test 的 `set_line_coverage(..., dut=dut)`，从
`GetCoveragePath()` 取得实际 VDB，并定位生成包的 `coverage/coverage` 查询程序。
`SetCoverage` 的参数用于选择 testdata，不能当作 VDB 路径。旧 picker 生成包缺少接口时应重建，
不能把 `.vdb` 当 Verilator 数据；模板 fake 阶段不查询原生覆盖率。UCAgent 与 toffee-test 必须配套升级。

测试 API 模板通过 `ucagent.get_default_subfix(dut, sub_type)` 选择产物后缀，`sub_type` 取 `"waveform"` 或 `"coverage"`，返回值不含前导点：

| `dut.SIMULATOR` | 波形后缀 | 覆盖率后缀 |
| --- | --- | --- |
| `verilator` | `.fst` | `.dat` |
| `vcs` | `.fsdb` | `.vdb` |
| `uvs` | `.usdb` | `.cdb` |

该函数接受 DUT 实例或类，从属性读取仿真器名称并忽略大小写与两端空白。仅缺少 `SIMULATOR` 属性时默认使用 Verilator。属性为 `None`、空字符串、非字符串或未知名称时会报错；无效 `sub_type` 同样报错。

picker 生成的 DUT 类必须提供 `SIMULATOR` 类属性（例如 `DUTAdder.SIMULATOR == "vcs"`），仅在包模块中设置同名变量无效。更新 picker 模板后需重新生成 DUT；fake DUT 会保留类上的该属性。

Master 编译通过 `picker_args: ["--sim", "vcs"]` 选择 VCS，默认传 `--rw dpi` 并生成 `.fsdb`；Verilator 默认使用 `--rw mem_direct` 和 `.fst`。显式 `--rw` / `--access-mode`、`-w` / `--wave_file_name` 覆盖默认值；重复选项或 VCS 配置 `mem_direct` 会在执行前报错。picker 同时接受枚举数字 `0`（DPI）和 `1`（mem_direct），VCS 不接受 `1`。

`get_coverage_data_path(request, dut, new_path)` 和 `get_waveform_path(request, dut, new_path)` 将返回的后缀用于每个测试的唯一产物路径。创建时使用 `new_path=True`，覆盖率上报时使用同一个 DUT 和 `new_path=False`，以取得原路径。VCS 的 `.vdb` 可以是目录，按完整路径传递即可。模板阶段的 fake DUT 与独立 Mock DUT 保留原 DUT 类声明的 `SIMULATOR`，无需启动真实仿真器。

新增仿真器时，在 `ucagent/util/test_tools.py` 的 `_SIMULATOR_DEFAULT_SUFFIXES` 中补充 `waveform` 和 `coverage` 两项，并增加对应测试；路径模板无需增加分支。此映射只定义命名规则，实际产物依赖 DUT 构建及仿真器支持；新波形格式仍需按本页注册读取器。覆盖率解析由 `toffee-test` 提供，使用 VCS 时还需确认所用版本支持 `.vdb`；后缀选择本身不会增加覆盖率解析能力。

## 格式优先级

默认配置位于 `ucagent/setting.yaml`：

```yaml
runtime_options:
  waveform_analysis_format_priority: [fst, vcd, fsdb]
```

可在工作区配置或显式指定的配置文件中覆盖，例如优先分析 VCD：

```yaml
runtime_options:
  waveform_analysis_format_priority: [vcd, fst, fsdb]
```

列表同时定义参与搜索的格式：`[vcd]` 只搜索 VCD，禁用 FST、FSDB。列表必须非空，扩展名使用小写且不带点，不允许重复。该配置遵循正常配置层级，解析后的值写入 `.ucagent/runtime_config.json` 的 `runtime_options`，运行时不重新读取环境变量。

`WaveInfo` 先确定最新的 `toffee_tmp_*` 测试会话，再匹配精确测试名及可选的数字 dump 后缀。在同一会话内，先比较格式优先级，再比较数字后缀、文件修改时间和路径。因此，默认配置下 `test_add001.fst` 优先于 `test_add999.vcd`。不会为了找到更高优先级格式而使用旧会话，也不会替换成相似测试名。文件扩展名的大小写不影响格式识别。

当选中的文件为空、损坏或缺少解析依赖时，工具返回该文件的路径、格式和修复建议，不自动切换到另一种格式。需要切换时，先修复波形生成或明确调整分析优先级，再重新调用 `WaveInfo`。清单及选择结果中的 `format_priority` 显示本次分析使用的顺序。

## FSDB 运行依赖与在线查看

FST、VCD、FSDB 分别使用 `wavekit` 的 `FstReader`、`VcdReader`、`FsdbReader`。FSDB 还需要 Verdi NPI 运行库 `libNPI.so`；在启动 UCAgent 前使用以下任一方式配置：

- `WAVEKIT_NPI_LIB`：指向 `libNPI.so` 的完整路径。
- `VERDI_HOME`：Verdi 安装目录。
- `LD_LIBRARY_PATH`：包含该库及其运行依赖的搜索路径。

这些变量由 FSDB 运行库使用，与分析格式优先级配置分别生效。缺少 NPI 时，`WaveInfo` 向验证任务报告波形无法分析及恢复动作，底层异常写入 UCAgent 运行日志；环境维护者按本节检查运行库配置。格式、读取器和依赖配置由环境维护者管理，运行时指南和工具说明只要求验证任务 LLM 调用 `WaveInfo` 并处理结果。

当前浏览器查看器支持 FST/VCD。FSDB 可以通过 `WaveInfo` 查询和分析，但不会生成无法打开的在线查看链接。需要带在线查看链接的最终 Bug 证据时，先导出 FST/VCD，将其配置为参与分析的首选格式，再重新执行最终 `WaveInfo`。直接访问逻辑查看接口并选中 FSDB 时，接口返回 HTTP 415，避免打开另一份格式的波形。最终证据仍需遵循 `Guide_Doc/dut_bug_analysis.md` 的信号组、分析窗口和 receipt 要求。

## 真实 VCS 验证入口

完整的最小 DUT 验收使用生产编译命令构造器、已安装 picker 及其默认模板，实际编译并运行四组 128 位加法，再用 WaveInfo 核对 FSDB 中进位的位宽、时间戳和值，同时检查 VDB 测试数据：

```bash
UCAGENT_VCS_PICKER=/absolute/path/picker \
python -m pytest -q tests/test_vcs_integration.py
```

该测试需要 VCS/Verdi 许可证、构建工具、Python 开发依赖和 NPI，使用 `--verdi-mode modern`（Verdi >= 2024.09）。未设置变量则跳过；显式启用后失败不会跳过。构建、仿真日志及 `analysis.json` 保存在 pytest 临时目录中；仿真使用子进程隔离 VCS 的退出行为。它验证编译到波形解析的链路，不启动模型任务或 Swarm 服务。

在具备 VCS/Verdi 的环境生成真实 FSDB 后，可运行不替换 reader 的验收测试：

```bash
UCAGENT_VCS_FSDB=/absolute/path/test.fsdb \
UCAGENT_VCS_SIGNAL=Adder_top.Adder.clk \
UCAGENT_VCS_END_STEP=100 \
python -m pytest -q tests/test_waveform_tool.py -k real_vcs_fsdb
```

信号路径和时间窗口应按真实 DUT 设置，窗口内应有跳变。未设置 `UCAGENT_VCS_FSDB` 时测试跳过；显式设置后，文件缺失、NPI 不可用或解析失败均算失败。该检查证明正式 WaveInfo 解析链路可用，仍需用已知测试激励核对信号值、时序和 DUT 正确性。

环境排查注意：

- Verdi NPI 初始化可能将进程 locale 改为 `C`，导致后续中文文档读取和模型指令写入出现 ASCII 编解码错误。内置读取器在初始化成功或失败后均恢复原 locale；这不会隔离原生初始化期间对其他线程的短暂影响。
- picker 二进制、模板与 xspcomm 必须匹配；生成代码应包含 `SIMULATOR = "vcs"`。仅更新模板不能解决旧生成器仍输出已移除的 `XPin` 接口的问题。
- Verdi W-2024.09-SP1 的 NPI 可能还需将 `$VERDI_HOME/platform/linux64/lib/Qt5/lib` 和 `$VERDI_HOME/platform/linux64/lib` 加入启动进程的 `LD_LIBRARY_PATH`，否则即使存在 `libNPI.so`，也可能因缺少 `libQt5Script.so.5` 而不可用。
- Python 与扩展模块 ABI 应一致；若导入 VCS DUT 报 `cannot allocate memory in static TLS block`，可仅对该测试进程设置 `LD_PRELOAD=/absolute/path/libUTAdder.so`，不要全局预加载 DUT 库。
- VCS 的 `Finish()` 可能直接结束宿主进程；已知向量断言应在调用前执行，FSDB 解析放在独立进程中验证，不能只根据构建命令退出码认定测试通过。
- 当前 picker 的 VCS `SetCoverage("test_real_vcs.vdb")` 选择的是编译 VDB 内的测试名，不是在该路径创建独立 VDB；数据位于 DUT 包的 `Adder.vdb/snps/coverage/db/testdata/test_real_vcs`。后缀接口正确不等于 toffee-test 已完成此目录的收集与报告集成。

## 注册其他格式

通过公开接口 `register_waveform_reader(format_name, factory)` 注册新扩展名。注册应在应用或插件初始化时显式执行，并在创建 `WaveInfo` 之前完成。同一格式只允许注册一次，不能覆盖内置读取器。注册后还需将格式名加入分析优先级。

```python
from ucagent.tools import WaveInfo, register_waveform_reader
from my_waveform_backend import WlfReader

# WlfReader accepts a file path and implements the reader contract below.
register_waveform_reader("wlf", WlfReader)

tool = WaveInfo(
    workspace="/path/to/workspace",
    test_dir="unity_test/tests",
    format_priority=["fst", "vcd", "fsdb", "wlf"],
)
result = tool.analyze(test_case_name="test_add")
```

与 UCAgent 的完整工作流集成时，使用相同注册调用，并配置：

```yaml
runtime_options:
  waveform_analysis_format_priority: [fst, vcd, fsdb, wlf]
```

`factory(path)` 接收波形文件路径字符串，返回一个上下文管理器。进入上下文后返回的对象必须符合 `wavekit` reader 接口：

- `begin_time`、`end_time`：整数模拟时间戳。
- `top_scopes`：每个 scope 提供 `full_name`。
- `get_matched_signals(pattern)`：支持 WaveInfo 使用的查询语法，返回信号映射。信号提供 `full_name`、`base_name` 和 `width`。
- `_load_value_changes(signal, value_mapping, begin_time=None, end_time=None)`：返回时间戳与映射后数值的二维序列。必须应用传入的 0/1/X/Z 映射；开始时间应保留之前最近的状态，结束时间为开区间。WaveInfo 分别读取值、X 掩码和 Z 掩码。
- 上下文退出时关闭文件、原生句柄等资源，包括分析失败的路径。

适配器可继承 `wavekit` reader 基类实现这些能力。额外依赖在工厂调用时加载，避免仅导入工具或列出文件就初始化原生运行库。扩展格式共享现有的发现、分析、receipt 和重放流程；注册读取器不会扩展浏览器查看器的解码能力。
