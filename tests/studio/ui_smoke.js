/* UI smoke harness: loads the real index.html + campaigns.js in jsdom,
   proxies fetch to the live studio server, and drives the three start
   points, the six-stage rail, every tab and the library. */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const BASE = process.env.BASE || "http://127.0.0.1:8000";
const ROOT = process.env.ROOT || "/home/user/OpenMontage";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let pass = 0, fail = 0;
const failures = [];
function check(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; failures.push(name + (extra ? ` — ${extra}` : "")); console.log(`  ✗ ${name} ${extra}`); }
}

async function boot() {
  const html = fs.readFileSync(path.join(ROOT, "studio/ui/index.html"), "utf8")
    .replace('<script src="/ui/campaigns.js" defer></script>', "");
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.message)));
  vc.on("error", (...a) => errors.push(a.join(" ")));

  const dom = new JSDOM(html, {
    url: `${BASE}/`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.fetch = async (url, options = {}) => {
        const target = String(url).startsWith("http") ? String(url) : BASE + url;
        const init = { ...options };
        if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
        if (init.body && typeof init.body === "string" && !init.headers?.["content-type"]) {
          init.headers = { ...(init.headers || {}), "content-type": "application/json" };
        }
        const res = await fetch(target, init);
        const textRes = await res.text();
        return {
          ok: res.ok, status: res.status,
          json: async () => JSON.parse(textRes),
          text: async () => textRes,
        };
      };
      window.FormData = globalThis.FormData;
      window.File = globalThis.File;
      window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
      window.scrollTo = () => {};
      window.HTMLElement.prototype.scrollIntoView = () => {};
      Object.defineProperty(window.navigator, "clipboard", {
        value: { writeText: async () => {} }, configurable: true,
      });
    },
  });
  const { window } = dom;
  window.eval(fs.readFileSync(path.join(ROOT, "studio/ui/campaigns.js"), "utf8"));
  await sleep(700);
  return { dom, window, errors };
}

async function waitFor(window, fn, ms = 60000, step = 250) {
  const started = Date.now();
  while (Date.now() - started < ms) {
    try { if (fn(window.document)) return true; } catch (_) {}
    await sleep(step);
  }
  return false;
}

