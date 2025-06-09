# UCAgent
UnityChip Verification AI-Agent


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
  openai_api_base: "http://10.156.154.242:8000/v1"
```

安装picker依赖， 然后运行测试：
```bash
make dut
make test_adder
```

测试结果位于`./output`目录。
