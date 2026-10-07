"""Cover the case-normalization skill against synthetic and real corpus products."""

import importlib.util
from pathlib import Path
import tempfile

import pytest

from bug_review.core.claims import report_claim_blocks
from bug_review.core.inventory import build_inventory, parse_summary

_SCRIPT = (Path(__file__).resolve().parents[1]
           / "src/bug_review/skills/case-normalization/scripts/normalize_case.py")
_spec = importlib.util.spec_from_file_location("normalize_case", _SCRIPT)
normalize_case = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(normalize_case)

CORPUS = Path("/Users/fy/work/XSV/UCSwarm/third-party/case")


def make_module(root: Path, name: str, files: dict[str, str]) -> Path:
    """Create one minimal module with one collected test and the given documents."""
    base = root / name
    tests = base / "unity_test" / "tests"
    tests.mkdir(parents=True)
    (tests / f"test_{name.lower()}.py").write_text(
        "def test_smoke():\n    assert True\n", encoding="utf-8")
    for relative, content in files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return base


def run_norm(root: Path, args: list[str]) -> None:
    """Invoke the normalization script in-process against one case root."""
    normalize_case.main(["--case-root", str(root), *args])


def plugin_blocks(module_dir: Path) -> list[dict]:
    """Read claim blocks through the plugin parser via a run-layout shim."""
    shim = Path(tempfile.mkdtemp(prefix="norm_test_shim_"))
    run = shim / "verification_review" / "run"
    run.mkdir(parents=True)
    (run / "unity_test").symlink_to(module_dir / "unity_test")
    return report_claim_blocks(shim, module_dir.name)


def plugin_inventory(module_dir: Path) -> dict:
    """Build one inventory through the plugin builder via a run-layout shim."""
    shim = Path(tempfile.mkdtemp(prefix="norm_test_inv_"))
    run = shim / "verification_review" / "run"
    run.mkdir(parents=True)
    (run / "unity_test").symlink_to(module_dir / "unity_test")
    inventory, _ = build_inventory(shim, module_dir.name)
    return inventory


BULLET_DOC = """# demo 动态 Bug 分析

## 场景

- <CK-RET-ONE> 返回值错误：写回 1 期望 0；Bug 置信度 98% <BG-RET-VALUE-98>
  - 触发 Bug 的测试用例：
    - <TC-unity_test/tests/test_demo_core.py::test_ret_zero> 复现失败
  - 备注：与静态分析一致
- 普通 bullet，没有 Bug 声明
"""


