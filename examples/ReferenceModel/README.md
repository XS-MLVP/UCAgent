
## 启用参考模型自动生成

在UCAgent的默认流程中，关闭了“自动生成参考模型”阶段，可通过环境变量或者修改配置文件启用：

#### 1 通过环境变量启动

设置环境变量`NEED_REF_MODEL`为true即可开启，例如：

```bash
NEED_REF_MODEL=true make mcp_ALU754
```

#### 2 通过修改配置文件

修改默认配置文件`ucagent/lang/zh/config/default.yaml`，把其中的所有`$(NEED_REF_MODEL: false)`替换为`true`:

```yaml
#...
  - name: reference_model_fixture_imp
    desc: "参考模型fixture实现与测试"
    ignore: not $(NEED_REF_MODEL: false) # 改为: ignore: not true
    task:
#...
      - "是否已启用参考模型": $(NEED_REF_MODEL: false)
      # 改为: - "是否已启用参考模型": true
#...
```
