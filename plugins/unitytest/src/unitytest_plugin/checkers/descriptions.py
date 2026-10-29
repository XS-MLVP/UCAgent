# -*- coding: utf-8 -*-
"""UnityTest stage-description prompt blocks and mark-function diagnostics.

These helpers render the Bug-analysis contract text and the FG/FC/CK
document-format guidance that UnityTest checkers embed in their stage
descriptions and diagnostics. The shared machine contract itself stays in
``ucagent_common.bug_analysis_contract``.
"""

import ast
import textwrap

from ucagent_common.bug_analysis_contract import (
    BUG_ANALYSIS_SECTION_MARKERS,
    BUG_TODO_MARKER,
    DYNAMIC_BUGS_END_MARKER,
    DYNAMIC_BUGS_MARKER,
    DYNAMIC_BUG_DOCUMENT_PATH,
    RELATED_BUGS_MARKER,
    ROOT_ANALYSIS_SECTION_MARKERS,
    ROOT_CAUSE_ANALYSIS_MARKER,
    ROOT_CAUSES_END_MARKER,
    ROOT_CAUSES_MARKER,
    ROOT_CAUSE_REFERENCE_MARKER,
    ROOT_SOURCE_EVIDENCE_MARKERS,
    ROOT_SOURCE_UNAVAILABLE_MARKER,
    TEST_CASE_SERIALIZATION,
    WAVEFORM_BUG_ANALYSIS_FIELDS,
    WAVEFORM_BLOCK_KEY,
    WAVEFORM_EVIDENCE_END_MARKER,
    WAVEFORM_EVIDENCE_MARKER,
    WAVEFORM_FENCE_OPEN,
    WAVEFORM_LLM_ANALYSIS_FIELDS,
    WAVEFORM_REFERENCE_MARKER,
)
from ucagent_common.str_utils import list_str_abbr
from ucagent.util.log import warning
from ucagent_common.test_report import check_file_block, parse_test_case_name


