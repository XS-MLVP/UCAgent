
# Plugin Development and Release

UCAgent plugins are designed for independent delivery of domain capabilities. A single plugin may provide one or more of the following capabilities as needed: Tool, Checker, Skill, Guide_Doc, and workflow. These contributions are all first-level options, independent of one another, and do not require the plugin to provide a complete workflow. Plugins are standard Python distributions: they are automatically discovered via standard entry points after installation, and can also be discovered via explicitly configured search paths during source development. Plugins are imported and activated only after being selected by the user; UCAgent does not scan or execute arbitrary workspace Python files.

The `plugins/RTL2Spec/` directory provides a documentation generation plugin; `plugins/DesignWithPPA/` demonstrates combinations of custom Tools, Checkers, templates, Skills, and workflows.

## Co-located Optional Plugins

The `plugins/` directory is used to maintain plugins developed alongside UCAgent and packaged independently. Installing the core package does not install or enable these plugins. Plugin development should be confined to their own directories: dependencies, entry points, configurations, resources, tests, and maintenance commands are managed by the plugin itself, without adding plugin content to the core's dependency list, default configurations, or Tool/Checker export tables.

| Content | Maintenance Location |
| :--- | :--- |
| Plugin API, loading mechanism, license, copyright notices, general contribution process, and vulnerability reporting channels | UCAgent core and repository root directory |
| Manifest, packaging configuration, dependencies, implementation, workflows, resources, and tests | Individual plugin directories |
| Plugin-specific ignore rules, editing conventions, file attributes, and usage/maintenance instructions | Individual plugin directories, inheriting repository-wide rules |
| Core and repository public CI | Root directory `.github/workflows/` |
| Plugin installation, verification, packaging, and installed-state test commands | Scripts or Makefiles in plugin directories |

Subdirectory `.gitignore`, `.editorconfig`, and `.gitattributes` files do not represent independent repositories and are not required for plugin execution; retain them only based on actual maintenance needs to avoid spreading plugin-specific rules across the entire repository. Plugin maintainers use the same UCAgent commit to execute plugin verification locally; adding new plugins does not require adding root directory CI workflows. Only when public plugin interfaces or repository-level infrastructure change should corresponding core files be synchronized.

The current co-located plugins are listed below. See the corresponding README for runtime dependencies, examples, and maintenance commands for each plugin:

| Project | Plugin ID / Workflow | Primary Purpose |
| :--- | :--- | :--- |
| [DesignWithPPA](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/DesignWithPPA/README.md) | `design-with-ppa:unit-design-tdd` | Test-driven RTL design and PPA optimization |
| [RTL2Spec](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/RTL2Spec/README.md) | `rtl2spec:xiangshan-design-document` | Deliver Chinese design and functional checkpoint documentation based on XiangShan source and RTL generation evidence |

First install the core, then install plugins on-demand from the UCAgent repository root, for example:

