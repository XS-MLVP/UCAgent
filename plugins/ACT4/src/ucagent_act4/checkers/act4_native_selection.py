"""Read source applicability using the selected checkout's native ACT APIs.

Run with that checkout's Python environment. This helper never prepares UDB
outputs, builds tests, invokes a model, or searches other build directories.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def inspect_selection(request: dict) -> dict:
    """Select candidate sources from config, UDB parameters and derived extensions."""
    root = Path(request["act4_root"]).resolve()
    framework = (root / "framework/src").resolve()
    sys.path.insert(0, str(framework))
    import act.config
    from act.config import load_config
    from act.parse_test_constraints import generate_test_dict
    from act.parse_udb_config import get_config_params, get_implemented_extensions
    from act.select_tests import filter_tests_by_certificate, select_tests

    if not Path(act.config.__file__).resolve().is_relative_to(framework):
        raise ValueError("native ACT imports must come from the selected checkout")
    config_path = Path(request["config_file"]).resolve()
    config = load_config(config_path, validate_tools=False)
    if not config.udb_config.resolve().is_relative_to(root):
        raise ValueError("UDB parameters must belong to the selected native checkout")
    params = get_config_params(config.udb_config)
    if type(params.get("MXLEN")) is not int or params["MXLEN"] not in {32, 64}:
        raise ValueError("selected UDB config must declare MXLEN 32 or 64")
    build = Path(request["build_root"]).resolve()
    extension_file = build / "env/extensions.txt"
    extensions = get_implemented_extensions(extension_file)
    controls = request["controls"]
    test_dir = (root / controls.get("TESTDIR", "tests")).resolve()
    metadata = generate_test_dict(
        test_dir, controls.get("EXTENSIONS") or "all", controls.get("EXCLUDE_EXTENSIONS", "")
    )
    candidates = {str(Path(path).resolve()) for path in request["sources"]}
    metadata = {key: value for key, value in metadata.items() if str(value.test_path.resolve()) in candidates}
    selected = select_tests(
        metadata, extensions, params, harts=config.harts,
        include_priv_tests=config.include_priv_tests,
        enable_experimental_extensions=bool(controls.get("ENABLE_EXPERIMENTAL_EXTENSIONS")),
    )
    if controls.get("CERTIFICATE"):
        selected = filter_tests_by_certificate(selected, controls["CERTIFICATE"])
    selected_paths = sorted(str(value.test_path.resolve()) for value in selected.values())
    by_path = {str(value.test_path.resolve()): value for value in metadata.values()}
    excluded = []
    for path in sorted(candidates - set(selected_paths)):
        entry = by_path.get(path)
        excluded.append({
            "source": path,
            "reason": "native target constraints or certificate" if entry else "outside the native source filter",
            "required_params": entry.params if entry else {},
            "config_params": {key: params.get(key) for key in entry.params} if entry else {},
        })
    return {
        "config_file": str(config_path), "config_name": config.name,
        "udb_config": str(config.udb_config.resolve()), "xlen": params["MXLEN"],
        "extension_file": str(extension_file), "build_root": str(build),
        "selected_sources": selected_paths, "excluded_sources": excluded,
        "smoke_source": selected_paths[0] if selected_paths else None,
        "native_api": "act.select_tests.select_tests", "controls": controls,
    }


def main() -> None:
    """Return bounded JSON diagnostics to the parent checker without a traceback."""
    try:
        result = inspect_selection(json.load(sys.stdin))
    except Exception as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
