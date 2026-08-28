"""Small Markdown formatting helpers shared by runtime document producers."""

from __future__ import annotations

import re


_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+.*)?$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_MACHINE_HEADING_COMPANION_RE = re.compile(
    r"^<(?:BUG-(?:OVERVIEW|SYMPTOMS|TRIGGER)|"
    r"ROOT-(?:CAUSE-ANALYSIS|SOURCE-EVIDENCE|CAUSAL-CHAIN|FIX|RETEST)|"
    r"RELATED-BUGS)>$"
)


def _fence_language(info: str) -> str:
    language = info.strip().split(maxsplit=1)[0].lower() if info.strip() else ""
    return language.strip("{.}")


def markdown_heading_spacing_errors(
    text: str,
    heading_companions: tuple[str, ...] | frozenset[str] = (),
) -> list[tuple[int, str]]:
    """Return heading line numbers whose surrounding blank line is missing.

    Only normal Markdown and fenced ``markdown``/``md`` examples are inspected;
    other fenced languages are treated as opaque source code. Every heading,
    including the first line of a document or embedded example, requires a
    preceding blank line. Canonical machine companion lines may be supplied
    when a document contract requires them to remain adjacent after a field
    heading.
    """

    lines = text.splitlines()
    companions = frozenset(line.strip() for line in heading_companions)
    fences: list[tuple[str, int, bool]] = []
    errors: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        fence = _FENCE_RE.fullmatch(line)
        if fence:
            token, info = fence.groups()
            if (
                fences
                and token[0] == fences[-1][0]
                and len(token) >= fences[-1][1]
                and not info.strip()
            ):
                fences.pop()
            elif not fences or fences[-1][2]:
                active = _fence_language(info) in {"md", "markdown"}
                fences.append((token[0], len(token), active))
            continue

        if fences and not fences[-1][2]:
            continue
        if not _HEADING_RE.fullmatch(line):
            continue

        if index == 0 or lines[index - 1].strip():
            errors.append((index + 1, "before"))
        if (
            index + 1 >= len(lines)
            or (lines[index + 1].strip() and lines[index + 1].strip() not in companions)
        ):
            errors.append((index + 1, "after"))

    return errors


def ensure_markdown_heading_spacing(
    text: str,
    heading_companions: tuple[str, ...] | frozenset[str] = (),
) -> str:
    """Insert missing blank lines around Markdown headings without reflowing text."""

    if not text:
        return text

    newline = "\r\n" if "\r\n" in text else "\n"
    companions = frozenset(line.strip() for line in heading_companions)
    lines = text.splitlines(keepends=True)
    bodies = [line.rstrip("\r\n") for line in lines]
    fences: list[tuple[str, int, bool]] = []
    headings: set[int] = set()

    for index, line in enumerate(bodies):
        fence = _FENCE_RE.fullmatch(line)
        if fence:
            token, info = fence.groups()
            if (
                fences
                and token[0] == fences[-1][0]
                and len(token) >= fences[-1][1]
                and not info.strip()
            ):
                fences.pop()
            elif not fences or fences[-1][2]:
                active = _fence_language(info) in {"md", "markdown"}
                fences.append((token[0], len(token), active))
            continue

        if (not fences or fences[-1][2]) and _HEADING_RE.fullmatch(line):
            headings.add(index)

    output: list[str] = []
    for index, line in enumerate(lines):
        if index in headings:
            if index == 0 and not output:
                output.append(newline)
            elif (
                index > 0
                and bodies[index - 1].strip()
                and output
                and output[-1].rstrip("\r\n").strip()
            ):
                output.append(newline)
            output.append(line)
            next_is_machine_companion = (
                index + 1 < len(lines)
                and bodies[index + 1].strip() in companions
            )
            if not next_is_machine_companion and (
                index + 1 >= len(lines) or bodies[index + 1].strip()
            ):
                if not line.endswith(("\n", "\r")):
                    output.append(newline)
                output.append(newline)
        else:
            output.append(line)

    result = "".join(output)
    return result


def ensure_markdown_file_heading_spacing(path: str, text: str) -> str:
    """Normalize headings when *path* identifies a Markdown document or template."""

    normalized_path = str(path).lower()
    if not normalized_path.endswith((".md", ".md.j2")):
        return text
    companions = frozenset(
        line.strip()
        for line in text.splitlines()
        if _MACHINE_HEADING_COMPANION_RE.fullmatch(line.strip())
    )
    return ensure_markdown_heading_spacing(text, companions)
