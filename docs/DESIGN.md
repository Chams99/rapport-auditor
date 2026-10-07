# Rapport Auditor: interaction and visual specification

This document turns the research in [RESEARCH.md](RESEARCH.md) into a concrete direction for the modernization. It is a review reference for the HTML, CSS, localization, and server-rendered states.

## Product promise

Rapport Auditor is a focused draft-review workspace. It helps a student spot repetitive wording, dense passages, and claims worth checking against sources. The student owns every decision and keeps the original file.

Use “review,” “signal,” “pattern,” “source-check prompt,” and “suggested revision.” Do not use “detector,” “proof,” “verified,” “confidence,” or “submission ready.” Explain the key limits at the point of use: the rules are narrow and language-specific (English or French), not a general grammar or fact checker; citation references are not resolved; and no source is checked for truth or relevance. The synthetic fixtures establish rule conformance for those examples only, not real-world reliability.

## Visual direction

Build a quiet editorial workspace around the manuscript. Use a warm paper canvas, dark ink for the main reading area, indigo for the primary action and navigation focus, and one restrained proofing mark to connect a finding to its excerpt. This gives the app a distinct academic-review character without imitating a government design system or turning the page into a stack of identical SaaS cards.

Candidate semantic tokens, to verify against the final composited states:

| Purpose | Candidate | Use |
| --- | --- | --- |
| `canvas` | `#F7F5EF` | Main page background. |
| `surface` | `#FFFFFF` | Editor, result sheet, and raised field surfaces. |
| `ink` | `#171B2C` | Headings and primary text. |
| `muted-text` | `#51596B` | Secondary text, source details, hints. |
| `action` | `#393584` | Main button, links, active navigation, proofing marker. |
| `control-boundary` | `#676F84` | Input borders and important control outlines. |
| `separator` | `#D6D8DD` | Non-interactive divider lines only. |
| `warning-text` / `warning-surface` | `#8C4A0F` / `#FFF6E6` | A review cue that needs a human check. |
| `error-text` / `error-surface` | `#9F2D3A` / `#FCEDEF` | User-correctable errors. |
| `success-text` / `success-surface` | `#1C5D49` / `#E8F5EF` | Confirmations. |

