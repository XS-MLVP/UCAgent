
# ACT4FileManifestChecker

实现：`act4_privileged_suite/checkers/act4_file_manifest_checker.py`

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

## 代码实现原理

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
4. 从 baseline inventory 读取受保护对象的 path/type/mode/SHA-256；扫描当前 ACT4 tree，
   比较新增、删除、内容、symlink target 和权限变化。suite 自身 generator 是显式例外，
   work/cache 等 artifact tree 不参与受保护扫描。
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

## 测试

回归测试位于 `plugins/ACT4/tests/test_act4_file_manifest_checker.py`。

## 实现定位与配置关系

`_validate_file_entries()` 校验文件/hash，`_validate_contribution_set()` 检查贡献集合，
`_validate_events()` 校验事件结构，`_validate_inventory()` 枚举实际产物，
`_validate_framework()` 执行基线比较。

01/04 使用 integrity_only，不等于检查了完整 files/change_events；
05 同时有 integrity-only 和 inventory 实例；06/07 启用 require_contribution_set。
inventory 只检查 actual - manifested 的遗漏，额外合法条目可保留；不是双向集合完全相等。
当前配置 inventory 未枚举 references 子树，不代表冻结参考副本可从工作流要求中省略。

事件不是连续 hash 链或可信时间日志；checker 不证明 baseline 确实在首次写入前生成，
也不证明每次修改都记录。默认链接脚本模式针对 link.ld 等指定名称，不会自动识别全部
其他 .ld/.lds 文件或语义上的通用代码。完整保护范围仍需按工作流政策审查。
不要通过修改保护模式、重写基线或恢复原文件掩盖违反政策的写入。
