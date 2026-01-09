# GenCov IFU 使用示例

## MCP 模式（唯一支持）

```bash
make -C examples/Gencov gencov_mcp_IFU
```

说明：先执行 `make -C examples/Gencov init_IFU`，会在仓库根目录的 `output/` 下创建工作区，
拷贝 `IFU/` 与 `GenCov/`，并生成配置 `output/GenCov/gencov.yaml`。
请确保使用 Python 3.11+（可先执行 `source ./.uvenv/bin/activate`）。
默认 MCP 地址为 `127.0.0.1:6001`，可用 `MCP_HOST`/`MCP_PORT` 覆盖。

## 一致性检查

```bash
make -C examples/Gencov check_IFU
```

## 可选参数

- 传递 UCAgent 参数：`make -C examples/Gencov gencov_mcp_IFU ARGS="..."`
- 指定 DUT 顶层名：`make -C examples/Gencov gencov_mcp_IFU DUT=<top_module>`
