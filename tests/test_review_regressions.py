"""Independent edge-case regressions for sentence and citation review rules."""

import pytest

from rapport_auditor.audit import audit_text, audit_text_deep, split_sentences
from rapport_auditor.revise import revise_text


@pytest.mark.parametrize(
    ("text", "language", "expected_sentences"),
    [
        (
            "Dr. Noor calibrated the sensor at 2.5 °C. Samples were sealed.",
            "en",
            [
                "Dr. Noor calibrated the sensor at 2.5 °C.",
                "Samples were sealed.",
            ],
        ),
        (
            "Dr. J. Noor cited e.g. a comparison by Smith et al. who reported a stable value. "
            "The samples were sealed.",
            "en",
            [
                "Dr. J. Noor cited e.g. a comparison by Smith et al. who reported a stable value.",
                "The samples were sealed.",
            ],
        ),
        (
            "The results show a change. the next sample remained stable.",
            "en",
            [
                "The results show a change.",
                "the next sample remained stable.",
            ],
        ),
        (
            "The results show a change? the next sample remained stable! the third sample was sealed.",
            "en",
            [
                "The results show a change?",
                "the next sample remained stable!",
                "the third sample was sealed.",
            ],
        ),
        (
            "Les résultats montrent un changement. le second échantillon est resté stable.",
            "fr",
            [
                "Les résultats montrent un changement.",
                "le second échantillon est resté stable.",
            ],
        ),
    ],
)
def test_sentence_boundaries_keep_unit_and_abbreviation_controls(
    text: str, language: str, expected_sentences: list[str]
) -> None:
    report = audit_text(text, content_language=language)

    assert report.sentence_count == len(expected_sentences)
    assert split_sentences(text, content_language=language) == expected_sentences


@pytest.mark.parametrize(
    ("text", "language", "expected_key"),
    [
        (
            "The results show a change in the fictional sample [Smith, 2024]. "
            "The next sample was sealed.",
            "en",
            "Smith, 2024",
        ),
        (
            "The results show a change in the fictional sample. [Smith, 2024] "
            "The next sample was sealed.",
            "en",
            "Smith, 2024",
        ),
        (
            "The results show a change in the fictional sample. [Smith, 2024] "
            "the next sample was sealed.",
            "en",
            "Smith, 2024",
        ),
        (
            "Les résultats montrent une variation. [Martin, 2024] "
            "le second échantillon a été scellé.",
            "fr",
            "Martin, 2024",
        ),
    ],
)
def test_adjacent_visible_citation_is_mapped_to_reported_result(
    text: str, language: str, expected_key: str
) -> None:
    report = audit_text_deep(text, content_language=language)

    assert report.base.sentence_count == 2
    assert len(report.citation_cues) == 1
    cue = report.citation_cues[0]
    assert cue.sentence_index == 1
    assert expected_key in cue.keys
    assert expected_key in cue.excerpt

    prompts = [
        finding
        for finding in report.findings
        if finding.code == "citation_context_prompt"
    ]
    assert len(prompts) == 1
    assert prompts[0].sentence_index == 1
    assert expected_key in prompts[0].citation_keys


@pytest.mark.parametrize(
    ("text", "language", "expected_key"),
    [
        (
            "The results show a change. Smith (2024) reported that the next sample remained stable.",
            "en",
            "Smith, 2024",
        ),
        (
            "Les résultats montrent un changement. Martin (2024) indique que le second échantillon est resté stable.",
            "fr",
            "Martin, 2024",
        ),
    ],
)
def test_narrative_author_date_citation_stays_with_following_sentence(
    text: str, language: str, expected_key: str
) -> None:
    report = audit_text_deep(text, content_language=language)

    assert report.base.sentence_count == 2
    assert len(report.citation_cues) == 1
    cue = report.citation_cues[0]
    assert cue.sentence_index == 2
    assert expected_key in cue.keys
    assert expected_key in cue.excerpt
    assert not any(f.code == "citation_context_prompt" for f in report.findings)


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        (
            "In order to estimate the fictional value, the team measured one sample.",
            "en",
            "To estimate the fictional value, the team measured one sample.",
        ),
        (
            "The team measured one sample in order to estimate the fictional value.",
            "en",
            "The team measured one sample to estimate the fictional value.",
        ),
        (
            "IN ORDER TO ESTIMATE THE FICTIONAL VALUE, THE TEAM MEASURED ONE SAMPLE.",
            "en",
            "TO ESTIMATE THE FICTIONAL VALUE, THE TEAM MEASURED ONE SAMPLE.",
        ),
        (
            "Afin de vérifier le dispositif fictif, l’équipe a répété la mesure.",
            "fr",
            "Pour vérifier le dispositif fictif, l’équipe a répété la mesure.",
        ),
        (
            "L’équipe a répété la mesure afin de vérifier le dispositif fictif.",
            "fr",
            "L’équipe a répété la mesure pour vérifier le dispositif fictif.",
        ),
        (
            "AFIN DE VÉRIFIER LE DISPOSITIF FICTIF, L’ÉQUIPE A RÉPÉTÉ LA MESURE.",
            "fr",
            "POUR VÉRIFIER LE DISPOSITIF FICTIF, L’ÉQUIPE A RÉPÉTÉ LA MESURE.",
        ),
    ],
)
def test_revision_preserves_case_for_purpose_phrase(
    text: str, language: str, expected: str
) -> None:
    revised, edits = revise_text(text, content_language=language)

    assert revised == expected
    assert len(edits) == 1


def test_revision_still_protects_nested_latex_math_and_comments() -> None:
    text = (
        r"In order to estimate the value, preserve \textbf{In order to keep "
        r"\emph{the original wording}} and $x = \text{In order to remain}$;"
        "\n% In order to stay unchanged in a comment.\n"
    )

    revised, _edits = revise_text(text, content_language="en", source_format="tex")

    assert revised == (
        r"To estimate the value, preserve \textbf{In order to keep "
        r"\emph{the original wording}} and $x = \text{In order to remain}$;"
        "\n% In order to stay unchanged in a comment.\n"
    )
