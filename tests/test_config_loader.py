#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest
import yaml
from unittest import mock

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.cli import _apply_experience_cli_overrides, get_args, get_override_dict
import ucagent.util.config as config_module
from ucagent.util.config import (
    Config,
    get_config,
    load_yaml_with_env_vars,
    resolve_experience_profile,
    _merge_config_file,
)


class TestConfigLoader(unittest.TestCase):
    def test_default_document_path_uses_template_overwrite(self):
        config_path = os.path.join(
            current_dir, "..", "ucagent", "lang", "zh", "config", "default.yaml"
        )
        config_data = load_yaml_with_env_vars(config_path)

        self.assertEqual(config_data["template_overwrite"]["DOC_PATH"], "{DUT}_Doc")
        functional_stage = next(
            stage
            for stage in config_data["stage"]
            if stage["name"] == "functional_specification_analysis"
        )
        self.assertIn("{DOC_PATH}/*.md", functional_stage["reference_files"])
        line_map_stage = next(
            stage
            for stage in functional_stage["stage"]
            if stage["name"] == "functional_line_mapping_gap_analysis"
        )
        self.assertIn(
            "{DOC_PATH}/*.md",
            line_map_stage["checker"][0]["args"]["file_list"],
        )

        config = Config(config_data)
        config.update_template({"DUT": "Adder"})
        config.update_template(config.template_overwrite.as_dict())
        resolved = config.as_dict()
        resolved_functional_stage = next(
            stage
            for stage in resolved["stage"]
            if stage["name"] == "functional_specification_analysis"
        )
        self.assertIn("Adder_Doc/*.md", resolved_functional_stage["reference_files"])

        labeled_spec_path = os.path.join(
            current_dir, "..", "ucagent", "lang", "zh", "config", "labeled_spec.yaml"
        )
        labeled_spec = load_yaml_with_env_vars(labeled_spec_path)
        self.assertIn("{DOC_PATH}/", "\n".join(labeled_spec["stage[2].task"]))
        self.assertIn(
            "{DOC_PATH}/*.md",
            labeled_spec["stage[2].checker"][1]["args"]["source_files"],
        )

    def test_default_prompt_requires_stage_local_reference_file_reads(self):
        config_path = os.path.join(
            current_dir, "..", "ucagent", "lang", "zh", "config", "default.yaml"
        )

        config = load_yaml_with_env_vars(config_path)
        system_prompt = config["mission"]["prompt"]["system"]

        self.assertIn("各stage相互独立", system_prompt)
        self.assertIn("逐一用`ReadTextFile`读取其`reference_files`", system_prompt)
        self.assertIn("`count=1`轻量复核", system_prompt)
        self.assertIn("`count=0`仅登记已读而不返回正文", system_prompt)

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

    def test_merge_from_dict_appends_nested_list_with_plus_key(self):
        cfg = Config({
            "experience": {
                "candidate_failure_hints": [
                    {"id": "base"},
                ],
            },
        })

        cfg.merge_from_dict({
            "experience": {
                "candidate_failure_hints+": [
                    {"id": "child"},
                ],
            },
        })

        self.assertEqual(
            [item.id for item in cfg.experience.candidate_failure_hints],
            ["base", "child"],
        )

    def test_merge_from_dict_appends_dotted_list_with_plus_key(self):
        cfg = Config({
            "experience": {
                "candidate_failure_hints": [
                    {"id": "base"},
                ],
            },
        })

        cfg.merge_from_dict({
            "experience.candidate_failure_hints+": [
                {"id": "dotted"},
            ],
        })

        self.assertEqual(
            [item.id for item in cfg.experience.candidate_failure_hints],
            ["base", "dotted"],
        )
        self.assertFalse(cfg.has_attr("experience.candidate_failure_hints"))

    def test_merge_from_dict_accepts_hyphenated_experience_hook_key(self):
        cfg = Config({
            "stage": [
                {"name": "example"},
            ],
        })

        cfg.merge_from_dict({
            "stage[0].experience-hook": True,
        })

        self.assertIs(cfg.stage[0].get_value("experience-hook"), True)
        self.assertFalse(cfg.stage[0].has_attr("experience_hook"))

    def test_yaml_include_searches_language_experience_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_util_dir = os.path.join(temp_dir, "ucagent", "util")
            experience_dir = os.path.join(temp_dir, "ucagent", "lang", "zh", "experience")
            os.makedirs(fake_util_dir, exist_ok=True)
            os.makedirs(experience_dir, exist_ok=True)

            shared_experience_file = os.path.join(experience_dir, "shared_exp.yaml")
            with open(shared_experience_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "experience:\n"
                    "  candidate_failure_hints:\n"
                    "    - id: shared\n"
                    "      patterns: [shared pattern]\n"
                    "      hint: shared hint\n"
                )

            target_file = os.path.join(temp_dir, "main.yaml")
            with open(target_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "include:\n"
                    "  - shared_exp.yaml\n"
                    "experience:\n"
                    "  candidate_failure_hints+:\n"
                    "    - id: local\n"
                    "      patterns: [local pattern]\n"
                    "      hint: local hint\n"
                )

            cfg = Config()
            loaded_configs = []
            fake_config_py = os.path.join(fake_util_dir, "config.py")
            with mock.patch.object(config_module, "__file__", fake_config_py):
                _merge_config_file(cfg, target_file, loaded_configs, lang="zh", user_home=temp_dir)

        self.assertEqual(
            [item.id for item in cfg.experience.candidate_failure_hints],
            ["shared", "local"],
        )
        self.assertEqual(
            [os.path.basename(path) for path in loaded_configs],
            ["shared_exp.yaml", "main.yaml"],
        )

    def test_experience_enables_profile_audit_and_distill_overrides(self):
        args = mock.Mock()
        args.override = []
        args.experience = True
        args.experience_audit = False
        args.experience_distill = False
        args.experience_out_dir = None
        args.experience_llm_max_events = None

        _apply_experience_cli_overrides(args)

        self.assertEqual(
            args.override,
            [
                {"experience.prior_rule_audit_enable": True},
                {"experience.llm_distill_enable": True},
            ],
        )

    def test_experience_audit_and_distill_are_independent(self):
        args = mock.Mock()
        args.override = []
        args.experience = False
        args.experience_audit = True
        args.experience_distill = False
        args.experience_out_dir = None
        args.experience_llm_max_events = 7

        _apply_experience_cli_overrides(args)

        self.assertEqual(
            args.override,
            [
                {"experience.prior_rule_audit_enable": True},
                {"experience.llm_distill_enable": False},
                {"experience.llm_max_events": 7},
            ],
        )

    def test_experience_distill_explicitly_disables_audit(self):
        args = mock.Mock()
        args.override = []
        args.experience = False
        args.experience_audit = False
        args.experience_distill = True
        args.experience_out_dir = None
        args.experience_llm_max_events = None

        _apply_experience_cli_overrides(args)

        self.assertEqual(
            args.override,
            [
                {"experience.prior_rule_audit_enable": False},
                {"experience.llm_distill_enable": True},
            ],
        )

    def test_experience_profile_alone_does_not_enable_artifact_processing(self):
        args = mock.Mock()
        args.override = []
        args.experience = False
        args.experience_audit = False
        args.experience_distill = False
        args.experience_profile = True
        args.experience_out_dir = "ignored"
        args.experience_llm_max_events = 7

        _apply_experience_cli_overrides(args)

        self.assertEqual(args.override, [])

    def test_removed_experience_flags_are_rejected(self):
        for flag in (
            "--extract-experience",
            "--experience-llm-distill",
            "--no-experience-log-hints",
        ):
            with mock.patch("sys.argv", ["ucagent.py", ".", "Adder", flag]):
                with self.assertRaises(SystemExit):
                    get_args()

    def test_resolve_experience_profile_matches_dut_case_insensitively(self):
        profile = resolve_experience_profile("Adder", lang="zh")

        self.assertEqual(os.path.basename(profile), "adder.yaml")

    def test_resolve_experience_profile_lists_available_profiles_when_missing(self):
        with self.assertRaisesRegex(FileNotFoundError, "Available profiles:.*adder"):
            resolve_experience_profile("unknown_dut", lang="zh")

    def test_experience_profile_loads_after_base_config_and_before_cli_override(self):
        repo_root = os.path.abspath(os.path.join(current_dir, ".."))
        profile = os.path.join(repo_root, "ucagent", "lang", "zh", "experience", "adder.yaml")
        with tempfile.TemporaryDirectory() as workspace:
            cfg = get_config(
                config_file=os.path.join(repo_root, "config.yaml"),
                workspace=workspace,
                experience_profile=profile,
                cfg_override=[{"stage[12].task": "CLI wins"}],
            )

        self.assertTrue(cfg.stage[12].get_value("experience-hook"))
        self.assertEqual(cfg.stage[12].task, "CLI wins")
        loaded_names = [os.path.basename(path) for path in cfg._loaded_config_files]
        self.assertLess(loaded_names.index("config.yaml"), loaded_names.index("adder.yaml"))

    def test_experience_stage_index_map_matches_resolved_workflow(self):
        repo_root = os.path.abspath(os.path.join(current_dir, ".."))
        with tempfile.TemporaryDirectory() as user_home:
            with mock.patch.dict(
                os.environ,
                {"HOME": user_home, "USERPROFILE": user_home},
                clear=True,
            ):
                cfg = get_config(config_file=os.path.join(repo_root, "config.yaml"))
        actual = []

        def collect(stages, prefix="stage"):
            for index, stage in enumerate(stages):
                path = f"{prefix}[{index}]"
                if stage.get_value("ignore", False):
                    continue
                substages = stage.get_value("stage", None)
                if substages:
                    collect(substages, path + ".stage")
                checker = stage.get_value("checker", [])
                output_files = stage.get_value("output_files", [])
                reference_files = stage.get_value("reference_files", [])
                is_group = not checker and not output_files and not reference_files and bool(substages)
                if not is_group:
                    actual.append({
                        "runtime_index": str(len(actual)),
                        "config_path": path,
                        "name": stage.name,
                    })

        collect(cfg.stage)
        general_path = os.path.join(
            repo_root,
            "ucagent",
            "lang",
            "zh",
            "experience",
            "general.yaml",
        )
        with open(general_path, "r", encoding="utf-8") as handle:
            expected = yaml.safe_load(handle)["experience"]["stage_index_config_tree"]

        self.assertEqual(expected, actual)


if __name__ == '__main__':
    unittest.main()
