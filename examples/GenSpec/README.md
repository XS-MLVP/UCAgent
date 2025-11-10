
## 基于 UCAgent 生成 Spec

Spec 文档是进行芯片验证与回归管理的基础。很多团队在项目早期只有零散的设计备忘、接口列表或旧版论文，缺乏结构化、可复用的规格说明。GenSpec 示例展示了如何借助 UCAgent 的自定义配置把这些碎片化资料整合成系统化的 `{DUT}_spec.md`，并在持续迭代中保持更新。

---

### 前置准备

- **工作空间布局**：以 `workspace/<DUT>/` 作为芯片资料主目录，新生成的 `spec` 文档会输出到 `workspace/{OUT}/`（OUT默认为`unity_test`）。
- **初始资料收集**：整理现有的功能列表、接口定义、时序图、论文摘录等，统一放置在 `{DUT}/docs/` 或 README 中，便于后续引用。

---

### `genspec.yaml` 配置要点
`genspec.yaml` 负责告诉 UCAgent 如何组织任务。如需了解具体内容请查看该文件。

---

### 生成流程

1. **撰写初稿（Collect 阶段）**  
	 - 根据已有资料编写 `{DUT}_spec.md` 的框架和概览（背景、功能摘要、关键性能指标）。
     - 需要按指定模板进行编写

2. **结合源码完善（Augment 阶段）**  
	 - 让 UCAgent 逐步阅读 RTL等源代码，提取信号含义、状态跳转条件、复位流程等细节。
	 - 对每个功能模块给出输入、输出、组合/时序行为、异常情况、覆盖点建议。对于参数化模块，记录参数取值限制与默认值。
     - 更新 `{DUT}_spec.md` 

3. **人机交互查漏补缺（Review 阶段）**  
	 - 人工对于LLM生成的结果进行校验，如果发现问题让LLM进行修改，直到人工检验通过。

---

### 运行命令示例
```bash
# 准备环境
mkdir output
cp examples/GenSpec/DCache output/
# 开始生成
ucagent output DCache \
	--config examples/GenSpec/genspec.yaml \
	--human \
    -s --tui --no-embed-tools
```

通过以上流程，GenSpec 示例可帮助团队快速搭建结构化规格说明文档，增加git支持，可实现设计演进过程中保持文档的可追溯性和一致性。祝使用顺利！
