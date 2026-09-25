---
name: report-publication
description: Validate the canonical Bug Review JSON and render workspace and cross-workspace HTML directly from it.
---

# Report Publication

## Goal

Treat `{OUT}/workspaces/<workspace>/bug_review.json` as the only report data source. Do not create a parallel `report_data.json` or duplicate Bug decisions in another file.

## Actions

Run the renderer from the workspace root:

```text
RunSkillScript(commands=[["ext/bug_review/report-publication", "render_report.py", ""]])
```

The script reads every selected workspace JSON, validates the current schema, then writes Bug detail pages, each workspace `index.html`, and `{OUT}/index.html`. The pages must preserve original Bug declarations and confidence, decisions, merged root cause membership, related tests, replay results, WaveInfo viewer/receipt, and Spec/RTL source references. HTML escaping and links are produced by the renderer. When Skills are disabled, follow the same JSON-to-HTML contract with available file tools.

Open the generated total index and workspace pages. Check every Bug detail link, waveform viewer and source reference. Set every workspace's `stage_status.publish` to `complete` after rendering and review, then run Check, record the stage journal and Complete.
