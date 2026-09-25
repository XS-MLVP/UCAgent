---
name: inventory-review
description: Analyze the original Bug summary and detailed analysis, then create and fill the canonical Bug Review JSON with each reported Bug and its candidate evidence.
---

# Inventory Review

## Goal

Read the selected input reports and prepare one canonical JSON record per workspace. The script creates the file structure and preserves parsed report identities; your analysis supplies and corrects its evidence content.

## Actions

For each selected workspace, read these files with `ReadTextFile`:

- `{OUT}/inputs/<workspace>/unity_test/<DUT>_bug_summary.md`
- `{OUT}/inputs/<workspace>/unity_test/<DUT>_bug_analysis.md`

Create its JSON skeleton by running:

```text
RunSkillScript(commands=[["ext/bug_review/inventory-review", "create_review_json.py", "<workspace>"]])
```

Edit `{OUT}/workspaces/<workspace>/bug_review.json` using `EditTextFile`. Keep one `suspected_bugs` entry for every summary item, preserving the exact raw summary row, ID, wording, confidence and source location under `bug_summary`. Preserve detailed-analysis claims even when no summary row matches; mark their origin and source. For each Bug, fill nested `evidence` with source-backed Spec references, test points, FG/FC/CK checks, case IDs, RTL references, root candidates and unresolved questions. Evidence paths must point to the original input workspace and include line ranges when known. Do not invent source locations.

Read Spec and RTL candidates from their mirrored paths under `{OUT}/inputs/<workspace>/`; preserve original source-relative paths in JSON evidence. The preparation step stages Markdown, HDL source and line-map text only, omitting generated reports, binaries, history and agent state. Test case files and shared helper/fixture files are available under `{OUT}/tests/<workspace>/unity_test/tests`. This is a partial runtime copy, not a full workspace copy. The replay stage must still select exact JSON nodes and must not run all tests just because they are present.

Keep each unique test node once in the top-level `cases` object, keyed by its normalized source node ID. Link each Bug to relevant cases through `evidence.case_ids`; cases may reference multiple Bug IDs. Do not decide whether a claim is a real DUT Bug in this stage. Mark `stage_status.inventory` as `complete` after every input claim and candidate relationship is represented, then run Check, record the stage journal and Complete.

## Required JSON structure

The canonical file is `{OUT}/workspaces/<workspace>/bug_review.json`, schema `bug_review.v3`. Preserve its `workspace`, `source_files`, `stage_status`, `suspected_bugs`, `cases` and `root_causes` top-level keys. Each Bug contains `bug_id`, `origin`, `bug_summary`, `reported_confidence`, `analysis_claims`, `evidence` and `decision`. Each case contains `nodeid`, `bug_ids`, `source_nodeid`, `replay_target`, `waveform_test_case_name`, `replay`, `test_review` and `waveform`. Extend these objects with source-backed evidence without renaming canonical keys.
