from __future__ import annotations

from scripts.evaluate_language_cues import evaluate


def test_authored_bilingual_challenge_cases_match_the_documented_cue_contract():
    mismatches, _confusion_counts, _citation_totals = evaluate()

    assert mismatches == []
