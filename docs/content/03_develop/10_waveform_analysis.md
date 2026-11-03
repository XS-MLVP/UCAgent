
# 波形分析格式与扩展

`WaveInfo` 根据文件扩展名自动选择读取器，内置支持 FST、VCD、FSDB。文件清单、信号查询、事件分析和证据重放使用同一套格式配置。此配置只影响分析时搜索和选择已有波形，不改变模拟器、`SetWaveform` 或测试 fixture 生成的格式。

## PDB 手动重放全部 Bug 波形

在 UCAgent 的 PDB 控制台执行：

```text
(UnityChip) waveform_replay
(UnityChip) waveform_replay 600
(UnityChip) waveform_replay --reanalyze 600
(UnityChip) waveform_replay --reanalyze --max-rounds 5 600
```

`waveform_replay [timeout_seconds]` 不调用 LLM，自动使用已加载配置中唯一的 `require_current_replay: true` 波形门禁及其动态 Bug 文档、测试目录。该阶段必须在波形门禁前配置一个匹配文档和目录的 DUT 测试分类检查；默认工作流的最后阶段已满足此要求。可选参数为本次全量测试的正整数秒数，省略时使用已解析的 `cfg.call_time_out`。无需切换到最后阶段；命令不提交 Bug 记录，也不推进或完成阶段。已有模型任务运行时，命令会在启动测试或修改证据前拒绝执行。

命令先执行该分类检查，重跑完整 DUT 测试集合并核对失败测试与 BG/TC/CK；正确复现 DUT Bug 的测试仍保持 Fail，分类检查失败则停止，不进入 replay。分类通过后，对所有非零置信度动态 Bug 关联的唯一 TC 逐一重放，每个 TC 只处理一次。签名语义未变的记录复用原有分析结论，自动原子刷新当前 receipt、波形路径和查看配置；已是当前证据时不重复写入。没有有效动态 Bug 时，校验规范空文档并报告无需重放。

控制台和 UCAgent 运行日志使用 `[waveform_replay]` 前缀，记录目标文档、测试目录、测试超时、分类结果、每个 TC 的进度与状态、刷新数量，以及最终耗时和 `SUCCESS`、`FAILED` 或 `CANCELLED`。按 Ctrl+C 可取消执行。配置缺失或歧义、测试分类失败、波形缺失、receipt 无效或写入失败都会明确报告当前操作及完整诊断；按诊断修复后重试。

TC 的断言、激励或对应测试源码变化时，即使重放出的波形完全一致，该 TC 仍必须报错，保留原分析记录并要求重新分析关联 Bug；测试路径、函数名或参数化 node ID 变化也不能自动建立等价关系。源码、timeline、信号值等签名语义变化返回 `WAVEFORM_SEMANTIC_BATCH_REVIEW_REQUIRED`，并包含 `requires_bug_reanalysis: true`、精确 TC、变化文件和完整 `review_batch_call`，供后续分析使用。先按返回调用使用 `ReviewWaveInfoEvidenceBatch` 准备全部上下文，结合当前 TC、规格、源码和波形重新分析全部关联 Bug，再一次原子提交全部 review；随后按诊断执行一次 `Check`。整次命令可能已刷新其他语义未变的记录，已完成的刷新会有独立日志；每次文档写入仍遵循原子提交约束。

增加 `--reanalyze` 后，命令会调用当前配置的 LLM 处理分类或 replay 失败：`waveform_replay [timeout_seconds] --reanalyze [--max-rounds N]`。只有检查失败才调用 LLM，默认最多重新分析 3 轮；`--max-rounds` 必须与 `--reanalyze` 一起使用，且为正整数。测试超时作用于每次全量测试，不是整个 LLM 任务的总时限。每轮输入包含完整诊断、当前目标和规范要求，LLM 读取 `Guide_Doc/dut_bug_analysis.md`、`Guide_Doc/dut_test_case.md`、当前 TC、规格及相关源码后修改实际产物。Skill 是可选加速路径，禁用或目录缺失时使用普通文件工具完成同一规范。

确认为 DUT Bug 时，保留正确失败的复现测试，更新 BG/ROOT 分析和签名波形证据。修正错误 TC 后证明某项关联不再是 DUT Bug 时，移除该关联的 TC/引用；保留其他失败 TC 支持的 BG，只删除失去支持的 BG、空动态分支、无人引用的 ROOT 和无人使用的中央波形记录，同时更新静态文档中的失效动态确认链接及已有汇总/报告。局部报告中没有某个 TC 不能作为删除历史记录的依据；不得弱化断言、减少覆盖或删除无关 Bug/共享根因。若仅一项关联被反证而 TC 仍复现其他 Bug，只删除被反证的关联，保留 TC 的真实 Fail 及其余结论。全部动态 Bug 被排除后，保留规范的三个空分区文档。

