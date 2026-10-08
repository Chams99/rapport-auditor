# Portfolio assets

These images and the video are made from the running app with a fictional chapter excerpt. No real study, data or source appears in them.

These supplied captures were generated in local mode in the original authoring folder on 2026-10-08, before integration into the deployment repository. Their local-service labels describe that session; they do not establish public-host privacy, deployment status, or accessibility conformance. See [the testing record](../TESTING.md) for the checks actually completed and their limits.

| File | Size | Use |
| --- | --- | --- |
| `cover-1600x1000.png` | 3200×2000 (2×) | Portfolio card or project header: title, three highlights, laptop and phone |
| `devices-1600x1000.png` | 3200×2000 (2×) | Laptop and phone mockup without text |
| `social-1200x630.png` | 2400×1260 (2×) | Open Graph / LinkedIn / X link preview |
| `demo.webm` | 1440×900 | About 25 s walkthrough: paste, review, filter, jump to the passage, mark reviewed, preview edits |
| `screens/desktop-review-light.png` | 2880×1800 | Main result screen |
| `screens/desktop-review-dark.png` | 2880×1800 | Same in dark mode |
| `screens/desktop-filtered-light.png` | 2880×1800 | "Source check" filter with the passage selected in the editor |
| `screens/desktop-revision-light.png` | 2880×1800 | Style-edit preview with changed words highlighted |
| `screens/desktop-home-light.png` | 2880×1800 | Empty state |
| `screens/desktop-home-fr-dark.png` | 2880×1800 | French interface, dark mode |
| `screens/desktop-about-light.png` | 2880×1800 | How it works page |
| `screens/mobile-*.png` | 1170×2532 (3×) | Phone screens, light and dark |
| `brand/logo-mark.svg` | vector | Logo |
| `brand/logo-mark-512.png`, `brand/app-icon-1024.png` | PNG | Logo with rounded tile; full-bleed app icon |

## Regenerate after you deploy

Run this from the repository root with the browser tools installed (`npm ci --prefix scripts`). The address bar in the mockups then shows your real domain:

```sh
PORTFOLIO_BASE_URL=https://your-domain.example node scripts/portfolio_shots.cjs
```

On Windows PowerShell:

```powershell
$env:PORTFOLIO_BASE_URL = "https://your-domain.example"; node scripts/portfolio_shots.cjs
```

Set `RAPPORT_AUDITOR_CHROME` to an installed Chrome if Playwright's own browser is not installed. Set `PORTFOLIO_OUT` to write somewhere other than this folder. After changing the logo in `apps/web/rapport_web/static/favicon.svg`, run `node scripts/build_icons.cjs` first.

## Suggested project text

**Rapport Auditor** — a bilingual (English/French) review desk for academic writing. It flags repeated openings and phrases, long or dense sentences, stock phrases and claims that may need a visible source. Each prompt links back to the exact passage, which is highlighted in the editor. The tool explains why it was flagged and asks a question instead of giving a verdict.

- **Product and UX:** an app-shell layout for wider screens and a page layout with a sticky action bar on phones. Highlights sit inside the editor, results can be filtered by type, prompts can be marked reviewed and the notes exported as Markdown. There is a light/dark/system theme and keyboard navigation. Check the testing record for measured viewport behavior.
- **Engineering:** Flask and Waitress with server-rendered Jinja templates and dependency-free browser JavaScript. The rule engine is deterministic and separate from the web layer. Native forms support review and revision without JavaScript; optional interactive enhancements require it.
- **Quality:** pytest regressions and browser test tooling, with WCAG 2.2 AA as the design target. Recorded checks and unverified browser/assistive-technology coverage are documented separately; automated checks do not establish full accessibility conformance.
- **Security and privacy:** a same-origin CSP, CSRF and origin checks, and bounded uploads with strict UTF-8 decoding. The application does not call an external writing service and is designed not to persist drafts. Public submissions go to the hosting server; infrastructure logs, backups, and retention have not been verified.
