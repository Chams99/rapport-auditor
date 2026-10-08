# Verification guide

The project targets Python 3.10 or newer and uses a Flask application factory with server-rendered HTML. There is no frontend build step.

## Install and run automated checks

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.venv\Scripts\python.exe -m pip install setuptools==84.0.0
.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pip_audit -r requirements-runtime.lock
.venv\Scripts\python.exe -m pip_audit -r requirements-dev.lock
```

The lock files record a Python 3.10 dependency resolution; use the same target Python and platform when reproducing it. Platform-marked packages can differ across operating systems. The Python tests cover the core heuristics, LaTeX preservation, citation-cue limits, API payload validation, HTML native forms, UTF-8 uploads, file and body boundaries, CSRF/origin/host restrictions, rate limiting, logging, response headers, and Waitress buffer configuration. Fixtures in `examples/synthetic/` are fictional and contain no student draft or real measured result.

To run only the security and request-boundary tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_security.py tests/test_security_unit.py tests/test_uploads.py tests/test_cli.py
```

## Browser smoke checks

Start the local Waitress server in a separate terminal:

```powershell
.venv\Scripts\python.exe -m rapport_api.cli --host 127.0.0.1 --port 5000
```

The optional browser runner is `scripts/browser_smoke.cjs`. It uses pinned Node development dependencies and automated axe checks:

```powershell
npm ci --prefix scripts
$env:RAPPORT_AUDITOR_CHROME = "C:\Program Files\Google\Chrome\Application\chrome.exe"
npm audit --prefix scripts
npm run --prefix scripts test:browser
```

If Chrome is not installed, install Playwright’s pinned Chromium with `npm run --prefix scripts install:browsers` and leave `RAPPORT_AUDITOR_CHROME` unset.

The runner uses only synthetic examples and localhost. It checks English/French home pages at 320, 390, 640, 768, and 1440 CSS pixels; English/French audit results and rejected-upload errors at 320, 390, and 1440 CSS pixels; labels and landmarks; horizontal overflow; 44px target bounds for locale links and primary controls; idle/results focus; the skip-link keyboard stop; locale navigation/back/forward; the opt-in example and replacement confirmation; reduced-motion preference and computed CSS; a failed script; and JavaScript-disabled native audit, revision, TeX upload, rejected upload, and retry flows. The built-in axe checks cover English/French home pages, an English audit result, and a synthetic findings result. Separate fresh-context axe checks covered English and French result and upload-error pages. The runner records browser errors and fails if the app requests an external origin. It writes `home-desktop.png`, `home-mobile.png`, `sample-review.png`, `sample-findings.png`, and localized result/error captures to `docs/screenshots/`. The findings capture has a screenshot-only banner to label the synthetic fixture; it is not a page feature.

The 640-CSS-pixel check is a reflow proxy for a 1280-pixel viewport at 200% zoom. It does not manipulate Chrome’s browser zoom control. Actual 200% browser zoom could not be verified in the recorded environment. Axe catches only some automatically detectable issues; the browser script is not a screen-reader test. Screen-reader operation and other browser engines were not verified. Manually inspect focus order, error announcements, and form operation with target assistive technology before claiming full accessibility conformance.

## Production-like local smoke test

`rapport_api.cli` starts Waitress, not Flask’s debug server. Confirm `/api/v1/health`, `/api/v1/csrf`, a synthetic API review, a native HTML audit, a revision preview, and a supported text upload from the local browser. The E2E runner exercises these flows against the server but does not send drafts to a remote service. Stop the server from its terminal when finished.

## What test results mean

Automated checks only establish the behavior exercised under the recorded Python, dependency, browser, and viewport setup. They do not establish factual accuracy, source validity, author identity, security under arbitrary remote exposure, production-scale load, actual 200% browser zoom, assistive-technology compatibility, or universal privacy guarantees. Record any skipped tools and manual checks beside the final results.

## Recorded verification — 2026-10-06

Environment: Windows 11 Pro 10.0.26200 (64-bit); Python 3.10.3 and 3.12.14; Flask 3.1.3; Werkzeug 3.1.9; Waitress 3.0.2; pytest 9.1.1; Ruff 0.16.10; pip-audit 2.10.1; Playwright 1.62.1; axe-core 4.13.0; Google Chrome 154.0.8037.98. Browser checks used the installed Chrome executable through `RAPPORT_AUDITOR_CHROME` and a local Waitress server at `127.0.0.1:5001`.

