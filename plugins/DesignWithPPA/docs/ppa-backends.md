
# PPA 分析后端与 PDK 接入

`AnalyzePPA` 将工作区输入、报告发布与具体分析工具分开。两个 workflow、直接调用
`AnalyzePPA` 以及 `RunDesignConsistency` 都使用解析后的 `design_with_ppa.ppa` 配置。
默认组合是 `yosys_opensta` 和 Nangate45 typical，执行布局布线前的面积、时序与
独立性能 TC 波形驱动的功耗分析。当前内置一个分析后端；其他工具通过 Python 接口接入。

## 配置默认分析与其他 PDK

默认配置如下，两个 workflow 均提供相同的后端与 PDK 配置入口：

```yaml
design_with_ppa:
  ppa:
    backend: yosys_opensta
    backend_options: {}
    pdk:
      name: nangate45
      corner: typical
      files: {}
      tie_high: null
      tie_low: null
      parameters: {}
    liberty_file: null
    sdc_file: null
    max_timing_paths: 10
    max_power_instances: 10
```

`nangate45` 预设在未提供 `files.liberty` 时加载插件内的 typical Liberty，并提供
`LOGIC1_X1/Z`、`LOGIC0_X1/Z` 常量映射。捆绑文件只支持 `corner: typical`。
`name` 使用其他值时不会补充任何工艺文件或常量单元。

接入其他工艺时，将获准使用的工艺文件放入工作区，并明确设置工艺、corner 和单元：

```yaml
design_with_ppa:
  ppa:
    backend: yosys_opensta
    backend_options: {}
    pdk:
      name: project_process
      corner: ss_0p8v_125c
      files:
        liberty: [technology/ss.lib]
      tie_high: {cell: TIEHI, port: Y}
      tie_low: {cell: TIELO, port: Y}
      parameters: {}
```

示例中的文件与单元名需要替换成实际工艺提供的内容。`corner` 是测量条件的身份，
实际模型由选定文件决定；设置 corner 名称不会转换或生成对应模型。默认后端目前要求
恰好一份 Liberty，工艺也必须能被 Yosys 和 OpenSTA 处理。常量单元可分别省略；
若产生的常量网络不能被后续工具接受，分析会返回失败诊断。

`files` 是通用的“资源名 → 有序文件列表”映射。其他后端可定义 `lef`、`rc`、
`model` 等资源名，也可以使用多份库。每个已声明列表必须非空且路径唯一；所有文件
都必须存在、位于工作区内且不经过符号链接，每份文件都记录 SHA-256。
测量结束后会重新校验工艺身份；期间改动工艺文件会使本次分析失败，需完成编辑后重试。
`parameters` 保存后端需要的非文件工艺设置。参数支持有限 JSON 值，禁止 NaN/Infinity。
具体后端负责检查资源是否齐全及参数是否适用。

现有 `ppa.liberty_file` 和直接调用 `AnalyzePPA(liberty_file=...)` 的含义是替换当前
PDK 的 `files.liberty`，其他 PDK 资源保留。该参数要求工作区内的 `.lib` 文件。
替换工艺时应同时设置正确的 `pdk.name`、`corner` 和映射单元。

## 实现独立分析后端

将实现安装到 UCAgent 使用的 Python 环境，然后配置可导入的 `module:Class`：

```yaml
design_with_ppa:
  ppa:
    backend: project_ppa.adapter:ProjectBackend
    backend_options:
      effort: medium
    pdk:
      name: project_process
      corner: ss_0p8v_125c
      files:
        liberty: [technology/ss.lib]
        lef: [technology/cells.lef]
      parameters:
        temperature_c: 125
```

实现继承 `PPABackend`，提供稳定的 `name`、`version` 和
`analyze(request, context) -> PPAResult`。每次分析创建一个后端实例。
`version` 标识会影响测量的后端实现，改变算法或工具选项解释时应更新。

