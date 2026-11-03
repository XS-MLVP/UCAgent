
# Custom Development

When customizing a workflow, first define tasks and acceptance criteria, then add tools, guidance documents, and templates as needed. It is recommended to run the [Mini Example](08_mini_example.md) first to understand how each component collaborates by comparing it with the actual files.

## Learning Path

1. Read [Getting Started with Custom Development](01_quick_start.md) to understand the components of a minimal workflow.
2. Run the [Mini Example](08_mini_example.md) to observe how the two stages generate and accept documents.
3. Adjust stages, inputs, and outputs according to the [Workflow Configuration](03_workflow.md).
4. When new capabilities are needed, write [Tools](05_customize.md) and [Checkers](07_checkers.md).
5. When independent installation and delivery of extensions are required, use [Plugins](09_plugins.md).

## Lookup by Problem

| Problem to Solve | Documentation |
| --- | --- |
| Understand component responsibilities and execution process | [Architecture and How It Works](02_architecture.md) |
| Configure stages, template variables, skip, and human review | [Workflow Configuration](03_workflow.md) |
| Write runtime guidance documents and initial files | [Template Files and Generated Artifacts](04_template.md) |
| Add computation, file, or external service capabilities | [Custom Tools](05_customize.md) |
| Find the purpose of built-in tools | [Tool List](06_tool_list.md) |
| Verify files, formats, business rules, and batch progress | [Custom Checker](07_checkers.md) |
| Run a complete example that does not depend on RTL | [Mini Example](08_mini_example.md) |
| Package and publish Tools, Checkers, Skills, or workflows | [Plugin Development and Publishing](09_plugins.md) |

When using UCAgent for the first time, complete [Installation](../01_start/00_installation.md) and [Getting Started with Normal Mode](../01_start/02_normal_mode.md) first. CLI parameters are documented in [Parameter Description](../02_usage/03_option.md).
