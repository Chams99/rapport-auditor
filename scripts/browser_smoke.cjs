/*
 * Real-browser smoke checks for the local, server-rendered workflow.
 * Usage: set NODE_PATH to a directory containing the Playwright npm package,
 * set RAPPORT_AUDITOR_BASE_URL if needed, then run `node scripts/browser_smoke.cjs`.
 */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const AxeBuilder = require("@axe-core/playwright").default;

const baseUrl = process.env.RAPPORT_AUDITOR_BASE_URL || "http://127.0.0.1:5000";
const hardDeadlineMs = Number(process.env.RAPPORT_AUDITOR_BROWSER_TIMEOUT_MS || 150000);
let deadlineBrowser;
const hardDeadline = setTimeout(async () => {
  console.error(`[browser] overall deadline exceeded after ${hardDeadlineMs}ms`);
  await deadlineBrowser?.close().catch(() => {});
  process.exit(124);
}, hardDeadlineMs);
hardDeadline.unref();
const root = path.resolve(__dirname, "..");
const screenshotDir = process.env.RAPPORT_AUDITOR_BROWSER_ARTIFACT_DIR
  ? path.resolve(process.env.RAPPORT_AUDITOR_BROWSER_ARTIFACT_DIR)
  : path.join(root, "docs", "screenshots");
const syntheticDir = path.join(root, "examples", "synthetic");
const viewports = [320, 390, 640, 768, 1440];
const responsiveMeasurements = [];
const touchMeasurements = [];

function check(condition, message) {
  assert.ok(condition, message);
}

function verifyNoHorizontalOverflow(metrics, label) {
  check(
    metrics.documentWidth <= metrics.viewportWidth,
    `${label}: document is ${metrics.documentWidth}px wide in a ${metrics.viewportWidth}px viewport`,
  );
}

async function verifyTouchTargets(page, label, selectors) {
  const targets = await page.evaluate((items) => items.flatMap(([name, selector]) => {
    const element = document.querySelector(selector);
    if (!element || element.hidden || getComputedStyle(element).display === "none") return [];
    const rect = element.getBoundingClientRect();
    return [{ name, width: rect.width, height: rect.height }];
  }), selectors);
  touchMeasurements.push({ label, targets });
  const undersized = targets.filter((target) => target.width < 44 || target.height < 44);
  check(
    undersized.length === 0,
    `${label}: touch targets below 44px: ${undersized.map((target) => `${target.name} ${target.width.toFixed(1)}×${target.height.toFixed(1)}px`).join(", ")}`,
  );
}

async function verifyA11y(page, label) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const problems = result.violations.map((violation) => {
    const targets = violation.nodes.map((node) => node.target.join(" ")).join(", ");
    return `${violation.id} (${violation.impact}): ${targets}`;
  });
  check(problems.length === 0, `${label}: axe violations:\n${problems.join("\n")}`);
  return result.passes.length;
}

async function installPageDiagnostics(page, errors, externalRequests, httpErrors) {
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) {
      errors.push(`console: ${message.text()}`);
    }
  });
  page.on("request", (request) => {
    const requestUrl = new URL(request.url());
    if (requestUrl.origin !== baseUrl) externalRequests.push(request.url());
  });
  page.on("requestfailed", (request) => errors.push(`requestfailed: ${request.url()} (${request.failure()?.errorText || "unknown"})`));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      httpErrors.push({ status: response.status(), pathname: new URL(response.url()).pathname });
    }
  });
}

