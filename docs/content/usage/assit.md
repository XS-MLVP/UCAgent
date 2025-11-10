# 人机协同验证

UCAgent 支持在验证过程中进行人机协同，允许用户暂停 AI 执行，人工干预验证过程，然后继续 AI 执行。这种模式适用于需要精细控制或复杂决策的场景。

**协同流程：**

1. 暂停 AI 执行：

   - 在直接接入 LLM 模式下：按 `Ctrl+C` 暂停。
   - 在 Code Agent 协同模式下：根据 Agent 的暂停方式（如 Gemini-cli 使用 `Esc`）暂停。

2. 人工干预：

   - 手动编辑文件、测试用例或配置。
   - 使用交互命令进行调试或调整。

3. 阶段控制：

   - 使用 `tool_invoke Check` 检查当前阶段状态。
   - 使用 `tool_invoke Complete` 标记阶段完成并进入下一阶段。

4. 继续执行：

   - 使用 `loop [prompt]` 命令继续 AI 执行，并可提供额外的提示信息。
   - 在 Code Agent 模式下，通过 Agent 的控制台输入提示。

5. 权限管理：
   - 可使用 `add_un_write_path`，`del_un_write_path` 等命令设置文件写权限，控制 AI 是否可以编辑特定文件。
   - 适用于直接接入 LLM 或强制使用 UCAgent 文件工具。
