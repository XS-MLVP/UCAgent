
# 波形分析格式与扩展

`WaveInfo` 根据文件扩展名自动选择读取器，内置支持 FST、VCD、FSDB。文件清单、信号查询、事件分析和证据重放使用同一套格式配置。此配置只影响分析时搜索和选择已有波形，不改变模拟器、`SetWaveform` 或测试 fixture 生成的格式。

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
