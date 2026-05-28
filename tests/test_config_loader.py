#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest
from unittest import mock

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.cli import get_args, get_override_dict
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

    def test_override_accepts_unquoted_base64_value_with_padding(self):
        override = get_override_dict(
            "backend.codex.cfg_bash_cmd=base64@K2VjaG8ge3siT1BFTkFJX0FQSV9LRVkiOntPUEVOQUlfQVBJX0tFWX19fSA+IH4vLmNvZGV4L2F1dGguanNvbg=="
        )

        self.assertEqual(
            override["backend.codex.cfg_bash_cmd"],
            "base64@K2VjaG8ge3siT1BFTkFJX0FQSV9LRVkiOntPUEVOQUlfQVBJX0tFWX19fSA+IH4vLmNvZGV4L2F1dGguanNvbg==",
        )

    def test_override_still_parses_literal_values(self):
        override = get_override_dict("a.b=123,c.d=True,e.f=['x']")

        self.assertEqual(override["a.b"], 123)
        self.assertIs(override["c.d"], True)
        self.assertEqual(override["e.f"], ["x"])


if __name__ == '__main__':
    unittest.main()
