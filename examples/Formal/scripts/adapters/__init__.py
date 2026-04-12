# -*- coding: utf-8 -*-
"""Formal Tool Adapters."""

from .formalmc import FormalMCAdapter
from .vcformal import VCFormalAdapter

# Tool name -> Adapter implementation
ADAPTER_REGISTRY = {
    "formalmc": FormalMCAdapter,
    "vcformal": VCFormalAdapter
}