def description_bug_doc():
    section_markers = " -> ".join(
        marker for _key, marker in BUG_ANALYSIS_SECTION_MARKERS
    )
    root_section_markers = " -> ".join(
        marker for _key, marker in ROOT_ANALYSIS_SECTION_MARKERS
    )
    source_markers = ", ".join(ROOT_SOURCE_EVIDENCE_MARKERS)
    shared_fields = ", ".join(WAVEFORM_LLM_ANALYSIS_FIELDS)
    bug_fields = ", ".join(WAVEFORM_BUG_ANALYSIS_FIELDS)
    return [
        "[Dynamic Bug Analysis Contract] Follow the active stage task and Guide_Doc/dut_bug_analysis.md for the complete workflow. When the active stage enables dynamic-bug-recording and its script is available, prefer that Skill's deterministic operations and ApplyWaveInfoEvidence, and avoid proactive direct edits to the Bug document. For a document-format blocker, attempt the returned next_action or -MODE repair once. If the same blocker remains or malformed structure prevents that recovery, edit only the exact reported markers, paths, or lines, preserve unrelated analysis and WAVEFORM-EVIDENCE content, and immediately rerun -MODE repair and Check. Follow the scope and after_edit call in a returned manual_edit_fallback. When Skill support or the script is unavailable, use text-editing tools for the same canonical contract.",
        f"  - The only dynamic Bug target is {DYNAMIC_BUG_DOCUMENT_PATH}. Its visible Markdown title is not a filename rule; never derive or create another filename from that title.",
        f"  - Keep the documented TC on the exact function-level report node: Markdown `{TEST_CASE_SERIALIZATION['markdown_tag']}`; recorder/Apply arguments and waveform YAML test_case `{TEST_CASE_SERIALIZATION['tool_or_yaml']}`. For a non-parameterized test, WaveInfo test_case_name is `{TEST_CASE_SERIALIZATION['waveinfo']}` for that same node. When Toffee aggregates parameterized executions, `tests.test_case_instances` lists exact child nodes; WaveInfo uses one FAILED child while the document TC stays unchanged. A child is related only when removing its final `[...]` leaves the byte-for-byte same workspace-relative path, optional class, and function.",
        f"  - Put dynamic Bug entries inside one closed {DYNAMIC_BUGS_MARKER} ... {DYNAMIC_BUGS_END_MARKER} container, root-cause entities inside one closed {ROOT_CAUSES_MARKER} ... {ROOT_CAUSES_END_MARKER} container, then waveform records inside one closed {WAVEFORM_EVIDENCE_MARKER} ... {WAVEFORM_EVIDENCE_END_MARKER} container.",
        "  - For a completed no-Bug result, keep the canonical document title and the three ordered closed containers, with every container body empty. Do not put explanatory prose, BG-*-0, TC/ROOT placeholders, comments, or waveform records in those bodies.",
        "  - Use the exact semantic heading hierarchy shown in Guide_Doc/dut_bug_analysis.md section 5.1 for FG, FC, CK, BG, and TC. Angle-bracket tags may be hidden by Markdown, so every visible title must describe the actual item rather than repeat its type.",
        "  - XX must be 1..100 for a dynamically reproduced DUT Bug. A zero-confidence BG is ignored and cannot explain a failed test.",
        "  - Every non-zero BG must contain at least one correctly implemented FAILED TC mapped to the same checkpoint.",
        "  - Validation is scoped to the full FG/FC/CK/BG path. Keep one BG occurrence per checkpoint branch, with all sibling TCs before the three BG fields and one root-cause reference.",
        "  - When one root cause affects FAILED TCs associated with different checkpoints, the same BG tag may repeat under those CK branches. Every CK-scoped BG path independently contains its three BG fields and one reference; the shared ROOT entity contains the full root analysis once. Central waveform data remains unique per TC.",
        f"  - Every BG path has exactly one root cause. Put one clickable {ROOT_CAUSE_REFERENCE_MARKER} at the end of <BUG-TRIGGER>; define the shared analysis once under {ROOT_CAUSE_ANALYSIS_MARKER}. A root cause may list multiple full BG paths under {RELATED_BUGS_MARKER}, and every link must be bidirectional. If a combination creates the defect, that combination is one distinct root cause.",
        "  - Every root-cause entity must use one document-wide unique <ROOT-NAME> tag and a visible title. Each entity must list at least one existing full BG path under <RELATED-BUGS>; each BG path must point to exactly one root entity through one <CAUSE-REF-ROOT-NAME> tag. Every reverse entry embeds its full path in <RELATED-BUG-FG-NAME/FC-NAME/CK-NAME/BG-NAME-XX> and adds a clickable link; the embedded path, link text, target BG, and generated anchor must match exactly.",
        "  - Every remaining FAILED DUT test must appear under at least one non-zero BG at one of the exact checkpoints associated with that test in the current report.",
        "  - A FAILED TC may trigger and cover a checkpoint that is itself PASSED. TC status and checkpoint coverage status are independent; never require every FAILED TC to map to an unhit checkpoint or infer checkpoint non-coverage from TC failure.",
        "  - Every remaining unhit checkpoint must have at least one correctly implemented FAILED TC that the current report associates with that exact FG/FC/CK path; the same CK/BG/TC relation must appear in the Bug document.",
        "  - Do not assume which side caused a FAILED TC. Before WaveInfo or a non-zero BG, derive an independent expected value from the specification, an independent reference model, or a verifiable formula. Record and compare the exact input, specification expected, test expected, DUT actual, and classification. If the two expected values differ, fix the test and rerun; do not record a Bug.",
        "  - If the expected values agree, validate the test stimulus/driver, API callbacks and Step ordering, valid sampling edge/condition and latency, fixtures, reference model, reset, and environment. Then validate the associated checkpoint coverage/check function, predicate, CovGroup.sample call, and sample timing. Fix each verification error and rerun before using WaveInfo.",
        "  - An unhit checkpoint does not by itself prove a DUT Bug. Only after the preceding checks are correct and the DUT actual still violates the specification may the FAILED TC proceed to WaveInfo and a non-zero dynamic BG.",
        f"  - The first non-empty content after every TC must be the exact {WAVEFORM_REFERENCE_MARKER} link generated by ApplyWaveInfoEvidence. Do not place YAML or a viewer inside a BG entry.",
        f"  - Each failed TC has exactly one central WAVEFORM-TC record whose visible heading reuses the TC title followed by the waveform suffix. Its {WAVEFORM_FENCE_OPEN} mapping must use {WAVEFORM_BLOCK_KEY} as the only top-level key and must be followed by the tool-generated WAVEFORM-VIEWER link. Do not copy, invent, or edit receipt-backed fields.",
        f"  - Complete shared field {shared_fields} once per TC. Under bug_evidence, complete {bug_fields} once for every associated BG. bug_tags and bug_evidence must exactly match all BG/TC references.",
        "  - ApplyWaveInfoEvidence owns one exact BG/TC association per call and preserves all non-target associations and central records. For multiple failed TCs with one root cause, reuse the BG and call each TC separately. If one failed TC exposes independent Bugs, keep distinct BGs and call the same TC once for each distinct bug_tag. All calls share one central record. Cross-BG application does not require replace_existing.",
        "  - For a TC associated with multiple Bugs, the signed signal_groups and viewer must include the union of every bug_evidence.<BG>.required_signals. If a new Bug needs another signal, obtain a new final receipt with the expanded signal set and apply it with replace_existing=true.",
        "  - A final WaveInfo call must provide complete signal_groups: the DUT clock mode and clock when present, relevant input data/control, relevant output data/status/validity, actual request/response protocol controls, and at least one function-specific selector, state, flag, or internal propagation signal. The same signed paths must be present in the timeline and online viewer; a target data bus alone is insufficient.",
        "  - Event pattern entries locate the failed transaction; signal_groups load context without creating extra triggers. Classify roles from the specification, DUT ports, test API/driver, and RTL, and use real signed paths. Do not infer protocol semantics from signal names.",
        "  - WaveInfo event matches are not automatic Bug decisions. The LLM must read the interface specification and test-driver/API Step ordering, identify ready/valid or the DUT's actual equivalent request-accept and response-valid conditions, account for backpressure and latency, and prove the observed output belongs to the failed transaction.",
        "  - One Step only advances simulation; it does not prove request acceptance or output validity. Check whether the API already steps/waits and sample only at the specified edge, after the required latency, or when response-valid/done/ack/busy conditions permit it.",
        "  - Do not classify a data mismatch sampled while valid/enable is inactive, ready/accept is false, reset/idle/transition rules make data invalid, or the documented response latency has not elapsed. Such a point is only an investigation clue unless the specification explicitly requires behavior there.",
        "  - The first non-empty content after the central YAML fence must be the same final WaveInfo result's <WAVEFORM-VIEWER> tagged Markdown link. Its marker, /wave/?meta= route, and signed metadata target must not be edited or constructed manually.",
        f"  - Inside every non-zero BG, include each analysis marker exactly once and in this order: {section_markers}.",
        "  - Put every TC and its WAVEFORM-REF directly after the owning BG heading. Put the three BG fields after the final TC/reference; no TC may appear after the first analysis marker.",
        f"  - Before each analysis marker, use the exact level-6 display title shown in Guide_Doc/dut_bug_analysis.md section 5.1, then write the field body after the marker. Keep this marker order: {section_markers}. Do not rename, translate, omit, duplicate, or reorder them.",
        f"  - Fill every marked BG field and every ROOT field with evidence-backed content and remove every {BUG_TODO_MARKER}. ROOT fields must appear in this order: {root_section_markers}; use the complete canonical reference in Guide_Doc/dut_bug_analysis.md section 5.1.",
        f"  - With source access, <ROOT-SOURCE-EVIDENCE> must contain a real HDL path:start-end and a complete HDL fenced block containing each marker exactly once: {source_markers}.",
        "  - Source locations must use an inclusive numeric range without an `L` prefix: `Adder/Adder.v:10-14` is valid, while `Adder/Adder.v:10` must be repaired to `Adder/Adder.v:10-10` and `Adder/Adder.v:L10-L14` must be repaired to `Adder/Adder.v:10-14`. This format-only repair does not require new tests, WaveInfo, or Bug classification.",
        f"  - Without source access, put one standalone {ROOT_SOURCE_UNAVAILABLE_MARKER} in <ROOT-SOURCE-EVIDENCE> and provide a black-box causal analysis from the interface contract, failure log, and waveform. This branch cannot contain an HDL fence or any {source_markers} marker.",
        "  - After classification confirms a DUT Bug and dynamic-bug-recording is available, prefer record_dynamic_bug.py with -MODE bug for the first exact TC association under each new BG path and -MODE root for each distinct ROOT. For a document-format blocker, attempt the returned next_action or -MODE repair once; edit only the exact reported markers, paths, or lines if the same blocker remains or malformed structure prevents that recovery, then immediately rerun -MODE repair and Check. Follow a returned manual_edit_fallback scope and after_edit call. Preserve unrelated analysis and WAVEFORM-EVIDENCE content. Add later sibling TCs under an existing CK/BG through WaveInfo and ApplyWaveInfoEvidence. When the Skill or script is unavailable, use text-editing tools to produce the same Guide_Doc/dut_bug_analysis.md section 5.1 contract.",
        "  - Keep only manifestation, severity, scope, and trigger-specific impact in the BG. Keep source evidence, causal chain, fix, risk, and revalidation in the owning ROOT entity; keep receipt/viewer/signal evidence in the central TC record.",
        "  - Fix test code, expected values, fixtures/APIs, reference models, timing, and environment failures until they pass. Never preserve a non-Bug failure with assert False, weakened assertions, or BG-*-0.",
    ]


