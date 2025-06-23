# UCAgent
UnityChip Verification Agent


通过大模型进行自动化的UT验证，完成以下工作：

- 生成功能列表和检测点列表
- 生成DUT通用API接口
- 生成功能覆盖定义
- 生成测试用例
- 生成bug分析文档

### 快速开始

安装依赖
```bash
pip install -r requirements.txt
```

编辑`config.yaml`配置必要设置，例如：

```yaml
openai:
  openai_api_base: <your_openai_api_base_url>
  model_name: <your_model_name>
  openai_api_key: <your_openai_api_key>

embed:
  model: <your_embed_model_name>
  openai_base_url: <your_openai_api_base_url>
  api_key: <your_api_key>
  dims: <your_embed_model_dims>
```


安装picker依赖， 然后运行测试：
```bash
make dut
make test_adder
```

测试结果位于`./output`目录。

### 主要目录结构：

```bash
UCAgent/
├── LICENSE                   # 开源协议
├── Makefile                  # 测试 Makefile 入口
├── README.md
├── config.yaml               # 配置文件，用于覆盖默认配置文件
├── doc                       # 给AI进行参考的文档
├── examples                  # 用于进行AI测试的案例
├── requirements.txt          # python依赖
├── tests                     # 单元测试
├── vagent                    # Agent主代码
│   ├── config
│   │   └── default.yaml      # 默认配置文件，全量
│   ├── stage                 # Agent流程定义
│   ├── template
│   │   └── unity_test        # 模板文件
│   ├── tools                 # 工具实现
│   │   ├── extool.py
│   │   ├── fileops.py
│   │   ├── human.py
│   │   ├── memory.py
│   │   ├── testops.py
│   │   └── uctool.py
│   ├── util                  # 公用函数
│   ├── verify_agent.py       # 主Agent逻辑
│   ├── verify_pdb.py         # 基于PDB的交互逻辑
│   └── verify_ui.py          # 交互UI
└── verify.py                 # 主入口文件
```

基于上述目录结构，UCAgent 按照 `config.yaml` 中定义的“阶段流程”进行验证任务，每个阶段必须检测通过才能进入下一个阶段。直到所有阶段的任务都完成。一般验证任务分以下5个阶段（具体参考`vagent/config/default.yaml`）：

1. 理解任务需求
2. 列出所有功能点与检测点
3. 接口封装
4. 生成功能覆盖分组"
5. 生成测试用例并运行"
