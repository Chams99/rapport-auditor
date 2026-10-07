#!/usr/bin/env python3
"""
Conservative academic prose style reviser for LaTeX and plain text files.

The goal is to revise common over-polished academic patterns into clearer,
more natural prose while preserving citations, LaTeX commands, equations,
tables, figures, and technical terms. Use it as an editing assistant, then
read the diff like any other academic revision.
"""

from __future__ import annotations

import argparse
import difflib
import pathlib
import re
import secrets
import sys
from dataclasses import dataclass
from typing import Callable, Iterable


SKIP_ENVIRONMENTS = {
    "equation",
    "equation*",
    "displaymath",
    "math",
    "align",
    "align*",
    "alignat",
    "alignat*",
    "flalign",
    "flalign*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "split",
    "comment",
    "figure",
    "figure*",
    "table",
    "table*",
    "tabular",
    "tikzpicture",
    "lstlisting",
    "minted",
    "verbatim",
    "verbatim*",
}


@dataclass
class Edit:
    line: int
    before: str
    after: str
    reason: str
    code: str = "revision"


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: re.Pattern[str]
    replacement: str | Callable[[re.Match[str]], str]
    reason_en: str
    reason_fr: str


RULES_BY_LANGUAGE: dict[str, list[Rule]] = {
    "en": [
        Rule("chapter_opening", re.compile(r"\bThis chapter examines\b", re.IGNORECASE), "This chapter studies", "Use a direct verb for the chapter’s action.", "Utilisez un verbe direct pour décrire l’action du chapitre."),
        Rule("chapter_opening", re.compile(r"\bThis chapter presents\b", re.IGNORECASE), "This chapter describes", "Use a direct verb for the chapter’s action.", "Utilisez un verbe direct pour décrire l’action du chapitre."),
        Rule("concise_purpose", re.compile(r"\bin order to\b", re.IGNORECASE), "to", "Shorten ‘in order to’ to ‘to’ where the intended purpose is unchanged.", "Remplacez « afin de » par « pour » seulement si le sens reste identique."),
        Rule("concise_cause", re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because", "Shorten this causal phrase to ‘because’.", "Remplacez cette locution causale par « parce que »."),
    ],
    "fr": [
        Rule("chapter_opening", re.compile(r"\bCe chapitre examine\b", re.IGNORECASE), "Ce chapitre étudie", "Use a direct verb for the chapter’s action.", "Utilisez un verbe direct pour décrire l’action du chapitre."),
        Rule("chapter_opening", re.compile(r"\bCe chapitre présente\b", re.IGNORECASE), "Ce chapitre décrit", "Use a direct verb for the chapter’s action.", "Utilisez un verbe direct pour décrire l’action du chapitre."),
        Rule("concise_purpose", re.compile(r"\bafin de\b", re.IGNORECASE), "pour", "Shorten this purpose phrase only if the intended meaning is unchanged.", "Remplacez « afin de » par « pour » seulement si le sens reste identique."),
        Rule("concise_purpose", re.compile(r"\bdans le but de\b", re.IGNORECASE), "pour", "Shorten this purpose phrase only if the intended meaning is unchanged.", "Remplacez « dans le but de » par « pour » seulement si le sens reste identique."),
        Rule("concise_cause", re.compile(r"\ben raison du fait que\b", re.IGNORECASE), "parce que", "Shorten this causal phrase to ‘parce que’.", "Remplacez cette locution causale par « parce que »."),
        Rule("concise_verb", re.compile(r"\brend possible de\b", re.IGNORECASE), "permet de", "Use the shorter verb phrase ‘permet de’ if it preserves the sentence meaning.", "Utilisez la locution plus courte « permet de » si le sens de la phrase est préservé."),
    ],
}

def is_latex_command_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith("\\"):
        return False
    return bool(re.match(r"^\\(?:section|subsection|subsubsection|chapter|caption|label|cite|ref|begin|end|item|includegraphics|centering|hline)\b", stripped))


def update_environment_stack(line: str, stack: list[str]) -> None:
    visible = line
    comment_start = next(
        (index for index, char in enumerate(line) if char == "%" and not _is_escaped(line, index)),
        None,
    )
    if comment_start is not None:
        visible = line[:comment_start]
    for env in re.findall(r"\\begin\{([^}]+)\}", visible):
        stack.append(env)
    for env in re.findall(r"\\end\{([^}]+)\}", visible):
        if env in stack:
            stack.reverse()
            stack.remove(env)
            stack.reverse()


def in_skipped_environment(stack: Iterable[str]) -> bool:
    return any(env in SKIP_ENVIRONMENTS for env in stack)


def protect_inline_latex(line: str) -> tuple[str, dict[str, str]]:
    return _protect_latex_spans(line, {})


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _scan_group(
    text: str,
    start: int,
    opening: str | None = None,
    closers: list[str] | None = None,
) -> tuple[int, list[str], bool]:
    matching = {"{": "}", "[": "]"}
    stack = list(closers or ([matching[opening]] if opening in matching else []))
    index = start + 1 if opening else start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char in matching:
            stack.append(matching[char])
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return index + 1, [], True
        index += 1
    return len(text), stack, False


def _find_unescaped(text: str, delimiter: str, start: int = 0) -> int:
    index = start
    while index < len(text):
        index = text.find(delimiter, index)
        if index < 0:
            return -1
        if not _is_escaped(text, index):
            return index
        index += len(delimiter)
    return -1


def _consume_command(line: str, start: int) -> tuple[int, list[str] | None]:
    index = start + 1
    if index >= len(line):
        return index, None
    if not (line[index].isalpha() or line[index] == "@"):
        return index + 1, None

    name_start = index
    while index < len(line) and (line[index].isalpha() or line[index] == "@"):
        index += 1
    name = line[name_start:index]
    if index < len(line) and line[index] == "*":
        index += 1

    if name in {"verb", "lstinline"}:
        cursor = index
        while cursor < len(line) and line[cursor].isspace() and line[cursor] != "\n":
            cursor += 1
        if name == "lstinline" and cursor < len(line) and line[cursor] == "[":
            option_end, _, option_closed = _scan_group(line, cursor, "[")
            if option_closed:
                cursor = option_end
        if cursor < len(line):
            delimiter = line[cursor]
            close = _find_unescaped(line, delimiter, cursor + 1)
            return (close + 1 if close >= 0 else len(line)), None
        return len(line), None

    cursor = index
    last_group_end = index
    while cursor < len(line):
        whitespace_end = cursor
        while whitespace_end < len(line) and line[whitespace_end] in " \t":
            whitespace_end += 1
        if whitespace_end >= len(line) or line[whitespace_end] not in "[{":
            break
        end, remaining_closers, closed = _scan_group(line, whitespace_end, line[whitespace_end])
        if not closed:
            return len(line), remaining_closers
        cursor = end
        last_group_end = end
    return (last_group_end if last_group_end > index else index), None


def _protect_latex_spans(line: str, state: dict[str, object]) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}
    prefix = f"\ue000RA{secrets.token_hex(8)}_"
    while prefix in line:
        prefix = f"\ue000RA{secrets.token_hex(8)}_"

    chunks: list[str] = []
    cursor = 0
    marker_index = 0

    def preserve(start: int, end: int) -> None:
        nonlocal marker_index
        marker = f"{prefix}{marker_index}\ue001"
        protected[marker] = line[start:end]
        chunks.append(marker)
        marker_index += 1

    group_closers = state.get("group_closers")
    if isinstance(group_closers, list) and group_closers:
        end, remaining, closed = _scan_group(line, 0, closers=group_closers)
        preserve(0, end)
        cursor = end
        if closed:
            state.pop("group_closers", None)
        else:
            state["group_closers"] = remaining
            return "".join(chunks), protected

    math_delimiter = state.get("math_delimiter")
    if isinstance(math_delimiter, str):
        close = _find_unescaped(line, math_delimiter)
        if close < 0:
            preserve(cursor, len(line))
            return "".join(chunks), protected
        end = close + len(math_delimiter)
        preserve(cursor, end)
        cursor = end
        state.pop("math_delimiter", None)

    plain_start = cursor
    while cursor < len(line):
        if line[cursor] == "%" and not _is_escaped(line, cursor):
            if plain_start < cursor:
                chunks.append(line[plain_start:cursor])
            preserve(cursor, len(line))
            cursor = len(line)
            plain_start = cursor
            break

        opening_math: tuple[str, str] | None = None
        if line.startswith(r"\[", cursor):
            opening_math = (r"\[", r"\]")
        elif line.startswith(r"\(", cursor):
            opening_math = (r"\(", r"\)")
        elif line.startswith("$$", cursor) and not _is_escaped(line, cursor):
            opening_math = ("$$", "$$")
        elif line[cursor] == "$" and not _is_escaped(line, cursor):
            opening_math = ("$", "$")

        if opening_math:
            if plain_start < cursor:
                chunks.append(line[plain_start:cursor])
            opening, closing = opening_math
            close = _find_unescaped(line, closing, cursor + len(opening))
            if close < 0:
                preserve(cursor, len(line))
                state["math_delimiter"] = closing
                cursor = len(line)
            else:
                end = close + len(closing)
                preserve(cursor, end)
                cursor = end
            plain_start = cursor
            continue

        if line[cursor] == "\\":
            if plain_start < cursor:
                chunks.append(line[plain_start:cursor])
            end, remaining_closers = _consume_command(line, cursor)
            preserve(cursor, end)
            if remaining_closers:
                state["group_closers"] = remaining_closers
                cursor = len(line)
            else:
                cursor = end
            plain_start = cursor
            continue
        cursor += 1

    if plain_start < len(line):
        chunks.append(line[plain_start:])
    return "".join(chunks), protected


