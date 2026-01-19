
## 多UCAgent并发执行

很多场景下，为了提升验证效率，需要在一个节点上同时对多个DUT进行并发验证。因此需要UCAgent在一个节点上运行多个。


### API 方式

在API模式下，不同workspace下的UCAgent是独立的，因此不同任务可以在多个终端同时运行。

如果需要指定不同`API_KEY`可以通过环境变量进行传递，例如：

```bash

# 第一个命令行窗口
OPENAI_API_KEY=sk-6ba91a522d9fx8dfc458b3a0c7074b66 ucagent ....

# 第二个命令行窗口
OPENAI_API_KEY=sk-55h9aa522d9fx8dfc458b3a0c8074b34 ucagent ....

```


### MCP 模式 + Code Agent

可以基于 UCAgent 的MCP端口参数来实现多个UCAgent同时运行。具体流程如下：

- 获取一个随机可用端口`P`
- 如果参数`--mcp-server-port P`启动 UCAgent
- 通过`P`配置Code Agent的MCP连接（例如通过 env 传递给iFflow cli）


示例并发见本目录下的 `Makefile` 文件，使用方法如下(请先配置IFLOW_env.bash中的KEY)：

```bash

# 通过API方式直接并发
make api_mul

# 基于UCAgent-MCP + iflow 进行并发
#  可以在多个终端下运行多次
make mcp_mul
```

## 运行Pytest时启用多核

可通过参数`PYTEST_ADDOPTS="-n auto"`环境变量进行多核配置，具体可参考：[https://pytest-xdist.readthedocs.io/en/stable/](https://pytest-xdist.readthedocs.io/en/stable/)
