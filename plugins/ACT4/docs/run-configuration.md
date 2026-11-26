
# 生成运行配置

两个生成工作流共用一个 YAML 输入：[完整示例](../examples/generation.yaml)。用户只需确定目标、
路线、工作区和按类别的处理意图；具体源文件、验证命令和证据由运行中的 agent 发现并填写，
不是额外要求用户预先编写的配置。香山交付继续使用自己的入口，不受本配置影响。

## 启动和复用

安装或更新本插件后运行：

```bash
act4-run plugins/ACT4/examples/generation.yaml --print-command
act4-run plugins/ACT4/examples/generation.yaml
act4-status /absolute/path/to/workspace
```

每次 `act4-run` 首先打印本轮解析后的配置（含九类策略、来源、限制、工作区）和实际启动参数，不打印 UCAgent 全局配置或认证环境。`--print-command` 打印同一份 JSON，不创建工作区、不启动模型。
`act4-status` 只读，也可运行 `python -m ucagent_act4.run_status <workspace>`。输出启动器锁状态
（未通过启动器记录时为 unknown）、阶段、最近正式 Check/Complete 和阻塞处置；配置矩阵分别列出
适用源码数、完整签名链、runner 摘要中的通过条目。摘要计数不是对进程退出码的复验；
reported_sail_coverage 是整次运行声明的 coverage 状态，不是按配置实测的命中数。
`native_tests_passed` 只在原生构建、运行及日志摘要可核对时列出；没有该字段表示未知，不是零。
`all_completed` 描述流程阶段；`finding_outcome` 单独列已修复数、本地与外部待办 ID，未取得可信终审时为 `null`。
预检报告和独立诊断不推进正式阶段；不要因为后台进程存活就继续等待同一个阻塞。
也可用 `python -m ucagent_act4.run_config <run.yaml>` 调用同一入口。
启动器固定使用 Codex 后端、MCP、自动循环和完成退出；模型认证沿用 UCAgent 的设置，配置文件不放密钥。
工作区保存解析后的 `.ucagent/act4-run.yaml`。恢复时使用同一配置；修改目标、来源、策略或限制时换新工作区，
不要编辑旧运行的证据来强行续跑。配置中选择分支只代表版本选择策略，实际提交由资源阶段固定并记录；
若要跨运行复现同一版本，请把 `act4_ref`、`manual_ref` 改为记录的提交 SHA。

## 配置项

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 固定整数 `1` |
| `suite` | [目录](test-suites.md)中的精确 Test Suite 标识 |
| `workflow` | `privileged-suite-generation` 或 `unprivileged-suite-generation`，按是否需要 trap/状态序列选择 |
| `workspace` | 独立运行目录；相对路径以 YAML 所在目录为基准 |
| `output` | 工作区内结果目录，默认 `act4_assets`，不能覆盖源码或配置目录 |
| `target_context` | 用户的范围、目标及假设；独立 ISA 计划原样保留 |
| `upstream` | ACT/规范根目录和版本、共享缓存位置；默认根目录名由资源阶段解析为共享来源 |
| `defaults` | suite 资产默认 `mode: improve`、`source: upstream`、`on_missing: generate`；不覆盖共享输入保护 |
| `assets` | 九类资产的覆盖配置，未写类别继承默认值 |
| `limits` | 连续无进展暂停轮数、每轮实验总次数、实验总秒数；不是模型 token 预算 |
| `accepted_partial_findings` | 默认 `[]`。只在操作方有意按指定 F-ID 部分交付时填写（如 `[F8]`），不豁免证据要求、不把缺项计为修复；不要把跨运行的同编号当作同一问题。 |
| `runtime` | `use_skill` 为布尔值；`mcp_port: -1` 自动选择端口，也可指定 1..65535 |

九类键为 `norm_rules`、`udb_params`、`rvvi`、`rvmodel_macros`、`testplan`、`ctp`、`coverpoints`、`sail`、`tests`。
未知键、无效目标和含糊策略会报错，不悄悄忽略。显式来源目录必须和工作区分离，不允许软链接路径。
`upstream` 指定的是干净的固定源码仓库；要使用上次未提交的修改，使用该类别的 `source: local`。

## 按类别选择

把完整配置的 `assets: {}` 替换为例如：

```yaml
assets:
  testplan:
    mode: regenerate
  coverpoints:
    mode: improve
    source: local
    path: /absolute/previous-run
  tests:
    mode: improve
    source: local
    path: /absolute/another-run/act4_assets
    on_missing: generate
```

- `repair_only`：Norm Rules、UDB/Params、RVVI、RVMODEL Macros、Sail 五类共享输入始终使用此策略。默认不改；仅允许对明确缺陷做可复现的修复。上游找不到默认 `on_missing: report`，显式本地来源默认 `error`，也可显式选择 `report`。不能用全局 regenerate 或缺项回退为其生成新内容。suite 自身的规则/参数映射不等于修改规则或参数定义。
- `improve`：对于 testplan、CTP、coverpoints、tests，在选定来源上检查、补缺或修复；原内容正确时可以完全不改，最终补丁可以为空。
- `regenerate`：从 ISA 重新设计这一类别，不读取该类别既有测试设计；不填写 `source/path/on_missing`。
  ISA、公共框架 API 和其他类别不是应被忘掉的内容，必须继续核对依赖及一致性。
- `source: local`：agent 在该目录内定位对应 suite 和类别的原生源码，不要求用户给具体文件名。
  默认找不到即报错；只有显式 `on_missing: generate` 才转为新生成，不能静默改成上游来源。
- 本地目录可包含源码或补丁。只有 patch 时必须有确切基线，且与选定上游提交一致；在隔离副本
  验证应用补丁后，只导入所选类别的源文件。原目录不改；ELF/bin 不能替代可编辑源资产。
- 同一公共文件可以属于多类，但必须选择相同来源、兼容策略；两个类别要求冲突时先解决，不以覆盖顺序决定语义。

输出的策略表记录用户**要求怎样处理**，九类 checklist 记录**实际怎样处理**及验证状态。
二者不可混同：请求 improve 不等于一定修复，重生成也不能被报告为复用。

## 执行和验收边界

先只读 ISA 形成独立计划，再定位、冻结和导入已有资产；随后执行基线审查、增量/重新生成和复验。
保留独立计划与既有资产的差异、缺陷及处理理由，而不要求所有缺口都被描述成“已有资产有 bug”。
商业工具可选；未验证、未完成或证据不足必须保留具体原因和下一步，不能宣称九类资产全部正确。
阶段中的审查可记录部分成果，但最终成功仍要求所有适用的必需生成和验证门禁通过。

源文件归属和规范语义仍需 AI 的有来源判断；checker 保证选择、哈希、引用、前后验证和补丁一致，
不能自动证明 ISA 语义绝对正确。本插件不提供操作系统沙箱，也无法抹除模型先验知识；
外层 agent 和 shell 同样必须遵守来源边界。
