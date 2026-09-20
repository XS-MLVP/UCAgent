
# 仓库模块开发

`repo-module-tdd` 使用已有 Git 仓库作为源码和依赖提供方，开发或优化一个模块。它只构建和测试选定的单元，不构建完整系统、不运行系统集成测试，也不修改源仓库。

## 运行

创建一个包含 `README.md`（可选 `spec/` 文档）的任务 case，描述目标模块、必需行为、允许的修改范围、接口约束和性能目标。这些文档只面向任务本身；推荐的架构和 RTL 文件名是建议，除非被显式声明为硬性要求。

```bash
make run-repo CASE=my_module CASE_SOURCE_ROOT=/path/to/tasks \
  SOURCE_PATH=/path/to/source-git REPO_WORKSPACE=/path/to/independent-workspace
```

等价的工作流选择器是 `--plugin-workflow design-with-ppa:repo-module-tdd`。现有的 `make run`、`make run-chisel` 和 `unit-design-tdd` 工作流保持不变。工作区必须位于源仓库之外；两个目录互相不得包含。

维护的 `repo_byte_increment` 案例需要一个包含 `rtl/unit.v`（模块 `Unit`，无符号 8 位 `a`/`y`，`y = (a + 1) mod 256`）的源 Git 仓库。一条命令生成配套演示源仓库后即可完整跑通：

```bash
make prepare-repo-demo-source
make run-repo CASE=repo_byte_increment SOURCE_PATH=output/repo_demo_source
```

演示源仓库生成在 `DEMO_REPO_SOURCE`（默认 `output/repo_demo_source`），可重复执行，已存在时直接复用。

## 源码选择

配置位于 `design_with_ppa.repo`。`SOURCE_PATH` 在配置加载时提供 `source_path` 的默认值；之后以解析后的配置为准。

| 选项 | 默认值 | 用途 |
| --- | --- | --- |
| `source_path` | `SOURCE_PATH` | 原始 Git 仓库根目录 |
| `source_ref` | `SOURCE_REF` 或 `HEAD` | 要导入的 commit/ref |
| `snapshot_mode` | `commit` | `commit` 或显式 `working_tree` 快照 |
| `include_untracked` | `[]` | working-tree 模式下显式附加的文件路径 |
| `source_paths` | `[]` | 显式要导入的仓库相对文件/目录；为空表示导入全部 |
| `mode` | `optimize` | 优化已有模块或 `add` 新增模块 |
| `interface_policy` | `evolve` | 允许接口版本演进或要求 `preserve` |
| `build_recipe` | `recipe.yaml` | 候选相对的单元导出 recipe |

commit 导入会记录被排除的本地修改并固定子模块版本。缺失的子模块需要在导入前单独准备。working_tree 模式要求所选 ref 解析到 HEAD，并捕获已跟踪的修改/删除以及显式列出的未跟踪文件。内部符号链接保持在独立副本内部；指向外部的链接被拒绝。Git 元数据和指向源仓库的可写硬链接不会被复制。

对于大型仓库，用 `source_paths` 选择目标目录和所需的依赖文件。只有选中的子模块需要本地对象；缺失的选中内容会连同其路径一起报错。被排除的子模块 pin 保留在源码和交付清单中。选择是显式的，不从构建失败推断。新增模块要包含其父目录，要修改的每个文件都必须包含在选择内。匹配不到任何源文件的选择会失败。更改选择需要新工作区和重新建立基线。

源仓库只用于只读导入。构建使用可信的项目命令和本地工具链在独立副本中运行。这是文件系统隔离，不是针对恶意脚本的沙箱。Git、Picker、Yosys、OpenSTA 以及 recipe 使用的任何模块生成器/转换器必须已安装。

## 单元工作流

八个阶段依次完成源码导入、FG/FC/CK 功能合同、模块合同、独立参考模型验证与按 CK 的功能覆盖率统计、基线测量、带 COVERS 反标的 pytest 用例（`RunTestCases` 可自行运行调试）、候选探索和交付重建。`design/repo/` 下生成的任务文件遵循[运行时指南](../src/design_with_ppa/Guide_Doc/repo_module.md)中的完整示例；重启后已存在的文档/代码基于其完善。每次 PPA 测量自动刷新 `{OUT}/design_with_ppa_dashboard.html`（复用既有 HTML 报告）。

