#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest
from unittest import mock

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.cli import get_args
from ucagent.util.config import Config, load_yaml_with_env_vars


class TestConfigLoader(unittest.TestCase):
    def test_load_yaml_with_negated_bool_scalars(self):
        yaml_content = """
plain_true: true
not_true: not true
minus_false: -false
list_values:
  - not false
  - -true
plain_text: not enabled
"""
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False, encoding='utf-8') as handle:
            handle.write(yaml_content)
            yaml_path = handle.name

        try:
            data = load_yaml_with_env_vars(yaml_path)
        finally:
            os.unlink(yaml_path)

        self.assertIs(data['plain_true'], True)
        self.assertIs(data['not_true'], False)
        self.assertIs(data['minus_false'], True)
        self.assertEqual(data['list_values'], [True, False])
        self.assertEqual(data['plain_text'], 'not enabled')

    def test_nested_dotted_config_paths_are_resolved_from_current_node(self):
        cfg = Config({
            "launch": {
                "default_args": {
                    "launch_mode": ["process"],
                },
            },
        })

        cfg.set_value("launch.default_args.launch_mode", "docker_swarm")

        self.assertEqual(cfg.get_value("launch.default_args.launch_mode"), "docker_swarm")

    def test_repeated_cli_overrides_are_merged(self):
        argv = [
            "ucagent.py",
            "--as-master",
            "--override",
            "launch.default_args.launch_mode='docker_swarm'",
            "--override",
            "launch.cluster.image='123123123'",
        ]

        with mock.patch("sys.argv", argv):
            args = get_args()

        self.assertEqual(args.override["launch.default_args.launch_mode"], "docker_swarm")
        self.assertEqual(args.override["launch.cluster.image"], "123123123")


if __name__ == '__main__':
    unittest.main()
