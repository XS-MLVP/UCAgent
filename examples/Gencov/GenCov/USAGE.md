# GenCov 使用示例

### 运行命令示例
```bash
# 初始化工作区（默认输出到 ../../output）
make -C examples/Gencov init_IFU

# 以API方式运行UCAgent生成覆盖
make -C examples/Gencov gencov_IFU

# 以MCP方式运行UCAgent
make -C examples/Gencov gencov_mcp_IFU
```

说明：`init_IFU` 会在项目根目录创建 `output/`，拷贝 `IFU/`，并将 GenCov 资源放入
`output/IFU/gencov/`。同时把首个 `.hvp` 复制为
`output/IFU/spec/IFU_verification_plan.hvp` 以匹配 `gencov.yaml` 的路径约定。

## 可选参数

- 指定工作区根目录：`OUT_DIR=/path/to/output make -C examples/Gencov init_IFU`
- 传递 UCAgent 参数（如指定输出目录）：`make -C examples/Gencov gencov_mcp_IFU ARGS="--output gencov"`
- 重新准备工作区：`make -C examples/Gencov clean`
