"""Bilingual repetition cues shared with the report review engine."""

from __future__ import annotations

from dataclasses import dataclass

from .review import audit_text_deep


@dataclass
class RepetitionReport:
    repeated_starts: list[tuple[str, int]]
    repeated_phrases: list[tuple[str, int]]

    @property
    def repeated_bigrams(self) -> list[tuple[str, int]]:
        """Compatibility alias; values are now three-word phrases, not bigrams."""
        return self.repeated_phrases


def analyze_repetition(
    text: str,
    *,
    start_width: int = 2,
    limit: int = 15,
    content_language: str = "en",
    source_format: str | None = None,
) -> RepetitionReport:
    """Return repeated sentence starts and phrases with language-aware tokens."""
    report = audit_text_deep(
        text,
        "<text>",
        content_language=content_language,
        source_format=source_format,
    )
    starts: list[tuple[str, int]] = []
    phrases: list[tuple[str, int]] = []
    for finding in report.findings:
        if finding.code == "repeated_sentence_start" and finding.phrase:
            words = finding.phrase.split()
            if start_width <= 1:
                phrase = " ".join(words[:1])
            else:
                phrase = " ".join(words[:start_width])
            starts.append((phrase, finding.count or len(finding.occurrences)))
        elif finding.code == "repeated_phrase" and finding.phrase:
            phrases.append((finding.phrase, finding.count or len(finding.occurrences)))
    return RepetitionReport(starts[:limit], phrases[:limit])
