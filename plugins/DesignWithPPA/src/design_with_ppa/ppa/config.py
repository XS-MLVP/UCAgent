"""Resolved analysis selection and technology files shared by all PPA backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .common import _sha256_file


_BUNDLED_PDKS = {
    "nangate45": {
        "corner": "typical",
        "liberty": "NangateOpenCellLibrary_typical.lib",
        "tie_high": {"cell": "LOGIC1_X1", "port": "Z"},
        "tie_low": {"cell": "LOGIC0_X1", "port": "Z"},
    },
}


class ConstantCell(BaseModel):
    """A technology-specific cell and output pin for a constant logic net."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cell: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    port: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")


class PDKConfig(BaseModel):
    """Technology identity, named file sets, and optional constant mapping cells."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(default="nangate45", min_length=1)
    corner: str = Field(default="typical", min_length=1)
    files: dict[str, list[str]] = Field(default_factory=dict)
    tie_high: ConstantCell | None = None
    tie_low: ConstantCell | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class PPAConfig(BaseModel):
    """Public, non-secret backend settings read from resolved agent configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    backend: str = Field(default="yosys_opensta", min_length=1)
    backend_options: dict[str, JsonValue] = Field(default_factory=dict)
    pdk: PDKConfig = Field(default_factory=PDKConfig)

    @model_validator(mode="after")
    def validate_json(self):
        """Reject nonfinite settings before they enter reports and history."""

        json.dumps(self.model_dump(), allow_nan=False)
        return self


@dataclass(frozen=True)
class ResolvedPDK:
    """Validated absolute technology paths with a reproducible public identity."""

    config: PDKConfig
    files: dict[str, tuple[Path, ...]]
    provenance: dict[str, Any]


def resolve_ppa_config(cfg: Any) -> PPAConfig:
    """Read backend and PDK selection from the resolved UCAgent configuration."""

    get_value = getattr(cfg, "get_value", lambda key, default: default)
    values = {}
    for key, default in PPAConfig().model_dump().items():
        value = get_value(f"design_with_ppa.ppa.{key}", default)
        values[key] = value.as_dict() if hasattr(value, "as_dict") else value
    return PPAConfig.model_validate(values)


def resolve_pdk(
    config: PDKConfig,
    resolve_input: Callable[[str, set[str] | None], Path],
    liberty_file: str | None = None,
) -> ResolvedPDK:
    """Confine and hash technology assets, expanding an explicitly named preset.

    An explicit tool-call Liberty replaces the configured Liberty file set.
    Other named file sets remain available to the selected backend.
    """

    labels = {key: list(values) for key, values in config.files.items()}
    if liberty_file:
        resolve_input(liberty_file, {".lib"})
        labels["liberty"] = [liberty_file]
    preset = _BUNDLED_PDKS.get(config.name)
    bundled = preset is not None and "liberty" not in labels
    if bundled and config.corner != preset["corner"]:
        raise ValueError(
            f"bundled {config.name} supports only corner={preset['corner']}; "
            "supply pdk.files.liberty for another corner"
        )
    high, low = config.tie_high, config.tie_low
    if preset is not None:
        high = high or ConstantCell(**preset["tie_high"])
        low = low or ConstantCell(**preset["tie_low"])
    config = config.model_copy(update={"tie_high": high, "tie_low": low})
    files: dict[str, tuple[Path, ...]] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    for key, values in labels.items():
        if not key or not values or len(set(values)) != len(values):
            raise ValueError("each pdk.files entry requires a name and a nonempty unique path list")
        files[key] = tuple(resolve_input(value, None) for value in values)
        if len(set(files[key])) != len(files[key]):
            raise ValueError(f"pdk.files.{key} contains multiple paths to the same file")
        rows[key] = [{"path": value, "sha256": _sha256_file(path)}
                     for value, path in zip(values, files[key])]
    if bundled:
        library = Path(__file__).resolve().parents[1] / "assets" / preset["liberty"]
        if not library.is_file():
            raise FileNotFoundError(
                f"bundled {config.name} Liberty asset is missing: {library.name}; "
                "reinstall the plugin or provide liberty_file"
            )
        files["liberty"] = (library,)
        rows["liberty"] = [{"path": f"bundled:{library.name}", "sha256": _sha256_file(library)}]
    provenance = config.model_dump(exclude={"files"})
    provenance["files"] = rows
    return ResolvedPDK(config, files, provenance)
