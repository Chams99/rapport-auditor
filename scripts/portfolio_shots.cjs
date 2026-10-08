/*
 * Portfolio assets: retina screenshots, a cover image, a social preview card and
 * a short demo video, all made from the running app with fictional text.
 *
 * Usage (from the repository root, with the app running):
 *   node scripts/portfolio_shots.cjs
 * Environment:
 *   PORTFOLIO_BASE_URL   app to capture (default http://127.0.0.1:5000); use your deployed URL after launch
 *   PORTFOLIO_OUT        output folder (default docs/portfolio)
 *   RAPPORT_AUDITOR_CHROME  path to an installed Chrome, if Playwright's own browser is not installed
 */
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const base = (process.env.PORTFOLIO_BASE_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const out = path.resolve(process.env.PORTFOLIO_OUT || path.join(root, "docs", "portfolio"));
const screens = path.join(out, "screens");
// Show the real domain once deployed; a local address says nothing to a visitor.
const shownHost = /^(localhost|127\.|\[::1\])/.test(new URL(base).host) ? "Rapport Auditor" : new URL(base).host;

// Fictional chapter excerpt: no real study, data or source.
const draft = [
  "This chapter presents the design of a fictional campus energy dashboard. This chapter presents the data pipeline and the evaluation protocol. This chapter presents the main limitations of the prototype.",
  "The results show that weekly energy use in the pilot building fell after the dashboard was introduced, which suggests that real-time feedback can change everyday habits when it is combined with clear goals, regular reminders and an interface that every member of staff can understand without any prior training.",
  "It is worth noting that the pilot only covered one building and a single semester.",
  "The survey found that most participants checked the dashboard at least once a week (Martin, 2024).",
  "In order to validate the approach, a second pilot is planned for the next academic year, and the evaluation protocol will be extended to two additional buildings.",
].join("\n");
const draftFile = { name: "chapter3_evaluation.txt", mimeType: "text/plain", buffer: Buffer.from(draft) };

async function openReview(page, mode = "audit") {
  await page.goto(`${base}/?locale=en`, { waitUntil: "networkidle" });
  await page.locator("#report-file").setInputFiles(draftFile);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle" }),
    page.locator(`button[formaction="/${mode}"]`).click(),
  ]);
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
}

async function shoot(browser, name, { width, height, scale = 2, scheme = "light", setup }) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale, colorScheme: scheme, reducedMotion: "reduce" });
  const page = await context.newPage();
  await setup(page);
  await page.waitForTimeout(300);
  const file = path.join(screens, `${name}.png`);
  await page.screenshot({ path: file });
  await context.close();
  return file;
}

const dataUri = (file) => `data:image/png;base64,${fs.readFileSync(file).toString("base64")}`;
const logoSvg = fs.readFileSync(path.join(root, "apps", "web", "rapport_web", "static", "favicon.svg"), "utf8");

