---
name: ppa-iteration-analysis
description: Use accepted PPA metrics to choose one bounded source optimization hypothesis for Pareto acceptance evaluation.
---

# PPA Iteration Analysis

Start from the accepted iteration, remaining candidate count, single base-normalized PPA score, classified PPA diffs, area composition and power composition returned by `CurrentTips` or the latest `Check`. Select one dominant hotspot that can be changed directly in the current RTL language. The score ranks only accepted versions; a high diagnostic score on a rejected version never overrides a regression inside the protected no-regression categories.

Record one bounded hypothesis in `{OUT}/reports/ppa/candidate_hypothesis.yaml` with exactly `iteration`, `hypothesis`, `target_hotspot`, and `expected_metrics`. An ordinary PPA candidate changes only the selected-language source, then calls `Check` to rerun the same functional and performance TC sets and return the PPA comparison. Do not edit reports or curve data produced by Check/Complete.

The Python reference remains a repairable implementation of README, Spec, architecture, and FG/FC/CK, but a reference repair is never a PPA candidate optimization. If functional evidence proves the reference wrong, repair it and rebuild the Python, RTL, performance, and base-PPA evidence before proposing another candidate; do not compare against the stale base. Never change reference behavior or expected values to make a candidate pass or improve its score.

Use `Guide_Doc/ppa_optimization.md` for the canonical artifact. The normal stage task and Check diagnostics provide the same route without this Skill.

Optionally call `RunSkillScript` with `commands=[["ext/design-with-ppa/ppa-iteration-analysis", "summarize_ppa.py", ""]]` to extract a bounded area, timing, power and change summary. The script is read-only; `Check` makes the acceptance decision.
