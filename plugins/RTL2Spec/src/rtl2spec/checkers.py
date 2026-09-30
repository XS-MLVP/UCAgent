"""Stage-local gates for template structure and evidence integrity."""

from pathlib import Path

from ucagent.checkers.base import Checker

from .documents import artifact_paths
from .tools import RTL2SpecCommandArgs
from .validation import validate


class RTL2SpecArtifactsChecker(Checker):
    """Validate real evidence and current artifacts at each stage boundary."""

    def __init__(
        self,
        module: str,
        config: str = "DefaultConfig",
        phase: str = "final",
        *,
        cfg=None,
    ):
        """Store static inputs; inspect no workspace state during construction."""
        super().__init__()
        RTL2SpecCommandArgs(action="validate", module=module, config=config)
        if phase not in {"evidence", "draft", "final"}:
            raise ValueError("a valid evidence/draft/final phase is required")
        self.module, self.config, self.phase = module, config, phase

    def on_init(self):
        """Register newly generated references when their consuming stage becomes active."""
        root = Path(self.workspace)
        if self.phase == "draft":
            files = [
                f"evidence/{self.module}/{name}"
                for name in ("manifest.json", "ports.csv", f"{self.module}.sv")
            ]
        elif self.phase == "final":
            files = [
                str(path.relative_to(root))
                for path in artifact_paths(root, self.module)
            ]
        else:
            files = []
        if self.stage is not None:
            for name in files:
                if (root / name).is_file():
                    self.stage.add_reference_files([name])
        return super().on_init()

    def do_check(self, is_complete: bool = False, **kwargs) -> tuple[bool, dict]:
        """Revalidate source, evidence and artifacts; no generation or rewriting occurs during Check."""
        result = validate(
            Path(self.workspace).resolve(),
            self.module,
            self.config,
            self.phase,
        )
        return result["ok"], result
