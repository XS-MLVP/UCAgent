"""Shared validation primitives for DesignWithPPA workflow artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml


_FENCED_YAML_RE = re.compile(r"```yaml\s*\n(?P<body>.*?)\n```", re.DOTALL)


def resolve_workspace_path(
    workspace: str | Path,
    value: str | Path,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve a workspace-relative path without permitting traversal or symlink escape."""

    root = Path(workspace).resolve()
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"path must be workspace-relative: {value}")
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path must remain inside workspace: {value}") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"workspace artifact was not found: {value}")
    return candidate


def sha256_file(path: Path) -> str:
    """Hash one regular non-symlink file."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"artifact must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    """Hash a finite JSON-compatible value using stable key and separator ordering."""

    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not finite canonical JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def performance_stimulus_identity(stimulus: dict[str, Any]) -> dict[str, Any]:
    """Return the stimulus-only fields that must remain stable across RTL rounds."""

    return {
        "deterministic": stimulus.get("deterministic"),
        "seed": stimulus.get("seed"),
        "parameters": stimulus.get("parameters"),
        "input_trace": stimulus.get("input_trace"),
    }


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object while rejecting non-finite constants and non-mappings."""

    def reject_constant(value: str) -> None:
        """Reject JSON NaN and Infinity extensions."""

        raise ValueError(f"non-finite JSON constant is not allowed: {value}")

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"JSON artifact must be a regular non-symlink file: {path}")
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            value = json.load(file_obj, parse_constant=reject_constant)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON artifact is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping from a regular non-symlink file."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"YAML artifact must be a regular non-symlink file: {path}")
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            value = yaml.safe_load(file_obj)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"YAML artifact is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"YAML artifact must contain a mapping: {path}")
    return value


def load_fenced_yaml(path: Path, root_key: str) -> dict[str, Any]:
    """Load the unique fenced YAML mapping carrying one required root key."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Markdown artifact must be a regular non-symlink file: {path}")
    content = path.read_text(encoding="utf-8")
    matches = []
    for match in _FENCED_YAML_RE.finditer(content):
        try:
            value = yaml.safe_load(match.group("body"))
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid fenced YAML in {path}: {exc}") from exc
        if isinstance(value, dict) and root_key in value:
            matches.append(value[root_key])
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError(
            f"{path} must contain exactly one fenced yaml mapping with root key {root_key!r}"
        )
    return matches[0]


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Write finite JSON through an fsynced temporary file and atomic replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"JSON destination must not be a symlink: {path}")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(value, file_obj, indent=2, ensure_ascii=False, allow_nan=False)
            file_obj.write("\n")
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    """Write one YAML mapping through an atomic replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"YAML destination must not be a symlink: {path}")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            yaml.safe_dump(value, file_obj, sort_keys=False, allow_unicode=True)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_text(path: Path, value: str) -> None:
    """Write UTF-8 text through an atomic replacement without following a symlink."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"text destination must not be a symlink: {path}")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            file_obj.write(value)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def diagnostic(
    error_code: str,
    error: str,
    next_action: str,
    **details: Any,
) -> dict[str, Any]:
    """Build one explicit bounded Checker diagnostic."""

    result = {
        "error_code": error_code,
        "error": error,
        "next_action": next_action,
    }
    result.update({key: value for key, value in details.items() if value is not None})
    return result


def finite_number(value: Any, field: str) -> float:
    """Validate one finite numeric field without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def resolved_output(cfg: Any) -> str:
    """Return the resolved workspace-relative output directory from agent config."""

    values = cfg.get_value("_temp_cfg", {})
    output = values.get("OUT") if isinstance(values, dict) else None
    if not isinstance(output, str) or not output.strip():
        raise ValueError("resolved configuration OUT must be a non-empty string")
    return output


def optimization_limits(cfg: Any) -> tuple[int, int]:
    """Return validated minimum and maximum candidate optimization rounds.

    The minimum is the number of candidate rounds that must be evaluated before
    a no-improvement result can terminate the search.  The maximum is a safety
    bound which may be reached only after all candidates up to that bound have
    been evaluated.  Both values are deliberately strict integers so YAML
    booleans, floats and stringified numbers cannot silently alter the search.
    """

    minimum = cfg.get_value("design_with_ppa.min_optimization_iterations", 5)
    maximum = cfg.get_value("design_with_ppa.max_optimization_iterations", 1000)
    for name, value in (
        ("min_optimization_iterations", minimum),
        ("max_optimization_iterations", maximum),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"design_with_ppa.{name} must be an integer"
            )
        if value < 0 or value > 1000:
            raise ValueError(
                f"design_with_ppa.{name} must be between 0 and 1000"
            )
    if minimum > maximum:
        raise ValueError(
            "design_with_ppa.min_optimization_iterations must not exceed "
            "design_with_ppa.max_optimization_iterations"
        )
    return minimum, maximum


