"""Exercise Swarm Make targets without starting containers or accessing a registry."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import textwrap

import pytest


@pytest.fixture
def swarm_make(tmp_path):
    """Run the real Make recipes against isolated Docker, HTTP, and clock stubs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "calls.jsonl"
    clock_path = tmp_path / "clock"
    clock_path.write_text("100", encoding="utf-8")
    stub = bin_dir / "stub"
    stub.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
        """Implement the external command responses needed by deployment tests."""
        import json
        import os
        from pathlib import Path
        import sys

        name = Path(sys.argv[0]).name
        args = sys.argv[1:]
        config = json.loads(os.environ["SWARM_TEST_CONFIG"])
        with open(os.environ["SWARM_TEST_LOG"], "a", encoding="utf-8") as log:
            log.write(json.dumps([name, *args]) + "\\n")
        clock = Path(os.environ["SWARM_TEST_CLOCK"])
        if name == "date":
            print(clock.read_text())
        elif name == "sleep":
            clock.write_text(str(int(clock.read_text()) + int(args[0])))
        elif name == "curl":
            clock.write_text(str(int(clock.read_text()) + config.get("http_elapsed", 0)))
            print(config.get("http_status", "200"), end="")
            sys.exit(config.get("http_exit", 0))
        elif args[:1] == ["info"]:
            if "--format" in args:
                fmt = args[args.index("--format") + 1]
                print("true" if "ControlAvailable" in fmt else "active")
        elif args[:2] == ["network", "inspect"]:
            if "--format" in args:
                fmt = args[args.index("--format") + 1]
                print("overlay" if "Driver" in fmt else "swarm")
        elif args[:2] == ["image", "inspect"]:
            sys.exit(0 if config.get("image_present", True) else 1)
        elif args[:1] == ["pull"]:
            sys.exit(config.get("pull_exit", 0))
        elif args[:2] == ["service", "inspect"]:
            sys.exit(1)
        elif args[:2] == ["service", "create"]:
            print("test-service-id")
        elif args[:2] == ["service", "ls"]:
            fmt = args[args.index("--format") + 1]
            for service, replicas in (
                ("ucagent_master_old", config.get("other_replicas", "0/1")),
                ("ucagent_master", config.get("replicas", "1/1")),
            ):
                print(f"{service} {replicas}" if "Name" in fmt else replicas)
        elif args[:3] == ["node", "inspect", "self"]:
            print("192.0.2.10")
        else:
            sys.exit(f"Unexpected command: {name} {args}")
    '''), encoding="utf-8")
    stub.chmod(0o755)
    for name in ("docker", "curl", "date", "sleep"):
        (bin_dir / name).symlink_to(stub)

    def run(target="swarm_master", config=None, **variables):
        """Return the Make result and recorded calls for one deployment scenario."""
        env = dict(os.environ)
        for key in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "UCAGENT_MASTER_SOURCE"):
            env.pop(key, None)
        env.update({
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "SWARM_TEST_CONFIG": json.dumps(config or {}),
            "SWARM_TEST_LOG": str(log_path),
            "SWARM_TEST_CLOCK": str(clock_path),
        })
        settings = {
            "SWARM_IS_COLIMA": "0",
            "SWARM_MASTER_WAIT_SECONDS": "3",
            "SWARM_MASTER_PERSIST": str(tmp_path / "persist"),
            "SWARM_DOCKER_SOCK_CHECK": "true",
            "SWARM_MASTER_PERSIST_MKDIR": "true",
            **variables,
        }
        result = subprocess.run(
            [shutil.which("make"), target, *[f"{key}={value}" for key, value in settings.items()]],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
        )
        calls = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
        return result, calls

    return run


@pytest.mark.parametrize("status", ["200", "401"])
def test_master_waits_for_http_and_accepts_password_protection(swarm_make, status):
    """A ready target service succeeds even if a similarly named service is unready."""
    result, calls = swarm_make(config={"http_status": status})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Published on host: http://192.0.2.10:8800" in result.stdout
    assert any(call[0] == "curl" for call in calls)


def test_unready_target_does_not_inherit_other_service_readiness(swarm_make):
    """A ready service with the same prefix must not make an unready Master pass."""
    result, calls = swarm_make(config={"replicas": "0/1", "other_replicas": "1/1"})
    assert result.returncode != 0
    assert "did not reach 1/1 replicas" in result.stdout
    assert not any(call[0] == "curl" for call in calls)


@pytest.mark.parametrize("status,exit_code", [("503", 0), ("000", 7)])
def test_master_http_failure_obeys_elapsed_time_budget(swarm_make, status, exit_code):
    """Slow or unreachable HTTP must time out despite a running container."""
    result, calls = swarm_make(config={
        "http_status": status, "http_exit": exit_code, "http_elapsed": 2,
    })
    assert result.returncode != 0
    assert "with a responding Master API" in result.stdout
    assert len([call for call in calls if call[0] == "curl"]) == 1


@pytest.mark.parametrize("host", ["", "master.example.test"])
def test_colima_uses_localhost_unless_host_is_explicit(swarm_make, host):
    """Colima checks and prints localhost, while respecting an explicit host."""
    result, calls = swarm_make(SWARM_IS_COLIMA="1", SWARM_MASTER_HOST=host)
    expected = host or "127.0.0.1"
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Published on host: http://{expected}:8800" in result.stdout
    assert [call for call in calls if call[0] == "curl"][0][-1] == f"http://{expected}:8800/api/launch/config"


@pytest.mark.parametrize("image,present,pulls", [
    ("registry.example.test/ucagent:latest", True, True),
    ("registry.example.test/ucagent@sha256:" + "a" * 64, True, False),
    ("registry.example.test/ucagent@sha256:" + "a" * 64, False, True),
])
def test_image_refresh_and_child_image_override(swarm_make, image, present, pulls):
    """Refresh tags, reuse cached digests, and preserve the image through CLI parsing."""
    from ucagent.cli import get_override_dict
    from ucagent.util.config import Config

    result, calls = swarm_make(config={"image_present": present}, SWARM_IMAGE=image)
    assert result.returncode == 0, result.stdout + result.stderr
    assert bool([call for call in calls if call[:2] == ["docker", "pull"]]) is pulls
    create = next(call for call in calls if call[:3] == ["docker", "service", "create"])
    assert create[-4] == image
    command = shlex.split(create[-1])
    cfg = Config({"launch": {"default_args": {}, "cluster": {"image": "old"}}})
    for index, value in enumerate(command):
        if value == "--override":
            cfg.set_values(get_override_dict(command[index + 1]))
    assert cfg.get_value("launch.cluster.image") == image


def test_failed_image_pull_stops_before_service_creation(swarm_make):
    """A registry failure must prevent creation of a service with a stale tag."""
    result, calls = swarm_make(config={"pull_exit": 1})
    assert result.returncode != 0
    assert not any(call[:3] == ["docker", "service", "create"] for call in calls)


@pytest.mark.parametrize("seconds", ["0", "-1", "abc", "1.5"])
def test_invalid_wait_budget_fails_before_deployment(swarm_make, seconds):
    """Reject invalid time budgets before mutating network or service resources."""
    result, calls = swarm_make(SWARM_MASTER_WAIT_SECONDS=seconds)
    assert result.returncode != 0
    assert "SWARM_MASTER_WAIT_SECONDS must be a positive integer" in result.stdout
    assert not any(call[:3] == ["docker", "service", "create"] for call in calls)
