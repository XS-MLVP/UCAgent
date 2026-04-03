# Review Gate

The RTL-analysis front half ends at a mandatory human review gate.
The top-selection experience should stay minimal: recommend one top, show alternatives once, record the answer, then move on to the draft review.

## What must be reviewed

- recommended top candidate
- confirmed top candidate
- ranked candidate list
- top-selection rationale
- draft `FG/FC/CK`
- draft verification plan
- initial test skeleton suggestions
- risks and open questions

## Required behavior

- Do not continue directly into workspace, runtime, bootstrap, contract, or smoke execution.
- First complete the single top-selection confirmation step and record it in review state.
- Wait for explicit user approval.
- If the user requests changes, update the drafts and wait again.

## After approval

Finalize the approved draft into a standard truth file:

```bash
python .codex/skills/pytoffee-toffee-test-workflow/scripts/finalize_functions_and_checks.py \
  --draft <draft_dir>/fg_fc_ck_draft.md \
  --dut <DUT> \
  --output-dir <docs_dir>
```

That confirmed `{DUT}_functions_and_checks.md` becomes the only execution truth for the back half of the workflow.

## Finalization rule

Do not finalize while placeholders remain.
Do not overwrite an existing confirmed file unless there is an explicit reason and `--force` is intended.
