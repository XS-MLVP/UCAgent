"""Original initialization views never mislabel clipped unknown vectors as complete."""

from formal.evidence import original_inputs


def test_wide_unknown_value_keeps_all_bounded_bits(tmp_path):
    """A 512-bit source value is representable without the former silent 256-bit cut."""
    bits = "10xz" * 128
    source = tmp_path / "sample.tb.v"
    source.write_text("// initialization\ninitial begin\nrequest <= 512'b" + bits + ";\nend\n")
    view = original_inputs(source)
    assert view["initial_values"][0]["value"] == bits
    assert view["initial_values"][0]["width"] == 512
    assert not view["initial_values_truncated"]


def test_oversized_unknown_value_is_explicitly_partial(tmp_path):
    """A bounded preview must identify its range and propagate the partial flag."""
    bits = "x" * 5000
    source = tmp_path / "sample.tb.v"
    source.write_text("// initialization\ninitial begin\nrequest <= 5000'b" + bits + ";\nend\n")
    view = original_inputs(source)
    row = view["initial_values"][0]
    assert len(row["value"]) == 4096
    assert row["value_truncated"]
    assert "leading source digits" in row["value_range"]
    assert view["initial_values_truncated"]
