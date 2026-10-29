# -*- coding: utf-8 -*-
"""Layered configuration loading and validated shared runtime snapshots."""

import os
import re
import yaml
import importlib.util
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from yaml.constructor import SafeConstructor
from .functions import (
    render_template,
    dump_as_json,
    replace_bash_var,
    get_abs_path_cwd_ucagent,
    load_json_file,
    save_json_file,
)
from .log import info
import base64


_NEGATED_BOOL_PATTERN = re.compile(
    r"^(?:not[ \t]+|-)(?:yes|no|true|false|on|off)$",
    re.IGNORECASE,
)
_DELETE_OVERRIDE = object()
RUNTIME_CONFIG_FILENAME = "runtime_config.json"
CURRENT_TEST_REPORT_FILENAME = "current_test_report.json"
CURRENT_TEST_REPORT_SCHEMA_VERSION = 1
CURRENT_TEST_REPORT_RELATIVE_PATH = f".ucagent/{CURRENT_TEST_REPORT_FILENAME}"


def _current_ucagent_python_path() -> Path:
    """Return the import root containing this loaded UCAgent package."""
    return Path(__file__).resolve().parents[2]


class UCAgentConfigLoader(yaml.SafeLoader):
    """Safe YAML loader with support for negated boolean scalars."""


def _construct_negated_bool(loader, node):
    scalar_value = loader.construct_scalar(node).strip()
    if scalar_value.startswith('-'):
        bool_value = scalar_value[1:]
    else:
        bool_value = re.sub(r"^not[ \t]+", "", scalar_value, count=1, flags=re.IGNORECASE)
    return not SafeConstructor.bool_values[bool_value.lower()]


UCAgentConfigLoader.add_implicit_resolver('!negated_bool', _NEGATED_BOOL_PATTERN, ['-', 'n', 'N'])
UCAgentConfigLoader.add_constructor('!negated_bool', _construct_negated_bool)

