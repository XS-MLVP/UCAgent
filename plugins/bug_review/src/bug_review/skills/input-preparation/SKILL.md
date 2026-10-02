---
name: input-preparation
description: 按需补齐 Bug Review 标准输入的测试、原报告、Spec、RTL、根目录 filelist 与启动清单；不负责运行复核。
---

# Bug Review 输入准备

先读插件根目录 `INPUTS.md`，检查目标 `workspace_<dut>/`。输入已经有可用的 `launch.yaml`、`filelist.txt`、`unity_test/tests/`、至少一份原 Bug 报告及所需 Spec 时直接启动；不运行本 Skill。原 Bug 报告仅作为待核查声明，缺失时阅读原材料后补写，不猜测 Bug、测试结果或波形。

## 选择输入

阅读源测试、RTL 例化关系和规格，明确顶层 RTL 及所有依赖。先创建可填写清单：

```bash
.venv/bin/python plugins/bug_review/src/bug_review/skills/input-preparation/scripts/prepare_inputs.py init \
  --source-workspace /absolute/path/workspace_<dut> \
  --rtl-root /absolute/path/rtl \
  --dut <dut> --manifest /absolute/path/input_manifest.json
```

填写 `rtl_top`、`rtl_files`、`spec_files` 和 `copy_runtime_package`；RTL 顶层模块名不同于 DUT 包名时填写 `module`。`rtl_files` 只列已确认的 RTL 源文件，不通过名称猜依赖。新建输入目录时执行：

```bash
.venv/bin/python plugins/bug_review/src/bug_review/skills/input-preparation/scripts/prepare_inputs.py apply \
  --manifest /absolute/path/input_manifest.json --inputs-root plugins/bug_review/inputs
```

已有 `workspace_<dut>/` 只缺启动材料时执行：

```bash
.venv/bin/python plugins/bug_review/src/bug_review/skills/input-preparation/scripts/prepare_inputs.py complete \
  --manifest /absolute/path/input_manifest.json --workspace /absolute/path/workspace_<dut>
```

脚本创建根目录 `filelist.txt`、`launch.yaml`，RTL 放在 `rtl/`；已有同名材料不会被覆盖。检查 filelist 的每条路径在目标节点可访问，检查 `dut`、`module` 与工作区身份一致。Spec 可保留在模块根目录或 `<dut>/README.md`。原测试及其 fixture、模型和相对数据须完整，旧 `toffee_tmp_*` 与测试报告不进入新的 run。

## 可选 DUT 包

若已有 `<dut>/`，用本次工作流的 Python 确认能导入。缺少或不兼容时，启动准备会根据 filelist 编译；需要事先排障时可调用 `picker-check` 和 `picker-package`：

```bash
.venv/bin/python plugins/bug_review/src/bug_review/skills/input-preparation/scripts/prepare_inputs.py picker-check --picker /absolute/path/picker
.venv/bin/python plugins/bug_review/src/bug_review/skills/input-preparation/scripts/prepare_inputs.py picker-package --picker /absolute/path/picker --workspace /absolute/path/workspace_<dut>
```

大型 Verilator 生成源在 Apple clang 下若 `-O3` 编译异常缓慢，可给 `picker-package` 加 `--cxx-opt O1`。包和 xspcomm 必须匹配运行 Python；先通过导入与单步冒烟，再启动 Bug Review。本 Skill 仅补齐输入，不执行测试、波形或裁决。
