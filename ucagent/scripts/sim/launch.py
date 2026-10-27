"""Launch a trusted viewer command with JSON data exposed safely to Tcl scripts."""

import json
import os
from pathlib import Path
import sys


def tcl_string(value):
    """Represent UTF-8 data without allowing Tcl substitution or evaluation."""
    return '[encoding convertfrom utf-8 [binary decode hex {' + str(value).encode().hex() + '}]]'


def main():
    """Read a server-owned launch manifest and replace this process with the viewer."""
    manifest = Path(sys.argv[1]).resolve()
    output = manifest.parent
    try:
        config = json.loads(manifest.read_text(encoding="utf-8"))
        assignments = [f"set {key} {tcl_string(config.get(key, ''))}"
                       for key in ("file", "daidir", "start", "end", "cursor")]
        assignments.append("set signals [list " + " ".join(tcl_string(signal)
                                                          for signal in config.get("signals", [])) + "]")
        assignments.append(f"set output {tcl_string(output)}")
        data = output / "data.tcl"
        data.write_text("\n".join(assignments), encoding="utf-8")
        environment = {**os.environ, "UCAGENT_WAVE_DATA": str(data)}
        os.execvpe(config["command"][0], config["command"], environment)
    except Exception as error:
        (output / "error.txt").write_text(str(error), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
