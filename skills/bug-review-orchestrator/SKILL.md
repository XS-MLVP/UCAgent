---
name: bug-review-orchestrator
description: Prepare and validate UnityTest bug-review inputs before UCAgent Master launch, with optional direct launch and monitoring for isolated bug_review runs.
---

# Bug Review Orchestrator

Use this skill before starting a hardware DUT's evidence-based `bug_review:analysis` run. This is a standalone pre-launch skill for the LLM or operator. It is not part of UCAgent Master startup: Master must consume the prepared `workspace_<dut>/` directory and must not call `scripts/prepare_inputs.py` or repair missing reports during launch.

## Prepare inputs

Run `scripts/prepare_inputs.py` with the shared module directory used by the default UCAgent workflow and the repository input root. The source must follow the `examples/Adder` layout: `launch.yaml`, `unity_test/`, module-level RTL, and optionally `filelist.txt`. The script creates `workspace_<dut>/` with the same root layout, copies reports and tests, copies RTL/filelists, and records source paths and hashes in `prepare_manifest.json`. It never copies an old compiled `.so` as a new Picker result.

Read `prepare_manifest.json` after preparing. If `bug_reports.reanalysis_required` is nonempty, do not start Bug Review yet. Read every file listed by `bug_reports.preserved_legacy_reports`, the available Bug/static-analysis documents, test summaries, current tests, Verification Needs, and relevant Spec/RTL. Rebuild each missing canonical report at the exact paths `unity_test/<dut>_bug_summary.md` and `unity_test/<dut>_bug_analysis.md`. Use `inputs/workspace_raid_dec_top/unity_test/raid_dec_top_bug_summary.md` and `raid_dec_top_bug_analysis.md` as the layout reference, and follow the current Bug Review report schema in the plugin's `src/bug_review/Guide_Doc/analysis.md`. Preserve each original Bug identity, claim, cited test and source reference when supported by the source material; distinguish historical claims from newly validated facts. Do not invent Bugs, test results, confidence, BG/TC associations, or waveforms. If the source material is insufficient to reconstruct a required field, retain the available claim and mark the gap explicitly in the report text. Rerun preparation after writing reports and verify both canonical paths exist and `reanalysis_required` is empty before launching.

When `launch.yaml` has `files.filelist` or the module root has `filelist.txt`, the filelist is the Picker entry point. Do not add a duplicate `<dut>.v` or `<dut>.sv` merely to satisfy preparation. The filelist must be usable on the current node: relative entries resolve from the module/filelist directory, and entries that point into another checkout must either remain accessible at the same absolute path or be copied into the module using the same relative layout. Without a usable filelist, provide a top-level `.v` or `.sv` and declare it as `files.main_rtl`.

The DUT runtime must be generated with the default Picker at `~/unitychip/bin/picker`. For a filelist-only module, use `picker export --fs <path/to/filelist.txt> --sname <dut> ...`; no positional top-level Verilog path is required. A VCS build requires a working license; a Verilator build requires every generated SRAM model in the filelist. Preserve failed build logs in the input workspace and report the exact missing prerequisite.

For example, prepare and validate the input before opening Master:

```bash
python3 scripts/prepare_inputs.py \
  --source examples/bosc_LoadUnit \
  --input-root plugins/bug_review/inputs
```

After `prepare_manifest.json` reports no pending reanalysis, start UCAgent Master separately and select the generated `plugins/bug_review/inputs/workspace_bosc_LoadUnit/launch.yaml` in the Launch page. The default run and the Bug Review run must consume the same prepared module directory and filelist. Master may create an execution snapshot for isolation, but it must not invoke this preparation script, invent a second RTL directory, or silently replace a missing canonical report.

The `launch_tmux.py` command below is an optional direct plugin runner for environments that do not use Master. It is not a step performed by Master and does not replace the pre-launch preparation or validation above.

## Launch in tmux

Run `scripts/launch_tmux.py --input-root ... --output-root ... --dut ... --python /path/to/python`. It prepares one output run per requested module, creates a tmux session with one window per run, and starts `bug_review.workflow run-analysis` with the requested backend (default `codex`) and an automatically selected MCP port. Each window writes to `<output-root>/tmux-<dut>.log`. Use the Python environment whose UCAgent version satisfies the plugin requirement. Add `--interactive` only when attaching a real terminal for the TUI; detached tmux runs should remain noninteractive so the Codex process can drive the stages.

## Monitor

Run `scripts/monitor.py --output-root ...` repeatedly or from a separate tmux pane. It emits JSON lines containing session existence, current run, completed stages, and the last log lines. A missing session is not success; inspect `workflow status` and the run log. Do not bypass plugin version checks or treat a failed Picker build as a valid DUT runtime.

For this repository's Prefetcher example, use `/nfs/home/songfangyuan/unitychip/.venv/bin/python`, not the system interpreter. The repository input is `plugins/bug_review/inputs/workspace_bosc_Prefetcher`; the review output must be outside `inputs/`.
