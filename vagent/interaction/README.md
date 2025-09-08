# UCAgent 交互模式系统

这个目录包含了UCAgent的智能交互系统，提供三种不同的交互模式来适应不同复杂度和需求的验证任务。

## 📁 文件结构

```
vagent/interaction/
├── __init__.py          # 模块导出和接口定义
├── enhanced.py          # 增强交互逻辑
├── advanced.py          # 高级自适应交互逻辑
├── orchestrator.py      # 智能工具编排器
└── README.md           # 本文档
```

## 🎯 三种交互模式

### 1. Standard Mode (标准模式)
**默认模式，适用于简单直接的任务**

- **特点**: 轻量级、快速响应、低资源消耗
- **适用场景**: 
  - 简单的验证任务
  - 资源受限的环境
  - 快速原型验证
  - 调试和测试

```python
# 自动使用标准模式（默认）
agent = VerifyAgent(workspace, dut_name, output)
```

### 2. Enhanced Mode (增强模式) 
**集成规划和内存管理的智能模式**

- **核心功能**:
  - ✅ 智能任务规划 (CreatePlan, UpdatePlan, GetPlan, ListPlans)
  - ✅ 阶段化执行管理 (planning → execution → verification → reflection)
  - ✅ 内存管理和上下文保持
  - ✅ 文档智能检索和参考

- **执行阶段**:
  1. **Planning Phase**: 创建详细的任务计划
  2. **Execution Phase**: 按计划系统性执行
  3. **Verification Phase**: 验证和检查结果
  4. **Reflection Phase**: 定期反思和优化

- **适用场景**:
  - 中等复杂度的验证项目
  - 需要系统性规划的任务
  - 要求可追踪进度的项目
  - 多阶段的验证流程

```python
# 使用增强模式
agent = VerifyAgent(workspace, dut_name, output, interaction_mode="enhanced")
```

### 3. Advanced Mode (高级模式)
**自适应策略和性能优化的智能模式**

- **核心功能**:
  - 🧠 自适应策略选择
  - 📊 上下文复杂性分析
  - 📈 实时性能跟踪
  - 🛠️ 智能工具推荐和编排
  - 🔄 策略动态调整

- **自适应策略**:

  #### Exploratory Strategy (探索策略)
  - **使用时机**: 任务开始、需要广泛调研
  - **特点**: 广度优先、多角度探索
  - **行为**: 搜索相关文档、探索多种方案、建立全面理解

  #### Focused Strategy (聚焦策略)  
  - **使用时机**: 目标明确、需要快速执行
  - **特点**: 深度优先、直接高效
  - **行为**: 最短路径执行、最小化探索活动

  #### Systematic Strategy (系统策略)
  - **使用时机**: 复杂任务、需要结构化处理
  - **特点**: methodical方法、全面验证
  - **行为**: 逐步执行、全面验证、详细记录

  #### Recovery Strategy (恢复策略)
  - **使用时机**: 遇到困难、需要问题诊断
  - **特点**: 问题诊断、替代方案、增量进展
  - **行为**: 分析障碍、寻找替代方法、重建动力

- **智能特性**:
  - **上下文分析**: 自动评估任务复杂度（Low/Medium/High/Critical）
  - **性能跟踪**: 监控执行效率和成功率
  - **策略适应**: 基于表现自动调整策略
  - **工具推荐**: 根据上下文推荐最合适的工具

- **适用场景**:
  - 复杂的验证项目
  - 需要性能优化的长期任务
  - 动态变化的验证需求
  - 对执行效率有高要求的项目

```python
# 使用高级模式
agent = VerifyAgent(workspace, dut_name, output, interaction_mode="advanced")
```

## 🎛️ CLI 使用方法

### 基本语法
```bash
python3.11 -m vagent.cli <workspace> <dut_name> [--interaction-mode MODE]
```

### 使用示例

```bash
# 标准模式（默认）
python3.11 -m vagent.cli ./workspace Adder

# 增强模式 - 适合需要规划的中等项目
python3.11 -m vagent.cli ./workspace DualPort --interaction-mode enhanced

# 高级模式 - 适合复杂的自适应任务
python3.11 -m vagent.cli ./workspace ALU --interaction-mode advanced
```

## 📊 模式选择指南

