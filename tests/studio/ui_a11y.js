/* Accessibility gate: walks the three studio screens in a real browser and
   fails if any text falls below WCAG AA or any control is smaller than a
   comfortable touch target.

   Run against a live studio:
     npm i puppeteer-core @sparticuz/chromium
     node tests/studio/ui_a11y.js
   Set CHROME_PATH to use a locally installed Chromium instead. */
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://127.0.0.1:8000";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MIN_TARGET = 32;

async function launch() {
  const options = { headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"],
                    defaultViewport: { width: 1440, height: 1000, deviceScaleFactor: 1 } };
  if (process.env.CHROME_PATH) return puppeteer.launch({ ...options, executablePath: process.env.CHROME_PATH });
  const chromium = require("@sparticuz/chromium").default;
  return puppeteer.launch({ ...options, executablePath: await chromium.executablePath(), args: [...chromium.args, "--no-sandbox"] });
}

const parse = (c) => {
  const m = String(c).match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
  return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null;
};
const lum = ({ r, g, b }) => {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const over = (fg, bg) => ({
  r: fg.r * fg.a + bg.r * (1 - fg.a),
  g: fg.g * fg.a + bg.g * (1 - fg.a),
  b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1,
});
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const AUDIT = () => {
  const out = { text: [], targets: [] };
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    if (!el || seen.has(el)) continue;
    seen.add(el);
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || +cs.opacity === 0) continue;
    if (el.closest("[hidden]")) continue;
    let bgEl = el, bg = null, gradient = null;
    while (bgEl) {
      const pcs = getComputedStyle(bgEl);
      if (pcs.backgroundImage && pcs.backgroundImage.includes("gradient")) {
        const stops = [...pcs.backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map((m) => m[0]);
        if (stops.length) { gradient = stops; bg = stops[0]; break; }
      }
      const c = pcs.backgroundColor;
      if (c && !c.startsWith("rgba(0, 0, 0, 0)")) { bg = c; break; }
      bgEl = bgEl.parentElement;
    }
    out.text.push({
      text: node.textContent.trim().slice(0, 42), color: cs.color, bg: bg || "rgb(8, 8, 10)",
      gradient, size: parseFloat(cs.fontSize), weight: cs.fontWeight,
      tag: el.tagName + (el.className ? "." + String(el.className).split(" ")[0] : ""),
    });
  }
  document.querySelectorAll("button, a, [role=tab], input, select, textarea").forEach((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === "hidden" || cs.display === "none") return;
    if (el.closest("[hidden]")) return;
    if (r.width < 32 || r.height < 32) {
      out.targets.push({ tag: el.tagName, cls: String(el.className).slice(0, 30),
                         w: Math.round(r.width), h: Math.round(r.height),
                         text: (el.textContent || "").trim().slice(0, 24) });
    }
  });
  return out;
};

(async () => {
  const browser = await launch();
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(BASE + "/", { waitUntil: "networkidle2" });
  await sleep(1500);

  const screens = [
    ["create", async () => {
      await page.goto(BASE + "/", { waitUntil: "networkidle2" });
      await sleep(1500);
    }],
    ["library", async () => {
      await page.click("[data-nav=library]");
      await sleep(1400);
    }],
  ];
  // only audit the project screen when there is real work to open
  await page.goto(BASE + "/", { waitUntil: "networkidle2" });
  await sleep(1200);
  await page.click("[data-nav=library]");
  await sleep(1400);
  if (await page.$("[data-open]")) {
    screens.push(["project", async () => {
      const tile = await page.$("[data-open]");
      if (tile) { await tile.click(); await sleep(2200); }
    }]);
  }

  let problems = 0;
  await page.click("[data-nav=create]");
  await sleep(900);
  screens.unshift(["create", null]);

  for (const [name, before] of screens) {
    if (before) await before();
    await sleep(900);
    const data = await page.evaluate(AUDIT);
    const low = [];
    for (const t of data.text) {
      const fg = parse(t.color), bg = parse(t.bg);
      if (!fg || !bg) continue;
      const bgS = bg.a < 1 ? over(bg, { r: 8, g: 8, b: 10, a: 1 }) : bg;
      let r = ratio(over(fg, bgS), bgS);
      if (t.gradient) {
        for (const stop of t.gradient) {
          const g = parse(stop);
          if (!g) continue;
          const gs = g.a < 1 ? over(g, { r: 8, g: 8, b: 10, a: 1 }) : g;
          r = Math.min(r, ratio(over(fg, gs), gs));
        }
      }
      const large = t.size >= 24 || (t.size >= 18.66 && +t.weight >= 700);
      if (r < (large ? 3 : 4.5)) low.push(`${r.toFixed(2)} "${t.text}" (${t.tag})`);
    }
    const small = data.targets.filter((t) => Math.min(t.w, t.h) < MIN_TARGET);
    problems += low.length + small.length;
    console.log(`${name}: ${data.text.length} text nodes · ${low.length} below AA · ${small.length} undersized targets`);
    low.slice(0, 6).forEach((l) => console.log("   LOW  ", l));
    small.slice(0, 6).forEach((t) => console.log("   SMALL", JSON.stringify(t)));
  }
  if (errors.length) { console.log("script errors:", errors.slice(0, 4)); problems += errors.length; }

  await browser.close();
  console.log(problems === 0 ? "\nPASS — AA contrast and touch targets hold on every screen"
                             : `\nFAIL — ${problems} accessibility problem(s)`);
  process.exit(problems === 0 ? 0 : 1);
})().catch((e) => { console.error("harness crashed:", e.message); process.exit(2); });