```bash
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

Explicitly select `--plugin rtl2spec` and `--plugin-workflow rtl2spec:xiangshan-design-document` at runtime. During source development, you can replace the plugin ID with `--plugin ./plugins/RTL2Spec`; no prior installation of the plugin is required. The workspace is independent of the plugin implementation; selected workflows automatically locate and copy accompanying guide documents and other resources.

### Repository Policy and Plugin-Specific Notes

Co-located plugins use the root directory's `LICENSE`, `NOTICE.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`. General contribution processes, code of conduct, and vulnerability reporting channels are maintained only in the root directory; plugins reference these via links, requiring no duplicate files in each plugin. CLA and CCLA terms also follow repository conventions. License and attribution statements attached to third-party code or assets must still be retained.

Plugin-specific content remains in the plugin directory: `README.md` introduces installation and usage only; implementation structure, tests, and packaging commands are written to `docs/development.md`. Workflow details, tool interfaces, and troubleshooting content are placed in `docs/` as needed. Plugin-specific technical notes are not written into the repository's general policy files.

### Licenses in Distribution Packages

Co-located plugins adopt the Apache-2.0 license from the root directory `LICENSE`; distribution package metadata must remain consistent with this. The source repository maintains only the root directory license and copyright notices; during the setuptools build process, the plugin's `setup.py` copies the root directory `LICENSE` and `NOTICE.md`, which are cleaned up after the build completes. The sdist includes these two files and build scripts; when building a wheel from an unpacked sdist, the bundled copies are used without accessing the UCAgent repository. The wheel stores the copies in `.dist-info/licenses/`. Actual examples are provided in the `setup.py` of RTL2Spec and DesignWithPPA.

Declare in the plugin's `pyproject.toml`:

```toml
[project]
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE.md"]
```

Paths in `license-files` are relative to the plugin project directory and cannot be written as `../../LICENSE`. Files must be prepared before setuptools reads project configuration, supporting standard installation, editable installation, and source distribution rebuild. Before release, verify that text in sdist and wheel matches the root directory files byte-for-byte; do not maintain a second copy of the license manually.

## Naming Conventions

A plugin typically has four names serving directory, Python packaging, plugin selection, and code import respectively:

Co-located plugin project directories are recommended to use PascalCase (camel-up), such as `DesignWithPPA` and `RTL2Spec`. This is a directory style convention; the loader does not depend on directory name casing.

| Level | DesignWithPPA Example | RTL2Spec Example | Purpose |
| :--- | :--- | :--- | :--- |
| Project Directory | `DesignWithPPA` | `RTL2Spec` | File system path |
| Distribution Name | `ucagent-design-with-ppa` | `ucagent-rtl2spec` | pip installation and distribution metadata |
| Plugin ID | `design-with-ppa` | `rtl2spec` | entry point, manifest, CLI selector |
| Python Package Name | `design_with_ppa` | `rtl2spec` | Python `import` path |

The Plugin ID must match `^[a-z0-9]+(?:[._-][a-z0-9]+)*$`: use lowercase letters and numbers, with separators `-`, `_`, and `.` appearing only between non-empty segments. IDs must remain unique within the same Python environment and single UCAgent run. Plugins should not retain compatibility entry points for deprecated names, as this can cause ambiguity in discovery results and configuration.

The manifest `name`, the key and provider in the `ucagent.plugins` entry point, and the `Plugin.name` returned by the provider must be completely consistent. The manifest `entry` and the value of the entry point should also point to the same provider. Project directories and Python package names need not match the Plugin ID literally; casing in documentation examples and the `ucagent-` prefix are not additional loading rules. `--plugin` accepts Plugin IDs or project paths, but cannot be replaced by distribution names or Python package names. Workflow names follow the same ID character rules, are unique within their parent plugin, and are selected as `<Plugin ID>:<Workflow Name>`.

## Standard Project Structure

```text
DesignWithPPA/
├── ucagent-plugin.toml
├── pyproject.toml
├── README.md
├── Makefile
├── cases/
├── scripts/
├── src/
│   └── design_with_ppa/
│       ├── __init__.py
│       ├── plugin.py
│       ├── ppa.py
│       ├── assets/
│       ├── checkers/
│       ├── workflows/
│       ├── Guide_Doc/
│       ├── templates/
│       └── skills/
└── tests/
```

Create only actual resource directories for release. Pure Tool, pure Checker, pure Skill, pure Guide_Doc, or pure workflow plugins are all valid. Additional contributions can be added in the same distribution later without modifying the UCAgent core package. Runtime scripts can be placed in `scripts/` within the package; test and maintenance configurations belong in the plugin project root. Co-located plugins follow the same structure, with the project root located at `plugins/<Project Directory>/`. The loader locates the project via the manifest, independent of the parent directory name. The standard structure does not require empty directories to be retained.

## Local Source Manifest

The source project root must include `ucagent-plugin.toml`:

```toml
schema_version = 1
name = "design-with-ppa"
entry = "design_with_ppa.plugin:get_plugin"
python_path = "src"
```

The manifest allows only these four fields:

- `schema_version`: must be `1` for the current version;
- `name`: the stable Plugin ID, must match `Plugin.name` returned by the provider exactly;
- `entry`: the provider in `module.path:provider` format;
- `python_path`: the Python import root relative to the project root.

The manifest and `python_path` are used only for local source loading. Installed wheels use distribution entry points and do not depend on the local manifest, though the same project manifest can be retained in the wheel for source development and review.

## Installed Automatic Discovery

The plugin's `pyproject.toml` must register the `ucagent.plugins` entry point:

```toml
[project]
name = "ucagent-design-with-ppa"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
  "UCAgent>=26.9.2.dev14",
  "vcdvcd>=2.3.5,<3.0.0",
]