每轮 LLM 返回后，命令重新运行完整分类和当前 replay，并运行配置中匹配的静态 Bug 关联检查，全部通过才输出 `SUCCESS`，不会采信 LLM 自述“已完成”。日志包含 `LLM REANALYSIS round i/N`、剩余错误及最终调用轮数。处理期间临时阻止阶段校验、完成、跳转和退出工具，`CurrentTips` 返回本次重新分析要求；结束后恢复工具回调与原暂停状态。命令不执行 Bug Recorder 或发布记录。自动刷新或 LLM 修改动态/静态分析后，会刷新所有匹配 Recorder 的文档视图并清除已接受的旧记录；部分编辑后失败或取消也执行此处理，发布前需在正常记录阶段重新提交当前 Bug。普通 replay 仍无需模型；重新分析遇到模型禁用/忙碌、调用异常、轮数耗尽或取消时会明确报错。验证失败或取消时保留 LLM 已做的修改，便于检查和重试。

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

## 同一格式的后端优先级

`runtime_options.waveform_analysis_backend_priority` 独立配置每种格式的读取库顺序。默认值：

```yaml
runtime_options:
  waveform_analysis_format_priority: [fst, vcd, fsdb]
  waveform_analysis_backend_priority:
    fst: [pywellen, wavekit]
    vcd: [pywellen, wavekit]
    fsdb: [wavekit]
```

格式优先级先选择波形文件，后端优先级再选择读取同一文件的实现。列表必须非空、名称小写且不重复；列出但未注册的后端在创建 `WaveInfo` 时失败。可以仅覆盖 `vcd: [wavekit]`，其他内置格式继续使用默认值；只列一个后端会禁用该格式的库回退。值来自解析后的 `cfg.runtime_options`，同时验证并保存至 `.ucagent/runtime_config.json`，不会在调用时读取环境变量。

默认 FST/VCD 分别由 `WellenFstReader`、`WellenVcdReader` 解码；备选为 `WavekitFstReader`、`WavekitVcdReader`。具体实现类必须带后端前缀。依赖约束为 `pywellen>=0.25.7,<0.26`、`wavekit>=0.7.0,<0.8.0`，并直接声明 `pylibfst>=0.2.1,<0.3`。

仅工厂构造或上下文进入时的 `ImportError`/`ModuleNotFoundError` 触发下一后端。文件损坏、权限错误、查询错误、高级参数不受支持以及已开始分析后的异常都会报告失败，不继续尝试；始终保持所选 TC、会话、文件和格式。所有后端不可用时返回维护者修复环境后重试的动作。

pywellen 当前 Python API 不提供文件完整时间边界或声明位索引。VCD 实现额外流式扫描声明和时间标记，保留末尾没有信号变化的时间；FST 实现通过 pylibfst 只读取声明和起止时间，并立即关闭元数据句柄。信号值由 pywellen 解码。它按需加载选择的信号，但加载后仍保留该信号的完整原生 trace；窄窗口通过原生索引二分选取，不复制全部 Python 行。目录输出有界，底层仍会枚举完整信号元数据，不能据此认为消除了大文件内存或扫描成本。数字信号支持声明索引、升序/负数范围、数组路径、宽整数和 X/Z；real/string 等非数字变量不进入数字分析目录。连续逐位声明会还原为原始位路径；如果绑定返回多个不可区分的同名描述符（如不连续的同名逐位声明），明确报告失败，不猜测对应关系。原生解码 panic 会转换成分析错误并清理资源。

人工执行日志使用 `[WaveInfo]` 前缀。运行日志记录 `backend_order`、每次 `backend_attempt`、`backend_unavailable` 原因、`backend_open_failed` 及 `backend_selected`；控制台和运行日志中的 `analysis_started` / `analysis_finished` 给出实际 `backend`、TC、状态与耗时。日志不输出 `backend_args` 内容。后端身份不增加到 LLM 工具返回；无参数文件清单不打开读取器，因此不会记录实际选中后端。

## FSDB 运行依赖与在线查看

