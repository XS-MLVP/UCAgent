"""CLI for GuideDoc generation."""

import argparse

from .core import GuideDocGenerationError, generate_guidedocs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow_root")
    parser.add_argument("--from-spec", action="append", dest="spec_paths", required=True)
    parser.add_argument("--no-update-config", action="store_true")
    args = parser.parse_args()
    try:
        outputs = generate_guidedocs(args.workflow_root, args.spec_paths, not args.no_update_config)
    except GuideDocGenerationError as exc:
        print(exc)
        return 1
    print("[PASS] generated Guide_Doc: " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
