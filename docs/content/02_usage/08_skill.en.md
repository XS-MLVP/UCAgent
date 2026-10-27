
# Skill SKILL

Skills bundle reusable task methods, scripts, and reference materials into a single directory. The Agent first lists available skills and then reads `SKILL.md` on demand, avoiding loading all instructions into the context at once. Skills are used to accelerate and guide tasks; when skills are disabled, the workflow must still provide complete task instructions, tool paths, and the same Checker acceptance criteria.

## Enabling and Configuration

Built-in configuration enables skills by default; if no CLI switch is passed, the `skill.use_skill` value in the hierarchical configuration takes precedence. You can explicitly override this:

```bash
ucagent <workspace> <DUT> --use-skill
ucagent <workspace> <DUT> --no-use-skill
```

You can disable it in the configuration file:

```yaml
skill:
  use_skill: false
```

`--extra-skill-path <path>` appends custom skills and enables skill support; it cannot be used simultaneously with `--no-use-skill`. During initialization, skills are copied to the workspace `.ucagent/skills/`, with additional skills located in the `ext/` subdirectory. Tools read and execute the workspace copies; after modifying skills in the source code, you must restart and re-copy them to use the new content.

## Stage Skills and General Skills

Example stage configuration:

```yaml
stage:
  - name: static_analysis
    desc: "Analyze static defect candidates"
    task:
      - "Read source code and requirements, complete static analysis according to Guide_Doc/dut_bug_analysis.md"
    skill_list:
      - unitytest/static-bug-analysis
    force_use_skill: true
```

| Configuration | Usage Requirement |
| --- | --- |
| Skills enabled and stage `skill_list` is non-empty | Forced by default; usage evidence must be satisfied before `Complete` |
| Stage sets `force_use_skill: false` | Stage-specific skills are optional |
| `skill_list` is unconfigured or empty | `SetSkillUsage` is not required; stage skill gate is not enforced |
| `skill.general_skill_list` | General skills are always optional |
| Skills globally disabled | All stage skill gates are disabled; other acceptance requirements are executed as usual |

The skill gate applies to `Complete` and does not block intermediate `Check` calls. Disabling skills should not block tasks due to the absence of `.ucagent/skills/`.

## Usage Flow and Evidence

Mandatory stage skills are used in the following order:

1. Call `ListSkill` to list currently available skills.
2. Use UCAgent's `ReadTextFile` to read the returned workspace `SKILL.md` path.
3. Execute the task according to the skill method; if scripts are needed, execute them via `RunSkillScript`.
4. Call `Check` to verify the current artifact.
5. After the current `Check` passes, call `SetSkillUsage` to confirm usage.
6. Call `Complete` to finish the stage.

`ListSkill` and `ReadTextFile` generate real list/read records respectively; `RunSkillScript` registers script usage only after the entire call succeeds. `SetSkillUsage` cannot fabricate these records via model declaration. It can confirm executed text methods only after both list/read records and a currently passing `Check` are present.

When a method has been applied, the tool parameters for `SetSkillUsage` are as follows:

```json
{
  "skill_usage": {
    "unitytest/static-bug-analysis": {
      "list": true,
      "read": true,
      "use": true
    }
  }
}
```

If the current stage has no objects for skills to process, after executing its no-applicable-objects branch and passing `Check`, submit `use: false` and a non-empty `reason` explaining the specific cause. This reason cannot replace list/read, skip the current check, or override an observed `use: true`; nor can it be used to fabricate bugs or artifacts to satisfy the skill gate. Do not fill in `reason` when `use: true`.

## Related Tools

| Tool | Purpose |
| --- | --- |
| `ListSkill` | Returns names, descriptions, `SKILL.md` paths, and script paths for current stage-specific skills and available general skills |
| `ReadTextFile` | Reads skill content and registers reading evidence |
| `RunSkillScript` | Executes listed skill scripts sequentially; registers usage only if all succeed |
| `SetSkillUsage` | Validates and saves evidence for current stage-specific skills |

