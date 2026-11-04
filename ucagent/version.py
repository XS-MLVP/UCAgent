# -*- coding: utf-8 -*-
"""Version information for UCAgent."""

try:
    from ._version import __version__
    # No generated ``_version`` module: this is the repository source tree,
    # not an installed distribution.
    SOURCE_TREE_RUNTIME = False
except ImportError:
    __version__ = "0.9.1+source.code"
    SOURCE_TREE_RUNTIME = True

__author__ = "XS-MLVP"
__email__ = "unitychip@bosc.ac.cn"
__description__ = "UnityChip Verification Agent - AI-powered hardware verification tool"

banner = f"""
\u001b[34m   __  __   ______    ___                           __ \u001b[0m
\u001b[34m  / / / /  / ____/   /   |   ____ _  ___    ____   / /_\u001b[0m
\u001b[34m / / / /  / /       / /| |  / __ `/ / _ \\  / __ \\ / __/\u001b[0m
\u001b[34m/ /_/ /  / /___    / ___ | / /_/ / /  __/ / / / // /_ \u001b[0m
\u001b[34m\\____/   \\____/   /_/  |_| \\__, /  \\___/ /_/ /_/ \\__/\u001b[0m
\u001b[34m                          /____/                       \u001b[0m \u001b[36mv{__version__}\u001b[0m
"""