- Python suites: Python 3.10.3 **132 passed, 3 skipped** (18.93s); Python 3.12.14 **132 passed, 3 skipped** (17.66s). The skips are two POSIX-only worker resource-limit cases and the live Redis integration test; Windows unit/API tests use deterministic fakes for unavailable infrastructure.
- Browser evidence: the consolidated EN/FR browser smoke completed successfully at 320, 390, 640, 768, and 1440 CSS pixels; all 22 recorded home/result/error measurements had `documentWidth == viewportWidth`. EN/FR audit results and rejected-upload error layouts completed at 320, 390, and 1440 CSS pixels with no overflow, pasted values retained, content language preserved, and alert/detail duplication absent. Locale links measured 44×44px at every home width; home upload, format, example, clear, and submit controls met 44px at 320 and 390. The document-language selector measured 130×44px at 320 and 137.8×44px at 390. JavaScript-disabled audit, revision, TeX upload, rejected-upload recovery, and valid retry passed. The 640-CSS-pixel measurement is a reflow proxy, not actual browser zoom.
- Axe: the consolidated browser run reported zero violations and 116 passing rules across its English/French home, English audit, and synthetic findings states. Separate fresh-context checks reported zero violations on EN result (30 passing rules), EN upload error (28), FR result (30), and FR upload error (28). Axe does not replace manual assistive-technology testing; no screen reader was used.
- Static/dependency checks: Ruff passed; `pip check` was clean in both Python environments; pip-audit reported no known vulnerabilities in runtime and development lock files; `npm audit --prefix scripts` reported zero vulnerabilities. The Python 3.12.14 wheel (SHA-256 `8e8a2359222119047077ce4cb714aaa4a9125d44952a64c83ee12d00d2e87b62`) was installed with locked runtime dependencies into a temporary isolated environment: package imports resolved there, expected module/template/CSS/JS resources were present, `/`, CSS, JavaScript, CSRF bootstrap, API audit, and revision requests returned 200, and `pip check` was clean. No live Redis service was available for this Windows verification.
- Evidence: [desktop home](screenshots/home-desktop.png), [mobile home](screenshots/home-mobile.png), [clean synthetic review](screenshots/sample-review.png), [synthetic findings review](screenshots/sample-findings.png), plus [EN results at 1440](screenshots/synthetic-result-en-1440.png), [EN results at 390](screenshots/synthetic-result-en-390.png), [EN results at 320](screenshots/synthetic-result-en-320.png), [FR results at 1440](screenshots/synthetic-result-fr-1440.png), [FR results at 390](screenshots/synthetic-result-fr-390.png), [FR results at 320](screenshots/synthetic-result-fr-320.png), and matching `synthetic-error-{en,fr}-{1440,390,320}.png` files.

No field p75 Core Web Vitals, actual 200% browser zoom, screen-reader session, alternate browser engine, or remote deployment was tested.

## Follow-up reliability verification — 2026-10-07

After the targeted sentence-boundary, citation-association, and revision-capitalization fixes, the full pytest suite passed on both installed Windows runtimes: Python 3.10.3 **150 passed, 3 skipped** (13.40s) and Python 3.12.14 **150 passed, 3 skipped** (12.45s). The skips are the two POSIX-only worker resource-limit cases and the live Redis integration test. The added `tests/test_review_regressions.py` cases passed **18/18** on both runtimes (0.07s and 0.06s on the final strengthened assertions). Ruff passed, and `pip check` found no broken requirements in either environment. The existing 47-case synthetic language-cue evaluator conformed to all expected cue sets. The new regressions are documented separately from that implementation-aware conformance set in [the evaluation notes](EVALUATION.md); neither set estimates real-world accuracy. This Windows verification does not replace the Linux worker-limit, live Redis, container, TLS, or load checks listed in [the production runbook](PRODUCTION.md).

## Wheel and browser verification — 2026-10-07

After the core source freeze, the wheel was rebuilt on Python 3.12.14 with setuptools 84.0.0 using `pip wheel --no-deps --no-build-isolation`. The resulting `rapport_auditor-1.0.0-py3-none-any.whl` (68,512 bytes) has SHA-256 `19272cbc6b303e2d0778baf9dff44e7d840d068264b08a047b407b584f360b45`. It was installed with `--no-deps` into a new isolated Python 3.12.14 environment after installing `requirements-runtime.lock`. `pip check` was clean. From a temporary working directory outside the repository, `rapport_api`, `rapport_web`, and `rapport_auditor` all imported from that environment’s `site-packages`; a Flask test-client request to `/?locale=en` returned 200. The imported package paths confirmed that this check did not fall back to the source checkout.

