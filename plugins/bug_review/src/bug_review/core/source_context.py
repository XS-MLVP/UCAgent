"""Provide bounded original test and helper navigation without executing input code."""

import ast
from pathlib import Path


def case_source_context(layout, case_id):
    """Locate exact pytest definitions and static helper candidates inside archived input."""
    navigation = {'test_excerpts': [], 'helper_refs': [], 'diagnostics': [],
                  'next_action': 'Use ReviewRefCheck for the named helpers and actual failure/specification lines; static references do not prove execution.'}
    try:
        relative, _, identity = case_id.partition('::')
        navigation['test_file'] = 'inputs/' + relative
        source = layout.path('inputs/' + relative)
        if not relative.startswith('tests/') or not source.is_file():
            raise ValueError('Case source must exist under inputs/tests/')
        tree = ast.parse(source.read_text(encoding='utf-8'), filename=relative)
        definitions, scopes = {}, [((), tree.body)]
        while scopes:
            scope, body = scopes.pop()
            for node in body:
                if isinstance(node, ast.ClassDef):
                    scopes.append(((*scope, node.name), node.body))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    definitions[(*scope, node.name)] = node
        # Pytest parameters decorate the node identity, not the Python definition.
        key = tuple(identity.split('[', 1)[0].split('::'))
        function = definitions.get(key)
        if function is None:
            navigation['available_definitions'] = ['::'.join(name) for name in sorted(definitions)[:12]]
            raise ValueError('No exact local test definition; inspect the indexed test file and its imports/inheritance')
        first = min([function.lineno, *[decorator.lineno for decorator in function.decorator_list]])
        last = function.end_lineno
        ranges = [(first, last)] if last - first < 60 else [(first, first + 29), (last - 29, last)]
        navigation['test_truncated'] = last - first >= 60
        for start, end in ranges:
            excerpt = layout.source(f'inputs/{relative}:{start}-{end}', 60)
            if len(excerpt['text']) > 6000:
                excerpt['text'] = excerpt['text'][:6000]
                excerpt['truncated'] = navigation['test_truncated'] = True
            navigation['test_excerpts'].append(excerpt)
        references, queue, visited = set(), [(key, function, 0)], set()
        while queue:
            scope, body, depth = queue.pop(0)
            if scope in visited:
                continue
            visited.add(scope)
            for call in ast.walk(body):
                if not isinstance(call, ast.Call):
                    continue
                if isinstance(call.func, ast.Name):
                    name, target = call.func.id, (call.func.id,)
                    references.add(name)
                elif (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                      and call.func.value.id in {'self', 'cls'}):
                    name, target = call.func.attr, (*scope[:-1], call.func.attr)
                else:
                    continue
                helper = definitions.get(target)
                if helper is not None and target != key and len(navigation['helper_refs']) < 16:
                    ref = f'inputs/{relative}:{helper.lineno}-{helper.end_lineno}'
                    entry = {'name': name, 'ref': ref}
                    if entry not in navigation['helper_refs']:
                        navigation['helper_refs'].append(entry)
                    if depth < 2:
                        queue.append((target, helper, depth + 1))
        # Inspect only explicit local import candidates; never import test code.
        inspected_imports = 0
        for imported in tree.body:
            if not isinstance(imported, ast.ImportFrom) or not imported.module:
                continue
            if len(navigation['helper_refs']) >= 16 or inspected_imports >= 8:
                navigation['diagnostics'].append('Helper navigation is bounded; inspect remaining calls in the original test source')
                break
            module = Path(*imported.module.split('.')).with_suffix('.py')
            if imported.level:
                parent = Path(relative).parent
                for _ in range(imported.level - 1):
                    if parent == Path('.'):
                        raise ValueError('Relative helper import leaves the archived source package; inspect it explicitly')
                    parent = parent.parent
                candidates = [parent / module]
            else:
                candidates = dict.fromkeys([Path(relative).parent / module, module])
            for candidate in candidates:
                if inspected_imports >= 8:
                    navigation['diagnostics'].append('Local import navigation is bounded; inspect remaining imports in the original source')
                    break
                imported_source = layout.path('inputs/' + candidate.as_posix())
                if not imported_source.is_file():
                    continue
                inspected_imports += 1
                try:
                    imported_tree = ast.parse(imported_source.read_text(encoding='utf-8'))
                except (SyntaxError, UnicodeError) as error:
                    navigation['diagnostics'].append(f'{candidate}: {type(error).__name__}; inspect the source directly')
                    continue
                aliases = {alias.asname or alias.name: alias.name for alias in imported.names}
                wildcard = '*' in aliases
                for helper in imported_tree.body:
                    if not isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    names = sorted(name for name in references if (name == helper.name if wildcard else aliases.get(name) == helper.name))
                    for name in names:
                        entry = {'name': name, 'ref': f'inputs/{candidate.as_posix()}:{helper.lineno}-{helper.end_lineno}'}
                        if entry not in navigation['helper_refs'] and len(navigation['helper_refs']) < 16:
                            navigation['helper_refs'].append(entry)
    except (ValueError, OSError, SyntaxError, UnicodeError) as error:
        navigation['diagnostics'].append(str(error)[:500])
    return navigation
