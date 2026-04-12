import os

with open("examples/Formal/scripts/formal_tools.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

split_idx = 0
for i, line in enumerate(lines):
    if "# Tool: GenerateFormalEnv" in line:
        split_idx = i - 1
        break

tools_lines = lines[:split_idx]
skill_lines = lines[split_idx:]

imports = [
    '# -*- coding: utf-8 -*-\n',
    '"""AI Skills for the Formal workflow example."""\n\n',
    'import glob\n',
    'import math\n',
    'import os\n',
    'import re\n',
    'import shutil\n',
    'import subprocess\n',
    'import json\n',
    'from typing import Dict, List, Optional, Tuple\n\n',
    'from langchain_core.tools.base import ArgsSchema\n',
    'from pydantic import BaseModel, Field\n\n',
    'from ucagent.tools.fileops import BaseReadWrite\n',
    'from ucagent.tools.uctool import UCTool\n',
    'from ucagent.util.log import str_error, str_info\n\n',
    'from examples.Formal.scripts.formal_tools import (\n',
    '    parse_avis_log,\n',
    '    extract_rtl_bug_from_analysis_doc,\n',
    '    _terminate_process_tree,\n',
    '    _backup_if_exists,\n',
    ')\n\n',
]

with open("examples/Formal/scripts/formal_skill.py", "w", encoding="utf-8") as f:
    f.writelines(imports + skill_lines)

new_tools_lines = []
in_all = False
for line in tools_lines:
    if line.startswith("__all__ = ["):
        in_all = True
        new_tools_lines.append("__all__ = [\n")
        new_tools_lines.append('    "parse_avis_log",\n')
        new_tools_lines.append('    "extract_rtl_bug_from_analysis_doc",\n')
        new_tools_lines.append('    "_terminate_process_tree",\n')
        new_tools_lines.append('    "_backup_if_exists",\n')
        new_tools_lines.append("]\n")
        continue
    if in_all:
        if line.strip() == "]":
            in_all = False
        continue
    new_tools_lines.append(line)

with open("examples/Formal/scripts/formal_tools.py", "w", encoding="utf-8") as f:
    f.writelines(new_tools_lines)
