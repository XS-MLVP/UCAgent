
# ACT4 scope 批量诊断修改与计时

日期：2026-11-10。分支：`fix/act4-scope-validation-diagnostics`。
分支基于本地 main 的 `5bf52fdc960ffdde5b24c569572c6a8f7cc4b248`，仅包含 ACT4 修改，不继承 TUI PR #160 的补丁。
计时对照版本为 `69a86490a1652767f38fef15f70ffd5e7db6b8a0`；基准脚本仅提取其中的 `_scope()`，该函数与上述 main 基点相同，不依赖 TUI 修改。

## 修改范围

`ACT4ReviewChecker._scope()` 保留原有审查规则，按字段收集独立错误，返回 `field/error/next_action`。
同一 job 的命令、超时、路径等独立问题可以一起反馈；父字段结构不合法时跳过依赖它的检查。
跨 job 的矩阵及依赖检查等待 job 字段有效后执行，因此修复父字段后仍可能出现新诊断。

最多展示 20 条错误，同时返回总数及省略数。任何 scope 错误均在基线冻结和原生命令执行前阻断。
无法解析的 YAML 或无效顶层 schema 仍先返回文档读取诊断。
运行指南和 inventory 提示同步说明批量修复方式；没有添加工具安装、环境探测或资产语义分类规则。

## 测量方法

使用 Python 3.11，前后版本共享同一解释器及依赖。初始化、模块导入及 fixture Git 仓库建立均在计时之外。
每项运行 30 次，交替新旧版本的顺序，报告中位数和范围。
基准脚本通过一次 `git show` 提取旧版本的 `_scope()`，其余未修改的辅助函数共享当前实现。

合成 scope 含六个 CI jobs，并注入六处独立错误：suite、缺失资产、references、discovery、generation 超时、build 工作目录。
确定性修复器只修复当前诊断指出的字段，直到校验成功；计时包含校验和每轮修复后的 YAML 重写。
该修复器用于固定实验条件，不代表真实模型每轮一定只修复同样数量的问题。

## 测量结果

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 六处错误修正过程总校验次数，含最终成功 | 7 | 2 |
| 失败反馈轮数 | 6 | 1 |
| 修正过程耗时中位数 | 33.118 ms | 10.176 ms |
| 修正过程耗时范围 | 32.690–33.906 ms | 9.889–10.694 ms |
| 合成合法 scope 单次校验中位数 | 4.095 ms | 4.216 ms |
| 合成合法 scope 单次校验范围 | 3.993–6.292 ms | 4.160–4.530 ms |

本地合成修正过程耗时减少 **69.27%**，失败反馈轮数减少 **83.33%**。合法输入的单次校验增加约 0.121 ms。

另对原 Zihintpause 运行中的真实合法 scope 做只读校验，各测 30 次：

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 单次校验中位数 | 31.061 ms | 31.706 ms |
| 单次校验范围 | 30.646–80.669 ms | 31.326–32.595 ms |

真实 scope 的中位数增加约 **0.645 ms（2.08%）**，原文件 SHA-256 前后相同：
`c61dac1198db7e19826e91da672729ed28a3e3e99e1de5945cd5a2adf0c3d04b`。

这些结果证明减少错误反馈轮次，未证明模型参与的 inventory 或完整 workflow 加速 69%。
历史 inventory 的 15 分 50.732 秒包含读取、环境准备和模型操作，不能据此计算节省分钟数。
本轮没有调用模型、重跑原生 ACT4 矩阵或改变原运行状态。

## 复现

在仓库根目录，使用安装了核心和插件测试依赖的 Python：

```bash
PYTHONPATH=plugins/ACT4/src:. python plugins/ACT4/tests/benchmark_scope_validation.py \
  --base-ref 69a86490a1652767f38fef15f70ffd5e7db6b8a0 \
  --repeats 30 \
  --output /tmp/act4-scope-benchmark.json
```

本轮解释器：`/tmp/ucagent-tui-pr-sv8hkm6s/venv/bin/python`。
原始样本和只读真实 scope 计时脚本位于 `/tmp/ucagent-scope-bench-KO0KFw/`：

- `result.json`：合成修正过程及合法输入样本，包含前后源码 SHA-256。
- `existing-scope-result.json`：真实 scope 的全部样本及文件 SHA-256。
- `measure_existing_scope.py`：只读真实 scope 的计时脚本。
- `act4_review_checker.before.py`：修改前源码副本。
- `check_equivalence.py`、`equivalence-result.json`：新旧版本通过/拒绝结果的差分检查及统计。

真实 scope 路径为：

```text
/home/ankohuu/Project/UCAgent/act4-run-01/runs/20261109T100239Z-4c0cdb94/workspace/act4_review/Zihintpause/review/scope.yaml
```

## 回归验证

执行 `test_act4_review_checker.py`、`test_documentation_contracts.py`、`test_plugin.py`，共 **261 项通过**。
新增用例覆盖跨字段和同 job 多错误、非法父字段、非法 job 字段、安全路径、诊断数量限制、修复后继续校验及错误输入不得冻结基线。
工作流 YAML 在默认和自定义 `ACT4_MANUAL_ROOT` 下解析通过，指南 Markdown 标题间距检查通过。

另对同一合成 scope 的根字段、资产类别、job 和 artifact 字段执行类型/值变异及字段删除，共比较 **2490 个输入**。
其中 227 个输入两版均通过，2263 个两版均拒绝，通过时返回内容一致，未发现通过/拒绝结果差异。
这覆盖单字段变异和删除，不是对所有输入的形式化等价证明；失败时的诊断结构、数量和检查顺序有意改变。

涉及模型的收益仍需在相同模型、服务、reasoning effort、输入提交和缓存条件下单独测量。
