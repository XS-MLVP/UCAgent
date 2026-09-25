---
name: review-notes
description: Update the Bug Review notes summary from completed stage artifacts while preserving manually written analysis.
---

# Bug Review Notes

Use this optional Skill to refresh `notes/bug_review_notes.md` after a stage completes. The script reads the resolved `OUT` value from `.ucagent/runtime_config.json`, then summarizes existing stage artifacts. It does not run tests, make Bug decisions, or change evidence. The `## 人工记录` section and text outside the summary markers remain unchanged.

From the DUT workspace, call:

```text
RunSkillScript(commands=[["ext/bug_review/review-notes", "sync_review_notes.py", ""]])
```

Read `notes/bug_review_notes.md` afterward and add your own analysis under `## 人工记录` if useful. The stage Checker validates the authoritative files under `{OUT}`; this note does not substitute for `BugReviewRunStage`, `BugReviewTasks`, `BugReviewSubmitResponse`, Check, or Complete.

When Skills are disabled or this directory is absent, read the current stage outputs under `{OUT}` directly. You may edit `notes/bug_review_notes.md` with the ordinary file tools. The required workflow and completion criteria are identical.