// A neutral browser frame and phone frame around real screenshots.
const composition = ({ desktop, mobile, width, height, title, tagline, bullets }) => `<!doctype html><html><head><style>
  * { box-sizing: border-box; margin: 0; }
  body { width: ${width}px; height: ${height}px; overflow: hidden; background: #efedf8; font-family: "Segoe UI", system-ui, sans-serif; color: #1c1b2b; position: relative; }
  .glow { position: absolute; inset: 0; background: radial-gradient(1200px 600px at 80% 0%, #dcd8fb 0%, transparent 60%), radial-gradient(900px 500px at 0% 100%, #f6f4ef 0%, transparent 60%); }
  .brand { position: absolute; display: flex; align-items: center; gap: 14px; }
  .brand svg { width: 48px; height: 48px; }
  .brand b { font-size: 22px; letter-spacing: -0.01em; }
  .copy { position: absolute; display: grid; gap: 24px; }
  h1 { font-family: "Palatino Linotype", Georgia, serif; font-weight: 400; letter-spacing: -0.02em; line-height: 1.08; }
  .tag { color: #555366; line-height: 1.5; }
  ul { list-style: none; padding: 0; display: grid; gap: 10px; color: #1c1b2b; }
  li { display: flex; gap: 10px; align-items: center; }
  li i { width: 8px; height: 8px; border-radius: 50%; background: #4b3fc4; flex: none; }
  .browser { position: absolute; border-radius: 14px; overflow: hidden; background: #fff; box-shadow: 0 40px 80px -30px rgba(40,30,110,.45), 0 0 0 1px rgba(28,27,43,.08); }
  .bar { height: 40px; display: flex; align-items: center; gap: 8px; padding: 0 16px; background: #f4f3f7; border-bottom: 1px solid #e2dfe7; }
  .bar span { width: 12px; height: 12px; border-radius: 50%; background: #d9d6e2; }
  .bar div { margin-left: 16px; flex: 1; max-width: 420px; height: 24px; border-radius: 6px; background: #fff; border: 1px solid #e2dfe7; font-size: 12px; color: #77748a; display: flex; align-items: center; padding: 0 10px; }
  .browser img, .phone img { display: block; width: 100%; }
  .phone { position: absolute; border-radius: 44px; padding: 12px; background: #1c1b2b; box-shadow: 0 40px 80px -30px rgba(20,15,60,.6); }
  .phone img { border-radius: 32px; }
</style></head><body><div class="glow"></div>
${title ? `<div class="brand" style="left:72px;top:64px">${logoSvg}<b>Rapport Auditor</b></div>
<div class="copy" style="left:72px;top:${Math.max(Math.round(height * 0.17), 170)}px;width:${Math.round(width * 0.33)}px">
<h1 style="font-size:${Math.round(width / 28)}px">${title}</h1>
<p class="tag" style="font-size:${Math.round(width / 80)}px">${tagline}</p>
${bullets ? `<ul style="font-size:${Math.round(width / 95)}px">${bullets.map((b) => `<li><i></i>${b}</li>`).join("")}</ul>` : ""}
</div>` : ""}
<div class="browser" style="${desktop.style}"><div class="bar"><span></span><span></span><span></span><div>${shownHost}</div></div><img src="${desktop.src}"></div>
${mobile ? `<div class="phone" style="${mobile.style}"><img src="${mobile.src}"></div>` : ""}
</body></html>`;

async function compose(browser, name, html, width, height) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 });
  await page.setContent(html, { waitUntil: "load" });
  await page.screenshot({ path: path.join(out, `${name}.png`) });
  await page.close();
}