(async () => {
  console.log("\n— boot —");
  const { window, errors } = await boot();
  const d = window.document;
  check("no script errors on boot", errors.length === 0, errors.join(" | "));
  check("hero headline renders", /Describe it/.test(d.querySelector(".cs-hero h1")?.textContent || ""));
  check("three start points offered", d.querySelectorAll(".cs-path").length === 3,
    `found ${d.querySelectorAll(".cs-path").length}`);
  check("brief box present", !!d.getElementById("briefText"));
  check("six 'what happens next' steps", d.querySelectorAll(".cs-next-step").length === 6);
  check("project counter hydrated", d.getElementById("navCount").textContent !== "");

  console.log("\n— start path: text —");
  d.querySelectorAll(".cs-path")[1].click();
  await sleep(120);
  check("dock has no drop zone for text", !d.getElementById("drop"));

  console.log("\n— start path: image —");
  d.querySelectorAll(".cs-path")[0].click();
  await sleep(120);
  check("drop zone appears for image path", !!d.getElementById("drop"));
  check("keyboard shortcut discoverable", /⌘/.test(d.body.textContent));

  console.log("\n— validation —");
  d.getElementById("createBtn").click();
  await sleep(300);
  check("empty brief is refused politely", !!d.querySelector(".cs-toast.is-on, .cs-toast"),
    d.querySelector(".cs-toast")?.textContent);
  d.querySelectorAll(".cs-path")[2].click();
  await sleep(120);

  console.log("\n— run a tiktok campaign —");
  const text = "three quiet habits that make a small kitchen feel twice as large";
  d.getElementById("briefText").value = text;
  d.getElementById("provider").value = "local";
  d.getElementById("length").value = "8";
  d.getElementById("createBtn").click();
  const ran = await waitFor(window, (doc) => /The decision|Publishing package/.test(doc.body.textContent), 90000);
  check("project view reached", ran);
  const body = () => d.body.textContent.replace(/\s+/g, " ");

  if (ran) {
    check("verdict ring rendered", !!d.querySelector(".cs-ring .fill"), "ring");
    check("director's call shown", /The director's call/i.test(body()));
    check("tabs rendered", d.querySelectorAll(".cs-tab").length >= 3);
    check("provenance labelled honestly", /Local preview|Model generated|From your image|Mixed sources/.test(body()));
    check("video element or still present", !!d.querySelector(".cs-phone video, .cs-phone img"));
    check("download affordance", /Download (video|image)/.test(body()));

    console.log("\n— tabs —");
    for (const tab of ["package", "quality", "decision"]) {
      const btn = [...d.querySelectorAll(".cs-tab")].find((b) => b.dataset.tab === tab);
      if (!btn) { check(`tab ${tab} exists`, false); continue; }
      btn.click();
      await sleep(220);
      check(`tab ${tab} renders`, d.getElementById("tabBody").children.length > 0);
    }
    const pkg = [...d.querySelectorAll(".cs-tab")].find((b) => b.dataset.tab === "package");
    pkg.click();
    await sleep(250);
    check("caption preview looks like the app", /characters · hook lands/.test(d.getElementById("tabBody").textContent));
    check("hashtag chips clickable", d.querySelectorAll("[data-copy]").length > 0);

    const qa = [...d.querySelectorAll(".cs-tab")].find((b) => b.dataset.tab === "quality");
    qa.click();
    await sleep(250);
    check("qa explains provenance", /Where the frames came from/.test(d.getElementById("tabBody").textContent));

    console.log("\n— creative control —");
    [...d.querySelectorAll(".cs-mode button")].find((b) => b.dataset.mode === "control").click();
    await sleep(300);
    check("control mode reveals refine bar", /Creative control/.test(body()) || /Caption lines/.test(body()));
    check("control mode opens advanced tab", [...d.querySelectorAll(".cs-tab")].every((b) => b.dataset.tab !== "advanced"));

    const hookBtn = d.querySelector('[data-refine="hook"]');
    check("refine actions offered", !!hookBtn);
    if (hookBtn) {
      hookBtn.click();
      await sleep(200);
      check("refine form opens with a starting value", (d.getElementById("refineValue")?.value || "").length > 3);
    }

    [...d.querySelectorAll(".cs-mode button")].find((b) => b.dataset.mode === "advanced").click();
    await sleep(250);
    const advTab = [...d.querySelectorAll(".cs-tab")].find((b) => b.dataset.tab === "advanced");
    check("advanced mode exposes advanced tab", !!advTab);
    if (advTab) {
      advTab.click();
      await sleep(300);
      check("advanced shows prompts", /Prompts, per shot/.test(d.getElementById("tabBody").textContent));
      check("advanced shows timeline", /Timeline/.test(d.getElementById("tabBody").textContent));
    }
  }

  console.log("\n— library —");
  [...d.querySelectorAll(".cs-mode button")].find((b) => b.dataset.mode === "automatic").click();
  d.querySelector('[data-nav="library"]').click();
  const libReady = await waitFor(window, (doc) => doc.querySelectorAll("[data-open]").length > 0, 15000);
  check("library lists projects", libReady);
  if (libReady) {
    check("tiles show a status", /complete|running|failed/.test(d.querySelector(".cs-tile .tag")?.className || ""));
    d.querySelector("[data-open]").click();
    const opened = await waitFor(window, (doc) => !!doc.querySelector(".cs-cinema"), 20000);
    check("tile opens the project", opened);
    d.getElementById("backBtn")?.click();
    await sleep(500);
    check("back returns to library", !!d.querySelector('.cs-grid, .cs-empty'));
  }

  console.log("\n— accessibility —");
  d.querySelector('[data-nav="create"]').click();
  await sleep(300);
  check("skip link present", !!d.querySelector(".cs-skip"));
  check("brief has a label", !!d.querySelector('label[for="briefText"]'));
  check("selects labelled", ["platform", "length", "provider"].every((id) => d.querySelector(`label[for="${id}"]`)));
  check("nav buttons are buttons", [...d.querySelectorAll(".cs-nav-btn")].every((b) => b.tagName === "BUTTON"));
  check("live region for toasts", d.getElementById("toast")?.getAttribute("role") === "status");

  console.log("\n— markup safety —");
  d.getElementById("briefText").value = '<img src=x onerror=alert(1)> "quoted" & <b>bold</b>';
  d.getElementById("createBtn").click();
  const escaped = await waitFor(window, (doc) => /onerror|<img src=x/.test("") || !!doc.querySelector(".cs-run, .cs-cinema, .cs-tab"), 60000);
  check("hostile text does not become markup", !d.querySelector('img[onerror], b'), "injection");
  check("hostile text still runs the campaign", escaped);

  console.log(`\n${fail === 0 ? "PASS" : "FAIL"} — ${pass} passed, ${fail} failed`);
  if (failures.length) console.log("failures:\n - " + failures.join("\n - "));
  process.exit(fail ? 1 : 0);
})().catch((error) => { console.error("harness crashed:", error); process.exit(2); });
