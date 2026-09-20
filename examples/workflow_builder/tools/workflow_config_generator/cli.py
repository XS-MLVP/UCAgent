"""CLI for workflow config generation."""

import argparse

from .core import ConfigGenerationError, generate_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow_root")
    parser.add_argument("--spec", default=".workflow/config_spec.yaml")
    parser.add_argument("--output", default="config.yaml")
    parser.add_argument("--workflow-spec", default=".workflow/workflow_spec.yaml")
    parser.add_argument("--replace-registrations", action="store_true")
    args = parser.parse_args()
    try:
        output = generate_config(
            args.workflow_root,
            args.spec,
            args.output,
            not args.replace_registrations,
            args.workflow_spec,
        )
    except ConfigGenerationError as exc:
        print(exc)
        return 1
    print(f"[PASS] generated config: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
