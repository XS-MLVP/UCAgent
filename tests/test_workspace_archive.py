#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import tarfile

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.cli import (
    WorkspaceArchiveError,
    _prepare_workspace_archive_source,
    _safe_extract_workspace_archive,
)


def _add_dir(tf: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    tf.addfile(info)


def _add_file(tf: tarfile.TarFile, name: str, data: bytes = b"ok") -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def _add_symlink(tf: tarfile.TarFile, name: str, linkname: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.mode = 0o777
    info.linkname = linkname
    tf.addfile(info)


def _add_hardlink(tf: tarfile.TarFile, name: str, linkname: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE
    info.mode = 0o644
    info.linkname = linkname
    tf.addfile(info)


def _write_archive(path, populate) -> None:
    with tarfile.open(path, "w:gz") as tf:
        _add_dir(tf, "workspace")
        _add_dir(tf, "workspace/Adder")
        _add_dir(tf, "workspace/Adder/xspcomm")
        populate(tf)


def test_workspace_archive_extracts_safe_symlink(tmp_path):
    archive = tmp_path / "workspace.tar.gz"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    _write_archive(
        archive,
        lambda tf: (
            _add_file(tf, "workspace/Adder/xspcomm/_pyxspcomm_real.so", b"binary"),
            _add_symlink(tf, "workspace/Adder/xspcomm/_pyxspcomm.so", "_pyxspcomm_real.so"),
        ),
    )

    workspace_dir = _safe_extract_workspace_archive(str(archive), str(extract_dir), "Adder")

    link_path = os.path.join(workspace_dir, "Adder", "xspcomm", "_pyxspcomm.so")
    assert os.path.exists(link_path)
    assert open(link_path, "rb").read() == b"binary"
    if os.name != "nt":
        assert os.path.islink(link_path)
        assert os.readlink(link_path) == "_pyxspcomm_real.so"


def test_workspace_archive_rejects_symlink_escape(tmp_path):
    archive = tmp_path / "workspace.tar.gz"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    _write_archive(
        archive,
        lambda tf: _add_symlink(
            tf,
            "workspace/Adder/xspcomm/_pyxspcomm.so",
            "../../../outside.so",
        ),
    )

    with pytest.raises(WorkspaceArchiveError, match="Unsafe archive symlink target"):
        _safe_extract_workspace_archive(str(archive), str(extract_dir), "Adder")


def test_workspace_archive_rejects_absolute_symlink(tmp_path):
    archive = tmp_path / "workspace.tar.gz"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    _write_archive(
        archive,
        lambda tf: _add_symlink(
            tf,
            "workspace/Adder/xspcomm/_pyxspcomm.so",
            "/tmp/outside.so",
        ),
    )

    with pytest.raises(WorkspaceArchiveError, match="Unsafe archive symlink target"):
        _safe_extract_workspace_archive(str(archive), str(extract_dir), "Adder")


def test_workspace_archive_still_rejects_hardlink(tmp_path):
    archive = tmp_path / "workspace.tar.gz"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    _write_archive(
        archive,
        lambda tf: (
            _add_file(tf, "workspace/Adder/xspcomm/_pyxspcomm_real.so", b"binary"),
            _add_hardlink(
                tf,
                "workspace/Adder/xspcomm/_pyxspcomm.so",
                "workspace/Adder/xspcomm/_pyxspcomm_real.so",
            ),
        ),
    )

    with pytest.raises(WorkspaceArchiveError, match="Unsupported archive hard link entry"):
        _safe_extract_workspace_archive(str(archive), str(extract_dir), "Adder")


def test_workspace_archive_prepare_replaces_previous_extract_with_restricted_permissions(tmp_path):
    archive = tmp_path / "compiled.tar.gz"
    workspace_base = tmp_path / "workspace_base"
    _write_archive(
        archive,
        lambda tf: _add_file(tf, "workspace/Adder/version.txt", b"new"),
    )

    first_workspace = _prepare_workspace_archive_source(str(archive), "Adder", str(workspace_base))
    stale_file = os.path.join(first_workspace, "Adder", "stale.txt")
    with open(stale_file, "wb") as fh:
        fh.write(b"old")
    os.chmod(first_workspace, 0o500)

    try:
        second_workspace = _prepare_workspace_archive_source(str(archive), "Adder", str(workspace_base))
    finally:
        if os.path.isdir(first_workspace):
            os.chmod(first_workspace, 0o700)

    assert second_workspace == first_workspace
    assert not os.path.exists(stale_file)
    with open(os.path.join(second_workspace, "Adder", "version.txt"), "rb") as fh:
        assert fh.read() == b"new"


def test_workspace_archive_prepare_replaces_previous_extract_without_marker(tmp_path):
    archive = tmp_path / "compiled.tar.gz"
    workspace_base = tmp_path / "workspace_base"
    extract_dir = workspace_base / "compiled"
    stale_workspace = extract_dir / "workspace" / "Adder"
    stale_workspace.mkdir(parents=True)
    (stale_workspace / "stale.txt").write_bytes(b"old")
    _write_archive(
        archive,
        lambda tf: _add_file(tf, "workspace/Adder/version.txt", b"new"),
    )

    workspace_dir = _prepare_workspace_archive_source(str(archive), "Adder", str(workspace_base))

    assert workspace_dir == str(extract_dir / "workspace")
    assert not (stale_workspace / "stale.txt").exists()
    assert (stale_workspace / "version.txt").read_bytes() == b"new"
