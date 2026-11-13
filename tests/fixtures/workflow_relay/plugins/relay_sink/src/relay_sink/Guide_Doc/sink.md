
# Relay sink artifact

Read inputs/payload.json and Guide_Doc/sink.md. Write value+1 and source_sha256 from CurrentTips.handoff_inputs into result_b/result.json.

Only integer values are accepted; booleans and extra or missing fields fail.
The input operation must be `increment`. Preserve the input file unchanged.

## Complete example

For input bytes `{"value": 7, "operation": "increment"}` (no trailing newline),
the complete `result_b/result.json` is:

```json
{"value": 8, "source_sha256": "1b58b6620fe6c9f8b3ba5427f71e14357f7810fed05cbf3fe5a10a10450ab5d7"}
```

Use the actual input values and digest for each run. Read this guide, record the
stage journal, run Check and submit only after the artifact passes.
