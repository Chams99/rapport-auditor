"""Bilingual, evidence-led prompts for reviewing academic prose.

The rules in this module identify visible wording patterns and citation
markers. They do not infer authorship, check factual truth, resolve a
bibliography, or measure writing quality.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .audit import (
    LATEX_DROP_ENVIRONMENTS,
    strip_latex,
)


SUPPORTED_LANGUAGES = {"en", "fr"}


@dataclass(frozen=True)
class Occurrence:
    sentence_index: int
    line: int


@dataclass(frozen=True)
class ReviewFinding:
    code: str
    category: str
    sentence: str
    sentence_index: int
    line: int
    reason: str
    prompt: str
    phrase: str | None = None
    count: int | None = None
    occurrences: list[Occurrence] = field(default_factory=list)
    citation_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CitationCue:
    syntax: str
    keys: list[str]
    line: int
    sentence_index: int
    excerpt: str


@dataclass
class AuditReport:
    path: str
    sentence_count: int
    word_count: int
    content_language: str
    flagged_sentence_count: int
    findings: list[ReviewFinding]
    citation_cues: list[CitationCue]
    notes: list[str]

    @property
    def flagged_sentences(self) -> list[ReviewFinding]:
        """Compatibility alias; entries are now localized human-review cues."""
        return self.findings


@dataclass
class DeepAuditReport:
    base: AuditReport
    findings: list[ReviewFinding]
    citation_cues: list[CitationCue]

    @property
    def citation_findings(self) -> list[ReviewFinding]:
        """Compatibility view for source-related prompts (there are no scores)."""
        return [item for item in self.findings if item.category == "source"]


@dataclass(frozen=True)
class _CitationSpan:
    start: int
    end: int
    syntax: str
    keys: tuple[str, ...]
    line: int
    marker: str


@dataclass(frozen=True)
class _Sentence:
    text: str
    analysis_text: str
    sentence_index: int
    line: int
    start: int
    end: int
    markers: tuple[str, ...]


_LATEX_CITATION_COMMANDS = {
    "cite", "citep", "citet", "citealp", "citealt", "citeauthor", "citeyear",
    "parencite", "textcite", "autocite", "footcite", "smartcite", "supercite",
}
_NARRATIVE_CITATION_COMMANDS = {
    r"\citet", r"\citealp", r"\citealt", r"\citeauthor", r"\textcite",
}
_CITE_KEY_RE = re.compile(r"@([\w:.+/-]+)", re.UNICODE)
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_CITATION_MARKER_RE = re.compile(r"\ue000RA-CITE-[A-Za-z0-9_-]+\ue001")
_BRACKETED_MARKER_RE = re.compile(r"\ue000RA-CITE-([A-Za-z0-9_-]+)\ue001")
_CITATION_PROMPTS = {
    "en": {
        "repeated_sentence_start": (
            "The same first two words begin at least three sentences.",
            "Check whether the repeated openings are intentional or would benefit from variation.",
        ),
        "repeated_phrase": (
            "This three-word phrase appears at least three times in the prose.",
            "Check whether each repetition is needed or whether a more specific term would help.",
        ),
        "long_sentence": (
            "This sentence contains at least 36 words.",
            "Would a split make one idea easier to follow? Keep the sentence if its structure is clear.",
        ),
        "dense_sentence": (
            "This sentence has at least 28 words and three or more clause punctuation marks.",
            "Consider whether the clauses are easy to follow or whether a split would help.",
        ),
        "formulaic_phrase": (
            "This familiar academic phrase appears in the sentence.",
            "Does the phrase add a specific point here, or could you state the point directly?",
        ),
        "claim_needs_source": (
            "This sentence reports a study result, data point, or observation.",
            "Check that the method or source is cited where your style expects it; this tool cannot verify the claim.",
        ),
        "citation_context_prompt": (
            "A visible citation cue appears alongside a reported result or observation.",
            "Check that the cited work supports this specific statement; this tool cannot resolve or evaluate the reference.",
        ),
    },
    "fr": {
        "repeated_sentence_start": (
            "Les deux mêmes premiers mots ouvrent au moins trois phrases.",
            "Vérifiez si ces débuts répétés sont voulus ou si une variation serait utile.",
        ),
        "repeated_phrase": (
            "Cette expression de trois mots apparaît au moins trois fois dans le texte.",
            "Vérifiez si chaque répétition est nécessaire ou si un terme plus précis aiderait.",
        ),
        "long_sentence": (
            "Cette phrase contient au moins 36 mots.",
            "La couper rendrait-elle une idée plus facile à suivre ? Gardez-la si sa structure est claire.",
        ),
        "dense_sentence": (
            "Cette phrase contient au moins 28 mots et trois signes de ponctuation entre propositions ou plus.",
            "Vérifiez si les propositions sont faciles à suivre ou si une coupure serait utile.",
        ),
        "formulaic_phrase": (
            "Cette formule académique courante apparaît dans la phrase.",
            "Apporte-t-elle une précision ici, ou pourriez-vous énoncer directement l’idée ?",
        ),
        "claim_needs_source": (
            "Cette phrase rapporte un résultat d’étude, des données ou une observation.",
            "Vérifiez que la méthode ou la source est citée selon les usages de votre discipline ; cet outil ne vérifie pas l’affirmation.",
        ),
        "citation_context_prompt": (
            "Une référence visible accompagne un résultat ou une observation rapportée.",
            "Vérifiez que la source citée étaye bien cette affirmation précise ; cet outil ne résout ni n’évalue la référence.",
        ),
    },
}

_FORMULAIC_PHRASES = {
    "en": (
        "it is worth noting that",
        "it should be noted that",
        "plays a crucial role in",
        "plays a pivotal role in",
    ),
    "fr": (
        "il convient de noter que",
        "il est important de noter que",
        "joue un rôle crucial dans",
        "joue un rôle essentiel dans",
    ),
}

_EMPIRICAL_MARKERS = {
    "en": (
        "the results show", "our findings show", "the data show", "the study found",
        "we observed", "the experiment demonstrates", "the survey found",
    ),
    "fr": (
        "les résultats montrent", "nos résultats montrent", "les données montrent",
        "l’étude a révélé", "nous avons observé", "l’expérience démontre", "l’enquête a révélé",
    ),
}

_STOP_WORDS = {
    "en": frozenset(
        "a an and are as at be been being by for from had has have he her hers him his i in "
        "into is it its me my of on or our ours she that the their theirs them they this those "
        "to was we were what when where which who will with you your yours not but if then than".split()
    ),
    "fr": frozenset(
        "à au aux avec ce ces dans de des du elle elles en et eux il ils je la le les leur leurs "
        "lui ma mais me même mes moi mon ne nos notre nous on ou par pas pour qu que quelle quelles "
        "quel quels qui sa sans se ses son sur ta te tes toi ton tu un une vos votre vous y est sont".split()
    ),
}

_ABBREVIATIONS = {
    "en": {"mr.", "mrs.", "ms.", "dr.", "prof.", "fig.", "eq.", "sec.", "p.", "pp.", "vs.", "cf."},
    "fr": {"m.", "mme.", "mlle.", "dr.", "pr.", "p.", "pp.", "cf.", "av."},
}
_SINGLE_LETTER_UNITS = frozenset("ACFGHJKLMNSTVWgms\u03a9")
_NUMBER_WITH_OPTIONAL_UNITS_RE = re.compile(
    r"\d(?:[\d.,\u00a0\u202f ]*\d)?"
    r"(?:\s*[A-Za-zµμΩ]+(?:\s*[*/·]\s*[A-Za-zµμΩ]+)*)?"
    r"(?:\s*[*/·])?\s*$"
)
_LOWERCASE_CONTINUATION_ABBREVIATION_RE = re.compile(
    r"(?<!\w)(?:etc\.|et\s+al\.)$", re.IGNORECASE | re.UNICODE
)


def _language(value: str) -> str:
    language = str(value or "en").casefold()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("content_language must be 'en' or 'fr'")
    return language


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text)
    return [unicodedata.normalize("NFC", match.group(0)).casefold() for match in _WORD_RE.finditer(normalized)]


def _matching_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized = re.sub(r"(?<=\w)’(?=\w)", "'", normalized)
    return normalized.casefold()


def _inline_verbatim_end(line: str, start: int) -> int | None:
    backslashes = 0
    cursor = start - 1
    while cursor >= 0 and line[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    if backslashes % 2:
        return None
    command = re.match(r"\\(verb|lstinline)(\*)?(?![A-Za-z])", line[start:])
    if not command:
        return None
    delimiter_index = start + len(command.group(0))
    if command.group(1) == "lstinline" and delimiter_index < len(line) and line[delimiter_index] == "[":
        after_options = _read_balanced(line, delimiter_index, "[", "]")
        if after_options is not None:
            delimiter_index = after_options
    if delimiter_index >= len(line) or line[delimiter_index].isspace():
        return None
    close = line.find(line[delimiter_index], delimiter_index + 1)
    return len(line) if close < 0 else close + 1


def _find_comment_start(line: str) -> int:
    index = 0
    while index < len(line):
        if line[index] == "\\":
            verbatim_end = _inline_verbatim_end(line, index)
            if verbatim_end is not None:
                index = verbatim_end
                continue
        if line[index] == "%":
            slashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slashes += 1
                cursor -= 1
            if slashes % 2 == 0:
                return index
        index += 1
    return len(line)


def _read_balanced(line: str, start: int, opening: str, closing: str) -> int | None:
    if start >= len(line) or line[start] != opening:
        return None
    depth = 0
    escaped = False
    for index in range(start, len(line)):
        char = line[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _find_unescaped(line: str, needle: str, start: int) -> int:
    cursor = start
    while True:
        found = line.find(needle, cursor)
        if found < 0:
            return -1
        backslashes = 0
        previous = found - 1
        while previous >= 0 and line[previous] == "\\":
            backslashes += 1
            previous -= 1
        if backslashes % 2 == 0:
            return found
        cursor = found + len(needle)


def _mask_tex_nonprose(line: str, math_state: dict[str, str]) -> str:
    """Mask inline math and verbatim spans before extracting prose citations."""
    visible = list(line)
    cursor = 0
    delimiter = math_state.get("math_delimiter")
    if delimiter:
        close = _find_unescaped(line, delimiter, 0)
        end = len(line) if close < 0 else close + len(delimiter)
        for index in range(0, end):
            if visible[index] not in "\r\n":
                visible[index] = " "
        cursor = end
        if close < 0:
            return "".join(visible)
        math_state.pop("math_delimiter", None)

    while cursor < len(line):
        if line[cursor] == "\\":
            verbatim_end = _inline_verbatim_end(line, cursor)
            if verbatim_end is not None:
                for index in range(cursor, verbatim_end):
                    if visible[index] not in "\r\n":
                        visible[index] = " "
                cursor = verbatim_end
                continue

            if (
                line.startswith(r"\[", cursor) and _find_unescaped(line, r"\[", cursor) == cursor
            ) or (
                line.startswith(r"\(", cursor) and _find_unescaped(line, r"\(", cursor) == cursor
            ):
                opening = line[cursor : cursor + 2]
                closing = r"\]" if opening == r"\[" else r"\)"
                close = _find_unescaped(line, closing, cursor + 2)
                end = len(line) if close < 0 else close + 2
                for index in range(cursor, end):
                    if visible[index] not in "\r\n":
                        visible[index] = " "
                cursor = end
                if close < 0:
                    math_state["math_delimiter"] = closing
                    break
                continue

        if line.startswith("$$", cursor) and _find_unescaped(line, "$$", cursor) == cursor:
            delimiter = "$$"
        elif line[cursor] == "$" and _find_unescaped(line, "$", cursor) == cursor:
            delimiter = "$"
        else:
            cursor += 1
            continue

        close = _find_unescaped(line, delimiter, cursor + len(delimiter))
        end = len(line) if close < 0 else close + len(delimiter)
        for index in range(cursor, end):
            if visible[index] not in "\r\n":
                visible[index] = " "
        cursor = end
        if close < 0:
            math_state["math_delimiter"] = delimiter
            break

    return "".join(visible)


def _latex_citation_spans(line: str, line_number: int, marker_prefix: str) -> list[_CitationSpan]:
    visible_end = len(line)  # TeX comments are removed by _source_lines only.
    spans: list[_CitationSpan] = []
    cursor = 0
    while cursor < visible_end:
        start = line.find("\\", cursor, visible_end)
        if start < 0:
            break
        match = re.match(r"\\([A-Za-z]+)(\*)?", line[start:visible_end])
        if not match:
            cursor = start + 1
            continue
        command = match.group(1)
        if command.casefold() not in _LATEX_CITATION_COMMANDS:
            cursor = start + len(match.group(0))
            continue
        position = start + len(match.group(0))
        option_count = 0
        while option_count < 2:
            while position < visible_end and line[position] in " \t":
                position += 1
            if position >= visible_end or line[position] != "[":
                break
            after_option = _read_balanced(line, position, "[", "]")
            if after_option is None:
                break
            position = after_option
            option_count += 1
        while position < visible_end and line[position] in " \t":
            position += 1
        after_group = _read_balanced(line, position, "{", "}")
        if after_group is None:
            cursor = start + len(match.group(0))
            continue
        key_text = line[position + 1 : after_group - 1]
        keys = tuple(dict.fromkeys(part.strip() for part in key_text.split(",") if part.strip()))
        if keys:
            spans.append(
                _CitationSpan(
                    start=start,
                    end=after_group,
                    syntax=f"\\{command}{'*' if match.group(2) else ''}",
                    keys=keys,
                    line=line_number,
                    marker=f"{marker_prefix}{line_number}-{len(spans)}\ue001",
                )
            )
            cursor = after_group
        else:
            cursor = start + len(match.group(0))
    return spans


def _other_citation_spans(line: str, line_number: int, marker_prefix: str, start_index: int) -> list[_CitationSpan]:
    visible_end = len(line)
    occupied: list[tuple[int, int]] = []
    spans: list[_CitationSpan] = []
    markdown = re.compile(r"\[(?=[^\]]*@)[^\]]*\]")
    numeric = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
    for match in markdown.finditer(line[:visible_end]):
        keys = tuple(dict.fromkeys(_CITE_KEY_RE.findall(match.group(0))))
        if not keys:
            continue
        spans.append(
            _CitationSpan(match.start(), match.end(), "markdown", keys, line_number, f"{marker_prefix}{line_number}-{start_index + len(spans)}\ue001")
        )
        occupied.append(match.span())
    for match in numeric.finditer(line[:visible_end]):
        if any(match.start() < end and match.end() > start for start, end in occupied):
            continue
        keys = tuple(part.strip() for part in re.split(r"[,;]", match.group(1)) if part.strip())
        spans.append(
            _CitationSpan(match.start(), match.end(), "bracket-number", keys, line_number, f"{marker_prefix}{line_number}-{start_index + len(spans)}\ue001")
        )
    author_date = re.compile(r"[\[(]([^()\[\]\n]{1,180})[\])]" )
    for match in author_date.finditer(line[:visible_end]):
        body = match.group(1)
        references: list[str] = []
        for item in re.split(r"\s*;\s*", body):
            item = item.strip()
            ref = re.match(
                r"([^,()]+?)\s*,\s*((?:19|20)\d{2}[a-z]?)\b",
                item,
                flags=re.IGNORECASE,
            )
            if ref:
                author = re.sub(r"\s+", " ", ref.group(1)).strip()
                if re.fullmatch(r"[\w .’'&-]{1,90}", author, re.UNICODE):
                    references.append(f"{author}, {ref.group(2)}")
        if references:
            spans.append(
                _CitationSpan(
                    match.start(), match.end(), "author-date", tuple(references), line_number,
                    f"{marker_prefix}{line_number}-{start_index + len(spans)}\ue001",
                )
            )
    narrative = re.compile(
        r"(?<!\w)([A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ’'.-]*(?:\s+(?:et\s+al\.?|and\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ’'.-]*|&\s*[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ’'.-]*))?)\s*\(((?:19|20)\d{2}[a-z]?)\)",
        re.UNICODE,
    )
    for match in narrative.finditer(line[:visible_end]):
        year_open = match.start(2) - 1
        spans.append(
            _CitationSpan(
                year_open, match.end(), "author-date", (f"{match.group(1)}, {match.group(2)}",), line_number,
                f"{marker_prefix}{line_number}-{start_index + len(spans)}\ue001",
            )
        )
    url_re = re.compile(r"https?://[^\s<>\]\[(){}]+", re.IGNORECASE)
    doi_re = re.compile(r"(?<![\w/])doi:\s*(10\.\d{4,9}/[^\s<>\]\[(){}]+)", re.IGNORECASE)
    for match in url_re.finditer(line[:visible_end]):
        value = match.group(0).rstrip(".,;:!?\u00a0\u202f")
        if value:
            spans.append(
                _CitationSpan(match.start(), match.start() + len(value), "url", (value,), line_number,
                              f"{marker_prefix}{line_number}-{start_index + len(spans)}\ue001")
            )
    for match in doi_re.finditer(line[:visible_end]):
        spans.append(
            _CitationSpan(match.start(), match.end(), "doi", (match.group(1).rstrip(".,;:!?"),), line_number,
                          f"{marker_prefix}{line_number}-{start_index + len(spans)}\ue001")
        )
    return spans


def _citation_spans(line: str, line_number: int, marker_prefix: str) -> list[_CitationSpan]:
    latex = _latex_citation_spans(line, line_number, marker_prefix)
    occupied = [(span.start, span.end) for span in latex]
    others = _other_citation_spans(line, line_number, marker_prefix, len(latex))
    spans = latex + [
        span for span in others
        if not any(span.start < end and span.end > start for start, end in occupied)
    ]
    return sorted(spans, key=lambda span: span.start)


def _source_lines(text: str, is_tex: bool, marker_prefix: str) -> tuple[list[str], list[_CitationSpan]]:
    lines = text.splitlines()
    if not lines and text == "":
        return [], []
    processed: list[str] = []
    citations: list[_CitationSpan] = []
    dropped_environment: str | None = None
    math_state: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        if is_tex and dropped_environment:
            if re.search(rf"\\end\{{{re.escape(dropped_environment)}\}}", raw_line):
                dropped_environment = None
            processed.append("")
            continue
        if is_tex:
            start_env = re.search(r"\\begin\{([^}]+)\}", raw_line)
            if start_env and start_env.group(1) in LATEX_DROP_ENVIRONMENTS:
                env = start_env.group(1)
                end_match = re.search(rf"\\end\{{{re.escape(env)}\}}", raw_line[start_env.end() :])
                if not end_match:
                    dropped_environment = env
                    processed.append("")
                    continue
                raw_line = raw_line[: start_env.start()] + " " + raw_line[start_env.end() + end_match.end() :]
        comment_start = _find_comment_start(raw_line) if is_tex else len(raw_line)
        source_for_scan = raw_line[:comment_start]
        if is_tex:
            prose_for_scan = _mask_tex_nonprose(source_for_scan, math_state)
            spans = _citation_spans(prose_for_scan, line_number, marker_prefix)
            citations.extend(spans)
            visible = prose_for_scan
            for span in reversed(spans):
                visible = visible[: span.start] + f" {span.marker} " + visible[span.end :]
            cleaned = strip_latex(visible)
        else:
            spans = _other_citation_spans(source_for_scan, line_number, marker_prefix, 0)
            citations.extend(spans)
            visible = source_for_scan
            for span in reversed(spans):
                visible = visible[: span.start] + f" {span.marker} " + visible[span.end :]
            cleaned = re.sub(r"\s+", " ", visible).strip()
        processed.append(cleaned)
    return processed, citations


def _starts_sentence(text: str, punctuation_end: int, language: str) -> int | None:
    period_index = punctuation_end - 1
    if period_index >= 0 and text[period_index] == ".":
        previous = text[period_index - 1] if period_index else ""
        following = text[period_index + 1] if period_index + 1 < len(text) else ""
        if previous.isdigit() and following.isdigit():
            return None
        context_start = max(0, punctuation_end - 48)
        context = text[context_start:punctuation_end]
        single_letter = re.search(r"(?<!\w)([^\W\d_])\.$", context, re.UNICODE)
        if single_letter:
            prefix = context[: single_letter.start(1)].rstrip()
            unit_prefix = prefix[:-1].rstrip() if prefix.endswith("°") else prefix
            is_degree_unit = (
                prefix.endswith("°")
                and single_letter.group(1).casefold() in {"c", "f"}
                and _NUMBER_WITH_OPTIONAL_UNITS_RE.search(unit_prefix) is not None
            )
            is_numeric_unit = (
                single_letter.group(1) in _SINGLE_LETTER_UNITS
                and _NUMBER_WITH_OPTIONAL_UNITS_RE.search(prefix) is not None
            )
            if not (is_degree_unit or is_numeric_unit):
                return None
        match = re.search(r"(?<!\w)([^\W\d_]+\.)$", context, re.UNICODE)
        if match and match.group(1).casefold() in _ABBREVIATIONS[language]:
            return None
    position = punctuation_end
    while position < len(text) and text[position] in "\"'’”»)]}":
        position += 1
    while position < len(text):
        gap_start = position
        while position < len(text) and text[position].isspace():
            position += 1
        marker = _CITATION_MARKER_RE.match(text, position)
        if marker:
            position = marker.end()
            continue
        if position == gap_start:
            return None
        while position < len(text) and text[position] in "\"'“‘«([{":
            position += 1
        break
    if position >= len(text):
        return None
    first = text[position]
    context_start = max(0, punctuation_end - 48)
    context = text[context_start:punctuation_end]
    if first.islower() and _LOWERCASE_CONTINUATION_ABBREVIATION_RE.search(context):
        return None
    if first.isalpha() or first.isdigit():
        return position
    return None


def _sentence_spans(
    text: str,
    marker_prefix: str,
    language: str,
    narrative_citation_markers: set[str] | None = None,
) -> list[tuple[str, int, int, tuple[str, ...]]]:
    if not text.strip():
        return []
    boundaries: list[int] = []
    for index, char in enumerate(text):
        if char not in ".!?…":
            continue
        marker_match = _CITATION_MARKER_RE.match(text, index + 1)
        if marker_match:
            continue
        cursor = index + 1
        while cursor < len(text) and text[cursor] in ".!?…":
            cursor += 1
        boundary_end = cursor
        while boundary_end < len(text) and text[boundary_end] in "\"'’”»)]}":
            boundary_end += 1
        if _starts_sentence(text, cursor, language) is not None:
            # A proximate citation cue stays with the preceding statement; this
            # does not establish support. Explicit narrative commands remain with the next one.
            citation_end = boundary_end
            while citation_end < len(text):
                marker_position = citation_end
                while marker_position < len(text) and text[marker_position].isspace():
                    marker_position += 1
                marker = _CITATION_MARKER_RE.match(text, marker_position)
                if not marker:
                    break
                marker_value = marker.group(0)
                if narrative_citation_markers and marker_value in narrative_citation_markers:
                    break
                citation_end = marker.end()
            boundary_end = citation_end
            boundaries.append(boundary_end)
    for match in re.finditer(r"\n\s*\n+", text):
        if match.start() > 0 and match.end() < len(text):
            boundaries.append(match.start())
            boundaries.append(match.end())
    boundaries = sorted(set(boundaries))
    segments: list[tuple[str, int, int, tuple[str, ...]]] = []
    start = 0
    for boundary in boundaries + [len(text)]:
        if boundary < start:
            continue
        raw = text[start:boundary].strip()
        if raw and _tokens(_CITATION_MARKER_RE.sub(" ", raw)):
            leading = len(text[start:boundary]) - len(text[start:boundary].lstrip())
            absolute_start = start + leading
            markers = tuple(_CITATION_MARKER_RE.findall(raw))
            segments.append((raw, absolute_start, boundary, markers))
        start = boundary
    return segments


def _line_for_offset(text: str, offset: int) -> int:
    # Kept as a compatibility utility; the hot path uses a precomputed index.
    return text.count("\n", 0, max(0, offset)) + 1


def _display_sentence(text: str, marker_map: dict[str, _CitationSpan]) -> str:
    def replace(match: re.Match[str]) -> str:
        span = marker_map.get(match.group(0))
        if not span:
            return "[citation]"
        return "[citation: " + ", ".join(span.keys) + "]"
    return _CITATION_MARKER_RE.sub(replace, text).strip()


def _phrase_matches(sentence: str, phrases: Iterable[str]) -> list[str]:
    lowered = _matching_text(sentence)
    matches = []
    for phrase in phrases:
        normalized_phrase = _matching_text(phrase)
        pattern = r"(?<!\w)" + re.escape(normalized_phrase) + r"(?!\w)"
        for match in re.finditer(pattern, lowered, re.UNICODE):
            quoted = False
            for opening, closing in (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"), ("«", "»")):
                previous_open = lowered.rfind(opening, 0, match.start())
                previous_close = lowered.rfind(closing, 0, match.start())
                next_close = lowered.find(closing, match.end())
                enclosed = (previous_open >= 0 and next_close >= 0) if opening == closing else (previous_open > previous_close and next_close >= 0)
                if enclosed:
                    quoted = True
                    break
            if quoted:
                continue
            matches.append(phrase)
            break
    return matches


def _make_finding(
    code: str,
    sentence: _Sentence,
    language: str,
    *,
    phrase: str | None = None,
    count: int | None = None,
    occurrences: list[Occurrence] | None = None,
    citation_keys: list[str] | None = None,
) -> ReviewFinding:
    reason, prompt = _CITATION_PROMPTS[language][code]
    if phrase and code == "formulaic_phrase":
        reason = ("The familiar phrase ‘" + phrase + "’ appears in the sentence." if language == "en"
                  else "La formule courante « " + phrase + " » apparaît dans la phrase.")
    if code == "dense_sentence":
        text_without_citations = re.sub(r"\[citation:[^\]]*\]", " ", sentence.text, flags=re.I)
        punctuation_count = len(re.findall(r"[,;:—–]", text_without_citations))
        reason = (
            f"This sentence has at least 28 words and {punctuation_count} clause punctuation marks (commas, semicolons, colons or dashes)."
            if language == "en"
            else f"Cette phrase contient au moins 28 mots et {punctuation_count} signes de ponctuation entre propositions (virgules, points-virgules, deux-points ou tirets)."
        )
    return ReviewFinding(
        code=code,
        category="source" if code in {"claim_needs_source", "citation_context_prompt"} else "writing",
        sentence=sentence.text,
        sentence_index=sentence.sentence_index,
        line=sentence.line,
        reason=reason,
        prompt=prompt,
        phrase=phrase,
        count=count,
        occurrences=occurrences or [Occurrence(sentence.sentence_index, sentence.line)],
        citation_keys=citation_keys or [],
    )


def _build_findings(sentences: list[_Sentence], language: str, citation_by_sentence: dict[int, list[CitationCue]]) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    starts: dict[tuple[str, ...], list[_Sentence]] = defaultdict(list)
    phrase_occurrences: dict[tuple[str, ...], list[_Sentence]] = defaultdict(list)
    for sentence in sentences:
        words = _tokens(_CITATION_MARKER_RE.sub(" ", sentence.analysis_text))
        if len(words) >= 2:
            starts[tuple(words[:2])].append(sentence)
        for start in range(max(0, len(words) - 2)):
            phrase = tuple(words[start : start + 3])
            if sum(word not in _STOP_WORDS[language] for word in phrase) >= 2:
                phrase_occurrences[phrase].append(sentence)

    for phrase, occurrences in sorted(starts.items(), key=lambda item: min(s.sentence_index for s in item[1])):
        if len(occurrences) < 3:
            continue
        first = occurrences[0]
        findings.append(_make_finding(
            "repeated_sentence_start", first, language,
            phrase=" ".join(phrase), count=len(occurrences),
            occurrences=[Occurrence(item.sentence_index, item.line) for item in occurrences],
        ))

    for phrase, occurrences in sorted(phrase_occurrences.items(), key=lambda item: min(s.sentence_index for s in item[1])):
        if len(occurrences) < 3:
            continue
        first = occurrences[0]
        findings.append(_make_finding(
            "repeated_phrase", first, language,
            phrase=" ".join(phrase), count=len(occurrences),
            occurrences=[Occurrence(item.sentence_index, item.line) for item in occurrences],
        ))

    for sentence in sentences:
        words = _tokens(_CITATION_MARKER_RE.sub(" ", sentence.analysis_text))
        if len(words) >= 36:
            findings.append(_make_finding("long_sentence", sentence, language, count=len(words)))
        text_without_citations = re.sub(r"\[citation:[^\]]*\]", " ", sentence.analysis_text, flags=re.I)
        separators = len(re.findall(r"[,;:—–]", text_without_citations))
        if len(words) >= 28 and separators >= 3:
            findings.append(_make_finding("dense_sentence", sentence, language, count=len(words)))
        prose = _CITATION_MARKER_RE.sub(" ", sentence.analysis_text)
        for phrase in _phrase_matches(prose, _FORMULAIC_PHRASES[language]):
            findings.append(_make_finding("formulaic_phrase", sentence, language, phrase=phrase))

        empirical = _phrase_matches(prose, _EMPIRICAL_MARKERS[language])
        cues = citation_by_sentence.get(sentence.sentence_index, [])
        if empirical and cues:
            keys = list(dict.fromkeys(key for cue in cues for key in cue.keys))
            findings.append(_make_finding("citation_context_prompt", sentence, language, count=len(cues), citation_keys=keys))
        elif empirical:
            findings.append(_make_finding("claim_needs_source", sentence, language, phrase=empirical[0]))

    order = {
        "repeated_sentence_start": 0,
        "repeated_phrase": 1,
        "long_sentence": 2,
        "dense_sentence": 3,
        "formulaic_phrase": 4,
        "claim_needs_source": 5,
        "citation_context_prompt": 6,
    }
    return sorted(findings, key=lambda item: (item.sentence_index, order[item.code], item.phrase or ""))


def _analyze(text: str, path: str, content_language: str, source_format: str | None = None) -> tuple[AuditReport, list[_Sentence], list[CitationCue]]:
    language = _language(content_language)
    normalized_format = str(source_format or "").casefold().lstrip(".")
    latex_markup = bool(re.search(r"\\(?:begin|end|section|subsection|text[a-z]+|cite[a-z]*)\b", text or ""))
    if normalized_format and normalized_format not in {"txt", "tex"}:
        raise ValueError("source_format must be 'txt' or 'tex'")
    is_tex = normalized_format == "tex" if normalized_format else (
        str(path or "").casefold().endswith((".tex", ".latex")) or latex_markup
    )
    prefix = "\ue000RA-CITE-" + re.sub(r"[^A-Za-z0-9_-]", "", hex(id(text))[-8:]) + "-"
    while prefix in text:
        prefix += "X"
    cleaned_lines, citation_spans = _source_lines(text or "", is_tex, prefix)
    cleaned = "\n".join(cleaned_lines)
    span_by_marker = {span.marker: span for span in citation_spans}
    narrative_citation_markers = {
        span.marker
        for span in citation_spans
        if span.syntax.casefold().rstrip("*") in _NARRATIVE_CITATION_COMMANDS
    }
    raw_spans = _sentence_spans(
        cleaned,
        prefix,
        language,
        narrative_citation_markers=narrative_citation_markers,
    )
    line_starts = [0]
    line_starts.extend(index + 1 for index, char in enumerate(cleaned) if char == "\n")
    sentences: list[_Sentence] = []
    marker_sentence: dict[str, int] = {}
    for sentence_index, (raw_sentence, start, end, markers) in enumerate(raw_spans, start=1):
        public_sentence = _display_sentence(raw_sentence, span_by_marker)
        sentence = _Sentence(
            text=public_sentence,
            analysis_text=raw_sentence,
            sentence_index=sentence_index,
            line=bisect_right(line_starts, start),
            start=start,
            end=end,
            markers=markers,
        )
        sentences.append(sentence)
        for marker in markers:
            marker_sentence[marker] = sentence_index

    sentence_by_index = {item.sentence_index: item for item in sentences}
    citation_cues = [
        CitationCue(
            syntax=span.syntax,
            keys=list(span.keys),
            line=span.line,
            sentence_index=marker_sentence.get(span.marker, 1),
            excerpt=sentence_by_index.get(marker_sentence.get(span.marker, -1)).text if marker_sentence.get(span.marker, -1) in sentence_by_index else "",
        )
        for span in citation_spans
    ]
    citation_by_sentence: dict[int, list[CitationCue]] = defaultdict(list)
    for cue in citation_cues:
        citation_by_sentence[cue.sentence_index].append(cue)
    findings = _build_findings(sentences, language, citation_by_sentence)
    token_count = len(_tokens(_CITATION_MARKER_RE.sub(" ", cleaned)))
    note = (
        "Prompts use explicit wording patterns and visible citation markers. They do not evaluate factual accuracy, source quality, or bibliography completeness."
        if language == "en"
        else "Les indications reposent sur des formulations explicites et des repères visibles. Elles n’évaluent ni l’exactitude factuelle, ni la qualité des sources, ni l’exhaustivité de la bibliographie."
    )
    report = AuditReport(
        path=str(path or "<text>"),
        sentence_count=len(sentences),
        word_count=token_count,
        content_language=language,
        flagged_sentence_count=len({item.sentence_index for item in findings}),
        findings=findings,
        citation_cues=citation_cues,
        notes=[note],
    )
    return report, sentences, citation_cues


def audit_text(text: str, path: str = "<text>", *, content_language: str = "en", source_format: str | None = None) -> AuditReport:
    """Review visible writing cues; English remains the default content language."""
    report, _sentences, _cues = _analyze(text, path, content_language, source_format)
    return report


def audit_text_deep(text: str, path: str = "<text>", *, content_language: str = "en", source_format: str | None = None) -> DeepAuditReport:
    """Return the same review plus explicit citation cues and sentence locations."""
    report, _sentences, cues = _analyze(text, path, content_language, source_format)
    return DeepAuditReport(base=report, findings=report.findings, citation_cues=cues)


def extract_citation_findings(text: str, *, content_language: str = "en") -> tuple[int, list[ReviewFinding]]:
    """Compatibility helper returning a count and human-only source prompts."""
    report = audit_text_deep(text, "<text>.tex", content_language=content_language)
    source_findings = report.citation_findings
    return len(source_findings), source_findings
