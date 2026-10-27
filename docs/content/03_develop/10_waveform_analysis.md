
# 波形分析格式与扩展

`WaveInfo` 根据文件扩展名自动选择读取器，内置支持 FST、VCD、FSDB。文件清单、信号查询、事件分析和证据重放使用同一套格式配置。此配置只影响分析时搜索和选择已有波形，不改变模拟器、`SetWaveform` 或测试 fixture 生成的格式。

## 测试产物的默认后缀

测试 API 模板通过 `ucagent.get_default_subfix(dut, sub_type)` 选择产物后缀，`sub_type` 取 `"waveform"` 或 `"coverage"`，返回值不含前导点：

| `dut.SIMULATOR` | 波形后缀 | 覆盖率后缀 |
| --- | --- | --- |
| `verilator` | `.fst` | `.dat` |
| `vcs` | `.fsdb` | `.vdb` |
| `uvs` | `.usdb` | `.cdb` |

该函数接受 DUT 实例或类，从属性读取仿真器名称并忽略大小写与两端空白。仅缺少 `SIMULATOR` 属性时默认使用 Verilator。属性为 `None`、空字符串、非字符串或未知名称时会报错；无效 `sub_type` 同样报错。

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

## 多格式查看入口

查看链接为`/wave/?meta=<工作区相对 JSON 路径>`，固定工具本次实际选中的波形。`a.fsdb`的元数据保存在同目录`a.fsdb.json`。文件浏览器从`GET /api/waveform/viewers`取得可查看扩展名；选中文件后调用`POST /api/waveform/metadata`，请求体为`{"waveform_file":"waves/a.fsdb"}`，只创建缺失元数据，保留已有最终取证配置。

`WaveInfo`最终取证自动写入元数据；直接`analyze()`和分析重放只计算结果。`ApplyWaveInfoEvidence`同步所选receipt的查看配置，包括重复Apply；批量刷新及审核在完整准备成功后提交，文档提交失败时回滚本次元数据修改。普通Check不写元数据。每份波形只保留当前查看配置，独立签名receipt保留历史快照；清理波形或JSON不影响已验证历史证据，在线打开会明确报告缺失文件。链接不搜索更新的测试会话，也不替换另一格式的波形。

例如`waves/a.fsdb.json`：

```json
{
  "schema_version": 1,
  "waveform_file": "a.fsdb",
  "signals": ["TOP.dut.clk", "TOP.dut.result"],
  "source_files": ["../rtl/Demo.sv", "../src/Demo.scala"],
  "dut_python_path": "../Demo/__init__.py",
  "test_file": "../unity_test/tests/test_demo.py",
  "test_case": "unity_test/tests/test_demo.py::test_saturation",
  "start": "100",
  "end": "200",
  "cursor": "150",
  "integrity_hmac": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

JSON中的文件路径均相对于JSON目录，使用`/`；允许`../`，解析后的真实路径（包括符号链接）必须位于选定工作区。`waveform_file`仅为同目录文件名。前五个字段必需；未确定的DUT Python入口为`null`，关联源码为空列表。测试关联包含文件和原样node ID。最终窗口的三个时间字段完整出现，保存非负十进制字符串，单位为原生波形时间戳，避免JavaScript整数精度损失；普通文件查看可以没有窗口。元数据最多1 MiB，信号去重后最多64个。

工具自动关联已存在的DUT主设计文件、Python入口和精确测试源码；`WaveInfo(source_files=[...], dut_python_path="...")`接受工作区相对路径，补充LLM分析确定的关联文件。工具不会将扫描到的所有源码作为关联资料。不存在的显式路径报错，未确定的自动可选关联返回提示，不编造路径。

## 元数据防篡改

磁盘 JSON 必须包含工具生成的 `integrity_hmac`；上例的 64 位十六进制值仅为格式示意，不能复制使用。HMAC-SHA256 覆盖除签名字段外的全部内容以及 JSON 的工作区相对路径，并使用当前工作区专属密钥。修改信号、窗口、关联文件、测试 ID 或链接目标，以及把签名文件复制到另一工作区，均不能通过校验。空白和对象字段排列不影响规范化后的签名；重复 JSON 字段被拒绝。在线链接必须使用 JSON 的真实工作区相对路径，不接受通过符号链接访问的别名，以保证浏览器与服务端解析到相同的波形目录。

密钥保存在服务运行用户的 `~/.ucagent/waveform_keys/`，不进入工作区、元数据、工具返回值或运行配置。目录权限为 `0700`，密钥文件权限为 `0600`，文件名由工作区真实路径的 SHA-256 派生。验签不会创建丢失的密钥；移动工作区或丢失密钥后，需通过工具重新发布查看配置。

CMD 在分发、返回 Surfer 元数据和创建 Xpra 会话前验签；返回给 Surfer 的是已验证、去除签名字段的语义数据。默认 Verdi 启动脚本在启动应用前再次验签，防止页面打开后文件被修改。缺少签名、签名不符或密钥不可用时拒绝打开。普通查看不会为已修改的 JSON 重新签名；最终取证使用 `WaveInfo`/`ApplyWaveInfoEvidence` 重新发布，普通查看可删除已损坏的 JSON 后重新选择实际波形。

历史 receipt 独立签名并保存语义快照，普通 Check 不依赖在线 JSON 或密钥，不会因清理波形、JSON 或丢失查看密钥而失效。此机制检测无密钥方对元数据的修改，不校验波形或源码文件的内容，也不能防御能够读取同一操作系统用户私钥或执行签名工具的主体。

## 查看器与Xpra配置

`ucagent/setting.yaml`提供默认映射，可通过已解析的工作区配置覆盖：

```yaml
cmd_api:
  waveform_viewers:
    fst:
      kind: web
      url: /surfer/
    vcd:
      kind: web
      url: /surfer/
    fsdb:
      kind: xpra
      script: verdi/launch_verdi.py
      args: ["--meta", "{wave_meta}", "--verdi", "verdi"]
      env: {}
      idle_timeout: -1
