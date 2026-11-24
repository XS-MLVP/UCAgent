"""Install one Toffee 2/UCAgent venv without changing the Legacy environment."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import venv


def main():
    """Resolve the source checkout, exclude Legacy distributions and install the plugin."""
    plugin = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ucagent", type=Path, default=plugin.parents[2])
    parser.add_argument("--venv", type=Path, default=plugin / ".venv")
    args = parser.parse_args()
    source, environment = args.ucagent.resolve(), args.venv.absolute()
    if not (source / "ucagent/core/plugins.py").is_file():
        parser.error("--ucagent must name a decoupling UCAgent source checkout")
    if not (environment / "pyvenv.cfg").exists():
        if environment.exists() and any(environment.iterdir()):
            parser.error("--venv must name a new directory or an existing clean virtual environment")
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python"
    check = subprocess.run([str(python), "-c", "from importlib.metadata import distributions; import sys; "
                            "sys.exit(any(d.metadata['Name'].lower().replace('_', '-').replace('.', '-') "
                            "in {'pytoffee', 'toffee-test'} for d in distributions()))"])
    if check.returncode:
        parser.error("This venv already contains Legacy Toffee; select a new --venv, do not alter the old environment")
    rows = (source / "requirements.txt").read_text().splitlines()
    requirements = [row for row in rows if not re.match(r"^\s*(pytoffee|toffee[-_.]test)(?=[@\s<>=!~\[]|$)", row, re.I)]
    requirements += (plugin / "requirements.txt").read_text().splitlines()
    preferred = Path("/tmp/opencode")
    with tempfile.TemporaryDirectory(prefix="toffee-ut-install-", dir=preferred if preferred.is_dir() else None) as directory:
        lock = Path(directory) / "requirements.txt"
        lock.write_text("\n".join(requirements) + "\n")
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(lock), "build"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "-e", str(plugin)], check=True)
    location = subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
    ).strip()
    (Path(location) / "ucagent-source.pth").write_text(str(source) + "\n")
    subprocess.run([str(python), "-c", "from toffee_ut.runner import runtime_info; print(runtime_info())"], check=True)
    print(f"Ready: {python} -m ucagent --validate-plugin {plugin}")


if __name__ == "__main__":
    main()
