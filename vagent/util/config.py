#coding=utf-8

import os
import yaml
from .functions import render_template, dump_as_json
from .log import info

class Config(object):

    def __init__(self, dict=None):
        self._freeze = False
        self.from_dict(dict)

    def from_dict(self, data):
        """
        Load configuration from a dictionary.
        :param dict: Dictionary containing configuration.
        :return: None
        """
        if data is None:
            return
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, Config(value))
            elif isinstance(value, list):
                # If the value is a list, convert each item to Config if it's a dict
                setattr(self, key, [Config(item) if isinstance(item, dict) else item for item in value])
            else:
                setattr(self, key, value)

    def empty(self):
        return len(self.as_dict()) <= 1

    def as_dict(self):
        """
        Convert the configuration to a dictionary.
        :return: Dictionary representation of the configuration.
        """
        result = {}
        for key, value in self.__dict__.items():
            if key == "_freeze":
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
        for key, value in self.__dict__.items():
            if isinstance(value, Config):
                value.update_template(template_dict)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, Config):
                        item.update_template(template_dict)
                    elif isinstance(item, str):
                        nval = render_template(item, template_dict)
                        if nval != item:
                            value[i] = nval
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
        for key, value in other.__dict__.items():
            if isinstance(value, Config):
                if self.has_attr(key) and isinstance(getattr(self, key), Config):
                    getattr(self, key).merge_from(value)
                else:
                    setattr(self, key, value)
            else:
                setattr(self, key, value)
        return self

    def merge_from_dict(self, data):
        """
        Merge configuration from a dictionary.
        :param data: Dictionary containing configuration.
        :return: self
        """
        if not isinstance(data, dict):
            raise TypeError("Can only merge from a dictionary.")
        for key, value in data.items():
            if isinstance(value, dict):
                if self.has_attr(key) and isinstance(getattr(self, key), Config):
                    getattr(self, key).merge_from_dict(value)
                else:
                    setattr(self, key, Config(value))
            else:
                setattr(self, key, value)
        return self

    def set_value(self, key, value):
        """
        Set a value in the configuration.
        :param key: Key of the value to set. eg a.b.c
        :param value: Value to set.
        :return: self
        """
        keys = key.split('.')
        current = self
        for k in keys[:-1]:
            if not self.has_attr(k):
                raise AttributeError(f"Configuration does not have attribute '{k}'")
            current = getattr(current, k)
        setattr(current, keys[-1], value)
        return self

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
            if not self.has_attr(k):
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
        for key, value in values.items():
            self.set_value(key, value)
        return self


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


def get_config(config_file=None, cfg_override=None):
    """
    Get the configuration for the agent.
    :param config_file: Path to the configuration file.
    :return: Configuration dictionary.
    """
    user_config_file = config_file
    if user_config_file is None:
        user_config_file = 'config.yaml'  # Default configuration file
    user_config_file_path = find_file_in_paths(user_config_file, [os.getcwd(),
                                                             os.path.join(os.path.dirname(__file__), "../config/")
                                                      ])
    if config_file is not None:
        assert user_config_file_path is not None, f"Config file '{user_config_file}' not found in current directory or default config path."
    if user_config_file_path is None:
        info(f"Default user config file '{user_config_file}' not found, ignore.")

    # 1. load default config
    default_config_file = os.path.join(os.path.dirname(__file__), "../setting.yaml")
    assert os.path.isfile(default_config_file), f"Default configuration file '{default_config_file}' not found."
    with open(default_config_file, 'r') as file:
        default_config = yaml.safe_load(file)
        cfg = Config(default_config)
    info(f"Load config from '{default_config_file}' completed.")

    # 2. load user config
    user_home = os.path.expanduser('~')
    user_config_file = os.path.join(user_home, '.ucagent/setting.yaml')
    if os.path.isfile(user_config_file):
        with open(user_config_file, 'r') as file:
            user_config = yaml.safe_load(file)
            cfg.merge_from(Config(user_config))
        info(f"Load config from '{user_config_file}' completed.")
    else:
        info(f"User config file '{user_config_file}' not found, ignore.")

    # 3. load lang config
    lang = cfg.get_value('lang', 'zh')
    lang_config_file = os.path.join(os.path.dirname(__file__), f"../lang/{lang}/config/default.yaml")
    info(f"Load config from '{lang_config_file}'")
    assert os.path.isfile(lang_config_file), f"Language configuration file '{lang_config_file}' not found."
    with open(lang_config_file, 'r') as file:
        lang_config = yaml.safe_load(file)
        cfg.merge_from(Config(lang_config))

    # 4. load user specified config
    if user_config_file_path is not None:
        with open(user_config_file_path, 'r') as file:
            user_config = yaml.safe_load(file)
            cfg.merge_from(Config(user_config))
        info(f"Load config from '{user_config_file_path}' completed.")

    # set override values
    return cfg.set_values(cfg_override).freeze()
