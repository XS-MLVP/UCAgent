"""Freeze native ACT plans and authenticated normative-rule inputs for generation."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen
from urllib.error import URLError

from .resources import git_text
from .xiangshan_bundle import safe_path, sha256, write_json


RULES_URL = "https://riscv.github.io/riscv-isa-manual/snapshot/norm-rules/norm-rules.json"


def native_plan_path(suite: str, kind: str) -> str:
    """Return the canonical upstream testplan path, rejecting ambiguous suite identifiers."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", suite) or kind not in {"privileged", "unprivileged"}:
        raise ValueError("Specify an exact ACT suite and privileged or unprivileged generation")
    return f"testplans/priv/{suite}.yaml" if kind == "privileged" else f"testplans/{suite}.csv"


def load_rules(path: Path, *, allow_empty: bool = False) -> dict[str, dict]:
    """Read the native norm-rules.json structure without accepting author-invented aliases."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("normative_rules"), list):
        raise ValueError(f"{path}: require a normative_rules array of name/text records")
    rules = {}
    for record in data["normative_rules"]:
        if (not isinstance(record, dict) or not isinstance(record.get("name"), str)
                or not re.fullmatch(r"[\w.-]+", record["name"])
                or not isinstance(record.get("text"), str)):
            raise ValueError(f"{path}: every rule needs a nonempty native name and a string text field")
        if record["name"] in rules:
            raise ValueError(f"{path}: duplicate normative rule {record['name']}")
        rules[record["name"]] = record
    if not rules and not allow_empty:
        raise ValueError(f"{path}: normative rule set is empty")
    return rules


def discover_generation_inputs(act4: Path, manual: Path, suite: str, kind: str,
                               manual_files: list[str], plan_paths: list[str] | None = None) -> dict:
    """Preview pinned plan families and specification candidates without freezing evidence."""
    default = native_plan_path(suite, kind)
    if (not isinstance(manual_files, list) or any(not isinstance(name, str) for name in manual_files)
            or len(set(manual_files)) != len(manual_files)):
        raise ValueError("manual_files must list distinct tracked specification paths")
    from .generation_run import git_source_files

    tracked = set(git_source_files(act4))
    family = sorted(name for name in tracked if Path(name).parent == Path(default).parent
                    and Path(name).suffix == Path(default).suffix
                    and (Path(name).stem == suite or Path(name).stem.startswith(suite + "_")))
    plans = plan_paths if plan_paths is not None else family or [default]
    pattern = r"testplans/priv/[A-Za-z0-9_]+\.yaml" if kind == "privileged" else r"testplans/[A-Za-z0-9_]+\.csv"
    if (not isinstance(plans, list) or not plans or any(not isinstance(name, str) or not re.fullmatch(pattern, name) for name in plans)
            or len(set(plans)) != len(plans)):
        raise ValueError("plan_paths must list distinct native plans in this workflow's testplans directory")
    if set(family) - set(plans):
        raise ValueError(f"plan_paths omits discovered suite members: {sorted(set(family) - set(plans))}")
    sources = {name: "plans/" + name for name in plans if name in tracked
               and safe_path(act4, name).is_file()}
    context = "\n".join(safe_path(act4, name).read_text(encoding="utf-8") for name in sources)
    mentions = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(suite) + r"(?![A-Za-z0-9_])", re.I)
    if len(suite) <= 2:
        mentions = re.compile(r'["`]' + re.escape(suite) + r'["`]|\b' + re.escape(suite) + r' extension\b', re.I)
    plan_references = set(re.findall(r"norm:([\w.-]+)", context))
    manual_head = git_text(manual, "rev-parse", "HEAD")
    if git_text(manual, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("ISA source has tracked modifications; use a clean pinned manual checkout")
    for name in manual_files:
        safe_path(manual, name)
        if Path(name).suffix not in {".adoc", ".md", ".rst"}:
            raise ValueError(f"Select tracked specification text (.adoc, .md or .rst): {name}")
        text = git_text(manual, "show", f"{manual_head}:{name}")
        if Path(name).stem.lower() == suite.lower():
            context += "\n" + text
        else:
            lines = text.splitlines()
            relevant = set()
            for number, line in enumerate(lines):
                if mentions.search(line) or plan_references.intersection(re.findall(r"norm:([\w.-]+)", line)):
                    relevant.update(range(max(0, number - 12), min(len(lines), number + 13)))
            context += "\n" + "\n".join(lines[number] for number in sorted(relevant))
    references = set(re.findall(r"(?:<<|xref:)([\w.:-]+)", context))
    dependencies = {token.lower() for token in re.findall(r"\b(?:S[msv]|Z)[A-Za-z0-9]+\b", context)}
    candidates = {}
    for name in git_text(manual, "ls-tree", "-r", "--name-only", manual_head).splitlines():
        if Path(name).suffix not in {".adoc", ".md", ".rst"}:
            continue
        candidate = manual / name
        if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents):
            continue
        path = safe_path(manual, name)
        text = path.read_text(encoding="utf-8")
        anchors = set(re.findall(r"\[(?:\[|#)([\w.:-]+)\]", text))
        hits = [{"line": number, "text": line[:200]} for number, line in enumerate(text.splitlines(), 1) if mentions.search(line)]
        referenced = sorted(anchors & references)
        dependency = Path(name).stem.lower() in dependencies
        if hits or referenced or dependency:
            candidates[name] = {"mentions": hits[:3], "referenced_anchors": referenced[:20],
                                "extension_dependency": dependency}
    return {"native_plans": plans, "source_plans": sources, "new_suite": not sources,
            "manual_candidates": candidates}


def read_generation_inputs(directory: Path, get_value) -> dict:
    """Verify recorded preparation, immutable snapshots, and both pinned repositories."""
    receipt = directory / "receipt.json"
    if not receipt.is_file() or get_value(f"act4_generation_inputs:{directory}", None) != sha256(receipt):
        raise ValueError("Return to prepare_generation_inputs and prepare the sources; do not edit its receipt")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2 or not isinstance(data.get("native_plans"), list) or not data["native_plans"]:
        raise ValueError("Generation inputs require a reviewed native_plans scope; start a new generation run")
    for name, digest in data["files"].items():
        if sha256(safe_path(directory, name)) != digest:
            raise ValueError(f"Generation input changed: {name}; restore the captured input")
    for role in ("act4", "manual"):
        if git_text(Path(data[role]["path"]), "rev-parse", "HEAD") != data[role]["head"]:
            raise ValueError(f"Pinned {role} revision changed; start a new generation run")
    for name, digest in data["manual_sources"].items():
        if sha256(safe_path(Path(data["manual"]["path"]), name)) != digest:
            raise ValueError(f"Read-only ISA source changed: {name}; restore the pinned checkout")
    return data


def prepare_generation_inputs(directory: Path, act4: Path, manual: Path, suite: str,
                              kind: str, manual_files: list[str], plan_paths: list[str] | None = None,
                              manual_exclusions: dict | None = None, previous: tuple[Path, dict] | None = None) -> dict:
    """Snapshot pinned native inputs; the public rule index and manual revisions remain distinct."""
    if (not isinstance(manual_files, list) or not manual_files
            or any(not isinstance(name, str) for name in manual_files)
            or len(set(manual_files)) != len(manual_files)):
        raise ValueError("manual_files must list distinct tracked specification files relevant to this suite")
    scope = discover_generation_inputs(act4, manual, suite, kind, manual_files, plan_paths)
    exclusions = manual_exclusions if manual_exclusions is not None else {}
    if (not isinstance(exclusions, dict) or any(not isinstance(name, str) or not isinstance(reason, str) or not reason.strip()
                                             for name, reason in exclusions.items())
            or exclusions.keys() - scope["manual_candidates"].keys() or exclusions.keys() & set(manual_files)):
        raise ValueError("manual_exclusions must explain omitted candidate paths; captured files cannot be excluded")
    missing = scope["manual_candidates"].keys() - set(manual_files) - exclusions.keys()
    if missing:
        raise ValueError(f"Specification scope has unreviewed candidates: {sorted(missing)}; discover and read them, "
                         "then include relevant files or explain each omission in manual_exclusions")
    heads = {"act4": {"path": str(act4), "head": git_text(act4, "rev-parse", "HEAD")},
             "manual": {"path": str(manual), "head": git_text(manual, "rev-parse", "HEAD")}}
    if git_text(manual, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("ISA source has tracked modifications; use a clean pinned manual checkout")
    if previous:
        old_directory, old = previous
        if (any(old[role] != heads[role] for role in heads) or old["suite"] != suite or old["kind"] != kind
                or set(old["native_plans"]) - set(scope["native_plans"]) or old["manual_sources"].keys() - set(manual_files)):
            raise ValueError("extend may only add plans or manual files at the same pinned revisions; preserve existing scope")
    directory.mkdir(parents=True, exist_ok=True)
    files, manual_sources, tags, locations = {}, {}, set(), {}
    for name in manual_files:
        if Path(name).suffix not in {".adoc", ".md", ".rst"}:
            raise ValueError(f"Select tracked specification text (.adoc, .md or .rst): {name}")
        source = safe_path(manual, name)
        content = source.read_bytes()
        original = subprocess.run(["git", "-C", str(manual), "show", f"{heads['manual']['head']}:{name}"],
                                  check=True, capture_output=True, timeout=30).stdout
        if original != content:
            raise ValueError(f"ISA source is not from the pinned commit: {name}")
        target = safe_path(directory, "manual/" + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files[target.relative_to(directory).as_posix()] = sha256(target)
        manual_sources[name] = sha256(source)
        for number, line in enumerate(content.decode("utf-8").splitlines(), 1):
            for tag in set(re.findall(r"\[(?:\[|#)norm:([\w.-]+)\]", line)):
                tags.add(tag)
                locations.setdefault(tag, []).append({"file": target.relative_to(directory).as_posix(), "line": number})
    index_status = previous[1]["index_status"] if previous else "downloaded"
    if previous:
        content = (old_directory / "published-norm-rules.json").read_bytes()
    else:
        try:
            with urlopen(RULES_URL, timeout=60) as response:
                if not response.geturl().startswith("https://riscv.github.io/riscv-isa-manual/"):
                    raise ValueError("Normative-rule download redirected outside the official ISA publication")
                content = response.read(20_000_001)
        except (URLError, TimeoutError):
            index_status = "unavailable"
            content = b'{"normative_rules": []}'
    if len(content) > 20_000_000:
        raise ValueError("Normative-rule response exceeds the bounded snapshot size")
    published = directory / "published-norm-rules.json"
    published.write_bytes(content)
    rules = load_rules(published, allow_empty=True)
    selected = sorted(tags & rules.keys())
    write_json(directory / "norm-rules.json", {"normative_rules": [rules[name] for name in selected]})
    files[published.name] = sha256(published)
    files["norm-rules.json"] = sha256(directory / "norm-rules.json")
    companion_plans = {}
    if kind == "privileged":
        for plan in scope["native_plans"]:
            companion = str(Path(plan).with_suffix(".csv"))
            if safe_path(act4, companion).is_file():
                companion_plans[companion] = "plans/" + companion
    for plan, snapshot in {**scope["source_plans"], **companion_plans}.items():
        content = safe_path(act4, plan).read_bytes()
        target = safe_path(directory, snapshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files[snapshot] = sha256(target)
    schema_path = "testplans/priv/testplan.schema.json"
    if kind == "privileged":
        schema = subprocess.run(["git", "-C", str(act4), "show", f"{heads['act4']['head']}:{schema_path}"],
                                check=True, capture_output=True, timeout=30)
        (directory / "testplan.schema.json").write_bytes(schema.stdout)
        files["testplan.schema.json"] = sha256(directory / "testplan.schema.json")
    non_text_rules = [name for name in selected if not rules[name]["text"].strip()]
    limitations = ["Published rule text and pinned manual are separate snapshots; compare semantics before implementation."]
    if index_status == "unavailable":
        limitations.append("Published rule index was unavailable; source-bound rules are not published rule IDs.")
    if non_text_rules:
        limitations.append("Selected non-text rules require inspection of the original encoding figures/tables and their dependencies; empty published text is not a semantic explanation.")
    data = {"schema_version": 2, "suite": suite, "kind": kind, **heads, **scope,
            "manual_exclusions": exclusions, "companion_plans": companion_plans,
            "files": files, "manual_sources": manual_sources,
            "rules_url": RULES_URL, "index_status": index_status, "unpublished_tags": sorted(tags - rules.keys()),
            "rule_locations": locations, "non_text_rules": non_text_rules, "pending_rules": {},
            "limitations": limitations}
    write_json(directory / "receipt.json", data)
    if previous and old["pending_rules"]:
        bindings = [{field: record[field] for field in ("name", "source", "start_line", "end_line", "text", "upstream")}
                    for name, record in load_rules(old_directory / "norm-rules.json").items() if name in old["pending_rules"]]
        data = bind_source_rules(directory, data, bindings)
    return data


def bind_source_rules(directory: Path, data: dict, bindings: list[dict]) -> dict:
    """Bind pending rule names to exact immutable source excerpts without forging published IDs."""
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("rule_bindings must be a nonempty list of source excerpts")
    rules = load_rules(directory / "norm-rules.json", allow_empty=True)
    published = load_rules(directory / "published-norm-rules.json", allow_empty=True)
    additions = {}
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"name", "source", "start_line", "end_line", "text", "upstream"}:
            raise ValueError("Each binding requires name, source, start_line, end_line, text and upstream")
        name, source = binding["name"], binding["source"]
        start, end = binding["start_line"], binding["end_line"]
        if not isinstance(name, str) or not re.fullmatch(r"[\w.-]+", name) or name in rules or name in additions or name in published:
            raise ValueError(f"Rule {name!r} is invalid or already indexed; select its actual tagged source instead")
        if not isinstance(source, str) or source not in data["manual_sources"]:
            raise ValueError("Bind only a file captured in manual_sources; start a new run to change source scope")
        lines = safe_path(directory, "manual/" + source).read_text(encoding="utf-8").splitlines()
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise ValueError(f"Invalid source line range for {name}")
        text = "\n".join(lines[start - 1:end])
        if not text.strip() or binding["text"] != text:
            raise ValueError(f"{name}: text must exactly match the captured source lines, not an AI paraphrase")
        if not isinstance(binding["upstream"], str) or not binding["upstream"].strip():
            raise ValueError(f"{name}: identify the pending tag proposal or upstream tracking location")
        additions[name] = {"name": name, "text": text, "status": "pending_source_binding", **{
            field: binding[field] for field in ("source", "start_line", "end_line", "upstream")}}
    rules.update(additions)
    write_json(directory / "norm-rules.json", {"normative_rules": list(rules.values())})
    data["files"]["norm-rules.json"] = sha256(directory / "norm-rules.json")
    for name, record in additions.items():
        data["pending_rules"][name] = record["upstream"]
        data["rule_locations"][name] = [{"file": "manual/" + record["source"], "line": record["start_line"],
                                         "end_line": record["end_line"]}]
    limitation = "Source-bound pending rules require native untagged_upstream tracking; they are not published rule IDs."
    if limitation not in data["limitations"]:
        data["limitations"].append(limitation)
    write_json(directory / "receipt.json", data)
    return data
