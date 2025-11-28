# TUI

## TUI（界面与操作）

UCAgent 自带基于 urwid 的终端界面（TUI），用于在本地交互式观察任务进度、消息流与控制台输出，并直接输入命令（如进入/退出循环、切换模式、执行调试命令等）。

### 界面组成

如“图 6：tui 界面组成所示例”

![tui界面组成](./tui-part.png)

- Mission 面板（左侧）

  - 阶段列表：显示当前任务的阶段（索引、标题、失败数、耗时）。颜色含义：
    - 绿色：已完成阶段
    - 红色：当前进行阶段
    - 黄色：被跳过的阶段（显示“skipped”）
  - Changed Files：近期修改文件（含修改时间与相对时间，如“3m ago”）。较新的文件以绿色显示。
  - Tools Call：工具调用状态与计数。忙碌中的工具会以黄色高亮（如 SqThink(2)）。
  - Deamon Commands：后台运行的 demo 命令列表（带开始时间与已运行时长）。

- Status 面板（右上）

  - 显示 API 与代理状态摘要，以及当前面板尺寸参数（便于调节布局时参考）。

- Messages 面板（右上中）

  - 实时消息流（模型回复、工具输出、系统提示）。
  - 支持焦点与滚动控制，标题会显示“当前/总计”的消息定位。例如：Messages (123/456)。

- Console（底部）
  - Output：命令与系统输出区域，支持分页浏览。
  - Input：命令输入行（默认提示符 “(UnityChip) ”）。提供历史、补全、忙碌提示等。

提示：界面每秒自动刷新一次（不影响输入）。当消息或输出过长时，会进入分页或手动滚动模式。

### 操作与快捷键

- Enter：执行当前输入命令；若输入为空会重复上一次命令；输入 q/Q/exit/quit 退出 TUI。
- Esc：
  - 若正在浏览 Messages 的历史，退出滚动并返回末尾；
  - 若 Output 正在分页查看，退出分页；
  - 否则聚焦到底部输入框。
- Tab：命令补全；再次按 Tab 可分批显示更多可选项。
- Shift+Right：清空 Console Output。
- Shift+Up / Shift+Down：在 Messages 中向上/向下移动焦点（浏览历史）。
- Ctrl+Up / Ctrl+Down：增/减 Console 输出区域高度。
- Ctrl+Left / Ctrl+Right：减/增 Mission 面板宽度。
- Shift+Up / Shift+Down（另一路径）：调整 Status 面板高度（最小 3，最大 100）。
- Up / Down：
  - 若 Output 在分页模式，Up/Down 用于翻页；
  - 否则用于命令历史导航（将历史命令放入输入行，可编辑后回车执行）。

分页模式提示：当 Output 进入分页浏览时，底部标题会提示 “Up/Down: scroll, Esc: exit”，Esc 退出分页并返回输入状态。

### 命令与用法

- 普通命令：直接输入并回车，例如 loop、tui、help 等（由内部调试器处理）。
- 历史命令：在输入行为空时按 Enter，将重复执行上一条命令。
- 清屏：输入 clear 并回车，仅清空 Output（不影响消息记录）。
- 演示/后台命令：命令末尾添加 & 将在后台运行，完成后会在 Output 区域提示结束；当前后台命令可通过 list_demo_cmds 查看。
- 直接执行系统/危险命令：以 ! 前缀执行（例如 !loop），该模式执行后优先滚动到最新输出。
- 列出后台命令：list_demo_cmds 显示正在运行的 demo 命令列表与开始时间。

#### 消息配置（message_config）

- 作用：在运行中查看/调整消息裁剪策略，控制历史保留与 LLM 输入 token 上限。
- 命令：
  - message_config 查看当前配置
  - message_config <key> <value> 设置配置项
- 可配置项：
  - max_keep_msgs：保留的历史消息条数（影响会话记忆窗口）
  - max_token：进入模型前的消息裁剪 token 上限（影响开销/截断）
- 示例：
  - message_config
  - message_config max_keep_msgs 8
  - message_config max_token 4096

其他说明

- 自动补全：支持命令名与部分参数的补全；候选项过多时分批显示，可多次按 Tab 查看剩余项。
- 忙碌提示：命令执行期间，输入框标题会轮转显示 (wait.), (wait..), (wait...)，表示正在处理。
- 消息焦点：当未手动滚动时，消息焦点自动跟随最新消息；进入手动滚动后，会保持当前位置，直至按 Esc 或滚动至末尾。
- 错误容错：若某些 UI 操作异常（如终端不支持某些控制序列），TUI 会尽量回退到安全状态继续运行。