def restore_inline_latex(line: str, protected: dict[str, str]) -> str:
    for key, value in protected.items():
        line = line.replace(key, value)
    return line


def _rule_replacement(rule: Rule) -> str | Callable[[re.Match[str]], str]:
    if callable(rule.replacement):
        return rule.replacement

    def replace(match: re.Match[str]) -> str:
        matched_text = match.group(0)
        replacement = rule.replacement
        if matched_text.isupper():
            return replacement.upper()
        if matched_text.islower():
            return replacement.lower()
        if matched_text[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        if matched_text[:1].islower():
            return replacement[:1].lower() + replacement[1:]
        return replacement

    return replace


def _apply_rules(line: str, content_language: str) -> tuple[str, list[Rule]]:
    protected_line, protected = _protect_latex_spans(line, {})
    used: list[Rule] = []
    updated = protected_line

    for rule in RULES_BY_LANGUAGE[content_language]:
        new_value, count = rule.pattern.subn(_rule_replacement(rule), updated)
        if count:
            used.append(rule)
            updated = new_value

    return restore_inline_latex(updated, protected), used


def apply_rules_to_line(line: str, *, content_language: str = "en") -> tuple[str, list[str]]:
    language = str(content_language or "en").casefold()
    if language not in RULES_BY_LANGUAGE:
        raise ValueError("content_language must be 'en' or 'fr'")
    updated, used = _apply_rules(line, language)
    return updated, [rule.reason_fr if language == "fr" else rule.reason_en for rule in used]


def humanize_text(text: str, *, content_language: str = "en") -> tuple[str, list[Edit]]:
    language = str(content_language or "en").casefold()
    if language not in RULES_BY_LANGUAGE:
        raise ValueError("content_language must be 'en' or 'fr'")
    lines = text.splitlines(keepends=True)
    stack: list[str] = []
    edits: list[Edit] = []
    output: list[str] = []
    inline_state: dict[str, object] = {}

    for index, line in enumerate(lines, start=1):
        before_stack = list(stack)
        skip = in_skipped_environment(before_stack) or is_latex_command_line(line)

        if skip or not line.strip():
            output.append(line)
        else:
            ending_match = re.search(r"(?:\r\n|\n|\r)$", line)
            ending = ending_match.group(0) if ending_match else ""
            body = line[:-len(ending)] if ending else line
            protected_line, protected = _protect_latex_spans(body, inline_state)
            used: list[Rule] = []
            updated = protected_line
            for rule in RULES_BY_LANGUAGE[language]:
                new_value, count = rule.pattern.subn(_rule_replacement(rule), updated)
                if count:
                    used.append(rule)
                    updated = new_value
            updated = restore_inline_latex(updated, protected)
            if updated != body:
                reasons = [rule.reason_fr if language == "fr" else rule.reason_en for rule in used]
                codes = list(dict.fromkeys(rule.code for rule in used))
                edits.append(Edit(index, body, updated, "; ".join(dict.fromkeys(reasons)), ",".join(codes)))
            output.append(updated + ending)

        update_environment_stack(line, stack)

    return "".join(output), edits


def revise_text(text: str, *, content_language: str = "en", source_format: str | None = None) -> tuple[str, list[Edit]]:
    return humanize_text(text, content_language=content_language)


def format_report(path: str, edits: list[Edit], limit: int) -> str:
    lines = [f"Path: {path}", f"Edits: {len(edits)}"]
    if edits:
        lines.append("")
        lines.append("Changed lines:")
        for edit in edits[:limit]:
            lines.append(f"  - line {edit.line}: {edit.reason}")
            lines.append(f"    before: {edit.before.strip()}")
            lines.append(f"    after:  {edit.after.strip()}")
        if len(edits) > limit:
            lines.append(f"  ... {len(edits) - limit} more edits omitted")
    return "\n".join(lines)


def build_diff(path: pathlib.Path, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(path),
            tofile=f"{path} (revision preview)",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview a small set of bilingual, meaning-aware prose edits while preserving LaTeX."
    )
    parser.add_argument("path", nargs="?", help="Text or .tex file. Reads stdin if omitted.")
    parser.add_argument("--write", action="store_true", help="Overwrite the input file with the revised text.")
    parser.add_argument("--diff", action="store_true", help="Print a unified diff.")
    parser.add_argument("--report-limit", type=int, default=20, help="Maximum changed lines to show in the report.")
    parser.add_argument("--content-language", choices=("en", "fr"), default="en", help="Language of the document (default: en).")
    args = parser.parse_args()

    if args.path:
        path = pathlib.Path(args.path)
        before = path.read_text(encoding="utf-8")
        display_path = str(path)
    else:
        path = None
        before = sys.stdin.read()
        display_path = "<stdin>"

    after, edits = humanize_text(before, content_language=args.content_language)

    if args.diff:
        if path is None:
            sys.stdout.write("Diff output needs a file path.\n")
        else:
            sys.stdout.write(build_diff(path, before, after))
            if edits:
                sys.stdout.write("\n")

    print(format_report(display_path, edits, args.report_limit))

    if args.write:
        if path is None:
            sys.stderr.write("--write requires a file path.\n")
            return 2
        path.write_text(after, encoding="utf-8")
        print(f"\nWrote revised file: {path}")
    elif not args.diff and path is None:
        sys.stdout.write("\n--- revised text ---\n")
        sys.stdout.write(after)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
