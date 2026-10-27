
# Custom Checker

A Checker is a deterministic gate for stages. After an Agent generates or modifies artifacts, you can call `Check` to receive feedback; a stage can only advance to `Complete` once all Checkers, referenced files, and output file gates pass. Checkers are responsible only for verifying facts and should not treat "appears complete" as a pass.

## When to Use a Custom Checker

Built-in Checkers are suitable for common Markdown, file, test, coverage, and batch task checks. When verifying business rules, you can write a custom Checker, such as:

- Documents must contain specified titles and fields;
- Generated configurations must reference existing files;
- Every test item in a batch must have a corresponding artifact;
- External commands must return success, and their output must meet explicit conditions.

Checkers should verify observable files, configurations, or command results. Do not rely solely on progress markers written by the Agent in documents, and do not relax test assertions just to allow a stage to pass.

## Lifecycle

When `VerifyStage` creates a Checker, it passes the `args` from the configuration and the current `cfg` to the constructor, then sets the workspace and stage. The Stage Manager injects these later; therefore:

1. `__init__` must call `super().__init__()` first, only storing parameters and creating lightweight objects;
2. Initialization depending on workspace, stage, Stage Manager, or file scanning should be placed in `on_init()`;
3. `do_check` performs real-time verification and returns `(bool, result)`;
4. `get_template_data()` can only return cached state and cannot scan files, advance batches, or write checkpoints;
5. Every overridden `do_check` must have a meaningful docstring, as it will be displayed in stage information.

Minimal structure:

~~~python
from pathlib import Path

from ucagent.checkers.base import Checker


class FileExistsChecker(Checker):
    """Check if the target file exists within the workspace."""

    def __init__(self, path: str, **kwargs):
        """Store the artifact path and optional human-review setting."""
        super().__init__()
        self.path = path
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def on_init(self):
        """Prepare cache state related to the stage."""
        return super().on_init()

    def do_check(self, is_complete=False, **kwargs) -> tuple[bool, object]:
        """Check the target file and return a pass result or structured diagnosis."""
        root = Path(self.workspace).resolve()
        target = (root / self.path).resolve()
        if Path(self.path).is_absolute() or not target.is_relative_to(root):
            return False, {
                "error_code": "INVALID_ARTIFACT_PATH",
                "error": "artifact path must be relative and remain inside workspace",
                "artifact": self.path,
                "next_action": "configure a workspace-relative artifact path",
            }
        if not target.is_file():
            return False, {
                "error_code": "FILE_MISSING",
                "error": f"required artifact is missing: {self.path}",
                "artifact": self.path,
                "expected": "a regular file",
                "next_action": "create the file, then call Check again",
            }
        return True, {"artifact": self.path}
~~~

`get_path` is used to append relative paths to the workspace but cannot replace full boundary checks. When receiving variable paths, you should resolve the real path as in the example above and confirm it remains within the workspace, including symbolic links pointing to targets.

## Configuring a Checker

Stage configuration specifies the class via `clss`, passes `args` to the constructor, and sets `extra_args` after instantiation via `set_extra`. Short names are exported from `ucagent.checkers`; custom classes use the full import path:

~~~yaml
stage:
  - name: generate_documentation
    desc: "Generate project documentation"
    task:
      - "Read project materials and write documentation"
    output_files:
      - "{OUT}/{DUT}_documentation.md"
    checker:
      - name: required_sections
        clss: "examples.MiniWorkflow.my_checkers.RequiredSectionsChecker"
        args:
          file_path: "{OUT}/{DUT}_documentation.md"
          required_sections:
            - "Project Overview"
            - "Function Description"
          need_human_check: false
~~~

`args` in the configuration are automatically augmented with the current `cfg`; custom constructors receive it or other optional parameters via `**kwargs`. List fields are replaced entirely at each level, so when copying configuration, write out the full Checker list.

## Diagnosis Results

