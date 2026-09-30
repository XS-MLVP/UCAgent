"""Build real plugin distributions to verify the shared repository license contract."""

from email.parser import BytesParser
from pathlib import Path
import shutil
import tarfile
import tomllib
import zipfile

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
NOTICE_FILES = ("LICENSE", "NOTICE.md")


@pytest.fixture(params=["RTL2Spec", "DesignWithPPA"])
def plugin_project(tmp_path, request):
    """Copy maintained build inputs to a temporary checkout, excluding runtime output."""
    pytest.importorskip("build")
    pytest.importorskip("setuptools", minversion="80")
    repository = tmp_path / "checkout"
    (repository / "ucagent").mkdir(parents=True)
    (repository / "ucagent/__init__.py").write_text('"""Checkout marker."""\n')
    for name in NOTICE_FILES:
        shutil.copyfile(REPOSITORY / name, repository / name)
    source = REPOSITORY / "plugins" / request.param
    project = repository / "plugins" / request.param
    project.mkdir(parents=True)
    for name in (
        "pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "Makefile",
        "ucagent-plugin.toml",
        "src", "scripts", "docs", "cases", "tests",
    ):
        path = source / name
        if path.is_dir():
            shutil.copytree(
                path, project / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "*.pyc"),
            )
        elif path.is_file():
            shutil.copyfile(path, project / name)
    return project


def assert_wheel_notices(wheel, repository):
    """Check actual installed metadata and notice bytes, including editable wheels."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        assert metadata["License-Expression"] == "Apache-2.0"
        assert set(metadata.get_all("License-File")) == set(NOTICE_FILES)
        directory = metadata_name.rsplit("/", 1)[0]
        for name in NOTICE_FILES:
            assert archive.read(f"{directory}/licenses/{name}") == (
                repository / name
            ).read_bytes()


def test_plugin_license_builds_and_standalone_sdist(plugin_project, tmp_path):
    """Direct, editable and standalone-sdist wheels include the root notices verbatim."""
    from build import ProjectBuilder

    project = plugin_project
    repository = project.parent.parent
    builder = ProjectBuilder(project)
    metadata = builder.prepare("wheel", tmp_path / "metadata")
    assert all(not (project / name).exists() for name in NOTICE_FILES)
    wheel = builder.build("wheel", tmp_path / "direct", metadata_directory=metadata)
    assert_wheel_notices(wheel, repository)
    editable = builder.build("editable", tmp_path / "editable")
    assert_wheel_notices(editable, repository)
    with zipfile.ZipFile(editable) as archive:
        paths = [
            archive.read(name).decode() for name in archive.namelist()
            if name.endswith(".pth")
        ]
        assert any(str(project / "src") in path for path in paths)

    sdist = builder.build("sdist", tmp_path / "dist")
    assert all(not (project / name).exists() for name in NOTICE_FILES)
    with tarfile.open(sdist) as archive:
        prefix = archive.getnames()[0].split("/")[0]
        for name in NOTICE_FILES:
            assert archive.extractfile(f"{prefix}/{name}").read() == (
                repository / name
            ).read_bytes()
        assert f"{prefix}/setup.py" in archive.getnames()
        for document in (project / "docs").rglob("*.md"):
            relative = document.relative_to(project).as_posix()
            assert archive.extractfile(f"{prefix}/{relative}").read() == document.read_bytes()
        archive.extractall(tmp_path / "unpacked", filter="data")
    standalone = tmp_path / "unpacked" / prefix
    # The extracted sdist cannot find the original repository at its parent paths.
    assert not (standalone.parent.parent / "ucagent").exists()
    rebuilt = ProjectBuilder(standalone).build("wheel", tmp_path / "rebuilt")
    assert_wheel_notices(rebuilt, repository)
    assert all((standalone / name).is_file() for name in NOTICE_FILES)
    nested = repository / "rebuild" / prefix
    nested.parent.mkdir()
    standalone.rename(nested)
    # An sdist still owns its bundled notices when extracted inside a checkout.
    nested_wheel = ProjectBuilder(nested).build("wheel", tmp_path / "nested")
    assert_wheel_notices(nested_wheel, repository)
    if project.name == "DesignWithPPA":
        relative = "design_with_ppa/assets/NangateOpenCellLibrary_typical.lib"
        with zipfile.ZipFile(rebuilt) as archive:
            assert archive.read(relative) == (project / "src" / relative).read_bytes()


def test_plugin_metadata_uses_updated_root_notice(plugin_project, tmp_path):
    """Each build reads the root source again rather than retaining a stale local copy."""
    from build import ProjectBuilder

    project = plugin_project
    repository = project.parent.parent
    builder = ProjectBuilder(project)
    builder.prepare("wheel", tmp_path / "first")
    notice = repository / "NOTICE.md"
    notice.write_bytes(notice.read_bytes() + b"\nUpdated repository notice.\n")
    wheel = builder.build("wheel", tmp_path / "updated")
    assert_wheel_notices(wheel, repository)
    assert all(not (project / name).exists() for name in NOTICE_FILES)


@pytest.mark.parametrize("defect", ["LICENSE", "NOTICE.md", "configuration", "local_notice"])
def test_failed_build_preserves_sources_and_removes_temporary_copies(
    plugin_project, tmp_path, defect,
):
    """Missing notices and backend failures cannot leave copies or overwrite local files."""
    from build import BuildBackendException, ProjectBuilder

    project = plugin_project
    if defect in NOTICE_FILES:
        (project.parent.parent / defect).unlink()
    elif defect == "configuration":
        config = project / "pyproject.toml"
        config.write_text(config.read_text().replace(
            'license = "Apache-2.0"', 'license = "invalid license"'
        ))
    else:
        (project / "NOTICE.md").write_text("Preserve unexpected local content\n")
    with pytest.raises(BuildBackendException):
        ProjectBuilder(project).prepare("wheel", tmp_path / "metadata")
    assert not (project / "LICENSE").exists()
    if defect == "local_notice":
        assert (project / "NOTICE.md").read_text() == "Preserve unexpected local content\n"
    else:
        assert not (project / "NOTICE.md").exists()


def test_incomplete_standalone_source_cannot_build(plugin_project, tmp_path, capfd):
    """Copying only a plugin directory without its bundled notices fails explicitly."""
    from build import BuildBackendException, ProjectBuilder

    standalone = tmp_path / "standalone"
    plugin_project.rename(standalone)
    with pytest.raises(BuildBackendException):
        ProjectBuilder(standalone).prepare("wheel", tmp_path / "metadata")
    assert (
        "build from the UCAgent checkout or a complete plugin sdist"
        in capfd.readouterr().err
    )


def test_core_metadata_matches_root_license(tmp_path):
    """The core packaging configuration also delivers matching metadata and notices."""
    pytest.importorskip("build")
    pytest.importorskip("setuptools", minversion="80")
    pytest.importorskip("setuptools_scm")
    from build import ProjectBuilder

    project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())["project"]
    assert project["license"] == "Apache-2.0"
    assert set(project["license-files"]) == set(NOTICE_FILES)
    assert "License :: OSI Approved :: MIT License" not in project["classifiers"]
    checkout = tmp_path / "core"
    (checkout / "ucagent").mkdir(parents=True)
    for name in (*NOTICE_FILES, "pyproject.toml", "README.en.md", "ucagent/__init__.py"):
        shutil.copyfile(REPOSITORY / name, checkout / name)
    wheel = ProjectBuilder(checkout).build("wheel", tmp_path / "dist")
    assert_wheel_notices(wheel, REPOSITORY)
