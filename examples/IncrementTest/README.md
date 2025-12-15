## 增量验证

大多数情况下，芯片验证任务都是增量验证，即DUT或者Spec做出了小的变更，需要针对这些变更进行新的验证。

UCAgent默认的配置为全量验证，需要编写所有测试用例。如果需要进行增量验证，可通过内置配置文件 `--config inc.yaml`进行。

本目录的目标：在已有 Adder 全量验证结果的基础上，对 RTL 做小改动（修 bug + 增强功能），然后仅针对改动部分进行增量验证。

### 前置条件

- 已完成 Adder 的一次“全量验证”，并且验证结果目录位于上级目录 `UCagent/output`（本例的 `make init` 会从 `../output` 复制基线结果）。
- 已安装 `picker`。

流程如下：

1. 完成原始全量验证（前置条件）
2. 通过参数`--config inc.yaml`启动UCAgent（记录修改前信息）
3. 对工作目录进行修改
4. 通过命令`hmcheck_pass [your_needs]`写入验证要求
5. 告诉LLM：`增量任务已给出，请Complete该阶段，从下一个阶段获取具体任务并进行完成`

## 案例

完成`examples/Adder`的验证后，对其进行修改：

1，修复原始的位宽bug
2，增加有符号加法
3，进行增量验证

具体步骤：

1. 参考 UCAgent/README.zh.md 完成 Adder 自动化验证（基线输出目录为 `UCAgent/output`）：

   - 在仓库根目录执行：

     ```bash
     make mcp_Adder
     ```
    然后通过 iflow或者qwen-cli完成验证。

1. 在本目录下运行 `make init`(默认mcp模式启动，api模式用`make init_test`)：复制基线验证结果到本目录的 `output/`，并以增量配置启动 UCAgent
2. 在Code Agent端输入`请通过工具RoleInfo获取任务信息，并完成所有任务`
3. 继续运行`make diff`对原始验证结果进行修改
4. 在 UCAgent 的命令行输入（通过人工审核并写入本次增量的验证要求）：

   ```bash
   hmcheck_pass Adder的bug已修复且增加了有符号加功能，请完成修改部分的验证
   ```

5. 在 Code Agent 端输入：`增量任务已给出，请Complete该阶段，从下一个阶段获取具体任务并进行完成` 开启验证


### 本例改动说明

`make diff` 做了两件事：

- 用本目录的 `Adder_new.v` 覆盖 `output/Adder_RTL/Adder.v`
- 调用 `picker export` 重新生成 `output/Adder`python包，然后覆盖 `output/Adder/README.md`

`Adder_new.v` 的增量点：

1. 修复位宽问题：`sum` 输出为 `[WIDTH-1:0]`（与 `WIDTH` 一致）。
2. 增加有符号加法：新增输入 `signed_mode`。

   - `signed_mode === 1'b1`：按有符号数相加（对 `a/b` 做符号扩展）。
   - 其他情况：按无符号数相加（包含 `signed_mode` 为 `0/1`）。
   - `cin` 始终按 0/1 零扩展参与运算，避免 signed 语境下的歧义。
