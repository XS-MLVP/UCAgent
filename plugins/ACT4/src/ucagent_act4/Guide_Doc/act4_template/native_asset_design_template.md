
# Native asset design record

This completed example illustrates one Zba sh1add scenario, not the entire suite.
It is a design example, not execution evidence. For generation, adapt these sections into
reports/design_review.md. For review, use the same questions within the existing repair_plan;
do not create a second report. Replace source references with the inspected revision and lines.

## Scope and native route

Test sh1add on RV32 and RV64 without traps using the table-driven route.
Reuse the R formatter and the operand-edge cross; no new VM setup or priv generator is needed.
The authoritative inputs are testplans/Zba.csv and the ISA definition of sh1add_op.

## Rule, coverage and observability

| Rule | Coverage target | Stimulus | Observation | Defect distinguished |
| --- | --- | --- | --- | --- |
| sh1add_op | Zba_sh1add_cg/cr_rs1_rs2_edges | rs1=1, rs2=3, plus the native edge matrix | Destination value recorded through the native signature path; this simple pair yields 5 | An unshifted add yields 4; shifting rs2 instead yields 7 |

The named cross and rule mapping come from coverpoints/norm/Zba.yaml. The single pair above
explains the idea, not complete bin coverage. Inspect the actual formatter and generated cases
to confirm operand placement, XLEN truncation, aliases and observable signature updates.

## Implementation and configuration

Keep the CSV's existing register/edge requests and supported XLENs. Reuse native allocator,
formatter and signature helpers. Decode sh1add through the existing native decoder; if a
shared component changes, enumerate its other instruction/suite consumers before validation.
Generated headers require I and Zba, select the actual XLEN and use the corresponding march.
No runtime assembly loop or dependency on a previous generated file is needed.

## Verification and remaining evidence

No generation, compilation, model run or coverage measurement has been executed for this
illustration. A real run must record its native commands, output paths and results in the
workflow's existing evidence artifacts, then link them here. Check generated testcase labels
and descriptors, header selection, final self-checking ELF results and any coverage limitations.
Do not infer bin hits from filenames, static mappings or successful compilation.
