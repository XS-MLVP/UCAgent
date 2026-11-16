"""Regress metadata isolation and exact interface mapping with real signed inputs."""

import json

import pytest

from conftest import RTL, draft
from rtl2spec.documents import ARTIFACT_TEXT, TEMPLATE, artifact_paths, generate_port_scaffold, update_metadata
from rtl2spec.generic_evidence import generate_generic, record_generic_related_sources, validate_generic_evidence
from rtl2spec.review import prepare_review
from rtl2spec.validation import validate, validate_ports, validate_quality_report


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
    generate_port_scaffold(tmp_path, "ExampleBlock", "DefaultConfig", generic=True)
    design, report = artifact_paths(tmp_path, "ExampleBlock")
    design.write_text(document + "\n", encoding="utf-8")
    report.write_text(
        (TEMPLATE.parent / "document-quality-review-template.md").read_text(encoding="utf-8")
        .replace("[DUT]", "ExampleBlock")
        .replace("[config]", "DefaultConfig")
        .replace("[manifest 中的基线]", "fixture")
        .replace("[success / partial]", "provided")
        .replace("`[count]`", "1"),
        encoding="utf-8",
    )
    update_metadata(tmp_path, "ExampleBlock", "DefaultConfig", generic=True)
    result = validate(tmp_path, "ExampleBlock", "DefaultConfig", "draft", generic=True)
    assert result["ok"], result
    prepare_review(tmp_path, "ExampleBlock", "DefaultConfig", generic=True)
    path = tmp_path / "outputs/semantic_review.json"
    current = json.loads(path.read_text())
    guide = (TEMPLATE.parent / "source-review-guide.md").read_text(encoding="utf-8")
    example = json.loads(guide.split("```json\n", 1)[1].split("\n```", 1)[0])
    example["baseline"] = current["baseline"]
    example["behaviors"][0]["fingerprint"] = current["baseline"]["behavior_fingerprints"]["P-FORWARD"]
    path.write_text(json.dumps(example), encoding="utf-8")
    result = validate(tmp_path, "ExampleBlock", "DefaultConfig", "review", generic=True)
    assert result["ok"], result


@pytest.mark.parametrize("public_status", [False, True])
def test_public_status_table_keeps_the_existing_structure(documents, public_status):
    """Synthetic public encodings and an evidence-backed empty table keep draft structure valid."""
    design, _ = artifact_paths(documents, "Sbuffer")
    text = design.read_text(encoding="utf-8")
    if public_status:
        header = "| 状态/编码 ID | 名称或编码 | 进入条件 | 退出条件 | reset 值 / 复位行为 | 证据 |"
        table = header + "\n| --- | --- | --- | --- | --- | --- |"
        text = text.replace(table, table + "\n| `STATE-STATUS` | public response status: OK=0 | response accepted | next response | response invalid during reset | `E-RTL-01` |")
        text = text.replace("没有公开状态或协议编码，本表不适用，依据 E-RTL-01；复位电平不改变输出关系。",
                            "Synthetic structure-only example: public response status encoding; no hardware behavior is proved.")
    else:
        assert "`STATE-01`" not in text
        assert "本表不适用" in text
    design.write_text(text, encoding="utf-8")
    update_metadata(documents, "Sbuffer", "Generic", generic=True)
    result = validate(documents, "Sbuffer", "Generic", "draft", generic=True)
    assert result["ok"], result


def test_generation_resources_preserve_the_behavioral_boundary():
    """Writing rules agree without adding a runtime semantic or keyword gate."""
    template = TEMPLATE.read_text(encoding="utf-8")
    generation = (TEMPLATE.parent / "generation-guide.md").read_text(encoding="utf-8")
    review = (TEMPLATE.parent / "source-review-guide.md").read_text(encoding="utf-8")
    for text in (template, generation, review):
        for obligation in ("内部控制 FSM", "事务历史", "P/CK/COV/CASE"):
            assert obligation in text
    for guide in (generation, review):
        assert "Guide_Doc/chip_design_document_template_zh.md" in guide
    for obligation in ("公开状态", "payload 保持", "吞吐"):
        assert obligation in template
    for text in (template, review):
        for obligation in ("公开输出的实际驱动式", "完整条件及寄存延迟",
                           "内部控制退出条件与公开完成输出", "控制阶段进入/退出"):
            assert obligation in text
    assert "配置对输出的作用须有驱动路径依据" in template
    assert "确认配置分支确实影响该输出" in review
    assert "semantic_review.json" in review and "真实内部 RTL 表达" in review
    timing = next(section for section in ARTIFACT_TEXT["contract"]["required_prose_sections"]
                  if section["title"] == "时序与状态")
    assert "内部控制 FSM" in timing["description"]
    assert "仍须描述接口时序" in timing["description"]


def test_quality_report_blocks_keep_canonical_order_and_level(documents):
    """The six audit blocks cannot be hidden by reordering or demoting headings."""
    _, report = artifact_paths(documents, "Sbuffer")
    text = report.read_text(encoding="utf-8")
    swapped = text.replace("## 输入基线", "## SWAP", 1).replace(
        "## 源码复核发现", "## 输入基线", 1
    ).replace("## SWAP", "## 源码复核发现", 1)
    assert any(issue["rule"] == "QUALITY_REPORT_ORDER" for issue in validate_quality_report(swapped))
    demoted = text.replace("## 输入基线", "### 输入基线", 1)
    assert any(issue["rule"] == "QUALITY_REPORT_SECTION" for issue in validate_quality_report(demoted))
    heading_only = text.replace(
        "P-FORWARD was compared with the captured assignment and its E-RTL-01 range.",
        "### 复核条目",
        1,
    )
    assert any(
        issue["rule"] == "QUALITY_REPORT_CONTENT"
        and "源码复核发现" in issue["error"]
        for issue in validate_quality_report(heading_only)
    )


@pytest.mark.parametrize("body,valid", [
    ("| Item | Finding |\n| --- | --- |", False),
    ("| Item | Finding |\n| --- | --- |\n| | |", False),
    ("<!-- findings still pending -->", False),
    ("### Findings", False),
    ("```text\nExample only\n```", False),
    ("No simulation was run; this report only checks captured evidence.", True),
    ("| Item | Finding |\n| --- | --- |\n| Simulation | Unrun |", True),
])
def test_quality_report_requires_visible_findings(body, valid):
    """Each audit section needs prose or populated data, rather than an empty table."""
    contract = ARTIFACT_TEXT["quality_report"]
    text = "\n# " + contract["title"] + "\n"
    text += "".join("\n## " + section["title"] + "\n\n" + body + "\n"
                    for section in contract["sections"])
    errors = validate_quality_report(text)
    assert (not errors) == valid, errors
    if not valid:
        assert len([issue for issue in errors if issue["rule"] == "QUALITY_REPORT_CONTENT"]) == 6


@pytest.mark.parametrize("extra,before", [("# Another report", False), ("## Preamble", True)])
def test_quality_report_has_one_leading_title(extra, before):
    """All six report sections must belong to a single canonical report title."""
    contract = ARTIFACT_TEXT["quality_report"]
    text = "\n# " + contract["title"] + "\n"
    text += "".join("\n## " + section["title"] + "\n\nObserved finding.\n"
                    for section in contract["sections"])
    text = "\n" + extra + "\n" + text if before else text + "\n" + extra + "\n"
    assert any(issue["rule"] == "QUALITY_REPORT_TITLE" for issue in validate_quality_report(text))
