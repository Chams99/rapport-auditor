# Language cue evaluation

**Recorded 2026-10-06.** Rapport Auditor is a deterministic English/French editing aid. Its checks count patterns and surface visible citation-shaped text; they do not classify writing quality, authorship, plagiarism, truth, or source adequacy.

## What was exercised

The offline evaluator is `scripts/evaluate_language_cues.py`; its fictional, hand-authored inputs are in [`examples/evaluation/cue-challenges.json`](../examples/evaluation/cue-challenges.json). It currently contains 47 cases (27 English, 20 French), with expected cue sets and visible-citation counts. The cases cover all seven stable finding codes, positive examples and threshold/paraphrase negatives, repeated year/university lines, ordinary technical and intentionally false factual prose, empirical phrases in quotations and negations, method descriptions, abbreviation/decimal punctuation, TeX comments and inline/display math, nested/multiple TeX citations, author-date forms, URLs/DOIs, ASCII/curly apostrophes, and French NBSP/narrow-NBSP typography. A few cases also pin source sentence/word counts so header-like content cannot silently disappear.

The labels are regression expectations based on the documented narrow cue rules. They were built to exercise those rules and revised while implementing the current contract; this is **not** a held-out benchmark, independent annotation study, or representative sample of academic writing. The reported confusion counts are exact conformance counts over these cases, not real-world precision, recall, or an accuracy estimate.

Latest run:

```text
en:citation_context_prompt: TP=6 FP=0 FN=0 TN=21
en:claim_needs_source: TP=4 FP=0 FN=0 TN=23
en:dense_sentence: TP=1 FP=0 FN=0 TN=26
en:formulaic_phrase: TP=1 FP=0 FN=0 TN=26
en:long_sentence: TP=1 FP=0 FN=0 TN=26
en:repeated_phrase: TP=2 FP=0 FN=0 TN=25
en:repeated_sentence_start: TP=3 FP=0 FN=0 TN=24
fr:citation_context_prompt: TP=3 FP=0 FN=0 TN=17
fr:claim_needs_source: TP=3 FP=0 FN=0 TN=17
fr:dense_sentence: TP=1 FP=0 FN=0 TN=19
fr:formulaic_phrase: TP=1 FP=0 FN=0 TN=19
fr:long_sentence: TP=1 FP=0 FN=0 TN=19
fr:repeated_phrase: TP=2 FP=0 FN=0 TN=18
fr:repeated_sentence_start: TP=3 FP=0 FN=0 TN=17
en: visible citation cues expected=9 actual=9
fr: visible citation cues expected=5 actual=5
All annotated synthetic challenge cases conformed to their expected cue sets.
```

## Independent targeted regression review — 2026-10-07

A separate reliability review identified four narrow behavior defects around Celsius unit punctuation, lowercase sentence starts, citations immediately after terminal punctuation, and capitalization in sentence-initial phrase substitutions. `tests/test_review_regressions.py` now contains 18 targeted cases for those contracts and nearby controls: English/French sentence starts; `Dr.`, initials, `e.g.`, `et al.`, and decimal preservation; citation placement before and after punctuation; lowercase continuations; narrative author-date prefixes that belong to the following sentence; case-preserving English/French rewrites; and nested LaTeX, math, and comments.

These cases were specified from a separate reliability review and are maintained as regression tests, outside the 47-case synthetic cue evaluator above. They establish only that these concrete examples follow the stated behavior; they are not a representative writing sample, independent annotation study, held-out benchmark, or accuracy estimate. A visible citation cue remains a proximity prompt and never establishes that a source supports a claim.

On 2026-10-07, the focused regression file passed all 18 cases with Python 3.10.3 and Python 3.12.14. The complete pytest suite passed 150 tests with 3 environment-dependent skips on both versions. The existing 47-case evaluator conformed to its expected cue sets. Ruff passed and `pip check` was clean in both environments. The skips were the two POSIX worker resource-limit tests and the live Redis integration test; this Windows run does not replace Linux worker, Redis, container, HTTPS, or load verification documented in [the production runbook](PRODUCTION.md).

To reproduce offline:

```powershell
.venv\Scripts\python.exe scripts\evaluate_language_cues.py
```

## Practical interpretation

- Repeated openings and repeated three-word phrases are the most mechanical cues. A hit means a matching pattern crossed a configured count threshold; it does not establish that the repetition is undesirable.
- Length and density use fixed word/punctuation thresholds. They can miss a difficult sentence below a threshold and flag a long sentence that is clear in context.
- Formulaic wording and empirical-reporting prompts use a small exact English/French phrase list. Paraphrases and other languages are outside that list. A method sentence such as “We observed …” can still be ambiguous, so the result asks for a human check.
- Citation cues report visible TeX, Markdown, bracket-number, author-date, URL, or DOI syntax where recognized. Keys and addresses are not opened, resolved against a bibliography, or checked for source identity, relevance, or support. A cue beside a listed empirical phrase is a prompt to inspect the source, not a finding that it supports the sentence.
- Revision suggestions use a small set of explicit phrase substitutions. Review each change in context, especially for technical terms, quotations, or meanings where the replacement is not equivalent.
- Text processing is local to the selected installation, but a public deployment sends submitted text to that server. It is designed not to retain document content; this application-level behavior does not make claims about host memory, crash dumps, browser/device state, or a hosting provider's infrastructure retention.

There is no labeled corpus of real English/French student or research writing, adjudicated false-positive review, held-out evaluation, calibrated threshold study, or source-resolution test. Before claiming measured reliability, create a consented, privacy-reviewed, licensed evaluation set with independent annotators, disagreement adjudication, separate tuning and held-out partitions, and per-language/per-cue error analysis. Keep source verification and factuality out of claims unless a separately scoped, evidence-based verification system is actually built and evaluated.
