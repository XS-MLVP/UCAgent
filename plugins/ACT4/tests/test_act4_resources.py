"""Exercise cross-run source reuse, writable isolation, and bounded resource access offline."""

import errno
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from act4_privileged_suite import resources
from act4_privileged_suite.checkers.act4_resource_checker import ACT4ResourceChecker
from act4_privileged_suite.resource_tools import ACT4Resources


def repository(root: Path, name: str, branch: str = "act4") -> Path:
    """Create a tiny local checkout with the selected upstream identity but no network access."""
    path = root / resources.REPOSITORIES[name][0]
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    (path / "README.md").write_text("Pinned source\nsecond line\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=Fixture", "-c", "user.email=test@example.org", "commit", "-qm", "fixture"], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", resources.REPOSITORIES[name][1]], check=True)
    return path


def checker_for(workspace: Path, *, workflow: str = "review", inputs: dict | None = None):
    """Construct an active resource gate with a private in-memory receipt registry."""
    workspace.mkdir(parents=True, exist_ok=True)
    state = {}
    manager = SimpleNamespace(get_data=state.get, set_data=state.__setitem__)
    checker = ACT4ResourceChecker("out/intermediate/Sstc/resources", workflow,
                                 inputs or {"act4": "riscv-arch-test", "manual": "riscv-isa-manual"})
    return checker.set_workspace(str(workspace)).set_stage_manager(manager)


def test_two_runs_import_existing_output_once_without_network(tmp_path, monkeypatch):
    """A clean old checkout seeds one pinned cache; later runs read exactly that same checkout."""
    output = tmp_path / "output"
    old = output / "old-run"
    act = repository(old, "act4")
    repository(old, "manual", "main")
    original_execute = resources.execute
    commands = []

    def local_only(argv, *args, **kwargs):
        """Observe all source commands and forbid an accidental remote download."""
        assert not any(value.startswith("https://") for value in argv)
        commands.append(argv)
        return original_execute(argv, *args, **kwargs)

    monkeypatch.setattr(resources, "execute", local_only)
    first = checker_for(output / "run-one")
    passed, result = first.do_check(action="prepare")
    assert passed, result
    assert first.do_check(is_complete=True)[0]
    shared = Path(result["resources"]["act4"]["path"])
    assert shared.is_relative_to(output / ".act4-cache")
    assert result["resources"]["act4"]["origin"] == "existing_output"
    assert not (output / "run-one/riscv-arch-test").exists()
    count = len(commands)
    second = checker_for(output / "run-two")
    passed, reused = second.do_check(action="prepare")
    assert passed, reused
    assert reused["resources"]["act4"]["path"] == str(shared)
    assert reused["resources"]["act4"]["origin"] == "shared_cache"
    assert len(commands) == count
    assert (act / "README.md").read_text() == "Pinned source\nsecond line\n"


def test_generation_gets_private_writable_checkout(tmp_path):
    """Generation edits cannot change either the shared pin or an earlier run's source."""
    output = tmp_path / "output"
    original = repository(output / "old", "act4")
    repository(output / "old", "manual", "main")
    checker = checker_for(output / "generation", workflow="generation")
    passed, result = checker.do_check(action="prepare")
    assert passed, result
    resource = result["resources"]["act4"]
    candidate = Path(resource["path"])
    shared = Path(resource["shared_source"])
    assert resource["origin"] == "writable_copy"
    assert candidate == output / "generation/riscv-arch-test"
    (candidate / "README.md").write_text("private change\n")
    assert (shared / "README.md").read_bytes() == (original / "README.md").read_bytes()
    assert (candidate / "README.md").stat().st_ino != (shared / "README.md").stat().st_ino


def test_explicit_local_assets_and_manual_are_preserved(tmp_path):
    """A non-Git module input stays authoritative and never triggers upstream acquisition."""
    workspace = tmp_path / "workspace"
    source = workspace / "local"
    source.mkdir(parents=True)
    (source / "test.S").write_text("local uncommitted test")
    manual = tmp_path / "manual"
    manual.mkdir()
    checker = checker_for(workspace, inputs={"act4": "local", "manual": str(manual)})
    passed, result = checker.do_check(action="prepare")
    assert passed, result
    assert result["resources"]["act4"]["origin"] == "provided"
    assert result["resources"]["manual"]["path"] == str(manual)
    assert (source / "test.S").read_text() == "local uncommitted test"


