#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util.config import load_yaml_with_env_vars


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


if __name__ == '__main__':
    unittest.main()