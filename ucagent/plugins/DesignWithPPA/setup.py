"""Bundle repository license notices while keeping standalone sdists buildable."""

from pathlib import Path

from setuptools import setup


project = Path(__file__).resolve().parent
repository = project.parent.parent
generated = []
try:
    if not (project / "PKG-INFO").is_file() and (repository / "ucagent/__init__.py").is_file():
        # Setuptools reads license files before running individual build commands.
        # Exclusive creation protects any unexpected plugin-local policy files.
        for name in ("LICENSE", "NOTICE.md"):
            content = (repository / name).read_bytes()
            target = project / name
            with target.open("xb") as stream:
                generated.append(target)
                stream.write(content)
    else:
        # A published sdist already contains these copies and needs no checkout.
        for name in ("LICENSE", "NOTICE.md"):
            if not (project / name).is_file():
                raise FileNotFoundError(
                    f"Missing {name}: build from the UCAgent checkout or a complete plugin sdist."
                )
    setup()
finally:
    for target in generated:
        target.unlink()
