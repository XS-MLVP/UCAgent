

## 自定义 Checker 示例

UCAgent 内置了常用的 Checker，但在真实项目中往往需要额外的业务规则。本示例演示如何编写自定义 Python Checker、将其注入到 UCAgent，并通过 MCP 流程完成验证。

示例目录结构：

- `my_checker.py`：示例 Checker 实现，定义了 `MyChecker` 类。
- `joke.yaml`：示例 DUT 配置，展示如何在 `config.yaml` 中引用自定义 Checker。
- `Makefile`：封装运行命令，简化示例操作。
- `joke.md`：待检测的文本样例。

运行时常用参数：

```bash
    --append-py-path APPEND_PY_PATH, -app APPEND_PY_PATH
                                                Append additional Python paths or files for
                                                module loading (can be used multiple times)
```

通过 `--append-py-path`（简写 `-app`）可以把指定目录或文件加入到 UCAgent 的 `PYTHONPATH`，从而让 `config.yaml` 中的 Checker 配置找到自定义实现。


### Checker 要求

- 需要继承 `ucagent.checkers.base.Checker`
- `__init__`函数用来接收yaml配置文件中传递的参数
- 需要实现函数 `do_check(self, timeout=0, **kwargs) -> tuple[bool, object]`
- 需要给 `do_check` 函数添加 docstring 说明其功能。
- `do_check`的返回格式为：`is_check_pass: bool, message: tuple[str, dict]`
    - `is_check_pass`：为 True 表示检测通过，为 False 表示检测失败
    - `message`：记录通过或失败的原因，可附带上下文信息


#### 示例

定义一个判断文件中是否有Jimmy字符串的检查器：

```python
#coding=utf-8

from ucagent.checkers.base import Checker

class MyChecker(Checker):

    def __init__(self, joke_file, word_count_min, word_count_max, **kwargs):
        self.joke_file = joke_file
        self.word_count_min = word_count_min
        self.word_count_max = word_count_max
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """A simple checker that alternates between success and failure."""
        joke_path = self.get_path(self.joke_file)
        try:
            with open(joke_path, 'r', encoding='utf-8') as f:
                joke = f.read().strip()
            if "jimmy" not in joke.lower():
                return False, {"error": "No Jimmy find in your joke."}
            if len(joke) < self.word_count_min:
                return False, {"error": f"Joke is too short. Min word count is {self.word_count_min}."}
            if len(joke) > self.word_count_max:
                return False, {"error": f"Joke is too long. Max word count is {self.word_count_max}."}
            return True, {"joke": joke}
        except Exception as e:
            return False, {"error": str(e)}
```

### 使用步骤

1. 根据需求调整 `my_checker.py` 中的逻辑（示例会检查 `joke.md` 是否包含 “Jimmy” 并限制字数范围）。
2. 在 `joke.yaml` 中配置 Checker 名称及其参数，例如目标文件、最小/最大字数及是否需要人工确认。
3. 运行示例 Makefile，它会自动把当前目录加入 `PYTHONPATH` 并启动 MCP 模式：

    ```bash
    make mcp_joke DUT="UFO"
    ```

4. 进入 TUI 后执行 `tool_invoke Check` 触发自定义 Checker。根据输出结果修改 `joke.md`，即可快速验证不同输入。

如需扩展，可在该目录下继续添加新的 Checker 文件，并在配置中引用它们，从而复用这一工作流。