[project.entry-points."ucagent.plugins"]
design-with-ppa = "design_with_ppa.plugin:get_plugin"
```

Both the core and plugin must be installed in the same Python environment. Install the core first according to UCAgent instructions, then install the plugin's local directory, wheel, or published distribution package; do not assume the example package is published on PyPI. `requires_ucagent` and the distribution package's UCAgent dependency ranges should be consistent, using the lower bound of a version verified in practice.

After installation, Python's distribution metadata provides discovery information. For example, run from the UCAgent root directory:

```bash
python3 -m pip install ./plugins/DesignWithPPA
ucagent --list-plugins
ucagent --validate-plugin design-with-ppa
ucagent <workspace> <dut> --plugin design-with-ppa
```

`--list-plugins` reads only entry point names and the local manifest, without importing the provider. `--validate-plugin` imports the selected provider and verifies the plugin API, UCAgent version, Python dependencies, external commands, and resources. UCAgent does not automatically install dependencies at runtime; missing items are returned as actionable errors.

## Source State Configuration Search

When no plugins are installed, add `plugin.search_paths` in any valid configuration layer:

```yaml
plugin:
  search_paths:
    - "/opt/ucagent-plugins"
    - "{WORKSPACE}/local-plugins"
```

This field must be a string list, processed through normal configuration layering and `{WORKSPACE}` template resolution. Each path may:

- Directly point to a plugin project containing `ucagent-plugin.toml`;
- Point to a collection directory containing multiple plugin projects, where UCAgent checks only its immediate subdirectories.

Paths must exist; full directory tree recursion is not performed. Upon discovery, only the strict manifest is read, and a provider is imported only after an exact match on `name`. If an installation entry point and a search path share the same ID, startup will list both the installed distribution and the local manifest path with an ambiguity warning; silent selection based on source priority is not permitted.

Relative search paths are relative to the current working directory when UCAgent is started. For user-level or workspace configurations requiring cross-directory stability, use absolute paths or the `{WORKSPACE}` template.

To force debugging of a specific source copy, pass the project path directly:

```bash
ucagent --validate-plugin /opt/ucagent-plugins/DesignWithPPA
ucagent <workspace> <dut> \
  --plugin /opt/ucagent-plugins/DesignWithPPA
```

Example using stable IDs for configuration:

```bash
ucagent --config config.yaml --list-plugins
ucagent <workspace> <dut> \
  --config config.yaml \
  --plugin design-with-ppa
```

The configuration list is processed according to UCAgent's overall replacement semantics. When workspace configuration overrides user configuration, write out the complete expected search path list.

## Provider and Runtime Context

A Provider returns `ucagent.plugins.Plugin`:

```python
from pathlib import Path

from ucagent.plugins import CommandRequirement, Plugin, PluginContext

from .checkers import TimingBudgetChecker
from .my_tool import MyTool


def create_tools(context: PluginContext):
    return [
        MyTool(
            workspace=str(context.workspace),
            output_dir=context.output_dir,
            write_dirs=list(context.write_dirs),
            un_write_dirs=list(context.un_write_dirs),
        )
    ]


def get_plugin():
    root = Path(__file__).resolve().parent
    return Plugin(
        name="design-with-ppa",
        version="0.2.0",
        description="Pre-layout PPA analysis and design workflows.",
        root=root,
        tool_factories=(create_tools,),
        checkers=(TimingBudgetChecker,),
        guide_doc_paths=(root / "Guide_Doc",),
        skill_paths=(root / "skills",),
        requires_ucagent=">=26.9.2.dev14",
        python_requirements=("vcdvcd>=2.3.5,<3.0.0",),
        command_requirements=(
            CommandRequirement("Yosys", ("yosys",)),
            CommandRequirement("OpenSTA", ("sta", "opensta")),
        ),
        assets=(root / "assets" / "reference.lib",),
    )