FSDB 使用 `WavekitFsdbReader` 适配 wavekit。FSDB 还需要 Verdi NPI 运行库 `libNPI.so`；在启动 UCAgent 前使用以下任一方式配置：

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

默认`verdi/launch_verdi.py`优先从元数据关联的DUT Python入口目录查找`*.daidir/simv.kdb`，其次检查关联源码所在目录；不扫描其他设计目录。找到唯一数据库时通过`-dbdir`加载VCS已编译设计，要求编译时启用`-kdb`。没有数据库时导入可支持的Verilog/SystemVerilog关联源码；Scala等保留为关联资料。多个数据库时拒绝猜测，可在`cmd_api.waveform_viewers.fsdb.args`中加入`"--dbdir", "Adder/libDPIAdder.so.daidir"`显式选择（放在`"--"`之前，路径相对所选工作区，也支持该工作区内的绝对路径）。数据库及其符号链接必须位于所选工作区内。

启动器打开FSDB、添加信号，并在同一Verdi窗口内停靠和显示波形，恢复时间窗口和游标。启动Tcl使用`wvGetFileTimeUnit`读取实际FSDB时间尺度，再通过`wvSetWindowTimeUnit`把显示单位设置为一个原生tick，随后应用JSON中的时间值。无法取得尺度时启动失败，不假定ns或将日志cycle当作时间。临时Tcl随Verdi进程结束清理，应用异常和返回码保留在Xpra诊断中。

Xpra运行环境需要Xpra/X11、Verdi及有效许可证，运行库分析环境参见本页FSDB依赖说明。替身测试覆盖参数、路径、Tcl字面量、多个时间尺度和错误处理；真实信号与时间定位仍需在实际许可环境执行集成验收。子工作区参数和Master的task/agent CMD代理前缀沿用全部接口。

### Surfer 总线展开与重建

多 bit 数字信号默认折叠显示总线值；点击信号左侧三角按钮可展开或收起逐位波形。位标签沿用波形声明的索引（含升序、非零起点和负索引），总线保留所选数值格式，子位保留 X/Z 状态。元数据加载和手动添加的数字总线使用相同交互，单 bit、时钟、实数、字符串及已有结构化解码不受影响。

内置 Surfer 固定于上游提交 `3ab79e7220f937cb3fadf1117f15d344e5f7e990`，本地原生修改及 EUPL-1.2 许可证位于 `ucagent/scripts/surfer/`。`bit_expansion.patch` 将 `bit_expansion.rs` 接入原生翻译器和默认关闭的结构行，实际位值直接来自波形数据。

重建需要 Rust 1.90+、`wasm32-unknown-unknown` 目标、`patch` 和 `wasm-bindgen-cli 0.2.113`。从上游克隆上述提交并初始化子模块；该提交的 `instruction-decoder` 为 `02bdcbfd5663a72e4a0b1b9d54519412d417fab1`，`f128` 为 `e60de395f0d6454c1dc546b87f06a6358425b6b6`。保持上游 `Cargo.lock` 不变，然后运行：

```bash
python ucagent/scripts/surfer/rebuild.py --source /absolute/path/to/surfer
```

脚本校验锁文件、目标源文件和绑定工具版本，以锁定依赖构建，更新配套 JS/WASM 及 `index.html` 的完整性摘要。`--wasm-bindgen` 可指定 CLI 路径；`--output` 可指定已有的预览资源目录。先停止使用该资源目录的服务再发布构建结果。

浏览器回归使用真实 CMD 服务和内置 WASM，覆盖 VCD/FST、Variables、全名、窗口/游标以及总线默认折叠和独立展开：

```bash
UCAGENT_RUN_SURFER_BROWSER_TESTS=1 python -m pytest -q tests/test_surfer_metadata_browser.py
```

需安装 Playwright Chromium/WebKit；`UCAGENT_SURFER_CHROMIUM_EXECUTABLE` 可指定本机 Chrome。原生位映射单元测试位于 `bit_expansion.rs`，复制到已应用补丁的上游目录后，可运行 `cargo test -p libsurfer --no-default-features translation::bit_expansion`。

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

`ucagent/util/waveform_formats/` 是一个 Python 包。公共协议与注册机制不依赖任何波形解析库；每个格式在独立文件中实现 reader，多个格式使用同一库时可以共享适配器：