原生项目 recipe 只导出选定的模块及其依赖。它们声明有序的 RTL 文件、include 路径、宏定义、生成器版本命令和超时。Yosys 检查实际 elaborate 出的公开引脚，然后由现有的受管 Picker 后端构建隔离的 Python DUT。综合前端不支持的 SystemVerilog 特性需要在 recipe 中包含显式转换步骤。参考模型和测试适配器使用独立进程运行；适配器只能驱动/读取已声明的引脚，结果值从硬件输出采样。

接口演进保持逻辑语义和工作负载不变，而引脚名、位宽、握手和延迟可以在任务约束内演进。必需的硬件适配属于被测单元边界内。调用方影响被记录下来供后续手工集成。每个被测版本完整保留全部源码修改、接口文档、适配器、协议测试、参考/工作负载输入和构建说明。

原始基线测量后不可变。修改冻结的任务、参考或工作负载需要新工作区和重新建立基线。PPA 迭代复用 `unit-design-tdd` 的键名和默认值：`min_optimization_iterations`/`max_optimization_iterations`/`no_improvement_patience` 约束候选轮数，`no_regression_metrics` 和 `score_weights` 驱动接受判定和最佳版本选择，`ppa.max_timing_paths`/`ppa.max_power_instances` 设定每次测量的 OpenSTA 详情深度。这些键全部导出到运行时快照。不宣称任何完整系统验证。

## 交付

`RunRepoValidation(action="deliver", migration_script=true)` 创建包含原始和最终接口合同、文件哈希、测试、PPA 和完整候选历史的源码/RTL/补丁交付包。自动生成的 `summary.md` 报告基线与交付版本的主指标对比、接口版本和如实的改善结论，只由封签测量记录生成。交付包在新副本中应用并重建。没有改善时，报告会如实说明。

可选的独立脚本 `apply.py --target /path/to/target` 预览变更。实际应用需要 `--apply`，在存在 Git 元数据时校验 base commit，并拒绝冲突的文件内容或可执行位。工作流从不自动把交付包应用到 `SOURCE_PATH`。

维护的[字节自增任务](../cases/repo_byte_increment/README.md)描述了一个小单元。真实工具回归 fixture 在临时目录中创建源 Git 仓库；不提交任何生成的工作区。

## XiangShan 单元验收

`tests/test_repo_xiangshan.py` 是针对本地 XiangShan checkout 的可选测试。它读取源码和 Git 元数据、导入显式依赖闭包，并只编译一个单元 wrapper 和选中的 Scala 源码。它从不调用根 Mill 构建，也不 elaborate 处理器。

优化 case 测量 `src/main/scala/utils/VecRotate.scala`——一个被 `ICacheReplacer` 使用的依赖，覆盖 8 个字节 lane、两个方向和全部旋转量。候选用分级多路选择器替换 one-hot 旋转网络。新增 case 在候选 overlay 中创建 `src/main/scala/xiangshan/frontend/icache/myICache.scala`：一个复用 `VecRotate` 的弹性 bank 重排单元，不是完整指令缓存。它的第二个接口版本把响应拆分为两个 32-bit 输出引脚。两个 case 都运行真实引脚测试、PPA、最佳版本恢复、补丁应用和全新单元重建。前后对比源码字节、权限和 Git 元数据；对原始仓库的迁移只做预览。

fixture 针对 XiangShan `build.mill` 中声明的 Scala 2.13.17 和 Chisel 7.13.0。安装 JDK 17、Scala CLI bootstrapped JAR 和常规 RTL/PPA 工具。首次依赖解析需要 Maven 访问。从插件源码目录运行：

```bash
JAVA_HOME=/path/to/jdk-17 \
SCALA_CLI_JAR=/path/to/scala-cli.jar \
COURSIER_REPOSITORIES=https://repo.maven.apache.org/maven2 \
DESIGN_WITH_PPA_XIANGSHAN_SOURCE=/path/to/XiangShan \
PYTHONPATH=/path/to/UCAgent:/path/to/DesignWithPPA/src \
python3 -m pytest -q -s tests/test_repo_xiangshan.py
```

不设置 `DESIGN_WITH_PPA_XIANGSHAN_SOURCE` 时，这两个测试跳过，不会给现有工作流增加 Scala 或 XiangShan 依赖。打印的独立工作区包含 `summary.json`、完整交付包和前后源码清单。结果只确立被测单元配置；完整 ICache 行为、其他 VecRotate 配置和处理器集成保持未验证。
