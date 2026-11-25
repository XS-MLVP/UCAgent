
<!-- SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# ucv4xs 方法保留与来源记录

来源仓库：[XS-MLVP/ucv4xs](https://github.com/XS-MLVP/ucv4xs)。读取时检出的基线为
`c13ee6fbb48f8b7eff19d1945393416822fe48ee`，**skills 目录包含本机未提交修订**。
下表 SHA-256 指实际读取文件，不把这些内容全部归到该 commit，也不声称上游已经审核。
本记录是插件方法的来源清单，不是 DUT 任务的状态或第二套验证计划。

## 保留原则

- 10 篇问题方法分别成为独立 Skill，保留输入、步骤、产出、验收和历史案例依据。
- 设计/执行导航与 ucv4xs 专用入口分别保留，共 13 个可发现入口；不把全文再压成三摘要。
- P01–P12 速查卡保留，4 篇 pending 以待审参考保留，不注册、不默认启用、不提升为门禁。
- 将工程路径、工具和结果格式适配到 ToffeeUT；盘点、生成、执行、计数仍由工具/脚本完成。
- 修正与当前公开 API 或验收冲突的表述：采样无效值过滤、实际 seed、报告 INCOMPLETE
  与用例 UNCERTAIN、当前 issue 分类等；不把旧 API/命令作为兼容入口。
- 升级、迁移、删除与发布的历史操作不成为默认授权；原生环境保持单 venv。
- 案例保留为原工程路径和经验摘要，不复制整份运行产物、不假装本轮复现。源材料缺失
  就披露缺失；本地修订可能未在公开 commit 中出现，不提供冒充精确版本的外链。

## 实际源文件与落位

源路径相对于 ucv4xs；目标相对于本插件 skills 根。

| 源路径 | 目标 | 实际源 SHA-256 |
|---|---|---|
| skills/design/requirements-boundary.md | requirements-boundary/SKILL.md | dacfcc488712656e7f3ee677cfe637ba4420acb37a5622f738c4eeda655c0947 |
| skills/design/observation-precision.md | observation-precision/SKILL.md | 06b223439784da201fad3c0ff3d8ddea43d87abc23850f4dc5342bf85714763b |
| skills/design/behavior-equivalence.md | behavior-equivalence/SKILL.md | cf0b8e0d4b4442e976f5c9747b180fcb3ac47d8c5e12be138d13e50fea82df00 |
| skills/design/traceability-and-implementation.md | traceability-and-implementation/SKILL.md | 9b3bd8269f0f24aa3e09db9b9589d7add50a3f8f5f94c769f339b42f6a604437 |
| skills/design/closure-and-residuals.md | closure-and-residuals/SKILL.md | 84a28c3a4252c532f852b9e652704c6421589b0ea59d69750c547918ff2ef45f |
| skills/execution/package-layout.md | package-layout/SKILL.md | 3fe43f6db32ae35614e1a70722e032105c32a79d4e3a3e3b207f54ffe4acfd59 |
| skills/execution/legal-stimulus.md | legal-stimulus/SKILL.md | 4804dc066a6eedcd276efc363299e65756a9a64c9d14cf51936f67bdac4c907b |
| skills/execution/independent-oracle.md | independent-oracle/SKILL.md | 7d39b8ee308a362463b6507ac0b121699d41b02786d270f48f933c782deebc33 |
| skills/execution/checker-and-runtime.md | checker-and-runtime/SKILL.md | fb4e8595376030a617593ccaafa8dc6a34a9bd498889ff09f5fd039129f55e0e |
| skills/review/triage-and-evidence.md | triage-and-evidence/SKILL.md | 8743e263ea6af7b71174c1fc75fee0c59ac21158503c343eb2668596957003e8 |
| skills/verification-completeness/SKILL.md | verification-completeness/SKILL.md | 7e9939db7a74f68a1191a6b8b35f4e07da81a9b7982d236d00219954cd9774b0 |
| skills/rtl-verification-soundness/SKILL.md | rtl-verification-soundness/SKILL.md | eeaa90ab2b3050facd1e0f7bb4f2071cd3d31f88c2a412f8598b69bfbb2cb970 |
| skills/ucv4xs-workflow/SKILL.md | ucv4xs-workflow/SKILL.md | 3c6e03541e4437fe79ffd8f4d085c6f58231a61acb70645227e68653ffa1716f |
| skills/rtl-verification-soundness/CARD.md | rtl-verification-soundness/CARD.md | 8c8091fa1e8cca197e364b68068b489388c1ef364285cc441218b15516befca0 |
| skills/pending/dependency-upgrade-and-capability-audit.md | ucv4xs-workflow/references/pending/dependency-upgrade-and-capability-audit.md | d30b454c425ae49af098b90fc0801c5af2367f88aea9e267bce3640659bdf8cb |
| skills/pending/fixture-consolidation.md | ucv4xs-workflow/references/pending/fixture-consolidation.md | 0b9a8c13ce6ffbb763190c7612122c2a1a1e52db2dd27beb3851ba5229b524dd |
| skills/pending/framework-capability-selection.md | ucv4xs-workflow/references/pending/framework-capability-selection.md | f4250cbc732e5a5ab075e5b3cf6d22ce0aebd13d01ca65128293b8edc12d09ce |
| skills/pending/pin-schema-and-suite-migration.md | ucv4xs-workflow/references/pending/pin-schema-and-suite-migration.md | d651c3e3679d8d457869e9622b8354f1ecbee1bddfa359975a030397ce220fc8 |
| skills/README.md | ../Guide_Doc/ut-methods.md | 50f322a7c43cb6e405baf491bcf89f3ca86ddf375617a37390f16cd10f55a5b9 |
| skills/pending/README.md | ucv4xs-workflow/references/pending/README.md | af5492b2b3622aed67a02bc9de44bc3588f1517e2cecf12d7e7958c499aece3d |

## 许可

适配的上述 Skill、速查卡、待审参考、Guide_Doc/ut-methods.md 及来源记录保留 MPL-2.0，正文为可修改的 Source Code
Form。见[许可全文](LICENSE-MPL-2.0.txt)，或 https://mozilla.org/MPL/2.0/ 。源项目贡献者的
权利和免责声明保留。插件自身 Python、工作流和工具仍按 UCAgent 的 Apache-2.0；方法内容
的复用不改变核心或其他插件许可。