def description_func_doc():
    return [
        "[Functions and Checkpoints Document Format] (see Guide_Doc/dut_functions_and_checks.md for details)",
        "  Tag hierarchy: <FG-GROUP> / <FC-FUNCTION> / <CK-CHECKPOINT>, tags must be on separate lines",
        "  Format example:",
        "    <FG-LOGIC>",
        "          Group description...",
        "            <FC-ADD>",
        "               Function description: Performs addition of two numbers.",
        "                <CK-BASIC>",
        "                  Checkpoint description: Verifies basic addition functionality.",
        "                <CK-OVERFLOW>",
        "                  Checkpoint description: Verifies addition overflow handling.",
        "             <FC-MUL>",
        "                ...",
        "    <FG-MEMORY>",
        "          ...",
    ]


def description_checkpoint_association_missing(check_points):
    """Explain checkpoint-to-test runtime association gaps without inferring a source cause."""
    check_points = list(check_points or [])
    return (
        "[Checkpoint Association Missing] Toffee defined the following checkpoint(s), but "
        "recorded no associated test execution: "
        f"{list_str_abbr(check_points)}. This runtime report state does not identify why the "
        "association was not recorded. Inspect the original `STDERR` and `STDOUT` attached to "
        "the Check/Complete result for Toffee warnings, then verify that the expected tests "
        "executed and that the fixture reported the active coverage-group objects after `yield`."
    )