```

All `Plugin` capability fields default to empty:

| Field | Contribution Contract |
| :--- | :--- |
| `tool_factories` | Creates one or more `UCTool` instances; does not depend on workflows |
| `checkers` | Registers one or more `Checker` subclasses; does not depend on Tools or workflows |
| `guide_doc_paths` | Includes runtime `Guide_Doc` files or directories when the plugin is activated |
| `skill_paths` | Copies the Skill collection directory when the plugin is activated and Skill functionality is enabled |
| `workflows` | Optional complete configuration entry points and workflow-specific resources |

All capability fields are allowed to be empty, facilitating the initial release and validation of plugin metadata, dependencies, and asset contracts before gradually adding capabilities. Actual release versions should provide at least one capability or asset useful to the user.

`PluginContext` is passed to the tool factory after configuration parsing and contains:

| Field | Contract |
| :--- | :--- |
| `workspace` | Absolute `Path` of the current workspace |
| `output_dir` | Relative output directory within the workspace |
| `write_dirs` | Tuple of final resolved writable directories |
| `un_write_dirs` | Tuple of final resolved non-writable directories |
| `cfg` | Final resolved, frozen UCAgent configuration; must not be written to logs or reports in whole |
| `plugin_root` | Absolute `Path` of the current plugin provider package directory |

Tools must inherit `UCTool`, use `Pydantic` `BaseModel` as `args_schema`, and adhere to workspace path and read/write strategies. A factory may return a single tool or a list of tools. UCAgent will reject non-`UCTool` instances, tools with duplicate names across plugins, and tools sharing names with core or external tools. Plugin tools enter the same standard filtering process as Agent and MCP tools; therefore, both `tools.ignore_tools` and `tools.selected_tools` will take effect.

## Checker

Each item in `checkers` must be a subclass of `ucagent.checkers.base.Checker`. After activating a plugin, any valid configuration file can reference it by its short name, regardless of whether the configuration belongs to the plugin's workflow:

```yaml
stage:
  - name: timing_budget
    desc: Check the timing budget
    task: []
    checker:
      - name: timing_budget_check
        clss: TimingBudgetChecker
        args: {}
```

UCAgent explicitly passes the plugin Checker registry to the stage parser, without writing the class to the global `ucagent.checkers` module. Checker class names must be unique across all activated plugins and cannot match core Checker names. Full dotted paths can still be used for regular importable classes, but formal `checkers` declarations provide startup type checking, short-name referencing, conflict detection, and plugin summaries.

### Isolated Execution Code Generation

Checkers must not import or execute workspace-generated Python modules in the UCAgent main process. When verifying Python DUTs, coverage definitions, test configurations, or other generated code, use `RunTestCases`; if checking structures obtainable only via execution is required, use a subprocess with timeouts, output limits, and side-effect isolation.

When starting an isolated subprocess with `python -I`, do not rely on `PYTHONPATH`: the isolated mode ignores this environment variable. The parent process must explicitly pass trusted import roots to the subprocess, which must add them to `sys.path`. These roots must include at least:

- The precise UCAgent import root derived from the currently loaded `ucagent` package location;
- The current running source plugin import root;
- The target generated module directory and workspace, added only after the above trusted runtime paths.

Import order is part of the safety contract. The current UCAgent root must precede the workspace to prevent a similarly named `ucagent` package in generated directories from shadowing the running implementation. Do not guess the UCAgent path from the current directory name, repository name, environment variables, or another installed distribution; source runs, editable installs, and wheel installs must all resolve to the same running package.

Testing for such Checkers must simultaneously prove: the source plugin can import the current UCAgent in an isolated subprocess; the target module does not appear in the parent process's `sys.modules`; modifications to environment variables, module global state, and bytecode in the subprocess do not pollute the main process or workspace; and import failures, timeouts, and excessive output return bounded diagnostics.

## Independent Guide_Doc and Skill

`guide_doc_paths` and `skill_paths` are plugin-level contributions that take effect upon selecting the plugin, without requiring the selection of `--plugin-workflow`. A `Guide_Doc` may declare a single file or directory; `Skill` paths must be collection directories containing at least one valid `SKILL.md`. Each Skill's YAML frontmatter must include a standardized `name` and a non-empty `description`, with `name` matching the directory name. `Guide_Doc` contributions require the final configuration's `guide_doc.enable` to be `true`; disabling the special runtime `Guide_Doc` mode will explicitly reject Doc plugins without copying files to unused locations. Plugin Skills are copied to:

```text
<workspace>/.ucagent/skills/ext/<plugin-id>/
```

Skills are always optional capabilities. Setting the final configuration `skill.use_skill: false` or CLI `--no-use-skill` will skip all plugin Skill copying, tool usage, and evidence gates, but will not disable the same plugin's Tools, Checkers, Guide_Docs, or workflows. Plugin-level `Guide_Doc` contributions will still load normally. Stage configurations reference copied plugin Skills via `ext/<plugin-id>/<skill-relative-path>`.

### Guide_Doc Core Guide

Plugins or plugin workflows can precisely select how to reuse the `Guide_Doc` file provided by the current language's default configuration via `guide_doc.core_copy_policy` in their own configuration YAML:

```yaml
guide_doc:
  core_copy_policy:
    default_action: ignore
    retain:
      - dut_fixture.md
      - dut_test_case.md
    override:
      - dut_api_instruction.md
    ignore:
      - dut_bug_analysis.md