| 对象 | 后端可以使用的内容 |
| --- | --- |
| `PPARequest.arguments` | 顶层模块、约束、波形层次、报告详情数量和超时等已校验参数 |
| `rtl_files`、`waveform_files`、`sdc_file` | 已解析且检查过的绝对路径；RTL 包含所需公共库 |
| `systemverilog` | RTL 语言转换后是否需要 SystemVerilog 前端 |
| `waveform_provenance` | 有序的 TC 路径、格式、大小和内容哈希 |
| `pdk.config`、`pdk.files`、`pdk.provenance` | 工艺设置、绝对文件集合和可发布的工艺身份 |
| `options` | `backend_options` 中的非秘密 JSON 配置 |
| `PPAContext.run_dir` | 本次运行独占、结束后删除的临时目录 |
| `deadline`、`check_deadline()` | 共用单调时钟截止时间与进程内计算的检查方法 |
| `run_process(argv, cwd, deadline)` | 无 shell 子进程执行，支持剩余超时及取消进程组 |
| `progress(message)` | 向工具调用界面提交进度 |

以下是一个完整的适配器示例。`project-ppa-wrapper` 是接入方实现并安装的命令，
负责调用真实工具、检查工具输出，并生成下一节规定的标准结果 JSON：

```python
"""Project PPA backend adapting an installed analysis wrapper."""

import json
from design_with_ppa.ppa import PPABackend, PPAContext, PPARequest, PPAResult


class ProjectBackend(PPABackend):
    """Measure one design through the project's installed tool wrapper."""

    name = "project_ppa"
    version = "1"

    def analyze(self, request: PPARequest, context: PPAContext) -> PPAResult:
        """Execute analysis and return measured values in canonical units."""

        context.check_deadline()
        context.progress("PPA: analyzing with project toolchain")
        payload = {
            "arguments": request.arguments.model_dump(),
            "rtl_files": [str(path) for path in request.rtl_files],
            "systemverilog": request.systemverilog,
            "waveform_files": [str(path) for path in request.waveform_files],
            "waveform_provenance": list(request.waveform_provenance),
            "sdc_file": str(request.sdc_file) if request.sdc_file else None,
            "pdk": request.pdk.config.model_dump(),
            "technology_files": {
                key: [str(path) for path in paths]
                for key, paths in request.pdk.files.items()
            },
            "options": request.options,
        }
        inputs = context.run_dir / "request.json"
        output = context.run_dir / "result.json"
        inputs.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        completed = context.run_process(
            ["project-ppa-wrapper", "--request", str(inputs), "--result", str(output)],
            context.run_dir,
            context.deadline,
        )
        if completed.returncode:
            raise RuntimeError("Project PPA analysis failed: " + completed.stderr[-2000:])
        context.check_deadline()
        return PPAResult.model_validate_json(output.read_text(encoding="utf-8"))
```

后端代码和 wrapper 都属于可信的本地扩展，不在 Python 沙箱内运行。必须通过提供的
runner 启动子进程；进程内长计算定期检查 deadline，耗时阶段提交 progress。
后端自行检查所需命令和许可证；自定义后端不会触发默认 Yosys/OpenSTA 分析。
插件通用依赖检查不要求这些默认 PPA 命令，默认后端在执行时诊断缺失命令。
workflow 自身的构建依赖仍然适用，例如 `repo-module-tdd` 的模块接口提取使用 Yosys。

## 标准结果、证据与可比较性

`PPAResult` 包含 `summary`、`details`、`hotspots`、`waveform_aggregation`、
`diagnostics`、`tools` 和可选 `waveform_scope`。不包含最终报告 ID、状态、输出路径或缓存。
下面的数值只演示结构，接入方必须用真实工具和波形的分析结果填充：

```json
{
  "summary": {
    "design_type": "combinational",
    "area": {"total": 12.5, "unit": "um^2"},
    "timing": {
      "metric_kind": "critical_path_delay",
      "critical_path_delay_ns": 2.0,
      "maximum_frequency_hz": 500000000.0
    },
    "power": {"total_w": 0.001}
  },
  "details": {"classification": {"evidence": "mapped combinational cells"}, "area_by_cell_type": {}, "timing_paths": [], "power_groups": []},
  "hotspots": {"timing_paths": [], "power_instances": [], "findings": []},
  "waveform_aggregation": {
    "method": "duration_weighted_independent_tc_activity",
    "reliable": true,
    "test_cases": [{"path": "output/performance/tc.vcd", "status": "valid"}],
    "merged_input_bits": [{"input_bit": "a", "density_hz": 1000000.0, "duty_cycle": 0.5}]
  },
  "diagnostics": [],
  "tools": {"project_tool": {"version": "1.0"}},
  "waveform_scope": "tb.dut"
}
```

