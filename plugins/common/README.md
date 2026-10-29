# ucagent-common

Shared verification-domain library for UCAgent workflow plugins. It is a
dependency of the workflow plugins (never of the core framework) and holds the
code more than one plugin consumes:

- `ucagent_common.bug_analysis_contract` — the canonical machine-readable
  contract for dynamic Bug analysis documents, including the localized
  display-title data under `lang/zh/config/`.
- `ucagent_common.doc_marks` — FG/FC/CK/BG/TC hierarchy parsing, generic
  `<TAG>` mark extraction, and their string helpers.
- `ucagent_common.test_report` — shared pytest-report and test-case source
  checks (pass/fail gating, assert-presence validation, location parsing).
- `ucagent_common.test_utils` — UnityTest-style test-domain helpers consumed
  by generated DUT test code (`from ucagent_common import test_utils`):
  simulator artifact suffix defaults, `UC_SEED_MODEL`/`UC_TEST_RCOUNT`
  resolution, and fake/mock DUT construction. Workspace test processes
  resolve it through the snapshot's `plugin_python_paths`.
- `ucagent_common.str_utils` — bounded string/list display helpers for
  plugin diagnostics (`list_str_abbr`).

Import direction: `ucagent_common` may import from the `ucagent` core package;
the core must never import `ucagent_common`.

## Wiring

Workflow plugins reference this library from their `ucagent-plugin.toml`:

```toml
python_path = ["src", "../common/src"]
```

The first entry stays the plugin's own import root; later entries may point at
sibling roots such as this one. Local plugin loading puts every root on
`sys.path`, and workspace runtime snapshots record them under
`plugin_python_paths` so skill scripts inherit the same `PYTHONPATH`.