```

All four fields must be present simultaneously, with the following meanings:

| Field | Behavior |
| :--- | :--- |
| `default_action` | Core documents not appearing in any list default to `retain` or `ignore` |
| `retain` | Copy and retain the core document; startup fails if the plugin provides a different file at the same path |
| `override` | Do not copy the core document; instead, copy the plugin-provided file at the same path; startup fails if the plugin does not provide it |
| `ignore` | Do not copy the core document; the plugin must also not provide a file at the same path |

List items are exact POSIX file paths relative to the current language's default `Guide_Doc` root directory. Paths must use canonical form; they cannot be absolute paths, contain `..`, backslashes, leading/trailing whitespace, or duplicates; the three action lists must also be disjoint. Explicitly listed paths must indeed exist in the current language's default documentation. Plugin-added documents that do not conflict with the core do not need to be listed in the policy and will be copied normally.

This configuration follows the standard configuration layering rules: a plugin workflow YAML can declare defaults, and workspace configuration, explicit `--config`, and CLI `--override` can further override it. Lists use full replacement semantics, so when overriding an action list, the complete list required for that layer should be provided. When no policy is declared, the core defaults to all `retain`, maintaining the original behavior of standard workflows.

Documents contributed by the plugin itself can be selected via `guide_doc.plugin_copy_policy`. This policy is suitable for selectively exposing only the language or target documents required by the current workflow in the final configuration: template variables are replaced before policy parsing:

```yaml
guide_doc:
  plugin_copy_policy:
    default_action: ignore
    retain:
      - "{RTL_CODING_GUIDE_FILE}"
      - shared_test_contract.md
    ignore: []
```

All three fields must be present. `default_action` and explicit actions can only be `retain` or `ignore`; path rules are the same as the core policy, and explicit paths must be provided by the currently activated plugin. The `ignore` action also deletes old plugin documents at the same path in the workspace, preventing the reading of expired resources after configuration switching. Whether plugin and core documents at the same path are replaced is still determined by `guide_doc.core_copy_policy`'s `retain/override/ignore`.

## Workflows and Their Exclusive Resources

Plugins can declare `PluginWorkflow` to bind future workflows and packages:

```python
from ucagent.plugins import CommandRequirement, PluginWorkflow

workflow = PluginWorkflow(
    name="unit-design-tdd",
    config_file=root / "workflows" / "unit-design-tdd.yaml",
    guide_doc_paths=(root / "Guide_Doc",),
    template_dir=root / "templates" / "unit_design",
    template_target="{OUT}",
    template_context_factory=build_template_context,
    skill_paths=(root / "skills",),
    command_requirements=(CommandRequirement("Picker", ("picker",)),),
    runtime_config_keys=("design_with_ppa.max_optimization_iterations",),
)
```

When calling, activate the plugin first, then select the workflow:

```bash
ucagent <workspace> <dut> \
  --plugin design-with-ppa \
  --plugin-workflow design-with-ppa:unit-design-tdd \
  --config config.yaml