The consolidated browser runner then passed with exit code 0 against a local Waitress preview started from that isolated environment at `127.0.0.1:5001`; its health endpoint returned 200. The run used Node 24.19.0, Playwright 1.62.1, axe-core 4.13.0, and Chrome 154.0.8037.98. It reported **zero axe violations and 116 passing rules**, with no horizontal overflow on English/French home pages at 320, 390, 640, 768, and 1440 CSS pixels or result/error pages at 320, 390, and 1440. The run also passed the 44px home target checks, keyboard and history flows, reduced-motion checks, failed-script fallback, and JavaScript-disabled audit, revision, upload, validation-error, recovery, and retry flows. It reported no unexpected third-party requests or browser runtime errors.

The run generated 16 screenshot captures in a temporary directory. Each was byte-identical to its matching file in `docs/screenshots/`, so no screenshot files were replaced. The 640px viewport remains a reflow proxy, not an actual 200% browser-zoom check; this run did not exercise a screen reader or an alternate browser engine. A separate, limited public-route acceptance check is recorded below.

## Linux co-host verification — 2026-10-07

At checked-out commit `30aa43e7d07552ee6a8cae109b255a7102c0ddb2`, `bash scripts/verify_cohost.sh` completed on the VPS with Python 3.12.14: **194 passed in 29.04 seconds, no skips**. The gate ran the full pytest suite in an isolated test container with a disposable live Redis service and resource limits; it used read-only source and cleaned only its own test containers and network. The retained builder image was identified as `sha256:8a1b06258360874fadba6630b34a88a196b3293ea0312648d9c1d47b89e23d93`. This is Linux/container regression evidence, not a production load or capacity result, and it did not stop or outage-test the live app's Redis.

## Public synthetic acceptance — 2026-10-07

From an external client, the deployed `https://rapport.chames.tn` route passed normal certificate validation. Synthetic health, API, and native-form requests succeeded; invalid Origin and CSRF requests returned `403`, an oversized request returned `413`, and a `30`-request same-client quota sequence with varying forged `X-Forwarded-For` values returned `200` until the next request returned `429` with `Retry-After: 18`. The response also included the expected HTTPS security headers and secure-cookie attributes. These checks used synthetic content only. They demonstrate the tested route behavior at that time; they do not establish host capacity, a complete CDN/upstream trust chain, proxy/provider log retention, backup retention, or a real Redis outage response on the live app. See [the co-hosting record](COHOSTING.md) for deployment-specific limits.

## Bounded co-host sample — 2026-10-07

At reviewed checkout `373811d60c5e5988614705d8290ed83efdb72f81`, the VPS probe `python3 scripts/cohost_acceptance.py` sent two concurrent, single-attempt HTTPS audits using 250,000 synthetic characters each. English returned valid API JSON and HTTP 200 in 7.62 seconds; French returned valid API JSON and HTTP 200 in 7.85 seconds. MemAvailable measured 3,936 MiB before, 3,874 MiB minimum during sampling, and 3,895 MiB afterward; Docker-root free space remained 8.19 GiB. Sampled memory ranged from 50.87 to 52.33 MiB for the app (2 GiB limit), 5.488 to 5.496 MiB for Redis (256 MiB limit), and 91.59 to 93.02 MiB for Traefik (512 MiB limit). Readiness/resource guards passed, and no restart or OOM change was observed. The bounded query/body canaries were absent in the scanned app and Traefik Docker logs. These are sampled observations during two requests, not peak measurements, a load/soak test, or a capacity guarantee; log checks did not cover host logs, external providers, backups, or retention.

## Current UI review — 2026-10-07

This was a manual interaction and viewport review in the in-app Chromium browser using the current interface and synthetic text. It is separate from the earlier Playwright/axe records above: `scripts/browser_smoke.cjs` and axe were **not rerun for this pass**.

- After the final layout freeze, a fresh Waitress preview (session 2134) was checked in English and French at 320, 390, 768, and 1440 CSS pixels. At each viewport, both `documentElement.clientWidth` and `scrollWidth` measured 305, 375, 753, and 1425 pixels respectively, with no horizontal overflow. Visible buttons, selects, summaries, locale links, the upload title, and the native file input measured at least 44px high; inline prose links were not part of that target check. In the French 390px home view, the text area began at y=768px, compared with y=1080px before the settings-fieldset reordering. A French sample audit also completed at 390px without horizontal overflow. The later generic-source-label localization affects result headings only, not this home-page matrix.
- The English sample audit moved focus to the results heading. The source filter showed 1 of 5 prompts, returning to All showed all 5, and editing the text surfaced the stale-results notice. The revision flow showed before/after edits, a manually copyable full-text field, and a working download.
- The final in-app Chromium pass (session 56746) also verified the French generic pasted-source label and localized all-filter status in the result view.
- Native file selection disabled the pasted-format selector; removing the file restored the selector and preserved pasted text. A synthetic `review_prompts_en.tex` upload completed an audit with its filename retained. The reviewed flows produced no browser-console errors.
- Current synthetic captures: [English desktop home](screenshots/ux-home-desktop.jpg), [French mobile home](screenshots/ux-home-mobile-fr.jpg), [English desktop review](screenshots/ux-review-desktop.jpg), [French mobile review](screenshots/ux-review-mobile-fr.jpg), and [desktop revision preview](screenshots/ux-revision-desktop.jpg).