| 因素 | Standard | Enhanced | Advanced |
|------|----------|----------|----------|
| **任务复杂度** | 低 | 中等 | 高 |
| **执行时间** | 短期 | 中期 | 长期 |
| **资源消耗** | 最低 | 中等 | 较高 |
| **智能化程度** | 基础 | 高 | 最高 |
| **可追踪性** | 基础 | 高 | 最高 |
| **自适应能力** | 无 | 有限 | 完全 |

### 决策树

```
任务是否复杂？
├── 否 → Standard Mode
└── 是 → 需要自适应优化？
    ├── 否 → Enhanced Mode  
    └── 是 → Advanced Mode
```

## 🛠️ 工具编排系统

高级模式包含智能工具编排器，将工具分为以下类别：

- **Search**: SemanticSearchInGuidDoc, ReadTextFile, ListDir
- **Memory**: MemoryPut, MemoryGet, MemoryList, MemoryDelete  
- **File Operations**: WriteTextFile, AppendTextFile, MoveFile
- **Verification**: CheckFunctionCoverage, RunTest, CompileCode
- **Planning**: CreatePlan, UpdatePlan, GetPlan, ListPlans
- **Analysis**: AnalyzeCode, ParseVerilog, ExtractFunctions
- **Reflection**: Reflect, SqThink
- **Execution**: RunCommand, CompileCode, ExecuteScript

工具编排器会根据当前上下文和策略智能推荐最合适的工具组合。

## 📈 性能监控

高级模式提供实时性能监控：

- **执行效率**: 跟踪每轮交互的时间消耗
- **成功率**: 监控任务完成的成功率
- **策略效果**: 评估不同策略的表现
- **工具使用**: 分析工具使用模式和效果

## 🔄 故障安全机制

所有模式都实现了多层回退机制：

```
Advanced Mode (失败) → Enhanced Mode (失败) → Standard Mode
```

确保即使在出现问题时也能继续执行任务。

## 💡 最佳实践建议

### 对于新用户
1. **从标准模式开始**: 熟悉基本功能
2. **逐步升级**: 了解需求后选择合适模式
3. **观察日志**: 了解不同模式的行为差异

### 对于项目选择
1. **评估复杂度**: 根据DUT复杂度选择模式
2. **考虑时间**: 长期项目优选高级模式
3. **监控资源**: 资源受限时使用标准模式

### 对于性能优化
1. **使用高级模式**: 获得性能洞察
2. **监控指标**: 关注成功率和执行时间
3. **策略调整**: 让系统自动优化策略选择

## 🧩 扩展开发

如果需要扩展交互系统：

1. **添加新策略**: 在`advanced.py`中扩展`AdaptiveStrategy`枚举
2. **自定义工具分类**: 在`orchestrator.py`中添加新的`ToolCategory`
3. **增强上下文分析**: 扩展`ContextAnalyzer`的分析能力
4. **性能指标**: 在`PerformanceTracker`中添加新的跟踪指标

## 📚 API 参考

### 核心类

- `EnhancedInteractionLogic`: 增强模式的核心逻辑
- `AdvancedInteractionLogic`: 高级模式的核心逻辑  
- `ToolOrchestrator`: 工具推荐和编排
- `ContextAnalyzer`: 上下文复杂性分析
- `PerformanceTracker`: 性能监控和跟踪

### 枚举类型

- `AdaptiveStrategy`: 自适应策略类型
- `ContextComplexity`: 上下文复杂度级别
- `ToolCategory`: 工具分类类型

## 🐛 故障排除

### 常见问题

1. **模式切换失败**: 检查依赖是否正确安装
2. **性能跟踪异常**: 确认Python版本为3.11+
3. **工具推荐不准确**: 检查上下文分析配置

### 调试建议

1. **启用详细日志**: 使用`--log`参数查看详细执行信息
2. **检查模式状态**: 在代码中打印交互状态信息
3. **降级测试**: 从高级模式逐步降级到标准模式

## 📝 更新历史

- **v1.0**: 初始三模式设计实现
- **v1.1**: 添加智能工具编排
- **v1.2**: 增强性能监控和自适应策略

---

> 💡 **提示**: 选择合适的交互模式可以显著提升验证效率。建议根据项目实际需求选择，并通过性能监控持续优化。