```

Both `--plugin-workflow` and `--config` can be used simultaneously. Workflow configuration is an independent baseline layer and does not impersonate user configuration files; the final priority order is: core global, user global, core language default, plugin workflow, workspace settings, explicit `--config`, CLI `--override`. Short workflow names without a specified plugin ID are only allowed if unique within the activated plugin. Runtime metadata separately preserves explicit configuration, plugin and workflow selector, and workflow configuration sources. The same information is also written to `launch_context` in `.ucagent/runtime_config.json`; non-secret final configuration scalars explicitly declared by the plugin are written separately to `plugin_options`, without copying the full configuration or credentials to the runtime snapshot.

Resources and dependency fields of `PluginWorkflow` are optional:

| Field | Contract After Workflow Selection |
| :--- | :--- |
| `config_file` | Independent workflow configuration layer; must be a YAML file within the plugin root |
| `guide_doc_paths` | Appends this workflow's exclusive runtime Guide_Doc |
| `template_dir` | This workflow's template source directory |
| `template_target` | Workspace-relative target template, e.g., `{OUT}`; must not resolve to workspace root, escape paths, or overlap with read-only paths |
| `template_context_factory` | Optional trusted function; returns additional template variables based on final configuration and core template context, cannot override core values like `DUT`, `OUT`, `WORKSPACE` |
| `skill_paths` | Optional set of workflow Skills appended when Skills are enabled |
| `python_requirements` | Python dependencies checked only when this workflow is selected |
| `command_requirements` | External command capabilities checked only when this workflow is selected |
| `runtime_config_keys` | Explicitly allowed non-secret scalar paths to write into runtime snapshot `plugin_options` |

Plugin-level dependencies are checked when the plugin is activated; workflow dependencies are checked only after the workflow is selected. Therefore, using only `AnalyzePPA` does not require Picker, but selecting `unit-design-tdd` then requires the `picker` console command. Do not declare speculative PyPI versions for unverified tools; instead, verify actual console commands, version output, and subcommands required by the workflow.

The `guide_doc_paths` and `skill_paths` of a workflow are appended to plugin-level resources only when that workflow is selected; duplicate declared paths are deduplicated. `template_dir` remains a workflow-exclusive resource because template rendering must remain consistent with the complete configuration entry for that run. Different Skill roots cannot contain Skills that would be copied to the same relative path within the same plugin; such target conflicts will cause startup failure rather than silently overwriting.

All declared workflow configurations, Guide_Doc, templates, Skills, and assets must exist and be located within `Plugin.root`; symbolic links must not escape. If a plugin's multiple Guide_Doc sources provide different content to the same path, startup will fail. When a plugin and core document share the same name, it is handled according to `guide_doc.core_copy_policy`; silent overwriting will not occur when `override` is not explicitly allowed. Identical retained files allow idempotent reuse. Plugin Skills are an optional acceleration path: under `--no-use-skill`, Skills are not copied, but workflow prompts, tools, and Checkers must still provide complete non-Skill paths while maintaining the same acceptance criteria. When `template_target` is specified, the renderer only includes and renders files owned by the template source, without traversing or rewriting other existing products in the target directory, and will also reject overlaps with specific read-only paths like `{DUT}` in `un_write_dirs` before writing.

`template_context_factory(cfg, base_context)` is called after merging at the final configuration layer, before stage and template rendering. It is suitable for selecting prompt variables, template filenames, and template content simultaneously based on already-parsed language, target platform, and other configurations. The return value must be a finite JSON mapping with non-empty string keys; the factory cannot override the core context. Dynamic values have higher priority than the static `template_overwrite` in the workflow YAML, but explicit `--template-cfg-override` can still override the final file render value.

Explicitly include non-Python resources in the package data of `pyproject.toml`, for example:

```toml
[tool.setuptools.package-data]
design_with_ppa = [
  "assets/*.lib",
  "assets/*.md",
  "workflows/*.yaml",
  "Guide_Doc/*.md",
  "templates/**/*",
  "skills/**/*",
]
```

`sdist` should also recursively include the same resource set via `MANIFEST.in`, as well as the local `ucagent-plugin.toml` and tests; it cannot rely solely on files that happen to exist in the source tree.

## Verification, Build, Install, and Publish

First, prepare external tools declared by the plugin. The following commands verify the same core and plugin source code from the UCAgent repository root:

```bash
python3 -m pip install -e .
python3 -m pip install build pytest
python3 -m pip install -e ./plugins/DesignWithPPA
python3 -m py_compile plugins/DesignWithPPA/src/design_with_ppa/*.py
python3 -m pytest -q plugins/DesignWithPPA/tests
ucagent --validate-plugin ./plugins/DesignWithPPA
python3 -m build ./plugins/DesignWithPPA
```

Other plugins should replace the above plugin path with their own project directory. The default process of `python3 -m build` first builds an sdist, then builds a wheel from the sdist, which can isolate the `build/` cache existing in the source tree to prevent stale files from entering the release package. The equivalent `uv build` default process can also be used. Do not run `python3 -m build --wheel` only on source trees that may contain old caches.

Installation-state verification must also be performed on the generated wheel; it cannot rely solely on importing from the source directory:

```bash
python3 -m venv /tmp/design-with-ppa-verify
/tmp/design-with-ppa-verify/bin/python -m pip install .
/tmp/design-with-ppa-verify/bin/python -m pip install plugins/DesignWithPPA/dist/ucagent_design_with_ppa-*.whl
/tmp/design-with-ppa-verify/bin/ucagent --list-plugins
/tmp/design-with-ppa-verify/bin/ucagent --validate-plugin design-with-ppa
/tmp/design-with-ppa-verify/bin/ucagent <workspace> <dut> \
  --plugin design-with-ppa \
  --plugin-workflow design-with-ppa:unit-design-tdd
```

Release checklist:

1. The `name`, entry point name, and `Plugin.name` must be completely consistent;
2. `Plugin.version` must match the package version, and `requires_ucagent` must cover the actual tested version;
3. Python dependencies must appear in both the package metadata and the `Plugin.python_requirements` verification declaration;
4. External commands must provide accurate names and acceptable executable alternatives;
5. The wheel must include copies of all configurations, documents, templates, Skills, scripts, assets, and root directory licenses and copyright notices;
6. The sdist must include `ucagent-plugin.toml`, tests, copies of licenses and copyright notices, and all files required to build an independent wheel;
7. Local paths, configuration search paths, and installation entry points must all be tested via the three discovery methods;
8. Each Tool must be tested via direct invocation, failure boundaries, MCP schema conversion, and tool filtering;
9. Each Checker must be tested via type validation, short name resolution, lifecycle, and name conflict tests;
10. Independent Guide_Doc, Skill, and workflow must each pass activation tests when no other capabilities are provided;
11. Each workflow must complete when Skills are enabled, explicitly disabled, and when the Skill directory does not exist;
12. Installation-state tests must run from the wheel, not relying on the `src` path within the repository;
13. After releasing a new version, update using `python3 -m pip install --upgrade <package or wheel path>`, then run `ucagent --validate-plugin <plugin ID>`.

## Common Failures

- `available=[]`: The plugin is not installed, and the final configured `plugin.search_paths` does not include the project or parent directory;
- `manifest name ... does not match`: The local manifest ID does not match the provider's `Plugin.name`;
- `requires Python package`: The current UCAgent Python environment is missing plugin dependencies or the version is unsatisfiable;
- `requires command`: The external analysis tool is not in the current process's `PATH`;
- `resource must remain inside plugin root`: The provider declares a path outside the package or an escaped symbolic link;
- `selector is ambiguous`: Multiple entry points, local plugins, or workflows use conflicting names; the error will list candidate distributions or manifest paths. You should uninstall, remove search paths, or explicitly use a unique source project path;
- `Duplicate plugin Checker name`: Two activated plugins declare a Checker with the same name;
- `conflicts with a core Checker`: The plugin Checker class name occupies a core Checker short name;
- Tool not in Agent/MCP: Confirm `--plugin` was passed, then check the final `tools.ignore_tools` and `tools.selected_tools`.

## Open Contract for Workflow Execution

Plugin workflows must include the specification files that the LLM actually needs to comply with in the current stage's `reference_files`, rather than relying solely on error messages after failure. For example, when using a line mapping Checker, the stage must simultaneously provide `Guide_Doc/dut_line_func_map.md` and the currently generated functional contract. Task prompts should also explicitly specify the single-line physical range using the complete `start-end` format, such as `10-10`, rather than a single number like `10`. Missing specification files will cause weaker models to repeatedly trial and error, and will count avoidable format errors as stage failures.

Stage configuration, template context, and capability dependencies are parsed and copied to the runtime workspace in a single pass during UCAgent startup. After modifying plugin YAML, `Guide_Doc`, or templates, you must restart the workflow and regenerate the workspace; a running Agent does not hot-load these files. When recovering or retrying, verify that the generated files match the current parsed configuration's source, hash, and language selection. Do not treat artifacts from an old workspace as evidence of the new configuration.

The command-line backend may inherently possess shell, file browsing, and external directory read capabilities. Relying solely on system prompts to require the model to adhere to workspace boundaries is insufficient. If the workflow requires testing, transformation, or analysis to be executed only by trusted Tools/Checkers, the backend configuration must simultaneously disable the native shell and reject paths outside the workspace. Reading and writing to the current workspace should still use the backend's restricted file tools, while testing and external commands should use public MCP Tools. Verify that disabled capabilities indeed return a refusal through a real backend session, rather than merely verifying that the configuration file contains the corresponding field.

Batch processing Checker stage documents are repeatedly edited by the model. After each refinement or addition, you must check that FG/FC/CK IDs are globally unique, parent-child paths are consistent, and line mapping references are closed on the complete document. Do not append a new description of the same CK under another FC, and do not check only the current batch while ignoring completed batches. When submitting `refined` progress, only use the complete CK path provided by `CurrentTips` for the current batch; after completion, re-fetch the next batch.

Batch processing templates must also distinguish between "covering a CK already declared by the model" and "testing a function already associated with a CK". Coverage groups typically declare all CKs at once before the template stage, but this does not mean all templates have been generated. The current Check only requires that historical completed items and the `CurrentTips` current batch have real test associations; future batches may be temporarily unassociated and must not be pre-associated and skipped. When source documents or test associations change, resynchronize progress from the current file and test report, rather than treating coverage declarations or old checkpoints as evidence of completion.

The coverage predicate itself is also independent evidence and cannot be substituted by the existence of a bin name for "condition implemented." Workflows implementing predicates in batches should write a unique explicit false placeholder for the complete CK set in the structure stage. During the implementation stage, distinguish placeholders from non-constant predicates via AST or equivalent source code evidence, allowing replacement only of `CurrentTips`'s current batch. Constant-true callables, early implementation of future batches, and rolling back completed items to placeholders must all be rejected. Source code gates can only prove that a condition has been written; whether the predicate is reachable and matches real stimuli still requires proof from subsequent isolated pytest coverage hits.

When reusing a core batch processing Checker, first confirm that its "report passed" semantics align with the plugin workflow. Verify that the workflow can retain DUT bugs exposed by correct tests, while design generation workflows typically require all current tests to pass; the two cannot share the same final report judgment. If different semantics are needed, inherit `UnityChipCheckerBatchTestsImplementation`, replace only the current batch's report gate via `_validate_current_batch_report(report)`, and continue reusing its source code resynchronization, precise node execution, checkpoint, and batch progression state machine. If the workflow does not use Bug documents, ensure `_cached_document_preflight(target_tests)` returns `None`, preventing irrelevant Bug document preflight checks from blocking test batches. The report gate must only check the status of the current precise node, CK association, and hit evidence; other CKs in the full coverage model not executed by this batch are normal misses in the local report and cannot be used to reject the current batch. When the gate fails, do not call batch completion or persist progress, and ensure regression tests cover "rebuilding the Checker after rejection still starts from the same batch."

When batch implementing Python tests, you must modify existing template functions specified by `CurrentTips` in-place, rather than appending a same-named `def` before or after the file. After each write, perform an AST-level top-level function name uniqueness check on the entire test file, and confirm that `mark_function` references this unique function; otherwise, the later definition will overwrite module attributes, causing pytest collection, coverage association, and the LLM's observed implementation to point to different functions, potentially hiding the real implementation behind an old placeholder assertion.

Fenced YAML in specification documents must be pre-validated with a real YAML parser. Natural language values containing colons, hashes, braces, templates, or other YAML syntax characters should be explicitly quoted; for example, `packing: "element k occupies bits [8*k+7:8*k+0]"`, to prevent colons from being parsed as new mappings. Do not treat Markdown text that "looks like YAML" as valid evidence; when a Check fails, fix the specific field and re-parse the entire fenced block.

External tool dependencies should declare the real console command, version parameters, and required subcommands, returning a clear next step when missing, version mismatched, or subcommands unavailable. When using only Tools, do not load workflow-specific dependencies; only check capabilities when selecting the corresponding workflow. Temporary files generated by testing, transformation, and analysis should be managed by trusted Check/Complete child processes, with the stage LLM contacting only public source code languages, Python tests, and result summaries.

Cleanup entry points provided by plugins are development convenience features and should not be relied upon to determine deletion scope based on Git status. Cleanup targets must be listed output, build, and cache directories within the plugin root, and should refuse to expand scope via coverable workspace or output parameters; tracked source files and user modifications to source files must remain unchanged. Before release, verify in a temporary directory that "target caches are deleted, unrelated files are retained, and paths outside the plugin root are not touched."
