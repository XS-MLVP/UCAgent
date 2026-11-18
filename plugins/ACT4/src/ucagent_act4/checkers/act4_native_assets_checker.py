"""Gate native generation assets independently of the chosen privileged/unprivileged style."""

from pathlib import Path

from jsonschema import SchemaError, ValidationError
import yaml

from ucagent.checkers.base import Checker

from ..generation_assets import validate_native_assets
from ..generation_inputs import native_plan_path, read_generation_inputs
from ..xiangshan_bundle import safe_path, write_json


class ACT4NativeAssetsChecker(Checker):
    """Check upstream-native plans and the source set required by their CTP consumers."""

    def __init__(self, suite: str, kind: str, input_dir: str, contract_file: str, phase: str = "assets",
                 act4_root: str = "riscv-arch-test", normalized_csv: str | None = None,
                 human_plan: str | None = None, output_file: str | None = None, cfg=None):
        """Validate stage-local settings without touching sources during construction."""
        super().__init__()
        native_plan_path(suite, kind)
        if phase not in {"plan", "assets"}:
            raise ValueError("Use plan or assets validation")
        self.suite, self.kind, self.input_dir, self.contract_file = suite, kind, input_dir, contract_file
        self.phase, self.act4_root = phase, act4_root
        self.normalized_csv, self.human_plan, self.output_file = normalized_csv, human_plan, output_file

    def do_check(self, is_complete=False, **kwargs):
        """Validate live native sources, reject dropped requests, and refresh derived local views."""
        try:
            if kwargs:
                raise ValueError("Native asset validation takes no stage arguments")
            workspace = Path(self.workspace).resolve()
            directory = safe_path(workspace, self.input_dir)
            data = read_generation_inputs(directory, self.smanager_get_value)
            root = safe_path(workspace, self.act4_root)
            if (data["suite"], data["kind"], data["act4"]["path"]) != (self.suite, self.kind, str(root)):
                raise ValueError("Native assets must use the prepared suite, style and ACT checkout")
            result = validate_native_assets(root, directory, self.suite, self.kind, safe_path(workspace, self.contract_file),
                                            self.phase, safe_path(workspace, self.normalized_csv) if self.normalized_csv else None,
                                            safe_path(workspace, self.human_plan) if self.human_plan else None)
            if self.output_file:
                destination = safe_path(workspace, self.output_file)
                destination.parent.mkdir(parents=True, exist_ok=True)
                write_json(destination, result)
            return True, result
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, SchemaError, ValidationError) as error:
            return False, {"error_code": "act4_native_assets", "error": str(error)[:2000],
                           "artifact": self.contract_file if self.phase == "assets" else native_plan_path(self.suite, self.kind),
                           "next_action": "Repair the native plan, rule/parameter mapping or CTP include at the indicated location, then Check. Do not edit derived CSV/Markdown views or source receipts."}