Return a concise result on pass. On failure, if a fix method can be determined, return a bounded structured diagnosis containing at least:

- `error_code`: a stable machine-readable code;
- `error`: the specific issue;
- `next_action`: the next step to execute, such as a fix or tool call;
- `artifact`, `location`, `observed`, `expected`: provide these when helpful, keeping content bounded.

~~~python
return False, {
    "error_code": "DOCUMENT_TOO_SHORT",
    "error": "the document contains 450 words; at least 500 are required",
    "artifact": "unity_test/Adder_analysis.md",
    "observed": {"word_count": 450},
    "expected": {"minimum_word_count": 500},
    "next_action": "add at least 50 words of relevant content, then call Check",
}
~~~

If the result needs to retain the original command output, place the bounded diagnosis in the `diagnostic` field and limit the raw output to a reasonable size. Do not guess failure summaries from ordinary `error`, `details`, `STDOUT`, or `STDERR` fields; stage management will retain raw results without complete diagnoses. Callers can pass `{"full_output": true}` in `stage_args` to request the raw result simultaneously.

The `is_complete` parameter in `do_check` distinguishes intermediate `Check` from final `Complete`. Do not declare all batches complete prematurely in `Check`, and do not treat intermediate progress as final verification.

## Batch Checker

When processing test cases, features, or line mappings in batches, use `UnityChipBatchTask` instead of writing separate checkpoints and batch state machines:

`UnityChipBatchTask` is imported from `ucagent.checkers.base`. After completing input and artifact validation and synchronizing the task list, call:

~~~python
return self.batch_task.do_complete(
    note_msg=[],
    is_complete=is_complete,
    fail_source_msg="generate artifacts for the missing source items",
    fail_gen_msg="remove generated items that are absent from the source",
    exmsg="read the current batch details before continuing",
)
~~~

This call is used within an existing batch Checker's `do_check` and cannot replace source data scanning and artifact validation. Actual implementation also requires:

- Setting `batch_size` before constructing `UnityChipBatchTask`;
- Preserving and synchronizing `source_task_list`, `gen_task_list`, `tbd_task_list`, and `cmp_task_list`;
- Treating source files as the source of truth, using checkpoints only for recovery;
- Removing or marking tasks as expired when source data changes; unknown, duplicate, or forged progress must fail;
- Completing batch transitions with `do_complete()`, which saves progress and resets the consecutive failure count upon batch pass;
- Returning clear diagnoses for empty source lists, invalid paths, and incomplete artifacts.

Function line mapping also requires `file_list` to be a unique set of files, not treating `Guide_Doc` as a mapping target; every non-empty physical line must have FG/FC/CK or a justified `IGNORE`, with a maximum of 100 lines per mapping block.

## Human Review and Stage Gates

A Checker can request human review via `set_human_check_needed(True)`; this causes the stage to wait for human operation after the Checker passes. Stage `reference_files`, `output_files`, and skill gates are handled uniformly by the Stage Manager, so Checkers should not reimplement these gates.

Skill gates only take effect when skill support is enabled and the current stage's `skill_list` is non-empty. Setting `force_use_skill: false` makes skills optional for that stage; `general_skill_list` does not enter stage-mandated gates. When skills are disabled, Checkers must still be able to perform the same verification using ordinary tools and existing artifacts.

## Test Custom Checkers

Must cover:

- File not found, empty files, and format errors;
- Normal input, boundary values, and invalid input;
- Workspace path boundaries;
- Completeness and bounded content of diagnostic fields;
- Synchronization behavior of batch tasks after adding, removing, or modifying source data.

See the repository for a runnable minimal implementation at
[examples/MiniWorkflow/my_checkers.py](https://github.com/XS-MLVP/UCAgent/blob/main/examples/MiniWorkflow/my_checkers.py).
For complete tool and workflow examples, see [Custom Development Intro](01_quick_start.md), [Workflow Configuration](03_workflow.md), and
[Mini Example](08_mini_example.md).
