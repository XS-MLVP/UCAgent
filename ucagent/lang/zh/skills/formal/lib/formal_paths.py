# -*- coding: utf-8 -*-
"""Centralized formal verification path resolution."""
import yaml
import os
from dataclasses import dataclass, field

@dataclass
class FormalPaths:
    """All formal artifacts paths, derived from DUT/OUT environment variables or explicit parameters.
    
    In Checker: FormalPaths(dut=dut_name)
    In Skill scripts: FormalPaths() (auto-detects DUT from .formal_records.yaml or env)
    """
    dut: str = field(default=None)
    out: str = field(default=None)
    workspace: str = field(default_factory=lambda: os.environ.get("UCAGENT_WORKSPACE", os.getcwd()))

    def __post_init__(self):
        if self.out is None:
            self.out = os.environ.get("OUT", "formal_test")
        
        # normalize: strip trailing slash and /tests suffix
        self.out = self.out.rstrip("/")
        if self.out.endswith("/tests"):
            self.out = self.out[:-6]

        # Auto-detect dut from JSON or env
        if not self.dut:
            self.dut = os.environ.get("DUT", "")
        if not self.dut:
            json_path = os.path.join(self.workspace, self.out, ".formal_records.yaml")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    self.dut = data.get("dut", "")
                except (yaml.YAMLError, OSError):
                    pass
        if not self.dut:
            self.dut = "N/A"


    @property
    def base(self) -> str:
        return os.path.join(self.workspace, self.out)

    @property
    def tests(self) -> str:
        return os.path.join(self.base, "tests")

    @property
    def checker(self) -> str:
        return os.path.join(self.tests, f"{self.dut}_checker.sv")

    @property
    def wrapper(self) -> str:
        return os.path.join(self.tests, f"{self.dut}_wrapper.sv")

    @property
    def tcl(self) -> str:
        return os.path.join(self.tests, f"{self.dut}_formal.tcl")

    @property
    def log(self) -> str:
        return os.path.join(self.tests, "avis.log")

    @property
    def fanin(self) -> str:
        return os.path.join(self.tests, "avis", "fanin.rep")

    @property
    def spec(self) -> str:
        return os.path.join(self.base, f"03_{self.dut}_functions_and_checks.md")

    @property
    def analysis(self) -> str:
        return os.path.join(self.base, f"07_{self.dut}_env_analysis.md")

    @property
    def bug_report(self) -> str:
        return os.path.join(self.base, f"04_{self.dut}_bug_report.md")

    @property
    def static_doc(self) -> str:
        return os.path.join(self.base, f"04_{self.dut}_static_bug_analysis.md")

    @property
    def test_file(self) -> str:
        return os.path.join(self.tests, f"test_{self.dut}_counterexample.py")

    @property
    def rtl_dir(self) -> str:
        return os.path.join(self.workspace, self.dut)

    @property
    def rtl_path(self) -> str:
        return os.path.join(self.rtl_dir, f"{self.dut}.v")

    @property
    def records_yaml(self) -> str:
        """Single structured YAML file accumulating data across all formal stages."""
        return os.path.join(self.base, f".formal_records.yaml")
