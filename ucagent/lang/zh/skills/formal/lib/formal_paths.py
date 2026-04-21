# -*- coding: utf-8 -*-
"""Centralized formal verification path resolution."""
import os
from dataclasses import dataclass, field

@dataclass
class FormalPaths:
    """All formal artifacts paths, derived from DUT/OUT environment variables or explicit parameters.
    
    In Checker: FormalPaths(dut=dut_name)
    In Skill scripts: FormalPaths() (Reads from env)
    """
    dut: str = field(default_factory=lambda: os.environ.get("DUT", "N/A"))
    out: str = field(default=None)
    workspace: str = field(default_factory=lambda: os.environ.get("UCAGENT_WORKSPACE", os.getcwd()))

    def __post_init__(self):
        if self.out is None:
            self.out = os.environ.get("OUT", "formal_test")
        
        # normalize: strip trailing slash and /tests suffix
        self.out = self.out.rstrip("/")
        if self.out.endswith("/tests"):
            self.out = self.out[:-6]

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
