"""Library-independent signal query syntax for hierarchy and declared bus paths."""

import re
from collections.abc import Callable


def compile_signal_query(path: str) -> Callable[[str], bool]:
    """Compile exact paths, *, recursive **, /regex/, and brace alternatives/ranges.

    Brackets denote literal HDL indices, never shell character classes. A query
    without a terminal range can also match a whole bus's declared range.
    Regex components use Python regex syntax and match their complete component.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("signal query must not be blank")
    parts = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == '/':
            end = index + 1
            while end < len(path) and (path[end] != '/' or path[end - 1] == '\\'):
                end += 1
            if end == len(path):
                raise ValueError("signal regex must have a closing slash")
            parts.append('(?:' + path[index + 1:end] + ')')
            index = end + 1
        elif char == '{':
            end = path.find('}', index)
            if end < 0:
                raise ValueError("signal alternatives must have a closing brace")
            content = path[index + 1:end]
            span = re.fullmatch(r'(-?\d+)\.\.(-?\d+)', content)
            if span:
                start, stop = map(int, span.groups())
                if abs(stop - start) > 10000:
                    raise ValueError("signal range contains too many alternatives")
                step = 1 if stop >= start else -1
                choices = [str(value) for value in range(start, stop + step, step)]
            else:
                choices = content.split(',')
                if any(not choice or '{' in choice for choice in choices):
                    raise ValueError("signal alternatives must be nonempty and cannot nest")
            parts.append('(?:' + '|'.join(re.escape(choice) for choice in choices) + ')')
            index = end + 1
        elif path.startswith('**.', index):
            parts.append(r'(?:[^.]+\.)*')
            index += 3
        elif path.startswith('**', index):
            parts.append('.*')
            index += 2
        elif char == '*':
            parts.append('[^.]*')
            index += 1
        elif char == '}':
            raise ValueError("unexpected closing signal alternative brace")
        else:
            parts.append(re.escape(char))
            index += 1
    expression = re.compile(''.join(parts))

    def matches(name: str) -> bool:
        """Match a full path or its unqualified whole-bus declaration."""
        return bool(expression.fullmatch(name) or expression.fullmatch(re.sub(r'\[-?\d+:-?\d+\]$', '', name)))

    return matches