class Config:
    """Configuration class for UCAgent settings."""

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Initialize configuration object.

        Args:
            data: Dictionary containing configuration data.
        """
        self._freeze = False
        self.from_dict(data)

    def from_dict(self, data: Optional[Dict[str, Any]]) -> None:
        """Load configuration from a dictionary.

        Args:
            data: Dictionary containing configuration.
        """
        if data is None:
            return self
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, Config(value))
            elif isinstance(value, list):
                # If the value is a list, convert each item to Config if it's a dict
                setattr(self, key, [Config(item) if isinstance(item, dict) else item for item in value])
            else:
                setattr(self, key, value)
        return self

    def empty(self) -> bool:
        """Check if the configuration is empty.

        Returns:
            True if configuration is empty, False otherwise.
        """
        return len(self.as_dict()) <= 1

    def as_dict(self) -> Dict[str, Any]:
        """Convert the configuration to a dictionary.

        Returns:
            Dictionary representation of the configuration.
        """
        result = {}
        for key, value in self.__dict__.items():
            if key in {"_freeze", "_loaded_config_files"}:
                continue
            if isinstance(value, Config):
                result[key] = value.as_dict()
            elif isinstance(value, list):
                # If the value is a list, convert each item to dict if it's a Config
                result[key] = [item.as_dict() if isinstance(item, Config) else item for item in value]
            else:
                result[key] = value
        return result

    def __str__(self):
        return "Config(" + dump_as_json(self.as_dict()) + ")"

    def update_template(self, template_dict):
        """
        Update the configuration with a template.
        :param template (dict): Template to update the configuration with.
        :return: self
        eg:
        template = {
            "OUT": "my_path_to_output",
        }
        """
        self.un_freeze()  # Ensure the configuration is mutable
        def _update_list(list_val):
            for i, itm in enumerate(list_val):
                if isinstance(itm, Config):
                    itm.update_template(template_dict)
                elif isinstance(itm, str):
                    nval = render_template(itm, template_dict)
                    if nval != itm:
                        list_val[i] = nval
                elif isinstance(itm, list):
                    _update_list(itm)
                else:
                    assert False, (
                        f"Unsupported list item type: {type(itm)}. "
                        "Supported types are: str, Config, str, and list."
                    )
        for key, value in self.__dict__.items():
            if isinstance(value, Config):
                value.update_template(template_dict)
            elif isinstance(value, list):
                _update_list(value)
            elif isinstance(value, str):
                nval = render_template(value, template_dict)
                if nval != value:
                    setattr(self, key, nval)
        self.freeze()  # Freeze the configuration after updating
        return self

    def dump_str(self, indent=2):
        """
        Dump the configuration as a YAML string.
        :param indent: Indentation level for YAML formatting.
        :return: YAML formatted string of the configuration.
        """
        return yaml.dump(self.as_dict(),
                         default_flow_style=False,
                         indent=indent, allow_unicode=True)

    def freeze(self):
        """
        Freeze the configuration, making it immutable.
        :return: self
        """
        for _, value in self.__dict__.items():
            if isinstance(value, Config):
                value.freeze()
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, Config):
                        v.freeze()
        self._freeze = True
        return self

    def un_freeze(self):
        """
        Unfreeze the configuration, making it mutable again.
        :return: self
        """
        for _, value in self.__dict__.items():
            if isinstance(value, Config):
                value.un_freeze()
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, Config):
                        v.un_freeze()
        self._freeze = False
        return self


    def __setattr__(self, name, value):
        """
        Set an attribute of the configuration.
        :param name: Name of the attribute.
        :param value: Value to set.
        :return: None
        """
        if name != "_freeze":
            if getattr(self, "_freeze", False) == True:
                raise RuntimeError("Configuration is frozen, cannot modify.")
        super().__setattr__(name, value)

    def __getattr__(self, name):
        """
        Get an attribute of the configuration.
        :param name: Name of the attribute.
        :return: Value of the attribute.
        """
        if name in self.__dict__:
            return self.__dict__[name]
        return Config()  # Return an empty Config object if the attribute does not exist

    def has_attr(self, name):
        return name in self.__dict__

    def merge_from(self, other):
        """
        Merge another Config object into this one.
        :param other: Another Config object to merge from.
        :return: self
        """
        if not isinstance(other, Config):
            raise TypeError("Can only merge from another Config instance.")
        return self.merge_from_dict(other.as_dict())

    def merge_from_dict(self, data, skip_include=False):
        """
        Merge configuration from a dictionary.
        :param data: Dictionary containing configuration.
        :param skip_include: Whether to treat top-level include as a loader directive.
        :return: self
        """
        if not isinstance(data, dict):
            raise TypeError("Can only merge from a dictionary.")
        for key, value in data.items():
            if skip_include and key == "include":
                continue
            if self._should_apply_merge_override(key, value):
                self.set_value(key, value)
            elif isinstance(value, dict):
                if self.has_attr(key) and isinstance(getattr(self, key), Config):
                    getattr(self, key).merge_from_dict(value)
                else:
                    setattr(self, key, Config().merge_from_dict(value))
            else:
                setattr(self, key, self._to_config_value(value))
        return self

    def _should_apply_merge_override(self, key, value):
        if not isinstance(key, str):
            return False
        if "[" in key or "]" in key:
            return True
        if value == "@delete":
            return self._override_target_exists(key)
        if isinstance(value, str):
            if (value.startswith("@@") or value.startswith("@base64:")) and self._override_target_exists(key):
                return True
            if value.startswith("+") and self._override_target_is_list(key):
                return True
        return False

    def _override_target_exists(self, key):
        try:
            tokens = self._parse_override_key(key)
            current = self
            for token in tokens[:-1]:
                if isinstance(token, str):
                    if not isinstance(current, Config) or not current.has_attr(token):
                        return False
                    current = getattr(current, token)
                else:
                    if not isinstance(current, list):
                        return False
                    index = self._normalize_list_index(token["index"], len(current), False)
                    if token["size"] != 1:
                        return False
                    current = current[index]

            target = tokens[-1]
            if isinstance(target, str):
                return isinstance(current, Config) and current.has_attr(target)
            if not isinstance(current, list):
                return False
            self._normalize_list_index(target["index"], len(current), target["size"] == 0)
            return True
        except Exception:
            return False

    def _override_target_is_list(self, key):
        try:
            tokens = self._parse_override_key(key)
            current = self
            for token in tokens[:-1]:
                if isinstance(token, str):
                    if not isinstance(current, Config) or not current.has_attr(token):
                        return False
                    current = getattr(current, token)
                else:
                    if not isinstance(current, list):
                        return False
                    index = self._normalize_list_index(token["index"], len(current), False)
                    if token["size"] != 1:
                        return False
                    current = current[index]
            target = tokens[-1]
            return isinstance(target, str) and isinstance(current, Config) and current.has_attr(target) and isinstance(getattr(current, target), list)
        except Exception:
            return False

    def set_value(self, key, value):
        """
        Set a value in the configuration. Support extending list with string value
            if the original value is a list and the new value is a string with '+' prefix.
        Also support list item overrides with ``path[index[:size]]`` syntax.
        :param key: Key of the value to set. eg a.b.c
        :param value: Value to set.
        :return: self
        """
        if getattr(self, "_freeze", False) == True:
            raise RuntimeError("Configuration is frozen, cannot modify.")
        tokens = self._parse_override_key(key)
        value = self._decode_override_value(value)
        self._set_value_by_tokens(tokens, value)
        return self

    def _set_value_by_tokens(self, tokens, value):
        current = self
        for token in tokens[:-1]:
            if isinstance(token, str):
                current = self._get_config_attr(current, token)
            else:
                current = self._get_list_item(current, token, allow_insert=False)

        target = tokens[-1]
        if isinstance(target, str):
            self._set_attr_value(current, target, value)
        elif value is _DELETE_OVERRIDE:
            self._delete_list_items(current, target)
        else:
            self._set_list_items(current, target, value)

    def _set_attr_value(self, current, target_key, value):
        if not isinstance(current, Config):
            raise TypeError(f"Cannot set attribute '{target_key}' on non-Config value.")
        if value is _DELETE_OVERRIDE:
            if not current.has_attr(target_key):
                raise AttributeError(f"Configuration does not have attribute '{target_key}'")
            delattr(current, target_key)
            return
        old_value = getattr(current, target_key, None)
        if isinstance(old_value, list) and isinstance(value, str):
            if value.startswith('+'):
                value = old_value + [value[1:]]
        setattr(current, target_key, self._to_config_value(value))

    def _get_config_attr(self, current, attr_name):
        if not isinstance(current, Config):
            raise TypeError(f"Cannot access attribute '{attr_name}' on non-Config value.")
        if not current.has_attr(attr_name):
            raise AttributeError(f"Configuration does not have attribute '{attr_name}'")
        return getattr(current, attr_name)

    def _get_list_item(self, current, index_token, allow_insert):
        if not isinstance(current, list):
            raise TypeError("Configuration override target is not a list.")
        index = self._normalize_list_index(index_token["index"], len(current), allow_insert)
        if index_token["size"] != 1:
            raise ValueError("Only single list indexes can be used before the final override path token.")
        return current[index]

    def _set_list_items(self, current, index_token, value):
        if not isinstance(current, list):
            raise TypeError("Configuration override target is not a list.")
        index = self._normalize_list_index(index_token["index"], len(current), index_token["size"] == 0)
        if index_token["size"] == 0:
            current.insert(index, self._to_config_value(value))
            return
        end = index + index_token["size"]
        if end > len(current):
            raise IndexError("List override range is out of range.")
        current[index:end] = [self._to_config_value(value) for _ in range(index_token["size"])]

    def _delete_list_items(self, current, index_token):
        if not isinstance(current, list):
            raise TypeError("Configuration override target is not a list.")
        index = self._normalize_list_index(index_token["index"], len(current), False)
        if index_token["size"] == 0:
            return
        end = index + index_token["size"]
        if end > len(current):
            raise IndexError("List override range is out of range.")
        del current[index:end]

    def _normalize_list_index(self, index, list_len, allow_end):
        if index < 0:
            index += list_len
        max_index = list_len if allow_end else list_len - 1
        if index < 0 or index > max_index:
            raise IndexError("List override index is out of range.")
        return index

    def _to_config_value(self, value):
        if isinstance(value, dict):
            return Config(value)
        if isinstance(value, list):
            return [self._to_config_value(item) for item in value]
        return value

    def _parse_override_key(self, key):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Configuration override key must be a non-empty string.")
        tokens = []
        for part in key.split('.'):
            if not part:
                raise ValueError(f"Invalid configuration override key '{key}'.")
            name, selectors = self._parse_override_key_part(part, key)
            if name:
                tokens.append(name)
            tokens.extend(selectors)
        return tokens

    def _parse_override_key_part(self, part, full_key):
        match = re.match(r"^([^\[\]]*)", part)
        name = match.group(1)
        rest = part[len(name):]
        selectors = []
        while rest:
            match = re.match(r"^\[(-?\d+)(?::(\d*))?\]", rest)
            if not match:
                raise ValueError(f"Invalid list override syntax in key '{full_key}'.")
            size = 1 if match.group(2) is None or match.group(2) == "" else int(match.group(2))
            selectors.append({"index": int(match.group(1)), "size": size})
            rest = rest[match.end():]
        if not name and not selectors:
            raise ValueError(f"Invalid configuration override key '{full_key}'.")
        return name, selectors

    def _decode_override_value(self, value):
        if not isinstance(value, str):
            return value
        if value == "@delete":
            return _DELETE_OVERRIDE
        if value.startswith("@base64:"):
            return self._str_b64_decode(value[len("@base64:"):])
        return self._unescape_override_string(value)

    def _unescape_override_string(self, value):
        result = []
        index = 0
        while index < len(value):
            if value[index] != "@":
                result.append(value[index])
                index += 1
                continue
            if index + 1 < len(value) and value[index + 1] == "@":
                result.append("@")
                index += 2
                continue
            raise ValueError("Single '@' is reserved in override values; use '@@' for a literal '@'.")
        return "".join(result)

    def _str_b64_decode(self, value):
        try:
            decoded_bytes = base64.b64decode(value)
            return decoded_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Failed to decode base64 string: {e}")

    def get_value(self, key, default=None):
        """
        Get a value from the configuration.
        :param key: Key of the value to get. eg a.b.c
        :param default: Default value to return if the key does not exist.
        :return: Value of the key if it exists, otherwise default.
        """
        keys = key.split('.')
        current = self
        for k in keys[:-1]:
            if not current.has_attr(k):
                raise AttributeError(f"Configuration does not have attribute '{k}'")
            current = getattr(current, k)
        if not current.has_attr(keys[-1]):
            return default
        return getattr(current, keys[-1], default)

    def __getitem__(self, key):
        """
        Get a value from the configuration using dictionary-like access.
        :param key: Key of the value to get. eg a.b.c
        :return: Value of the key if it exists, otherwise raises KeyError.
        """
        if not isinstance(key, str):
            raise TypeError("Key must be a string.")
        assert self.has_attr(key), f"Configuration does not have attribute '{key}'"
        return self.get_value(key)

    def set_values(self, values):
        """
        Set multiple values in the configuration.
        :param values: Dictionary of key-value pairs to set.
        :return: self
        """
        if values is None:
            return self
        if not isinstance(values, list):
            values = [values]
        for v in values:
            if not isinstance(v, dict):
                raise TypeError("Configuration override values must be a dict or a list of dicts.")
            for key, value in v.items():
                self.set_value(key, value)
        return self


def build_runtime_config(
    cfg: Config,
    runtime_config_keys: Optional[List[str]] = None,
    launch_context: Optional[Dict[str, Any]] = None,
    plugin_python_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the non-secret runtime snapshot shared with workspace consumers."""
    if not isinstance(cfg, Config):
        raise TypeError("Runtime config can only be built from a Config instance.")

    runtime_options = cfg.get_value("runtime_options", None)
    if runtime_options is None:
        runtime_options = {}
    elif isinstance(runtime_options, Config):
        runtime_options = runtime_options.as_dict()
    elif isinstance(runtime_options, dict):
        runtime_options = dict(runtime_options)
    else:
        raise TypeError("Configuration value 'runtime_options' must be a mapping.")

    template_values = cfg.__dict__.get("_temp_cfg")
    if not isinstance(template_values, dict):
        raise ValueError("Configuration is missing resolved DUT/OUT template values.")
    dut = template_values.get("DUT")
    output = template_values.get("OUT")
    if not isinstance(dut, str) or not dut.strip():
        raise ValueError("Resolved configuration value 'DUT' must be a non-empty string.")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("Resolved configuration value 'OUT' must be a non-empty string.")
    try:
        test_output_dir = cfg.get_value("tools.RunTestCases.test_dir", None)
    except AttributeError:
        test_output_dir = None
    if not isinstance(test_output_dir, str) or not test_output_dir.strip():
        # workflows that run no tests declare no test dir; the snapshot then
        # omits test_output_dir for its workspace consumers
        test_output_dir = None
    ucagent_python_path = str(_current_ucagent_python_path())
    if not (Path(ucagent_python_path) / "ucagent" / "__init__.py").is_file():
        raise ValueError(
            "Cannot resolve the current UCAgent Python import path."
        )
    plugin_import_roots = [
        str(path) for path in (plugin_python_paths or []) if str(path).strip()
    ]
    for plugin_root_text in plugin_import_roots:
        if not Path(plugin_root_text).is_absolute() or not Path(plugin_root_text).is_dir():
            raise ValueError(
                "Plugin Python import path must be an existing absolute "
                f"directory: {plugin_root_text}"
            )

    result = {
        "schema_version": 1,
        "DUT": dut,
        "OUT": output,
        "ucagent_python_path": ucagent_python_path,
        "runtime_options": runtime_options,
    }
    if test_output_dir is not None:
        result["test_output_dir"] = test_output_dir
        # only test-running workflows publish the shared report pointer
        result["current_test_report"] = CURRENT_TEST_REPORT_RELATIVE_PATH
    if plugin_import_roots:
        # plugin import roots feed skill-script PYTHONPATH resolution
        result["plugin_python_paths"] = plugin_import_roots
    plugin_options = {}
    for key in runtime_config_keys or []:
        value = cfg.get_value(key, None)
        if isinstance(value, bool) or value is None or isinstance(value, str):
            plugin_options[key] = value
        elif isinstance(value, int):
            plugin_options[key] = value
        elif isinstance(value, float) and value == value and abs(value) != float("inf"):
            plugin_options[key] = value
        else:
            raise ValueError(
                f"Declared runtime config value {key!r} must be a finite JSON scalar."
            )
    if plugin_options:
        result["plugin_options"] = plugin_options
    if launch_context is not None:
        result["launch_context"] = dict(launch_context)
    return result


