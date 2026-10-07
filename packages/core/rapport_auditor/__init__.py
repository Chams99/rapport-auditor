"""Bilingual writing-pattern review and revision helpers for Rapport Auditor."""

from .audit import audit_text, audit_text_deep
from .revise import revise_text
from .repetition import analyze_repetition
from .review import CitationCue, Occurrence, ReviewFinding

__all__ = [
    "CitationCue",
    "Occurrence",
    "ReviewFinding",
    "analyze_repetition",
    "audit_text",
    "audit_text_deep",
    "revise_text",
]
