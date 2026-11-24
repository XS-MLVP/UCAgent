
# ToffeeUT

独立的 UCAgent UT 插件，使用当前环境中的 `uc-toffee`，输出采用 ucv4xs 的工程结构。
旧 UnitTest、DesignWithPPA 和默认工作流不变。这里的 `env/agent` 指 DUT 事务环境，
不是 LLM 子 Agent。

## 安装

在 UCAgent 仓库根运行，插件拥有自己的一个 venv：

```bash
python3 ucagent/plugins/ToffeeUT/scripts/setup_env.py
source ucagent/plugins/ToffeeUT/.venv/bin/activate
python -m ucagent --validate-plugin ./ucagent/plugins/ToffeeUT
```

脚本安装核心运行依赖时排除 `pytoffee` 和 `toffee-test`，把当前 UCAgent 源码加入
此 venv，不改核心依赖文件、不升级 ucv4xs 的环境。不要在这个环境再执行普通的
`pip install UCAgent`，它会带入同样占用 `toffee` 导入名的 Legacy 依赖。

## 使用自己的 opencode 终端

工作区应包含自己的 RTL/资料，若已有 Picker DUT 包，可放在 `<workspace>/<DUT>/`。
启动时不自动编译 RTL，不调用任何示例 DUT：

```bash
python -m ucagent /abs/workspace MyDUT \
  --plugin ./ucagent/plugins/ToffeeUT --plugin-workflow toffee-ut:ut \
  --mcp-server-no-file-tools --mcp-server-port 5000 -hm --tui
```

这条命令只启动阶段与工具服务，不启动模型回合。在任务工作区的另一个终端启动你
自己的 opencode；将 MCP 地址接到 `http://127.0.0.1:5000/mcp`，用 `/models` 选择
你已配置的模型。插件不指定模型，也不生成或改写你的 opencode 配置。完整接入示例
及可选自动调用方式见 [开发和运行契约](docs/development.md)。

默认工程位于工作区 `ut_project/`。在已有 ucv4xs 工程内工作时，显式使用
`--output <工程相对路径>`，保留其 `workspace.json`、`ucv.json`、包名及 fixtures。
工程本身就是 workspace 时可用 `--output .`；若原生包/RTL 链接位于仓库缓存，
workspace 应选仓库根，确保链接仍在工作区范围内。不复制平行工程，不在同一任务
同时运行另一个 UCAgent 实例。

## 按本次任务接入

已有项目首次交接可选 `--plugin-workflow toffee-ut:adopt`。该流程只读相关成果，
生成本次任务的阶段与复验建议，交用户确认；不要求先完成全部旧阶段或取得全量 PASS。
主流程仍是 `toffee-ut:ut`，默认保留完整配置范围，也可用 `ut_task` 与
`ut_task_stages` 明确只执行本次选定的父阶段或子阶段。

接入不会自动切换流程或迁移阶段进度。切换前应保存需要的旧进度，再显式不加载另一
流程的历史；配置和启动示例见[按任务接入与选择阶段](docs/development.md#按任务接入与选择阶段)。

## 文档分流

`runtime_options.ut_document_mode` 为 `auto`（默认）、`provided` 或 `derive`。
auto 根据非空资料选择“复核已有规格”或“从源码补建候选规格”的处理方式；两种
输入都保留原工作流的 20 个独立顶层阶段及子阶段；模型、Mock、人工复核按明确的配置
启用，原生行覆盖默认启用，不会因资料分流合并其他阶段。
有文件不代表规格可信，RTL 推断不能自动升级为独立 oracle。

可用 `--config /abs/project.yaml` 覆盖：

```yaml
runtime_options:
  ut_document_mode: provided
  ut_documents: [inputs/spec.md]
  ut_rtl_dirs: [rtl]
  ut_dut_package: MyDUT
  ut_workers: 1
  ut_timeout: 1200
```

显式指定的资料路径必须存在；路径相对于 workspace。没有文档不阻止分析，但
未确认依据和未验证范围不得算作 PASS。

## 自动化与方法的边界

- `UTProject` / `toffee-ut`：资料盘点、按需建目录、检查文档/实现、汇总报告。
- `RunToffee`：使用当前 venv 执行真实测试，保留精确 nodeid、完整阶段判定和产物。
- Skill：保留 10 个独立问题方法、3 个导航／项目入口，以及 P01–P12 速查卡和 4 篇待审参考；按问题读取，不承担生成、执行或计数。
- 禁用 Skill 不改变阶段任务、工具和验收标准。

方法入口见 [问题索引](src/toffee_ut/Guide_Doc/ut-methods.md)，详细规范见 [开发和运行契约](docs/development.md)。插件本身的回归为
`python -m pytest -q ucagent/plugins/ToffeeUT/tests`；不运行 Adder 或额外仿真示例。