def validate_runtime_config(data: Any) -> Dict[str, Any]:
    """Validate a runtime snapshot before it is consumed."""
    if not isinstance(data, dict):
        raise ValueError("Resolved runtime config must be a JSON object.")
    if data.get("schema_version") != 1:
        raise ValueError("Resolved runtime config has an unsupported schema_version.")
    for key in ("DUT", "OUT"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(
                f"Resolved runtime config value '{key}' must be a non-empty string."
            )
    if "test_output_dir" in data:
        test_output_dir = data["test_output_dir"]
        if not isinstance(test_output_dir, str) or not test_output_dir.strip():
            raise ValueError(
                "Resolved runtime config value 'test_output_dir' must be a non-empty string."
            )
    if "current_test_report" in data:
        if data["current_test_report"] != CURRENT_TEST_REPORT_RELATIVE_PATH:
            raise ValueError(
                "Resolved runtime config value 'current_test_report' must be "
                f"'{CURRENT_TEST_REPORT_RELATIVE_PATH}'."
            )
        if "test_output_dir" not in data:
            raise ValueError(
                "Resolved runtime config value 'current_test_report' requires "
                "'test_output_dir': workflows without a test dir publish no "
                "test report."
            )
    ucagent_python_path = data.get("ucagent_python_path")
    if not isinstance(ucagent_python_path, str) or not ucagent_python_path.strip():
        raise ValueError(
            "Resolved runtime config value 'ucagent_python_path' must be a "
            "non-empty string."
        )
    import_root = Path(ucagent_python_path)
    if not import_root.is_absolute():
        raise ValueError(
            "Resolved runtime config value 'ucagent_python_path' must be an "
            "absolute path."
        )
    if not (import_root / "ucagent" / "__init__.py").is_file():
        raise ValueError(
            "Resolved runtime config value 'ucagent_python_path' does not contain "
            "an importable ucagent package. Restart UCAgent for this workspace to "
            "regenerate .ucagent/runtime_config.json."
        )
    if import_root.resolve() != _current_ucagent_python_path():
        raise ValueError(
            "Resolved runtime config value 'ucagent_python_path' does not match the "
            "currently running UCAgent package. Restart UCAgent for this workspace "
            "to regenerate .ucagent/runtime_config.json."
        )
    plugin_python_paths = data.get("plugin_python_paths")
    if plugin_python_paths is not None:
        if not isinstance(plugin_python_paths, list) or not plugin_python_paths:
            raise ValueError(
                "Resolved runtime config value 'plugin_python_paths' must be a "
                "non-empty list."
            )
        for plugin_root_text in plugin_python_paths:
            if (
                not isinstance(plugin_root_text, str)
                or not plugin_root_text.strip()
                or not Path(plugin_root_text).is_absolute()
            ):
                raise ValueError(
                    "Resolved runtime config value 'plugin_python_paths' must "
                    "contain non-empty absolute path strings."
                )
            if not Path(plugin_root_text).is_dir():
                raise ValueError(
                    f"Resolved runtime config plugin Python path was not found: "
                    f"{plugin_root_text}. Restart UCAgent for this workspace "
                    "to regenerate .ucagent/runtime_config.json."
                )

    runtime_options = data.get("runtime_options")
    if not isinstance(runtime_options, dict):
        raise ValueError("Resolved runtime config has no runtime_options mapping.")
    plugin_options = data.get("plugin_options")
    if plugin_options is not None:
        if not isinstance(plugin_options, dict):
            raise ValueError("Resolved runtime config plugin_options must be a mapping.")
        for key, value in plugin_options.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Resolved runtime plugin option keys must be non-empty strings.")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError(
                    f"Resolved runtime plugin option {key!r} must be a JSON scalar."
                )
            if isinstance(value, float) and (
                value != value or abs(value) == float("inf")
            ):
                raise ValueError(
                    f"Resolved runtime plugin option {key!r} must be finite."
                )
    launch_context = data.get("launch_context")
    if launch_context is not None:
        if not isinstance(launch_context, dict):
            raise ValueError("Resolved runtime config launch_context must be a mapping.")
        expected_launch_keys = {
            "config_file",
            "plugin_selectors",
            "plugin_workflow",
            "workflow_config_file",
        }
        if set(launch_context) != expected_launch_keys:
            raise ValueError(
                "Resolved runtime launch_context must contain exactly config_file, "
                "plugin_selectors, plugin_workflow, and workflow_config_file."
            )
        for key in ("config_file", "plugin_workflow", "workflow_config_file"):
            value = launch_context[key]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(
                    f"Resolved runtime launch_context.{key} must be null or a non-empty string."
                )
        selectors = launch_context["plugin_selectors"]
        if not isinstance(selectors, list) or any(
            not isinstance(value, str) or not value.strip() for value in selectors
        ):
            raise ValueError(
                "Resolved runtime launch_context.plugin_selectors must be a list of non-empty strings."
            )
    return data


