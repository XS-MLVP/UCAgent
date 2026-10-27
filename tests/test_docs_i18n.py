"""Validate translated documentation and the rendered bilingual website."""

from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    """Collect rendered language, links, headings, and searchable content."""

    def __init__(self, path):
        """Parse a built page without additional HTML dependencies."""
        super().__init__()
        self.language = None
        self.links = []
        self.alternates = {}
        self.language_controls = {}
        self.refresh = None
        self.noscript_refresh = None
        self.noscript_depth = 0
        self.redirect_script = ""
        self.in_redirect_script = False
        self.ids = set()
        self.article_links = []
        self.article_depth = 0
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        """Capture navigation targets and identifiers used by Markdown links."""
        attrs = dict(attrs)
        if tag == "html":
            self.language = attrs.get("lang")
        if tag == "noscript":
            self.noscript_depth += 1
        if tag == "script" and attrs.get("id") == "uc-language-redirect":
            self.in_redirect_script = True
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            if self.noscript_depth:
                self.noscript_refresh = attrs.get("content")
            else:
                self.refresh = attrs.get("content")
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "article":
            self.article_depth += 1
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
            if self.article_depth:
                self.article_links.append(attrs["href"])
            if "uc-language-switch__link" in attrs.get("class", "").split():
                self.alternates[attrs.get("hreflang")] = attrs["href"]
                self.language_controls[attrs.get("hreflang")] = attrs
        if tag == "img" and attrs.get("src"):
            self.links.append(attrs["src"])

    def handle_endtag(self, tag):
        """Track article scope independently of surrounding site navigation."""
        if tag == "article":
            self.article_depth -= 1
        if tag == "noscript":
            self.noscript_depth -= 1
        if tag == "script":
            self.in_redirect_script = False

    def handle_data(self, data):
        """Retain the built redirect script for execution against browser locales."""
        if self.in_redirect_script:
            self.redirect_script += data


