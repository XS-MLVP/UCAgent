
# ACT4FileManifestChecker

## 作用

该 checker 负责两类硬 gate：资产账本完整性，以及 ACT4 protected framework integrity。
阶段 01 建立初始基线；04、05、06、07 在首次写入、生成构建、贡献整理和最终报告后重复
比较。它还保证 contribution set 只包含实际 PR 源码，不混入生成测试和构建证据。

## 主要输入与输出

- 输入：manifest v2、expected suite、ACT4 root、inventory globs、protected/exclude/artifact
  patterns，以及 `integrity_only` / `require_contribution_set`。
- 输出：manifested files、inventory files、change events、contribution sources、protected
  changes 和 findings。
- 该 checker 不落盘自身结果，避免“checker 输出改变 manifest，manifest 又需重算”的
  递归；工作流应先登记其他输出，最后运行 completeness check。

## 提交前检查

1. 验证 manifest v2 顶层、files 和 change_events schema、枚举、必填说明及 workspace
   containment；稳定文件重算 SHA-256，deleted/mutable/self-referential 情况执行专门规则。
2. `contribution_set` 与 `category: contribution_source` 做精确集合相等比较；提交路径必须
   在配置的 `act4_root` 内，禁止 `.S`、work/cache/venv、ELF、signature、results 和日志进入
   PR 源码集合。只对贡献集检查显式依赖：复用 Python 私有导入/路径/环境检查，并对照
   manifest 识别非贡献文件的读取/导入；检查 coverage 的 include/文件操作、CTP 的
   include/图片和符号链接目标。本地脚本、契约、配置与报告不接受独立性扫描，仍可相互依赖。
3. 按配置的 inventory globs 枚举实际核心交付/证据，过滤 cache/pyc 等噪声，确保每个
   实际文件在 manifest 中有条目。宽泛的报告 glob 覆盖本地 `work/`、`work_*/` 构建树时，
   只强制登记其中的 `.S/.sig/.results/.sig.log` 和最终 `.elf`；`.sig.elf`、生成配置、
   stamp 等中间文件可保留，不逐个要求登记。work 树外的报告和独立辅助配置仍正常检查。
4. baseline inventory 每个对象必须有唯一 path、`type: file|symlink`、引号包住的八进制
   mode 及 64 位小写十六进制 SHA-256。比较受保护对象的新增、删除、内容、链接目标和
   权限变化。suite generator 仅在基线不存在时允许本轮新建；基线已有时选择新 suite，
   不得覆盖或改写基线。work/cache 等运行产物不参与受保护扫描。
5. 若 baseline method 为 Git，同时运行 `git rev-parse HEAD`，确保当前 ACT4 HEAD 未漂移；
   manifest 中任何 policy_violation event 都直接失败。

## 当前局限

- 完整性比较只能看到当前状态。文件曾被修改后恢复为相同 bytes/mode 时无法自动发现，
  必须依靠 change event 如实记录 `policy_violation`；checker 不能替代可信审计日志。
- inventory 完整性只覆盖配置的 glob。未纳入 pattern 的重要文件可能不会被发现，因此
  工作流更新输出布局时必须同步配置。
- 对非 manifest 自身的 mutable report，`sha256_after: null` 加说明可通过 schema；这表示
  内容未被 hash 固定，应在最终阶段尽量收敛为稳定 hash。
- 默认 protected patterns 是项目策略，不是 ACT4 上游自动提供的完整分类；上游目录重构
  时必须复审。
- contribution set 的“是否值得提交”仍是工程判断。依赖检查只覆盖明确的静态引用，
  不执行贡献源码，不能证明任意动态路径、反射或间接依赖的完整闭包。贡献集/依赖变化时，
  必须按工作流在冻结 HEAD 的干净 ACT4 副本中仅加入贡献集，运行相应原生消费者并记录证据。
  正常 ACT4 依赖、贡献源码间引用、注释和规范/profile 标记可用；norm YAML 中的
  rule/coverpoint 标识不是文件导入。不通过扫描全部字符串或全部本地文件实现此检查。

