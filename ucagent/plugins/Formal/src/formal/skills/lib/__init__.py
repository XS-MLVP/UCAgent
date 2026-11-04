# -*- coding: utf-8 -*-
import os
import sys

# Bootstrap: Add UCAgent project root to sys.path if not present, so we can import 'ucagent' package.
_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from .formal_paths import FormalPaths
from .formal_tools import *
from ucagent.util.log import str_error, str_info, warning, info