```text
ucagent/util/waveform_formats/
├── __init__.py          # Public exports and built-in registration
├── protocols.py         # Reader, factory, scope, signal, and result contracts
├── registry.py          # Priority validation and extension dispatch
├── pagination.py        # Bounded, deterministic signal pages
├── queries.py           # Library-independent signal queries
├── adapter_pywellen.py  # Shared pywellen decoding and advanced options
├── adapter_wavekit.py   # Shared wavekit context and value-loading adapter
├── read_fst.py          # WellenFstReader / WavekitFstReader
├── read_vcd.py          # WellenVcdReader / WavekitVcdReader
└── read_fsdb.py         # WavekitFsdbReader
```

通过包入口导入 `WaveformReader`、`WaveformReaderFactory`、`WaveformScope`、`WaveformSignal`、`WaveformSignalMatches` 和 `WaveformValueChanges`。它们采用结构化类型：函数、可调用对象或 reader 类只要满足签名即可，不要求继承 UCAgent 或 wavekit 的基类。`WaveInfo` 只消费此公共协议；wavekit 的 `_load_value_changes` 仅在其专用适配器内调用。

### 工厂与读取接口

以下签名定义关键输入、输出；完整的函数说明位于 `protocols.py`：

```python
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, Literal, NotRequired, Protocol, TypedDict

BackendArgs = dict[str, Any] | Literal["help"]

class WaveformScope(Protocol):
    @property
    def full_name(self) -> str: ...

class WaveformSignal(Protocol):
    @property
    def full_name(self) -> str: ...
    @property
    def base_name(self) -> str: ...
    @property
    def width(self) -> int: ...

class WaveformSignalMatches(TypedDict):
    signals: Mapping[Any, WaveformSignal]
    total: int
    offset: int
    limit: int
    extensions: NotRequired[dict[str, Any]]

class WaveformValueChanges(TypedDict):
    mapped: Iterable[tuple[int, int]]
    extensions: NotRequired[dict[str, Any]]

class WaveformReader(Protocol):
    @property
    def backend_name(self) -> str: ...
    def configure_backend(self, backend_args: BackendArgs) -> dict[str, Any]: ...
    @property
    def begin_time(self) -> int: ...
    @property
    def end_time(self) -> int: ...
    @property
    def top_scopes(self) -> Sequence[WaveformScope]: ...

    def get_matched_signals(
        self, path: str, *, offset: int = 0, limit: int = 100,
    ) -> WaveformSignalMatches: ...

    def load_value_changes(
        self,
        signal: WaveformSignal,
        value_mapping: Mapping[str, int],
        begin_time: int | None = None,
        end_time: int | None = None,
    ) -> WaveformValueChanges: ...

class WaveformReaderFactory(Protocol):
    def __call__(self, path: str, /) -> AbstractContextManager[WaveformReader]: ...
```

| 接口 | 输入与输出约定 |
| --- | --- |
| `factory(path)` | 接收相对调用者当前目录或绝对的文件路径字符串，返回上下文管理器；进入上下文得到 `WaveformReader`。只打开该文件，不替换格式或寻找另一个文件。 |
| `backend_name` / `configure_backend(backend_args)` | 返回用于人工日志的后端名，在查询前处理一次高级参数；`{}` 使用默认功能，`"help"` 返回帮助且不加载 trace，无效选项抛出 `WaveformBackendArgumentError`。 |
| `begin_time` / `end_time` | 返回波形首、末时间戳，均包含端点。所有时间均为非负原生仿真 tick 整数，保留完整精度，不转换成 DUT cycle 或其他时间单位。 |
| `top_scopes` | 返回真实顶层 scope 序列，每项提供完整点分路径 `full_name`；没有 scope 时返回空序列。 |
| `get_matched_signals(path)` | 支持精确点分路径、`*`、递归 `**`、`/{regex}/`、花括号备选及范围。接收 `path` 及仅限关键字的 `offset=0`、`limit=100`。返回 `signals`、真实匹配总数 `total`、回显的 `offset` / `limit` 和可选 `extensions`；按完整信号名排序后返回 `[offset, offset + limit)` 页，保留后端映射键。无匹配或越界时 `signals` 为空；无效查询抛出异常，不加载轨迹。 |
| `WaveformSignal` | `full_name` 为精确完整路径，保留声明的位索引；`base_name` 为非限定名称；`width` 为正整数位宽。可额外保存后端原生句柄，但描述符只能交回产生它的 reader，且只在当前上下文内有效。 |
| `load_value_changes(...)` | 接收当前 reader 解析得到的 signal、四态映射和可选窗口；返回包含 `mapped` 及可选 `extensions` 的字典，具体规则见下文。 |
| 上下文退出 | 正常退出和分析异常时均释放文件、原生句柄等资源；打开失败时也清理已分配的部分资源。依赖缺失、文件损坏和查询错误向外抛出，由工具记录运维诊断。 |