def test_bullet_product_converts_and_builds_inventory(tmp_path):
    """Old bullet-style claims become canonical blocks, TCs and a valid summary."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": BULLET_DOC,
        "unity_test/tests/test_demo_core.py": "def test_ret_zero():\n    assert False\n",
    })
    run_norm(tmp_path, ["--module", "demo"])
    lines = (module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8")
    assert lines.count("###### ") == 1
    assert "<BG-RET-VALUE-98> (98%)" in lines or "(98%) <BG-RET-VALUE-98>" in lines
    assert "<CK-RET-ONE> 返回值错误" in lines  # original bullet text kept as block body
    blocks = plugin_blocks(module)
    assert len(blocks) == 1
    assert blocks[0]["source_label"] == "BG-RET-VALUE-98"
    assert blocks[0]["tc_labels"] == ["tests/test_demo_core.py::test_ret_zero"]
    summary = parse_summary(module / "unity_test/demo_bug_summary.md")
    assert [row["bug_id"] for row in summary] == ["RET-VALUE"]
    assert summary[0]["reported_confidence"] == 0.98
    inventory = plugin_inventory(module)
    assert [bug["bug_id"] for bug in inventory["bugs"]] == ["RET-VALUE"]
    assert inventory["bugs"][0]["aggregate_tests"] == [
        "tests/test_demo_core.py::test_ret_zero"]


def test_bare_tags_and_short_tc_labels(tmp_path):
    """Standalone BG lines become headings; short TC labels expand when the file exists."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": (
            "<FG-ACT>\n"
            "\n"
            "<CK-REQ-RISE>\n"
            "\n"
            "<BG-ACK-TWO-CYCLE-98>\n"
            "ACK 在下一拍仍未置高：复现稳定失败。\n"
            "\n"
            "<TC-test_demo_link.py::test_ack_next>\n"
            "严格检查一拍延迟，当前稳定 Fail。\n"
            "\n"
            "<TC-tests/test_demo_link.py::test_ack_prefixed>\n"
            "已有 tests/ 前缀的引用同样补全。\n"
            "\n"
            "<TC-test_missing_case.py::test_absent>\n"
            "缺失文件的引用保持原样。\n"
        ),
        "unity_test/tests/test_demo_link.py": "def test_ack_next():\n    assert False\n",
    })
    run_norm(tmp_path, ["--module", "demo"])
    text = (module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8")
    assert "###### ACK 在下一拍仍未置高：复现稳定失败 (98%) <BG-ACK-TWO-CYCLE-98>" in text
    assert "<TC-unity_test/tests/test_demo_link.py::test_ack_next>" in text
    assert "<TC-unity_test/tests/test_demo_link.py::test_ack_prefixed>" in text
    assert "<TC-test_missing_case.py::test_absent>" in text  # missing file: unchanged
    blocks = plugin_blocks(module)
    assert [block["source_label"] for block in blocks] == ["BG-ACK-TWO-CYCLE-98"]
    assert blocks[0]["tc_labels"] == [
        "test_missing_case.py::test_absent", "tests/test_demo_link.py::test_ack_next",
        "tests/test_demo_link.py::test_ack_prefixed"]


def test_h1_h5_bg_heading_demoted(tmp_path):
    """A BG heading above level six is demoted so the plugin parser accepts it."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": (
            "# demo 动态 Bug 分析\n"
            "\n"
            "##### 缩放错误场景 (90%) <BG-SCALE-WRAP-90>\n"
            "正文描述。\n"
        ),
    })
    run_norm(tmp_path, ["--module", "demo"])
    text = (module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8")
    assert "###### 缩放错误场景 (90%) <BG-SCALE-WRAP-90>" in text
    assert plugin_blocks(module)[0]["source_label"] == "BG-SCALE-WRAP-90"


def test_multi_tag_bullet_emits_one_heading_per_tag(tmp_path):
    """One bullet with several BG tags yields one heading per tag plus an anomaly."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": (
            "- 场景描述 <BG-ONE-90> 以及 <BG-TWO-80>\n"
            "  - <TC-unity_test/tests/test_demo_core.py::test_multi> 复现\n"
        ),
    })
    run_norm(tmp_path, ["--module", "demo"])
    text = (module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8")
    assert text.count("###### ") == 2
    assert "<BG-ONE-90>" in text and "<BG-TWO-80>" in text
    assert plugin_blocks(module)  # both tags parse as separate claim blocks


def test_canonical_product_is_untouched_and_summary_validated(tmp_path):
    """A product already in canonical shape stays byte-identical across runs."""
    analysis = ("# demo 动态 Bug 分析\n"
                "\n"
                "###### 提交永不置位 (95%) <BG-COMMIT-NEVER-95>\n"
                "\n"
                "正文。\n"
                "\n"
                "<TC-unity_test/tests/test_demo_core.py::test_commit>\n"
                "复现。\n")
    summary = ("# demo Bug Summary\n"
               "\n"
               "Total Bugs: 1\n"
               "\n"
               "| Name | Severity | Alias | CK | Analysis | Locations | Confidence | Ref |\n"
               "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
               "| COMMIT-NEVER | high |  |  | 摘要 |  | 0.95 "
               "| [unity_test/demo_bug_analysis.md:3-7](demo_bug_analysis.md#L3-L7) |\n")
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": analysis,
        "unity_test/demo_bug_summary.md": summary,
    })
    run_norm(tmp_path, ["--module", "demo"])
    assert (module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8") == analysis
    assert (module / "unity_test/demo_bug_summary.md").read_text(encoding="utf-8") == summary


def test_second_run_is_a_no_op(tmp_path):
    """Re-normalizing a converted product rewrites nothing."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": BULLET_DOC,
    })
    run_norm(tmp_path, ["--module", "demo"])
    converted = (module / "unity_test/demo_bug_analysis.md").read_bytes()
    summary = (module / "unity_test/demo_bug_summary.md").read_bytes()
    run_norm(tmp_path, ["--module", "demo"])
    assert (module / "unity_test/demo_bug_analysis.md").read_bytes() == converted
    assert (module / "unity_test/demo_bug_summary.md").read_bytes() == summary


def test_summary_identity_drift_regenerates(tmp_path):
    """An existing summary naming unknown Bugs is regenerated from the analysis."""
    analysis = ("###### 悬挂写丢失 (90%) <BG-HANG-LOSS-90>\n"
                "\n"
                "正文。\n"
                "\n"
                "<TC-unity_test/tests/test_demo_core.py::test_hang>\n")
    summary = ("# demo Bug Summary\n"
               "\n"
               "Total Bugs: 1\n"
               "\n"
               "| Name | Severity | Alias | CK | Analysis | Locations | Confidence | Ref |\n"
               "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
               "| WRONG-NAME | high |  |  | 摘要 |  | 0.9 | unity_test/demo_bug_analysis.md:1-5 |\n")
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": analysis,
        "unity_test/demo_bug_summary.md": summary,
    })
    run_norm(tmp_path, ["--module", "demo"])
    rows = parse_summary(module / "unity_test/demo_bug_summary.md")
    assert [row["bug_id"] for row in rows] == ["HANG-LOSS"]


def test_missing_documents_become_empty_templates(tmp_path):
    """A module without report documents receives explicit zero-claim templates."""
    module = make_module(tmp_path, "demo", {})
    run_norm(tmp_path, ["--module", "demo"])
    analysis = (module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8")
    summary = (module / "unity_test/demo_bug_summary.md").read_text(encoding="utf-8")
    assert "demo" in analysis and "0 个原始 Bug 声明" in analysis
    assert "Total Bugs: 0" in summary
    inventory = plugin_inventory(module)
    assert inventory["bugs"] == []
    run_norm(tmp_path, ["--module", "demo"])  # templates are never overwritten
    assert "0 个原始 Bug 声明" in (
        module / "unity_test/demo_bug_analysis.md").read_text(encoding="utf-8")


def test_no_tests_module_skipped(tmp_path):
    """Modules without collectable tests are skipped entirely."""
    base = tmp_path / "demo"
    (base / "unity_test" / "tests").mkdir(parents=True)
    (base / "unity_test" / "tests" / "helper.py").write_text("value = 1\n", encoding="utf-8")
    run_norm(tmp_path, ["--all"])
    assert not (base / "unity_test" / "demo_bug_analysis.md").exists()


def test_duplicate_agents_twins(tmp_path):
    """Byte-identical AGENTS.md twins normalize once, the richer one."""
    files = {"unity_test/demo_bug_analysis.md": BULLET_DOC}
    make_module(tmp_path, "twin_a", files)
    make_module(tmp_path, "twin_b", files)
    (tmp_path / "twin_a" / "AGENTS.md").write_text("same\n", encoding="utf-8")
    (tmp_path / "twin_b" / "AGENTS.md").write_text("same\n", encoding="utf-8")
    (tmp_path / "twin_b" / "extra.md").write_text("richer\n", encoding="utf-8")
    run_norm(tmp_path, ["--all"])
    assert plugin_blocks(tmp_path / "twin_b")  # richer twin converted
    assert not (tmp_path / "twin_a" / "unity_test" / "demo_bug_summary.md").exists()


def test_in_place_mode_backs_up_original(tmp_path):
    """In-place rewrites back up the original bytes once and keep them stable."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": BULLET_DOC,
    })
    original = (module / "unity_test/demo_bug_analysis.md").read_bytes()
    backup = tmp_path / "backups"
    run_norm(tmp_path, ["--module", "demo", "--backup-dir", str(backup)])
    saved = backup / "demo/unity_test/demo_bug_analysis.md"
    assert saved.read_bytes() == original
    assert (module / "unity_test/demo_bug_analysis.md").read_bytes() != original
    run_norm(tmp_path, ["--module", "demo", "--backup-dir", str(backup)])
    assert saved.read_bytes() == original


