---
name: pytoffee-toffee-test-workflow
description: Use when analyzing raw RTL into FG/FC/CK drafts or executing a pytoffee + toffee-test verification workflow from a confirmed FG/FC/CK markdown spec, especially for UCAgent-style or mixed Chisel+Verilog projects.
---

# pytoffee + toffee-test Workflow

## When to use

Use this skill when you need to move from raw RTL to reviewable FG/FC/CK drafts, or when you already have a confirmed `*_functions_and_checks.md` and need to execute the pytoffee verification flow.

## First read order

1. Read this file.
2. If the user gave you raw RTL, run `scripts/scan_rtl_project.py` on the RTL project root.
3. Run `scripts/bootstrap_rtl_review.py` on the scan JSON to create review drafts.
4. Present the recommended top plus the ranked candidate list in one concise question, then record the human choice with `scripts/confirm_top_candidate.py`.
5. Read `references/rtl-analysis-rules.md` and `references/review-gate.md`, then fill or revise the draft artifacts.
6. Stop for explicit human review.
7. After approval, run `scripts/finalize_functions_and_checks.py` to emit a confirmed `{DUT}_functions_and_checks.md` truth file.
7. If you need to rediscover an execution layout, run `scripts/detect_project_layout.py` on the project root or the confirmed docs location.
8. Run `scripts/bootstrap_workspace.py` to create a disposable workspace before generation or smoke execution.
9. Run `scripts/check_runtime_env.py` before bootstrapping or repairing anything.
10. Run `scripts/extract_fg_fc_ck.py` on the confirmed `*_functions_and_checks.md` file.
11. Run `scripts/bootstrap_verif_tree.py` only if you still need a minimal scaffold.
12. Run `scripts/check_verif_contracts.py` on the verification tree.
13. If contracts fail, read `references/repair-checklist.md` and `references/template-contracts.md`, then repair the failing files before generating anything else.
14. Once contracts pass, run `scripts/run_smoke_test.py` to execute one real smoke command.
15. Once smoke reaches real execution, read `references/stage-guidance.md`, `references/picker-quickref.md`, `references/toffee-test-quickref.md`, and `references/pytoffee-patterns.md`, then run `scripts/check_fg_fc_ck_mapping.py` before expanding tests.

## First-round commands

### RTL analysis draft phase

```bash
python .codex/skills/pytoffee-toffee-test-workflow/scripts/scan_rtl_project.py ../UCAgent/examples/Sbuffer > /tmp/sbuffer_scan.json
python .codex/skills/pytoffee-toffee-test-workflow/scripts/bootstrap_rtl_review.py --scan /tmp/sbuffer_scan.json --output /tmp/sbuffer_review
# show recommended_top_candidate + ranked candidates to the human in one message
python .codex/skills/pytoffee-toffee-test-workflow/scripts/confirm_top_candidate.py --review-dir /tmp/sbuffer_review --top Sbuffer
# fill and review /tmp/sbuffer_review/rtl_analysis_overview.md and split draft files
# after human approval:
python .codex/skills/pytoffee-toffee-test-workflow/scripts/finalize_functions_and_checks.py --draft /tmp/sbuffer_review/fg_fc_ck_draft.md --dut Sbuffer --output-dir /tmp/sbuffer_review/confirmed
```

### Execution phase after approval

```bash
python .codex/skills/pytoffee-toffee-test-workflow/scripts/bootstrap_workspace.py --workspace /tmp/pytoffee_skill_ws --dut Adder --project-root ../UCAgent_Gencov/UCAgent/examples/Adder --tests-dir ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests --docs-dir ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test
python .codex/skills/pytoffee-toffee-test-workflow/scripts/check_runtime_env.py --workspace /tmp/pytoffee_skill_ws --dut Adder --rtl ../UCAgent_Gencov/UCAgent/examples/Adder/Adder.v --tests-dir ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests
python .codex/skills/pytoffee-toffee-test-workflow/scripts/extract_fg_fc_ck.py ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/Adder_functions_and_checks.md
python .codex/skills/pytoffee-toffee-test-workflow/scripts/check_verif_contracts.py ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests
python .codex/skills/pytoffee-toffee-test-workflow/scripts/run_smoke_test.py --workspace /tmp/pytoffee_skill_ws --tests-dir ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests --test-node ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests/test_Adder_api_basic.py::test_api_Adder_add_zero_values --dut Adder --rtl ../UCAgent_Gencov/UCAgent/examples/Adder/Adder.v
python .codex/skills/pytoffee-toffee-test-workflow/scripts/check_fg_fc_ck_mapping.py ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/Adder_functions_and_checks.md ../UCAgent_Gencov/UCAgent/examples/Adder/unity_test/tests
```