`value_mapping` 包含小写 `0`、`1`、`x`、`z` 四个键及其整数位值，例如 `{"0": 0, "1": 1, "x": 0, "z": 0}`。后端逐位映射后按声明位序组合成无符号整数。`mapped` 是时间递增的 `(timestamp, mapped_integer)` 可迭代序列，不能因为映射后的数值相等而丢掉源信号变更；`WaveInfo` 分别用 value、X mask、Z mask 三种映射读取，并按时间戳合并。空信号轨迹返回空序列。

`begin_time=None`、`end_time=None` 表示该端无界。指定起点时，保留起点处或之前最近的一次状态及其原始时间戳；终点为开区间，只返回严格早于 `end_time` 的变化。这样显式窗口起始点发生变化时，工具仍能取得前一状态。多次读取不得修改元数据或污染同一信号的后续读取。

### 大量信号的分页与摘要

`get_matched_signals(path, *, offset=0, limit=100)` 默认返回排序后的 `[0, 100)`，即最多 100 条信号。`offset` 必须是非负整数，`limit` 必须是 1–1000 的整数。`total` 是完整查询的匹配数，不得把页大小当作总数。返回数量必须精确等于 `min(limit, max(total - offset, 0))`；空匹配和越界都返回空的 `signals`，并保留真实总数和请求边界。分页顺序在同一文件内按 `full_name` 稳定排序，不能重复、漏项或因查询其他页使已有描述符失效。

没有原生分页的库可以调用公开辅助函数 `paginate_signal_matches(mapping, offset=..., limit=...)`，保留映射键和描述符。内置 wavekit 适配器使用这个辅助函数：它仍需取得底层库的完整匹配映射，但不会把完整集合返回给 `WaveInfo` 或 LLM。具有原生分页的库可直接实现相同契约，避免构造全量描述符。查询扩展必须随当前页生成，不能把未返回信号的全量层级/关联详情塞入 `extensions`。

`WaveInfo` 的本地和 MCP 调用增加三个参数；省略 `pattern` 时用于目录浏览：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `signal_query` | `"**"` | 目录查询，支持精确路径与 reader 的查询语法；例如 `TOP.dut.**`。 |
| `signal_offset` | `0` | 排序后信号目录的起始索引。 |
| `signal_limit` | `100` | 每页最多显示的信号数，范围 1–1000。 |

例如读取第二页：

```python
result = tool.analyze(
    test_case_name="tests/test_demo.py::test_add",
    signal_query="TOP.dut.**",
    signal_offset=100,
    signal_limit=100,
)
```

假设有 250 条匹配，输出中的目录摘要如下（`signals` 实际包含该页 100 条完整路径及位宽）：

```yaml
signal_catalog:
  query: TOP.dut.**
  total: 250
  offset: 100
  limit: 100
  shown: 100
  end_offset: 200
  remaining: 50
  has_more: true
  next_offset: 200
  truncated: true
  next_call:
    test_case_name: tests/test_demo.py::test_add
    signal_query: TOP.dut.**
    signal_offset: 200
    signal_limit: 100
    include_extensions: false
    backend_args: {}
```

`signal_catalog.next_call` 可以原样传给 `WaveInfo`；它保留精确 TC、查询、页大小、扩展开关及 `backend_args`。第一页默认是 `[0, 100)`，后续为 `[100, 200)`、`[200, 250)`，最后一页没有 `next_call`。偏移越界时返回空页及回到 0 的恢复调用；查询无匹配时提示放宽 `signal_query`。`waveform_info.signal_count` 始终为整份波形的真实信号总数。

`signal_query_summary` 按查询字符串提供相同的分页计数，适用于目录、时钟、事件和上下文查询；有剩余时附带一个目录模式的 `next_call`。时钟提示及相似信号只基于当前有限目录页，未列出不表示波形中不存在。顶层 scope 名最多显示 100 个，并通过 `top_scope_count`、`top_scopes_remaining`、`top_scopes_truncated` 说明省略情况。

