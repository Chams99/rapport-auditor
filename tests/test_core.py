from pathlib import Path

from rapport_auditor.audit import audit_text, audit_text_deep, extract_citation_findings, split_sentences, strip_latex
from rapport_auditor.repetition import analyze_repetition
from rapport_auditor.revise import revise_text


def test_audit_plain_text_returns_metrics():
    text = (
        "This chapter presents the implemented platform. "
        "The system provides schema discovery, validation, orchestration, and hybrid retrieval. "
        "It achieved 95 percent accuracy in all cases without visible citation."
    )

    report = audit_text(text, "sample.txt")

    assert report.word_count > 0
    assert report.sentence_count >= 2
    assert isinstance(report.flagged_sentences, list)


def test_latex_is_stripped_for_analysis():
    text = r"\section{Intro} This chapter presents the platform. \textbf{Important result}."

    stripped = strip_latex(text)

    assert "\\section" not in stripped
    assert "Important result" in stripped


def test_repetition_accepts_arbitrary_text():
    text = (
        "The system works well in production today. "
        "The system responds quickly during tests. "
        "The system records data safely every time. "
        "Another sentence appears with enough words."
    )

    report = analyze_repetition(text)

    assert ("the system", 3) in report.repeated_starts


def test_revision_preview_preserves_inline_latex_and_does_not_require_file_write():
    text = r"This chapter presents the result with \textbf{important} notation."

    revised, edits = revise_text(text)

    assert r"\textbf{important}" in revised
    assert edits
    assert "This chapter describes" in revised


def test_revision_preserves_citations_references_and_urls_verbatim():
    text = (
        r"This chapter presents a result \cite{synthetic-key}, points to \ref{fig:synthetic}, "
        r"and links \url{https://example.invalid/source}."
    )

    revised, _ = revise_text(text)

    assert r"\cite{synthetic-key}" in revised
    assert r"\ref{fig:synthetic}" in revised
    assert r"\url{https://example.invalid/source}" in revised
    assert "This chapter describes a result" in revised


def test_revision_does_not_rewrite_verbatim_environment_contents():
    code = "This chapter presents a fictional output."
    text = (
        "\\begin{verbatim}\n"
        + code
        + "\n\\end{verbatim}\n\nThis chapter presents a fictional method."
    )

    revised, _ = revise_text(text)

    assert f"\\begin{{verbatim}}\n{code}\n\\end{{verbatim}}" in revised
    assert "This chapter describes a fictional method." in revised


def test_citation_cue_reports_only_visible_support_prompt_not_source_verification():
    fixture = Path(__file__).resolve().parents[1] / "examples" / "synthetic" / "citation_cues.tex"
    text = fixture.read_text(encoding="utf-8")

    finding_count, findings = extract_citation_findings(text)

    assert finding_count == 1
    assert len(findings) == 1
    assert findings[0].code == "citation_context_prompt"
    assert findings[0].citation_keys == ["synthetic-grouping-2026"]
    assert "supports this specific statement" in findings[0].prompt
    # The key is an invented fixture value: a visible citation cue prompts
    # human review, but the local engine does not resolve bibliography data.
    assert "synthetic-grouping-2026" in findings[0].sentence


def test_empty_and_unicode_inputs_do_not_crash_or_create_invalid_results():
    assert split_sentences("") == []

    report = audit_text_deep("École : déjà résumé. नमस्ते रिपोर्ट।", "synthetic.txt")

    assert report.base.word_count >= 0
    assert report.base.sentence_count >= 0
    assert isinstance(report.citation_findings, list)
    assert isinstance(report.findings, list)
    assert isinstance(report.citation_cues, list)


def test_revision_preserves_math_blocks_and_inline_math():
    inline = r"This chapter presents a value $x = \text{whereas}$."
    display = "\\begin{equation}\n\\text{whereas} = 1\n\\end{equation}"

    revised_inline, _ = revise_text(inline)
    revised_display, _ = revise_text(display)

    assert r"$x = \text{whereas}$" in revised_inline
    assert "This chapter describes a value" in revised_inline
    assert revised_display == display


def test_revision_preserves_citation_options_and_nested_latex_arguments():
    citation = r"This chapter presents result \citep[whereas][p. 2]{synthetic-key}."
    nested = r"This chapter presents result \textbf{whereas \emph{it works}}."

    revised_citation, _ = revise_text(citation)
    revised_nested, _ = revise_text(nested)

    assert r"\citep[whereas][p. 2]{synthetic-key}" in revised_citation
    assert r"\textbf{whereas \emph{it works}}" in revised_nested
    assert "This chapter describes result" in revised_citation
    assert "This chapter describes result" in revised_nested


def test_revision_preserves_latex_comments_but_edits_following_prose():
    text = "This chapter presents a method. % This chapter presents a comment.\n"

    revised, _ = revise_text(text)

    assert revised == "This chapter describes a method. % This chapter presents a comment.\n"


def test_revision_does_not_confuse_literal_mask_like_text_with_protected_latex():
    text = (
        r"Literal @@LATEX0@@ stays unchanged beside \textbf{whereas}. "
        r"This chapter presents the value $x = \text{whereas}$."
    )

    revised, edits = revise_text(text)

    assert edits
    assert "Literal @@LATEX0@@ stays unchanged" in revised
    assert r"\textbf{whereas}" in revised
    assert r"$x = \text{whereas}$" in revised
    assert "This chapter describes the value" in revised


def test_tex_linebreak_and_escaped_commands_do_not_open_false_protected_spans():
    text = (
        r"\\[2pt] This chapter presents a value \verb|\cite{inline-fake}|."
        "\n"
        r"This chapter presents a value \[x = \cite{math-fake}\] and \cite{real-key}."
        "\n"
        r"This chapter presents a value \\verb|\cite{escaped-fake}|."
    )

    revised, edits = revise_text(text, content_language="en")
    report = audit_text_deep(text, "synthetic.tex", content_language="en", source_format="tex")

    assert len(edits) == 3
    assert r"\\[2pt] This chapter describes a value \verb|\cite{inline-fake}|." in revised
    assert r"This chapter describes a value \[x = \cite{math-fake}\] and \cite{real-key}." in revised
    assert r"This chapter describes a value \\verb|\cite{escaped-fake}|." in revised
    # The escaped command is ordinary prose after a TeX line break, so its
    # citation is visible; only the real inline-verbatim and math citations are masked.
    assert [cue.keys for cue in report.citation_cues] == [["real-key"], ["escaped-fake"]]
