
# RTL2Spec 开发与验证

安装和使用见 [README](../README.md)。通用贡献流程遵循 [UCAgent 贡献指南](https://github.com/XS-MLVP/UCAgent/blob/main/CONTRIBUTING.md)，插件接口与发布约定见 [UCAgent 插件开发文档](https://github.com/XS-MLVP/UCAgent/blob/main/docs/content/03_develop/09_plugins.md)。

## 项目结构

| 层级 | 当前名称 |
| --- | --- |
| 项目目录 | `RTL2Spec` |
| Python 发行包 | `ucagent-rtl2spec` |
| 插件 ID | `rtl2spec` |
| Python 导入包 | `rtl2spec` |
| 工作流 ID | `design-document` |

```text
UCAgent/plugins/RTL2Spec/
├── ucagent-plugin.toml          # 源码入口，python_path = "src"
├── pyproject.toml               # 依赖、安装入口和 wheel 资源
├── setup.py                     # 构建时复制根目录 LICENSE、NOTICE.md
├── MANIFEST.in                  # sdist 范围
├── Makefile                     # 维护命令
├── docs/                        # 开发步骤、工具参考与问题排查
├── src/rtl2spec/
│   ├── *.py                     # 插件实现，职责见下表
│   ├── scripts/                 # 环境准备与 RTL 编译脚本
│   ├── workflows/               # 工作流 YAML
│   └── Guide_Doc/               # 生成指南与唯一写作模板
└── tests/                       # 回归测试及 fixtures/
```

下表路径相对于 `src/rtl2spec/`：

| 模块 | 职责 |
| --- | --- |
| `__init__.py`、`plugin.py` | 插件版本、能力和依赖声明，启动前检查输出目录 |
| `tools.py` | 工具参数、工作区权限、子进程和超时管理 |
| `checkers.py` | 阶段验收入口，调用 `validation.py` |
| `runtime.py` | 调度证据生成、元数据同步和检查 |
| `evidence.py` | 源码状态、RTL、端口、相关模块源码及工具凭据 |
| `documents.py` | Markdown 解析、Mermaid 围栏、模板结构和事实元数据 |
| `validation.py` | 组合产物检查并返回诊断 |
| `repository.py` | 仓库文档链接、模板资源及打包声明检查 |

## 修改约定

- UCAgent 兼容下限使用已验证的 `26.9.2.dev14`，在发行包依赖与 `requires_ucagent` 中同步维护；降低下限前验证对应版本，不能照抄开发文档的示例值。
- 格式或行为变化时，同步工作流、Guide_Doc、模板、Checker 和相关测试；阶段所需规范文件列入 `reference_files`。修改资源后用新工作区验证。
- 写作规则统一维护在[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md)和[文档模板](../src/rtl2spec/Guide_Doc/chip_design_document_template_zh.md)。模板版本独立于插件版本，使用 SemVer。
- `tests/fixtures/design_document.md` 是合成 RTL 的独立完整样例。模板结构变化时同步审阅样例；样例随 sdist 发布，不进入 wheel 或用户工作区。
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

`make` 显式从插件目录的 `src` 加载代码。测试使用临时源码夹具，无需下载 XiangShan；`template-check` 只解析模板的 Markdown 和 Mermaid 围栏，不需要 Node.js、浏览器或网络。影响生成行为时，还需选一个真实模块在干净工作区验证。

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

默认构建先生成 sdist，再从 sdist 构建 wheel。wheel 包含代码、脚本、工作流及 Guide_Doc；sdist 还包含清单、`docs/` 和测试。恢复源码开发时重新执行可编辑安装。

插件沿用 UCAgent 根目录的 [Apache-2.0 许可证](https://github.com/XS-MLVP/UCAgent/blob/main/LICENSE)；发行包包含构建时复制的许可证和版权声明。打包规则见 [UCAgent 插件开发文档](https://github.com/XS-MLVP/UCAgent/blob/main/docs/content/03_develop/09_plugins.md#发行包中的许可证)。

## 方法来源

Coverage 方法参考 Verification Academy《Coverage Cookbook》（2013-08-21 快照），适用原则见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md#coverage-practice-principles)。引入外部材料时记录来源与用途，并确认许可和再分发条件。

设计文档字段参考了 [XS-MLVP/spec_generator 的 chip-design-document 模板](https://github.com/XS-MLVP/spec_generator/blob/feat/chip-dv-spec-workflow/templates/chip-design-document/chip_design_document_template_zh.md)，仅吸收职责边界、事务模型、验证架构、形式化执行条件和场景字段；RTL2Spec 自有的 evidence、相关模块签名、Mermaid-only 输出和固定附录契约仍以本插件模板为准。
