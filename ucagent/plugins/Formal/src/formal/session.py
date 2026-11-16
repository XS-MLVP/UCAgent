"""Keep an initialized FormalMC process for one bounded serial group of assertions."""

from pathlib import Path
import os
import shutil
import signal
import subprocess


class ProofSession:
    """Own one worker slot; publish one Tcl job at a time and seal each attempt."""

    def __init__(self, directory: Path, setup_word: str, executable: str, slot):
        """Start the native interpreter and load the frozen setup once."""
        self.directory = directory
        self.directory.mkdir(parents=True)
        self.path = directory / "session.log"
        self.slot = slot
        self.jobs = 0
        script = directory / "session.tcl"
        script.write_text(
            f"source {setup_word}\n"
            "while {1} {\n"
            "    if {![file exists request.tcl]} { after 50; continue }\n"
            "    file rename -force request.tcl active.tcl\n"
            "    source active.tcl\n"
            "}\n",
            encoding="utf-8",
        )
        with self.path.open("wb") as stream:
            self.process = subprocess.Popen(
                [executable, "-f", str(script), "-override", "-work_dir", str(directory)],
                cwd=directory, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True, pass_fds=(slot.fileno(),),
            )

    def submit(self, commands: str) -> int:
        """Publish a new job atomically and return the start of its output."""
        offset = 0 if self.jobs == 0 else self.path.stat().st_size
        self.jobs += 1
        temporary = self.directory / "request.tmp"
        temporary.write_text(commands, encoding="utf-8")
        temporary.replace(self.directory / "request.tcl")
        return offset

    def seal(self, name: str, console: Path, offset: int, completed: bool):
        """Copy only the requested property's result, original witness and waveform."""
        with self.path.open("rb") as stream:
            stream.seek(offset)
            console.write_bytes(stream.read())
        if completed:
            for suffix in (".tb.v", ".vcd"):
                relative = Path("avis") / name / (name + suffix)
                source = self.directory / relative
                if source.is_symlink() or not source.resolve().is_relative_to(self.directory):
                    raise ValueError("Invalid session witness path.")
                if source.is_file():
                    target = console.parent / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)

    def clear_witness(self, name: str):
        """Discard any earlier native artifact for this exact target in this session."""
        for suffix in (".tb.v", ".vcd"):
            path = self.directory / "avis" / name / (name + suffix)
            if not path.parent.resolve().is_relative_to(self.directory):
                raise ValueError("Invalid session witness directory.")
            path.unlink(missing_ok=True)

    def close(self, *, graceful: bool):
        """Return the slot and terminate this process group if it does not exit."""
        try:
            if graceful and self.process.poll() is None:
                try:
                    self.submit("exit\n")
                    self.process.wait(timeout=0.75)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process.wait()
        finally:
            self.slot.close()
