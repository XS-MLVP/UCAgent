"""Safe resolved path-policy context for the Formal data Skill."""

from typing import Any

from ucagent.util.file_policy import normalize_relative_path


class FormalDataRuntimeHook:
    """Publish only the non-secret policies needed by the copied data Skill."""

    def snapshot_sections(self, cfg: Any) -> dict:
        """Copy validated resolved policies without exposing model or tool configuration."""
        section = {}
        for key in ("write_dirs", "un_write_dirs"):
            value = cfg.get_value(key, None)
            if value is not None:
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise ValueError(f"Formal data {key} must be a list of workspace-relative paths or null")
                value = [normalize_relative_path(item) for item in value]
            section[key] = value
        return {"formal_data": section}

    def validate_runtime_snapshot(self, data: dict) -> None:
        """Reject missing or malformed plugin-owned snapshot policy rather than guessing."""
        section = data.get("formal_data")
        if not isinstance(section, dict) or set(section) != {"write_dirs", "un_write_dirs"}:
            raise ValueError("Formal data runtime context is missing; restart UCAgent to regenerate its runtime snapshot")
        for key, values in section.items():
            if values is None:
                continue
            if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"Invalid formal_data.{key}; restart UCAgent to regenerate its runtime snapshot")
            for item in values:
                if normalize_relative_path(item) != item:
                    raise ValueError(f"Noncanonical formal_data.{key}; restart UCAgent to regenerate its runtime snapshot")
