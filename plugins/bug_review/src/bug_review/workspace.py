"""Prepare a fresh review workspace without editing or compiling the source input."""

import argparse
from pathlib import Path
import shutil


def prepare(source, workspace):
    """Copy supplied runtime material and UnityTest; reject overlapping/existing targets."""
    source, workspace = Path(source).resolve(), Path(workspace).resolve()
    if workspace.exists() or workspace.is_relative_to(source) or source.is_relative_to(workspace):
        raise ValueError('workspace must be new and separate from source')
    if not (source / 'unity_test').is_dir():
        raise ValueError('source must contain unity_test reports and tests')
    if any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('provide ordinary source files, not symlinks')
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns('.ucagent', '.git', '.venv',
                    '__pycache__', '.pytest_cache', 'node_modules', 'output', 'results'))
    return workspace


def main():
    """Expose preparation for Make and manual launch without requiring a DUT import."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    print(prepare(args.source, args.workspace))


if __name__ == '__main__':
    main()
