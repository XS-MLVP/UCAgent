---
name: spec-line-mapping
description: Atomically write one current Spec line-map batch from LLM-selected semantic mappings while enforcing canonical paths, ranges, reasons, and output-file identity.
---

# Spec Line Mapping

Use this Skill in the `design_spec_line_mapping` stage and prioritize the current `CurrentTips` batch. The LLM must read the returned source lines and decide which existing FG/FC/CK behavior each line describes, or provide a factual reason why a line has no DUT functional meaning. The script does not make that semantic decision. Canonical mappings already written for other batches are retained; the Checker independently validates them and counts every valid line block.

Submit the complete current source block in one call. Use the exact `file`, `start_line`, `end_line`, and `map_file` values returned by `CurrentTips`:

```text
RunSkillScript(commands=[["ext/design-with-ppa/spec-line-mapping", "write_line_map.py", "-SOURCE 'MyDUT/spec/interface.md' -START 1 -END 40 -MAP-FILE 'design/line_map/MyDUT_spec_interface_md_line_func_map.txt' -ITEMS '[{\"target\":\"FG-IF/FC-REQUEST/CK-ACCEPT\",\"ranges\":[[8,12]]},{\"target\":\"IGNORE/FC-DOC/CK-HEADING\",\"ranges\":[[1,1]],\"reason\":\"Document title; it does not specify DUT behavior.\"}]'"]])
```

Each item contains exactly `target`, `ranges`, and, for `IGNORE`, `reason`. A range uses inclusive physical line numbers. The script validates the canonical mapping filename, existing CK paths, current block boundary, source length, complete nonblank-line coverage, and concrete IGNORE reasons. It atomically replaces only mappings wholly inside the current block and preserves other completed blocks. It refuses partially overlapping existing ranges.

After the script succeeds, call `Check`. If the Checker reports a semantic mismatch, revise the selected target or reason and rerun the same block; do not alter the read-only Spec. After a passing Check, call `CurrentTips` for the next block.

When Skill support is disabled or this directory is absent, write the same canonical mapping manually using `Guide_Doc/dut_line_func_map.md`. The Checker and completion standard remain unchanged.
