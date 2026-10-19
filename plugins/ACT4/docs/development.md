# ACT4 插件开发

插件实现位于 `src/act4_privileged_suite/`，不修改 UCAgent 核心的默认 workflow、
依赖或 checker 导出。`ucagent-plugin.toml` 支持源码加载，`pyproject.toml` 的
`ucagent.plugins` entry point 支持安装态发现；两者指向相同 provider。

## 资源和注册

- `plugin.py` 声明工作流、8 类 checker、依赖和 Guide_Doc。
- `workflows/privileged-suite-generation.yaml` 保留 ITGen 七阶段任务及其验收规则，
  使用插件 registry 的 checker 短名。
- `checkers/` 包含资产一致性、CTP/manual 来源、审查、switch、manifest 和最终报告校验。
- `Guide_Doc/` 包含运行指南、checker 说明和阶段填写模板，仅在选择本工作流后复制。
- 各阶段 `reference_files` 列出当前模板及所用 gate 的说明，保留原有 ACT4 原生输入。
- `tests/` 保留 ITGen 的 ACT4 checker 回归，并增加插件描述、阶段生命周期及配置测试。

这些文件迁移自 ITGen 的 `itgen/lang/zh/config/act4_priv_suite_generate.yaml`、
`itgen/checker/act4_*.py` 与相应指南及测试。原有 `work_itgen_<Suite>` 构建目录名继续使用。
checker 使用包内导入，所有 Checker 构造函数调用核心基类初始化，不依赖
`sys.path` 注入、ITGen checkout 或顶层模块别名。
工作流仍为 7 个阶段、25 个 gate，完整保留原有参数和验收语义。插件特有适配为
checker 短名注册、manual 路径配置和静态规范引用；生成器独立性校验另外拒绝
`act4_privileged_suite` 私有导入/路径及 `ACT4_MANUAL_ROOT`，允许 ACT4 原生输入。
UCAgent 版本下限采用实际测试的 `26.9.2.dev25`。

manual 路径由工作流的 `template_overwrite.ACT4_MANUAL_ROOT` 提供，加载 YAML 时解析
`ACT4_MANUAL_ROOT` 环境变量，再由 UCAgent 模板系统统一渲染进提示和 checker 参数。
工作流的 context factory 在初始化前验证 manual 与可写目录无重叠，不修改最终配置。
新增配置应继续走 UCAgent 的最终配置，不在 checker 中重复读取环境变量。

## 验证与打包

在插件目录执行：

```bash
python3 -m pip install -e '.[dev]'
make validate
make test
make package
```

也可在 UCAgent 根目录直接加载源码：

```bash
python3 ucagent.py --validate-plugin ./plugins/ACT4
PYTHONPATH=plugins/ACT4/src python3 -m pytest -q plugins/ACT4/tests
```

`make test` 使用临时工作区和合成资产，检查成功与失败边界，不联网生成真实 suite。
阶段启动测试使用 UCAgent blank backend，验证 Skill 开启/关闭时均能装配完整工作流，
并验证 manual 路径覆盖、Guide_Doc 复制与目录策略。
插件契约测试还覆盖配置搜索路径、全部 checker 的名称冲突、依赖缺失、命令版本探测
失败和工作流专属依赖的按需激活。原有测试分别覆盖 CTP/manual 来源、资产集合与语义、
generator API/拆分/独立性、VM scope、testcase 可达性、ELF/签名、审查、switch、manifest
和最终报告；测试不等价于真实套件的编译、参考模型执行或 coverage 命中。
正式 ACT4 生成和模拟执行需按 README 准备真实依赖并另行运行。

`setup.py` 构建时临时带入根目录 LICENSE/NOTICE，构建结束后清理副本；
sdist 带入它们以支持脱离仓库重建 wheel。发布前检查 wheel 的 entry point、所有
checker 模块、workflow、Guide_Doc 和 `.dist-info/licenses/`，并在仓库外测试安装态加载。
无需为本插件增加核心依赖或仓库根目录 CI。
