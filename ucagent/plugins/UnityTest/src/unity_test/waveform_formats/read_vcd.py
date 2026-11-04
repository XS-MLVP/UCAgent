"""VCD implementations preserving native declarations and unchanged time bounds."""

import re

from .adapter_pywellen import PywellenReaderAdapter
from .adapter_wavekit import WavekitReaderAdapter


class WellenVcdReader(PywellenReaderAdapter):
    """Decode VCD values with pywellen while retaining declaration bit indices."""

    def __enter__(self):
        """Read declarations and all timestamp markers without retaining trace data."""
        import pywellen  # noqa: F401 - dependency check precedes metadata I/O

        scope = []
        directive = []
        in_header = True
        in_comment = False
        expect_identifier = False
        first_time = None
        with open(self.path, encoding='utf-8') as source:
            for line in source:
                for token in line.split():
                    if in_header:
                        directive.append(token)
                        if token != '$end':
                            continue
                        command, *body, _ = directive
                        directive = []
                        if command == '$scope':
                            scope.append(body[1])
                        elif command == '$upscope':
                            if not scope:
                                raise ValueError('Unbalanced VCD scope declarations')
                            scope.pop()
                        elif command == '$var':
                            name = '.'.join([*scope, ''.join(body[3:])])
                            self._add_declaration(name, int(body[1]))
                        elif command == '$enddefinitions':
                            if scope:
                                raise ValueError('Unclosed VCD scope declarations')
                            in_header = False
                    elif in_comment:
                        in_comment = token != '$end'
                    elif expect_identifier:
                        # VCD identifier codes may themselves look like #123.
                        # Only a timestamp outside a value/identifier pair counts.
                        expect_identifier = False
                    elif token == '$comment':
                        in_comment = True
                    elif token[0] in 'bBrRsS':
                        expect_identifier = True
                        if first_time is None:
                            first_time = 0
                    elif re.fullmatch(r'#\d+', token):
                        value = int(token[1:])
                        if first_time is None:
                            first_time = value
                        if value < self._end_time:
                            raise ValueError('VCD timestamps must be nondecreasing')
                        self._end_time = value
                    elif not token.startswith('$') and first_time is None:
                        first_time = 0
        if in_header:
            raise ValueError('Missing VCD enddefinitions')
        if expect_identifier:
            raise ValueError('Missing VCD value identifier')
        self._begin_time = first_time if first_time is not None else 0
        return super().__enter__()


class WavekitVcdReader(WavekitReaderAdapter):
    """Adapt wavekit's VCD implementation to the public waveform contract."""

    def __init__(self, path: str) -> None:
        """Create a resource-owning context for exactly the selected VCD file."""
        import wavekit

        super().__init__(wavekit.VcdReader(path))
