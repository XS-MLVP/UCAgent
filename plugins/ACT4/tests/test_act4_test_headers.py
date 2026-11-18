"""Exercise the shared native test header contract and its checker consumers."""

from pathlib import Path

import pytest

from ucagent_act4.test_headers import inspect_test_header
from ucagent_act4.checkers.act4_test_asset_checker import ACT4TestAssetChecker


def source(body, prefix="#", newline="\n"):
    """Wrap exact YAML in a native commented header without changing its indentation."""
    return newline.join([f"{prefix} START_TEST_CONFIG", *[f"{prefix} {line}" for line in body.splitlines()],
                         f"{prefix} END_TEST_CONFIG", ".text", "RVTEST_BEGIN", ""])


@pytest.mark.parametrize("prefix", ["#", "//", "*"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_native_nested_header_preserves_selection_constraints(prefix, newline):
    """Preserve OR extension groups and parameter constraints instead of flattening YAML."""
    text = source("REQUIRED_EXTENSIONS:\n  - I\n  - [Sm, U]\nFORBIDDEN_EXTENSIONS: [S]\n"
                  "MARCH: rv${XLEN}i_zicsr\nMIN_HARTS: 2\nNEEDS_SIGNATURE: true\n"
                  "params:\n  MXLEN: 64\n  VLEN: '>=128'\n  MISALIGNED_LDST: false", prefix, newline)
    result = inspect_test_header(text, "Example.S")
    assert not result["findings"]
    assert result["metadata"]["params"] == {"MXLEN": 64, "VLEN": ">=128", "MISALIGNED_LDST": False}
    assert result["metadata"]["REQUIRED_EXTENSIONS"] == ["I", ["Sm", "U"]]
    findings = []
    ACT4TestAssetChecker()._check_test_config(text, Path("Example.S"), findings)
    assert not findings


@pytest.mark.parametrize("body,code", [
    ("MARCH: rv64i", "test_config_extensions"),
    ("REQUIRED_EXTENSIONS: []\nMARCH: rv64i", "test_config_extensions"),
    ("REQUIRED_EXTENSIONS: [I, []]\nMARCH: rv64i", "test_config_extensions"),
    ("REQUIRED_EXTENSIONS: [I, [[S]]]\nMARCH: rv64i", "test_config_extensions"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nFORBIDDEN_EXTENSIONS: [[S]]", "test_config_extensions"),
    ("REQUIRED_EXTENSIONS: [I]", "test_config_march"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: RV64I", "test_config_march"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nMIN_HARTS: false", "test_config_harts"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nMIN_HARTS: 0", "test_config_harts"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nNEEDS_SIGNATURE: 'false'", "test_config_signature"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nparams:\n  VLEN: []", "test_config_params"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nparams: []", "test_config_params"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nMXLEN: 64", "test_config_field"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nMARCH: rv32i", "test_config_parse"),
    ("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i\nparams:\n  MXLEN: 64\n  MXLEN: 32", "test_config_parse"),
    ("REQUIRED_EXTENSIONS: [I", "test_config_parse"),
    ("[I]", "test_config_schema"),
    ("", "test_config_schema"),
    ("&cycle {REQUIRED_EXTENSIONS: [I], MARCH: rv64i, params: *cycle}", "test_config_params"),
])
def test_invalid_headers_return_actionable_diagnostics(body, code):
    """Reject malformed constraints, duplicate keys and unsafe values with file and repair guidance."""
    result = inspect_test_header(source(body), "tests/Example/Example-00.S")
    assert code in {finding["check"] for finding in result["findings"]}
    assert result["metadata"] == {}
    assert all(finding["file"] == result["file"] and finding["line"] > 0 and finding["next_action"]
               for finding in result["findings"])


@pytest.mark.parametrize("mutation,code", [
    ("missing", "test_config_markers"), ("duplicate", "test_config_markers"),
    ("reversed", "test_config_order"), ("late", "test_config_order"),
    ("uncommented", "test_config_comment"),
])
def test_test_header_block_boundaries(mutation, code):
    """Require one ordered commented configuration before instructions, not a silent skip."""
    text = source("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64i")
    if mutation == "missing":
        text = "RVTEST_BEGIN\n"
    elif mutation == "duplicate":
        text += text
    elif mutation == "reversed":
        text = text.replace("START_TEST_CONFIG", "temporary").replace("END_TEST_CONFIG", "START_TEST_CONFIG").replace("temporary", "END_TEST_CONFIG")
    elif mutation == "late":
        text = "addi a0, a0, 1\n" + text
    else:
        text = text.replace("# MARCH:", "MARCH:")
    assert code in {finding["check"] for finding in inspect_test_header(text, "Example.S")["findings"]}


def test_header_reports_all_invalid_fields_in_one_pass():
    """Expose independent field defects together rather than forcing repeated review runs."""
    result = inspect_test_header(source("MIN_HARTS: 0\nparams: []\nUNKNOWN: 3"), "Example.S")
    assert {finding.get("field") for finding in result["findings"]} == {
        "MIN_HARTS", "params", "UNKNOWN", "REQUIRED_EXTENSIONS", "MARCH"}


def test_cpp_description_before_header_is_not_assembly():
    """Permit recipient-facing documentation and licenses before the native YAML block."""
    text = "/*\nProgram intent and provenance.\n*/\n// Additional description\n"
    text += source("REQUIRED_EXTENSIONS: [I]\nMARCH: rv64g\nNEEDS_SIGNATURE: false")
    assert not inspect_test_header(text, "Example.S")["findings"]
