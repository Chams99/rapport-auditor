#!/usr/bin/env python3
"""Bilingual writing-pattern and visible-citation review tools.

This module exposes lightweight, deterministic prompts. It does not classify
authorship, assess factual truth, resolve sources, or provide calibrated scores.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter
from dataclasses import asdict
from typing import List


PDF_WORD_BREAK_REPAIRS = {
    "com prising": "comprising", "com prise": "comprise", "com prises": "comprises",
    "f low": "flow", "f lows": "flows", "dash board": "dashboard", "back end": "backend",
    "front end": "frontend", "devel opment": "development", "cor rectly": "correctly",
    "re ally": "really", "thefirst": "the first", "BytheendofSprint1": "By the end of Sprint 1",
    "Sprint1": "Sprint 1", "imple mentation": "implementation", "veri fication": "verification",
    "authenti cation": "authentication", "ac count": "account", "admin istrative": "administrative",
    "administra tive": "administrative", "adminis trative": "administrative", "func tionality": "functionality",
    "con figuration": "configuration", "docu mentation": "documentation", "inter face": "interface",
    "Postgre SQL": "PostgreSQL", "Web Socket": "WebSocket",
}

LATEX_FORMATTING_COMMANDS = {"textbf", "textit", "emph", "texttt", "underline"}
LATEX_DROP_ENVIRONMENTS = {
    "figure", "figure*", "table", "table*", "tikzpicture", "tabular", "equation", "equation*", "align", "align*",
    "alignat", "alignat*", "flalign", "flalign*", "gather", "gather*", "multline", "multline*", "displaymath", "math",
    "split", "verbatim", "verbatim*", "lstlisting", "minted", "comment",
}
LATEX_HEADING_COMMANDS = {"section", "subsection", "subsubsection", "chapter", "paragraph", "caption", "title"}


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def repair_pdf_word_breaks(text: str) -> str:
    for broken, fixed in PDF_WORD_BREAK_REPAIRS.items():
        text = re.sub(re.escape(broken), fixed, text, flags=re.IGNORECASE)
    return text


def pdf_word_break_hits(text: str) -> List[str]:
    lowered = text.casefold()
    return sorted(broken for broken in PDF_WORD_BREAK_REPAIRS if broken.casefold() in lowered)


def strip_pdf_artifacts(text: str) -> str:
    """Remove repeated university headers and standalone page numbers."""
    lines = text.splitlines()
    normalized = [normalize_whitespace(line) for line in lines]
    counts = Counter(line for line in normalized if line)
    headers = re.compile(r"faculty of sciences|universit|department|ann[ée]e universitaire|202[0-9][-/]202[0-9]", re.I)
    kept: list[str] = []
    for raw, line in zip(lines, normalized):
        lowered = line.casefold()
        if not line or re.fullmatch(r"\d+", line):
            continue
        if "faculty of sciences of gafsa" in lowered:
            raw = re.sub(r"\s*\d*\s*Faculty of Sciences of Gafsa\s+202[0-9][-/]202[0-9]\s*", " ", raw, flags=re.I)
            line = normalize_whitespace(raw)
            lowered = line.casefold()
        if counts[line] >= 2 and len(line) <= 90 and headers.search(lowered):
            continue
        if re.fullmatch(r"\d+\s+faculty of sciences.*202[0-9].*", lowered):
            continue
        if re.fullmatch(r".*\bfaculty of sciences of gafsa\b.*\b202[0-9][-/]202[0-9]\b.*", lowered):
            continue
        kept.append(raw)
    return repair_pdf_word_breaks("\n".join(kept))


def strip_latex(text: str) -> str:
    """Keep prose while removing common LaTeX structure, math and references."""
    for environment in LATEX_DROP_ENVIRONMENTS:
        text = re.sub(rf"\\begin\{{{re.escape(environment)}\}}.*?\\end\{{{re.escape(environment)}\}}", " ", text, flags=re.S)
    text = re.sub(r"\\item\b", ". ", text)
    for command in LATEX_HEADING_COMMANDS:
        text = re.sub(rf"\\{command}\*?(?:\[[^\]]*\])?\{{[^}}]*\}}", ". ", text)
    text = re.sub(r"\\addcontentsline\{[^}]*\}\{[^}]*\}\{[^}]*\}", " ", text)
    text = re.sub(r"\\label\{[^}]*\}", " ", text)
    text = re.sub(r"\\(?:ref|pageref|autoref)\{[^}]*\}", " [REF] ", text)
    text = re.sub(r"\\phantomsection\b", " ", text)
    citation_command = re.compile(r"\\(?:cite[a-z]*|[pP]arencite|[tT]extcite|[aA]utocite|footcite|smartcite|supercite)\*?(?:\[[^\]]*\]){0,2}\s*\{[^{}]*\}", re.I)
    text = citation_command.sub(" [CITATION] ", text)
    text = re.sub(r"\\url\{([^}]*)\}", r" \1 [URL] ", text)
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r" \1 [URL] ", text)
    text = text.replace("\\\\", " ")

    pattern = re.compile(r"\\([a-zA-Z*]+)(?:\[[^\]]*\])?\{([^{}]*)\}")
    changed = True
    while changed:
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal changed
            changed = True
            command = match.group(1).rstrip("*")
            return f" {match.group(2)} " if command in LATEX_FORMATTING_COMMANDS else " "

        text = pattern.sub(replace, text)
    text = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z*]+(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\$\$?.*?\$\$?", " ", text, flags=re.S)
    text = re.sub(r"\\\[.*?\\\]|\\\(.*?\\\)", " ", text, flags=re.S)
    return normalize_whitespace(text)


def split_sentences(text: str, *, content_language: str = "en") -> List[str]:
    """Compatibility helper that uses the same Unicode-aware sentence rules."""
    from .review import _sentence_spans  # lazy import avoids a utility cycle
    return [item[0] for item in _sentence_spans(text, "\ue000RA-CITE-", content_language)]


def tokenize(text: str) -> List[str]:
    from .review import _tokens  # lazy import avoids a utility cycle
    return _tokens(text)


def audit_text(text: str, path: str = "<text>", *, content_language: str = "en", source_format: str | None = None):
    from .review import audit_text as run_review
    return run_review(text, path, content_language=content_language, source_format=source_format)


def audit_text_deep(text: str, path: str = "<text>", *, content_language: str = "en", source_format: str | None = None):
    from .review import audit_text_deep as run_review
    return run_review(text, path, content_language=content_language, source_format=source_format)


def extract_citation_findings(text: str, *, content_language: str = "en"):
    from .review import extract_citation_findings as run_review
    return run_review(text, content_language=content_language)


# Public model imports remain available from the historical `audit` module.
from .review import (  # noqa: E402
    AuditReport as AuditReport,
    CitationCue as CitationCue,
    DeepAuditReport as DeepAuditReport,
    Occurrence as Occurrence,
    ReviewFinding as ReviewFinding,
)


def report_to_text(report: AuditReport) -> str:
    language_name = "French" if report.content_language == "fr" else "English"
    lines = [
        f"Path: {report.path}",
        f"Content language: {language_name}",
        f"Words: {report.word_count}",
        f"Sentences: {report.sentence_count}",
        f"Passages with prompts: {report.flagged_sentence_count}",
        "",
        "Limitations:",
        *(f"  - {note}" for note in report.notes),
        "",
    ]
    if report.findings:
        lines.append("Human review prompts:")
        for index, finding in enumerate(report.findings, start=1):
            lines.extend([
                f"  {index}. line {finding.line} | {finding.code}",
                f"     Passage: {finding.sentence}",
                f"     Why it was surfaced: {finding.reason}",
                f"     Prompt: {finding.prompt}",
            ])
            if finding.phrase:
                lines.append(f"     Phrase: {finding.phrase}")
            if finding.count is not None:
                lines.append(f"     Occurrences/words: {finding.count}")
            if finding.citation_keys:
                lines.append(f"     Visible citation labels: {', '.join(finding.citation_keys)}")
    else:
        lines.append("Human review prompts: none for the implemented rules")
    return "\n".join(lines)


def deep_report_to_text(report: DeepAuditReport) -> str:
    lines = [report_to_text(report.base), "", "Visible citation cues:"]
    if report.citation_cues:
        for index, cue in enumerate(report.citation_cues, start=1):
            location = (
                f"line {cue.line}, sentence {cue.sentence_index}"
                if cue.sentence_index is not None
                else f"line {cue.line}, not associated with a sentence"
            )
            lines.append(
                f"  {index}. {location} | {cue.syntax} | labels: {', '.join(cue.keys)}"
            )
            lines.append(f"     Context: {cue.excerpt}")
    else:
        lines.append("  None recognized in the supported visible forms.")
    lines.extend([
        "",
        "This tool does not resolve bibliography entries or check whether a source supports a claim.",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review bilingual writing patterns and visible citation cues.")
    parser.add_argument("path", nargs="?", help="A UTF-8 text or LaTeX file. Reads standard input if omitted.")
    parser.add_argument("--json", action="store_true", help="Emit the structured review as JSON.")
    parser.add_argument("--deep", action="store_true", help="Include citation cues with source-line references.")
    parser.add_argument("--content-language", choices=("en", "fr"), default="en", help="Language of the document (default: en).")
    parser.add_argument("--clean", action="store_true", help="Print cleaned prose and exit.")
    args = parser.parse_args()
    if args.path:
        file_path = pathlib.Path(args.path)
        text = file_path.read_text(encoding="utf-8")
        path = str(file_path)
        source_format = file_path.suffix.casefold().lstrip(".")
    else:
        text = sys.stdin.read()
        path = "<stdin>"
        source_format = None
    if args.clean:
        print(strip_latex(text) if source_format in {"tex", "latex"} else normalize_whitespace(text))
        return 0
    report = (
        audit_text_deep(text, path, content_language=args.content_language, source_format=source_format)
        if args.deep
        else audit_text(text, path, content_language=args.content_language, source_format=source_format)
    )
    if args.json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=True))
    else:
        print(deep_report_to_text(report) if args.deep else report_to_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
