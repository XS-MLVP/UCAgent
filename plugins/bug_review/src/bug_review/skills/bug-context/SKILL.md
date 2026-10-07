---
name: bug-context
description: List one Bug's original claim, linked cases, waveform receipt references, Spec, RTL and current decision without reading the full source reports.
---

# Bug Context

Use the exact `bug_id` from `{OUT}/review_index.json`. Original-claim sections become available after `dut_evidence`; earlier stages may request only `cases` or `waveform`. Call `ReviewBugContext(bug_id="<bug_id>")`. Optional `sections`, `max_lines`, `max_chars`, `case_offset`, and `ref_offset` arguments select bounded context. `claims` returns original overview, symptoms and trigger text with exact line spans. The trigger and symptoms provide scenario and observed-behavior candidates; expected behavior remains `needs_review` with an overview line reference when the text does not separate it reliably. The tool enforces a total response budget and reports truncation. Use `WaveInfoReceipts(receipt_id="...", include_result=true)` for the signed waveform timeline; this Skill does not recreate it. A missing source reference or record must be corrected in the index or reported as missing evidence.
