## GenCov 功能覆盖示例

该示例演示如何将 IFU 的 HVP 测试点转换为可实现的功能覆盖率逻辑，并进行一致性检查。

### 目录结构

- `IFU/`：示例输入材料（hvp/rtl/doc/chisel）。
- `GenCov/`：配置模板、一致性检查脚本与覆盖骨架。
- `Makefile`：示例启动入口。

### 使用方式

```bash
# 初始化工作区（默认输出到 ../../output）
make -C examples/Gencov init_IFU

# 以API方式运行UCAgent生成覆盖
make -C examples/Gencov gencov_IFU

# 以MCP方式运行UCAgent
make -C examples/Gencov gencov_mcp_IFU
```

更多说明请参考 `examples/Gencov/GenCov/USAGE.md`。
