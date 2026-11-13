"""Portable ACT4 build and XiangShan execution support, shipped as act4_driver.py."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import time
import uuid


SOURCE_IGNORE_DIRS = {".git", ".venv", ".bundle", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}
NOTE_NAME = ".note.ucagent.act4"


def test_description(trace: dict, test: dict) -> dict:
    """Project one source's summary and exact coverpoint/rule links into portable metadata."""
    points = {point["id"]: point for point in trace["coverpoints"]}
    identifiers = sorted({identifier for case in test["cases"] for identifier in case["coverpoints"]})
    return {"source": test["path"], "summary": test["summary"], "case_count": len(test["cases"]),
            **{field: test[field] for field in ("preconditions", "setup", "exercise", "check", "limitations")},
            "evidence_level": trace["evidence_level"], "traceability": "traceability.json",
            "coverpoints": [{"id": identifier, "intent": points[identifier]["intent"],
                             "rules": [rule["id"] for rule in points[identifier]["rules"]]} for identifier in identifiers]}


def description_note(description: dict, newline: str = "\n") -> str:
    """Encode a non-loaded description for original and locally modified ACT sources."""
    payload = json.dumps(description, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\0"
    text = f'.pushsection {NOTE_NAME},"",@note{newline}.balign 4{newline}'
    text += f".long 8, {len(payload)}, 1{newline}.asciz \"UCAGENT\"{newline}.balign 4{newline}"
    for offset in range(0, len(payload), 24):
        text += ".byte " + ",".join(str(value) for value in payload[offset:offset + 24]) + newline
    return text + f".balign 4{newline}.popsection{newline}"


def annotate_source(original: bytes, test: dict, description: dict) -> bytes:
    """Add comments and a non-allocated ELF note without rewriting source instructions or assertions."""
    newline = "\r\n" if b"\r\n" in original else "\n"

    def comment(text):
        """Keep prose from introducing ACT configuration delimiters or C line splicing."""
        return "".join("// " + line.replace("\\", "∖").replace("START_TEST_CONFIG", "START TEST CONFIG").replace("END_TEST_CONFIG", "END TEST CONFIG") + newline for line in text.splitlines())

    lines = original.decode("utf-8").splitlines(keepends=True)
    header = ["ACT4 XiangShan test description", description["summary"],
              "Static design mapping; not measured coverage."]
    header += [f"{field.capitalize()}: {description[field]}" for field in ("preconditions", "setup", "exercise", "check", "limitations")]
    header += [f"{point['id']}: {point['intent']} | norm rules: {', '.join(point['rules'])}" for point in description["coverpoints"]]
    prefix = "".join(comment(text) for text in header)
    comments = {case["lines"][0]: case for case in test["cases"]}
    output = [prefix]
    for number, line in enumerate(lines, 1):
        if number in comments:
            case = comments[number]
            for text in (f"ACT4 testcase {case['id']}: {case['description']}", f"Stimulus: {case['stimulus']}",
                         f"Expected/check: {case['expected']}", "Coverpoints: " + ", ".join(case["coverpoints"])):
                output.append(comment(text))
            if case.get("mapping_reason"):
                output.append(comment("Mapping scope: " + case["mapping_reason"]))
        output.append(line)
    return ("".join(output) + newline + description_note(description, newline)).encode("utf-8")


def elf_description(path: Path) -> dict:
    """Read exactly one non-allocated ACT4 note from a structurally bounded ELF64 section table."""
    content = path.read_bytes()
    if len(content) < 64 or content[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError(f"Not an ELF64 description input: {path.name}")
    table = struct.unpack_from("<Q", content, 40)[0]
    size, count, strings = struct.unpack_from("<HHH", content, 58)
    if size < 64 or not count or strings >= count or table + count * size > len(content):
        raise ValueError(f"Missing ELF section table for ACT4 description: {path.name}")
    sections = [struct.unpack_from("<IIQQQQIIQQ", content, table + index * size) for index in range(count)]
    names_offset, names_size = sections[strings][4:6]
    if names_offset + names_size > len(content):
        raise ValueError("ELF section-name table exceeds file")
    names = content[names_offset:names_offset + names_size]
    matches = [section for section in sections if section[0] < len(names) and names[section[0]:].split(b"\0", 1)[0] == NOTE_NAME.encode()]
    if len(matches) != 1:
        raise ValueError(f"Require one {NOTE_NAME} section; retain it in the linker script: {path.name}")
    section = matches[0]
    offset, length = section[4:6]
    if section[1] != 7 or section[2] & 2 or length < 20 or offset + length > len(content):
        raise ValueError("ACT4 description must be a bounded non-allocated SHT_NOTE section")
    namesize, descsize, kind = struct.unpack_from("<III", content, offset)
    if namesize != 8 or kind != 1 or content[offset + 12:offset + 20] != b"UCAGENT\0" or descsize < 2 or 20 + (descsize + 3) // 4 * 4 != length:
        raise ValueError("Malformed ACT4 ELF description note")
    program_table = struct.unpack_from("<Q", content, 32)[0]
    program_size, program_count = struct.unpack_from("<HH", content, 54)
    if program_size < 56 or program_table + program_size * program_count > len(content):
        raise ValueError("Invalid program table for ACT4 description")
    for index in range(program_count):
        kind, flags, file_offset, virtual, physical, file_size, memory_size, alignment = struct.unpack_from("<IIQQQQQQ", content, program_table + index * program_size)
        if kind == 1 and max(file_offset, offset) < min(file_offset + file_size, offset + length):
            raise ValueError("ACT4 ELF description must not be part of a loadable segment")
    payload = content[offset + 20:offset + 20 + descsize]
    if not payload.endswith(b"\0"):
        raise ValueError("ACT4 description must end with a NUL byte")
    return json.loads(payload[:-1].decode("utf-8"))


def trace_report(trace: dict, tests: list[dict], features: list[dict]) -> str:
    """Render every testcase and reverse coverpoint/norm link without implying measured coverage."""
    products = {test["path"]: test for test in tests}
    text = "\n# ACT test index and design\n\nStatic design links, not measured coverpoint/bin hits. Native ACT suite paths, testcase IDs and covergroup/coverpoint IDs are preserved.\n"
    text += "\n## Program index\n\n| ACT program | Purpose | Coverpoints | Build | Run |\n| --- | --- | --- | --- | --- |\n"
    for test in trace["tests"]:
        points = sorted({point for case in test["cases"] for point in case["coverpoints"]})
        product = products[test["path"]]
        summary = test["summary"].replace("|", "\\|").replace("\n", " ")
        text += f"| [{test['path']}](src/{test['path']}) | {summary} | {', '.join(points)} | {product['build_status']} | {product['run_status']} |\n"
    text += "\n## Requested scope and gaps\n\nThis navigation does not rename ACT tests or establish complete manual coverage.\n\n"
    for feature in features:
        text += f"- {feature['description']}: {', '.join(feature['act4_suites']) or 'no ACT suite'}; {feature['resolution']}. {feature['assessment']}\n"
        if feature.get("gap"):
            text += f"  Upstream gap: {feature['gap']}. {feature.get('next_action', '')}\n"
    text += "\n## Program designs\n"
    reverse = {}
    for test in trace["tests"]:
        product = products[test["path"]]
        text += f"\n### {test['path']}\n\n{test['summary']}\n\n"
        text += f"Source: [src/{test['path']}](src/{test['path']}); ELF: `{product.get('elf', 'not built')}`.\n\n"
        for field in ("preconditions", "setup", "exercise", "check", "limitations"):
            text += f"- {field.capitalize()}: {test[field]}\n"
        if product.get("run_reason"):
            text += f"- Run diagnosis: {product['run_reason']}\n"
        for case in test["cases"]:
            text += f"\n#### {case['id']}\n\n{case['description']}\n\n- Stimulus/design: {case['stimulus']}\n- Expected/check: {case['expected']}\n"
            if case.get("mapping_reason"):
                text += f"- Mapping scope: {case['mapping_reason']}\n"
            text += "- Coverpoints: " + ", ".join(f"`{point}`" for point in case["coverpoints"]) + "\n"
            for point in case["coverpoints"]:
                reverse.setdefault(point, []).append(f"`{test['path']} / {case['id']}`")
    text += "\n## Coverpoint to norm rules\n"
    for point in trace["coverpoints"]:
        text += f"\n### {point['id']}\n\n{point['intent']}\n\n"
        text += f"Definition: `framework/{point['definition']['path']}:{point['definition']['lines'][0]}`\n\n"
        text += "Tests: " + ", ".join(reverse[point["id"]]) + "\n\n"
        for link in point["rules"]:
            text += f"- `{link['id']}` ({link['kind']}): {link['reason']}\n"
    text += "\n## Norm rules\n"
    for rule in trace["rules"]:
        text += f"\n### {rule['id']}\n\n{rule['description']}\n\nSource: `framework/{rule['definition']['path']}:{rule['definition']['lines'][0]}`\n"
    return text


def safe_path(root: Path, name: str) -> Path:
    """Require a relative, regular path with no traversal or symlink components."""
    if not isinstance(name, str) or not name or "\\" in name or any(ord(char) < 32 for char in name):
        raise ValueError(f"Invalid relative path: {name!r}")
    relative = Path(name)
    if relative.is_absolute() or any(part in {"..", ".git"} for part in relative.parts) or relative == Path("."):
        raise ValueError(f"Path must stay within its directory: {name}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink paths are not accepted: {name}")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes its directory: {name}")
    return current


def sha256(path: Path) -> str:
    """Hash file bytes without loading large executables into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path: Path) -> dict:
    """Record content and executability without binding a package to the sender's umask."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular file: {path}")
    return {"sha256": sha256(path), "executable": bool(path.stat().st_mode & 0o111)}


def write_json(path: Path, data: dict) -> None:
    """Atomically publish a complete JSON record next to its destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_files(root: Path, files: dict) -> None:
    """Reject missing, substituted, or modified files in an exact inventory."""
    if not isinstance(files, dict) or not files:
        raise ValueError("The file inventory must not be empty")
    for name, expected in files.items():
        path = safe_path(root, name)
        if not path.is_file() or identity(path) != expected:
            raise ValueError(f"File changed or missing: {name}; restore the package or rebuild it")


def execute(argv: list[str], cwd: Path, log: Path, timeout: int, process_started=None, env=None) -> dict:
    """Capture a real command, terminating its entire process group on timeout."""
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError("timeout must be an integer in 1..86400 seconds")
    log.parent.mkdir(parents=True, exist_ok=True)
    record = {"argv": argv, "started_at": datetime.now(timezone.utc).isoformat()}
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            stream.write(str(error).encode())
            return {**record, "status": "unavailable", "reason": str(error)}
        try:
            if process_started is not None:
                process_started(process, timeout, log)
            code = process.wait(timeout=timeout)
            return {**record, "status": "passed" if code == 0 else "failed", "exit_code": code}
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return {**record, "status": "timeout", "reason": f"Exceeded {timeout} seconds"}
        except BaseException:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            raise


def inspect_elf(path: Path, memory: dict) -> dict:
    """Check a loadable RV64 little-endian RISC-V executable and its ACT selfcheck markers."""
    content = path.read_bytes()
    if len(content) < 64 or content[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError(f"Not a little-endian ELF64 file: {path.name}")
    elf_type, machine = struct.unpack_from("<HH", content, 16)
    entry, table = struct.unpack_from("<QQ", content, 24)
    entry_size, count = struct.unpack_from("<HH", content, 54)
    if elf_type != 2 or machine != 243 or entry_size < 56 or not count or table + count * entry_size > len(content):
        raise ValueError(f"Not a loadable RISC-V executable: {path.name}")
    origin, end = memory["base"], memory["base"] + memory["size"]
    executable_entry = False
    loaded, executable = [], []
    for index in range(count):
        kind, flags, offset, virtual, physical, file_size, mem_size, alignment = struct.unpack_from("<IIQQQQQQ", content, table + index * entry_size)
        if kind != 1 or not mem_size:
            continue
        if file_size > mem_size or offset + file_size > len(content) or not origin <= physical < physical + mem_size <= end:
            raise ValueError(f"ELF segment is invalid or outside declared RAM: {path.name}")
        executable_entry |= bool(flags & 1 and virtual <= entry < virtual + mem_size)
        loaded.append(content[offset:offset + file_size])
        if flags & 1:
            executable.append(content[offset:offset + file_size])
    if not executable_entry or not origin <= entry < end:
        raise ValueError(f"ELF entry is outside executable RAM: {path.name}")
    load_bytes = b"".join(loaded)
    if b"RVCP-SUMMARY:" not in load_bytes or b"TEST PASSED" not in load_bytes or b"TEST FAILED" not in load_bytes or b"RVCP-SUMMARY: TEST SIGRUN" in load_bytes:
        raise ValueError(f"Missing ACT selfcheck summaries in {path.name}; do not deliver a signature-generation ELF")
    if not any(bytes.fromhex("6b000500") in segment for segment in executable):
        raise ValueError(f"Missing XiangShan termination instruction in {path.name}")
    return {"entry": entry, "machine": "riscv", "xlen": 64}


def load_plan(root: Path) -> dict:
    """Load the selected source and target inventory before running any commands."""
    plan = json.loads(safe_path(root, "build-plan.json").read_text())
    if plan.get("schema_version") != 1 or not plan.get("tests"):
        raise ValueError("build-plan.json requires schema_version 1 and nonempty tests")
    verify_files(root, plan["files"])
    actual = set()
    for directory, children, files in os.walk(safe_path(root, "act4"), followlinks=False):
        children[:] = [name for name in children if name not in SOURCE_IGNORE_DIRS]
        for name in children:
            safe_path(root, str((Path(directory) / name).relative_to(root)))
        for name in files:
            if name == ".git" or name.endswith(".pyc"):
                continue
            relative = str((Path(directory) / name).relative_to(root))
            safe_path(root, relative)
            actual.add(relative)
    expected = {name for name in plan["files"] if name.startswith("act4/")}
    if actual != expected:
        raise ValueError(f"Frozen ACT sources changed: added={sorted(actual - expected)[:20]}, missing={sorted(expected - actual)[:20]}")
    return plan


def binary_extent(path: Path) -> tuple[int, int]:
    """Compute raw-image load address and extent from file-backed allocated ELF sections."""
    content = path.read_bytes()
    table = struct.unpack_from("<Q", content, 40)[0]
    size, count = struct.unpack_from("<HH", content, 58)
    if size < 64 or table + size * count > len(content):
        raise ValueError(f"Invalid ELF section table: {path.name}")
    program_table = struct.unpack_from("<Q", content, 32)[0]
    program_size, program_count = struct.unpack_from("<HH", content, 54)
    programs = [struct.unpack_from("<IIQQQQQQ", content, program_table + index * program_size) for index in range(program_count)]
    ranges = []
    for index in range(count):
        section = struct.unpack_from("<IIQQQQIIQQ", content, table + index * size)
        _, kind, flags, address, offset, length, *_ = section
        if not flags & 2 or kind == 8 or not length:
            continue
        matches = [program for program in programs if program[0] == 1 and program[2] <= offset
                   and offset + length <= program[2] + program[5] and address - program[3] == offset - program[2]]
        if len(matches) != 1:
            raise ValueError(f"Allocated section has no unique load mapping: {path.name}")
        load_address = matches[0][4] + address - matches[0][3]
        ranges.append((load_address, load_address + length))
    if not ranges:
        raise ValueError(f"No file-backed allocated sections for binary export: {path.name}")
    start, end = min(item[0] for item in ranges), max(item[1] for item in ranges)
    return start, end - start


def build(root: Path, output: str, timeout: int, jobs: int, process_started=None, env=None) -> dict:
    """Build fresh native selfchecking ELFs, retaining Sail evidence and every selection gap."""
    plan = load_plan(root)
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError("timeout must be an integer in 1..86400 seconds")
    if type(jobs) is not int or not 1 <= jobs <= 64:
        raise ValueError("jobs must be in 1..64")
    result_path = safe_path(root, output)
    result_name = str(result_path.relative_to(root))
    if result_name in plan["files"] or result_name in {"build-plan.json", "manifest.json", "README.md"}:
        raise ValueError("Build output must not overwrite packaged source or manifest files")
    attempt = safe_path(root, f"builds/{uuid.uuid4().hex}")
    attempt.mkdir(parents=True)
    safe_path(root, "act4/coverpoints").mkdir(exist_ok=True)
    work = attempt / "work"
    deadline = time.monotonic() + timeout
    versions = {}
    for label, command in plan["tools"].items():
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            break
        log = attempt / f"version-{label}.log"
        versions[label] = {**execute([command, "--version"], root / "act4", log, min(10, remaining), process_started, env=env), "log": str(log.relative_to(root))}
    argv = ["uv", "run", "--frozen", "act", "config/xiangshan-kmhv3/test_config.yaml",
            "--test-dir", "selected-tests", "--workdir", str(work), "--jobs", str(jobs)]
    remaining = int(deadline - time.monotonic())
    if remaining < 1:
        (attempt / "build.log").write_text("Build budget exhausted during tool probes\n")
        record = {"argv": argv, "status": "timeout", "reason": "Build budget exhausted during tool probes"}
    else:
        record = execute(argv, root / "act4", attempt / "build.log", remaining, process_started, env=env)
    record.update(schema_version=1, plan_sha256=sha256(root / "build-plan.json"), tests=[],
                  log=str((attempt / "build.log").relative_to(root)), artifacts={}, errors=[], tool_versions=versions)
    record["artifacts"][record["log"]] = identity(attempt / "build.log")
    record["artifacts"].update({item["log"]: identity(root / item["log"]) for item in versions.values()})
    try:
        load_plan(root)
        expected = set()
        for test in plan["tests"]:
            name = str(Path(test["path"]).with_suffix(".elf"))
            expected.add(name)
            elf = safe_path(work / "xiangshan-kmhv3/elfs", name)
            metadata = inspect_elf(elf, plan["memory"])
            if elf_description(elf) != test["description"]:
                raise ValueError(f"ELF description does not match the frozen test mapping: {name}")
            binary = elf.with_suffix(".bin")
            disassembly = elf.with_suffix(".disass")
            binary_base, binary_size = binary_extent(elf)
            related = [elf, binary, disassembly]
            for command, log in (([plan["tools"]["objcopy"], "-O", "binary", str(elf), str(binary)], elf.with_suffix(".objcopy.log")),
                                 ([plan["tools"]["objdump"], "-d", str(elf)], disassembly)):
                remaining = int(deadline - time.monotonic())
                if remaining < 1:
                    raise ValueError("Build budget exhausted during binary/disassembly export")
                conversion = execute(command, root, log, remaining, process_started, env=env)
                record["artifacts"][str(log.relative_to(root))] = identity(log)
                if conversion["status"] != "passed":
                    raise ValueError(f"Product export failed: {log.relative_to(root)}")
            if binary.stat().st_size != binary_size or not disassembly.stat().st_size:
                raise ValueError(f"Binary extent or disassembly is invalid: {name}")
            if test["needs_signature"]:
                for suffix in (".sig", ".results", ".sig.log"):
                    evidence = safe_path(work / "xiangshan-kmhv3/build", str(Path(test["path"]).with_suffix(suffix)))
                    if not evidence.is_file() or not evidence.stat().st_size:
                        raise ValueError(f"Missing native Sail evidence for {test['path']}: {suffix}")
                    related.append(evidence)
            record["tests"].append({"source": test["path"], "elf": str(elf.relative_to(root)),
                                    "bin": str(binary.relative_to(root)), "disass": str(disassembly.relative_to(root)),
                                    "binary_load_address": binary_base, **metadata})
            record["artifacts"].update({str(path.relative_to(root)): identity(path) for path in related})
        actual = {str(path.relative_to(work / "xiangshan-kmhv3/elfs")) for path in (work / "xiangshan-kmhv3/elfs").rglob("*.elf")}
        if actual != expected:
            raise ValueError(f"Native test selection differs: missing={sorted(expected - actual)[:20]}, extra={sorted(actual - expected)[:20]}")
    except (ValueError, OSError) as error:
        record["errors"].append(str(error))
        if record["status"] == "passed":
            record["status"] = "failed"
    write_json(result_path, record)
    return record


def validate_build(root: Path, result: dict) -> dict:
    """Bind compiled outputs to the current source plan and exact expected test set."""
    plan = load_plan(root)
    if result.get("status") != "passed" or result.get("plan_sha256") != sha256(root / "build-plan.json"):
        raise ValueError("A successful build for the current source plan is required")
    if result.get("errors") or sorted(test["source"] for test in result["tests"]) != sorted(test["path"] for test in plan["tests"]):
        raise ValueError("Build result does not cover the complete selected test set")
    verify_files(root, result["artifacts"])
    descriptions = {test["path"]: test["description"] for test in plan["tests"]}
    for test in result["tests"]:
        inspect_elf(safe_path(root, test["elf"]), plan["memory"])
        if elf_description(safe_path(root, test["elf"])) != descriptions[test["source"]]:
            raise ValueError(f"ELF description differs from its source: {test['source']}")
        base, length = binary_extent(safe_path(root, test["elf"]))
        if test["binary_load_address"] != base or safe_path(root, test["bin"]).stat().st_size != length:
            raise ValueError(f"Binary layout differs from ELF: {test['source']}")
    return plan


def run(root: Path, result_file: str, emu: str, timeout: int, cycles: int, output: str, process_started=None, env=None) -> dict:
    """Run every selected final ELF, requiring both ACT selfcheck and a good simulation trap."""
    result = json.loads(safe_path(root, result_file).read_text())
    plan = validate_build(root, result)
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError("timeout must be an integer in 1..86400 seconds")
    output_path = safe_path(root, output)
    result_name = str(output_path.relative_to(root))
    if result_name in plan["files"] or result_name in result["artifacts"] or result_name in {str(Path(result_file)), "build-plan.json", "manifest.json", "README.md"}:
        raise ValueError("Run output must not overwrite packaged source, build evidence or manifest files")
    report = run_elfs(root, result["tests"], plan["target"], emu, timeout, cycles, "runs", process_started, env)
    report["build_sha256"] = sha256(root / result_file)
    validate_build(root, result)
    write_json(output_path, report)
    return report


def run_elfs(root: Path, tests: list[dict], target: dict, emu: str, timeout: int, cycles: int,
             log_directory: str, process_started=None, env=None) -> dict:
    """Run an exact nonempty program selection with shared ACT and XiangShan verdict rules."""
    if not tests or type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError("Select at least one program and a timeout in 1..86400 seconds")
    executable = Path(emu).expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"Provide an executable XiangShan emulator: {executable}")
    if type(cycles) is not int or cycles <= 0:
        raise ValueError("cycles must be a positive integer")
    attempt = safe_path(root, f"{log_directory}/{uuid.uuid4().hex}")
    attempt.mkdir(parents=True)
    report = {"schema_version": 1, "status": "passed",
              "emulator_sha256": sha256(executable), "target": target,
              "target_identity_verified": False, "tests": [], "artifacts": {}}
    deadline = time.monotonic() + timeout
    for index, test in enumerate(tests):
        log = attempt / f"{index:05d}.log"
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            log.write_text("Execution budget exhausted before this test started\n")
            record = {"status": "not_run", "reason": "Execution budget exhausted"}
        else:
            record = execute([str(executable), "-i", str(safe_path(root, test["elf"])), "--no-diff", "-C", str(cycles)], root, log, remaining, process_started, env=env)
        summaries = []
        good, bad = False, False
        with log.open(errors="replace") as stream:
            for line in stream:
                summaries.extend(re.findall(r"RVCP-SUMMARY:\s*TEST\s+(PASSED|FAILED|SIGRUN)\b", line))
                good |= "HIT GOOD TRAP" in line
                bad |= any(marker in line for marker in ("HIT BAD TRAP", "CRITICAL ERROR", "EXCEEDING CYCLE/INSTR LIMIT"))
        if record["status"] == "passed" and (not good or bad or not summaries or set(summaries) != {"PASSED"}):
            record.update(status="failed", reason="Require PASSED selfcheck and GOOD TRAP, without BAD TRAP, SIGRUN or cycle-limit termination")
        record.update(source=test["source"], log=str(log.relative_to(root)))
        report["tests"].append(record)
        report["artifacts"][record["log"]] = identity(log)
        if record["status"] != "passed":
            report["status"] = "failed"
    return report
