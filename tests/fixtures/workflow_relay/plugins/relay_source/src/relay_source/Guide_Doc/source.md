
# Relay source artifact

Read inputs/request.json and Guide_Doc/source.md. Copy the exact value and operation into result_a/payload.json.

Only integer values are accepted; booleans and extra or missing fields fail.
The input operation must be `increment`. Preserve the input file unchanged.

## Complete example

For input bytes `{"value": 7, "operation": "increment"}` (no trailing newline),
the complete `result_a/payload.json` is:

```json
{"value": 7, "operation": "increment"}
```

Use the actual input values and digest for each run. Read this guide, record the
stage journal, run Check and submit only after the artifact passes.
