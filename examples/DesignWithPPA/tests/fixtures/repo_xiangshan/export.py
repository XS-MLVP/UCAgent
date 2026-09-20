"""Export only a selected Scala unit and its explicitly listed XiangShan dependencies."""

from pathlib import Path
import subprocess
import sys


def main():
    """Compile the supplied sources with the repository's pinned Scala/Chisel versions."""

    java, scala_cli, wrapper, *sources = sys.argv[1:]
    root = Path(".unit-export")
    root.mkdir()
    main_source = root / "UnitMain.scala"
    main_source.write_text(wrapper)
    subprocess.run([
        java, "-jar", scala_cli, "run", str(main_source), *sources,
        "--server=false", "--scala", "2.13.17",
        "--dependency", "org.chipsalliance::chisel:7.13.0",
        "--compiler-plugin", "org.chipsalliance:::chisel-plugin:7.13.0",
        "--scalac-option", "-language:reflectiveCalls",
        "--main-class", "UnitMain",
    ], check=True)


if __name__ == "__main__":
    main()
