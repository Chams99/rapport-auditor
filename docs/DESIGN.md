# Rapport Auditor: interaction and visual specification

This document turns the research in [RESEARCH.md](RESEARCH.md) into a concrete direction for the modernization. It is a review reference for the HTML, CSS, localization, and server-rendered states.

## Product promise

Rapport Auditor is a focused draft-review workspace. It helps a student spot repetitive wording, dense passages, and claims worth checking against sources. The student owns every decision and keeps the original file.

Use “review,” “signal,” “pattern,” “source-check prompt,” and “suggested revision.” Do not use “detector,” “proof,” “verified,” “confidence,” or “submission ready.” Explain the key limits at the point of use: the rules are narrow and language-specific (English or French), not a general grammar or fact checker; citation references are not resolved; and no source is checked for truth or relevance. The synthetic fixtures establish rule conformance for those examples only, not real-world reliability.

## Visual direction

Keep the warm paper, dark ink, and indigo identity, but treat the page as an editorial workbench rather than a marketing landing page. The current interface uses a compact intro above an editor/results workspace; excerpts, reasons, and review questions carry the visual emphasis. Keep the proofing mark restrained, avoid scores that look like a verdict, and use local system fonts rather than remote font services.

The stylesheet uses purpose-named tokens. The light palette includes `--canvas: #f6f4ef`, `--surface: #ffffff`, `--text: #1c1b2b`, `--text-muted: #555366`, `--border-control: #77748a`, and `--accent: #4b3fc4`; it provides corresponding dark-surface values and semantic status colors. These are implementation values, not a blanket conformance claim. Check composited text, focus rings, control boundaries, pressed states, dark mode, and forced-colors mode when changing the palette. WCAG 2.2 is the normative reference for contrast, reflow, focus, and target size ([WCAG 2.2](https://www.w3.org/TR/WCAG22/)).

Controls use local system sans-serif, with a local serif for headings/excerpts and monospace for technical output. Editor and excerpt text use 16px; body and control text use 14px, while metadata and some helper copy are smaller. Keep the textarea resizable and usable at phone widths. The theme script applies the saved system/light/dark choice before the page paints; the header control remains hidden until its JavaScript handler initializes. Keep user text and core form actions usable without JavaScript.

## Page structure

The server renders the home review flow and an English/French “How it works” page at `/about`. On wide, tall screens the header and compact intro sit above a two-column workbench: the editor on the left and results on the right. Each pane can scroll within the app shell. On narrow or short screens, the workspace returns to normal document flow, with the editor before results and the action bar sticky while the editor is in view. Let French text wrap; do not use a minimum page width or global overflow masking.

The editor starts with compact document-language and pasted-format controls alongside the native file picker, then the paste field. The sample action sits in the editor footer after JavaScript initializes; the same fictional EN/FR text remains in a native disclosure near the label for manual copy and is hidden only when the enhanced action is ready. A selected file takes precedence over pasted text. Without JavaScript the native file input remains visible and exposes the selected filename; the custom picker and removable-file chip appear only after file-selection behavior is ready. A no-script note explains that users can reload and paste again to switch back. The privacy disclosure identifies unverified public-host log and backup retention. Input character, byte, line, and file-size limits come from server configuration.

An audit result shows source and document counts, a per-type check overview, writing-pattern notes, citation cues, and findings. When findings are capped, the overview says that unmatched types are not shown among displayed prompts rather than claiming no omitted match exists. Citation cues stay in their own section, outside the prompt filters. JavaScript can filter finding cards by rule type, mark cards as reviewed, highlight excerpts in the editor, and navigate to cited lines; review progress is temporary and is not an accuracy or quality score. The short-sample notice appears only below four sentences. Keyboard help documents Ctrl/Command+Enter, J/K navigation, X review, G passage navigation, and ? for the shortcut dialog.

A revision result keeps before/suggested wording visible and includes a labelled, read-only textarea with the complete proposed text for manual selection and copying, including when JavaScript is unavailable. JavaScript adds the download action after initialization. The unified diff follows in a native disclosure that is open by default and can be collapsed. Clearing a draft is reversible for eight seconds through the Undo control/toast. The idle state combines a small illustration with a three-step guide and no fabricated findings. The /about page documents the available pattern types, workflow, limits, and mode-specific privacy wording.

The home route links versioned same-origin CSS, application JavaScript, and theme JavaScript by content hash so browsers request new assets after a file change. Favicons are served by the app’s static route or the explicit `/favicon.ico` route.

## Main flow and content

1. **Orient the writer.** State that the tool produces selected English/French writing-pattern and citation prompts. Say plainly that it does not check grammar generally, factual claims, bibliography entries, source contents, plagiarism, or authorship. Never imply that a cue verifies a source or supports a claim.
2. **Explain data handling before input.** The visible public-service summary says the text is sent to the hosting server and recommends synthetic or non-sensitive text. The local-service summary describes local processing and advises against sensitive passages. The disclosure retains the exact mode-specific wording, including the unknown hosting-log and backup-retention caveat in public mode and possible temporary OS/browser copies in local mode.
3. **Enter or select a source.** No text is prefilled. The closed sample disclosure exposes the same fictional EN/FR examples for manual copy without JavaScript. After initialization, the sample action loads the selected document-language example and confirms before replacing existing text or a file. The native UTF-8 `.txt`/`.tex` picker is visible without JavaScript and its selected filename remains available; the enhanced picker and removable-file chip appear only after the handlers initialize. A selected file takes precedence, and the no-script instructions explain how to reload and paste again to switch back. The file picker’s `accept` attribute is a convenience only; server validation decides what is accepted.
4. **Set review options.** The document-language and pasted-format controls appear before the source fields. Keep interface locale independent from selected document language; the format selector applies only to pasted input and uploaded file type is inferred from its extension.
5. **Choose an action.** “Review writing patterns” and “Preview style edits” are separate native POST actions. Neither writes into the original file.
6. **Read evidence in context.** Show word and sentence counts, category labels, exact excerpts, short reasons, and a human review question. Do not show a confidence score, risk gauge, or “ready” verdict. A sample of fewer than four sentences receives a brief caveat that patterns may change with more text.
7. **Navigate and filter.** Use ordinary in-page anchors for result groups. JavaScript may reveal filters for the displayed finding cards only; it must not remove or hide the separate citation-cue inventory. Announce the active filter and displayed/total counts, and provide a localized empty-filter state.
8. **Review proposed wording.** Keep each before/after change and reason visible. Show the complete proposed text in a labelled read-only field that remains useful without JavaScript. JavaScript reveals the download action after initialization. The unified diff follows in a native disclosure, open by default but collapsible.

## States and copy

| State | Expected content and behavior |
| --- | --- |
| Empty | Show a compact next step, supported language/input guidance, and no sample text prefilled. |
| Submitting | Native POST remains the core path. If JavaScript adds a busy label/status, keep it localized and prevent duplicate submission without trapping keyboard users. |
| Validation error | Show a top error summary with links to each affected control and matching field-level messages. Keep entered text and provide a path to remove a selected file. |
| Unsupported file or encoding | Name supported UTF-8 `.txt` and `.tex` input and give a specific correction. Preserve pasted text when upload validation fails. |
| Too large | Report the configured character or byte limit and suggest splitting the document. Reject excess input; never silently clip it and present a partial review. |
| No prompts | Say that no configured writing or source-check prompts were raised for this sample. Do not imply factual, citation, originality, or source verification. |
| Filter with no cards | Explain that the selected category has no displayed prompts and offer another filter. Keep every finding available under “All.” |
| Revision preview | Keep the original text available, show any proposed edits, and expose the full revised text for manual copy whether or not JavaScript runs. |
| Service failure | Use a localized stable message, preserve form state where possible, and do not show a traceback or internals. |

Keep errors specific and consistent beside the field and in the summary. GOV.UK’s guidance uses linked summaries, focus on the summary after failure, matching inline error text, and preserved field values ([error messages](https://design-system.service.gov.uk/components/error-message/), [error summaries](https://design-system.service.gov.uk/components/error-summary/)). Use those behaviors, not its visual identity.

## Accessibility and responsive behavior

- Keep a visible-on-focus skip link, one descriptive page-level `h1`, hierarchical headings, and a strong visible `:focus-visible` indicator.
- Use native labels, fieldsets, selects, textarea, visible file input, buttons, anchors, and `<details>/<summary>`. Link helper/error text with `aria-describedby`; mark only the failing field invalid. Preserve ordinary keyboard behavior and JavaScript-disabled form submission. Native file inputs display the selected filename and remain operable without custom JavaScript ([MDN file input](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input/file)).
- Keep the live character count out of an always-announcing live region. It is described by the textarea; status announcements should be reserved for meaningful state changes such as submission, file selection, filtering, and stale results. USWDS recommends associating the count with the field and notes testing issues around count announcements and threshold awareness ([character count](https://designsystem.digital.gov/components/character-count/)).
- Keep body and primary control text at 14px or larger and the editor at 16px; secondary metadata and helper text use smaller tokens and should remain legible. Aim for 44px comfortable actions; WCAG 2.2’s minimum target-size criterion is 24×24 CSS pixels with exceptions ([Target Size Minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)).
- Keep text at 320px and 200% zoom without page-level overflow. Result excerpts and filenames must wrap. Allow an individual diff region to scroll if necessary.
- Keep the page `lang` set to the interface language and annotate document-language excerpts. Localize all control names, field errors, announcements, privacy wording, filters, empty states, and result labels.
- Retain reduced-motion and forced-colors support. Core content and controls must not depend on animation, JavaScript, color alone, or unsupported CSS.
- Test both locales with keyboard-only navigation, JavaScript on/off, direct load and POST results, 320/390/768/1440px widths, actual 200% browser zoom, and back/forward. Browser automation and axe do not replace manual screen-reader testing.

Native disclosure is suitable for optional details such as privacy wording, citation inventory, and the unified diff; it works without a custom widget controller and is broadly supported ([MDN `<details>`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details)). Keep the HTML form as the working baseline and add JavaScript only to improve it ([MDN progressive enhancement](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Best_practices)). Container queries are broadly supported for size-based component adaptation, but viewport media queries remain adequate for this single-page shell ([MDN container queries](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/container-type)).

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
| Host confusion / unintended exposure | Default to `127.0.0.1`. The public profile requires explicit trusted hosts/origins, exact proxy peers, HTTPS at the prepared reverse proxy, secure cookies, a strong signing secret, and shared Redis rate limiting; do not expose the app or Redis ports publicly. Keep debug mode off; Flask warns that its development server is not secure for production and its debugger can execute arbitrary Python from the browser ([Flask server](https://flask.palletsprojects.com/en/stable/server/), [debugger](https://flask.palletsprojects.com/en/stable/debugging/), [trusted hosts](https://flask.palletsprojects.com/en/stable/web-security/)). The standalone profile is in [`../deployment/compose.yaml`](../deployment/compose.yaml); the Traefik cohosting profile and its host-specific release checks are documented in [`COHOSTING.md`](COHOSTING.md). |
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