```

`kind: web`使用同源、以`/`开头及结尾且无query的页面路径，重定向时传递同一`meta`。Surfer异步读取`GET /api/waveform/metadata?meta=...`，加载指定波形并恢复信号、窗口、游标；保留FST兼容转换与加载进度。增加其他格式时配置相应扩展名及查看页面或启动脚本；未配置格式返回415和配置动作，错误配置返回503。

`kind: xpra`的GET只返回启动页面；页面调用现有`POST /api/xpra/sessions`，请求体为`{"wave_meta":"waves/a.fsdb.json"}`。服务端校验元数据后从配置生成命令，复用原有认证、配额、会话状态与诊断。JSON不能指定脚本、命令或环境变量。相同元数据内容及查看器配置复用存活会话，并发创建合并；退出后重新打开可创建新会话。

相对`script`只在实际运行包的`ucagent/scripts`下解析，支持子目录，拒绝通过`../`或符号链接逃逸；不搜索工作目录或PATH。绝对路径按原路径检查。Python脚本由运行UCAgent的`sys.executable`执行。`args`必须是参数列表，`{wave_meta}`在启动时替换为已验证JSON的绝对路径；参数安全传递。`env`由运维配置指定。`idle_timeout`为`-1`或正整数秒。需要额外Verdi参数时可在默认脚本参数末尾加入`"--"`及对应参数列表。

默认`verdi/launch_verdi.py`导入可支持的Verilog/SystemVerilog关联源码、打开FSDB、添加信号并恢复时间窗口和游标；Scala等保留为关联资料。启动Tcl使用`wvGetFileTimeUnit`读取实际FSDB时间尺度，再通过`wvSetWindowTimeUnit`把显示单位设置为一个原生tick，随后应用JSON中的时间值。无法取得尺度时启动失败，不假定ns或将日志cycle当作时间。临时Tcl随Verdi进程结束清理，应用异常和返回码保留在Xpra诊断中。

Xpra运行环境需要Xpra/X11、Verdi及有效许可证，运行库分析环境参见本页FSDB依赖说明。替身测试覆盖参数、路径、Tcl字面量、多个时间尺度和错误处理；真实信号与时间定位仍需在实际许可环境执行集成验收。子工作区参数和Master的task/agent CMD代理前缀沿用全部接口。

### 无 Verdi 时的图形集成测试

`tests/fixtures/fake_verdi.py` 是有 Tk 窗口的测试应用，执行默认启动器生成的真实 Tcl，绘制选定信号、时间窗和游标，并通过按钮或 `R` 键记录远程交互。它只读取带有显式测试标记的 JSON 波形夹具；夹具使用 `.fsdb` 文件名以测试格式分发，不包含或解码真实 FSDB。Xpra、Xvfb、CMD REST、HTML5 客户端和 WebSocket 均使用真实实现。

在已安装项目测试依赖、Xpra、Xpra HTML5 资源、Xvfb 和 Python Tk 的 Linux 环境中运行。容器应使用 init 进程（如 `docker run --init`）回收已退出的应用后代进程：

```bash
UCAGENT_RUN_WAVE_XPRA_INTEGRATION=1 python -m pytest -q tests/test_waveform_xpra_runtime.py
```

测试使用临时工作区和私有签名目录，覆盖认证、GET 不启动、并发会话复用、配额、退出重开、进程清理、元数据篡改拒绝和 Tcl 启动错误。夹具包含中文、空格及 Tcl 特殊字符路径、RTL/Scala 关联、`10fs` 时间尺度和超过 JavaScript 安全整数范围的时间戳。

浏览器验收可在相同 Linux 环境中启动独立夹具服务；跨容器运行时按实际映射修改浏览器访问地址：

```bash
python tests/test_waveform_xpra_runtime.py --serve --host 0.0.0.0 --port 8765 --info /tmp/wave-xpra-info.json
```

在浏览器测试所在环境安装 Playwright 及 Chromium/WebKit，设置以下变量后运行测试。密码取服务端信息文件的 `password` 字段，通过安全渠道传入；不要提交该文件或凭据。

```bash
export UCAGENT_WAVE_XPRA_URL=http://127.0.0.1:8765
export UCAGENT_WAVE_XPRA_PASSWORD='<password from the private info file>'
export UCAGENT_WAVE_XPRA_ARTIFACTS=/tmp/wave-xpra-screenshots
python -m pytest -q tests/test_waveform_xpra_browser.py
```

可用 `UCAGENT_XPRA_CHROMIUM_EXECUTABLE` 指定已安装的 Chrome。浏览器测试从 `/wave/?meta=...` 自动进入远程应用，检查实际绘制像素、信号和精确时间，发送键盘输入，再验证刷新重连及重复打开的会话复用，并保存截图。服务收到中断或终止信号时清理会话和临时文件。这些测试验证查看链路和启动协议；真实 Verdi 的 FSDB 解码、命令兼容性及时间定位仍需在有许可证的运行环境验收。

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
