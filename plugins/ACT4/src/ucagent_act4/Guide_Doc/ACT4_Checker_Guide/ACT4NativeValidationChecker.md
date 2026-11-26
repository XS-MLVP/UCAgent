
# ACT4NativeValidationChecker

证明声明的贡献集可独立消费，而不是依赖本轮未交付的脚本、配置或缓存。

## 操作

先完成原生资产和 file manifest，再调用：

```text
Check(stage_args={"action":"validate","timeout":3600})
Check()
Complete()
```

原生命令在临时独立副本执行，仅加入 contribution_set，日志和 receipt 留在
`native-validation/`。包括 make tests 的生成一致性、prek、必要的 UDB 查询、CTP 构建、
选定 native configs 的 ELF 编译和运行。完整输入与报告示例见
`Guide_Doc/ACT4_Generation_Guide.md section 6` 和
`Guide_Doc/ACT4_Generation_Guide.md section 7`。

## 结论

失败、超时、零 ELF、未提交生成变更或 hooks 改写源码都不能通过。这里运行的原生消费者
都是非商业验证依赖；缺失时应安装或实现并重试，不能以“不可用”结束验收。
商业覆盖工具的可选性单独记录，不免除原生生成、hooks、CTP、编译与运行。
所选配置通过不代表全部 CI、可选覆盖或真实 DUT 认证通过。
UDB 查询结果在 `udb_parameters.log`，诊断在 `udb_parameters.stderr.log`；参数缺失、重复、输出无效或命令失败仍须修复。
CTP 默认构建整书。仅当范围外未修改的映射在独立冻结基线复现相同缺规则错误，且本轮没有更改文档或共享 CTP 工具时，才可验收套件表格。
这要求重新生成计划表、规则表和适用的参数表，按原章节的 include 使用原生构建渲染 HTML 和 PDF。查看 `ctp_baseline.log`、`ctp_suite_render.log` 和两份渲染产物；在报告中保留 `ctp` 限制，不得声称整书通过。其他错误或缺失渲染依赖仍然阻塞。
普通 Check/Complete 仅核验当前贡献、环境和日志，修改后需重跑 validate。
最终报告需引用收据，且 generation_result 与实际结果一致；人工签署和维护者审批始终独立。

## 修复

阅读错误所指日志，修改真正的原生源码、更新 manifest/hash，再运行 validate。
缺工具时回到环境准备，不能修改测试范围去掩盖失败；源文件被 hook 改写时将正确格式
应用到工作副本，不编辑临时验证副本。仅声明本次实际执行范围。