def save_runtime_config(
    workspace: str,
    cfg: Config,
    runtime_config_keys: Optional[List[str]] = None,
    launch_context: Optional[Dict[str, Any]] = None,
    plugin_python_paths: Optional[List[str]] = None,
) -> Path:
    """Persist resolved runtime values for skills and other workspace consumers."""
    runtime_path = Path(
        get_abs_path_cwd_ucagent(workspace, RUNTIME_CONFIG_FILENAME)
    )
    runtime_data = validate_runtime_config(
        build_runtime_config(
            cfg,
            runtime_config_keys=runtime_config_keys,
            launch_context=launch_context,
            plugin_python_paths=plugin_python_paths,
        )
    )
    save_json_file(str(runtime_path), runtime_data)
    return runtime_path


def load_runtime_config(workspace: str) -> Dict[str, Any]:
    """Load the shared resolved runtime snapshot from a workspace."""
    runtime_path = Path(workspace) / ".ucagent" / RUNTIME_CONFIG_FILENAME
    if not runtime_path.is_file():
        raise FileNotFoundError(
            f"Resolved runtime config not found: {runtime_path}. "
            "Start UCAgent for this workspace before using runtime consumers."
        )
    return validate_runtime_config(load_json_file(str(runtime_path)))


def _current_test_report_path(workspace: str) -> Path:
    """Return the workspace-local report shared by test consumers and Skills."""
    runtime_config = load_runtime_config(workspace)
    relative = runtime_config.get("current_test_report")
    if not relative:
        raise ValueError(
            "Runtime config declares no 'current_test_report': workflows "
            "without a test dir publish no current test report."
        )
    return Path(workspace) / relative