async function main() {
  fs.mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.RAPPORT_AUDITOR_CHROME || undefined,
    args: ["--disable-dev-shm-usage"],
  });
  deadlineBrowser = browser;
  const runtimeErrors = [];
  const externalRequests = [];
  const httpErrors = [];
  let axePasses = 0;

  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.setDefaultNavigationTimeout(20000);
    await installPageDiagnostics(page, runtimeErrors, externalRequests, httpErrors);

    // EN and FR at the requested narrow, mobile, tablet, and desktop widths.
    console.log("[browser] start home locale/viewport matrix");
    for (const locale of ["en", "fr"]) {
      for (const width of viewports) {
        await page.setViewportSize({ width, height: 900 });
        const response = await page.goto(`${baseUrl}/?locale=${locale}`, { waitUntil: "networkidle" });
        check(response && response.status() === 200, `${locale}/${width}: home page did not load`);
        check(await page.locator("html").getAttribute("lang") === locale, `${locale}: html lang mismatch`);
        check(await page.locator("h1").count() === 1, `${locale}: expected one h1`);
        check(await page.locator("#report-text").count() === 1, `${locale}: missing labelled editor`);
        check(await page.locator(".editor-state").getAttribute("data-state") === "empty", `${locale}: empty editor state is inaccurate`);
        check((await page.locator("#editor-state-text").innerText()).length > 0, `${locale}: editor state needs visible guidance`);
        check(await page.locator("#remove-file").isHidden(), `${locale}: file removal should stay hidden without a selected file`);
        check(await page.locator("#results-stale").isHidden(), `${locale}: empty home page must not claim results are stale`);
        check(
          await page.evaluate(() => document.activeElement?.id) !== "results-heading",
          `${locale}/${width}: idle page must not steal focus to the results heading`,
        );
        check(await page.locator('label[for="report-text"]').count() === 1, `${locale}: textarea label missing`);
        check(await page.locator("header").count() === 1 && await page.locator("main").count() === 1, `${locale}: landmarks missing`);
        const metrics = await page.evaluate(() => ({
          viewportWidth: document.documentElement.clientWidth,
          documentWidth: document.documentElement.scrollWidth,
        }));
        verifyNoHorizontalOverflow(metrics, `${locale}/${width}`);
        responsiveMeasurements.push({ locale, width, ...metrics });
        await verifyTouchTargets(page, `${locale}/${width}px locale links`, [
          ["English locale link", 'a[hreflang="en"]'],
          ["French locale link", 'a[hreflang="fr"]'],
        ]);
        if (width === 320 || width === 390) {
          await verifyTouchTargets(page, `${locale}/${width}px home`, [
            ["English locale link", 'a[hreflang="en"]'],
            ["French locale link", 'a[hreflang="fr"]'],
            ["document-language selector", "#content-language"],
            ["upload picker label", 'label[for="report-file"]'],
            ["source format select", "#source-format"],
            ["fictional example action", "#load-example"],
            ["clear input", "#clear-text"],
            ["audit submit", 'button[formaction="/audit"]'],
            ["revision submit", 'button[formaction="/revise"]'],
          ]);
        }
        if (locale === "en" && width === 1440) {
          axePasses += await verifyA11y(page, "English home");
          await page.screenshot({ path: path.join(screenshotDir, "home-desktop.png") });
        }
        if (locale === "en" && width === 390) {
          await page.screenshot({ path: path.join(screenshotDir, "home-mobile.png") });
        }
        if (locale === "fr" && width === 390) {
          axePasses += await verifyA11y(page, "French home");
        }
      }
    }

    console.log("[browser] home matrix passed; start keyboard/history, sample, audit and revision flows");
    // Focus order starts at the skip link; locale GET navigation supports back/forward.
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.goto(`${baseUrl}/?locale=en`, { waitUntil: "networkidle" });
    await page.keyboard.press("Tab");
    check(
      await page.evaluate(() => document.activeElement?.getAttribute("href")) === "#main-content",
      "the first keyboard stop should be the skip link",
    );
    await page.locator('a[hreflang="fr"]').click();
    check(await page.locator("html").getAttribute("lang") === "fr", "FR link did not navigate");
    await page.goBack({ waitUntil: "networkidle" });
    check(await page.locator("html").getAttribute("lang") === "en", "browser back did not restore EN");
    await page.goForward({ waitUntil: "networkidle" });
    check(await page.locator("html").getAttribute("lang") === "fr", "browser forward did not restore FR");

    // At 640 CSS pixels, a 1280-pixel viewport viewed at 200% would reflow to
    // this effective width. This checks reflow, not browser zoom UI itself.
    await page.setViewportSize({ width: 640, height: 900 });
    await page.goto(`${baseUrl}/?locale=fr`, { waitUntil: "networkidle" });
    check(await page.locator("#load-example").isVisible(), "French sample action should be visible after enhancement");
    check((await page.locator("#load-example").innerText()).includes("Essayer l’exemple fictif"), "French sample action label is incorrect");
    check(await page.locator("#copy-sample").isHidden(), "the manual-copy fallback should hide when the French sample action is enhanced");
    verifyNoHorizontalOverflow(
      await page.evaluate(() => ({
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
      })),
      "FR/640 CSS px (200% reflow proxy)",
    );

    // Check sample-loading is opt-in and must confirm before replacing a draft.
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.goto(`${baseUrl}/?locale=en`, { waitUntil: "networkidle" });
    const editor = page.locator("#report-text");
    const loadExample = page.locator("#load-example");
    check((await editor.inputValue()) === "", "the initial page must not preload sample text");
    check(await loadExample.isVisible(), "the sample action should be visible after JavaScript enhancement");
    check((await loadExample.innerText()).includes("Try fictional example"), "English sample action label is incorrect");
    check(await page.locator("#copy-sample").isHidden(), "the manual-copy fallback should hide when the English sample action is enhanced");
    await loadExample.click();
    const example = await editor.inputValue();
    check(example.length > 0, "the explicit synthetic-example action did not load text");
    await editor.fill("My own synthetic draft must be preserved until I confirm.");
    let dismissedDialogType;
    page.once("dialog", async (dialog) => {
      dismissedDialogType = dialog.type();
      await dialog.dismiss();
    });
    await loadExample.click();
    check(dismissedDialogType === "confirm", "replacing non-empty text must use a confirmation");
    check(
      (await editor.inputValue()) === "My own synthetic draft must be preserved until I confirm.",
      "dismissing example replacement discarded existing text",
    );
    let acceptedDialogType;
    page.once("dialog", async (dialog) => {
      acceptedDialogType = dialog.type();
      await dialog.accept();
    });
    await loadExample.click();
    check(acceptedDialogType === "confirm", "the replacement confirmation was not presented");
    check((await editor.inputValue()) === example, "confirming replacement did not load the example");

    await page.locator("#source-format").selectOption("tex");
    await page.locator("#report-file").setInputFiles({
      name: "synthetic-upload.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("SYNTHETIC TEST — file selection only; no personal content."),
    });
    check(await page.locator("#source-format").isDisabled(), "source format should be locked to the selected upload format");
    check(await page.locator("#source-format").inputValue() === "txt", "file extension should set the effective upload format");
    await page.locator("#remove-file").click();
    check((await editor.inputValue()) === example, "removing an upload discarded pasted text");
    check(await page.locator("#source-format").inputValue() === "tex", "removing an upload did not restore the pasted format");
    check(await page.locator("#source-format").isEnabled(), "pasted format should be enabled after removing a file");

    let clearDismissed;
    page.once("dialog", async (dialog) => {
      clearDismissed = dialog.type();
      await dialog.dismiss();
    });
    await page.locator("#clear-text").click();
    check(clearDismissed === "confirm", "clearing existing text should require confirmation");
    check((await editor.inputValue()) === example, "canceling Clear discarded the draft");
    let clearAccepted;
    page.once("dialog", async (dialog) => {
      clearAccepted = dialog.type();
      await dialog.accept();
    });
    await page.locator("#clear-text").click();
    check(clearAccepted === "confirm", "Clear did not show its confirmation");
    check((await editor.inputValue()) === "", "confirmed Clear did not empty the editor");
    check(await page.locator(".editor-state").getAttribute("data-state") === "empty", "Clear did not restore the empty state");
    check(await page.locator("#results-stale").isHidden(), "editing the home page should not mark nonexistent results stale");

    const baseline = fs.readFileSync(path.join(syntheticDir, "baseline_en.txt"), "utf8");
    await editor.fill(baseline);
    const auditResponse = page.waitForNavigation({ waitUntil: "networkidle" });
    await page.locator('button[formaction="/audit"]').click();
    const auditNavigation = await auditResponse;
    const auditHeaders = auditNavigation ? await auditNavigation.request().allHeaders() : {};
    const formInfo = await page.locator("#report-form").evaluate((form) => ({
      action: form.action,
      method: form.method,
      target: form.target,
      baseURI: document.baseURI,
      isMainFrame: window === window.top,
      sandbox: window.frameElement?.getAttribute("sandbox") ?? null,
    }));
    check(
      auditNavigation && auditNavigation.status() === 200,
      `sample audit POST failed (${auditNavigation?.status() ?? "no response"}, origin=${auditHeaders.origin ?? "missing"}, referer=${auditHeaders.referer ?? "missing"}, fetch=${auditHeaders["sec-fetch-site"] ?? "missing"}, host=${auditHeaders.host ?? "missing"}, page=${await page.evaluate(() => location.origin)}, form=${JSON.stringify(formInfo)}): ${(await page.locator("body").innerText()).slice(0, 600)}`,
    );
    check(await page.locator("#signals-heading").count() === 1, "audit results did not render");
    check((await editor.inputValue()) === baseline, "review response failed to preserve the submitted draft");
    check(
      (await page.locator("body").innerText()).includes(
        "does not check factual claims, bibliography entries or source contents",
      ),
      "results omitted the factual and source-check limitation",
    );
    check(
      await page.evaluate(() => document.activeElement?.id) === "results-heading",
      "audit response did not focus the results heading",
    );
    await editor.fill(`${baseline}\nA synthetic local edit makes these results stale.`);
    check(await page.locator("#results-stale").isVisible(), "editing a result page must mark its existing results stale");
    await editor.fill(baseline);
    axePasses += await verifyA11y(page, "English audit results");
    await page.screenshot({ path: path.join(screenshotDir, "synthetic-result-en-1440.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await verifyTouchTargets(page, "EN/390px audit results", [
      ["cleaned text download", '[data-download="cleaned"]'],
    ]);
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    });
    await page.screenshot({ path: path.join(screenshotDir, "sample-review.png"), fullPage: true });
    await page.screenshot({ path: path.join(screenshotDir, "synthetic-result-en-390.png"), fullPage: true });

    const revisionNavigation = page.waitForNavigation({ waitUntil: "networkidle" });
    await page.locator('button[formaction="/revise"]').click();
    check((await revisionNavigation)?.status() === 200, "JavaScript-enabled revision POST failed");
    check(await page.locator("#changes-heading").count() === 1, "revision result did not render");
    check(
      await page.evaluate(() => document.activeElement?.id) === "results-heading",
      "revision response did not focus the results heading",
    );

    // A second, explicitly synthetic LaTeX example demonstrates repetition,
    // formulaic phrasing, and human source-check prompts without real metrics.
    const findingsContext = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    const findingsPage = await findingsContext.newPage();
    findingsPage.setDefaultTimeout(15000);
    findingsPage.setDefaultNavigationTimeout(20000);
    await installPageDiagnostics(findingsPage, runtimeErrors, externalRequests, httpErrors);
    await findingsPage.goto(`${baseUrl}/?locale=en`, { waitUntil: "networkidle" });
    const findingsFixture = fs.readFileSync(path.join(syntheticDir, "review_prompts_en.tex"));
    await findingsPage.locator("#report-file").setInputFiles({
      name: "synthetic_review_prompts.tex",
      mimeType: "text/x-tex",
      buffer: findingsFixture,
    });
    const findingsNavigation = findingsPage.waitForNavigation({ waitUntil: "networkidle" });
    await findingsPage.locator('button[formaction="/audit"]').click();
    check((await findingsNavigation)?.status() === 200, "synthetic findings example audit failed");
    const findingsText = await findingsPage.locator("body").innerText();
    check(findingsFixture.toString("utf8").startsWith("SYNTHETIC TEST"), "findings fixture must identify itself as synthetic");
    check(findingsText.includes("synthetic_review_prompts.tex"), "findings example source name was lost");
    check(
      findingsText.includes("The same first two words begin at least three sentences."),
      "findings example did not show the repeated-opening explanation",
    );
    check(
      findingsText.includes("Check that the cited work supports this specific statement"),
      "findings example did not show the citation-context prompt",
    );
    const reviewFilters = findingsPage.locator("#review-filters");
    check(await reviewFilters.isVisible(), "categorized findings should reveal the filter controls with JavaScript");
    check(await findingsPage.locator('#review-filters [data-review-filter="all"]').getAttribute("aria-pressed") === "true", "All should be the initial pressed filter");
    const writingCards = findingsPage.locator('.prompt-card[data-review-category="writing"]');
    const sourceCards = findingsPage.locator('.prompt-card[data-review-category="source"]');
    check((await writingCards.count()) > 0 && (await sourceCards.count()) > 0, "synthetic fixture needs both prompt categories");
    await findingsPage.locator('#review-filters [data-review-filter="writing"]').click();
    check(await findingsPage.locator('#review-filters [data-review-filter="writing"]').getAttribute("aria-pressed") === "true", "writing filter did not update aria-pressed");
    check(await writingCards.first().isVisible(), "writing filter hid a writing prompt");
    check(await sourceCards.first().isHidden(), "writing filter should hide source prompts");
    check(await findingsPage.locator(".citation-card").first().getAttribute("hidden") === null, "filters must not add hidden state to the separate citation inventory");
    check((await findingsPage.locator("#filter-status").innerText()).includes("displayed prompts"), "filter status should explain the displayed subset");
    await findingsPage.locator('#review-filters [data-review-filter="source"]').click();
    check(await sourceCards.first().isVisible(), "source filter hid a source prompt");
    check(await writingCards.first().isHidden(), "source filter should hide writing prompts");
    await findingsPage.locator('#review-filters [data-review-filter="all"]').click();
    axePasses += await verifyA11y(findingsPage, "English synthetic findings example");
    // This annotation is intentionally screenshot-only: the real parser omits
    // comments/preamble from its result view, so label the captured evidence.
    await findingsPage.evaluate(() => {
      const note = document.createElement("aside");
      note.id = "synthetic-demo-annotation";
      note.setAttribute("aria-label", "Synthetic test fixture");
      note.textContent = "SYNTHETIC TEST · Fictional wording and citation cues · no real study or results";
      note.style.cssText = "box-sizing:border-box;margin:0 auto;padding:12px 24px;max-width:1280px;background:#f1e5c9;color:#27221a;border-bottom:1px solid #b99b61;font:600 14px/1.4 system-ui,sans-serif;letter-spacing:.02em";
      document.body.prepend(note);
    });
    await findingsPage.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    });
    await findingsPage.screenshot({ path: path.join(screenshotDir, "sample-findings.png"), fullPage: true });
    await findingsContext.close();

    // Capture native server-rendered EN/FR findings and rejected-upload layouts
    // at narrow and desktop widths. All submitted text and files are synthetic.
    console.log("[browser] primary flows passed; start localized result/error matrix");
    const localizedSamples = {
      en: "The results show a fictional increase (Smith, 2024).",
      fr: "Les résultats montrent une amélioration fictive (Martin, 2024).",
    };
    for (const locale of ["en", "fr"]) {
      for (const width of [1440, 390, 320]) {
        const localizedContext = await browser.newContext({
          javaScriptEnabled: false,
          viewport: { width, height: 960 },
        });
        const localizedPage = await localizedContext.newPage();
        localizedPage.setDefaultTimeout(15000);
        localizedPage.setDefaultNavigationTimeout(20000);
        await installPageDiagnostics(localizedPage, runtimeErrors, externalRequests, httpErrors);
        await localizedPage.goto(`${baseUrl}/?locale=${locale}`, { waitUntil: "networkidle" });
        await localizedPage.locator("#content-language").selectOption(locale);
        await localizedPage.locator("#report-text").fill(localizedSamples[locale]);
        const localizedAudit = localizedPage.waitForNavigation({ waitUntil: "networkidle" });
        await localizedPage.locator('button[formaction="/audit"]').click();
        check((await localizedAudit)?.status() === 200, `${locale}/${width}: synthetic audit failed`);
        check(await localizedPage.locator("html").getAttribute("lang") === locale, `${locale}: UI locale changed unexpectedly`);
        check(await localizedPage.locator("#content-language").inputValue() === locale, `${locale}: document language was not preserved`);
        check(await localizedPage.locator("#signals-heading").count() === 1, `${locale}: review result did not render`);
        const resultMetrics = await localizedPage.evaluate(() => ({
          viewportWidth: document.documentElement.clientWidth,
          documentWidth: document.documentElement.scrollWidth,
        }));
        verifyNoHorizontalOverflow(resultMetrics, `${locale}/${width}px synthetic result`);
        responsiveMeasurements.push({ locale, state: "audit-result", width, ...resultMetrics });
        if (width === 320 || width === 390) {
          await verifyTouchTargets(localizedPage, `${locale}/${width}px document language`, [
            ["document-language selector", "#content-language"],
          ]);
        }
        await localizedPage.screenshot({
          path: path.join(screenshotDir, `synthetic-result-${locale}-${width}.png`),
          fullPage: true,
        });
        console.log(`[browser] captured ${locale}/${width}px audit result`);

        await localizedPage.locator("#report-file").setInputFiles({
          name: "unsupported-synthetic.pdf",
          mimeType: "application/pdf",
          buffer: Buffer.from("%PDF synthetic unsupported file"),
        });
        const rejectedUpload = localizedPage.waitForNavigation({ waitUntil: "networkidle" });
        await localizedPage.locator('button[formaction="/audit"]').click();
        check((await rejectedUpload)?.status() === 415, `${locale}/${width}: invalid upload did not show a 415 form error`);
        check(await localizedPage.locator("#report-text").inputValue() === localizedSamples[locale], `${locale}: rejected upload lost pasted text`);
        check(await localizedPage.locator('[role="alert"]').count() === 1, `${locale}: upload error was not announced`);
        const summaryAlert = await localizedPage.locator('[role="alert"]').innerText();
        const inlineFileError = await localizedPage.locator("#file-error").innerText();
        check(!summaryAlert.includes(inlineFileError), `${locale}: file validation detail was duplicated in the summary alert`);
        check(await localizedPage.locator("#file-error").isVisible(), `${locale}: specific upload error was not linked inline`);
        const errorMetrics = await localizedPage.evaluate(() => ({
          viewportWidth: document.documentElement.clientWidth,
          documentWidth: document.documentElement.scrollWidth,
        }));
        verifyNoHorizontalOverflow(errorMetrics, `${locale}/${width}px synthetic error`);
        responsiveMeasurements.push({ locale, state: "upload-error", width, ...errorMetrics });
        await localizedPage.screenshot({
          path: path.join(screenshotDir, `synthetic-error-${locale}-${width}.png`),
          fullPage: true,
        });
        if (locale === "fr" && width === 390) {
          const retryText = "A synthetic retry file contains no personal draft.";
          await localizedPage.locator("#report-file").setInputFiles({
            name: "retry.txt",
            mimeType: "text/plain",
            buffer: Buffer.from(retryText),
          });
          const retryNavigation = localizedPage.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 15000 });
          await localizedPage.locator('button[formaction="/audit"]').click();
          check((await retryNavigation)?.status() === 200, "JavaScript-disabled retry after the French upload error failed");
          check((await localizedPage.locator("#report-text").inputValue()) === retryText, "valid no-JS retry lost its selected file text");
          check((await localizedPage.locator("body").innerText()).includes("retry.txt"), "valid no-JS retry lost its source name");
        }
        await localizedContext.close();
        console.log(`[browser] captured ${locale}/${width}px upload error; no overflow and field/error assertions passed`);
      }
    }

    // Reduced motion is a real media preference, not a device-scale emulation.
    const reducedContext = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 390, height: 844 } });
    const reducedPage = await reducedContext.newPage();
    await installPageDiagnostics(reducedPage, runtimeErrors, externalRequests, httpErrors);
    await reducedPage.goto(`${baseUrl}/?locale=en`, { waitUntil: "networkidle" });
    check(await reducedPage.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches), "reduced-motion preference was not active");
    const reducedMotionStyles = await reducedPage.evaluate(() => ({
      scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
      buttonTransitions: getComputedStyle(document.querySelector(".button-primary")).transitionDuration
        .split(",")
        .map((duration) => Number.parseFloat(duration)),
    }));
    check(reducedMotionStyles.scrollBehavior === "auto", "reduced motion should disable smooth scrolling");
    check(
      reducedMotionStyles.buttonTransitions.every((seconds) => seconds <= 0.00001),
      `reduced motion should minimize CSS transitions: ${reducedMotionStyles.buttonTransitions.join(", ")}`,
    );
    await reducedContext.close();

    // A failed optional script must leave the native form usable and helpers hidden.
    const failedScriptContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await failedScriptContext.route("**/static/app.js", (route) => route.fulfill({ status: 503, body: "unavailable" }));
    const failedScriptPage = await failedScriptContext.newPage();
    await failedScriptPage.goto(`${baseUrl}/?locale=en`, { waitUntil: "networkidle" });
    check(await failedScriptPage.locator("#load-example").isHidden(), "synthetic helper should remain hidden when its script fails");
    check(await failedScriptPage.locator("#copy-sample").isVisible(), "manual-copy fallback should remain when its script fails");
    check(await failedScriptPage.locator("#report-text").isVisible(), "native editor should remain visible when its script fails");
    await failedScriptContext.close();

    // JavaScript-disabled flow: native POST audit, revision, upload, and failed
    // upload recovery preserve the pasted text and accept a retry.
    const noJsContext = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
    const noJsPage = await noJsContext.newPage();
    await installPageDiagnostics(noJsPage, runtimeErrors, externalRequests, httpErrors);
    await noJsPage.goto(`${baseUrl}/?locale=fr`, { waitUntil: "networkidle" });
    check(await noJsPage.locator("html").getAttribute("lang") === "fr", "French no-JS page failed");
    check(await noJsPage.locator("#load-example").isHidden(), "sample control should stay hidden without JavaScript");
    check(await noJsPage.locator("#copy-sample").isVisible(), "manual-copy fallback should remain without JavaScript");
    await noJsPage.locator("#report-text").fill("This chapter presents a fictional method. The sample contains no real research claim.");
    // Native POST acceptance depends on the document arriving, not every
    // optional asset reaching an idle-network heuristic.
    let navigation = noJsPage.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 15000 });
    await noJsPage.locator('button[formaction="/audit"]').click();
    check((await navigation)?.status() === 200, "JavaScript-disabled native audit POST failed");
    check(await noJsPage.locator("#signals-heading").count() === 1, "no-JS audit results did not render");
    verifyNoHorizontalOverflow(
      await noJsPage.evaluate(() => ({
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
      })),
      "FR/390px audit results",
    );
    await noJsPage.setViewportSize({ width: 320, height: 844 });
    verifyNoHorizontalOverflow(
      await noJsPage.evaluate(() => ({
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
      })),
      "FR/320px audit results",
    );

    await noJsPage.locator("#report-file").setInputFiles({
      name: "synthetic_review_prompts.tex",
      mimeType: "text/x-tex",
      buffer: findingsFixture,
    });
    navigation = noJsPage.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 15000 });
    await noJsPage.locator('button[formaction="/audit"]').click();
    check((await navigation)?.status() === 200, "JavaScript-disabled synthetic findings audit failed");
    check(await noJsPage.locator("#review-filters").count() === 1, "categorized no-JS result omitted the progressive enhancement group");
    check(await noJsPage.locator("#review-filters").isHidden(), "filters should remain hidden without JavaScript");
    check((await noJsPage.locator(".prompt-card[data-review-category]").count()) > 0, "no-JS prompts should remain visible without filters");

    await noJsPage.locator("#report-text").fill("This chapter presents a fictional method with \cite{synthetic-key}.");
    navigation = noJsPage.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 15000 });
    await noJsPage.locator('button[formaction="/revise"]').click();
    check((await navigation)?.status() === 200, "JavaScript-disabled native revision POST failed");
    check(await noJsPage.locator("#changes-heading").count() === 1, "no-JS revision preview did not render");
    verifyNoHorizontalOverflow(
      await noJsPage.evaluate(() => ({
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
      })),
      "FR/320px revision results",
    );
    await noJsPage.setViewportSize({ width: 390, height: 844 });

    const texContent = fs.readFileSync(path.join(syntheticDir, "citation_cues.tex"));
    await noJsPage.locator("#report-file").setInputFiles({
      name: "citation_cues.tex",
      mimeType: "text/x-tex",
      buffer: texContent,
    });
    navigation = noJsPage.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 15000 });
    await noJsPage.locator('button[formaction="/audit"]').click();
    check((await navigation)?.status() === 200, "JavaScript-disabled TeX upload failed");
    check((await noJsPage.locator("body").innerText()).includes("citation_cues.tex"), "uploaded source name was lost");

    await noJsContext.close();

    check(externalRequests.length === 0, `unexpected third-party request(s): ${externalRequests.join(", ")}`);
    check(runtimeErrors.length === 0, `browser runtime errors: ${runtimeErrors.join(" | ")}`);
    const unexpectedHttpErrors = httpErrors.filter(({ status, pathname }) =>
      !(status === 404 && pathname === "/favicon.ico") && !(status === 415 && pathname === "/audit"),
    );
    check(
      unexpectedHttpErrors.length === 0,
      `unexpected HTTP error responses: ${unexpectedHttpErrors.map(({ status, pathname }) => `${status} ${pathname}`).join(", ")}`,
    );
    console.log(`Browser smoke passed: EN/FR ${viewports.join("/")}px, 640px reflow proxy, 44px touch targets, keyboard, history, reduced motion, JS-off audit/revision/upload/error/retry, axe checks (${axePasses} passing rules). Screenshots: ${screenshotDir}`);
    console.log(`Responsive widths: ${JSON.stringify(responsiveMeasurements)}`);
    console.log(`Touch bounds: ${JSON.stringify(touchMeasurements)}`);
  } finally {
    clearTimeout(hardDeadline);
    await browser.close();
  }
}

main().catch((error) => {
  clearTimeout(hardDeadline);
  console.error(error.stack || error);
  process.exitCode = 1;
});
