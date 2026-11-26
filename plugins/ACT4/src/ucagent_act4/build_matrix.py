"""Read required native builds from the accepted baseline, not a generated report."""

from hashlib import sha256
import json
from pathlib import Path

from .xiangshan_bundle import safe_path


SELECTION_FIELDS = {"TESTDIR", "EXTENSIONS", "EXCLUDE_EXTENSIONS", "CERTIFICATE", "ENABLE_EXPERIMENTAL_EXTENSIONS"}


def assignments(tokens):
    """Extract explicit native controls without executing the recorded command."""
    values = {}
    for token in tokens:
        name, separator, value = token.partition("=")
        if separator and name in SELECTION_FIELDS | {"CONFIG_FILES", "WORKDIR"}:
            if name in values:
                raise ValueError(f"Ambiguous repeated selection control: {name}")
            values[name] = value
    return values


def required_builds(workspace: Path, root: Path, review_dir: str, receipt: dict):
    """Verify frozen review evidence and resolve one reproducible selection per required target."""
    evidence = json.loads(safe_path(workspace, review_dir + "/evidence-before.json").read_bytes())
    if sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest() != receipt.get("evidence-before"):
        raise ValueError("Baseline evidence does not match the accepted review")
    builds = {}
    for job in evidence["jobs"]:
        if job["purpose"] != "build" or job["optional"]:
            continue
        target = job["target"]
        record = evidence["validation_plan"]["targets"][target]
        controls = assignments(job["argv"])
        config = record.get("config")
        if not config or config not in controls.get("CONFIG_FILES", "").split():
            raise ValueError(f"Required build {target} must select its recorded native CONFIG_FILES")
        config_path = safe_path(root, config)
        if sha256(config_path.read_bytes()).hexdigest() != record["sources"].get(config):
            raise ValueError(f"Native config differs from its reviewed contents: {config}")
        selection = {key: value for key, value in controls.items() if key in SELECTION_FIELDS and value}
        if config in builds and builds[config] != selection:
            raise ValueError(f"Conflicting source selections for required config {config}")
        builds[config] = selection
    if not builds:
        raise ValueError("The accepted review contains no required native build job")
    return builds
