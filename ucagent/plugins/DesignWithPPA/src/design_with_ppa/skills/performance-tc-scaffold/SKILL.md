---
name: performance-tc-scaffold
description: Scaffold deterministic performance pytest cases, waveform sidecars, and a stable multi-TC manifest for PPA analysis.
---

# Performance TC Scaffold

Use the current stage's resolved output paths and performance contract. Derive latency and throughput from simulated time, clock occurrences, cycles, and transaction counts, never pytest wall-clock duration.

After the performance contract is complete, create the exact dedicated pytest nodes declared by every `measurement_test`:

```text
RunSkillScript(commands=[["ext/design-with-ppa/performance-tc-scaffold", "scaffold_performance_tests.py", ""]])
```

The script deterministically aligns file paths, function names, the `performance` marker, the `env, request` signature, and the RTL sidecar branch. It replaces only unimplemented performance scaffolds and refuses to overwrite implemented test logic. It does not choose stimulus, expected results, observation windows, transaction counts, or metric formulas; implement those from the Spec and performance contract, then remove every `assert False, "Not implemented"` placeholder.

Give every performance pytest node one deterministic stimulus or recorded seed, one unique VCD/FST, and one atomically written JSON sidecar. Preserve the base node IDs, parameters, seed, stimulus hash, input-trace hash, and waveform scope for every optimization round. Use the helpers and complete schemas in `Guide_Doc/performance_contract.md` and `Guide_Doc/performance_measurement.md`.

Run each existing performance pytest with `RunTestCases`, or let `Check`/`Complete` run the complete set. Never execute performance code by directly importing a test/reference/adapter module or by using `python -c` or a temporary script.

If a deterministic performance vector proves that the Python reference contradicts README, Spec, architecture, or FG/FC/CK behavior, repair the reference and rerun the affected functional and performance tests before collecting RTL evidence. Do not alter reference behavior or expected values to improve a measured metric or to match an incorrect RTL result. Any reference change invalidates existing RTL waveform and PPA evidence and requires those gates to run again.

The stage task, templates, and Guide_Doc files carry the same contract when this Skill is disabled.

After the performance tests have produced their artifacts, optionally call `RunSkillScript` with `commands=[["ext/design-with-ppa/performance-tc-scaffold", "audit_performance_artifacts.py", ""]]` for a bounded path/hash consistency summary. `Check`/`Complete` remains the authoritative validation path.