The UI integration was also covered by the Python 3.12.14 full suite (**202 passed, 10 skipped in 14.55 seconds**) and focused web tests (**14 passed**); the app-state harness, JavaScript syntax check, Ruff, and whitespace check passed. The 10 skips were seven Linux/Bash-only cases, two POSIX worker-limit cases, and the opt-in live Redis case. This manual browser pass did not rerun the browser-smoke runner or axe. It also did not test JavaScript-disabled behavior, reduced motion, actual 200% browser zoom, another browser engine, or a screen reader. Earlier automated checks in this file are historical results for their recorded code and environment, not results from this UI pass.

## VPS deployment verification — 2026-10-07

The VPS deployment log for release commit `6e17a4b54b4dbaf92cb4376cacbec8d5787a937a` records the co-host gate passing on Python 3.12.14 with **212 passed in 32.33 seconds and no skips**, using live Redis. The builder image was `sha256:9f4d96928804fda84ccdd14b7d12e6f0c7477847875a590083da9407e688a653`; the app image was built as `sha256:389455b23adf8a7204d4e9d4f4eb6da6ca5c8130365d2d1e196ed6bb8588758d`, and the app container started. These build and test facts come from the user's VPS log.

Separately, an independent HTTPS check of `https://rapport.chames.tn` passed normal TLS validation. English and French home GETs returned 200 with matching document-language tags; readiness returned 200/`ready`; versioned CSS and JavaScript assets returned 200 with the expected content types and SHA-256 bytes matching the committed files. The responses included the checked security headers and CSRF-cookie attributes. These GET checks do not identify which image served the route, and are not new POST, load, cross-browser, or accessibility results. The deployment log's image digest is recorded as a build result, not as proof that the independent HTTPS requests reached that exact runtime image.

A separate public-browser spot-check confirmed the public-service safety summary in both locales. At a 390px French viewport, `clientWidth` and `scrollWidth` were both 375px with no horizontal overflow, and the JavaScript-enhanced sample button was visible.

## User UI integration verification — 2026-10-08

The authoring-tree layout, themes, shortcuts, About page, and icons were integrated into the deployment repository while retaining production input ceilings, asset fingerprinting, privacy caveats, and native form fallbacks. The original authoring tree was left intact. The imported [portfolio media](portfolio/README.md) were captured before this integration; they are showcase assets, not deployment or accessibility evidence.

- On Windows with Python 3.12.14 and imports explicitly pointed at this deployment checkout, the full suite passed: **203 passed, 10 skipped in 19.57 seconds**. The skips were seven Linux/Bash cases, two POSIX worker-limit cases, and the opt-in live Redis test. Focused web tests passed **15/15**. Ruff, JavaScript syntax checks, the Node app-state regression harness, and `git diff --check` passed. The state harness now models a live FileList and checks that Clear/Undo restores the file, text, chip, and format lock.
- Manual in-app Chromium checks against local Waitress at `127.0.0.1:5012` covered English/French home pages at 320, 390, 768, and 1440 CSS pixels with no horizontal overflow; theme cycling; localized About navigation; native synthetic audit; finding filters, marking reviewed, and editor line selection. A final French 390px check measured `clientWidth == scrollWidth == 375px` after the small fallback-copy changes.
- After the final source freeze and preview restart, a real synthetic `.tex` selection survived Clear/Undo with the original pasted draft and disabled LaTeX format selector restored. Removing the file restored the pasted-text format without losing the draft. A native revision submitted successfully, focused the results heading, exposed the labelled readonly full text, and completed its revised-text download. No console warnings/errors were recorded in the checked flows.
- The final wheel built successfully (95,134 bytes; SHA-256 `da081d3b874787ac22ab46b9b228cff841b1e77e2780ff23c7fd75db909c736e`). All 11 packaged top-level static/template resources matched the checkout bytes, including the theme script, icons, About page, and shared partials. This was a wheel-content check, not a new isolated installation test.

The revised browser-smoke runner was syntax-checked but **not executed**, and axe was **not rerun**. This pass did not exercise a JavaScript-disabled browser, reduced-motion preferences, actual 200% browser zoom, another engine, or a screen reader. Linux/container/live Redis checks and deployment of this candidate remain to be run on the VPS; earlier records above apply to their dated releases.
