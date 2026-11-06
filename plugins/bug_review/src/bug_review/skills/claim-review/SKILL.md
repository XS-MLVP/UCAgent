---
name: claim-review
description: Organize original Bug statements from inconsistent reports without changing input files.
---

# 整理原始声明

先读 Guide_Doc/analysis.md。逐份阅读 source_documents，给出 source_reviews 的处理理由。
同一缺陷出现在摘要、多个检查点或静态报告时，核对语义后合并并保留全部来源。不要把原始 BG 块数量当作 Bug 数量。
以 SubmitReviewClaims 提交结构化内容，由工具生成记录。填写精确 Case 关联；缺失关联就记录缺口，不猜测身份。
用 ReviewContext 核对来源及关联，再 Check。该 Skill 可选，全部必需规则和完整示例均在 Guide_Doc/analysis.md。