def has_executable_mark_function_call(source_code):
    """Return whether source contains an actual ``.mark_function(...)`` call."""
    try:
        tree = ast.parse(textwrap.dedent(source_code))
    except (SyntaxError, IndentationError, TypeError):
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mark_function"
        for node in ast.walk(tree)
    )


def description_mark_function_doc(
    func_list=[], workspace=None, func_RunTestCases=None, timeout_RunTestCases=0
):
    """
    Description for marking functions in test cases.

    ``func_RunTestCases`` and ``timeout_RunTestCases`` are retained for caller
    compatibility. Diagnostics use the original STDOUT/STDERR already returned
    by Check/Complete and never rerun tests here.
    """
    simple_msg = (
        "Add an executable `mark_function` call near the beginning of each test and associate "
        "it with at least one checkpoint. Example: "
        "env.dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', "
        "test_function_name, ['CK-CHECK1', 'CK-CHECK2']). "
        "If a test covers checkpoints from multiple function points, call `mark_function` once "
        "for each function point. If the test is redundant, delete it. "
        "(See Guide_Doc/dut_test_case.md)"
    )

    if len(func_list) > 0:
        assert workspace is not None, "workspace must be provided if func_list is not empty."
        func_file_blocks = {}
        func_test_cases = {}
        unreadable_tc_list = []
        for tc in func_list:
            try:
                tc_name, (file_path, line_from, line_to) = parse_test_case_name(tc, workspace)
            except Exception as e:
                warning(f"Cannot resolve test case location '{tc}': {e}")
                unreadable_tc_list.append(tc)
                continue
            func_test_cases[tc] = tc_name
            if file_path not in func_file_blocks:
                func_file_blocks[file_path] = {}
            func_file_blocks[file_path][tc] = [line_from, line_to]

        blocks = {}
        try:
            checked_blocks = check_file_block(
                func_file_blocks,
                workspace,
                has_executable_mark_function_call,
                strip_comments=False,
            )
            for _, value in checked_blocks.items():
                blocks.update(value)
        except (AssertionError, OSError, UnicodeError) as e:
            warning(f"Cannot inspect test source for mark_function calls: {e}")
            unreadable_tc_list.extend(
                tc for tc in func_test_cases if tc not in unreadable_tc_list
            )

        no_mark_tc_list = []
        recorded_no_association_tc_list = []
        for tc in func_list:
            if tc in unreadable_tc_list:
                continue
            if tc not in blocks:
                unreadable_tc_list.append(tc)
            elif blocks[tc] is True:
                recorded_no_association_tc_list.append(tc)
            else:
                no_mark_tc_list.append(tc)

        messages = []
        if recorded_no_association_tc_list:
            tc_msg = (
                "[Call present, association absent] Source inspection found an executable "
                f"`mark_function` call in: {', '.join(recorded_no_association_tc_list)}. "
                "Do not add a duplicate call: the call exists, but Toffee did not record a "
                "checkpoint association for these test executions. Check, in order: "
                "(1) the call executes on every path before `return` or `pytest.skip`; "
                "(2) its test-function argument refers to the current test; "
                "(3) FG/FC/CK names exactly match the coverage definition, including case, and "
                "the checkpoint list is non-empty; "
                "(4) the fixture reports the same coverage-group objects via "
                "`set_func_coverage(request, func_coverage_group)` after `yield`. "
                "Inspect the original `STDERR` and `STDOUT` fields attached to this "
                "Check/Complete result for Toffee warnings and the corresponding runtime "
                "error."
            )
            messages.append(tc_msg)

        if no_mark_tc_list:
            messages.append(
                "[Call missing] No executable `mark_function` call was found in: "
                f"{', '.join(no_mark_tc_list)}. {simple_msg}"
            )

        if unreadable_tc_list:
            warning(f"Test cases not found in workspace {workspace}: {unreadable_tc_list}")
            messages.append(
                "[Source location unavailable] The report locations could not be matched to "
                f"readable source blocks for: {', '.join(unreadable_tc_list)}. Re-run the tests "
                "from the current workspace and verify that the report does not contain stale or "
                "external file paths."
            )

        return " ".join(messages)
    return simple_msg
