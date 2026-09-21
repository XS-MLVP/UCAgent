
# 插件维护指南

安装和使用见 [README](README.md)。插件开发遵循 UCAgent 的 [09_plugins.md](https://github.com/XS-MLVP/UCAgent/blob/main/docs/content/03_develop/09_plugins.md)，变更和问题统一提交到 UCAgent 仓库。

## 项目结构

| 层级 | 当前名称 |
| --- | --- |
| 项目目录 | `RTL2Spec` |
| Python 发行包 | `ucagent-rtl2spec` |
| 插件 ID | `rtl2spec` |
| Python 导入包 | `rtl2spec` |
| 工作流 ID | `design-document` |

清单、entry point 和 `Plugin.name` 使用同一插件 ID。目录名和 Python 包名各按自身用途命名，无需与插件 ID 字面相同。

```text
UCAgent/plugins/RTL2Spec/
├── ucagent-plugin.toml          # 源码入口，python_path = "src"
├── pyproject.toml               # 依赖、安装入口和 wheel 资源
├── MANIFEST.in                  # sdist 范围
├── Makefile                     # 维护命令
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
| `__init__.py`、`plugin.py` | 版本、插件能力和依赖声明 |
| `tools.py` | 工具参数、工作区权限、子进程和超时管理 |
| `checkers.py` | 阶段验收入口，调用 `validation.py` |
| `runtime.py` | 调度证据生成、元数据同步、渲染和检查 |
| `evidence.py` | 源码状态、RTL、端口及工具凭据 |
| `documents.py` | Markdown 解析、模板结构和事实元数据 |
| `validation.py` | 组合产物检查并返回诊断 |
| `rendering.py` | Mermaid 渲染与图形清单 |
| `repository.py` | 仓库文档链接、模板资源及打包声明检查 |

## 修改约定

- 身份保持一致：清单、entry point 和 `Plugin.name` 使用同一 ID；发行包与插件版本一致。Python 依赖同步到 `pyproject.toml` 和插件声明。
- UCAgent 兼容下限使用已验证的 `26.9.2.dev14`，在发行包依赖与 `requires_ucagent` 中同步维护；降低下限前验证对应版本，不能照抄开发文档的示例值。
- 格式或行为变化时，同步工作流、Guide_Doc、模板、Checker 和相关测试；阶段所需规范文件列入 `reference_files`。修改资源后用新工作区验证。
- 写作规则统一维护在[生成指南](src/rtl2spec/Guide_Doc/generation-guide.md)和[文档模板](src/rtl2spec/Guide_Doc/chip_design_document_template_zh.md)。模板版本独立于插件版本，使用 SemVer。
- `tests/fixtures/design_document.md` 是合成 RTL 的独立完整样例。模板结构变化时同步审阅样例；样例随 sdist 发布，不进入 wheel 或用户工作区。
- 提交维护源码、文档和测试；输入、产物和工具缓存放在独立工作区，不修改 XiangShan 源码来迁就工具。
- 日常变更限于本插件目录，包括依赖、测试和打包命令。通用贡献流程和漏洞报告渠道使用 UCAgent 的约定；插件专用的 `.gitignore`、`.editorconfig`、`.gitattributes` 和安全边界说明在本目录维护。

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

`make` 显式从插件目录的 `src` 加载代码。测试使用临时源码夹具，无需下载 XiangShan；`template-check` 实际渲染模板图，首次可能下载工具。影响生成行为时，还需选一个真实模块和新版本验证。

本插件不设专用 CI；提交前由维护者执行上述本地检查，发布前执行下述打包验证。验证命令维护在本目录，无需修改 UCAgent 根目录 workflow。

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

默认构建先生成 sdist，再从 sdist 构建 wheel。wheel 包含代码、脚本、工作流及 Guide_Doc；sdist 还包含清单、维护文档和测试。恢复源码开发时重新执行可编辑安装。

## 方法来源

Coverage 方法参考 Verification Academy《Coverage Cookbook》（2013-08-21 快照），适用原则见[生成指南](src/rtl2spec/Guide_Doc/generation-guide.md#coverage-practice-principles)。引入外部材料时记录来源和用途，遵守许可与再分发条件；保密要求见 [SECURITY.md](SECURITY.md)。
