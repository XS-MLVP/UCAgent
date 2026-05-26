#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import tarfile

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.cli import WorkspaceArchiveError, _safe_extract_workspace_archive


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
