"""Resolve explicitly selected analysis inputs without historical batch defaults."""
from pathlib import Path


def resolve_run_specs(config_path, config, explicit_values):
    """Resolve LABEL=PATH arguments from cwd or configured paths beside the config."""
    if explicit_values:
        runs = []
        for value in explicit_values:
            label, separator, path = value.partition("=")
            if not separator or not label.strip() or not path.strip():
                raise ValueError(f"run must be LABEL=PATH with a nonempty label and path: {value!r}")
            runs.append((label.strip(), Path(path).expanduser().resolve()))
    else:
        base = Path(config_path).resolve().parent
        inputs = config.get("model_inputs", {})
        labels = config.get("include_models") or list(inputs)
        excluded = set(config.get("exclude_models", []))
        runs = [(label, (base / Path(path).expanduser()).resolve())
                for label in labels if label not in excluded
                for path in inputs.get(label, [])]
    if not runs:
        raise ValueError("no analysis inputs; pass --run LABEL=PATH or configure [model_inputs]")
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
