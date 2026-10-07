#!/usr/bin/env python3
"""Run the authored bilingual cue challenge set without network access."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rapport_auditor.audit import audit_text_deep


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "examples" / "evaluation" / "cue-challenges.json"
RULE_CODES = (
    "repeated_sentence_start",
    "repeated_phrase",
    "long_sentence",
    "dense_sentence",
    "formulaic_phrase",
    "claim_needs_source",
    "citation_context_prompt",
)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def evaluate(
    dataset: Path = DEFAULT_DATASET,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("The evaluation dataset must be a non-empty JSON array.")

    rows: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    )
    citation_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"expected": 0, "actual": 0})
    seen_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each challenge case must be an object.")
        case_id = case.get("id")
        language = case.get("language")
        text = case.get("text")
        source_format = case.get("source_format", "txt")
        expected = case.get("expected_codes")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise ValueError(f"Challenge case ID is missing or duplicated: {case_id!r}")
        seen_ids.add(case_id)
        if language not in {"en", "fr"} or not isinstance(text, str) or source_format not in {"txt", "tex"}:
            raise ValueError(f"{case_id}: language must be en/fr, source_format txt/tex, and text a string.")
        if not isinstance(expected, list) or any(code not in RULE_CODES for code in expected):
            raise ValueError(f"{case_id}: expected_codes contains an unknown cue code.")

        report = audit_text_deep(
            text,
            f"evaluation/{case_id}.{source_format}",
            content_language=language,
            source_format=source_format,
        )
        findings = _field(report, "findings")
        if not isinstance(findings, list):
            raise TypeError("DeepAuditReport.findings must be a list of structured findings.")
        actual = {_field(finding, "code") for finding in findings}
        if None in actual:
            raise TypeError(f"{case_id}: each finding must have a stable `code` field.")
        unexpected_codes = actual - set(RULE_CODES)
        if unexpected_codes:
            raise ValueError(f"{case_id}: unexpected finding codes: {sorted(unexpected_codes)}")

        expected_set = set(expected)
        for code in RULE_CODES:
            expected_present = code in expected_set
            actual_present = code in actual
            key = f"{language}:{code}"
            if expected_present and actual_present:
                confusion[key]["tp"] += 1
            elif expected_present:
                confusion[key]["fn"] += 1
            elif actual_present:
                confusion[key]["fp"] += 1
            else:
                confusion[key]["tn"] += 1
        citation_cues = _field(report, "citation_cues")
        if not isinstance(citation_cues, list):
            raise TypeError("DeepAuditReport.citation_cues must be a list.")
        expected_citation_count = case.get("expected_citation_count", 0)
        if not isinstance(expected_citation_count, int) or expected_citation_count < 0:
            raise ValueError(f"{case_id}: expected_citation_count must be a non-negative integer.")
        citation_totals[language]["expected"] += expected_citation_count
        citation_totals[language]["actual"] += len(citation_cues)
        mismatch: dict[str, Any] = {
            "id": case_id,
            "language": language,
            "expected": sorted(expected_set),
            "actual": sorted(actual),
        }
        expected_sentence_count = case.get("expected_sentence_count")
        expected_word_count = case.get("expected_word_count")
        if expected_sentence_count is not None and not isinstance(expected_sentence_count, int):
            raise ValueError(f"{case_id}: expected_sentence_count must be an integer.")
        if expected_word_count is not None and not isinstance(expected_word_count, int):
            raise ValueError(f"{case_id}: expected_word_count must be an integer.")
        base = _field(report, "base")
        actual_sentence_count = _field(base, "sentence_count")
        actual_word_count = _field(base, "word_count")
        if expected_sentence_count is not None and actual_sentence_count != expected_sentence_count:
            mismatch["expected_sentence_count"] = expected_sentence_count
            mismatch["actual_sentence_count"] = actual_sentence_count
        if expected_word_count is not None and actual_word_count != expected_word_count:
            mismatch["expected_word_count"] = expected_word_count
            mismatch["actual_word_count"] = actual_word_count
        if (
            actual != expected_set
            or len(citation_cues) != expected_citation_count
            or (expected_sentence_count is not None and actual_sentence_count != expected_sentence_count)
            or (expected_word_count is not None and actual_word_count != expected_word_count)
        ):
            if len(citation_cues) != expected_citation_count:
                mismatch["expected_citation_count"] = expected_citation_count
                mismatch["actual_citation_count"] = len(citation_cues)
            rows.append(mismatch)

    return rows, dict(confusion), dict(citation_totals)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    mismatches, confusion, citation_totals = evaluate(args.dataset)
    print("Synthetic challenge-set conformance counts (not real-world accuracy):")
    for key in sorted(confusion):
        counts = confusion[key]
        print(
            f"{key}: TP={counts['tp']} FP={counts['fp']} "
            f"FN={counts['fn']} TN={counts['tn']}"
        )
    for language in sorted(citation_totals):
        totals = citation_totals[language]
        print(f"{language}: visible citation cues expected={totals['expected']} actual={totals['actual']}")
    if mismatches:
        print("Case mismatches:")
        for mismatch in mismatches:
            print(json.dumps(mismatch, ensure_ascii=False, sort_keys=True))
        return 1
    print("All annotated synthetic challenge cases conformed to their expected cue sets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