def test_copy_mode_excludes_artifacts_and_keeps_source(tmp_path):
    """Output-dir mode normalizes a pruned copy while the corpus stays untouched."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": BULLET_DOC,
    })
    (module / "unity_test/tests/__pycache__").mkdir()
    (module / "unity_test/tests/__pycache__/x.pyc").write_bytes(b"x")
    (module / "unity_test/tests/toffee_tmp_old").mkdir()
    (module / "unity_test/tests/toffee_tmp_old/wave.fst").write_bytes(b"w")
    (module / ".coverage-report-1").write_text("data\n", encoding="utf-8")
    out = tmp_path / "normalized"
    run_norm(tmp_path, ["--module", "demo", "--output-dir", str(out)])
    copy = out / "demo"
    assert (copy / "unity_test/demo_bug_summary.md").is_file()
    assert not (copy / "unity_test/tests/__pycache__").exists()
    assert not (copy / "unity_test/tests/toffee_tmp_old").exists()
    assert not (copy / ".coverage-report-1").exists()
    assert (module / "unity_test/demo_bug_summary.md").exists() is False
    assert plugin_blocks(copy)  # the copy itself is canonical


def test_dry_run_writes_nothing(tmp_path):
    """Dry run reports the plan without touching the corpus."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": BULLET_DOC,
    })
    original = (module / "unity_test/demo_bug_analysis.md").read_bytes()
    run_norm(tmp_path, ["--module", "demo", "--dry-run"])
    assert (module / "unity_test/demo_bug_analysis.md").read_bytes() == original
    assert not (module / "unity_test/demo_bug_summary.md").exists()