## Full closed loop

The full closed loop is:

1. scan RTL / Chisel inputs
2. rank top candidates and recommend one default
3. ask the human to confirm or override the recommendation once
4. bootstrap and revise review drafts
5. stop for human review
6. emit a confirmed `*_functions_and_checks.md`
6. create a disposable workspace
7. verify runtime prerequisites
8. bootstrap or repair the minimum verification tree
9. run contract checks
10. run one real smoke command
11. run mapping checks
12. stop and repair before adding more assets

## Layout fallback rules

`detect_project_layout.py` applies these rules in order:

1. Look for `examples/*/unity_test/*_functions_and_checks.md` under the input root.
2. If the input root is already near one sample, accept any descendant `unity_test/*_functions_and_checks.md`.
3. If no `unity_test` doc exists, search the input root for `*_functions_and_checks.md`.
4. If multiple candidates exist, prefer one with a sibling `tests/` directory, then the shallowest path, then lexical order.
5. For the selected doc, use its parent as `docs_dir`.
6. Prefer a sibling `tests/` directory; otherwise use the nearest descendant `tests/` directory.

## When to stop generating and switch to repair

Switch to repair immediately when any of these is true:

- `check_runtime_env.py` prints a FAIL line for Python, `picker`, `toffee`, `toffee_test`, `pytest`, DUT import, or API import
- `check_verif_contracts.py` prints a FAIL line
- `run_smoke_test.py` returns `picker_failure`, `dut_import_failure`, `pytest_collection_failure`, `fixture_failure`, or `test_failure`
- generated files already exist and contain user edits
- `check_fg_fc_ck_mapping.py` reports missing, extra, or mismatched `FG/FC/CK` names
- the API layer exists but tests bypass it with direct low-level pokes

Regenerate only into an empty or disposable output directory.

## Reference files

- `references/rtl-analysis-rules.md` — front-half RTL analysis rules, top inference expectations, and draft quality rules
- `references/review-gate.md` — mandatory human approval gate before execution begins
- `references/stage-guidance.md` — stage-by-stage workflow, inputs, outputs, and fallback behavior
- `references/workspace-rules.md` — disposable workspace structure, safe reuse rules, and export layout
- `references/runtime-env.md` — how to read preflight failures and recover from them
- `references/template-contracts.md` — minimum contracts for `*_api.py`, `*_function_coverage_def.py`, and `test_*.py`
- `references/repair-checklist.md` — symptom-driven repair checklist for fixtures, coverage wiring, imports, and `FG/FC/CK`
- `references/picker-quickref.md` — local `picker` usage with the UnityChip toolchain
- `references/toffee-test-quickref.md` — local `toffee_test` syntax guidance and smoke command patterns
- `references/pytoffee-patterns.md` — workflow-facing usage notes for core `pytoffee` constructs

## Hard rules

- Do not continue into workspace, contract, or smoke execution before the RTL-analysis review gate is approved.
- Do not skip the one-shot top confirmation step after scan; record the selected top with `confirm_top_candidate.py` or equivalent state update.
- Do not keep generating or repairing verification code on a broken runtime environment.
- Put picker-exported DUT packages under `<workspace>/exports/{DUT}` so `from {DUT} import DUT{DUT}` works when `PYTHONPATH` includes `<workspace>/exports`.
- Do not invent `FG`, `FC`, or `CK` names that are not present in the source markdown.
- `test_*.py` must import through `from *_api import *`.
- Do not omit `set_func_coverage(...)` in `*_api.py` teardown.
- Do not omit `set_line_coverage(...)` in `*_api.py` teardown when the API opts into line-coverage reporting.
- Do not skip `Step()` just because the DUT looks combinational.
- Prefer a stable API layer over direct low-level signal pokes.
- Do not overwrite existing user-edited files during bootstrap.

## Output expectations

The minimum workflow state must include:

- a disposable workspace with `exports/`, `generated/`, and `logs/`
- readable runtime preflight results
- readable smoke logs

The minimum generated verification tree must include:

- `{DUT}_api.py`
- `{DUT}_function_coverage_def.py`
- `test_basic.py`

Useful follow-on assets include:

- `test_random.py`
- `{DUT}_test_summary.md`
- `{DUT}_bug_analysis.md`

The current templates remain UCAgent-style and `pytest`-fixture based. Use `references/toffee-test-quickref.md` when you need pure `toffee_test.fixture` / `toffee_test.testcase` syntax in addition to the UCAgent workflow.

If a check fails, repair the failing file first and rerun the appropriate checker or smoke command before expanding scope.
