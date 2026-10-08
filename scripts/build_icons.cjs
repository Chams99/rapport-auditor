/*
 * Renders the brand mark (apps/web/rapport_web/static/favicon.svg) to the raster
 * icons browsers and phones expect. Re-run after changing the mark.
 * Usage: node scripts/build_icons.cjs   (RAPPORT_AUDITOR_CHROME=<path> to use an installed Chrome)
 */
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const staticDir = path.join(root, "apps", "web", "rapport_web", "static");
const brandDir = path.join(root, "docs", "portfolio", "brand");
const mark = fs.readFileSync(path.join(staticDir, "favicon.svg"), "utf8");

// Phone home-screen icons are masked by the OS, so they need a full-bleed square
// with the glyph inset rather than the rounded tile.
const fullBleed = mark
  .replace(/<rect width="32" height="32" rx="8" fill="#4b3fc4"\/>/, '<rect width="32" height="32" fill="#4b3fc4"/>')
  .replace(/(<rect width="32" height="32" fill="#4b3fc4"\/>)([\s\S]*)<\/svg>/, '$1<g transform="translate(16 16) scale(1.05) translate(-17 -16)">$2</g></svg>');

async function render(page, svg, size) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<html><body style="margin:0;background:transparent">${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}</body></html>`);
  return page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}

// An .ico container may hold PNG images directly: 6-byte header, 16 bytes per entry.
function buildIco(images) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = 6 + 16 * images.length;
  const entries = images.map(({ size, data }) => {
    const entry = Buffer.alloc(16);
    entry.writeUInt8(size >= 256 ? 0 : size, 0);
    entry.writeUInt8(size >= 256 ? 0 : size, 1);
    entry.writeUInt16LE(1, 4);
    entry.writeUInt16LE(32, 6);
    entry.writeUInt32LE(data.length, 8);
    entry.writeUInt32LE(offset, 12);
    offset += data.length;
    return entry;
  });
  return Buffer.concat([header, ...entries, ...images.map(({ data }) => data)]);
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.RAPPORT_AUDITOR_CHROME || undefined });
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  const icoImages = [];
  for (const size of [16, 32, 48]) icoImages.push({ size, data: await render(page, mark, size) });
  fs.writeFileSync(path.join(staticDir, "favicon.ico"), buildIco(icoImages));
  fs.writeFileSync(path.join(staticDir, "apple-touch-icon.png"), await render(page, fullBleed, 180));
  fs.mkdirSync(brandDir, { recursive: true });
  fs.copyFileSync(path.join(staticDir, "favicon.svg"), path.join(brandDir, "logo-mark.svg"));
  fs.writeFileSync(path.join(brandDir, "logo-mark-512.png"), await render(page, mark, 512));
  fs.writeFileSync(path.join(brandDir, "app-icon-1024.png"), await render(page, fullBleed, 1024));
  await browser.close();
  console.log("Icons written to", path.relative(root, staticDir), "and", path.relative(root, brandDir));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