目录分页独立于事件分析上限 `max_signals`。分析时每个事件查询最多读取 `max_signals + 1` 个描述符用于超限检测，并使用真实 `total` 校验完整集合；多 pattern、上下文和时钟的并集仍受 `max_signals` 限制。超限时返回真实匹配数、有界预览和 `catalog_call`，不会只分析一页后报告成功。先分页查看并缩小 `pattern`，再执行事件分析；非默认目录参数与非空 `pattern` 混用会明确报错。没有 `test_case_name` 时不能设置非默认目录参数。

### 两个接口的输入输出示例

下面的例子也完整写在 `WaveformReader` 两个方法的 Protocol 定义注释中。首先查询一条信号：

```python
matches = reader.get_matched_signals("TOP.dut.data[7:0]", offset=0, limit=100)
```

输出示例中，`data_signal` 代表当前 reader 产生的信号描述符。映射键 `data` 仅作后端身份示意；扩展中的关联信号使用精确路径，不会自动成为匹配结果或事件触发信号：

```python
from types import SimpleNamespace

data_signal = SimpleNamespace(
    full_name="TOP.dut.data[7:0]", base_name="data", width=8,
)
result = {
    "signals": {"data": data_signal},
    "total": 1,
    "offset": 0,
    "limit": 100,
    "extensions": {
        "hierarchy": {"TOP.dut.data[7:0]": {"parent_scope": "TOP.dut"}},
        "related_signals": {"TOP.dut.data[7:0]": ["TOP.dut.valid", "TOP.dut.ready"]},
    },
}
```


继续使用 `signals` 中的描述符读取变化。假定源状态依次为 `0: 8'b00000000`、`10: 8'b00000011`、`20: 8'b0000xz01`、`30: 8'b11111111`：

```python
signal = matches["signals"]["data"]
changes = reader.load_value_changes(
    signal,
    {"0": 0, "1": 1, "x": 0, "z": 0},
    begin_time=15,
    end_time=30,
)
```

输出保留起点 15 之前的状态 10，并排除开区间终点 30：

```python
result = {
    "mapped": [(10, 3), (20, 1)],
    "extensions": {
        "raw_values": [[10, "00000011"], [20, "0000xz01"]],
        "quality": {"source": "native", "gaps": []},
    },
}
```


同一输入改用 X mask 映射时，`mapped` 为 `[(10, 0), (20, 8)]`；改用 Z mask 映射时为 `[(10, 0), (20, 4)]`。没有扩展时，两个方法分别返回 `{"signals": page, "total": total, "offset": offset, "limit": limit}` 和 `{"mapped": rows}`，不要求空的 `extensions` 字段。

### 适配其他库并注册

下例演示独立插件中的 `read_wlf.py`。`my_wlf_library` 是示意库：假设它返回满足上述元数据与查询语义的对象，`read_mapped` 满足四态映射、源变更保留和窗口规则，`query_metadata(path, page_signals)` 仅为当前页生成可 JSON 序列化的层级/关联信息，`signal_quality` 返回可 JSON 序列化的质量信息。接入实际库时，在这个格式文件中完成对象和语义转换；若该库只支持部分查询语法，适配器需补齐其余查询能力。后端构造函数负责清理打开失败时的资源。

```python

# my_plugin/readers/read_wlf.py

from contextlib import AbstractContextManager
from ucagent.util.waveform_formats import (
    WaveformSignalMatches, WaveformValueChanges, WaveformBackendArgumentError,
    paginate_signal_matches,
)

class ExampleWlfReader(AbstractContextManager):
    """Adapt the chosen WLF library to the UCAgent reader contract."""

    backend_name = "example"

    def configure_backend(self, backend_args):
        """Accept defaults and describe the supported advanced options."""
        if backend_args == "help":
            return {"options": {}, "examples": [{"backend_args": {}}]}
        if backend_args != {}:
            raise WaveformBackendArgumentError('Use backend_args="help".')
        return {}

    def __init__(self, path: str):
        self.path = path
        self.backend = None

    def __enter__(self):
        from my_wlf_library import Reader

        self.backend = Reader(self.path)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.backend.close()
        return False

    @property
    def begin_time(self):
        return self.backend.begin_time

    @property
    def end_time(self):
        return self.backend.end_time

    @property
    def top_scopes(self):
        return self.backend.top_scopes

    def get_matched_signals(self, path, *, offset=0, limit=100) -> WaveformSignalMatches:
        page = paginate_signal_matches(
            self.backend.find_signals(path), offset=offset, limit=limit,
        )
        page["extensions"] = self.backend.query_metadata(path, page["signals"])
        return page

    def load_value_changes(
        self, signal, value_mapping, begin_time=None, end_time=None,
    ) -> WaveformValueChanges:
        return {
            "mapped": self.backend.read_mapped(
                signal, value_mapping, begin_time=begin_time, end_time=end_time,
            ),
            "extensions": {"quality": self.backend.signal_quality(signal)},
        }

# Plugin initialization

from ucagent.tools import WaveInfo, register_waveform_reader
from my_plugin.readers.read_wlf import ExampleWlfReader

register_waveform_reader("wlf", ExampleWlfReader, backend="example")
tool = WaveInfo(
    workspace="/path/to/workspace",
    test_dir="unity_test/tests",
    format_priority=["fst", "vcd", "fsdb", "wlf"],
    backend_priority={"wlf": ["example"]},
)
result = tool.analyze(test_case_name="test_add")
```

