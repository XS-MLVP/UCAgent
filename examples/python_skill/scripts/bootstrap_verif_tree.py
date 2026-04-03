#!/usr/bin/env python3
import argparse
from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"


def render_template(template_name: str, dut: str):
    text = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    return text.replace("{DUT}", dut)


def create_file(path: Path, content: str):
    if path.exists():
        raise SystemExit(f"FAIL bootstrap: refusing to overwrite existing file {path.name}")
    path.write_text(content, encoding="utf-8")
    return f"CREATE {path.name}: generated"


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the minimum pytoffee verification tree from local templates.")
    parser.add_argument("--dut", required=True, help="DUT name, such as Adder.")
    parser.add_argument("--output", required=True, help="Directory to generate files into.")
    args = parser.parse_args()

    output_dir = Path(args.output).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(
            f"FAIL bootstrap: refusing to write into non-empty output directory {output_dir}"
        )
    targets = [
        output_dir / f"{args.dut}_api.py",
        output_dir / f"{args.dut}_function_coverage_def.py",
        output_dir / "test_basic.py",
    ]
    existing = [path.name for path in targets if path.exists()]
    if existing:
        raise SystemExit(
            "FAIL bootstrap: refusing to write into existing verification tree with existing target files: "
            + ", ".join(existing)
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    results = [
        create_file(targets[0], render_template("api.py.tpl", args.dut)),
        create_file(targets[1], render_template("function_coverage_def.py.tpl", args.dut)),
        create_file(targets[2], render_template("test_basic.py.tpl", args.dut)),
    ]

    for item in results:
        print(item)


if __name__ == "__main__":
    main()