def no_improvement_patience(cfg: Any) -> int:
    """Return the validated number of consecutive rejected rounds before stopping.

    A patience of one stops on the first rejected/non-improving candidate once
    the minimum round count has been reached.  Zero is intentionally rejected:
    at least one observed candidate is required to establish that progress has
    stopped.
    """

    value = cfg.get_value("design_with_ppa.no_improvement_patience", 3)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "design_with_ppa.no_improvement_patience must be an integer"
        )
    if value < 1 or value > 1000:
        raise ValueError(
            "design_with_ppa.no_improvement_patience must be between 1 and 1000"
        )
    return value


NO_REGRESSION_CATEGORIES: tuple[str, ...] = (
    "performance",
    "area",
    "timing",
    "power",
)


DEFAULT_NO_REGRESSION_CATEGORIES: tuple[str, ...] = ("performance", "timing")


PPA_SCORE_WEIGHT_DIMENSIONS: tuple[str, ...] = ("timing", "area", "power")


def ppa_score_weights(cfg: Any) -> dict[str, float]:
    """Return validated PPA selection-score weights for the three PPA dimensions.

    The selection score generalizes
    ``timing_efficiency * area_efficiency * power_efficiency`` to
    ``timing_efficiency^w_timing * area_efficiency^w_area *
    power_efficiency^w_power``; every weight defaults to ``1.0`` and weights of
    ``0`` remove a dimension from the score.  Custom functional performance
    metrics (simulation latency/throughput) intentionally have no weight: the
    performance dimension is represented solely by the frequency or critical
    delay metric, which is in a deterministic linear relationship with them.
    The value must be a mapping keyed by a subset of ``timing``, ``area`` and
    ``power``; unknown keys (including any performance metric) are rejected.
    """

    raw = cfg.get_value("design_with_ppa.score_weights", None)
    if raw is None:
        return {dimension: 1.0 for dimension in PPA_SCORE_WEIGHT_DIMENSIONS}
    if hasattr(raw, "as_dict") and callable(raw.as_dict):
        raw = raw.as_dict()
    if not isinstance(raw, dict):
        raise ValueError(
            "design_with_ppa.score_weights must be a mapping of "
            f"{list(PPA_SCORE_WEIGHT_DIMENSIONS)} to non-negative numbers"
        )
    unknown = sorted(set(raw) - set(PPA_SCORE_WEIGHT_DIMENSIONS))
    if unknown:
        raise ValueError(
            "design_with_ppa.score_weights supports only "
            f"{list(PPA_SCORE_WEIGHT_DIMENSIONS)}; unsupported keys: {unknown}. "
            "Custom performance metrics carry no weight; the timing dimension "
            "already represents them through the frequency metric."
        )
    weights: dict[str, float] = {}
    for dimension in PPA_SCORE_WEIGHT_DIMENSIONS:
        if dimension not in raw:
            weights[dimension] = 1.0
            continue
        value = finite_number(
            raw[dimension], f"design_with_ppa.score_weights.{dimension}"
        )
        if value < 0.0:
            raise ValueError(
                "design_with_ppa.score_weights values must be non-negative; "
                f"got {dimension}={value}"
            )
        weights[dimension] = value
    return weights


def no_regression_metric_categories(cfg: Any) -> tuple[str, ...]:
    """Return the validated metric categories that must not regress.

    A candidate is rejected when any primary metric inside one of these
    categories regresses against the previously accepted version.  Category
    names classify primary metrics: ``performance`` covers every simulation
    latency/throughput metric, while ``area``, ``timing`` and ``power`` cover
    the corresponding ``ppa.*`` metrics.  The value may be a YAML list of
    category names or a comma-separated string (the environment-substitution
    form).  The default protects ``performance`` and ``timing`` so PPA
    (area and power) is optimized as far as possible without losing
    performance; an explicitly empty
    value (an empty string, YAML ``null`` as produced by an empty environment
    variable, or an empty list) removes all regression protection and accepts
    any candidate that strictly improves at least one primary metric.
    """

    raw = cfg.get_value(
        "design_with_ppa.no_regression_metrics",
        ",".join(DEFAULT_NO_REGRESSION_CATEGORIES),
    )
    if raw is None:
        items = []
    elif isinstance(raw, str):
        items = [part.strip() for part in raw.split(",")] if raw.strip() else []
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValueError(
            "design_with_ppa.no_regression_metrics must be a list of category "
            f"names or a comma-separated string, one of {list(NO_REGRESSION_CATEGORIES)}"
        )
    categories: list[str] = []
    for item in items:
        if not isinstance(item, str) or item not in NO_REGRESSION_CATEGORIES:
            raise ValueError(
                "design_with_ppa.no_regression_metrics entries must be one of "
                f"{list(NO_REGRESSION_CATEGORIES)}; got {item!r}"
            )
        if item in categories:
            raise ValueError(
                "design_with_ppa.no_regression_metrics must not repeat "
                f"category {item!r}"
            )
        categories.append(item)
    return tuple(categories)