`register_waveform_reader(format_name, factory, *, backend="default")` 接受小写、不带点的扩展名和小写后端名；注册时不打开文件或加载解析依赖。应在应用或插件初始化时显式注册，并在创建 `WaveInfo` 之前完成。同一格式允许不同后端，同一 `(format_name, backend)` 不能重复或覆盖。未指定名称的单一插件使用 `"default"`；配置其他后端名时必须已注册。完整工作流还需配置分析与后端优先级：

```yaml
runtime_options:
  waveform_analysis_format_priority: [fst, vcd, fsdb, wlf]
  waveform_analysis_backend_priority:
    wlf: [example]
```

额外依赖放在工厂调用或上下文进入时加载。FST/VCD 的默认实现共用 `adapter_pywellen.py`，备选 wavekit 实现及 FSDB 共用 `adapter_wavekit.py`。未请求高级功能时，两个接口只返回标准字段。新格式共享发现、分析、receipt 和重放流程；注册分析读取器不会扩展浏览器查看器的解码能力。

### 高级参数与帮助查询

本地和 MCP 的 `backend_args: dict | Literal["help"]` 默认 `{}`。字典允许嵌套 JSON 数据，拒绝非字符串顶层键、原生对象及 NaN/Infinity。参数只作用于当前 reader，不选择库、不执行任意方法或代码、不改变标准证据语义。非空参数及 `"help"` 都要求指定 `test_case_name`；帮助查询需省略事件 `pattern`。

```python
help_result = tool.analyze(
    test_case_name="tests/test_demo.py::test_add",
    backend_args="help",
)
catalog = tool.analyze(
    test_case_name="tests/test_demo.py::test_add",
    signal_query="TOP.dut.**",
    signal_limit=100,
    backend_args={"signal_metadata": True},
    include_extensions=True,
)
analysis = tool.analyze(
    test_case_name="tests/test_demo.py::test_add",
    pattern=[{"signal": "TOP.dut.data[7:0]", "event": "unknown"}],
    start_step=10,
    end_step=30,
    backend_args={"statistics": True},
    include_extensions=True,
)
```

工具在打开所选 reader 后调用 `configure_backend()`，再执行目录查询或事件分析。传入深拷贝，后端不得改变其他调用的参数。`"help"` 只返回 `status: advanced_help`、文件选择和 `extensions.backend` 中的用法；即使 `include_extensions=False` 也显示显式请求的帮助，不创建事件证据。pywellen 帮助示例：

```yaml
extensions:
  backend:
    options:
      signal_metadata:
        type: boolean
        default: false
        description: Return declaration metadata for the current page.
      statistics:
        type: boolean
        default: false
        description: Return source-state counts for each loaded signal and window.
    examples:
      - backend_args:
          signal_metadata: true
        include_extensions: true
      - backend_args:
          statistics: true
        include_extensions: true
```

当前 pywellen 的 `signal_metadata` 在查询页的 `extensions.signal_queries[query].signal_metadata` 返回父 scope、类型、方向、声明/选择索引、枚举及 VHDL 类型。存在枚举时，`enum_type` 为 `[类型名, [[位值, 标签], ...]]` 数组；不存在时为 `null`。`statistics` 在 `extensions.value_changes[signal][channel].statistics` 返回 `source_states`、`unknown_states`、首末时间及读取边界；计数包含重建窗口起始值所需的此前状态，不等于窗口内事件数。两个选项都只接受布尔值，默认关闭。wavekit 当前帮助的 `options` 为空，仅接受 `{}` 和 `"help"`。

