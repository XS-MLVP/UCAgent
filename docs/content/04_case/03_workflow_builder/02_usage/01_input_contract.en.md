
# Input Contract

The business inputs for Workflow Builder reside in the `input/` directory under the business root. This directory is maintained by the user, and the Makefile copies it to `workspace/input/` in the build workspace upon startup. The copied workspace inputs represent a snapshot of the current run; modifying the source inputs requires restarting the relevant workflow to ensure consistency.

## Required Structure

```text
<business-root>/
└── input/
    ├── guide.md
    └── test_input/
```

`guide.md` is the single fixed entry point. `test_input/` must be a directory that can contain multiple files and subdirectories; its contents should represent a minimal but complete real-world business case.

## Contents of guide.md

1. Workflow objectives and explicitly excluded actions.
2. Paths, formats, required fields, and constraints for each user input.
3. Paths, formats, and acceptance criteria for each public output.
4. Expected stages, parameters, results, exceptions, and examples for tools.
5. Expected check objects, evidence, pass/fail conditions for the Checker.
6. Runtime environment, Python dependencies, and system dependencies.
7. Requirements for user documentation and developer documentation.
8. Whether independent evaluation workflows, incremental workflows, and a knowledge base directory are required.

Requirements should not pre-ask the user to generate testbenches, configurations, Checker code, or tool source code; these are capabilities that the workflow should generate automatically. Users provide business code, descriptions, verification requirements, assets, and knowledge.

## test_input Design

Samples must cover primary paths without being large enough to slow down every regression. Filenames, extensions, and directory levels must align with future `input/<TARGET>/`. If the real business allows optional files, both samples and requirements must specify behavior when they are missing, avoiding the generation of Checkers that force all optional fields.

Binary assets should be small, publicly shareable files; text should use UTF-8. Do not include tokens, private certificates, customer data, oversized media, or links that require external network access to resolve.

## res Knowledge Base

User knowledge used for evaluation and incremental processing resides in the `res/` directory within the build workspace, not as a replacement for the source `input/`. Typical content includes domain acceptance rules, known tool limitations, organizational standards, and user judgment. The initialization program creates structured files; the Agent can only read or access via allowed structured tools, not fabricate user knowledge.

## Input Changes

Modifying `guide.md` during the build causes inconsistencies between the requirements list, plan, and generated specs. Major changes should stop the current run, save necessary reports, and then rebuild from a clean workspace. Minor fix requests, after the workflow has generated outputs, should be prioritized via user suggestions and incremental workflows.

## Input Self-Check

```bash
test -f <business-root>/input/guide.md
test -d <business-root>/input/test_input
find <business-root>/input -type l -print
```

It is not recommended for inputs to contain symbolic links pointing outside the business root. Example paths in requirements should use relative business paths, avoiding absolute paths specific to a particular machine.

## Recommended Requirements Template

```markdown

# <Business Name> Workflow Requirements

## User Goals and Exclusions

## Input File Contract

## Public Output Contract

## Processing Stages and Data Flow

## Tool Requirements

## Checker and Acceptance Evidence

## Environment and Dependencies

## User Documentation and Developer Documentation

## Evaluation, Incremental, and Knowledge Base

```

Each file contract should specify relative paths, format versions, encoding, top-level structure, required fields, allowed sizes, and error handling. Directory inputs should specify whether they are recursive, allowed extensions, sorting rules, and behavior for empty directories. Binary inputs should specify the parsing library and behavior for corrupted files.

Tool requirements are not requests for users to write source code, but rather descriptions of business capabilities. Checker requirements should specify what evidence is used for judgment, not just "check results." The first stage of the parent workflow should expand these contents into an implementation-level plan; conservative inferences must be recorded as design decisions and cannot be disguised as user requirements.

Domain requirements in `res/` should indicate scope and source. The evaluation Agent can read them but cannot modify them to favor its own conclusions. After the run begins, it is recommended to record the `guide.md` and sample tree revision; if inputs change during the build, the process should stop and choose to rebuild or proceed with incremental updates.
