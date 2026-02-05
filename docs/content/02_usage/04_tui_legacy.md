# 旧版 TUI（urwid）

> 本页描述的是使用 `--legacy-ui` 启动的旧版 urwid 界面。默认启动的是基于 Textual 的新版 TUI，请参考 [新版 TUI 文档](./04_tui.md)。

## 启用方式

```bash
ucagent <workspace> <dut_name> --legacy-ui
```

`--legacy-ui` 会隐含启用 TUI，并切换到基于 urwid 的旧版界面。

---

## 界面组成

旧版界面同样由以下四个区域组成：

- **Mission 面板（左侧）**：阶段列表、Changed Files、Tools Call、Daemon Commands。
- **Status 面板（右上）**：API 与代理状态摘要。高度可通过 Shift+Up / Shift+Down 调节（最小 3，最大 100）。
- **Messages 面板（右上中）**：实时消息流，支持手动滚动浏览历史。
- **Console（底部）**：Output 输出区（支持分页）+ Input 输入行。

---

## 操作与快捷键

**全局操作**

- Enter：执行当前输入命令；若输入为空会重复上一次命令；输入 q/Q/exit/quit 退出 TUI。
- Esc：
  - 若正在手动浏览 Messages，退出滚动并返回末尾；
  - 若 Output 正在分页查看，退出分页；
  - 否则聚焦到底部输入框。
- Tab：命令补全。

**面板大小调整**

- Ctrl+Up / Ctrl+Down：增大/缩小底部 Console 输出区域高度（最小 3 行）。
- Ctrl+Left / Ctrl+Right：缩小/增大左侧 Mission 面板宽度（最小 10，最大 200）。
- Shift+Up / Shift+Down：缩小/增大右侧 Status 面板高度（最小 3，最大 100）。

**Console 操作**

- Up / Down：
  - 若 Output 在分页模式，用于翻页；
  - 否则用于命令历史导航。
- Alt+Right（Meta+Right）：进入 Console Output 分页模式并向后翻页。
- Alt+Left（Meta+Left）：在分页模式中向前翻页。
- Shift+Right：清空 Console Output。
- Shift+Left：清空输入行。

**Messages 面板操作**

- Alt+Up（Meta+Up）：在 Messages 中向上滚动（浏览历史）。
- Alt+Down（Meta+Down）：在 Messages 中向下滚动。

---

## 与新版 TUI 的主要区别

| 功能 | 旧版（urwid） | 新版（Textual） |
| :--- | :--- | :--- |
| Messages 滚动 | Alt+Up / Alt+Down | Up / Down（面板获焦时） |
| Console 分页 | Alt+Left / Alt+Right | PageUp / PageDown |
| Status 面板高度调节 | Shift+Up / Shift+Down | 不支持（Status 自动布局） |
| Vim 风格快捷键 | 不支持 | Ctrl+H/J/K/L |
| 主题选择 | 不支持 | Ctrl+T |
| 帮助面板 | 不支持 | Ctrl+/ 或 F1 |
| 取消运行命令 | Ctrl+C | Ctrl+C |
