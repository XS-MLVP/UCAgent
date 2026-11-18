
# ACT4 输入资源与输出目录

## 1. 准备固定版本的输入

在 `prepare_resources` 调用 `Check(stage_args={"action":"prepare"})`。
已有输入保持不变；默认目录缺失时先复用共享来源，再寻找既有输出中的完整、干净、版本匹配的
checkout，最后才下载。不要自行重复 clone、复制整个规范库或更新共享仓库。
准备通过后调用 `Complete`；后续运行继续使用记录的提交，不把缓存版本称为“上游最新”。
下载失败看 `StdCheck` 和当前资源目录中的日志，补充可访问的固定版本输入后重试。

使用 `ACT4Resources(action="status")` 获取各输入的位置和来源。
`list` 列出目录，`read` 返回带起始行与总行数的文本，均只读；列表截断时进入更具体的子目录。
独立 ISA 计划验收前只读 ISA、用户范围及依赖安装资料，不预览已有测试计划、coverage 或 testgen。
生成流程会准备独立可写的 `riscv-arch-test`；审查及香山流程的执行和候选副本由后续 `Check` 准备。
不向共享来源写测试、缓存、虚拟环境或日志。

## 2. 引用必要的原始文件

需要 `reference_files` 的工作区相对路径时，仅保留实际引用的 ISA 文件，不复制整个仓库。
下面是一段完整的操作示例；文件名应先根据实际目录确认：

```text
ACT4Resources(action="status")
ACT4Resources(action="list", resource="manual", path="src")
ACT4Resources(action="read", resource="manual", path="src/sstc.adoc", start_line=1, limit=100)
ACT4Resources(action="snapshot", resource="manual", path="src/sstc.adoc")
```

若最后一步返回 `out/intermediate/Sstc/resources/references/manual/src/sstc.adoc`，
在 ISA 计划的 `reference_files` 和 `reference_scope` 中使用这一确切路径，并选择实际阅读的行范围。
继续遵循 `Guide_Doc/ACT4_Extension_Review_Guide.md` 的完整 ISA 计划契约。
保留文件与原始输入不一致时，不覆盖已引用证据，重新选择稳定来源并开始新一轮运行。
生成流程的 provenance 仍记录原始规范内的 `source_path`；资源状态中的绝对位置用于说明原始来源，
规范副本和 metadata 副本按当前阶段的指定路径保存。

## 3. 交付与过程资料分离

`{OUT}` 是本轮 `--output` 目录，根目录只放用户的主要结果：

```text
out/
  final.md
  changes.patch                  生成或审查流程
  Vector-kunminghu-v3.tar.gz      香山交付流程
  delivery/                      香山接收方的可独立使用目录
  intermediate/
    Vector/
      resources/                 输入来源、下载日志、必要的原文快照
      environment/               工具计划、探测及安装证据
      handoff/                   配置、构建副本、执行日志及机器收据
```

审查使用 `intermediate/{DUT}/review/` 保存计划、批次、基线、候选、实验、原生命令与前后证据。
生成使用 `intermediate/{DUT}/` 保存草稿、契约、references、reports 和 experimental。
`final.md` 中链接过程资料，不重复复制它们到根目录或交付包。
审查的 `changes.patch` 相对于原始输入根目录；生成补丁只包含 manifest 声明的 contribution_set，
不包含工具、构建产物或证据。补丁存在不等于原生 CI 或真实 DUT 通过，必须结合摘要中的限制阅读。
香山交付包只含接收方需要的源码、构建环境、二进制、索引与操作指南，不混入本轮日志和审查收据。
