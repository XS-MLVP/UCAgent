# Workspace Rules

Use a disposable workspace whenever you need picker exports, generated files, or smoke logs.

## Expected layout

```
<workspace>/
  exports/
  generated/
  logs/
  workspace.json
```

## Rules

- Keep the workspace disposable; do not point it at a maintained verification tree.
- Put picker-exported DUT packages under `exports/{DUT}`.
- Put freshly generated scaffolds under `generated/` when you are not repairing an existing tree.
- Keep smoke and export logs under `logs/`.

## Why `exports/{DUT}` matters

The generated API template imports the DUT as:

```python
from {DUT} import DUT{DUT}
```

That works when `PYTHONPATH` contains the parent directory of the exported DUT package. In other words:

- export target: `<workspace>/exports/Adder`
- `PYTHONPATH` entry: `<workspace>/exports`
- import: `from Adder import DUTAdder`

## Reuse vs regenerate

- Reuse the existing `tests/` tree when it already contains maintained verification code.
- Regenerate only into an empty directory, typically `<workspace>/generated/<DUT>_mvp`.
- Use the workspace even when reusing existing tests, because picker export and smoke logs still need a safe place.