def clear_current_test_report(workspace: str) -> None:
    """Invalidate a previous stage's report when a stage becomes active."""
    target = Path(workspace) / CURRENT_TEST_REPORT_RELATIVE_PATH
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def save_current_test_report(
    workspace: str,
    report: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Path:
    """Publish the latest structured test report for runtime consumers.

    The report is deliberately kept outside the DUT output directory so a Skill
    cannot accidentally bind itself to a stage-private or historical report.
    ``context`` is diagnostic metadata only; the actual test report remains under
    the stable ``report`` key.
    """
    if not isinstance(report, dict):
        raise TypeError("Current test report must be a mapping.")
    if context is not None and not isinstance(context, dict):
        raise TypeError("Current test report context must be a mapping.")
    target = _current_test_report_path(workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CURRENT_TEST_REPORT_SCHEMA_VERSION,
        "report": report,
        "context": context or {},
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    save_json_file(str(temporary), payload)
    os.replace(temporary, target)
    return target


def load_current_test_report(workspace: str) -> Dict[str, Any]:
    """Load and validate the latest structured test report for a workspace."""
    target = _current_test_report_path(workspace)
    if not target.is_file():
        raise FileNotFoundError(
            f"Current test report not found: {target}. Run the current stage's "
            "real test cases with Check or RunTestCases before using a test-report Skill."
        )
    payload = load_json_file(str(target))
    if not isinstance(payload, dict):
        raise ValueError(f"Current test report {target} must be a JSON object.")
    if payload.get("schema_version") != CURRENT_TEST_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"Current test report {target} has an unsupported schema_version."
        )
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError(f"Current test report {target} has no report object.")
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise ValueError(f"Current test report {target} has invalid context metadata.")
    return payload


def find_file_in_paths(filename, search_paths):
    """
    Search for a file in a list of directories.
    :param filename: Name of the file to search for.
    :param search_paths: List of directories to search in.
    :return: Full path to the file if found, otherwise None.
    """
    if filename.startswith('/'):
        # If the filename is an absolute path, return it directly
        if os.path.isfile(filename):
            return filename
        else:
            return None
    for path in search_paths:
        full_path = os.path.join(path, filename)
        if os.path.isfile(full_path):
            return full_path
    return None


def load_yaml_with_env_vars(file_path):
    """Load YAML after environment-variable substitution.

    Supports negated boolean scalars like ``not true`` and ``-false``.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        rendered_content = replace_bash_var(content, os.environ)
        return yaml.load(rendered_content, Loader=UCAgentConfigLoader)


def _normalize_include_value(include_value, config_file):
    if include_value is None:
        return []
    if isinstance(include_value, str):
        return [include_value]
    if not isinstance(include_value, list):
        raise TypeError(f"Config include in '{config_file}' must be a string or a list of strings.")
    for include_file in include_value:
        if not isinstance(include_file, str) or not include_file.strip():
            raise TypeError(f"Config include in '{config_file}' must be a string or a list of strings.")
    return include_value


def _resolve_include_file(include_file, parent_config_file):
    include_file = os.path.expanduser(include_file)
    if os.path.isabs(include_file):
        if os.path.isfile(include_file):
            return os.path.abspath(include_file)
        raise FileNotFoundError(f"Included config file '{include_file}' not found.")

    parent_dir = os.path.dirname(os.path.abspath(parent_config_file))
    found_file = find_file_in_paths(include_file, [parent_dir, os.getcwd()])
    if found_file is not None:
        return os.path.abspath(found_file)
    raise FileNotFoundError(
        f"Included config file '{include_file}' not found relative to "
        f"'{parent_dir}' or current working directory '{os.getcwd()}'."
    )


# Mission prompt keys that a task workflow loaded through the framework
# `workflow` pointer extends instead of replacing: the workflow's system prompt
# is appended to the framework's and the tips lists are concatenated.
WORKFLOW_APPEND_KEYS = (
    "mission.prompt.system",
    "mission.prompt.tips.always",
    "mission.prompt.tips.random",
)


def _get_config_path_values(cfg, dotted_keys):
    """Read current values for dotted key paths; unreachable paths map to None."""
    values = {}
    for dotted_key in dotted_keys:
        try:
            values[dotted_key] = cfg.get_value(dotted_key)
        except AttributeError:
            values[dotted_key] = None
    return values


def _set_config_path_value(cfg, dotted_key, value):
    """Set a value at a dotted key path; intermediate sections must exist."""
    keys = dotted_key.split(".")
    target = cfg
    for key in keys[:-1]:
        target = getattr(target, key)
    setattr(target, keys[-1], value)


def _merge_config_file(cfg, config_file, loaded_configs, loading_stack=None, append_keys=None):
    """
    Merge a config file into cfg, honoring include directives and load dedup.
    :param append_keys: Dotted keys whose str/list values from this file are
        appended to the existing values instead of replacing them; include
        directives never inherit this behavior.
    """
    config_file = os.path.abspath(config_file)
    if config_file in loaded_configs:
        info(f"Config file '{config_file}' already loaded, ignore.")
        return cfg
    if loading_stack is None:
        loading_stack = []
    if config_file in loading_stack:
        cycle = loading_stack[loading_stack.index(config_file):] + [config_file]
        raise ValueError(f"Config include cycle detected: {' -> '.join(cycle)}")

    loading_stack.append(config_file)
    try:
        data = load_yaml_with_env_vars(config_file) or {}
        if not isinstance(data, dict):
            raise TypeError(f"Config file '{config_file}' must contain a YAML mapping.")

        for include_file in _normalize_include_value(data.get("include"), config_file):
            include_config_file = _resolve_include_file(include_file, config_file)
            _merge_config_file(cfg, include_config_file, loaded_configs, loading_stack)

        append_bases = _get_config_path_values(cfg, append_keys or ())

        cfg.merge_from_dict(data, skip_include=True)

        for dotted_key, base in append_bases.items():
            try:
                merged = cfg.get_value(dotted_key)
            except AttributeError:
                merged = None
            if base is None or merged is None or merged == base:
                continue
            if isinstance(base, str) and isinstance(merged, str):
                value = base.rstrip("\n") + "\n\n" + merged.strip("\n") + "\n"
            elif isinstance(base, list) and isinstance(merged, list):
                value = base + merged
            else:
                raise TypeError(
                    f"Cannot append configuration value of '{dotted_key}' from "
                    f"'{config_file}': expected str+str or list+list, got "
                    f"{type(base).__name__}+{type(merged).__name__}."
                )
            _set_config_path_value(cfg, dotted_key, value)

        loaded_configs.append(config_file)
        info(f"Load config from '{config_file}' completed.")
        return cfg
    finally:
        loading_stack.pop()


def resolve_workflow_pointer_path(workflow_selector, lang):
    """Resolve the 'workflow' pointer selector to an absolute config path.

    Relative selectors resolve against the lang config dir first, then the
    repository root, so the pointer can name workflow configs owned by
    in-repo plugin projects (plugins/<name>/config/...). A
    "<importable-module>:<relative-path>" selector resolves inside an
    installed plugin package, which keeps the pointer working when the
    repository tree is absent (pip-installed UCAgent plus a plugin wheel).
    """
    if os.path.isabs(workflow_selector):
        return os.path.abspath(workflow_selector)
    module_match = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*):(.+)$", workflow_selector)
    if module_match:
        spec = importlib.util.find_spec(module_match.group(1))
        if spec is not None:
            base = (
                next(iter(spec.submodule_search_locations))
                if spec.submodule_search_locations
                else os.path.dirname(spec.origin)
            )
            return os.path.abspath(os.path.join(base, module_match.group(2)))
    config_dir = os.path.dirname(os.path.abspath(__file__))
    lang_dir_candidate = os.path.abspath(
        os.path.join(config_dir, "../lang", lang, "config", workflow_selector)
    )
    if os.path.isfile(lang_dir_candidate):
        return lang_dir_candidate
    return os.path.abspath(
        os.path.join(config_dir, "../..", workflow_selector)
    )


def _find_user_config_file(config_file, user_home, lang):
    """Resolve the explicit --config file (default: config.yaml) against the
    standard search paths: cwd, ~/.ucagent/, the lang config dir, repo root.
    """
    target_file = config_file
    if config_file is None:
        target_file = 'config.yaml'  # Default configuration file
    return find_file_in_paths(target_file, [os.getcwd(),
                                             os.path.join(user_home, '.ucagent/'),
                                             os.path.join(os.path.dirname(__file__), f"../lang/{lang}/config/"),
                                             os.path.join(os.path.dirname(__file__), "../..")
                                             ])


def get_config(
    config_file=None,
    cfg_override=None,
    workspace=None,
    workflow_config_file=None,
):
    """
    Get the configuration for the agent.
    :param config_file: Path to the explicit user configuration file.
    :param cfg_override: Final key/value overrides.
    :param workspace: Workspace whose local settings are loaded.
    :param workflow_config_file: Optional plugin workflow baseline config.
    :return: Configuration dictionary.

    Load order: setting.yaml layers -> lang default.yaml (framework prompts) ->
    the task workflow baseline (an explicitly selected plugin workflow, or the
    default workflow the launcher resolved from the 'workflow' selector),
    whose mission system/tips prompts append to the framework layer ->
    workspace config -> explicit config file -> overrides.

    The 'workflow' key is launcher-side selection data, not something
    get_config interprets: resolve it with resolve_default_task_workflow (or,
    in the cli, the same fully merged read) and pass the resulting file as
    workflow_config_file. Callers passing None get a framework-only config.
    """
    # ignore repeated loaded configs
    loaded_configs = []

    # 1. load default config
    default_config_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../setting.yaml"))
    assert os.path.isfile(default_config_file), f"Default configuration file '{default_config_file}' not found."
    cfg = Config()
    _merge_config_file(cfg, default_config_file, loaded_configs)

    # 2. load user config
    user_home = os.path.expanduser('~')
    user_config_file = os.path.abspath(os.path.join(user_home, '.ucagent/setting.yaml'))
    if os.path.isfile(user_config_file):
        _merge_config_file(cfg, user_config_file, loaded_configs)
    else:
        info(f"User config file '{user_config_file}' not found, touch an empty one.")
        os.makedirs(os.path.dirname(user_config_file), exist_ok=True)
        with open(user_config_file, 'w') as f:
            f.write("# UCAgent user configuration file\n")
        loaded_configs.append(user_config_file)

    # 3. load lang config
    lang = cfg.get_value('lang', 'zh')
    lang_config_file = os.path.abspath(os.path.join(os.path.dirname(__file__), f"../lang/{lang}/config/default.yaml"))
    info(f"Load config from '{lang_config_file}'")
    assert os.path.isfile(lang_config_file), f"Language configuration file '{lang_config_file}' not found."
    _merge_config_file(cfg, lang_config_file, loaded_configs)

    # framework mission prompts before the task workflow layer extends them;
    # the workflow baseline appends to these values instead of replacing them
    framework_mission_prompts = _get_config_path_values(cfg, WORKFLOW_APPEND_KEYS)

    # 4. load the task workflow baseline: an explicitly selected plugin
    # workflow, or the default workflow the launcher resolved from the
    # 'workflow' selector and passed here as a plain file path. Its mission
    # prompts extend the framework values directly. The 'workflow' key
    # itself is launcher-side selection data — get_config never interprets
    # it, so callers passing workflow_config_file=None get a framework-only
    # config.
    if workflow_config_file is not None:
        workflow_config_path = os.path.abspath(os.fspath(workflow_config_file))
        if not os.path.isfile(workflow_config_path):
            raise FileNotFoundError(
                f"Workflow config file '{workflow_config_file}' was not found."
            )
        if workflow_config_path not in loaded_configs:
            for dotted_key, framework_value in framework_mission_prompts.items():
                if framework_value is not None:
                    _set_config_path_value(cfg, dotted_key, framework_value)
        _merge_config_file(
            cfg, workflow_config_path, loaded_configs,
            append_keys=WORKFLOW_APPEND_KEYS,
        )

    # 5. load workspace config
    if workspace is not None:
        cwd_setting_file = get_abs_path_cwd_ucagent(workspace, "setting.yaml")
        if os.path.isfile(cwd_setting_file):
            _merge_config_file(cfg, cwd_setting_file, loaded_configs)
        else:
            info(f"Workspace config file '{cwd_setting_file}' not found, ignore.")

    # 6. find user specified config file
    user_config_file_path = _find_user_config_file(config_file, user_home, lang)
    if config_file is not None:
        assert user_config_file_path is not None, f"Config file '{config_file}' not found in current directory or default config path."
    if user_config_file_path is None:
        info(f"Default user config file '{config_file}' not found, ignore.")
    else:
        user_config_file_path = os.path.abspath(user_config_file_path)
        _merge_config_file(cfg, user_config_file_path, loaded_configs)

    # 7. set override values
    cfg.set_values(cfg_override)
    object.__setattr__(cfg, "_loaded_config_files", list(loaded_configs))
    return cfg.freeze()


def resolve_default_task_workflow(config_file=None, cfg_override=None,
                                  workspace=None, lang=None):
    """Decide which file the default task workflow is: read the fully merged
    config's 'workflow' selector and resolve it to a path.

    Any later layer (workspace config, --config, CLI overrides) may redefine
    or null the selector — None means framework-only. Selection only: pass
    the result to get_config as workflow_config_file. The launcher (cli)
    makes the same decision and additionally activates the plugin owning the
    resolved file.
    """
    cfg = get_config(config_file, cfg_override, workspace)
    if lang is None:
        lang = cfg.get_value("lang", "zh")
    selector = cfg.get_value("workflow", None)
    if not isinstance(selector, str) or not selector.strip():
        return None
    return resolve_workflow_pointer_path(selector.strip(), lang)
