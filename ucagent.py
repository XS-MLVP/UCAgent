#!/usr/bin/env python3
"""
UCAgent Command Line Interface - Direct Python Script Version

This file provides a direct Python script interface for users who prefer running:
    python ucagent.py [args...]

It imports and calls the main CLI function from ucagent.cli, providing
the same functionality as the `ucagent` command installed via pip.
"""

import os
import sys

# Add the current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Import and use the main CLI function
from ucagent.cli import main

if __name__ == "__main__":
    main()
