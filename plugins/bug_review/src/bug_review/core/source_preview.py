"""Create bounded citations and offline source readers without changing upstream files."""

from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit
from markupsafe import Markup
from .json_io import read_object


class SourceRegistry:
    """Deduplicate cited documents and collect the exact assets needed by their previews."""

    def __init__(self, layout, environment, labels, pages, assets):
        """Keep one rendering-plan-local registry; never write during planning or verification."""
        self.layout = layout
        self.environment = environment
        self.labels = labels
        self.pages = pages
        self.assets = assets
        self.documents = {}
        self.catalog = read_object(layout.inputs / 'review_standards/catalog.json')

    def add(self, reference):
        """Validate a citation, render its full source once and return a bounded excerpt."""
        excerpt = self.layout.source(reference, 40)
        name, coordinates = reference.rsplit(':', 1)
        first = int(coordinates.split('-')[0])
        if name not in self.documents:
            filename = f'assets/source-{len(self.documents) + 1:04d}.html'
            self.documents[name] = filename
            base = self.layout.out if Path(name).parts[0] in {'inputs', 'runs'} else self.layout.workspace
            source = (base / name).resolve()
            original = source.read_text(encoding='utf-8', errors='replace')
            lines = original.splitlines()
            markdown = source.suffix.lower() in {'.md', '.markdown', '.mdx'}
            provenance = None
            prefix = 'inputs/review_standards/'
            if name.startswith(prefix):
                relative = name[len(prefix):]
                for item in self.catalog['sources']:
                    snapshot = item.get('snapshot', item['id'])
                    if relative.startswith(snapshot + '/'):
                        repository = item.get('repository', '')
                        url = repository.removesuffix('.git') + '/blob/' + item['revision'] + '/' + quote(relative[len(snapshot) + 1:], safe='/') if repository.startswith('https://') else ''
                        provenance = {'url': url, 'revision': item['revision'], 'retrieved_at': item.get('retrieved_at', '')}
                        break
            rendered, toc, seen = '', [], set()
            if markdown:
                try:
                    from markdown_it import MarkdownIt
                except ImportError as error:
                    raise ValueError('Markdown preview requires markdown-it-py>=3,<5; install the Bug Review plugin dependencies') from error
                prepared = original
                if original.startswith('---\n'):
                    match = re.match(r'---\n.*?\n---(?:\n|$)', original, re.S)
                    if match:
                        prepared = '\n' * match[0].count('\n') + original[match.end():]
                parser = MarkdownIt('commonmark', {'html': False}).enable('table').enable('strikethrough')
                tokens = parser.parse(prepared)
                headings = {}
                for index, token in enumerate(tokens):
                    if token.map and token.type != 'inline' and token.nesting >= 0:
                        start, end = token.map
                        token.attrSet('data-source-start', str(start + 1))
                        token.attrSet('data-source-end', str(end))
                        if start + 1 not in seen:
                            token.attrSet('id', 'L' + str(start + 1))
                            seen.add(start + 1)
                        if token.type == 'heading_open':
                            text = ''.join(t.content for t in (tokens[index + 1].children or []) if t.type in {'text', 'code_inline'})
                            headings[re.sub(r'[^\w\- ]', '', text).lower().replace(' ', '-')] = start + 1
                            if int(token.tag[1]) <= 3:
                                toc.append({'line': start + 1, 'text': text, 'level': int(token.tag[1])})
                for token in tokens:
                    disabled_links = []
                    for child in token.children or []:
                        if child.type == 'image':
                            raw = child.attrGet('src') or ''
                            parsed = urlsplit(raw)
                            if parsed.scheme or not parsed.path:
                                continue
                            candidate = (source.parent / unquote(parsed.path)).resolve()
                            # Docsy and Docusaurus keep figures outside their content tree.
                            if not candidate.is_file() and 'documents/content/' in str(source):
                                content_root = next(parent for parent in source.parents if parent.name == 'documents' and (parent / 'content').is_dir())
                                suffix = source.relative_to(content_root / 'content').parts[1:]
                                candidate = (content_root / 'static' / Path(*suffix).with_suffix('') / unquote(parsed.path)).resolve()
                            if not candidate.is_file() and raw.startswith('/img/') and provenance:
                                relative = name[len(prefix):].split('/', 1)[0]
                                candidate = (self.layout.inputs / 'review_standards' / relative / 'website/static' / raw.lstrip('/')).resolve()
                            if candidate.is_file() and candidate.is_relative_to(self.layout.workspace) and candidate.suffix.lower() in {'.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp'}:
                                relative = 'assets/source-media/' + candidate.relative_to(self.layout.workspace).as_posix()
                                self.assets[relative] = candidate
                                child.attrSet('src', quote(relative[len('assets/'):], safe='/'))
                            else:
                                # Keep the missing image description, without generating a broken URL.
                                child.type, child.tag, child.content = 'text', '', child.content or raw
                                child.attrs = {}
                        elif child.type == 'link_open':
                            raw = child.attrGet('href') or ''
                            parsed = urlsplit(raw)
                            disabled = False
                            if parsed.scheme or parsed.netloc:
                                pass
                            elif not parsed.path and parsed.fragment in headings:
                                child.attrSet('href', '#L' + str(headings[parsed.fragment]))
                            elif not parsed.path and re.fullmatch(r'L\d+', parsed.fragment):
                                pass
                            elif provenance and provenance['url']:
                                path = (source.parent / unquote(parsed.path)).resolve()
                                root = self.layout.inputs / 'review_standards' / name[len(prefix):].split('/', 1)[0]
                                if path.is_relative_to(root):
                                    upstream = provenance['url'].split('/blob/', 1)[0]
                                    child.attrSet('href', upstream + '/blob/' + provenance['revision'] + '/' + quote(path.relative_to(root).as_posix(), safe='/') + ('#' + parsed.fragment if parsed.fragment else ''))
                                else:
                                    disabled = True
                            else:
                                disabled = True
                            if disabled:
                                child.tag = 'span'
                                child.attrs.pop('href', None)
                                child.attrSet('title', raw)
                            disabled_links.append(disabled)
                        elif child.type == 'link_close' and disabled_links:
                            if disabled_links.pop():
                                child.tag = 'span'
                rendered = Markup(parser.renderer.render(tokens, parser.options, {}))
            self.pages[filename] = self.environment.get_template('source.html.j2').render(
                labels=self.labels, name=name, lines=lines, markdown=markdown, provenance=provenance,
                rendered=rendered, toc=toc, missing_lines=[n for n in range(1, len(lines) + 1) if n not in seen])
        return {'label': reference, 'href': self.documents[name] + '#L' + str(first),
                'excerpt': excerpt['text'], 'truncated': excerpt['truncated']}

    def many(self, references):
        """Preserve citation order while deduplicating repeated references."""
        return [self.add(ref) for ref in dict.fromkeys(references)]