These candidate pairs have at least 4.5:1 text contrast in the stated pairings. Check actual text, hover, selected, disabled, focus, overlay, and dark-surface states before treating the palette as final. Keep the distinction between a control boundary and a decorative separator: the lighter separator is not suitable as the only edge around an input. WCAG 2.2 requires minimum contrast for text and meaningful graphical controls ([WCAG 2.2](https://www.w3.org/TR/WCAG22/)).

Use a system sans-serif for controls and interface labels. A system serif can distinguish the app title and manuscript excerpts while staying local and avoiding third-party font requests. Keep prose lines around 65–75 characters, use generous line height in the editor, and reserve a monospace face for diffs or technical LaTeX details. Do not use tracked uppercase labels as decoration, decorative numbering, gradient fills, large blur, or animation. The visible excerpt and the reason for flagging it should do the visual work.

## Page structure

One route should provide the complete review flow. The server should render an empty state on GET, retain the submitted text when validation fails, and return the result state after a successful POST. Keep `h1` unique, use `h2` for each results group, and `h3` for each individual finding.

Desktop concept:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Rapport Auditor                          English / French · Review cues │
├──────────────────────────────────────┬─────────────────────────────────┤
│ YOUR DRAFT                            │ REVIEW SUMMARY                  │
│ [Paste text or upload .tex/.txt]      │ 842 words · 14 sentences        │
│                                      │                                 │
│ [large labelled textarea]             │ Writing patterns (3)            │
│                                      │ excerpt + reason + review cue    │
│ [Choose file]                         │                                 │
│                                      │ Repeated wording (2)             │
│ [Review patterns] [Preview edits]     │ exact phrase + count + locations │
│                                      │                                 │
│ Data handling / size limit note       │ Source checks (1)                │
│                                      │ citation key + limitation        │
└──────────────────────────────────────┴─────────────────────────────────┘
```

On small screens, place the text entry first and results after the submitted form. Do not make the editor or results a fixed-height region. Let long French labels and excerpts wrap. At tablet widths, stack panels before reducing the editor to an unusable strip. At 320px, content should fit without global horizontal scrolling; long diff lines may scroll inside their own labelled code region.

## Main flow and content

1. **Start a review.** A concise heading says what the tool can help with. Give the textarea a persistent label (“Paste report text or LaTeX”), a short helper, an explicit file option for UTF-8 `.txt` / `.tex`, and an optional, clearly synthetic example loaded only after the user asks for it. Do not preload an example or sample results. Never replace a non-empty draft with the example without first asking in the browser. A paste field remains usable even when JavaScript is disabled. A browser file picker’s `accept` attribute is only a convenience; server validation decides whether the upload is supported.
2. **Choose the report language.** Keep interface locale and document language separate. Let the user select English or French rules and state that each checks only a small, documented set of patterns; French interface copy alone does not determine the report language. Do not imply general language understanding or equivalent quality across languages.
3. **Choose the action.** Make the primary button’s outcome precise: “Review writing patterns.” Use a secondary button labelled “Preview style edits.” These are form submits to distinct POST routes; no action writes back to a file.
4. **Read the result.** Put word and sentence counts first. Call out sample size in plain language (for example, “Short sample: 3 sentences; pattern summaries may change with more text.”). Do not show a numeric confidence badge or traffic-light risk score. Separate style patterns from claim/source checks.
5. **Inspect findings.** Each finding shows the exact excerpt, an explicit text label for the category, a short “Why this appears” reason, and a useful human question. Example: “A claim marker and year appear without a citation on this line. Does your required citation style place its reference elsewhere?” A cue lowers neither source-check burden nor user responsibility.
6. **Review revisions.** Pair before and suggested wording with the transformation reason. Provide “Copy suggestion” only when copy-to-clipboard JavaScript works; keep the before/after text visible without it. If no change exists, say so clearly and do not show an empty diff frame.

Avoid double-counted summary cards when the user can already see the finding list. Use a compact list for repetition results and a `<dl>` for label/value summary facts. Use a native `<details>` region for optional cleaned-text or full-diff output so the default page remains scannable.

## States and copy

| State | Expected content and behavior |
| --- | --- |
| Empty | Explain that input can be pasted or uploaded. Mention supported extensions and language limit. Show no fabricated results or prefilled draft; an optional synthetic example may be offered as an explicit action. |
| Submitting | With native POST there may be no custom loading state. If later added, announce it using a status region, keep the button state understandable, and prevent duplicate processing without blocking keyboard navigation. |
| Empty submit | Return an error summary and a field-level message that says to paste text or choose a file. Keep any value already entered. Focus the error summary after failure. |
| Unsupported file | Say that only UTF-8 `.tex` and `.txt` files are accepted. Preserve pasted text. Link the message to the file control. |
| Invalid UTF-8 | Explain that the bytes could not be read as UTF-8 and suggest exporting as UTF-8. Do not replace undecodable bytes silently. |
| Too large | Report the configured byte or character limit and ask the user to split the document. Reject the input; never silently clip it and report on a fragment. |
| No findings | Say which categories were checked and that no matching pattern crossed the tool’s rule threshold. Do not imply the text is accurate, original, or fully sourced. |
| Error-free revision preview | Say that no configured rewrite rule matched. Keep original text available. |
| Server failure | Give a localized, stable message and a way to try again. Preserve input where practical. Never show a traceback or library/provider internals. |

Build field errors from a shared message list so each error appears next to its control and in a top summary. Wording should name the affected field and tell the user how to correct it; do not clear other fields. The GOV.UK error guidance documents these patterns and recommends moving focus to the summary ([error message](https://design-system.service.gov.uk/components/error-message/), [error summary](https://design-system.service.gov.uk/components/error-summary/)).

## Accessibility and responsive behavior

- Put a skip link before the header. Preserve one descriptive page-level `h1`, hierarchical headings, visible `:focus-visible` outlines, and enough sticky-header offset if section links are added.
- Use native labels and controls. Link hint and error text with `aria-describedby`; use `aria-invalid="true"` only for the field that failed. Do not duplicate built-in keyboard behavior with custom key handlers.
- Communicate issue type with words or icons plus color. Keep the excerpt legible at 200% zoom and 320px viewport width. Do not suppress page overflow to conceal a layout bug.
- Provide at least 44px comfortable action targets. Ensure the focus ring contrasts with both the control and surrounding surface. Target WCAG 2.2 AA contrast; its `Target Size Minimum` criterion is 24×24 CSS pixels with exceptions, while 44×44 is a usability target for this project ([W3C target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)).
- Keep document text visible by default. Honor reduced motion if any optional animation is introduced; a static server-rendered page should work without an animation controller.
- Set the page `lang` for the active interface locale and localize visible copy, screen-reader text, field hints, error messages, result categories, and privacy claims. Keep terminology consistent across EN and FR.
- Test the form and result views with keyboard only, JavaScript enabled and disabled, 320px, 390px, 768px, and 1440px widths, and 200% zoom. Test direct navigation, reloading, and browser back/forward so text is not unexpectedly lost.

## Technical boundaries

Use these project boundaries in the implementation:

```text
apps/api/rapport_api/     JSON and shared request validation/security
apps/web/rapport_web/     Flask views, Jinja templates, CSS, small JS
packages/core/rapport_auditor/  pure Python analysis/repetition/revision
tests/                    core, HTTP/security, and browser-facing checks
docs/                     research, design, API, and security notes
```

Keep one application factory and a small, bounded analysis-worker pool. The local profile binds to loopback; the explicit public profile sits behind the prepared HTTPS proxy and uses shared Redis rate-limit metadata. Give JSON endpoints stable error codes and validate content type, byte length, character length, and strict UTF-8 before analysis. HTML form errors should retain entered text and use human language; API errors should remain machine-readable. Keep the core free of Flask imports so its CLI/tests remain usable and so existing `rapport_auditor.*` imports can be preserved during migration.

All browser modules should be same-origin and served from the application. No user text should enter logs, analytics, URLs, HTML attributes without escaping, or JavaScript via `innerHTML`. Jinja’s autoescaping should remain enabled; do not mark uploaded text or names safe. Do not return the whole input in the API analysis result unless the caller explicitly needs it. Return excerpts the interface needs, with stable line/sentence references.

## Security model and controls

**Assets:** student drafts, extracted excerpts, uploaded filenames, compute capacity, and the runtime. **Entry points:** paste form, multipart upload, HTML routes, JSON API, text/LaTeX parsing, diff rendering, and browser-origin requests. Assume malformed input, very large input, hostile filenames/text, malicious cross-origin submissions, proxy-header spoofing, and service exhaustion. The service is anonymous and has no user accounts; its public profile shares only rate-limit metadata through Redis, not submitted documents.

| Threat | Required control |
| --- | --- |
| Draft exposure | Keep parsing bounded and analysis within the app's isolated worker pool; do not call third-party writing, AI, analytics, or error-reporting services. Do not store drafts. Avoid request-body logging. Use `Cache-Control: no-store` on review/error responses and explain temporary upload buffering accurately. |
| Memory/CPU exhaustion | Enforce an HTTP body-byte cap before form parsing, then a decoded-character limit before analysis. Reject excess size with 413. Bound multipart field count. Do not `read()` an unrestricted stream and truncate afterward. |
| Cross-origin form submission | Keep audit/revision as POST-only routes. Use a validated CSRF token for native forms and compare exact trusted host/origin on mutating requests; no wildcard CORS. Flask does not provide complete CSRF form protection by itself; OWASP recommends a token defense and verifying origin where appropriate ([Flask security](https://flask.palletsprojects.com/en/stable/web-security/), [OWASP CSRF Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)). |
| Host confusion / unintended exposure | Default to `127.0.0.1`. The public profile requires explicit trusted hosts/origins, exact proxy peers, HTTPS at the prepared reverse proxy, secure cookies, a strong signing secret, and shared Redis rate limiting; do not expose the app or Redis ports publicly. Keep debug mode off; Flask warns that its development server is not secure for production and its debugger can execute arbitrary Python from the browser ([Flask server](https://flask.palletsprojects.com/en/stable/server/), [debugger](https://flask.palletsprojects.com/en/stable/debugging/), [trusted hosts](https://flask.palletsprojects.com/en/stable/web-security/)). The topology in [`../deployment/compose.yaml`](../deployment/compose.yaml) is a scaffold and still requires the documented host-specific release checks. |
| Cross-site scripting | Let Jinja escape user data. Render text in text nodes/preformatted blocks; never use user-controlled HTML. In JavaScript use `textContent`. Add a same-origin CSP, `X-Content-Type-Options: nosniff`, and a restrictive framing policy. |
| Temp-file/code execution risk | Accept plain UTF-8 text only. The `.tex` parser is a text transformer; never compile a submitted document, follow `\input`, or execute anything in it. Do not persist the client filename as a path. |
| Secret/config exposure | Do not hardcode a known signing secret. Keep local configuration outside source control and supply the public profile secret through its documented secret-file configuration. Do not set HSTS for the local plain-HTTP profile; it applies to HTTPS origins and can persist in browser state. |

Treat extension and `Content-Type` as untrusted hints. Because this application consumes plain text and does not publish uploaded files, allowlist `.txt` / `.tex`, decode strict UTF-8, enforce size, and never save or serve upload bytes. OWASP says extension/MIME claims alone are not a general file-upload safety check; for this narrower text-only flow, strict decoding and non-execution are the relevant checks ([OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)).

## Rollout and acceptance checkpoints

1. **Preserve behavior and package boundaries.** Move the pure modules under `packages/core` and keep compatibility imports. Capture existing expected outputs using synthetic English/LaTeX fixtures before changing finding semantics.
2. **Secure the server boundary.** Add app factory, request-size/encoding errors, CSRF/origin/host checks, secure headers, no-store responses, safe defaults, and tests for malformed/oversized inputs. Validate through Flask’s test client before browser work.
3. **Build the accessible workbench.** Implement native POST forms, localized copy, responsive layout, result hierarchy, and comparison view. Confirm no-JavaScript workflows and retain input after every recoverable failure.
4. **Evaluate honest result labels.** Use synthetic examples of ordinary academic prose, claims with citations, claims without inline citations, repeated wording, code/LaTeX, French, and non-Latin Unicode. Record missed and false-positive patterns in the UI limits. Do not tune a result threshold to make a screenshot look clean.
5. **Finish verification and docs.** Run the project suite and real-browser QA at 320/390/768/1440px and 200% zoom, keyboard navigation, reduced motion, JavaScript off, upload errors, and back/forward. Inspect the final repository diff to confirm unrelated parent-directory files were not changed.

Completion means the UI describes all heuristics as suggestions; all flows work without JavaScript; EN/FR strings and errors are complete and the selected language is explicit; size/encoding errors are specific and preserve user work; the application does not log or intentionally retain draft content; deployment checks are reported with conditions and gaps; and screenshots use synthetic text only.