async function recordDemo(browser) {
  const videoDir = path.join(out, ".video-tmp");
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } },
    bypassCSP: true, // only to draw a visible cursor in the recording
  });
  await context.addInitScript(() => {
    window.addEventListener("DOMContentLoaded", () => {
      const dot = document.createElement("div");
      dot.style.cssText = "position:fixed;z-index:9999;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(75,63,196,.35);border:2px solid #4b3fc4;pointer-events:none;transition:transform .12s;left:-40px;top:-40px";
      document.body.append(dot);
      addEventListener("mousemove", (event) => { dot.style.left = `${event.clientX}px`; dot.style.top = `${event.clientY}px`; });
      addEventListener("mousedown", () => { dot.style.transform = "scale(.7)"; });
      addEventListener("mouseup", () => { dot.style.transform = "scale(1)"; });
    });
  });
  const page = await context.newPage();
  const glide = async (locator) => {
    const box = await locator.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 });
    await page.waitForTimeout(250);
    await locator.click();
  };
  await page.goto(`${base}/?locale=en`, { waitUntil: "networkidle" });
  await page.mouse.move(700, 450);
  await page.waitForTimeout(900);
  const editor = page.locator("#report-text");
  await glide(editor);
  await page.keyboard.type(draft.slice(0, 74), { delay: 28 });
  await editor.fill(draft);
  await page.waitForTimeout(700);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle" }), glide(page.locator('button[formaction="/audit"]'))]);
  await page.waitForTimeout(1600);
  await glide(page.locator("button.type-row", { hasText: "Stock phrase" }));
  await page.waitForTimeout(1200);
  await glide(page.locator(".finding-card:not([hidden]) .line-link").first());
  await page.waitForTimeout(1500);
  await glide(page.locator(".finding-card:not([hidden]) .review-toggle").first());
  await page.waitForTimeout(1000);
  await glide(page.locator("[data-show-all]"));
  await page.waitForTimeout(800);
  await page.mouse.move(1000, 600, { steps: 15 });
  for (let i = 0; i < 6; i += 1) { await page.mouse.wheel(0, 220); await page.waitForTimeout(260); }
  await page.waitForTimeout(600);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle" }), glide(page.locator('button[formaction="/revise"]'))]);
  await page.waitForTimeout(2200);
  await page.mouse.move(1000, 600, { steps: 15 });
  for (let i = 0; i < 4; i += 1) { await page.mouse.wheel(0, 220); await page.waitForTimeout(300); }
  await page.waitForTimeout(1200);
  const video = page.video();
  await context.close();
  await video.saveAs(path.join(out, "demo.webm"));
  fs.rmSync(videoDir, { recursive: true, force: true });
}

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.RAPPORT_AUDITOR_CHROME || undefined });

  const desktop = { width: 1440, height: 900 };
  const phone = { width: 390, height: 844, scale: 3 };
  const reviewLight = await shoot(browser, "desktop-review-light", { ...desktop, setup: (page) => openReview(page) });
  await shoot(browser, "desktop-review-dark", { ...desktop, scheme: "dark", setup: (page) => openReview(page) });
  await shoot(browser, "desktop-filtered-light", {
    ...desktop,
    setup: async (page) => {
      await openReview(page);
      await page.locator("button.type-row", { hasText: "Source check" }).click();
      await page.locator(".finding-card:not([hidden]) .line-link").first().click();
    },
  });
  await shoot(browser, "desktop-home-light", { ...desktop, setup: (page) => page.goto(`${base}/?locale=en`, { waitUntil: "networkidle" }) });
  await shoot(browser, "desktop-revision-light", { ...desktop, setup: (page) => openReview(page, "revise") });
  await shoot(browser, "desktop-home-fr-dark", { ...desktop, scheme: "dark", setup: (page) => page.goto(`${base}/?locale=fr`, { waitUntil: "networkidle" }) });
  await shoot(browser, "desktop-about-light", { ...desktop, setup: (page) => page.goto(`${base}/about?locale=en`, { waitUntil: "networkidle" }) });
  const mobileReview = await shoot(browser, "mobile-review-light", { ...phone, setup: (page) => openReview(page) });
  await shoot(browser, "mobile-home-light", { ...phone, setup: (page) => page.goto(`${base}/?locale=en`, { waitUntil: "networkidle" }) });
  await shoot(browser, "mobile-review-dark", { ...phone, scheme: "dark", setup: (page) => openReview(page) });

  await compose(browser, "cover-1600x1000", composition({
    width: 1600, height: 1000,
    title: "Make the next draft clearer.",
    tagline: "A bilingual review desk for academic writing: repetition, dense sentences and claims that need a visible source.",
    bullets: ["English and French rule sets", "Every prompt linked to its passage", "Runs locally; drafts are not stored"],
    desktop: { src: dataUri(reviewLight), style: "left:600px;top:140px;width:940px" },
    mobile: { src: dataUri(mobileReview), style: "left:1320px;top:400px;width:236px" },
  }), 1600, 1000);
  await compose(browser, "social-1200x630", composition({
    width: 1200, height: 630,
    title: "Make the next draft clearer.",
    tagline: "Bilingual review prompts for academic writing.",
    desktop: { src: dataUri(reviewLight), style: "left:580px;top:110px;width:720px" },
  }), 1200, 630);
  await compose(browser, "devices-1600x1000", composition({
    width: 1600, height: 1000,
    desktop: { src: dataUri(reviewLight), style: "left:90px;top:110px;width:1180px" },
    mobile: { src: dataUri(mobileReview), style: "left:1190px;top:250px;width:310px" },
  }), 1600, 1000);

  await recordDemo(browser);
  await browser.close();
  console.log(`Portfolio assets written to ${path.relative(root, out) || out} (captured from ${base})`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
