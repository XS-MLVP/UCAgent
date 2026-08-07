# Workflow Tool Generator

## 作用

该组件从结构化 tool spec 生成普通 Python 工具，并将工具记录注册到工作流 `config.yaml`。工具采用统一返回结构，便于直接测试和 MCP adapter 包装。

## 两种模式

- `base`：生成内置基础工具，如读取文件、写文件和受限命令执行。
- `from_spec`：根据 `.workflow/tool_specs/*.yaml` 生成业务工具。

## Tool Spec

spec 声明工具名称、入口文件、类名、方法、输入、输出以及测试。输出必须包含：

```text
ok, data, errors, warnings, meta
```

先写 spec 再生成实现，可以让 Layer 2 用确定性检查器验证结构和行为，而不是只相信 LLM 生成结果。

## CLI

```bash
python -m workflow_tool_generator.cli <workflow_root> --tool run_command_tool
python -m workflow_tool_generator.cli <workflow_root> \
  --from-spec .workflow/tool_specs/my_tool.yaml \
  --existing-policy create_only
```

`create_only` 是默认策略，保留全部已有源码。`refresh_scaffold` 仅更新生成状态中摘要
匹配的未修改骨架；`force_replace` 会显式覆盖已有文件，只能在确认无需保留人工实现时
使用。旧 `--overwrite` 暂时兼容为 `force_replace`，并会产生弃用警告。

生成状态保存在 `.workflow/tool_generation_state.yaml`。它同时冻结已经登记的测试用例；
后续允许追加新测试，但删除或改写既有测试会被拒绝。

## UCAgent 工具

```yaml
- examples.workflow_builder.workflow_tool_generator.uc_tools.WorkflowToolGenerator
```

## 验证闭环

```bash
make check_tool_specs
make check_tools
make test_tools
make test_mcp
make check
```

`test_tools` 直接调用 Python 类；`test_mcp` 启动子 UCAgent 并通过 MCP 调用工具。两者都必须通过。
