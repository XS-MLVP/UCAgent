# UCAgent Docker Usage

## Quick Start

### 使用预构建镜像

```bash
# Pull the image
docker pull ghcr.io/xs-mlvp/ucagent:latest

# Run interactively
docker run -it --rm \
  -v $(pwd)/examples:/workspace/examples \
  -v $(pwd)/output:/workspace/output \
  -e OPENAI_API_KEY=your_api_key \
  ghcr.io/xs-mlvp/ucagent:latest
```

### 本地构建

```bash
# Build the image
docker build -t ucagent:latest .

# Run interactively
docker run -it --rm \
  -v $(pwd)/examples:/workspace/examples \
  -v $(pwd)/output:/workspace/output \
  -e OPENAI_API_KEY=your_api_key \
  ucagent:latest
```

## 在容器内使用 UCAgent

进入容器后，可以直接使用 ucagent 命令：

```bash
# 查看帮助
ucagent --help

# 运行示例
cd examples/Adder
ucagent

# 使用配置文件
ucagent -c config.yaml

# 使用 npm 命令
npm --version
npm install <package>
npm run <script>
```

## 环境变量

- `OPENAI_API_KEY`: OpenAI API 密钥（必需）
- `LANGCHAIN_API_KEY`: LangChain API 密钥（可选，用于追踪）
- `LANGCHAIN_TRACING_V2`: 启用 LangChain 追踪（可选，默认 false）

## 挂载卷

建议挂载以下目录：

- `./examples:/workspace/examples` - 示例代码
- `./output:/workspace/output` - 输出结果
- 持久化缓存卷以加速后续运行

## 镜像信息

- 基础镜像: `ghcr.io/xs-mlvp/picker:latest`
- 包含: UCAgent 及其所有依赖
- 预装工具: Verilator, SWIG, Python 3 等验证工具
