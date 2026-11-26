"""Distinguish a reproducible frozen rule-index mismatch from a suite CTP regression."""

from pathlib import Path
import re
import shutil

from .generation_inputs import load_rules
from .xiangshan_bundle import safe_path, sha256


def missing_ctp_rules(log: Path, checkout: Path) -> dict[str, list[str]]:
    """Recognize only the native normrules target failing on named missing index entries."""
    missing = {}
    make_errors = 0
    prefix = re.escape(str(checkout / "coverpoints/norm") + "/")
    with log.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("Error:"):
                match = re.fullmatch(r"Error: " + prefix + r"([\w.-]+\.yaml): (\d+) rules not in norm-rules\.json: ([\w., -]+)", line.rstrip())
                if not match:
                    return {}
                filename, count, names = match.groups()
                rules = names.split(", ")
                if (filename in missing or int(count) != len(rules) or len(set(rules)) != len(rules)
                        or not all(re.fullmatch(r"[\w.-]+", rule) for rule in rules)):
                    return {}
                missing[filename] = sorted(rules)
            elif "***" in line and re.match(r"(?:g?make)(?:\[\d+\])?:", line):
                if not re.search(r"\*\*\* \[Makefile:\d+[:：] *normrules\]", line):
                    return {}
                make_errors += 1
    return missing if make_errors == 1 else {}


def validate_ctp_scope(checkout, baseline, suite, assets, chapters, published, directory, run, results):
    """Require equal baseline errors and fresh native tables and renders; keep both full-build logs."""
    full = results[-1]
    rules_arg = f"NORM_RULES_URL={published.as_uri()}"
    index = load_rules(published)
    for name, rules in full["missing_rules"].items():
        relative = f"coverpoints/norm/{name}"
        if not index.keys().isdisjoint(rules) or sha256(safe_path(checkout, relative)) != sha256(safe_path(baseline, relative)):
            return
    baseline_cmd = run("ctp_baseline", ["make", "-C", "docs/ctp", "normrules", rules_arg], baseline)
    results.append(baseline_cmd)
    errors = full["missing_rules"]
    if baseline_cmd["status"] != "failed" or missing_ctp_rules(directory / baseline_cmd["log"], baseline) != errors:
        full["reason"] = "Frozen baseline did not reproduce the exact missing rules; a passing full CTP build is required"
        return
    baseline_cmd.update(status="passed", command_status="failed", reason="Reproduced the identical frozen normrules failure", missing_rules=errors)
    scope = checkout.parent / "ctp-scope"
    scope.mkdir()
    (scope / "generators").symlink_to(checkout / "generators", target_is_directory=True)
    mappings = scope / "coverpoints/norm"
    mappings.mkdir(parents=True)
    mapping = safe_path(checkout, f"coverpoints/norm/{suite}.yaml")
    shutil.copyfile(mapping, mappings / mapping.name)
    (scope / "coverpoints/param").symlink_to(safe_path(checkout, "coverpoints/param"), target_is_directory=True)
    for name, args in (("ctp_testplans", ["testplans"]), ("ctp_suite_tables", ["normrules", f"REPO_ROOT={scope}"])):
        record = run(name, ["make", "-C", "docs/ctp", *args, rules_arg], checkout)
        results.append(record)
        if record["status"] != "passed":
            return
    generated = checkout / "docs/ctp/build/generated"
    plans = [Path(plan).with_suffix(".adoc").as_posix() for plan in assets["native_plans"]]
    norm = f"norm/{suite}_norm_rules.adoc"
    includes = [*(plan.replace("testplans/", "{testplansdir}/", 1) for plan in plans), norm]
    tables = [*plans, norm]
    param = f"param/{suite}_parameters.adoc"
    if assets["parameters"]["status"] == "required":
        tables.append(param)
    for table in tables:
        path = safe_path(generated, table)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing generated CTP table: {table}")
    if param in tables and f"include::../{param}[]" not in (generated / norm).read_text().splitlines():
        includes.append(param)
    chapter_lines = {line for chapter in chapters for line in safe_path(checkout, chapter).read_text().splitlines()}
    directives = [f"include::{target}[]" for target in includes]
    if not set(directives) <= chapter_lines:
        raise ValueError("Cannot establish exact suite table includes from the declared CTP chapters; a full CTP build is required")
    document = safe_path(checkout, "docs/ctp/src/act4-suite-tables.adoc")
    outputs = [safe_path(checkout, f"docs/ctp/build/{document.stem}.{extension}") for extension in ("html", "pdf")]
    if any(output.exists() for output in outputs):
        raise ValueError("Scoped CTP render needs fresh outputs in the isolated checkout")
    with document.open("x", encoding="utf-8") as stream:
        stream.write(f"= {suite} CTP tables\n:testplansdir: testplans\ninclude::../common/adoc_common.adoc[]\n\n" + "\n\n".join(directives) + "\n")
    record = run("ctp_suite_render", ["make", "-C", "docs/ctp", "--old-file=testplans", "--old-file=normrules",
                                      f"DOCS={document.stem}", "build", rules_arg], checkout)
    results.append(record)
    if record["status"] != "passed":
        return
    for output, signature in zip(outputs, (b"<!DOCTYPE html>", b"%PDF-"), strict=True):
        if not output.is_file() or not output.stat().st_size:
            record.update(status="failed", reason=f"No native render produced: {output.name}")
            return
        with output.open("rb") as stream:
            if stream.read(len(signature)) != signature:
                record.update(status="failed", reason=f"Invalid native render: {output.name}")
                return
        retained = safe_path(directory, output.name)
        shutil.copyfile(output, retained)
        record.setdefault("outputs", {})[retained.name] = sha256(retained)
    full.update(status="baseline_limited", command_status="failed", reason="Full CTP build failed on unchanged out-of-scope mappings; only the suite tables were rendered")
