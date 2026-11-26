
# ACT4NativeAssetsChecker

检查原生资产类别是否齐备，不把本地分析文档当作可贡献资产。

## 产物

完整原生 YAML、CSV、asset_contract、规则/参数映射与 CTP 示例见
`Guide_Doc/ACT4_Generation_Guide.md section 3` 至
`Guide_Doc/ACT4_Generation_Guide.md section 5`。

- plan 阶段：冻结的空计划、重复场景和描述性名称允许补全；完成后的计划必须有有效请求，
  逐个检查 native_plans，source_request_map 使用原生路径#请求名保留重命名前的场景，自动派生阅读视图。
  已有纯说明成员可为空，但整个集合必须有真实测试点；不同文件的同名点不能相互替代。
- assets 阶段：核对公开或原文绑定规则、待发布跟踪、参数与 effect、CTP、coverage 及真实生成源码。
- 非特权用 Instruction/Type/ExtraExtensions 区分变体；EFFEW 作为元数据，SEW 模板由原生
  生成及隔离重生成验证。native_suites 列实际展开入口，输出检查包含 rv32i/rv64i/rv32e/rv64e。
- extension_sources 支持已有、共享和子目录生成器，以及新建原生配置；不改已有目标配置。
- 每个选中 instruction/XLEN 的生成汇编须有合法原生测试头；格式和筛选边界见
  `Guide_Doc/ACT4_Asset_Authoring_Guide.md section 4`。不以“存在非空 .S”代替合法测试资产。

## 操作与边界

修改原生源文件后调用 Check，再 Complete，不传业务参数；可通过 timeout 调整调用预算。不要修改派生 CSV/Markdown。
错误会给出具体文件和字段；修复缺项或引用，而不是删除源请求、编造 rule 或乱写不适用。
存在某类文件不能证明语义正确；必须继续核对设计并执行原生消费者，完整验证要求见
`Guide_Doc/ACT4_Checker_Guide/ACT4NativeValidationChecker.md`。