普通高级结果沿用默认隐藏策略，通过 `extensions_available` 提示字段，`include_extensions=True` 才展示内容。`configure_backend()` 的调用级结果放在 `extensions.backend`，其余结果仍按查询页/信号/映射/窗口归属；不得用扩展绕过分页。未知选项或无效值返回 `invalid_backend_args` 及可直接调用的 `details.help_call`，不会换库。分页、超限目录调用、推荐取证调用、收据、恢复调用和重放均保留 `backend_args`；显式返回的扩展参与语义比较。

插件必须实现 `backend_name` 和 `configure_backend()`。无高级功能时接受 `{}` 返回 `{}`，接受 `"help"` 返回 `{"options": {}}`，拒绝其他非空字典；有功能时在帮助中说明参数类型、默认值、结果位置、范围与可执行示例，验证后存于当前 reader 实例，再由查询/读取接口生成扩展。不得返回原生句柄、秘密或无界数据。

### 扩展信息与按需查看

`get_matched_signals` 返回字典中的 `signals`、`total`、`offset`、`limit` 必需；`load_value_changes` 返回字典中的 `mapped` 必需。两个接口的 `extensions` 均可省略或为空字典。非空扩展字段由后端定义，每层对象的键都必须是字符串，值只允许 JSON 对象、数组、标量或 `null`，不得含 Python tuple、原生描述符、句柄、NaN/Infinity 或敏感信息。查询扩展属于当前查询页，可包含该页信号的层级、关联信息，以及有界的查询级摘要；不得把所有未返回信号的详细信息放入扩展绕过分页。读取扩展属于当前信号、映射和时间窗口。后端应按各自范围限制信息量；`max_points` 只限制标准时间线，不截断扩展字典。格式错误会导致当前查询或分析失败并记录运维诊断。

`WaveInfo` 的本地 `analyze()` 和本地/MCP 工具调用均支持 `include_extensions: bool = False`。默认不返回扩展内容；存在非空扩展时，通过 `extensions_available` 返回字段名，并通过 `extensions_hint` 提示 LLM 判断是否需要查看。输出按以下范围分组，空分组不输出：

- `backend`：`configure_backend()` 返回的当前调用级高级功能结果或显式帮助。
- `signal_queries`：按原样查询字符串（包括 `**`）保留最近一次查询页的扩展；对应范围见 `signal_query_summary`。
- `value_changes`：按完整信号名及 `value` / `x_mask` / `z_mask` 保留读取扩展。

默认输出中的相关字段示例：

```yaml
extensions_available:
  signal_queries:
    TOP.dut.result: [hierarchy, related_signals]
  value_changes:
    TOP.dut.result:
      value: [quality]
extensions_hint: "Additional signal information is available in the listed fields. If it would help your analysis, repeat this WaveInfo call with the same arguments and include_extensions=true to view its contents."
```

LLM 需要这些信息时，保持目标 TC、信号和窗口等查询参数不变，追加 `include_extensions=true`。输出增加 `extensions`，按相同分组保留扩展内容；`extensions_available` 仍保留，此时不再显示查看提示：

```yaml
extensions:
  signal_queries:
    TOP.dut.result:
      hierarchy:
        TOP.dut.result:
          parent_scope: TOP.dut
      related_signals:
        TOP.dut.result: [TOP.dut.valid, TOP.dut.ready]
  value_changes:
    TOP.dut.result:
      value:
        quality:
          source: native
          gaps: []
```

查询扩展只来自实际执行的查询，不额外加载波形值；因此信号目录等元数据调用也可返回查询扩展。读取扩展只来自实际加载过的信号，包括用于对齐的时钟和上下文信号。仅列文件的 inventory 不调用 reader，不返回扩展。无匹配的查询可以保留其关联候选信息，但这些候选不会被当作匹配信号。没有扩展时，无论开关取值如何都不输出三个扩展相关字段。该参数不改变标准事件、时间线和时间窗口。

显式返回的各类扩展内容均随工具调用的签名 receipt 保存，并参与语义重放比较；默认调用只保存可用字段名，不保存扩展内容。动态 Bug 文档的中央波形记录格式保持既有契约。

新增后端时，测试独立于 wavekit 的注册与分析、查询层级/关联信息、无匹配和无轨迹的元数据调用、四态映射、窗口边界、空轨迹、大整数、扩展省略/按需返回及异常清理。相关回归：

```bash
python -m pytest -q tests/test_waveform_backends.py tests/test_waveform_formats.py tests/test_waveform_tool.py
```
