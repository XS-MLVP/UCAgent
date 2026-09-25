"""Select immutable UnityTest input workspaces for one analysis run."""
from pathlib import Path


def resolve_run_specs(explicit_values):
    """Resolve selected LABEL=PATH inputs without guessing historical runs."""
    runs = []
    for value in explicit_values:
        label, separator, path = value.partition("=")
        if not separator or not label.strip() or not path.strip():
            raise ValueError(f"run must be LABEL=PATH with a nonempty label and path: {value!r}")
        runs.append((label.strip(), Path(path).expanduser().resolve()))
    if not runs:
        raise ValueError("no analysis inputs; pass --run LABEL=PATH or populate inputs/workspace_*")
    missing = [str(path) for _, path in runs if not path.exists()]
    if missing:
        raise ValueError("analysis inputs do not exist: " + ", ".join(missing[:5]))
    return [(label, str(path)) for label, path in runs]


def discover_input_workspaces(input_root):
    """Return every direct ``workspace_*`` DUT directory in input_root."""
    root = Path(input_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"input root does not exist: {root}")
    return [(path.name.removeprefix("workspace_"), str(path))
            for path in sorted(root.glob("workspace_*")) if path.is_dir()]