`ListSkill` prioritizes listing all stage skills, then supplements with general skills limited by `skill.max_skill_list_count`; stage skills are not truncated by this limit. Skill identifiers are paths relative to the workspace skill root directory, e.g., `unitytest/static-bug-analysis`.

`RunSkillScript.commands` is a non-empty array, where each item is a tuple of three strings: `[skill_name, script_filename, args]`. Script names do not include directories or runners. Assuming a custom skill `example/analysis` has listed the script `analyze.py`, the call format is:

```json
{
  "commands": [
    ["example/analysis", "analyze.py", "--input 'input.md'"]
  ]
}
```

Prefer passing nested JSON arrays. Scripts are executed in order; if any fails, execution stops. File modifications already executed are not automatically rolled back, and a failed entire call does not register script usage for that attempt.

## Skill Directory and Metadata

```text
analysis/
├── SKILL.md
├── scripts/                  # Optional
│   ├── analyze.py
│   ├── __init__.py           # Optional stage hook
│   └── script_runner.json    # Optional runner mapping
└── references/               # Optional auxiliary materials
```

The first line of `SKILL.md` must be `---` directly, and the frontmatter must include at least `name` and `description`:

```markdown
---
name: analysis
description: Analyze input materials, generate and check results according to project conventions
metadata:
  category: analysis
---

# Analyze Input Materials

## Objectives and Inputs

List applicable tasks, input files, and prerequisites.

## Execution Steps

Describe which materials to read, how to analyze, when to call scripts, and how to verify.

## Output and Acceptance

Describe allowed write paths, complete artifact formats, and remediation steps after failure.
```

- `name`: No more than 64 characters, using only lowercase letters, digits, and hyphens, and must satisfy naming validation.
- `description`: Describes applicable tasks, up to 1024 characters; excess content is truncated. The description helps the Agent select skills but does not automatically trigger scripts.
- `metadata`: Optional string key-value mapping; keys and values are converted to strings at runtime.

The body must provide executable steps and real script parameters. Mandatory format and evidence rules must also be available in stage tasks, Guide_Doc, and templates to avoid losing acceptance criteria when skills are disabled.

## Script Execution Environment

Script processes use the DUT workspace as the current directory. `RunSkillScript` uses `shlex` to split arguments, then launches the process with the runner and argv, with `shell=False`; do not rely on pipes, redirection, or shell variable expansion.

- `.py` files use the Python interpreter running UCAgent; `.sh` and `.bash` files use Bash.
- Other scripts specify a single executable program in `scripts/script_runner.json` as `{"filename": "executable"}`; runner arguments are not allowed.
- Environment variables `DUT` and `OUT` come from the resolved configuration in `.ucagent/runtime_config.json`.
- `RunSkillScript` reads `ucagent_python_path` from the snapshot, places it at the beginning of the subprocess `PYTHONPATH`, deduplicates, and preserves other import paths.

Python skill scripts that need to import `ucagent` must be executed via `RunSkillScript`. Scripts should use `load_runtime_config(workspace)` to read runtime configuration; do not re-interpret original functional environment variables or guess the UCAgent source directory from the copied script location. If import paths in the snapshot are missing, non-absolute, or invalid, restart UCAgent to regenerate the snapshot.

## Stage Hook (Advanced)

Skills can provide `setup_vstage(stage)` in a non-empty `scripts/__init__.py`, wrapping existing methods of the current stage via `stage.add_hook(method_name, hook_func)`. Skills in both stage-specific `skill_list` and `skill.general_skill_list` participate in hook loading and are deduplicated.

Hooks only affect the current stage instance. Registration must remain idempotent to avoid hidden operations during import; also, do not place mandatory behavior only in hooks, which would prevent task completion if skills are disabled.

When developing and testing skills, verify at least three scenarios: enabled, disabled, and missing skill directory. See [Workflow Configuration](../03_develop/03_workflow.md) for configuration methods in workflows, and [Custom Tools](../03_develop/05_customize.md) for tool and path policies.