面积需声明单位，时序使用 ns/Hz，功耗使用 W。`metric_kind` 使用
`critical_path_delay` 或 `minimum_clock_period`，分别要求正的关键路径延迟或最大频率。
`design_type` 是 `combinational`、
`sequential` 或证据不足时的 `unknown`。对独立 TC 按总仿真时长加权活动，不能拼接
波形或重复计数；可靠活动的 `test_cases` 必须覆盖请求中的完整有序路径集合。
工具版本放在 `tools.<tool>.version`。详情和热点尽可能使用默认报告的字段，受
`max_timing_paths`、`max_power_instances` 限制，不在结果中保留临时文件引用。

默认后端的总面积和总单元数来自 Yosys Liberty 映射统计；时序单元数来自
OpenSTA 根据 Liberty 识别的寄存器/锁存器实例，不依赖工艺单元的名称。
若时序分析未完成，时序/组合单元的分类计数保持 `null`，总面积和总单元数仍可保留。

缺少任一主指标、未知电路类型或不可靠波形会得到 `partial`；后端应给出含
`error_code`、`error`、`next_action` 的诊断。非法主指标、非有限 JSON 数字、错误
返回类型、输入或执行失败得到 `error`。成功、部分成功和失败均经过公共缓存与发布流程。
异常不能被包装成虚构的测量值。

最终报告 schema 为 `1.2`。`provenance.backend` 记录后端选择、名称、实现版本和
选项，`provenance.pdk` 记录工艺名称、corner、全部资源哈希、常量单元与参数。
报告比较同时检查这些身份、工具版本和面积单位，以及 RTL 公共库、约束、顶层模块、
时序指标种类、TC 集合和活动条件。不同条件下仍可查看数值差异，但不会标为 PPA 改善。

两个 workflow 都冻结后端/PDK 配置及工艺文件内容；更改后需要重新建立基线。
运行时快照导出 `ppa.backend`、`ppa.pdk.name`、`ppa.pdk.corner` 等标量，完整测量身份
保存在报告及 workflow 记录里。`backend_options`、PDK 参数和工具日志不得包含密钥或 token。
无需启用 Skills 即可配置和执行分析。

## 源码位置与验证

`src/design_with_ppa/ppa/` 按职责组织：

| 模块 | 职责 |
| --- | --- |
| `tool.py`、`models.py` | 工具入口、公共参数、输入限制、溯源与报告发布 |
| `backend.py`、`config.py` | 后端扩展接口、结果校验、PDK 与解析后的配置 |
| `backends/yosys_opensta.py` | 默认工具链执行、技术映射及度量组装 |
| `activity.py`、`parsers.py` | 波形活动处理、默认工具报告解析 |
| `comparison.py` | 指标差异和可比较条件 |
| `storage.py`、`process.py`、`dashboard.py`、`common.py` | 缓存、进程生命周期、看板快照及通用报告操作 |

公共导入为 `from design_with_ppa.ppa import AnalyzePPA, PPABackend, PPARequest,
PPAContext, PPAResult, PPAConfig, PDKConfig`，包顶层也导出这些名称。
面向 Python 直接调用时，通过 `AnalyzePPA(analysis_config=PPAConfig(...))` 设置后端与工艺，
继续使用 `AnalyzePPAArgs` 提供本次设计、波形和约束。

在插件根目录运行 `python3 -m pytest tests/test_ppa_backends.py tests/test_ppa_tool.py`，
分别验证独立后端、工艺边界、条件变化、超时取消，以及默认工具链的真实分析。
工作流回归还覆盖配置导出、冻结身份、缓存复用和优化日志。
