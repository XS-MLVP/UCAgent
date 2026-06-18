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
from ucagent.util.config import Config, load_yaml_with_env_vars, _merge_config_file


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

    def test_repeated_cli_overrides_keep_order(self):
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

        self.assertEqual(
            args.override,
            [
                {"launch.default_args.launch_mode": "docker_swarm"},
                {"launch.cluster.image": "123123123"},
            ],
        )

    def test_repeated_keys_in_one_override_return_multiple_dicts(self):
        override = get_override_dict("a.b=+x,a.b=+y,c.d=True")

        self.assertEqual(
            override,
            [
                {"a.b": "+x"},
                {"a.b": "+y"},
                {"c.d": True},
            ],
        )

    def test_repeated_keys_across_cli_overrides_keep_order(self):
        argv = [
            "ucagent.py",
            "--as-master",
            "--override",
            "a.b=x",
            "--override",
            "a.b=",
        ]

        with mock.patch("sys.argv", argv):
            args = get_args()

        self.assertEqual(args.override, [{"a.b": "x"}, {"a.b": ""}])

    def test_set_values_applies_override_list_in_order(self):
        cfg = Config({
            "a": {
                "b": [],
            },
        })

        cfg.set_values([
            {"a.b": "+x"},
            {"a.b": "+y"},
        ])

        self.assertEqual(cfg.get_value("a.b"), ["x", "y"])

    def test_override_replaces_list_item_by_index(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": ["zero", "one", "two"],
                },
            },
        })

        cfg.set_value("a.b.c[1]", "updated")

        self.assertEqual(cfg.get_value("a.b.c"), ["zero", "updated", "two"])

    def test_override_replaces_list_range(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": ["zero", "one", "two", "three"],
                },
            },
        })

        cfg.set_value("a.b.c[1:2]", "updated")

        self.assertEqual(cfg.get_value("a.b.c"), ["zero", "updated", "updated", "three"])

    def test_override_inserts_list_item_with_zero_size(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": ["zero", "two"],
                },
            },
        })

        cfg.set_value("a.b.c[1:0]", "one")
        cfg.set_value("a.b.c[-1:0]", "before_two")

        self.assertEqual(cfg.get_value("a.b.c"), ["zero", "one", "before_two", "two"])

    def test_override_deletes_list_items(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": ["zero", "one", "two", "three", "four", "five", "six"],
                },
            },
        })

        cfg.set_values([
            {"a.b.c[-1]": "@delete"},
            {"a.b.c[5]": "@delete"},
            {"a.b.c[1:2]": "@delete"},
        ])

        self.assertEqual(cfg.get_value("a.b.c"), ["zero", "three", "four"])

    def test_override_deletes_config_attribute(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": 1,
                    "d": 2,
                },
            },
        })

        cfg.set_value("a.b.c", "@delete")

        self.assertFalse(cfg.get_value("a.b").has_attr("c"))
        self.assertEqual(cfg.as_dict(), {"a": {"b": {"d": 2}}})

    def test_override_deletes_entire_list_attribute(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": ["zero", "one"],
                    "d": "keep",
                },
            },
        })

        cfg.set_value("a.b.c", "@delete")

        self.assertFalse(cfg.get_value("a.b").has_attr("c"))
        self.assertEqual(cfg.as_dict(), {"a": {"b": {"d": "keep"}}})

    def test_override_updates_nested_config_in_list(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": [
                        {"x": {"y": 0}},
                        {"x": {"y": 1}},
                    ],
                },
            },
        })

        cfg.set_value("a.b.c[-1].x.y", 2)

        self.assertEqual(cfg.get_value("a.b.c")[-1].x.y, 2)
        self.assertEqual(cfg.as_dict()["a"]["b"]["c"][-1]["x"]["y"], 2)

    def test_override_inserts_dict_as_config_list_item(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": [],
                },
            },
        })

        cfg.set_value("a.b.c[0:0]", {"x": {"y": 1}})
        cfg.set_value("a.b.c[0].x.y", 2)

        self.assertEqual(cfg.as_dict()["a"]["b"]["c"], [{"x": {"y": 2}}])

    def test_override_uses_at_delete_only_as_reserved_directive(self):
        cfg = Config({
            "a": {
                "b": {
                    "c": ["keep"],
                    "literal": "",
                },
            },
        })

        cfg.set_value("a.b.literal", "@@delete")
        cfg.set_value("a.b.c[0]", "@@delete")

        self.assertEqual(cfg.get_value("a.b.literal"), "@delete")
        self.assertEqual(cfg.get_value("a.b.c"), ["@delete"])

    def test_override_rejects_unescaped_at_in_value(self):
        cfg = Config({
            "a": {
                "b": "",
            },
        })

        with self.assertRaises(ValueError):
            cfg.set_value("a.b", "email@example.com")

    def test_override_decodes_base64_directive(self):
        cfg = Config({
            "a": {
                "b": "",
            },
        })

        cfg.set_value("a.b", "@base64:aGVsbG9AZXhhbXBsZS5jb20=")

        self.assertEqual(cfg.get_value("a.b"), "hello@example.com")

    def test_override_rejects_legacy_base64_prefix(self):
        cfg = Config({
            "a": {
                "b": "",
            },
        })

        with self.assertRaises(ValueError):
            cfg.set_value("a.b", "base64@aGVsbG8=")

    def test_override_accepts_unquoted_base64_directive_with_padding(self):
        override = get_override_dict(
            "backend.codex.cfg_bash_cmd=@base64:K2VjaG8ge3siT1BFTkFJX0FQSV9LRVkiOntPUEVOQUlfQVBJX0tFWX19fSA+IH4vLmNvZGV4L2F1dGguanNvbg=="
        )

        self.assertEqual(
            override["backend.codex.cfg_bash_cmd"],
            "@base64:K2VjaG8ge3siT1BFTkFJX0FQSV9LRVkiOntPUEVOQUlfQVBJX0tFWX19fSA+IH4vLmNvZGV4L2F1dGguanNvbg==",
        )

    def test_override_still_parses_literal_values(self):
        override = get_override_dict("a.b=123,c.d=True,e.f=['x']")

        self.assertEqual(override["a.b"], 123)
        self.assertIs(override["c.d"], True)
        self.assertEqual(override["e.f"], ["x"])

    def test_yaml_include_merges_in_order_and_applies_list_operations(self):
        config_dir = os.path.join(current_dir, "test_data", "configs")
        cfg = Config()
        loaded_configs = []

        _merge_config_file(cfg, os.path.join(config_dir, "new.yaml"), loaded_configs)

        self.assertEqual(
            cfg.as_dict(),
            {
                "app": {
                    "name": "base",
                    "include": "literal-app-include",
                    "title": "final-title",
                    "items": ["start", "zero", "one-updated", "inserted-before-two", "two"],
                    "nested": [
                        {
                            "name": "beta",
                            "tags": ["purple", "navy"],
                        }
                    ],
                },
            },
        )
        self.assertNotIn("include", cfg.as_dict())
        self.assertEqual(cfg.get_value("app.include"), "literal-app-include")
        self.assertEqual(
            [os.path.basename(path) for path in loaded_configs],
            ["base.yaml", "extra.yaml", "new.yaml"],
        )

    def test_yaml_include_supports_absolute_paths_and_cwd_fallback(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            configs_dir = os.path.join(temp_dir, "configs")
            os.makedirs(configs_dir, exist_ok=True)

            cwd_include_file = os.path.join(temp_dir, "shared.yaml")
            with open(cwd_include_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "from_cwd:\n"
                    "  value: cwd\n"
                )

            absolute_include_file = os.path.join(temp_dir, "absolute.yaml")
            with open(absolute_include_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "from_absolute:\n"
                    "  value: absolute\n"
                )

            target_file = os.path.join(configs_dir, "main.yaml")
            with open(target_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "include:\n"
                    "  - shared.yaml\n"
                    f"  - {absolute_include_file}\n"
                    "from_main:\n"
                    "  value: main\n"
                )

            os.chdir(temp_dir)
            try:
                cfg = Config()
                loaded_configs = []
                _merge_config_file(cfg, target_file, loaded_configs)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(
            cfg.as_dict(),
            {
                "from_cwd": {"value": "cwd"},
                "from_absolute": {"value": "absolute"},
                "from_main": {"value": "main"},
            },
        )
        self.assertEqual(
            [os.path.basename(path) for path in loaded_configs],
            ["shared.yaml", "absolute.yaml", "main.yaml"],
        )

    def test_yaml_merge_keeps_dotted_literal_keys_when_not_override_paths(self):
        cfg = Config({
            "render_files": {
                "{ASSETS}/mcp_claude.json": "{CWD}/.mcp.json",
            },
        })

        cfg.merge_from_dict({
            "render_files": {
                "{ASSETS}/mcp_claude.json": "{CWD}/custom.json",
                "{ASSETS}/mcp_new.json": "{CWD}/new.json",
            },
        })

        self.assertEqual(
            cfg.as_dict()["render_files"],
            {
                "{ASSETS}/mcp_claude.json": "{CWD}/custom.json",
                "{ASSETS}/mcp_new.json": "{CWD}/new.json",
            },
        )


if __name__ == '__main__':
    unittest.main()