def test_rename_prefix_drift(tmp_path):
    """A drifted report name is renamed to the canonical module name."""
    module = make_module(tmp_path, "demo", {
        "unity_test/other_demo_bug_analysis.md": BULLET_DOC,
    })
    run_norm(tmp_path, ["--module", "demo"])
    assert (module / "unity_test/demo_bug_analysis.md").is_file()
    assert not (module / "unity_test/other_demo_bug_analysis.md").is_file()
    assert plugin_blocks(module)


def test_mirror_parser_matches_plugin(tmp_path):
    """The script's local claim reader agrees with the plugin parser."""
    module = make_module(tmp_path, "demo", {
        "unity_test/demo_bug_analysis.md": BULLET_DOC,
    })
    run_norm(tmp_path, ["--module", "demo"])
    lines = (module / "unity_test/demo_bug_analysis.md").read_text(
        encoding="utf-8").splitlines()
    local = {f"BG-{block['tag']}" for block in normalize_case.parse_claim_blocks(lines)}
    remote = {block["source_label"] for block in plugin_blocks(module)}
    assert local == remote


@pytest.mark.skipif(not CORPUS.is_dir(), reason="third-party case corpus not present")
def test_real_corpus_smoke(tmp_path):
    """Copy-mode smoke over one bullet, one canonical and one empty corpus module."""
    out = tmp_path / "corpus"
    for name in ("bosc_AtomicsUnit", "bosc_Rob", "bosc_ExuBlock_2"):
        run_norm(CORPUS, ["--module", name, "--output-dir", str(out)])
    converted = plugin_inventory(out / "bosc_AtomicsUnit")
    assert len(converted["bugs"]) > 0
    canonical = plugin_inventory(out / "bosc_Rob")
    assert len(canonical["bugs"]) > 0
    source_analysis = (CORPUS / "bosc_Rob/unity_test/bosc_Rob_bug_analysis.md").read_bytes()
    assert (out / "bosc_Rob/unity_test/bosc_Rob_bug_analysis.md").read_bytes() == source_analysis
    empty = plugin_inventory(out / "bosc_ExuBlock_2")
    assert empty["bugs"] == []
