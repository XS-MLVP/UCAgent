"""Render evidence-bound delivery views without reading files or interpreting test code."""

from html import escape
import json
import posixpath
from urllib.parse import quote, urlsplit


SUMMARY_START = "<!-- toffee-ut-summary:start -->"
SUMMARY_END = "<!-- toffee-ut-summary:end -->"


def _text(value):
    """Keep evidence literal in Markdown text, tables, summaries and link labels."""
    if value is None:
        value = "not recorded"
    elif isinstance(value, (dict, list, bool)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return escape(str(value)).translate(str.maketrans({
        "`": "&#96;", "|": "&#124;", "[": "&#91;", "]": "&#93;",
        "*": "&#42;", "_": "&#95;", "~": "&#126;", "\\": "&#92;",
        "#": "&#35;", "\r": "&#13;", "\n": "<br>",
    }))


def _pre(value):
    """Display raw structured evidence or diagnostics without enabling HTML or fences."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return "<pre>" + escape(value).replace("`", "&#96;") + "</pre>"


def report_link(data, path, label=None, *, workspace=False):
    """Link project artifacts or workspace requirement sources from docs/README.md."""
    path = str(path)
    if path.startswith(("http://", "https://")) and urlsplit(path).netloc:
        target = quote(path, safe="/:?#&=%")
    else:
        provenance = data["provenance"]
        base = provenance["workspace_root"] if workspace else provenance["project_root"]
        filename, separator, fragment = path.partition("#") if workspace else (path, "", "")
        absolute = posixpath.normpath(posixpath.join(base, filename))
        relative = posixpath.relpath(absolute, posixpath.join(provenance["project_root"], "docs"))
        target = quote(relative, safe="/")
        if separator:
            target += "#" + quote(fragment, safe="")
    return "[" + _text(path if label is None else label) + "](" + target + ")"


def render_summary(data):
    """Render the complete owned block from validated run data and maintained contracts."""
    cases = data["case_details"]
    contracts = data["contracts"]
    provenance = data["provenance"]
    issues = data["issues"]
    lines = [SUMMARY_START, "", "## ToffeeUT result", "",
             f"**Delivery status: {_text(data['status'])}**", "",
             f"- Run: {report_link(data, data['run'])}",
             f"- Full selection: {_text(data['full_selection'])}",
             f"- Requested seed: {_text(data['requested_seed'])}", "",
             "Counts are exact pytest nodeids, not requirements, iterations, transactions or RTL defects. "
             "Non-selftest means functional-candidate selection, not proof of implementation or checking. "
             "Committed artifacts, exit code 0 and coverage hits are not hardware PASS.", "",
             "| Case population | Total | Raw outcomes |", "|---|---:|---|"]
    for population, counts in data["case_counts"].items():
        lines.append(f"| {_text(population)} | {counts['total']} | {_text(counts['outcomes'])} |")
    lines.extend(["", "### Scope and evidence gaps", ""])
    for field in ("problems", "missing_scenarios", "unconfirmed_requirements", "scope_exclusions",
                  "unregistered_cases", "unclassified_failures", "static_candidates"):
        lines.append(f"- {_text(field)}: {_text(data[field])}")
    lines.append(f"- Functional coverage target met: {_text(data['functional_coverage']['covered'])}")
    native = data["native_coverage"]
    lines.append(f"- Native coverage required: {_text(native['required'])}; review state: "
                 + _text(native["review"]["state"]))
    for metric in ("line", "branch", "toggle"):
        lines.append(f"- Native {metric} collection: {_text(native[metric]['state'])}; coverage: "
                     + _text(native[metric]["coverage"]) + " (not functional proof)")
    lines.extend(["",
                  "Scenario tags and call-phase success do not prove field comparisons, independent oracle use, "
                  "per-UID accounting or completion obligations were reached. Implementation status, actual "
                  "accepted stimulus, expected/observed values and per-transaction checked/failed/not-reached/"
                  "not-checked records are not established by this run receipt. No such results are inferred "
                  "from test names, assertion text or aggregate counts.", "",
                   "Maintained contracts: " + report_link(data, contracts["design_path"], "design") + "; "
                   + report_link(data, contracts["verification_path"], "verification") + "; "
                   + report_link(data, "docs/reviews/", "manual reviews (not runtime proof)") + ".", "",
                   "### Scenario-to-case traceability", "",
                   "All maintained scenarios remain visible, including those with no matching call-phase candidates "
                   "and deferred or out-of-domain scope. Matches are non-selftest scenario tags with a recorded "
                   "passed/failed call phase, not proof of native execution, implementation, field checking or "
                   "completion. Raw outcomes are case outcomes, not requirement verdicts; rows can share nodeids.", "",
                   "| Planned scenario | Requirement / basis | Maintained scope / reason | Call-phase candidate nodeids | Raw case outcomes |",
                   "|---|---|---|---|---|"])
    for scenario, contract in sorted(contracts["scenarios"].items()):
        observed = data["scenarios"].get(scenario, {})
        requirement = contracts["requirements"].get(contract.get("requirement"), {})
        scope = _text(contract.get("status"))
        if contract.get("reason"):
            scope += " / " + _text(contract["reason"])
        lines.append("| " + " | ".join((_text(scenario),
                     _text(contract.get("requirement")) + " / " + _text(requirement.get("basis")), scope,
                     "<br>".join(_text(node) for node in observed.get("nodeids", []))
                     or "No matching call-phase candidates recorded", _text(observed.get("outcomes")))) + " |")
    lines.extend(["", "### Bug / issue records", "",
                   f"Failed case count: {len(data['failing_nodes'])}. Current-run issue record count: {len(issues)}. "
                  "Independent root-cause count: not established. Neither count is an independent root-cause "
                  "count; matching diagnostics are not used to merge cases or issues.", "",
                  "| Maintained issue | Classification | State | Run | Source requirement / basis | Case nodeids |",
                  "|---|---|---|---|---|---|"])
    for issue in issues:
        requirement = contracts["requirements"].get(issue.get("requirement"), {})
        source = (_text(issue.get("requirement")) + " / " + _text(requirement.get("basis")))
        if requirement.get("source"):
            source += " / " + report_link(data, requirement["source"], workspace=True)
        lines.append("| " + " | ".join((report_link(data, issue["path"]), _text(issue["classification"]),
                     _text(issue["state"]), report_link(data, issue["run"]), source,
                     "<br>".join(_text(node) for node in issue["nodeids"]))) + " |")
    if not issues:
        lines.append("| No current-run typed issue records | — | — | — | — | — |")
    lines.extend(["", "Unattributed failing cases (never hidden by issue grouping): "
                  + _text(data["unclassified_failures"]) + ".", "",
                  "Classifications and evidence explanations are maintained issue claims, not generated "
                  "failure diagnostics. See each linked record for evidence, alternatives and next actions.", "",
                  "### Runtime and source / build provenance", "",
                  "Recorded test runtime (only fields present in the signed receipt):", "",
                  _pre(provenance["runtime"]), "", "Recorded selection:", "", _pre(provenance["selection"]), "",
                  f"- Recorded process exit code: {_text(provenance['returncode'])} (not a hardware verdict)",
                  f"- Source-map identity: {_text(provenance['source_identity'])}",
                  f"- Receipt signature: {_text(data['receipt_signature'])}", "",
                  "The source-map digest identifies the sorted source_after mapping; full source hashes and "
                  "build file identities remain in receipt.json and manifest.json, not duplicated here. "
                  "Unrecorded tool commits, build options and native seed effectiveness are not proved. "
                  "Equal requested or declared seeds do not establish identical native stimulus across versions.", "",
                  "Native builds (manifest identities, not a claim that every case used every build):", ""])
    for build in provenance["native_builds"]:
        lines.append("- " + _text(build))
    if not provenance["native_builds"]:
        lines.append("- None recorded.")
    lines.extend(["", "Raw run artifacts (the receipt and manifest retain complete identities):", ""])
    lines.extend("- " + report_link(data, path) for path in provenance["raw_artifacts"])
    lines.extend(["", "Coverage artifacts:", ""])
    lines.extend("- " + report_link(data, path) for path in data["coverage_artifacts"])
    if not data["coverage_artifacts"]:
        lines.append("- None recorded.")
    lines.extend(["", "### Detailed cases", "",
                  "Each scenario below is a **planned contract**, not a runtime comparison or completion "
                  "record. Diagnostics come only from recorded case phases; actual values are not reconstructed "
                  "from the plan. Captured messages are not parsed into comparisons, completion or effective seed "
                  "evidence. Native seed declarations are not verified effective seeds.", ""])
    for node, case in sorted(cases.items()):
        lines.extend([f"<details><summary>{_text(node)} — {_text(case['status'])}</summary>", "",
                      f"- Exact nodeid: {_text(node)}",
                      f"- Run: {report_link(data, data['run'])}; raw phases: "
                      + report_link(data, data["run"] + "/cases.json"),
                      f"- selftest: {_text(case['selftest'])}; roles: {_text(case.get('roles'))}",
                      f"- Requested seed: {_text(data['requested_seed'])}; declared_native_seed: "
                      + _text(case.get("declared_native_seed")) + "; effective native seed: not proved by receipt.",
                      "- Associated issues: " + ("; ".join(report_link(data, issue["path"]) for issue in issues
                          if node in issue["nodeids"]) or "none recorded"), "",
                      "| Phase | Outcome | Duration (s) | wasxfail |", "|---|---|---:|---|"])
        for phase in ("setup", "call", "teardown"):
            row = case["phases"].get(phase, {})
            lines.append("| " + " | ".join(_text(value) for value in (
                phase, row.get("outcome"), row.get("duration"), row.get("wasxfail"))) + " |")
        lines.extend(["", "Recorded phases and diagnostics (verbatim fields; failure text may be bounded at capture):",
                      "", _pre({phase: {key: value for key, value in row.items() if key != "captured_diagnostics"}
                                 for phase, row in case["phases"].items()})])
        for phase, row in case["phases"].items():
            if "captured_diagnostics" not in row:
                continue
            capture = row["captured_diagnostics"]
            lines.extend(["", f"**{_text(phase)} — runtime captured diagnostics, not independent proof**", "",
                          "Optional text from standard pytest sections only. Absence does not prove silence or "
                          "checking; retained text and truncation metadata do not prove its claims.", "",
                          _pre({key: value for key, value in capture.items() if key != "sections"})])
            for part in capture["sections"]:
                lines.extend(["", "- " + _text(part["name"]) + "; original_chars: " + _text(part["original_chars"])
                              + "; retained_chars: " + _text(part["retained_chars"]) + "; truncated: "
                              + _text(part["truncated"]), "", _pre(part["text"]).replace("\n#", "\n&#35;")])
        lines.extend(["", "Native DUT registrations and matching build identities:", ""])
        for identity in case.get("native_duts", []):
            matches = [build for build in provenance["native_builds"]
                       if identity in build["native_duts"]]
            lines.append("- " + _text(identity) + "; matching build IDs: "
                         + _text([build["build_id"] for build in matches]))
        if not case.get("native_duts"):
            lines.append("- None recorded; no native execution credit inferred.")
        lines.extend(["", "Waveform files (links do not prove analysis or continued file availability):", ""])
        for wave in case.get("waveforms", []):
            lines.append("- " + report_link(data, wave["path"]) + "; native_dut: " + _text(wave["native_dut"]))
        if not case.get("waveforms"):
            lines.append("- None recorded.")
        lines.extend(["- Waveform capture diagnostics: " + _text(case.get("waveform_errors")), "",
                      "#### Scenario contracts (planned, not runtime proof)", ""])
        for scenario in case["scenarios"]:
            contract = contracts["scenarios"].get(scenario)
            lines.append("- Scenario: " + _text(scenario))
            if contract is None:
                lines.append("  - No maintained scenario contract; no obligation inferred.")
                continue
            for field in ("status", "reason", "stimulus", "expected", "oracle", "completion"):
                if field in contract:
                    lines.append("  - " + field + ": " + _text(contract[field]))
            requirement = contracts["requirements"][contract["requirement"]]
            lines.append("  - Requirement: " + _text(contract["requirement"]) + "; basis: "
                         + _text(requirement["basis"]) + "; source: "
                         + report_link(data, requirement["source"], workspace=True))
            for field in ("statement", "precondition", "observation", "timing", "next_action"):
                if field in requirement:
                    lines.append("    - " + field + ": " + _text(requirement[field]))
        if not case["scenarios"]:
            lines.append("- No scenario tags recorded.")
        lines.extend(["", "</details>", ""])
    # JSON stays semantically unchanged, but evidence cannot inject owner markers.
    encoded = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c").replace(">", "\\u003e")
    lines.extend(["### Structured evidence summary", "", "```json", encoded, "```", "", SUMMARY_END])
    return "\n".join(lines)
