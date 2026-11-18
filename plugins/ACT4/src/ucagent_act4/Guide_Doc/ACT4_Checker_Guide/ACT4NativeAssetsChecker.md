
# ACT4NativeAssetsChecker

检查原生资产类别是否齐备，不把本地分析文档当作可贡献资产。

## 产物

完整原生 YAML、CSV、asset_contract、规则/参数映射与 CTP 示例见
`Guide_Doc/ACT4_Generation_Guide.md section 3` 至
`Guide_Doc/ACT4_Generation_Guide.md section 5`。

- plan 阶段：核对原生 schema/字段、唯一标识、非空请求及原计划保留；自动派生阅读视图。
- assets 阶段：核对正式规则、参数适用性与 effect、CTP include、coverage 及必要生成源码。
- 非特权还核对选中 coverpoint/variant 和 Type 对应的模板、受限的 extension_sources。
- 每个选中 instruction/XLEN 的生成汇编须有合法原生测试头；格式和筛选边界见
  `Guide_Doc/ACT4_Asset_Authoring_Guide.md section 4`。不以“存在非空 .S”代替合法测试资产。

## 操作与边界

修改原生源文件后调用 Check，再 Complete，不传额外参数。不要修改派生 CSV/Markdown。
错误会给出具体文件和字段；修复缺项或引用，而不是删除源请求、编造 rule 或乱写不适用。
存在某类文件不能证明语义正确；必须继续核对设计并执行原生消费者，完整验证要求见
`Guide_Doc/ACT4_Checker_Guide/ACT4NativeValidationChecker.md`。