@pytest.mark.parametrize("mutation", ["source", "receipt", "missing"])
def test_shared_drift_or_receipt_tampering_blocks_completion(tmp_path, mutation):
    """Existing runs cannot silently accept a changed or removed shared input."""
    output = tmp_path / "output"
    repository(output / "old", "act4")
    repository(output / "old", "manual", "main")
    checker = checker_for(output / "run")
    passed, result = checker.do_check(action="prepare")
    assert passed, result
    source = Path(result["resources"]["act4"]["path"])
    if mutation == "source":
        (source / "README.md").write_text("changed")
    elif mutation == "receipt":
        Path(result["receipt"]).write_text("{}")
    else:
        source.rename(source.with_name("removed"))
    assert not checker.do_check(is_complete=True)[0]


def test_busy_cache_is_retryable_without_starting_download(tmp_path):
    """A competing preparer receives an actionable failure rather than corrupting shared state."""
    workspace = tmp_path / "output/run"
    checker = checker_for(workspace)
    cache, _ = resources.resource_locations(workspace)
    cache.mkdir()
    with (cache / ".resources.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        passed, result = checker.do_check(action="prepare")
    assert not passed and "Another run" in result["error"]


def test_failed_download_is_not_published(tmp_path, monkeypatch):
    """Failed source acquisition leaves neither a trusted pin nor an occupied checkout path."""
    checker = checker_for(tmp_path / "output/run")
    monkeypatch.setattr(resources, "execute", lambda *args, **kwargs: {"status": "failed"})
    passed, result = checker.do_check(action="prepare")
    assert not passed and "Cannot obtain act4" in result["error"]
    assert not list((tmp_path / "output/.act4-cache/repositories").glob("riscv-arch-test-*"))


@pytest.mark.parametrize("fallback", [False, True])
def test_reflink_or_copy_never_shares_writable_inodes(tmp_path, monkeypatch, fallback):
    """Normal copies remain correct when reflinks are unsupported on the current filesystem."""
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"original\r\n")
    source.chmod(0o755)
    if fallback:
        def unsupported(*args):
            """Simulate a filesystem without reflink support."""
            raise OSError(errno.EOPNOTSUPP, "no reflinks")

        monkeypatch.setattr(resources.fcntl, "ioctl", unsupported)
    resources.copy_on_write(source, target)
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode == source.stat().st_mode
    target.write_bytes(b"private")
    assert source.read_bytes() == b"original\r\n"


def test_resource_tool_bounded_reads_snapshots_and_path_safety(tmp_path):
    """The plugin reads only registered inputs; references are small private files, not links."""
    output = tmp_path / "output"
    repository(output / "old", "act4")
    repository(output / "old", "manual", "main")
    workspace = output / "run"
    checker = checker_for(workspace)
    assert checker.do_check(action="prepare")[0]
    tool = ACT4Resources(workspace=str(workspace), resource_dir=checker.environment_dir,
                         inputs=checker.inputs, write_dirs=["out"])
    assert tool._run("read", path="README.md", limit=1)["lines"] == ["Pinned source"]
    result = tool._run("snapshot", path="README.md")
    assert result["ok"], result
    snapshot = workspace / result["path"]
    assert not snapshot.is_symlink()
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == result["sha256"]
    assert not tool._run("read", path="../../secret")["ok"]
    assert not tool._run("read", path=".git/config")["ok"]
    assert not tool._run("snapshot", resource="act4", path="README.md")["ok"]
    denied = tool.model_copy(update={"write_dirs": []})
    assert not denied._run("snapshot", path="README.md")["ok"]
    snapshot.write_text("fabricated ISA content")
    assert not checker.do_check(is_complete=True)[0]
    with pytest.raises(ValueError, match="differs from its registered source"):
        resources.resolve_source(workspace, "riscv-arch-test", workspace / checker.environment_dir, checker.smanager_get_value)
    receipt = workspace / checker.environment_dir / "receipt.json"
    data = json.loads(receipt.read_text())
    data["resources"]["manual"]["path"] = str(tmp_path)
    receipt.write_text(json.dumps(data))
    assert not tool._run("list")["ok"]


