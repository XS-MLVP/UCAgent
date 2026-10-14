"""Stage-local gates for template structure and evidence integrity."""

from pathlib import Path
import json

from ucagent.checkers.base import Checker
from ucagent.tools.fileops import is_file_writeable

from .tools import RTL2SpecCommandArgs
from .validation import validate
from .evidence import local_path, output_root


class RTL2SpecArtifactsChecker(Checker):
    """Validate real evidence and current artifacts at each stage boundary."""

    def __init__(
        self,
        module: str,
        config: str = "DefaultConfig",
        phase: str = "final",
        *,
        output_dir: str = "outputs",
        cfg=None,
    ):
        """Store static inputs; inspect no workspace state during construction."""
        super().__init__()
        RTL2SpecCommandArgs(action="validate", module=module, config=config)
        if phase not in {"evidence", "draft", "review", "final"}:
            raise ValueError("a valid evidence/draft/review/final phase is required")
        self.module, self.config, self.phase = module, config, phase
        self.output_dir = output_dir
        self._timing_registered = False

    def on_init(self):
        """Register newly generated references when their consuming stage becomes active."""
        root = Path(self.workspace)
        files = []
        if self.phase == "draft":
            files = [f"{self.output_dir}/evidence/manifest.json", f"{self.output_dir}/evidence/ports.md"]
        elif self.phase == "review":
            manifest = root / self.output_dir / "evidence/manifest.json"
            files = [f"{self.output_dir}/evidence/manifest.json",
                     f"{self.output_dir}/{self.module}_design_document_zh.md"]
            if manifest.is_file():
                records = json.loads(manifest.read_text(encoding="utf-8"))
                files.append(f"{self.output_dir}/evidence/{self.module}.sv")
                if "source_baseline" in records:
                    files.append(f"{self.output_dir}/evidence/{self.module}.preprocessed.sv")
                files += [record["path"] for record in records["related_sources"]]
        if self.stage is not None:
            for name in files:
                if (root / name).is_file():
                    self.stage.add_reference_files([name])
            if not self._timing_registered:
                self.stage.append_on_complete_callback(self.record_stage_timing)
                self._timing_registered = True
        return super().on_init()

    def record_stage_timing(self, stage):
        """Publish the core's actual completion timing without logging runtime secrets."""
        root = Path(self.workspace).resolve()
        path = local_path(root, output_root(root, self.output_dir) / "logs/stages.jsonl")
        cfg = getattr(self, "cfg", None)
        write_dirs = cfg.get_value("write_dirs", [self.output_dir]) if cfg is not None else [self.output_dir]
        un_write_dirs = cfg.get_value("un_write_dirs", []) if cfg is not None else []
        allowed, reason = is_file_writeable(path.relative_to(root).as_posix(), un_write_dirs, write_dirs)
        if not allowed:
            raise ValueError(f"Stage timing path is not writable: {reason}")
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {"stage": stage.name, "phase": self.phase, "started_at": stage.time_start,
                 "completed_at": stage.time_end, "elapsed_seconds": round(stage.get_time_cost(), 3)}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, sort_keys=True) + "\n")

    def do_check(self, is_complete: bool = False, **kwargs) -> tuple[bool, dict]:
        """Revalidate source, evidence and artifacts; no generation or rewriting occurs during Check."""
        result = validate(
            Path(self.workspace).resolve(),
            self.module,
            self.config,
            self.phase,
            output_dir=self.output_dir,
        )
        return result["ok"], result


class RTL2SpecGenericArtifactsChecker(RTL2SpecArtifactsChecker):
    """Validate evidence and documents captured by the generic RTL workflow."""

    def do_check(self, is_complete: bool = False, **kwargs) -> tuple[bool, dict]:
        """Revalidate user-supplied RTL evidence and generic document artifacts."""

        result = validate(
            Path(self.workspace).resolve(),
            self.module,
            self.config,
            self.phase,
            output_dir=self.output_dir,
            generic=True,
        )
        return result["ok"], result
