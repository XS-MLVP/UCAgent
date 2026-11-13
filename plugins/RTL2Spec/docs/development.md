
# RTL2Spec 开发与验证

安装和使用见 [README](../README.md)，实现原理、工作流与 checker 设计见[插件原理与设计](architecture.md)。本文介绍代码组织、开发验证和打包方法。通用贡献流程遵循 [UCAgent 贡献指南](https://github.com/XS-MLVP/UCAgent/blob/main/CONTRIBUTING.md)，插件接口与发布约定见 [UCAgent 插件开发文档](https://github.com/XS-MLVP/UCAgent/blob/main/docs/content/03_develop/09_plugins.md)。

## 项目结构

| 层级 | 当前名称 |
| --- | --- |
| 项目目录 | `RTL2Spec` |
| Python 发行包 | `ucagent-rtl2spec` |
| 插件 ID | `rtl2spec` |
| Python 导入包 | `rtl2spec` |
| 工作流 ID | `xiangshan-design-document`, `generic-design-document` |

```text
UCAgent/plugins/RTL2Spec/
├── ucagent-plugin.toml          # 源码入口，python_path = "src"
├── pyproject.toml               # 依赖、安装入口和 wheel 资源
├── setup.py                     # 构建时复制根目录 LICENSE、NOTICE.md
├── MANIFEST.in                  # sdist 范围
├── Makefile                     # 维护命令
├── docs/                        # 原理与设计、开发验证、工具参考
├── src/rtl2spec/
│   ├── *.py                     # 插件实现，职责见下表
│   ├── scripts/                 # 环境准备与 RTL 编译脚本
│   ├── workflows/               # 工作流 YAML
│   ├── launch_configs/          # 用户启动配置模板
│   └── Guide_Doc/               # 生成指南与唯一写作模板
├── examples/GenericBlock/       # 可直接捕获的参数化 RTL 示例
└── tests/                       # 回归测试及 fixtures/
```

下表路径相对于 `src/rtl2spec/`：

| 模块 | 职责 |
| --- | --- |
| `__init__.py`、`plugin.py` | 插件版本、能力和依赖声明，启动前检查输出目录 |
| `tools.py` | 工具参数、工作区权限、子进程和超时管理 |
| `launch.py` | 从用户 YAML 解析启动参数，将同一文件交给 UCAgent 加载；导出随包配置模板 |
| `checkers.py` | 阶段验收入口，调用 `validation.py` |
| `runtime.py` | 调度证据生成、元数据同步和检查 |
| `evidence.py` | 源码状态、RTL、端口、相关模块源码及工具凭据 |
| `generic_evidence.py` | 捕获通用 Verilog/SystemVerilog 输入、端口和源文件哈希 |
| `verilog.py` | 显式输入配置、有限预处理及原始行号映射；不声称完成 HDL 编译 |
| `sv_frontend.py` | 通过 pyslang 解析/展开端口类型，从语法树提取受限赋值、条件与事件并比较 HDL token |
| `review.py` | 逐行为复核契约、当前工件验收记录和失效检查 |
| `documents.py` | Markdown 解析、Mermaid 围栏、模板结构和事实元数据 |
| `contracts.py` | 规范字段、跨表追溯、源位置与签核声明的确定性检查 |
| `validation.py` | 组合产物检查并返回诊断 |
| `repository.py` | 仓库文档链接、模板资源及打包声明检查 |

## 修改约定

- UCAgent 兼容下限使用已验证的 `26.9.2.dev14`，在发行包依赖与 `requires_ucagent` 中同步维护；降低下限前验证对应版本，不能照抄开发文档的示例值。
- 格式或行为变化时，同步工作流、Guide_Doc、模板、Checker 和相关测试；阶段所需规范文件列入 `reference_files`。修改资源后用新工作区验证。
- 写作规则统一维护在[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md)和[文档模板](../src/rtl2spec/Guide_Doc/chip_design_document_template_zh.md)。模板版本独立于插件版本，使用 SemVer。
- `tests/fixtures/design_document.md` 是合成 RTL 的独立完整样例。模板结构变化时同步审阅样例；测试样例随 sdist 发布；运行指南中的完整教学例与其保持结构一致。
- 提交维护源码、文档和测试；输入、产物和工具缓存放在独立工作区，不修改 XiangShan 源码来迁就工具。

## 开发与验证

从 UCAgent 仓库根目录执行，使核心和插件都使用当前源码：

```bash
python -m pip install -e .
cd plugins/RTL2Spec
python -m pip install -e '.[dev]'
make repo-lint
make plugin-check
make test
make template-check
git diff --check
```

`make` 显式从插件目录的 `src` 加载代码。测试使用临时源码夹具，无需下载 XiangShan；`template-check` 只解析模板的 Markdown 和 Mermaid 围栏，不需要 Node.js、浏览器或网络。影响生成行为时，还需选一个真实模块在干净工作区验证。端口展开与赋值事实测试调用真实 pyslang，不用正则或模拟解析器代替。

按改动风险选择测试，提交前运行完整插件测试：

| 关注点 | 测试文件与主要边界 |
| --- | --- |
| 端口、编译输入与事实提取 | `test_sv_frontend.py`、`test_compilation_inputs.py`：类型、参数、宏/include、非 ANSI 声明位置、条件/事件匹配及不支持的语法范围 |
| 文档和质量报告 | `test_document_contracts.py`、`test_document_structure.py`、`test_deterministic_contract.py`：完整样例、端口映射、表格追溯、唯一报告标题、空区块拒绝 |
| 复核与验收 | `test_review_acceptance.py`、`test_incremental_review.py`：两种事实状态的引用关联、七类 checks、依赖失效、答案保留、并发修改及签名 |
| 阶段和工作区 | `test_runtime.py`、`test_generic_workflow.py`、`test_output_lifecycle.py`、`test_ucagent_plugin.py`：两套工作流、Skill 开关、独立输出、损坏 manifest/越界软链接的诊断及修复后重试 |
| 文件配置启动 | `test_launch.py`：两套模板、真实 CLI 和配置加载、相对路径、无覆盖导出、默认配置启动及非法输入拒绝 |

修改后端权限或升级 UCAgent/OpenCode 时，安装 OpenCode 并执行以下测试（已验证 OpenCode 1.18.26）：

```bash
RTL2SPEC_TEST_OPENCODE=1 python -m pytest -q tests/test_backend_permissions.py
```

该测试用本地服务提供预设工具调用，无需模型密钥；真实 OpenCode 会话验证 Shell、工作区外读写被拒绝，工作区内读写成功。默认测试跳过此项。

## 打包验证

在已安装 UCAgent 和开发依赖的临时 Python 环境中执行，`dist/` 只保留本次构建的 wheel：

```bash
python -m build
python -m pip install --force-reinstall --no-deps dist/*.whl
ucagent --validate-plugin rtl2spec
python -I -m pytest -q --import-mode=append -o pythonpath=''
```

默认构建先生成 sdist，再从 sdist 构建 wheel。wheel 包含代码、脚本、工作流、启动配置模板及 Guide_Doc，并注册 `rtl2spec` 命令；sdist 还包含清单、`docs/`、示例和测试。恢复源码开发时重新执行可编辑安装。

检查 wheel 中的 `sv_frontend.py`、`Guide_Doc/artifact-templates.json`、全部运行指南和两套工作流均存在，安装后可以加载。通过 `python -I` 运行测试可避免源码目录和 `PYTHONPATH` 遮蔽已安装的包；测试仍须使用 sdist 携带的完整 fixtures。构建和安装测试应在临时环境执行，不覆盖正在使用的 UCAgent 环境。

插件沿用 UCAgent 根目录的 [Apache-2.0 许可证](https://github.com/XS-MLVP/UCAgent/blob/main/LICENSE)；发行包包含构建时复制的许可证和版权声明。打包规则见 [UCAgent 插件开发文档](https://github.com/XS-MLVP/UCAgent/blob/main/docs/content/03_develop/09_plugins.md#发行包中的许可证)。

## 方法来源

Coverage 方法参考 Verification Academy《Coverage Cookbook》（2013-08-21 快照），适用原则见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md#写作与验收约束)。引入外部材料时记录来源与用途，并确认许可和再分发条件。

设计文档字段参考了 [XS-MLVP/spec_generator 的 chip-design-document 模板](https://github.com/XS-MLVP/spec_generator/blob/feat/chip-dv-spec-workflow/templates/chip-design-document/chip_design_document_template_zh.md)，仅吸收职责边界、事务模型、验证架构、形式化执行条件和场景字段；RTL2Spec 自有的 evidence、相关模块签名、Mermaid-only 输出和固定附录契约仍以本插件模板为准。