## 失败后修复

`manifest_snapshot_inventory`：修正指出的重复路径或缺失/错误身份字段，依据首次写入前
保存的真实记录填写，不能用当前修改后的内容重建历史。
`manifest_suite_generator_exists`：当前是新 suite 工作流，选择基线中不存在的 suite，
不要覆盖已有 generator。若已产生违规写入，保留证据并报告阻塞。
其他 findings 给出具体文件；先修正资产或清单，再调用 `Check`。

01/04 使用 integrity_only，不等于检查了完整 files/change_events；
05 同时有 integrity-only 和 inventory 实例；06/07 启用 require_contribution_set。
inventory 只检查 actual - manifested 的遗漏，额外合法条目可保留；不是双向集合完全相等。
当前配置 inventory 未枚举 references 子树，不代表冻结参考副本可从工作流要求中省略。

事件不是连续 hash 链或可信时间日志；checker 不证明 baseline 确实在首次写入前生成，
也不证明每次修改都记录。默认链接脚本模式针对 link.ld 等指定名称，不会自动识别全部
其他 .ld/.lds 文件或语义上的通用代码。完整保护范围仍需按工作流政策审查。
不要通过修改保护模式、重写基线或恢复原文件掩盖违反政策的写入。

## 完整初始清单示例

以下是隔离示例：ACT4 中只有内容为 `all:\n\t@true\n`、权限为 644 的受保护 Makefile，
输出 `act4_assets/artifact.txt` 内容为 `asset\n`。示例用于填写初始清单，不表示真实
ACT4 checkout 只有一个受保护文件；实际必须记录冻结时的完整对象集合。

`act4_assets/baseline.yaml` 完整内容如下，换行及引号也是其字节内容的一部分：

```yaml
files:
  - path: riscv-arch-test/Makefile
    type: file
    mode: "644"
    sha256: 8e9d2d32d6d1845adc673c5ca7a7a5846c135698c20f967648ee4cdadbb6d297
```

`act4_assets/manifest.yaml` 完整内容：阶段 01 的贡献集为空，后续阶段按实际源码补齐；
self-referential 清单本身不填写内容 hash。稳定的 baseline 和产物都填写真实 hash。

```yaml
schema_version: 2
suite: H
workspace_root: .
baseline:
  method: sha256_snapshot
  git_head: null
  preexisting_changes: []
  status_command: sha256 snapshot before writes
  status_recorded: true
  baseline_inventory: act4_assets/baseline.yaml
contribution_set: []
files:
  - path: act4_assets/artifact.txt
    action: created
    category: internal_asset
    stage: 01_coverpoints
    content_summary: Recorded the initial example asset
    origin: isolated example
    reason: Demonstrate a complete initial manifest
    diff_summary: null
    diff_evidence: null
    existed_before: false
    sha256_before: null
    sha256_after: 38e2f84393baeb97ad9debdb0b096d4cceb12d9fc4204df0f351eb4fe919962f
    hash_note: null
  - path: act4_assets/baseline.yaml
    action: created
    category: report
    stage: 01_coverpoints
    content_summary: Recorded protected objects before suite writes
    origin: frozen workspace inventory
    reason: Compare protected files against the initial snapshot
    diff_summary: null
    diff_evidence: null
    existed_before: false
    sha256_before: null
    sha256_after: c0d8680f27cadfefa1b527e9011734031e4c40e41c1a4fd201b2baa64d8e8774
    hash_note: null
  - path: act4_assets/manifest.yaml
    action: created
    category: report
    stage: 01_coverpoints
    content_summary: Initial asset inventory and framework comparison
    origin: stage journal and saved evidence
    reason: Track output ownership and integrity
    diff_summary: null
    diff_evidence: null
    existed_before: false
    sha256_before: null
    sha256_after: null
    hash_note: self-referential manifest
change_events: []
framework_integrity:
  protected_files_modified: []
  protected_files_deleted: []
  protected_type_or_mode_changed: []
  policy_violations: []
  verification_command: sha256 and mode comparison with frozen snapshot
  passed: true
```
