# Bilingual cue challenge set

`cue-challenges.json` contains short synthetic passages authored for this
repository on 2026-10-06. The passages describe fictional instruments, samples,
and trials. Citation keys and bracketed citations are invented placeholders.
No student draft, external paper excerpt, real measurement, or external source
was copied into this set, so it has no third-party text license or attribution
requirement.

`expected_codes` records the expected presence of a stable deterministic cue
under the current documented rule contract. Cases may set `source_format` to
`tex` so LaTeX syntax is evaluated as TeX rather than ordinary text. The
optional `expected_citation_count` records how many visible citation markers
the parser should surface. Empty arrays are deliberate
negative controls, including a normal technical sentence, a paraphrase of a
listed phrase, a below-threshold repetition case, a citation marker without an
empirical-reporting phrase, and an intentionally false sentence. The false
sentence is a capability limit control: the expected result is that the engine
does not detect its truth value.

The set is reserved for challenge evaluation and separate from the routine
unit-test fixture examples, but it is **not** a blind or independently
human-annotated evaluation corpus. The author designed the cases from the
same published rule contract being tested. Per-code counts therefore measure
implementation conformance on these examples only. They do not estimate
precision, recall, usefulness, or error rates for real academic writing.

To evaluate after installing the package, run:

```sh
python scripts/evaluate_language_cues.py
```

The evaluator reports per-language and per-code true/false positive/negative
counts and failing case IDs. It makes no network requests, performs no source
lookup, and writes no files.
