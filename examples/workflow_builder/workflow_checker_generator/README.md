# Workflow Checker Generator

## 作用

该组件从 Checker spec 生成 UCAgent `Checker` 子类和测试 fixture，也可在独立维护场景更新 config 注册。WorkflowBuilder 初次构建时使用 `workflow_spec.checkers` 的中心定义调用本组件，直接交付全部业务 Checker。

## 内联源码

spec 可包含完整受信任 Python `source`。生成器会执行 AST 校验：入口类名必须匹配
`entry.class_name` 并继承 `Checker`，`entry.method` 必须存在且有方法级 docstring。
内联源码模式必须提供非空 `fixtures`，路径位于
`.workflow/checker_tests/cases/<CheckerName>/`，并在 `tests` 中至少声明一个 PASS
与一个 FAIL。生成器原样写入源码并物化 fixture，不再受下面四类声明式规则限制。

## 支持的规则

以下规则继续用于兼容独立的声明式 Checker spec：

- `json_required_keys`：JSON 包含必需字段。
- `json_numeric_range`：JSON 数值字段位于闭区间。
- `file_exists`：工作流相对路径文件存在。
- `command_exit_code`：allowlist 命令返回预期退出码。

## 自动测试

设置：

```yaml
auto_tests: true
```

生成器会在 `.workflow/checker_tests/cases/<checker_name>/` 创建正反 fixture，并把测试项写回 spec。这样 Layer 2 可以验证 checker，而不把测试责任交给未来运行工作流的 Layer 3。

## CLI

```bash
python -m workflow_checker_generator.cli <workflow_root> \
  --from-spec .workflow/checker_specs/my_checker.yaml \
  --overwrite
```

## UCAgent 工具

```yaml
- examples.workflow_builder.workflow_checker_generator.uc_tools.WorkflowCheckerGenerator
```

## 验证闭环

```bash
make check_checker_specs
make check_checkers
make test_checkers
make check
make smoke
```

前三项验证 spec、代码和正反行为；`make smoke` 启动真实子 UCAgent，确认 checker 在阶段完成时实际触发。
