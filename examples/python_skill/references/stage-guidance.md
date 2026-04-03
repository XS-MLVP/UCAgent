# Stage Guidance

## Scope

This guide covers the full workflow from raw RTL analysis through runtime smoke execution.
Use it when the user gives you RTL and you need to move from design understanding to executable verification.

## Stage 0 — Scan the RTL project

**Input:** RTL project root

**Action:** run `scripts/scan_rtl_project.py <project_root>`.

**Output:** JSON with discovered RTL files, Scala hints, modules, instance edges, ranked top candidates, a recommended top candidate, and `selection_required: true`.

**Completion standard:** you have enough structural evidence to draft top analysis and ask the user for one top-selection confirmation.

## Stage 1 — Bootstrap review drafts

**Input:** scan JSON

**Action:** run `scripts/bootstrap_rtl_review.py --scan <scan.json> --output <draft_dir>`, present the recommended top plus alternatives in one concise question, then run `scripts/confirm_top_candidate.py` with the human choice.

**Output:** overview Markdown, split draft files, copied scan JSON, and `review_state.json` with `approved: false`, `recommended_top_candidate`, and `confirmed_top_candidate`.

**Completion standard:** the project has a stable place for human review and one recorded top-selection decision.

## Stage 2 — Human review gate

**Input:** draft review tree with recorded top selection

**Action:** revise the draft files, present them to the human, and wait.

**Output:** either requested changes or explicit approval.

**Completion standard:** the human explicitly confirms the top candidate and draft testpoint model.

## Stage 3 — Finalize the execution truth file

**Input:** approved `fg_fc_ck_draft.md`, DUT name, output docs directory

**Action:** run `scripts/finalize_functions_and_checks.py ...`.

**Output:** a confirmed `{DUT}_functions_and_checks.md`.

**Completion standard:** the back-half execution flow has exactly one truth file to consume.


## Stage 4 — Detect the working layout

**Input:** project root

**Action:** run `scripts/detect_project_layout.py <project_root>`.

**Output:** JSON with `project_type`, `dut_name`, `tests_dir`, `docs_dir`, and `has_fg_fc_ck_doc`.

**Completion standard:** you have one concrete DUT name, one doc path, and one tests directory candidate.

## Stage 5 — Create a disposable workspace

**Input:** workspace path, DUT name, project metadata

**Action:** run `scripts/bootstrap_workspace.py --workspace <dir> --dut <DUT> ...`.

**Output:** a workspace containing `exports/`, `generated/`, `logs/`, and `workspace.json`.

**Completion standard:** you have a safe place for picker exports, generated files, and smoke logs.

### Rules

- Use a disposable workspace for generation and smoke execution.
- Do not point the workspace at a maintained directory.
- Keep exported DUT packages under `<workspace>/exports/{DUT}`.

## Stage 6 — Run runtime preflight

**Input:** workspace, tests directory, DUT name

**Action:** run `scripts/check_runtime_env.py ...`.

**Output:** readable PASS/FAIL lines for Python, `picker`, `toffee`, `toffee_test`, `pytest`, DUT import or DUT export readiness, and API import.

**Completion standard:** runtime prerequisites are green, or you have a precise remediation target.

### Rules

- Treat runtime FAIL as a hard stop.
- Repair runtime issues before bootstrapping more files.
- If the DUT is not importable yet but the RTL file and picker path are healthy, runtime preflight can still pass in an export-ready state.
- `picker --check` only needs Python support for this workflow; Go/Java/Lua failures are not blockers.

## Stage 7 — Extract the canonical FG/FC/CK set

**Input:** one `*_functions_and_checks.md` file

**Action:** run `scripts/extract_fg_fc_ck.py <doc>`.

**Output:** `groups -> functions -> checks` JSON.

**Completion standard:** every later coverage name and test mapping comes from this extracted set.

### Rules

- Treat the markdown file as the source of truth for `FG`, `FC`, and `CK` names.
- Keep exact names; do not translate, normalize, or invent alternatives.

## Stage 8 — Bootstrap or repair the minimum tree

**Input:** DUT name plus either an empty output directory or an existing verification tree

**Action:** run `scripts/bootstrap_verif_tree.py --dut <DUT> --output <dir>` only for fresh scaffold output; otherwise repair the existing tree.

**Output:** `{DUT}_api.py`, `{DUT}_function_coverage_def.py`, and `test_basic.py`, or repaired equivalents.

**Completion standard:** the tree exists in a form that can be contract-checked.

### Rules

- Bootstrap only into an empty or disposable directory.
- If files already exist and matter, switch to repair instead of regenerate.

## Stage 9 — Enforce minimum contracts first

**Input:** verification tree directory

**Action:** run `scripts/check_verif_contracts.py <dir>`.

**Output:** readable PASS/FAIL lines.

**Completion standard:** contract checks pass before runtime smoke or test expansion.

If this stage fails, go directly to `repair-checklist.md` and `template-contracts.md`.

## Stage 10 — Run one real smoke command

**Input:** workspace, tests directory, one targeted pytest node, DUT name, optional RTL file

**Action:** run `scripts/run_smoke_test.py ...`.

**Output:** one of `pass`, `picker_failure`, `dut_import_failure`, `pytest_collection_failure`, `fixture_failure`, `test_failure`, or `env_failure`, plus log paths.

**Completion standard:** the workflow reaches a real test invocation and leaves logs.

### Rules

- Prefer one targeted smoke node over a full suite for the first runtime check.
- If the DUT package is missing, export it into `<workspace>/exports/{DUT}` before retrying.
- A `test_failure` means the verification chain ran; repair the DUT/test logic, not the toolchain.

## Stage 11 — Check FG/FC/CK mapping

**Input:** canonical markdown doc plus runnable tests directory

**Action:** run `scripts/check_fg_fc_ck_mapping.py <doc> <tests_dir>`.

**Output:** missing/extra/mismatch results across coverage and tests.

**Completion standard:** names align before broader test expansion.

## Stage 12 — Expand deliberately

Only after runtime smoke and mapping checks are understood should you add:

- `test_random.py`
- summary output templates
- bug analysis templates
- richer API helpers or coverage groups

At this point, use `picker-quickref.md`, `toffee-test-quickref.md`, and `pytoffee-patterns.md` as the syntax guides.
