
# LLM Check and Refinement

The UCAgent Checker first uses deterministic rules to verify stage artifacts. The optional LLM Check provides two types of assistance on top of this:

- **Fail Refinement**: After a stage `Check` fails, it analyzes the current diagnosis and provides repair suggestions.
- **Pass Check**: After the Checker passes before stage completion, an independent model reviews the results; the review model must call `ApproveStagePass` to approve the stage.

Both features are disabled by default. They do not replace the Checker, nor do they automatically convert test infrastructure failures into DUT Bugs.

## 1. Minimal Configuration

Fail Refinement:

```bash
export ENABLE_LLM_FAIL_SUGGESTION=true
export FAIL_SUGGESTION_MODEL="<model_name>"
export FAIL_SUGGESTION_API_KEY="<api_key>"
export FAIL_SUGGESTION_API_BASE="https://<provider>/v1"
```

Pass Check:

```bash
export ENABLE_LLM_PASS_SUGGESTION=true
export PASS_SUGGESTION_MODEL="<model_name>"
export PASS_SUGGESTION_API_KEY="<api_key>"
export PASS_SUGGESTION_API_BASE="https://<provider>/v1"
```

It is recommended to use a model or API quota different from the main model to distinguish between verification execution and result review. The API parameters for Fail and Pass are configured independently; if using `launch.default_env` in `ucagent/setting.yaml`, sub-Agents can also inherit these variables.

The same configuration can be written into the project YAML:

```yaml
vmanager:
  llm_suggestion:
    check_fail_refinement:
      enable: true
      clss: ucagent.stage.llm_suggestion.OpenAILLMFailSuggestion
      args:
        model_name: "<model_name>"
        openai_api_key: "<api_key>"
        openai_api_base: "https://<provider>/v1"
        min_fail_count: 3
      bypass_stages: []
      target_stages: []
      default_apply_all_stages: true
    check_pass_refinement:
      enable: true
      clss: ucagent.stage.llm_suggestion.OpenAILLMPassSuggestion
      args:
        model_name: "<model_name>"
        openai_api_key: "<api_key>"
        openai_api_base: "https://<provider>/v1"
      bypass_stages: []
      target_stages: []
      default_apply_all_stages: true
```

The `enable` field in the configuration file can also use environment variable placeholders, for example `enable: $(ENABLE_LLM_FAIL_SUGGESTION: false)`. Do not write secrets into documentation, logs, or runtime snapshots.

## 2. When It Triggers

### Fail Refinement

When the Checker for the current stage returns a structured failure diagnosis, and Fail Refinement is enabled for that stage, UCAgent accumulates the count of consecutive failures. By default, the suggestion model is called only after 3 consecutive failures; before reaching the threshold, the regular Checker results are retained. A successful Check resets the consecutive failure count to zero.

The suggestion model receives the current stage task and failure report, and can use read-only inspection tools to read relevant files. It returns an `action` suggestion, and the Agent still needs to apply the suggested fix and re-run `Check`.

### Pass Check

When the Checker in the `Complete` path passes, and Pass Check is enabled for the current stage, UCAgent passes the stage task, check results, and stage Diff to the review model. The review model needs to:

- Return specific repair suggestions and reject approval if issues are found;
- Call `ApproveStagePass(pass_or_not=true)` if there are no issues.

If approval is not obtained, the stage will not proceed. Each Pass Check trigger results in a model call, so it is recommended to use it only for critical stages such as specification, coverage, test implementation, or Bug reporting.

## 3. Stage Filtering

Each suggestion configuration supports:

| Field | Function |
| --- | --- |
| `bypass_stages` | Always skips the listed stages; highest priority |
| `target_stages` | If non-empty, enables the feature only for the listed stages |
| `default_apply_all_stages` | Whether to apply to all stages when `target_stages` is empty; defaults to `true` |

The evaluation order is: first check `bypass_stages`, then `target_stages`, and finally `default_apply_all_stages`. You can also toggle LFail/LPass per stage on the running Agent page; stage-level settings override the global filtering results.

Example:

```yaml
check_pass_refinement:
  enable: true
  target_stages: [functional_specification_analysis, comprehensive_verification_and_bug_analysis]
  default_apply_all_stages: false
```

Stage names must use the `name` from the current configuration, not the page title or stage index.

## 4. Common Parameters

| Parameter | Applies To | Default | Description |
| --- | --- | --- | --- |
| `model_name` | Fail/Pass | None | Review model name |
| `openai_api_key` | Fail/Pass | None | API Key |
| `openai_api_base` | Fail/Pass | None | OpenAI-compatible API address |
| `min_fail_count` | Fail | `3` | Number of consecutive failures before calling the model |
| `summary_trigger_tokens` | Fail/Pass | Fail `32768`, Pass `65536` | Trigger threshold for conversation summary in the suggestion model |
| `summary_keep_messages` | Fail/Pass | `10` | Number of messages to retain after summarization |
| `ignore_labels` | Fail/Pass | `<think>...</think>` | Tag pairs to filter from suggestion text |
| `temperature`, `top_p` | Fail/Pass | Not set | Sampling parameters passed to the suggestion model |

## 5. Troubleshooting and Cost

- No suggestion output: First check `ENABLE_LLM_*_SUGGESTION`, the corresponding model variables, and the API address, then confirm that the current stage is not filtered out.
- Fail suggestion does not appear immediately: By default, 3 consecutive failures are required; you can adjust `min_fail_count`, but do not use it to mask unresolved Checker failures.
- Pass Check does not proceed: Check the review model's return value to confirm it called `ApproveStagePass(true)` when there were no issues; fix the issues and re-run `Complete`.
- Suggestion model calls increase latency and cost. Prioritize enabling it for critical stages, and set reasonable API timeouts and context summary thresholds.
- Regular Checker results are always the source of truth. LLM suggestions can only help locate issues; they cannot replace tests, source code, reports, or waveform evidence.

Configuration fields and default values are subject to the current version of `ucagent/setting.yaml`; to modify the implementation or add new review strategies, refer to `ucagent/stage/llm_suggestion/` and [Workflow Configuration](../03_develop/03_workflow.md).
