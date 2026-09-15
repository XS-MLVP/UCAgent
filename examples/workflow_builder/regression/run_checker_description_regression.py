from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import yaml

from examples.workflow_builder.tools.workflow_checker_generator.core import generate_checkers_from_specs


ROOT = Path(__file__).resolve().parents[1]


def _load_class(path: Path, class_name: str):
    module_spec = importlib.util.spec_from_file_location(
        f"checker_description_regression_{path.stem}",
        path,
    )
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec.loader is not None
    module_spec.loader.exec_module(module)
    return getattr(module, class_name)


def main() -> None:
    source_specs = sorted((ROOT / "tools/workflow_checker_generator/test_data").glob("*_checker.yaml"))
    assert len(source_specs) == 4, source_specs

    with tempfile.TemporaryDirectory(prefix="checker_description_regression_") as temp:
        workflow = Path(temp)
        specs_dir = workflow / ".workflow/checker_specs"
        specs_dir.mkdir(parents=True)
        (workflow / "config.yaml").write_text(
            yaml.safe_dump(
                {"stage": [{"name": "smoke_read_generated_docs", "checker": []}]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        relative_specs = []
        for source in source_specs:
            target = specs_dir / source.name
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            relative_specs.append(target.relative_to(workflow).as_posix())

        report = generate_checkers_from_specs(
            workflow,
            relative_specs,
            overwrite=True,
            update_config=True,
        )
        assert len(report.generated_checkers) == 4

        for relative_spec in relative_specs:
            spec = yaml.safe_load((workflow / relative_spec).read_text(encoding="utf-8"))
            checker_path = workflow / spec["entry"]["file"]
            checker_class = _load_class(checker_path, spec["entry"]["class_name"])
            checker = checker_class(**spec.get("register", {}).get("args", {}))
            checker.workspace = str(workflow)
            method = getattr(checker, spec["entry"]["method"])
            assert method.__doc__ and method.__doc__.strip(), checker_class.__name__
            rendered = str(checker)
            assert method.__doc__.strip().splitlines()[0] in rendered

    print("[PASS] generated checker descriptions")


if __name__ == "__main__":
    main()
