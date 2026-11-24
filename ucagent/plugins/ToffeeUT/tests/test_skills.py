"""Keep the full method collection discoverable, self-contained and optional."""

from pathlib import Path
import glob
import re
import tomllib

import pytest
import yaml

from ucagent.core.tools.skill import _scan_skills
from ucagent.util.functions import copytree_incremental


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/toffee_ut"
SKILLS = PACKAGE / "skills"
METHODS = {
    "requirements-boundary", "observation-precision", "behavior-equivalence",
    "traceability-and-implementation", "closure-and-residuals", "package-layout",
    "legal-stimulus", "independent-oracle", "checker-and-runtime", "triage-and-evidence",
}
NAVIGATION = {"verification-completeness", "rtl-verification-soundness", "ucv4xs-workflow"}
PENDING = {
    "dependency-upgrade-and-capability-audit", "fixture-consolidation",
    "framework-capability-selection", "pin-schema-and-suite-migration",
}


@pytest.mark.parametrize("enabled", [None, ["ucv4xs-workflow"]])
def test_native_copy_and_discovery_keep_references_without_registering_pending(tmp_path, enabled):
    """The existing copier includes nested resources, while only SKILL.md defines entries."""
    destination = tmp_path / ".ucagent/skills/ext/toffee-ut"
    copied = copytree_incremental(str(SKILLS), str(destination), enable_skill_list=enabled or [])
    expected = set(enabled) if enabled else METHODS | NAVIGATION
    assert set(copied) == expected
    entries = _scan_skills(str(tmp_path))
    assert {entry["name"] for entry in entries} == {f"ext/toffee-ut/{name}" for name in expected}
    assert all(not entry["script"] for entry in entries)
    for name in expected:
        for source in (SKILLS / name).rglob("*"):
            if source.is_file():
                assert (destination / source.relative_to(SKILLS)).read_bytes() == source.read_bytes()
    pending = destination / "ucv4xs-workflow/references/pending"
    assert {path.stem for path in pending.glob("*.md")} == PENDING | {"README"}
    assert not list(pending.rglob("SKILL.md"))
    for path in pending.glob("*.md"):
        if path.stem in PENDING:
            metadata = yaml.safe_load(path.read_text().split("---", 2)[1])
            assert metadata["status"] == "pending"


def test_each_method_and_reference_has_provenance_and_packaging_coverage():
    """All retained inputs have bounded source fingerprints and ship as editable resources."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["license"] == "Apache-2.0 AND MPL-2.0"
    notice = SKILLS / "ucv4xs-workflow/references/SOURCES.md"
    rows = re.findall(r"^\| (skills/[^|]+) \| ([^|]+) \| ([0-9a-f]{64}) \|$", notice.read_text(), re.M)
    assert len(rows) == len({row[0] for row in rows}) == 20
    retained = {source: (target, digest) for source, target, digest in rows}
    assets = {path for path in SKILLS.rglob("*") if path.is_file()}
    assert {path.parent.name for path in SKILLS.rglob("SKILL.md")} == METHODS | NAVIGATION
    for source, (target, digest) in retained.items():
        path = (SKILLS / target).resolve()
        assert path.is_relative_to(PACKAGE) and path.is_file()
        text = path.read_text()
        assert "SPDX-License-Identifier: MPL-2.0" in text
        if path.name == "SKILL.md":
            frontmatter = yaml.safe_load(text.split("---", 2)[1])["metadata"]
            assert frontmatter["source"] == f"ucv4xs/{source}"
            assert frontmatter["source_sha256"] == digest
        elif path.stem in PENDING:
            frontmatter = yaml.safe_load(text.split("---", 2)[1])
            assert frontmatter["source"] == f"ucv4xs/{source}"
            assert frontmatter["source_sha256"] == digest
    assert assets == {SKILLS / target for target, _ in retained.values() if not target.startswith("../")} | {
        notice, SKILLS / "ucv4xs-workflow/references/LICENSE-MPL-2.0.txt",
    }
    packaged = set()
    for pattern in metadata["tool"]["setuptools"]["package-data"]["toffee_ut"]:
        packaged.update(Path(path) for path in glob.glob(str(PACKAGE / pattern), recursive=True))
    assert assets <= packaged
    assert PACKAGE / "Guide_Doc/ut-methods.md" in packaged
    license_file = SKILLS / "ucv4xs-workflow/references/LICENSE-MPL-2.0.txt"
    assert str(license_file.relative_to(ROOT)) in metadata["project"]["license-files"]
    assert license_file.read_text().startswith("Mozilla Public License Version 2.0\n")
    assert "Exhibit B" in license_file.read_text()


def test_method_links_are_local_and_canonical_without_external_checkout():
    """Cross-method links resolve within the package; historical paths remain explicit task data."""
    for path in SKILLS.rglob("*.md"):
        for target in re.findall(r"\[[^\]\n]+\]\(([^)]+)\)", path.read_text()):
            if target.startswith(("https://", "http://", "#")):
                continue
            linked = (path.parent / target.split("#", 1)[0]).resolve()
            assert linked.is_relative_to(PACKAGE) and linked.is_file(), (path, target)
    card = (SKILLS / "rtl-verification-soundness/CARD.md").read_text()
    assert set(re.findall(r"\| (P\d{2}) ", card)) == {f"P{index:02d}" for index in range(1, 13)}