def test_local_clone_preserves_recursive_submodule_pins(tmp_path):
    """Existing initialized submodules are cloned locally without contacting their upstream URL."""
    source = repository(tmp_path / "old", "act4")
    module = repository(tmp_path / "module", "manual", "main")
    subprocess.run(["git", "-C", str(source), "-c", "protocol.file.allow=always", "submodule", "add", str(module), "vendor/manual"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=test@example.org", "commit", "-qam", "module"], check=True)
    import time

    target = tmp_path / "copy"
    resources.clone_local(source, target, tmp_path, time.monotonic() + 30)
    assert resources.repository_identity(source, clean=True) == resources.repository_identity(target, clean=True)
    (target / "vendor/manual/README.md").write_text("private module")
    assert (source / "vendor/manual/README.md").read_text().startswith("Pinned")


def test_read_only_manual_reuses_uninitialized_optional_submodules(tmp_path):
    """Do not fetch a manual's documentation-build dependencies merely to read ISA text."""
    output = tmp_path / "output"
    repository(output / "old", "act4")
    manual = repository(output / "old", "manual", "main")
    module = repository(tmp_path / "module", "manual", "main")
    subprocess.run(["git", "-C", str(manual), "-c", "protocol.file.allow=always", "submodule", "add", str(module), "docs-resources"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(manual), "-c", "user.name=Fixture", "-c", "user.email=test@example.org", "commit", "-qam", "docs module"], check=True)
    subprocess.run(["git", "-C", str(manual), "submodule", "deinit", "-f", "docs-resources"], check=True, capture_output=True)
    checker = checker_for(output / "run")
    passed, result = checker.do_check(action="prepare")
    assert passed, result
    record = result["resources"]["manual"]
    assert record["origin"] == "existing_output"
    assert record["identity"]["submodules"].startswith("-")
    assert not list((Path(record["path"]) / "docs-resources").iterdir())
    assert checker.do_check(is_complete=True)[0]


def test_shared_input_alias_is_order_independent(tmp_path):
    """Equivalent local/framework paths select one cached source even when input is listed first."""
    output = tmp_path / "output"
    repository(output / "old", "act4")
    repository(output / "old", "manual", "main")
    checker = checker_for(output / "run", workflow="handoff",
                          inputs={"input": "./riscv-arch-test", "manual": "riscv-isa-manual", "act4": "riscv-arch-test"})
    passed, result = checker.do_check(action="prepare")
    assert passed, result
    assert result["resources"]["input"]["path"] == result["resources"]["act4"]["path"]
    tool = ACT4Resources(workspace=checker.workspace, resource_dir=checker.environment_dir, inputs=checker.inputs, write_dirs=["out"])
    assert tool._run("read", resource="input", path="README.md")["ok"]


@pytest.mark.parametrize("problem", ["dirty", "wrong_ref", "wrong_remote"])
def test_unmatched_historical_checkout_is_not_implicitly_adopted(tmp_path, monkeypatch, problem):
    """Reject unselected modifications and repository/version mismatches without changing old runs."""
    output = tmp_path / "output"
    old = repository(output / "old", "act4")
    if problem == "dirty":
        (old / "README.md").write_text("uncommitted user input")
    elif problem == "wrong_ref":
        resources.git_text(old, "branch", "-m", "different")
    else:
        resources.git_text(old, "remote", "set-url", "origin", "https://example.invalid/unrelated.git")
    original = (old / "README.md").read_bytes()
    monkeypatch.setattr(resources, "execute", lambda *args, **kwargs: {"status": "failed"})
    checker = checker_for(output / "run")
    passed, result = checker.do_check(action="prepare")
    assert not passed and "Cannot obtain act4" in result["error"]
    assert (old / "README.md").read_bytes() == original


def test_explicit_external_inputs_reject_symlink_and_traversal(tmp_path):
    """Configuration grants read-only access only to direct declared roots, not escaped paths."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert resources.input_path(workspace, str(outside)) == outside
    for name in (str(link), str(link / "nested"), "../outside", "."):
        with pytest.raises(ValueError):
            resources.input_path(workspace, name)


def test_local_import_does_not_keep_borrowed_git_objects(tmp_path):
    """A cached import remains usable if an older checkout's borrowed object store disappears."""
    original = repository(tmp_path / "original", "act4")
    borrowed = tmp_path / "borrowed"
    subprocess.run(["git", "clone", "--shared", str(original), str(borrowed)], check=True, capture_output=True)
    assert (borrowed / ".git/objects/info/alternates").is_file()
    target = tmp_path / "independent"
    import time

    resources.clone_local(borrowed, target, tmp_path, time.monotonic() + 30)
    assert not (target / ".git/objects/info/alternates").exists()
    original.rename(tmp_path / "removed-original")
    assert resources.git_text(target, "show", "HEAD:README.md").startswith("Pinned source")
