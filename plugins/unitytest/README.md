# UnityTest

`UnityTest` 是面向 UCAgent 的可安装插件，提供 UCAgent 默认的芯片验证工作流：DUT 文档生成与精炼、测试模板与用例实现（含 must-pass / free / mock / 批量实现）、行覆盖映射、静态与动态 Bug 分析、波形证据链等。工作流资产（`workflows/unitytest.yaml`、`templates/unity_test`、`skills/`、`Guide_Doc/`）随包分发。

Python 发行包名为 `ucagent-unitytest`，插件 ID 为 `unitytest`，要求 Python 3.11 及以上。

## 构建与安装

从源码构建并安装：

```bash
cd plugins/unitytest
python3 -m pip install build
python3 -m build .
python3 -m pip install dist/ucagent_unitytest-0.1.0-py3-none-any.whl
ucagent --validate-plugin unitytest
```

源码树内无需安装：默认启动会通过 `ucagent/lang/zh/config/default.yaml` 的 `workflow` 指针自动激活本插件。

## 选用方式

```bash
# 默认启动（源码树：指针指向 plugins/unitytest/...，自动激活）
ucagent <dut> <output>

# 显式选择（源码树或安装后均可）
ucagent <dut> <output> --plugin plugins/unitytest --plugin-workflow unitytest:unitytest
ucagent <dut> <output> --plugin unitytest --plugin-workflow unitytest:unitytest
```

pip 安装（无源码树）时，把 `~/.ucagent/setting.yaml`（或 lang 层 `default.yaml`）中的 `workflow` 指针改为包内相对形式：

```yaml
workflow: "unitytest_plugin:workflows/unitytest.yaml"
```

框架按 `<可导入模块>:<包内相对路径>` 解析该指针，并在已安装的 `ucagent.plugins` 入口点中定位归属插件。
