# 安装

## 系统要求

- Python 版本： 3.11+
- 操作系统：Linux / macOS
- API 需求：可访问 OpenAI 兼容 API
- 内存：建议 4GB+
- 依赖：
  - [picker](https://github.com/XS-MLVP/picker)（将 Verilog DUT 导出为 Python 包）
  - Code Agent：[Qwen Code CLI](https://qwenlm.github.io/qwen-code-docs/zh/cli/)(使用UCAgent提供的工作流和工具)


## 安装方式

- 方式一：克隆仓库并安装依赖

  ```bash
  git clone https://github.com/XS-MLVP/UCAgent.git
  cd UCAgent
  pip3 install .
  ```

- 方式二（pip 安装）
  ```bash
  pip3 install git+https://git@github.com/XS-MLVP/UCAgent@main
  ucagent --help # 确认安装成功
  ```
