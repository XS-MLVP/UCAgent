"""Regress metadata isolation and exact interface mapping with real signed inputs."""

import json

import pytest

from conftest import RTL, draft
from rtl2spec.documents import TEMPLATE, artifact_paths, generate_port_scaffold, update_metadata
from rtl2spec.generic_evidence import generate_generic, record_generic_related_sources, validate_generic_evidence
from rtl2spec.review import prepare_review
from rtl2spec.validation import validate, validate_ports


@pytest.fixture
def documents(tmp_path):
    """Capture independent top/helper digests before drafting a complete document."""
    source = tmp_path / "inputs/Sbuffer"
    source.mkdir(parents=True)
    (source / "top.sv").write_text(RTL)
    (source / "helper.sv").write_text("module helper(input wire clk); endmodule\n")
    generate_generic(tmp_path, "Sbuffer", "Generic")
    record_generic_related_sources(tmp_path, "Sbuffer", "Generic", ["helper.sv"])
    draft(tmp_path)
    return tmp_path


def test_metadata_preserves_other_hashes_and_three_column_tables(documents):
    """Metadata updates one value cell and each registered source's own digest only."""
    design, report = artifact_paths(documents, "Sbuffer")
    manifest, _ = validate_generic_evidence(documents, "Sbuffer", "Generic")
    source = manifest["related_sources"][0]
    foreign = "a" * 64
    original = design.read_text()
    original += f"\nUnrelated source SHA-256 `{foreign}`.\n"
    original += f"\n| ID | Type | Path | Digest | Use |\n| --- | --- | --- | --- | --- |\n| `{source['evidence_id']}` | Related source | `{source['path']}:1` | SHA-256 `{foreign}` / Generic | helper |\n"
    design.write_text(original)
    report.write_text("\n# Review\n\n| Item | Status | Value |\n| --- | --- | --- |\n| 生成日期 | Pass | 2000-01-01 |\n| 适用配置 | Pass | `Wrong` |\n")
    update_metadata(documents, "Sbuffer", "Generic", generic=True)
    assert f"Unrelated source SHA-256 `{foreign}`." in design.read_text()
    assert f"SHA-256 `{source['sha256']}` / Generic" in design.read_text()
    assert "| 生成日期 | Pass | " in report.read_text()
    assert "| 适用配置 | Pass | `Generic` |" in report.read_text()
    before = [p.read_bytes() for p in (design, report)]
    update_metadata(documents, "Sbuffer", "Generic", generic=True)
    assert [p.read_bytes() for p in (design, report)] == before


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "direction", "width", "fenced"])
def test_exact_port_contract_rejects_invalid_mappings(documents, mutation):
    """Missing, duplicate, invented and incorrectly typed ports cannot pass."""
    design, _ = artifact_paths(documents, "Sbuffer")
    text = design.read_text()
    _, ports = validate_generic_evidence(documents, "Sbuffer", "Generic")
    row = next(line for line in text.splitlines() if line.startswith('| `IO-INPUT-01`'))
    replacement = {
        "missing": "", "duplicate": row + "\n" + row.replace("IO-INPUT-01", "IO-EXTRA"),
        "extra": row.replace("`io_data`", "`invented`"),
        "direction": row.replace("I/8", "O/8"), "width": row.replace("I/8", "I/9"),
        "fenced": "\n```markdown\n\n" + row + "\n```\n",
    }[mutation]
    assert validate_ports(text.replace(row, replacement), ports)


def test_logical_clock_alias_is_not_an_rtl_port(documents):
    """Only the exact interface column defines mappings; prose names stay logical."""
    design, _ = artifact_paths(documents, "Sbuffer")
    _, ports = validate_generic_evidence(documents, "Sbuffer", "Generic")
    text = design.read_text().replace("`clock`", "`clk`").replace("`reset`", "`rst_n`")
    for port in ports:
        port["name"] = {"clock": "clk", "reset": "rst_n"}.get(port["name"], port["name"])
    text += "\nLogical `clock` and `reset` denote abstract controls.\n"
    assert validate_ports(text, ports) == []


def test_port_scaffold_contains_exact_facts(documents):
    """The generated table preserves ordering and exact widths for model annotation."""
    path = generate_port_scaffold(documents, "Sbuffer", "Generic", generic=True)
    text = path.read_text()
    _, ports = validate_generic_evidence(documents, "Sbuffer", "Generic")
    for port in ports:
        assert f"`{port['name']}`" in text
        assert f"`IO-{port['index']:03d}`" in text
    assert "`I/8`" in text and "`O/8`" in text
    assert "inputs/Sbuffer/top.sv:5" in text


def test_runtime_guide_example_satisfies_the_draft_contract(tmp_path):
    """Complete teaching artifacts must pass draft and review against the published RTL."""
    guide = (TEMPLATE.parent / "generation-guide.md").read_text(encoding="utf-8")
    rtl = guide.split("```verilog\n", 1)[1].split("\n```", 1)[0]
    document = guide.split("````markdown\n", 1)[1].split("\n````", 1)[0]
    source = tmp_path / "inputs/ExampleBlock"
    source.mkdir(parents=True)
    (source / "ExampleBlock.sv").write_text(rtl + "\n", encoding="utf-8")
    generate_generic(tmp_path, "ExampleBlock", "DefaultConfig")
    design, report = artifact_paths(tmp_path, "ExampleBlock")
    design.write_text(document + "\n", encoding="utf-8")
    report.write_text("\n# Review\n\nTeaching example only. Simulation and formal verification are Unrun.\n")
    update_metadata(tmp_path, "ExampleBlock", "DefaultConfig", generic=True)
    result = validate(tmp_path, "ExampleBlock", "DefaultConfig", "draft", generic=True)
    assert result["ok"], result
    prepare_review(tmp_path, "ExampleBlock", "DefaultConfig", generic=True)
    path = tmp_path / "outputs/semantic_review.json"
    current = json.loads(path.read_text())
    guide = (TEMPLATE.parent / "source-review-guide.md").read_text(encoding="utf-8")
    example = json.loads(guide.split("```json\n", 1)[1].split("\n```", 1)[0])
    example["baseline"] = current["baseline"]
    path.write_text(json.dumps(example), encoding="utf-8")
    result = validate(tmp_path, "ExampleBlock", "DefaultConfig", "review", generic=True)
    assert result["ok"], result
