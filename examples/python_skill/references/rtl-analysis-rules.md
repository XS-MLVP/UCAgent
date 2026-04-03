# RTL Analysis Rules

Use this guide before the verification execution flow when the user gives you RTL instead of a ready-made `*_functions_and_checks.md`.

## Input assumptions

The user provides RTL.
The project may include:

- Verilog / SystemVerilog
- Chisel / Scala source used to explain design intent
- multiple plausible top modules

The skill analyzes these inputs but does not own RTL generation.

## Required front-half outputs

Before execution, produce draft artifacts that cover:

- default top candidate
- ranked alternative top candidates
- top-selection reasoning
- draft `FG/FC/CK`
- draft verification plan
- initial test skeleton suggestions
- risks and open questions

## Top-candidate rules

Always provide:

- one default top candidate
- a ranked candidate list
- explicit reasons for the ranking

Do not pretend certainty when the structure is ambiguous.

## Chisel / Scala usage rule

Treat Chisel / Scala as design-intent evidence.
Use it to understand:

- naming and grouping intent
- module roles
- interface structure
- clock / reset semantics

Do not assume the skill must generate RTL from Chisel.

## Draft quality rules

- Keep draft `FG/FC/CK` names stable and machine-readable.
- Do not hide uncertainty.
- Keep the draft file close enough to the final `*_functions_and_checks.md` shape that it can be finalized after review.
- Mark missing knowledge as risks or questions, not as fake certainty.

## Hard stop rules

Stop at review and do not continue to execution if:

- top-level identity is still materially ambiguous
- clock / reset interpretation is unclear
- interface grouping is unstable
- placeholder draft content has not been replaced
