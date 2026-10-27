
# Evaluation, Approval, and Incremental Fixing Issues

## Configuration Errors Not Detected During Evaluation

**Phenomenon**: For example, a phase uses a non-existent variable, references future files, or a Checker checks an error object, but the evaluation report contains no findings.

**Root Cause Types**: Evaluation guidelines list only a few surface-level rules; the evaluation Agent searches for keywords without performing phase data flow verification; the evidence budget is exhausted; or a specific component considers the issue belongs to another responsibility domain.

**Remedy**: Enhance general check dimensions rather than simply adding variable names. The evaluation process should establish mappings from variable definitions to usage, phase inputs to outputs, reference existence timelines, and Checker objects to artifacts, and perform refutation. Severity should be judged based on actual impact.

## How Users Approve and Propose Suggestions

Users can use the console or execute `eval-approve`, `eval-reject`, `eval-defer`, and `eval-suggest`. Approval reasons should describe the allowed modification boundaries and acceptance objectives; users do not need to provide full patches. New suggestions are used when users proactively propose issues not found in the evaluation report.

## Incremental Phase Takes a Long Time to Read

The goal of the cognitive phase is to understand the current workflow and the scope of approval for this round, not to read all tools, checkers, GuideDoc, docs, and reports in full. First, read indexes, directories, and summaries, then read directly relevant files according to the approval target. Tool outputs should also be limited to the required intervals to avoid compression followed by immediate quota exceedance.

## Incremental Process Does Not Complete All Approvals

Check the approval snapshot of the current run and the "item to modification/evidence" mapping. Completion conditions must cover every id; passing `make check` after fixing only the first item does not represent that other suggestions are complete. Entries without modifications must also record why no modification is needed and the supporting evidence.

## `make check` Fails After Deployment but Process Waits

This is a serious state machine issue. After formal files are replaced, the approval status no longer acts as a gate blocking repairs. The process must continue fixing and re-verifying, or rollback and fail out. Version backups are responsible for recovery; a second round of human approval for the same approved target is not required.

## Old Findings Remain After Fix

Aggregated reports retain history. To conclude, one must re-run `eval_tools`, `eval_checkers`, `eval_flow`, or `eval_env` using the new run. Directly deleting old findings loses audit information and cannot prove the fix is effective.

## Fix Completed Abnormally Quickly

Check `applied_changes.json`, formal file diffs, candidate evidence, and actual command return codes. The issue may only require minor changes, or the report may not have been deployed. Speed itself is not evidence of quality.

## Evaluation Agent Continues to Fail

First, distinguish between a reported Checker failure and a target finding. Read the last tool invocation, JSON store errors, required check id, and report status. If the tool only accepts records but the Agent passes the entire document, the guideline example should be fixed; if evidence is missing, source code or commands should be added, not the Checker lowered directly.

## Finding Quality Assessment

High-quality findings are reproducible, cite requirements, include source code or return codes, have justified severity, and have clear suggestion scopes. Low-quality findings merely state "there may be risks," set format preferences as critical, cite non-existent paths, or suggest rewriting the entire system. Merge duplicate items with the same root cause before approval.

## Candidate Plan and Build Plan

`wfgen/workflow_implementation_plan.md` belongs to the initial build; the current candidate plan is located in `tmp/inc_runs/<id>/`. The console can display both simultaneously, but they cannot be mixed into a single system. Writing the candidate back to the build plan will pollute historical design.

## Read-Only Formal Files and Early Termination

The deployer deploys via temporary files in the same directory and `os.replace`. Standard read-only files can be handled, but if the directory is not writable or backup fails, it blocks. If the inc terminates early, compare the approval snapshot, candidate plan, incremental report, and applied changes to confirm that every approved id has a change or evidence of no modification; passing `make check` alone cannot prove all suggestions are complete.