@unittest.skipUnless(importlib.util.find_spec("mkdocs"), "Install docs/requirements-docs.txt")
class DocumentationLanguagesTest(unittest.TestCase):
    """Exercise language switching, assets, anchors, redirects, and search."""

    @classmethod
    def setUpClass(cls):
        """Reuse a CI build or build the actual site in a temporary directory."""
        from mkdocs.config import load_config

        cls.config = load_config(str(ROOT / "mkdocs.yml"))
        configured_site = os.environ.get("UCAGENT_DOCS_SITE_DIR")
        if configured_site:
            cls.site = Path(configured_site).resolve()
        else:
            temporary = tempfile.TemporaryDirectory(prefix="ucagent-docs-test-")
            cls.addClassCleanup(temporary.cleanup)
            cls.site = Path(temporary.name)
            result = subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "-f", "mkdocs.yml", "--strict", "--site-dir", str(cls.site)],
                cwd=ROOT, capture_output=True, text=True, timeout=180,
            )
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        cls.sources = sorted(
            path for path in (ROOT / "docs/content").rglob("*.md")
            if not path.name.endswith(".en.md")
        )
        cls.pages = {}
        for source in [ROOT / "docs/index.md", *cls.sources]:
            relative = source.relative_to(ROOT / "docs")
            output = relative.with_suffix("") / "index.html" if relative.name != "index.md" else Path("index.html")
            for locale, prefix in (("zh", Path()), ("en", Path("en"))):
                target = prefix / output
                if not (cls.site / target).is_file():
                    raise AssertionError(f"Missing {locale} page: {target}")
                cls.pages[target.as_posix()] = Page(cls.site / target)

    def resolve(self, source, target):
        """Resolve a built relative URL under the GitHub Pages project prefix."""
        parsed = urlsplit(urljoin("https://xs-mlvp.github.io/UCAgent/" + source, target))
        if parsed.netloc != "xs-mlvp.github.io" or not parsed.path.startswith("/UCAgent/"):
            return None, None
        path = unquote(parsed.path.removeprefix("/UCAgent/"))
        if path.endswith("/") or not path:
            path += "index.html"
        return path, unquote(parsed.fragment)

    def test_every_document_has_an_english_translation(self):
        """Prevent silent Chinese fallback when a new documentation page is added."""
        for source in self.sources:
            with self.subTest(source=source.relative_to(ROOT)):
                translation = source.with_suffix(".en.md")
                self.assertTrue(translation.is_file(), str(translation))
                self.assertNotEqual(source.read_text(), translation.read_text())

    def test_language_switch_preserves_the_current_page(self):
        """Every page must link to both corresponding locales, including homepages."""
        for path, page in self.pages.items():
            with self.subTest(page=path):
                english = path.startswith("en/")
                self.assertEqual(page.language, "en" if english else "zh")
                base = path.removeprefix("en/")
                self.assertEqual(set(page.alternates), {"zh", "en"})
                for locale, target in page.alternates.items():
                    expected = ("en/" if locale == "en" else "") + base
                    self.assertEqual(self.resolve(path, target)[0], expected)
                    self.assertEqual(page.language_controls[locale].get("aria-current"),
                                     "true" if locale == page.language else None)

    def test_translations_preserve_public_options_and_artifact_paths(self):
        """Translation must not rename CLI options or literal generated artifact files."""
        for source in self.sources:
            original = source.read_text(encoding="utf-8")
            translation = source.with_suffix(".en.md").read_text(encoding="utf-8")
            references = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9_-]+", original))
            for token in re.findall(r"(?<!`)`([^`\n]+)`(?!`)", original):
                if re.fullmatch(r"(?:[\w.{}-]+/)+[\w.{}-]+\.(?:md|py|yaml|yml|json|txt|sh|toml)", token):
                    references.add(token)
            for reference in references:
                with self.subTest(source=source.relative_to(ROOT), reference=reference):
                    self.assertIn(reference, translation)

    def test_homepages_open_their_documentation_automatically(self):
        """Root locale detection must not race a refresh; explicit English stays fixed."""
        root = self.pages["index.html"]
        english = self.pages["en/index.html"]
        self.assertTrue(root.redirect_script.strip())
        self.assertIsNone(root.refresh)
        self.assertFalse(english.redirect_script)
        for path, refresh in (("index.html", root.noscript_refresh),
                              ("en/index.html", english.refresh)):
            with self.subTest(page=path):
                self.assertIsNotNone(refresh)
                delay, destination = refresh.split("; url=", 1)
                self.assertEqual(delay, "0")
                self.assertEqual(self.resolve(path, destination)[0],
                                 "en/content/00_index/index.html")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required to execute the browser redirect")
    def test_root_redirect_uses_the_first_preferred_browser_language(self):
        """Execute the rendered script for Chinese variants, other locales, and fallbacks."""
        cases = [
            ({"languages": [locale], "language": locale}, "")
            for locale in ("zh", "zh-CN", "zh-TW", "zh-HK", "zh-SG",
                           "zh-Hans", "zh-Hant-TW", "ZH-cn")
        ] + [
            ({"languages": [locale], "language": locale}, "en/")
            for locale in ("en-US", "en", "ja-JP", "fr-FR", "zhx")
        ] + [
            ({"languages": ["en-US", "zh-CN"], "language": "zh-CN"}, "en/"),
            ({"languages": ["zh-TW", "en-US"], "language": "en-US"}, ""),
            ({"languages": [], "language": "zh-CN"}, ""),
            ({"language": "zh-Hant"}, ""),
            ({"languages": [], "language": "en-US"}, "en/"),
            ({}, "en/"),
        ]
        script = self.pages["index.html"].redirect_script
        result = subprocess.run(
            [shutil.which("node"), "-e", """
                const vm = require('node:vm');
                const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
                const results = input.cases.map(([navigator]) => {
                    let destination;
                    vm.runInNewContext(input.script, {
                        navigator,
                        window: {location: {
                            search: '?from=home',
                            hash: '#section',
                            replace: value => { destination = value; }
                        }}
                    });
                    return destination;
                });
                process.stdout.write(JSON.stringify(results));
            """],
            input=json.dumps({"script": script, "cases": cases}),
            capture_output=True, text=True, timeout=20, check=True,
        )
        destinations = json.loads(result.stdout)
        self.assertEqual(len(destinations), len(cases))
        for (navigator, prefix), destination in zip(cases, destinations):
            with self.subTest(navigator=navigator):
                self.assertIsInstance(destination, str)
                self.assertEqual(self.resolve("index.html", destination),
                                 (prefix + "content/00_index/index.html", "section"))
                self.assertEqual(urlsplit(destination).query, "from=home")

    def test_internal_links_images_and_article_anchors_exist(self):
        """Resolve rendered links and images in both languages at nested depths."""
        for path, page in self.pages.items():
            for link in page.links:
                target, fragment = self.resolve(path, link)
                if target is None:
                    continue
                with self.subTest(page=path, link=link):
                    self.assertTrue((self.site / target).is_file(), target)
                    if fragment and link in page.article_links and target in self.pages:
                        self.assertIn(fragment, self.pages[target].ids)

    def test_english_article_links_remain_in_english(self):
        """Translated Markdown links must stay within the English document tree."""
        for path, page in self.pages.items():
            if not path.startswith("en/"):
                continue
            for link in page.article_links:
                target, _ = self.resolve(path, link)
                if target in self.pages:
                    with self.subTest(page=path, link=link):
                        self.assertTrue(target.startswith("en/"), target)

    def test_search_contains_both_languages(self):
        """Search must index actual English and Chinese content and page URLs."""
        index = json.loads((self.site / "search/search_index.json").read_text())
        # Material segments Chinese at build time; lunr.zh breaks its worker.
        self.assertEqual(index["config"]["lang"], ["en"])
        entries = index["docs"]
        for prefix in ("", "en/"):
            location = prefix + "content/01_start/00_installation/"
            matching = [entry for entry in entries if entry["location"].split("#")[0] == location]
            self.assertTrue(matching, location)
            text = " ".join(entry["text"] for entry in matching)
            self.assertIn("pip install", text)
            source = ROOT / "docs/content/01_start" / ("00_installation.en.md" if prefix else "00_installation.md")
            title = re.search(r"^# (.+)$", source.read_text(encoding="utf-8"), re.MULTILINE).group(1)
            self.assertIn(title, [entry["title"].replace(chr(0x200B), "") for entry in matching])

    def test_redirects_preserve_existing_document_urls(self):
        """Historical Chinese document URLs must redirect to their current pages."""
        redirects = self.config.plugins["redirects"].config["redirect_maps"]
        for old, new in redirects.items():
            path = str(Path(old).with_suffix("") / "index.html")
            page = Page(self.site / path)
            destination = str(Path(new).with_suffix("") / "index.html")
            self.assertTrue(any(self.resolve(path, link)[0] == destination for link in page.links), path)


@unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required to validate PDF section links")
class DocumentationPdfTest(unittest.TestCase):
    """Keep web layout containers from changing PDF chapter link mappings."""

    def test_homepage_layout_preserves_pdf_section_targets(self):
        """Nested homepage headings must not shift subsequent input-file targets."""
        sources = ["docs/content/00_index.md",
                   "docs/content/01_start/00_installation.md"]
        documents = []
        for filters in ([], ["--lua-filter=docs/pandoc/convert_md_links.lua"]):
            result = subprocess.run(
                [shutil.which("pandoc"), *sources,
                 "--from=markdown+table_captions+grid_tables+header_attributes+pipe_tables",
                 "--to=json", *filters],
                cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
            )
            pending = [json.loads(result.stdout)["blocks"]]
            headings, links = [], []
            while pending:
                node = pending.pop()
                if isinstance(node, dict):
                    if node.get("t") == "Header" and node["c"][0] == 1:
                        headings.append(node["c"][1][0])
                    if node.get("t") == "Link":
                        links.append(node["c"][-1][0])
                    pending.extend(reversed(list(node.values())))
                elif isinstance(node, list):
                    pending.extend(reversed(node))
            documents.append((headings, links))
        original, converted = documents
        self.assertEqual(len(converted[0]), len(sources))
        self.assertEqual(len(original[1]), len(converted[1]))
        checked = 0
        for before, after in zip(original[1], converted[1]):
            for index, source in enumerate(sources):
                if before.endswith(Path(source).name):
                    self.assertEqual(after, "#" + converted[0][index])
                    checked += 1
        self.assertGreaterEqual(checked, 3)


if __name__ == "__main__":
    unittest.main()
