/* ═══════════════════════════════════════════════════════════════════
   OpenMontage — Creative & Growth Studio
   Four systems, one project, six honest stages.

   Structure: state → views → components. Views are pure template
   functions; all mutation happens in event handlers. Templates use a
   tagged `html` that escapes by default, so user text (prompts,
   project titles) can never break or inject markup.
   ═══════════════════════════════════════════════════════════════════ */

const API = "/api/studio";

const S = {
  view: "create",
  mode: localStorage.getItem("om-mode") || "automatic",
  path: "text",
  project: null,
  projectId: null,
  tab: "decision",
  upload: null,
  busy: false,
  capabilities: null,
  poll: null,
  stageSince: null,
  lastStage: null,
  tick: null,
};

/* ── templating ──────────────────────────────────────────────────── */

const RAW = Symbol("raw");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function interpolate(value) {
  if (value === null || value === undefined || value === false) return "";
  if (value && value[RAW]) return value.value;
  if (Array.isArray(value)) return value.map(interpolate).join("");
  return esc(value);
}

function html(strings, ...values) {
  let out = "";
  strings.forEach((chunk, index) => {
    out += chunk;
    if (index < values.length) out += interpolate(values[index]);
  });
  return { [RAW]: true, value: out };
}

const raw = (value) => ({ [RAW]: true, value: String(value ?? "") });
const mount = (node, template) => { if (node) node.innerHTML = template.value; };

/* ── dom + utility ───────────────────────────────────────────────── */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const main = () => document.getElementById("main");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function toast(message, kind = "") {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = message;
  node.className = `cs-toast ${kind}`;
  node.hidden = false;
  requestAnimationFrame(() => node.classList.add("is-on"));
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    node.classList.remove("is-on");
    setTimeout(() => { node.hidden = true; }, 260);
  }, 4000);
}

async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: isForm ? {} : { "content-type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload && payload.detail) detail = payload.detail;
    } catch (_) { /* not JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

const mediaUrl = (id, file) => `${API}/projects/${encodeURIComponent(id)}/media/${encodeURIComponent(file)}`;
const artifactUrl = (id, file) => `${API}/projects/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(file)}`;

const pick = (project, name) => {
  const component = project?.components?.[name];
  return component && component.done ? component.data : null;
};

const COMPONENT_NAMES = {
  intent: "Read your idea",
  media: "Read your photograph",
  concept: "Chose the angle",
  brief: "Wrote the creative brief",
  hooks: "Wrote the opening lines",
  beats: "Structured the beats",
  visual_plan: "Planned the shots",
  prompts: "Wrote the shot prompts",
  assets: "Framed the artwork",
  script: "Wrote the script",
  storyboard: "Built the storyboard",
  scene_assets: "Matched scenes to frames",
  edit: "Cut the timeline",
  cues: "Timed the captions",
  render: "Rendered the film",
  review: "Reviewed the cut",
  final_review: "Checked the final file",
  seo: "Wrote the publishing package",
};

const ACTIONS = {
  present_to_user: "show it to you as is",
  regenerate_assets: "regenerate some frames",
  re_edit: "re-cut the timeline",
  fix_technical: "fix the file",
};

function humanEvent(event) {
  const message = String(event.message || "");
  const done = message.match(/^([a-z_]+) complete$/);
  if (done && COMPONENT_NAMES[done[1]]) return COMPONENT_NAMES[done[1]];
  return message.charAt(0).toUpperCase() + message.slice(1);
}

function shortDetail(detail) {
  const text = String(detail || "");
  if (!text) return "";
  if (!text.includes("/")) return text;
  const file = text.split("/").pop();
  return file;
}

const fmtSeconds = (value) => {
  const n = Number(value) || 0;
  if (n < 0.1) return "instant";
  if (n < 60) return `${n.toFixed(n < 10 ? 1 : 0)}s`;
  return `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
};

async function copy(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast(label || "Copied");
    return true;
  } catch (_) {
    toast("Could not reach the clipboard", "err");
    return false;
  }
}

/* ── chrome ──────────────────────────────────────────────────────── */

function setMode(mode, { silent } = {}) {
  S.mode = mode;
  localStorage.setItem("om-mode", mode);
  $$(".cs-mode button").forEach((button) => {
    const on = button.dataset.mode === mode;
    button.classList.toggle("is-active", on);
    button.setAttribute("aria-checked", String(on));
  });
  if (S.tab === "advanced" && mode !== "advanced") S.tab = "decision";
  if (!silent && S.view === "project" && S.project) renderProject();
  if (S.view === "create") updateDockHint();
}

function setView(view) {
  S.view = view;
  $$(".cs-nav-btn").forEach((b) => {
    const on = b.dataset.nav === view || (view === "project" && b.dataset.nav === "library");
    b.classList.toggle("is-active", on);
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  if (view === "create") { stopPolling(); renderCreate(); }
  if (view === "library") { stopPolling(); renderLibrary(); }
  if (view === "project") {
    renderProject();
    if (S.project?.status === "running") startPolling();
  }
}

$$(".cs-nav-btn").forEach((b) => b.addEventListener("click", () => setView(b.dataset.nav)));
$$(".cs-mode button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
$$("[data-nav='create']").forEach((el) => el.addEventListener("click", (e) => {
  if (el.tagName === "A") e.preventDefault();
  setView("create");
}));

document.addEventListener("keydown", (event) => {
  const meta = event.metaKey || event.ctrlKey;
  if (meta && event.key.toLowerCase() === "k") {
    event.preventDefault();
    setView("create");
    setTimeout(() => document.getElementById("briefText")?.focus(), 60);
  }
  if (meta && event.key === "Enter" && S.view === "create") {
    event.preventDefault();
    document.getElementById("createBtn")?.click();
  }
  if (event.key === "Escape") {
    if (document.getElementById("theatre")) toggleTheatre(false);
    else if (S.view === "project" && S.mode === "control") document.getElementById("refineForm")?.replaceChildren();
  }
});

/* ── create ──────────────────────────────────────────────────────── */

const PATHS = {
  image:  { icon: "<svg viewBox='0 0 16 16' width='15' height='15' aria-hidden='true'><rect x='1.8' y='2.6' width='12.4' height='10.8' rx='2' stroke='currentColor' stroke-width='1.4' fill='none'/><circle cx='5.8' cy='6.4' r='1.3' fill='currentColor'/><path d='M3 11.4l3.2-3 2.3 2.1 2.2-2.4 2.3 3.3' stroke='currentColor' stroke-width='1.3' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>", label: "From an image", placeholder: "What should this image become? e.g. a quiet, cinematic reveal for autumn" },
  text:   { icon: "<svg viewBox='0 0 16 16' width='15' height='15' aria-hidden='true'><path d='M3 3.5h10M3 7h10M3 10.5h6' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/></svg>", label: "From text", placeholder: "One sentence is enough — e.g. why pressing beats man-marking in modern football" },
  tiktok: { icon: "<svg viewBox='0 0 16 16' width='15' height='15' aria-hidden='true'><rect x='1.6' y='3' width='12.8' height='10' rx='2.4' stroke='currentColor' stroke-width='1.4' fill='none'/><path d='M6.6 6.2l3.6 1.9-3.6 1.9z' fill='currentColor'/></svg>", label: "TikTok campaign", note: "Full package", placeholder: "e.g. a quiet luxury camel trench coat for autumn" },
};

const STARTERS = {
  text: [
    "why pressing beats man-marking in modern football",
    "three quiet habits that make a small kitchen feel twice as large",
    "what nobody tells you about training for a first marathon",
  ],
  image: [
    "turn this into a slow, cinematic product reveal",
    "make this photograph feel like late-summer dusk",
    "use this as the opening frame for a 12 second teaser",
  ],
  tiktok: [
    "a quiet luxury camel trench coat for autumn",
    "the 60 second skincare routine dermatologists actually keep",
    "a desk setup that makes deep work feel easy",
  ],
};

function renderStarters() {
  const host = document.getElementById("examples");
  if (!host) return;
  const field = document.getElementById("briefText");
  if (field && field.value.trim()) { host.innerHTML = ""; return; }
  host.innerHTML = html`
    <span class="lbl">Try</span>
    ${STARTERS[S.path].map((text) => html`
      <button type="button" data-starter="${text}">${text}</button>`)}`.value;
  $$("[data-starter]", host).forEach((button) => button.addEventListener("click", () => {
    const input = document.getElementById("briefText");
    if (!input) return;
    input.value = button.dataset.starter;
    autosize(input);
    saveDraft();
    renderStarters();
    input.focus();
  }));
}

const STAGE_MAP = [
  { key: "understand", n: "01", label: "Reads your idea", sys: "director" },
  { key: "concept",    n: "02", label: "Picks the angle",  sys: "director" },
  { key: "assets",     n: "03", label: "Designs the visuals", sys: "creative" },
  { key: "produce",    n: "04", label: "Cuts and renders", sys: "producer" },
  { key: "check",      n: "05", label: "Checks the film",  sys: "producer" },
  { key: "publish",    n: "06", label: "Writes your post", sys: "growth" },
];

const SYSTEMS = [
  ["director", "Director", "Reads the brief, weighs every angle, picks one and can explain the call."],
  ["creative", "Creative", "Turns the angle into a shot list, a palette and per-shot prompts."],
  ["producer", "Producer", "Cuts, captions, renders, then checks its own file before handing it over."],
  ["growth", "Growth", "Writes the caption, hashtags, sound brief and posting plan."],
];

function castCard() {
  const recent = (S.recent || [])[0];
  return html`
    <aside class="cs-cast">
      <div class="cs-cast-head">
        <span>Who works on it</span>
        <em>4 systems</em>
      </div>
      ${SYSTEMS.map(([key, name, role]) => html`
        <div class="cs-cast-row cs-sys-${key}">
          <i aria-hidden="true"></i>
          <b>${name}</b>
          <span>${role}</span>
        </div>`)}
      ${recent ? html`
        <a class="cs-cast-work" href="#" data-open-recent="${recent.id}">
          ${recent.poster
            ? html`<img src="${mediaUrl(recent.id, recent.poster)}" alt="" />`
            : html`<span class="ph"></span>`}
          <span class="meta">
            <small>Latest work</small>
            <strong>${recent.title}</strong>
          </span>
          <span class="go" aria-hidden="true">→</span>
        </a>` : html`
        <div class="cs-cast-work">
          <span class="ph"></span>
          <span class="meta">
            <small>Nothing made yet</small>
            <strong>Your first campaign will appear here.</strong>
          </span>
        </div>`}
    </aside>`;
}

function renderCreate() {
  stopPolling();
  const path = PATHS[S.path];
  const template = html`
    <div class="cs-create">
      <section class="cs-hero cs-in">
        <div class="cs-hero-copy">
          <span class="cs-eyebrow">Four systems · one project</span>
          <h1>Describe it.<br />We make <em>the decisions</em>.</h1>
          <p>You bring an idea or an image. The director picks the angle, the creative
             engine designs the shots, production cuts and checks the film, growth writes
             the post. No prompt engineering, no hand-offs.</p>
          <div class="cs-paths" role="tablist" aria-label="Starting point">
            ${Object.entries(PATHS).map(([key, p]) => html`
              <button class="cs-path ${S.path === key ? "is-on" : ""}" data-path="${key}"
                      role="tab" aria-selected="${S.path === key}">
                <span class="icon" aria-hidden="true">${raw(p.icon)}</span>
                ${p.label}
                ${p.note ? html`<span class="tag">${p.note}</span>` : ""}
              </button>`)}
          </div>
        </div>
        ${castCard()}
      </section>

      <section class="cs-dock cs-in" id="dock" aria-label="Campaign brief">
        <div class="cs-dock-body">
          ${S.path === "image" ? html`
            <button class="cs-drop ${S.upload ? "has-image" : ""}" id="drop" type="button"
                    aria-label="${S.upload ? "Replace image" : "Choose an image"}">
              ${S.upload
                ? html`<img src="${S.upload.url}" alt="Uploaded source, ${S.upload.width} by ${S.upload.height}" />`
                : html`<span class="txt"><strong>Drop an image</strong><span>or click</span></span>`}
            </button>` : ""}

          <div class="cs-dock-field">
            <label class="cs-sr" for="briefText">What do you want to make?</label>
            <textarea id="briefText" rows="2" placeholder="${path.placeholder}"
                      autocomplete="off" spellcheck="true"></textarea>
            <div class="cs-dock-tools">
              <label class="cs-sr" for="platform">Platform</label>
              <select class="cs-select" id="platform">
                <option value="">Platform: auto</option>
                <option value="tiktok">TikTok</option>
                <option value="instagram">Instagram</option>
                <option value="youtube">YouTube</option>
                <option value="linkedin">LinkedIn</option>
              </select>
              <label class="cs-sr" for="length">Length</label>
              <select class="cs-select" id="length">
                <option value="">Length: auto</option>
                <option value="8">8 seconds</option>
                <option value="12">12 seconds</option>
                <option value="15">15 seconds</option>
                <option value="22">22 seconds</option>
                <option value="30">30 seconds</option>
              </select>
              <label class="cs-sr" for="provider">Generator</label>
              <select class="cs-select" id="provider">
                <option value="auto">Generator: auto</option>
                <option value="local">Local design</option>
              </select>
              <span class="cs-spacer"></span>
              <button class="cs-primary" id="createBtn">
                Create <span aria-hidden="true">→</span>
              </button>
            </div>
          </div>
        </div>
        <div class="cs-dock-foot">
          <div class="cs-dock-foot-row">
            <span class="cs-status" id="dockHint"></span>
            <span class="cs-key">⌘ ↵ to create</span>
          </div>
          <div class="cs-dock-examples" id="examples"></div>
        </div>
      </section>

      <section class="cs-next cs-in" aria-label="What happens next">
        ${STAGE_MAP.map((stage) => html`
          <div class="cs-next-step">
            <span class="n">${stage.n}</span>
            <strong>${stage.label}</strong>
            <span class="sys cs-sys-${stage.sys}"><i></i>${stage.sys}</span>
          </div>`)}
      </section>
    </div>`;

  mount(main(), template);
  wireCreate();
  restoreDraft();
  renderStarters();
  loadCapabilities();
}

let draftTimer = null;
function saveDraft() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    const text = $(".cs-dock textarea")?.value || "";
    try { localStorage.setItem(`om-draft-${S.path}`, text); } catch (_) { /* private mode */ }
  }, 300);
}

function restoreDraft() {
  try {
    const text = localStorage.getItem(`om-draft-${S.path}`) || "";
    const field = document.getElementById("briefText");
    if (text && field) { field.value = text; autosize(field); }
  } catch (_) { /* private mode */ }
}

function autosize(field) {
  field.style.height = "auto";
  field.style.height = `${Math.min(220, Math.max(74, field.scrollHeight))}px`;
}

function wireCreate() {
  $$(".cs-path").forEach((button) => {
    button.addEventListener("click", () => {
      const field = document.getElementById("briefText");
      if (field) saveDraft();
      S.path = button.dataset.path;
      S.upload = S.path === "image" ? S.upload : null;
      renderCreate();
      document.getElementById("briefText")?.focus();
    });
  });

  const field = document.getElementById("briefText");
  if (field) {
    field.addEventListener("input", () => { autosize(field); saveDraft(); renderStarters(); });
    field.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        document.getElementById("createBtn")?.click();
      }
    });
  }

  const drop = document.getElementById("drop");
  if (drop) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp";
    input.hidden = true;
    document.body.appendChild(input);
    input.addEventListener("change", () => { if (input.files[0]) uploadFile(input.files[0]); });
    drop.addEventListener("click", () => input.click());
    ["dragenter", "dragover"].forEach((type) => drop.addEventListener(type, (event) => {
      event.preventDefault(); drop.classList.add("is-over");
    }));
    ["dragleave", "drop"].forEach((type) => drop.addEventListener(type, (event) => {
      event.preventDefault(); drop.classList.remove("is-over");
    }));
    drop.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file) uploadFile(file);
    });
  }

  document.getElementById("createBtn")?.addEventListener("click", startProject);
  $$("[data-open-recent]").forEach((link) => link.addEventListener("click", async (event) => {
    event.preventDefault();
    S.projectId = link.dataset.openRecent;
    try {
      S.project = await api(`/projects/${S.projectId}`);
      S.tab = "decision";
      setView("project");
    } catch (error) { toast(error.message, "err"); }
  }));
  updateDockHint();
}

function updateDockHint() {
  const hint = document.getElementById("dockHint");
  if (!hint || !S.capabilities) return;
  const { image, video } = S.capabilities;
  const live = image.available || video.available;
  hint.className = `cs-status ${live ? "live" : ""}`;
  hint.innerHTML = `<i aria-hidden="true"></i>${live
    ? esc(image.chosen || video.chosen || "Model available")
    : "Local preview mode"}`;
  hint.title = live
    ? "A generation provider is configured and will be used where it fits."
    : "No model key is configured, so frames are composed locally and labelled as previews. Everything else — script, cut, captions, QA, package — is real.";
}

async function loadCapabilities() {
  try {
    S.capabilities = await api("/capabilities");
    updateDockHint();
  } catch (_) { /* advisory only */ }
}

async function uploadFile(file) {
  const drop = document.getElementById("drop");
  if (drop) {
    drop.innerHTML = `<span class="txt"><strong>Uploading…</strong><span>${esc(file.name)}</span></span>`;
  }
  try {
    const data = new FormData();
    data.append("file", file);
    S.upload = await api("/upload", { method: "POST", body: data });
    renderCreate();
    document.getElementById("briefText")?.focus();
  } catch (error) {
    S.upload = null;
    toast(`Upload failed — ${error.message}`, "err");
    renderCreate();
  }
}

async function startProject() {
  if (S.busy) return;
  const text = (document.getElementById("briefText")?.value || "").trim();
  if (S.path === "image" && !S.upload) { toast("Add an image first, or start from text.", "err"); return; }
  if (!text && !S.upload) { toast("Give the studio a sentence to work from.", "err"); return; }

  S.busy = true;
  const button = document.getElementById("createBtn");
  if (button) {
    button.disabled = true;
    button.innerHTML = `<span class="cs-spin"></span> Starting`;
  }
  try {
    const project = await api("/projects", {
      method: "POST",
      body: JSON.stringify({
        mode: S.path,
        text,
        upload_id: S.upload?.upload_id || "",
        platform: document.getElementById("platform")?.value || "",
        duration_seconds: document.getElementById("length")?.value
          ? Number(document.getElementById("length").value) : null,
        provider: document.getElementById("provider")?.value || "auto",
      }),
    });
    S.project = project;
    S.projectId = project.id;
    S.tab = "decision";
    S.stageSince = Date.now();
    S.lastStage = null;
    try { localStorage.removeItem(`om-draft-${S.path}`); } catch (_) { /* ignore */ }
    setView("project");
  } catch (error) {
    toast(error.message, "err");
    if (button) { button.disabled = false; button.innerHTML = `Create <span aria-hidden="true">→</span>`; }
  } finally {
    S.busy = false;
  }
}

/* ── progress ────────────────────────────────────────────────────── */

function stopPolling() {
  if (S.poll) { clearTimeout(S.poll); S.poll = null; }
  if (S.tick) { clearInterval(S.tick); S.tick = null; }
}

function startPolling() {
  stopPolling();
  S.stageSince = Date.now();
  S.lastStage = null;
  if (S.tick) clearInterval(S.tick);
  S.tick = setInterval(paintElapsed, 500);

  const poll = async () => {
    if (!S.projectId) return;
    try {
      const project = await api(`/projects/${S.projectId}`);
      S.project = project;
      if (S.view !== "project") { stopPolling(); return; }
      if (project.status === "running") {
        if (S.lastStage !== project.stage) { S.lastStage = project.stage; S.stageSince = Date.now(); }
        renderProgress(project);
        S.poll = setTimeout(poll, 900);
      } else {
        stopPolling();
        renderProject();
      }
    } catch (error) {
      stopPolling();
      toast(error.message, "err");
    }
  };
  poll();
}

function framesArriving(project) {
  const frames = pick(project, "assets")?.assets || [];
  if (!frames.length) {
    return html`<p class="cs-hint cs-in">You can leave this page — the project keeps building
      in the background and will be waiting in Projects.</p>`;
  }
  return html`
    <div class="cs-in">
      <p class="cs-hint" style="margin-bottom:10px">Frames arriving — each one is
        <strong>composed locally</strong> unless a model provider is configured.</p>
      <div class="cs-strip" aria-label="Frames produced so far">
        ${frames.map((frame, index) => html`
          <a href="${mediaUrl(project.id, frame.url)}" target="_blank" rel="noopener"
             title="Frame ${index + 1}">
            <img src="${mediaUrl(project.id, frame.url)}" alt="Frame ${index + 1}" />
          </a>`)}
      </div>
    </div>`;
}

function paintElapsed() {
  const node = document.getElementById("stageElapsed");
  if (!node || !S.stageSince) return;
  node.textContent = fmtSeconds((Date.now() - S.stageSince) / 1000);
}

function stageSeconds(project, stage) {
  const names = stage.components || [];
  return names.reduce((total, name) => total + (project.components?.[name]?.seconds || 0), 0);
}

function renderProgress(project) {
  const stages = project.progress || [];
  const events = (project.events || []).slice(-18).reverse();
  const active = stages.find((s) => s.status === "active") || stages.find((s) => s.status === "pending");
  const doneCount = stages.filter((s) => s.status === "done").length;

  const template = html`
    <div class="cs-run">
      <header class="cs-run-head cs-in">
        <span class="cs-eyebrow">Running · ${doneCount} of ${stages.length} stages</span>
        <h1>${active ? active.label : "Finishing up"}<span class="cs-sr">…</span></h1>
        <p class="cs-run-sub">${project.title}</p>
      </header>

      <p class="cs-sr" aria-live="polite">${active ? `${active.label}. ${doneCount} of ${stages.length} stages complete.` : "Finishing up."}</p>
      <div class="cs-meter cs-in" role="progressbar" aria-valuemin="0" aria-valuemax="${stages.length}"
           aria-valuenow="${doneCount}" aria-label="Campaign progress">
        ${stages.map((stage) => html`
          <span class="cs-meter-seg is-${stage.status === "not_applicable" ? "skip" : stage.status}"><i></i></span>`)}
      </div>

      <div class="cs-run-grid">
        <div class="cs-stages cs-in">
          ${stages.map((stage) => html`
            <div class="cs-stage is-${stage.status}">
              <div class="dot"><span aria-hidden="true">${stage.status === "done" ? "✓" : stage.status === "not_applicable" ? "–" : ""}</span></div>
              <div class="label">
                ${stage.label}
                ${stage.status === "not_applicable" ? html`<span class="cs-hint"> — not needed for this brief</span>` : ""}
              </div>
              <div class="meta">
                ${stage.status === "active"
                  ? html`<span id="stageElapsed">0s</span>`
                  : stage.status === "done"
                    ? fmtSeconds(stageSeconds(project, stage))
                    : stage.status === "not_applicable" ? "" : "queued"}
              </div>
            </div>`)}
        </div>

        <aside class="cs-feed cs-in" aria-label="Studio activity">
          <div class="cs-feed-head"><span class="cs-feed-dot" aria-hidden="true"></span>Live activity</div>
          <ul>
            ${events.length
              ? events.map((event) => html`
                  <li>
                    <span class="sys cs-sys-${event.system}">${event.system}</span>
                    <span class="msg">${humanEvent(event)}</span>
                  </li>`)
              : html`<li><span class="sys cs-sys-studio">studio</span><span class="msg">Waking the systems…</span></li>`}
          </ul>
        </aside>
      </div>

      ${framesArriving(project)}

      ${project.status === "failed" ? html`
        <div class="cs-stop cs-in">
          <h3>Stopped — your work is safe</h3>
          <p>Everything finished before the failure is kept. Resuming picks up from the step that broke.</p>
          <code>${project.error || "Unknown error"}</code>
          <div>
            <button class="cs-primary" id="retryBtn">Resume from where it stopped</button>
          </div>
        </div>` : ""}
    </div>`;

  mount(main(), template);
  paintElapsed();

  const retry = document.getElementById("retryBtn");
  if (retry) {
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      retry.innerHTML = `<span class="cs-spin"></span> Resuming`;
      try {
        await api(`/projects/${S.projectId}/retry`, { method: "POST" });
        startPolling();
      } catch (error) {
        toast(error.message, "err");
        retry.disabled = false;
        retry.textContent = "Resume from where it stopped";
      }
    });
  }
}

/* ── project ─────────────────────────────────────────────────────── */

function elapsedLabel(project) {
  const start = Date.parse(project.created_at || "");
  const end = Date.parse(project.updated_at || "");
  if (!start || !end || end <= start) return "under a minute";
  const seconds = Math.round((end - start) / 1000);
  return seconds < 90 ? `${seconds}s` : `${Math.round(seconds / 60)} min`;
}

function fact(label, value) {
  return html`<div><dt>${label}</dt><dd>${value}</dd></div>`;
}

function provenanceLabel(project) {
  const assets = pick(project, "assets")?.assets || [];
  const kinds = new Set(assets.map((a) => a.provenance));
  if (kinds.has("model") && kinds.size === 1) return ["Model generated", "ok"];
  if (kinds.has("model")) return ["Mixed sources", "warn"];
  if (kinds.has("source")) return ["From your image", "ok"];
  if (kinds.has("local")) return ["Local preview · no model", "warn"];
  return ["Local render", "warn"];
}

function provenanceSummary(project) {
  const assets = pick(project, "assets")?.assets || [];
  const counts = assets.reduce((acc, a) => ({ ...acc, [a.provenance]: (acc[a.provenance] || 0) + 1 }), {});
  const parts = [];
  if (counts.source) parts.push(`${counts.source} derived from your photograph, no generative model`);
  if (counts.model) parts.push(`${counts.model} generated by a model provider`);
  if (counts.local) parts.push(`${counts.local} composed locally by the art director, not model output`);
  return parts.join(" · ") || "No assets recorded.";
}

function scoreRing(score) {
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - value / 100);
  return html`
    <div class="cs-ring" role="img" aria-label="Score ${value} out of 100">
      <svg width="92" height="92" viewBox="0 0 92 92" aria-hidden="true">
        <defs>
          <linearGradient id="csRingGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#F0A93B" />
            <stop offset="100%" stop-color="#FF6B3D" />
          </linearGradient>
        </defs>
        <circle class="track" cx="46" cy="46" r="${radius}" />
        <circle class="fill" cx="46" cy="46" r="${radius}"
                stroke-dasharray="${circumference.toFixed(2)}"
                stroke-dashoffset="${offset.toFixed(2)}" />
      </svg>
      <span class="val">${Math.round(value)}<small>/100</small></span>
    </div>`;
}

function selectedReasons(concept) {
  if (!concept?.selected) return [];
  const match = (concept.options || []).find((o) => o.id === concept.selected.id);
  return match?.reasons || concept.selected.reasons || [];
}

function renderProject() {
  stopPolling();
  const project = S.project;
  if (!project) { setView("create"); return; }
  if (project.status === "running") { renderProgress(project); startPolling(); return; }
  if (project.status === "failed") { renderProgress(project); return; }

  const render = pick(project, "render");
  const assets = pick(project, "assets");
  const concept = pick(project, "concept");
  const intent = pick(project, "intent");
  const review = pick(project, "final_review");
  const seo = pick(project, "seo");
  const [provLabel, provKind] = provenanceLabel(project);
  const frames = assets?.assets || [];
  const isStill = intent?.deliverable === "image";
  const selected = concept?.selected;

  const tabs = [
    ["decision", "The decision"],
    ["package", "Publishing package"],
    ["quality", "Quality"],
    ...(S.mode === "advanced" ? [["advanced", "Advanced"]] : []),
  ];
  if (!tabs.some(([key]) => key === S.tab)) S.tab = "decision";

  const template = html`
    <div class="${S.view === "project" ? "is-wide" : ""}">
      <button class="cs-back" id="backBtn">
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M9.5 3.5L5 8l4.5 4.5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Projects
      </button>

      <div class="cs-cinema">
        <div class="cs-reel cs-in">
          <div class="cs-phone">
            ${render
              ? html`<video src="${mediaUrl(project.id, render.url)}"
                            poster="${render.poster_url ? mediaUrl(project.id, render.poster_url) : ""}"
                            controls playsinline preload="metadata"></video>`
              : html`<img src="${frames[0]?.url ? mediaUrl(project.id, frames[0].url) : ""}"
                          alt="${frames[0]?.prompt ? `First frame: ${frames[0].prompt}` : "First frame of the campaign"}" />`}
            <span class="badge ${provKind}" title="Where these frames came from">${provLabel}</span>
            <button class="cs-expand" id="expandBtn" aria-label="View full size">
              <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M6 2.5H2.5V6M10 2.5h3.5V6M6 13.5H2.5V10M10 13.5h3.5V10" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </div>

          <div class="cs-reel-actions">
            ${render ? html`
              <a class="cs-ghost primary wide" href="${mediaUrl(project.id, render.url)}" download>
                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M8 2.5v8M4.8 7.4L8 10.6l3.2-3.2M3 13h10" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
                Download video
              </a>
              <div class="cs-reel-secondary">
                <a class="cs-ghost" href="${mediaUrl(project.id, render.poster_url || render.url)}" download="cover.jpg">Cover</a>
                ${seo ? html`<button class="cs-ghost" id="copyCaption">Copy caption</button>` : ""}
              </div>`
              : frames.length ? html`
              <a class="cs-ghost primary wide" href="${mediaUrl(project.id, frames[0].url)}" download>
                Download image
              </a>` : ""}
          </div>

          <dl class="cs-facts">
            ${fact("Made in", elapsedLabel(project))}
            ${fact("Shots", `${frames.length}`)}
            ${fact("Format", render ? `${render.resolution} · ${render.aspect || "9:16"}` : "stills")}
            ${fact("Angle", selected?.name || "—")}
            ${fact("Post", seo ? `${seo.hashtags.count} tags · ${seo.caption.characters} chars` : "not written")}
          </dl>

          ${frames.length > 1 ? html`
            <div class="cs-strip" aria-label="Frames in this campaign">
              ${frames.slice(0, 5).map((frame, index) => html`
                <a href="${mediaUrl(project.id, frame.url)}" target="_blank" rel="noopener"
                   title="${frame.provenance === "source" ? "From your image" : frame.provenance === "model" ? "Model generated" : "Local preview"}">
                  <img src="${mediaUrl(project.id, frame.url)}" alt="Frame ${index + 1}" loading="lazy" />
                </a>`)}
            </div>` : ""}
        </div>

        <div class="cs-detail">
          <header class="cs-detail-head cs-in">
            <span class="cs-eyebrow">
              ${intent?.platform || "tiktok"}${render ? ` · ${render.duration_seconds}s · ${render.resolution}` : " · stills"}
            </span>
            <h1>${project.title}</h1>
            <div class="cs-meta-row">
              ${selected ? html`<span class="cs-pill">${selected.name}</span>` : ""}
              ${review ? html`<span class="cs-pill ${review.status === "pass" ? "ok" : "warn"}">QA ${review.status}</span>` : ""}
              ${render?.has_captions ? html`<span class="cs-pill">Captions burned in</span>` : ""}
              <span class="cs-pill ${provKind}">${provLabel}</span>
              ${isStill ? html`<span class="cs-pill">Still brief</span>` : ""}
            </div>
          </header>

          ${selected ? html`
            <section class="cs-verdict cs-in">
              ${scoreRing(selected.score)}
              <div class="cs-verdict-body">
                <span class="kicker">The director's call</span>
                <h2>${selected.name}</h2>
                <p>${selected.why || selected.description || ""}</p>
                <ul class="cs-verdict-reasons">
                  ${selectedReasons({ options: concept.options, selected }).slice(0, 4).map((reason) => html`
                    <li><span class="pts ${reason.points < 0 ? "neg" : ""}">${reason.points > 0 ? "+" : ""}${reason.points}</span>${reason.why}</li>`)}
                </ul>
              </div>
            </section>` : ""}

          ${S.mode !== "automatic" ? refineBar() : html`
            <button class="cs-ghost" id="changeBtn" style="justify-self:start">
              Change something
            </button>`}

          <nav class="cs-tabs" role="tablist" aria-label="Campaign detail">
            ${tabs.map(([key, label]) => html`
              <button class="cs-tab ${S.tab === key ? "is-active" : ""}" data-tab="${key}"
                      role="tab" aria-selected="${S.tab === key}">${label}</button>`)}
          </nav>

          <div id="tabBody"></div>
        </div>
      </div>
    </div>`;

  mount(main(), template);
  wireProject(project);
  renderTab();
}

function wireProject(project) {
  document.getElementById("backBtn")?.addEventListener("click", () => setView("library"));
  document.getElementById("expandBtn")?.addEventListener("click", () => toggleTheatre(true));
  document.getElementById("theatre")?.addEventListener("click", (event) => {
    if (event.target.id === "theatre" || event.target.closest("[data-close]")) toggleTheatre(false);
  });
  document.getElementById("changeBtn")?.addEventListener("click", () => setMode("control"));
  document.getElementById("copyCaption")?.addEventListener("click", copyCaption);
  const tabButtons = $$(".cs-tab");
  tabButtons.forEach((button, index) => {
    button.tabIndex = button.classList.contains("is-active") ? 0 : -1;
    button.addEventListener("click", () => {
      S.tab = button.dataset.tab;
      $$(".cs-tab").forEach((b) => {
        const on = b.dataset.tab === S.tab;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-selected", String(on));
        b.tabIndex = on ? 0 : -1;
      });
      renderTab();
    });
    button.addEventListener("keydown", (event) => {
      const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      const next = tabButtons[(index + step + tabButtons.length) % tabButtons.length];
      next.focus();
      next.click();
    });
  });
  $$("[data-refine]").forEach((button) => button.addEventListener("click", () => openRefine(button.dataset.refine)));
}

function toggleTheatre(open) {
  const existing = document.getElementById("theatre");
  if (!open) {
    existing?.remove();
    document.documentElement.style.overflow = "";
    if (S.theatreReturn?.focus) S.theatreReturn.focus();
    return;
  }
  if (existing || !S.project) return;
  const render = pick(S.project, "render");
  const frames = pick(S.project, "assets")?.assets || [];
  const node = document.createElement("div");
  node.id = "theatre";
  node.className = "cs-theatre";
  node.setAttribute("role", "dialog");
  node.setAttribute("aria-modal", "true");
  node.setAttribute("aria-label", "Campaign preview, full size");
  node.innerHTML = html`
    <button class="cs-theatre-close" data-close aria-label="Close preview">✕</button>
    ${render
      ? html`<video src="${mediaUrl(S.project.id, render.url)}"
                    poster="${render.poster_url ? mediaUrl(S.project.id, render.poster_url) : ""}"
                    controls autoplay playsinline></video>`
      : frames[0] ? html`<img src="${mediaUrl(S.project.id, frames[0].url)}" alt="" />` : ""}
  `.value;
  document.body.appendChild(node);
  document.documentElement.style.overflow = "hidden";
  S.theatreReturn = document.activeElement;
  node.querySelector("[data-close]")?.focus();
  node.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const focusable = node.querySelectorAll("button, video, [href]");
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

function copyCaption() {
  const seo = pick(S.project, "seo");
  if (!seo) return;
  copy(`${seo.caption.text}\n\n${(seo.hashtags?.selected || []).join(" ")}`, "Caption and hashtags copied");
}

function refineBar() {
  const actions = [
    ["hook", "Opening line"],
    ["scene", "One scene"],
    ["palette", "Colour"],
    ["duration", "Length"],
    ["sound", "Sound"],
  ];
  return html`
    <section class="cs-section">
      <div class="cs-section-head">
        <h3>Creative control</h3>
        <span class="cs-section-note">only what you touch is rebuilt</span>
      </div>
      <div class="cs-section-body">
        <div class="cs-chips">
          ${actions.map(([key, label]) => html`
            <button class="cs-ghost" data-refine="${key}">${label}</button>`)}
        </div>
        <div id="refineForm"></div>
      </div>
    </section>`;
}

/* ── tabs ────────────────────────────────────────────────────────── */

function renderTab() {
  const host = document.getElementById("tabBody");
  if (!host) return;
  const project = S.project;
  const builders = {
    decision: decisionPanel,
    package: packagePanel,
    quality: qualityPanel,
    advanced: advancedPanel,
  };
  const build = builders[S.tab] || decisionPanel;
  mount(host, build(project));
  wireTab(project);
}

function section(title, body, note, cls = "", id = "") {
  return html`
    <section class="cs-section ${cls}" ${id ? raw(`id="${esc(id)}"`) : ""}>
      <div class="cs-section-head">
        <h3>${title}</h3>
        ${note ? html`<span class="cs-section-note">${note}</span>` : ""}
      </div>
      <div class="cs-section-body">${body}</div>
    </section>`;
}

function captionLines(project) {
  const script = pick(project, "script");
  if (!script) return "";
  return section("Caption lines", html`
    <p class="cs-hint">These become burned-in captions. Editing one re-times the burn and
      rebuilds the export — the artwork is untouched.</p>
    ${script.sections.map((line, index) => html`
      <div class="cs-refine-row">
        <input id="line-${index}" value="${line.text}" aria-label="Caption ${index + 1}" />
        <button class="cs-ghost" data-line="${index}" data-section="${line.id}">Reburn</button>
      </div>`)}`, "control mode");
}

function decisionPanel(project) {
  const concept = pick(project, "concept");
  if (!concept) return html`<div class="cs-empty"><strong>Waiting on the director</strong>The creative decision has not been made yet.</div>`;
  const plan = pick(project, "visual_plan");
  const brief = pick(project, "brief");
  const intent = pick(project, "intent");
  const frames = pick(project, "assets")?.assets || [];
  const byShot = Object.fromEntries(frames.map((a) => [a.shot_id, a]));
  const selected = concept.selected;

  return html`
    <div class="cs-panel">
      ${section("Every angle considered", html`
        <div class="cs-angles">
          ${(concept.options || []).map((option) => html`
            <div class="cs-angle ${option.id === selected.id ? "is-selected" : ""}">
              <div>
                <strong>${option.name}</strong>
                <small>${option.description}</small>
              </div>
              <div style="display:flex;align-items:center;gap:10px">
                <span class="n ${option.score < 55 ? "low" : ""}">${option.score}</span>
                ${option.id !== selected.id && S.mode !== "automatic"
                  ? html`<button class="cs-ghost" data-concept="${option.id}">Use</button>` : ""}
              </div>
            </div>`)}
        </div>`, concept.why_not || "")}

      ${switchHint(concept)}

      ${plan ? section("The shot list", html`
        <div class="cs-shots">
          ${plan.shots.map((shot, index) => {
            const asset = byShot[shot.id];
            return html`
              <article class="cs-shot">
                <img src="${asset?.url ? mediaUrl(project.id, asset.url) : ""}" alt="" loading="lazy" />
                <div class="body">
                  <strong>${index + 1}. ${shot.beat}</strong>
                  <span>${shot.description}</span>
                  <code>${shot.framing} · ${shot.movement}</code>
                  ${asset ? html`<span class="prov ${asset.provenance}">${asset.provenance}</span>` : ""}
                </div>
              </article>`;
          })}
        </div>`, `${plan.shots.length} shots`) : ""}

      ${section("What the studio understood", html`
        <p>${intent?.niche_label} · ${intent?.deliverable} · ${intent?.duration_seconds}s ·
           ${intent?.platform} · audience: ${intent?.audience}</p>
        ${intent?.assumptions?.length ? html`
          <ul class="cs-list">
            ${intent.assumptions.map((item) => html`<li>${item}</li>`)}
          </ul>` : ""}
        <p class="cs-hint">Confidence ${Math.round((intent?.confidence || 0) * 100)}% — how much the
           request actually constrained the decision.</p>`, "")}

      ${S.mode !== "automatic" ? captionLines(project) : ""}

      ${plan ? section("Colour direction", html`
        <div class="cs-swatches">
          ${plan.palette.map((colour) => html`
            <div class="cs-swatch">
              <i style="background:${colour}"></i>
              <span>${colour}</span>
            </div>`)}
        </div>
        <p class="cs-hint">${plan.grade}</p>
        ${brief?.metadata?.credibility_note
          ? html`<p class="cs-hint"><strong>Guardrail:</strong> ${brief.metadata.credibility_note}</p>` : ""}
      `, "") : ""}
    </div>`;
}

function switchHint(concept) {
  const options = concept.options || [];
  const selected = concept.selected || {};
  const runnerUp = options
    .filter((option) => option.id !== selected.id)
    .sort((a, b) => b.score - a.score)[0];
  if (!runnerUp) return "";
  const gap = Math.round((selected.score - runnerUp.score) * 10) / 10;
  if (gap > 8) return "";
  return html`
    <div class="cs-switch">
      <p><strong>Close call.</strong> ${runnerUp.name} came within ${gap} points of
        ${selected.name}. That is inside the noise, so the choice is yours if you want it.</p>
      ${S.mode !== "automatic"
        ? html`<button class="cs-ghost" data-concept="${runnerUp.id}">Build ${runnerUp.name} instead</button>`
        : html`<button class="cs-ghost" id="tiebreak">Let me choose</button>`}
    </div>`;
}

function highlightTags(text) {
  return String(text || "").split(/(\s+)/).map((token) => (
    token.startsWith("#") ? html`<span class="cs-tag">${token}</span>` : token
  ));
}

function packagePanel(project) {
  const seo = pick(project, "seo");
  if (!seo) return html`<div class="cs-empty"><strong>Not written yet</strong>The publishing package is written once the film exists.</div>`;

  return html`
    <div class="cs-panel">
      ${section("How it reads in the app", html`
        <div class="cs-caption-preview">
          <div class="handle">
            <span class="avatar" aria-hidden="true">OM</span>
            <span class="who">yourstudio <span>· now</span></span>
          </div>
          <div class="cs-caption-text">${highlightTags(seo.caption.text)}</div>
          <div class="cs-caption-fold">${seo.caption.characters} characters · hook lands ${seo.caption.hook_in_fold ? "before" : "after"} the fold</div>
        </div>
        <div class="cs-chips">
          <button class="cs-ghost" id="copyCaption">Copy caption + hashtags</button>
        </div>

        <p class="cs-hint">${seo.caption.why}</p>`, "")}

      <div class="cs-cols">
      <div class="cs-col">
      ${section(`Hashtags · ${seo.hashtags.count}`, html`
        <div class="cs-chips">
          ${seo.hashtags.selected.map((tag) => html`
            <button class="cs-chip" data-copy="${tag}">${tag}</button>`)}
        </div>
        <p class="cs-hint">${seo.hashtags.guidance}</p>`, "")}

      ${section("Search terms", html`
        <div class="cs-chips">
          ${seo.keywords.targets.map((term) => html`
            <button class="cs-chip" data-copy="${term}">${term}</button>`)}
        </div>
        <ul class="cs-list">
          ${seo.keywords.where_they_go.map((line) => html`<li>${line}</li>`)}
        </ul>
        <p class="cs-hint">${seo.keywords.note}</p>`, "")}

      ${seo.cover ? section("Cover frame", html`
        <p style="font-family:var(--display);font-size:26px;line-height:1.15;letter-spacing:-.01em">
          ${seo.cover.thumbnail_text}</p>
        <p class="cs-hint">${seo.cover.reason}
          ${(seo.cover.alternates || []).length ? ` Alternates: ${seo.cover.alternates.join(" · ")}` : ""}</p>`, "") : ""}

      ${section("Posting plan", html`
        <ul class="cs-list">
          ${seo.posting_plan.slots.map((slot) => html`
            <li>${slot.date} · ${slot.window_local} — ${slot.reason}</li>`)}
        </ul>
        <p class="cs-hint">${seo.posting_plan.disclaimer}</p>`, "")}
      </div>

      <div class="cs-col">
      ${section("Sound", html`
        <p><strong>${seo.sound.mood}</strong> · ${seo.sound.tempo_target}</p>
        <p class="cs-hint">${seo.sound.instruction}</p>
        <div class="cs-chips">
          ${seo.sound.search_terms.map((term) => html`
            <button class="cs-chip" data-copy="${term}">${term}</button>`)}
        </div>`, "")}

      ${section("Before you post", html`
        ${seo.checklist.map((item) => html`
          <div class="cs-check ${item.done ? "done" : ""}">
            <span class="mark" aria-hidden="true">✓</span>
            <span>${item.item}</span>
            <span class="detail">${shortDetail(item.detail)}</span>
          </div>`)}`, "")}

      ${(seo.series || []).length ? section("What to post next", html`
        <ul class="cs-list">
          ${seo.series.map((item) => html`
            <li><strong>${item.when}</strong> — ${item.concept}. ${item.why}</li>`)}
        </ul>`, "series") : ""}
      </div>
      </div>

      ${section("What this cannot promise", html`
        <p>${seo.expectations.statement}</p>
        <p class="cs-hint">Search volume: ${seo.evidence.search_volume}.</p>`, "")}
    </div>`;
}

function qualityPanel(project) {
  const review = pick(project, "final_review");
  const findings = pick(project, "review");
  const intent = pick(project, "intent") || {};

  if (!review) {
    if (intent.deliverable === "image") {
      const frames = pick(project, "assets")?.assets || [];
      return html`
        <div class="cs-panel">
          ${section("Still brief — no film to check", html`
            <p>${frames.length} frame${frames.length === 1 ? "" : "s"} produced. You asked for an
               image, so the studio stopped there instead of rendering a video you did not ask for.</p>`, "")}
          ${section("Where the frames came from", html`<p>${provenanceSummary(project)}</p>`, "")}
        </div>`;
    }
    return html`<div class="cs-empty"><strong>Checks run after the render</strong>Quality control samples the finished file.</div>`;
  }

  const checks = review.checks || {};
  const technical = checks.technical_probe || {};
  const subtitles = checks.subtitle_check || {};
  const promise = checks.promise_preservation || {};

  return html`
    <div class="cs-panel">
      ${section("Findings", html`
        <p>
          <span class="cs-pill ${review.status === "pass" ? "ok" : "warn"}">${review.status}</span>
          <span class="cs-hint">${(findings?.findings || []).length} finding(s) · suggested:
            ${ACTIONS[review.recommended_action] || review.recommended_action}</span>
        </p>
        <div class="cs-findings">
          ${(findings?.findings || []).length
            ? findings.findings.map((finding) => html`
                <div class="cs-finding">
                  <span class="sev ${finding.severity}">${finding.severity}</span>
                  <span>${finding.description}</span>
                </div>`)
            : html`<p class="cs-hint">Nothing was flagged. The file passed every automated check
                and the sampler found no blank or broken frames.</p>`}
        </div>`, "automated review")}

      <div class="cs-cols">
        <div class="cs-col">
          ${section("Technical", html`
            <p>${technical.resolution} · ${technical.duration_seconds}s · ${technical.fps} fps ·
               ${Math.round((technical.file_size_bytes || 0) / 1024)} KB</p>
            <p class="cs-hint">${technical.issues?.length ? technical.issues.join(" · ") : "No technical issues."}</p>`, technical.codec || "")}

          ${section("Captions", html`
            <p>Coverage ${Math.round((subtitles.coverage_ratio || 0) * 100)}% ·
               ${subtitles.timing_drift_detected ? "timing drift detected" : "timing matches the script"}</p>
            <p class="cs-hint">Captions are burned from a caption script, so they are a timeline object
               rather than a file bolted on afterwards.</p>`, "")}
        </div>

        <div class="cs-col">
          ${section("Where the frames came from", html`
            <p>${provenanceSummary(project)}</p>
            <p class="cs-hint">${promise.delivery_promise_honored
              ? "What the plan promised is what was delivered."
              : "Model generation was planned but not reachable — every frame is labelled as a local preview."}</p>`, `runtime ${promise.render_runtime_used || "ffmpeg"}`)}
        </div>
      </div>
    </div>`;
}

function advancedPanel(project) {
  if (S.mode !== "advanced") {
    return html`<div class="cs-empty"><strong>Hidden by design</strong>Switch to Advanced mode in the header to inspect prompts and the timeline.</div>`;
  }
  const prompts = pick(project, "prompts");
  const storyboard = pick(project, "storyboard");
  const edit = pick(project, "edit");

  return html`
    <div class="cs-panel">
      ${section("Prompts, per shot", html`
        <div class="cs-prompt">
          ${(prompts?.shots || []).map((entry, index) => html`
            <div class="cs-prompt-item">
              <label for="prompt-${index}">${entry.shot_id}</label>
              <textarea id="prompt-${index}" rows="2">${entry.prompt}</textarea>
              <div class="row">
                <button class="cs-ghost" data-regen="${index}">Regenerate this shot</button>
              </div>
            </div>`)}
        </div>
        ${prompts?.negative_prompt
          ? html`<p class="cs-hint"><strong>Negative:</strong> ${prompts.negative_prompt}</p>` : ""}`, "")}

      ${section("Timeline", html`
        <div class="cs-filmstrip" aria-hidden="true">
          ${(edit?.cuts || []).map((cut) => html`
            <span class="seg" style="flex:${Math.max(0.2, cut.out_seconds - cut.in_seconds).toFixed(2)}"
                  title="${cut.transition_in} · ${(cut.out_seconds - cut.in_seconds).toFixed(2)}s"></span>`)}
        </div>
        <div class="cs-timeline-wrap">
          <table class="cs-timeline">
            <thead><tr><th>#</th><th>In</th><th>Out</th><th>Transition</th><th>Scene</th></tr></thead>
            <tbody>
              ${(edit?.cuts || []).map((cut, index) => html`
                <tr>
                  <td>${index + 1}</td>
                  <td>${Number(cut.in_seconds).toFixed(2)}s</td>
                  <td>${Number(cut.out_seconds).toFixed(2)}s</td>
                  <td>${cut.transition_in || "cut"}</td>
                  <td class="desc">${storyboard?.scenes?.[index]?.description || ""}</td>
                </tr>`)}
            </tbody>
          </table>
        </div>`, `${(edit?.cuts || []).length} cuts`)}

      ${section("Repository artifacts", html`
        <p class="cs-hint">Written next to the project, validated against
          <code>schemas/artifacts/*.json</code>.</p>
        <div class="cs-artifacts" id="artifactList">
          <span class="cs-hint">Loading…</span>
        </div>`, "")}
    </div>`;
}

function wireTab(project) {
  document.getElementById("copyCaption")?.addEventListener("click", copyCaption);
  document.getElementById("tiebreak")?.addEventListener("click", () => {
    setMode("control");
  });

  $$("[data-copy]").forEach((chip) => chip.addEventListener("click", async () => {
    const ok = await copy(chip.dataset.copy, `Copied ${chip.dataset.copy}`);
    if (ok) {
      chip.classList.add("is-copied");
      setTimeout(() => chip.classList.remove("is-copied"), 1400);
    }
  }));

  $$("[data-concept]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api(`/projects/${project.id}/refine`, {
        method: "POST",
        body: JSON.stringify({ operation: "concept", payload: { concept_id: button.dataset.concept } }),
      });
      toast("Angle changed — rebuilding the piece around it");
      S.stageSince = Date.now();
      S.lastStage = null;
      S.project = { ...S.project, status: "running" };
      renderProgress(S.project);
      startPolling();
    } catch (error) {
      toast(error.message, "err");
      button.disabled = false;
    }
  }));

  $$("[data-line]").forEach((button) => button.addEventListener("click", async () => {
    const index = Number(button.dataset.line);
    const text = document.getElementById(`line-${index}`)?.value || "";
    button.disabled = true;
    try {
      await api(`/projects/${project.id}/refine`, {
        method: "POST",
        body: JSON.stringify({
          operation: "caption_text",
          payload: { section_id: button.dataset.section, text },
        }),
      });
      toast("Caption updated — re-burning the film");
      S.stageSince = Date.now();
      S.lastStage = null;
      S.project = { ...S.project, status: "running" };
      renderProgress(S.project);
      startPolling();
    } catch (error) {
      toast(error.message, "err");
      button.disabled = false;
    }
  }));

  $$("[data-regen]").forEach((button) => button.addEventListener("click", () => {
    const index = Number(button.dataset.regen);
    const value = document.getElementById(`prompt-${index}`)?.value || "";
    regenerateScene(index, value);
  }));

  $$(".cs-prompt textarea").forEach((box) => {
    const fit = () => { box.style.height = "auto"; box.style.height = `${box.scrollHeight + 2}px`; };
    fit();
    box.addEventListener("input", fit);
  });

  const list = document.getElementById("artifactList");
  if (list) {
    api(`/projects/${project.id}/inspect`)
      .then((data) => {
        const files = data.artifacts || [];
        list.innerHTML = files.length
          ? files.map((file) => `<a href="${artifactUrl(project.id, file)}" target="_blank" rel="noopener">${esc(file)}</a>`).join("")
          : `<span class="cs-hint">No artifacts written yet.</span>`;
      })
      .catch(() => { list.innerHTML = `<span class="cs-hint">Artifacts unavailable.</span>`; });
  }
}

async function regenerateScene(index, prompt) {
  const plan = pick(S.project, "visual_plan");
  const shot = plan?.shots?.[index];
  if (!shot) return;
  const description = String(prompt).split(".")[0].slice(0, 240);
  try {
    await api(`/projects/${S.projectId}/refine`, {
      method: "POST",
      body: JSON.stringify({ operation: "scene", payload: { scene_index: index, description } }),
    });
    toast(`Regenerating ${shot.id} only`);
    S.stageSince = Date.now();
    S.lastStage = null;
    S.project = { ...S.project, status: "running" };
    renderProgress(S.project);
    startPolling();
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ── refine forms ────────────────────────────────────────────────── */

function openRefine(operation) {
  const host = document.getElementById("refineForm");
  if (!host) return;
  const project = S.project;
  const plan = pick(project, "visual_plan");
  const intent = pick(project, "intent");

  const forms = {
    hook: html`
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" placeholder="New opening line" autocomplete="off" />
          <button class="cs-primary" data-run="hook">Apply</button>
        </div>
        <p class="cs-refine-hint">Words only. Captions are re-timed and the film re-cut; the artwork
           is reused, so this takes seconds.</p>
      </div>`,
    scene: html`
      <div class="cs-refine">
        <div class="cs-refine-row">
          <select class="cs-select" id="refineScene">
            ${(plan?.shots || []).map((shot, index) => html`
              <option value="${index}">Scene ${index + 1} · ${shot.beat}</option>`)}
          </select>
          <button class="cs-primary" data-run="scene">Apply</button>
        </div>
        <textarea id="refineValue" rows="2" placeholder="What should this scene become?"></textarea>
        <p class="cs-refine-hint">Only this scene is regenerated. Every other shot is reused, then the
           timeline and captions follow.</p>
      </div>`,
    palette: html`
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" value="${(plan?.palette || []).join(", ")}" autocomplete="off" />
          <button class="cs-primary" data-run="palette">Apply</button>
        </div>
        <p class="cs-refine-hint">Comma-separated hex colours. Grade, frames and caption colour update;
           script and timing do not.</p>
      </div>`,
    duration: html`
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" type="number" min="4" max="120"
                 value="${intent?.duration_seconds || 15}" />
          <button class="cs-primary" data-run="duration">Apply</button>
        </div>
        <p class="cs-refine-hint">Length runs through every beat, so the structure is rebuilt to fit.</p>
      </div>`,
    sound: html`
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" placeholder="e.g. minimal cinematic, low strings" autocomplete="off" />
          <button class="cs-primary" data-run="sound">Apply</button>
        </div>
        <p class="cs-refine-hint">The export stays silent by design — this changes the brief you take
           into the app.</p>
      </div>`,
  };

  mount(host, forms[operation] || html``);
  host.scrollIntoView({ block: "nearest", behavior: "smooth" });
  $("[data-run]", host)?.addEventListener("click", () => runRefine(operation));

  const input = document.getElementById("refineValue");
  if (input) {
    if (operation === "hook") {
      const first = pick(project, "script")?.sections?.[0];
      if (first) input.value = first.text;
    }
    input.focus();
    if (input.select) input.select();
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        runRefine(operation);
      }
    });
  }
}

async function runRefine(operation) {
  const value = document.getElementById("refineValue")?.value ?? "";
  const payload = {};
  if (operation === "hook") payload.hook = value.trim();
  if (operation === "scene") {
    payload.scene_index = Number(document.getElementById("refineScene")?.value || 0);
    payload.description = value.trim();
  }
  if (operation === "palette") payload.palette = value.split(",").map((c) => c.trim()).filter(Boolean);
  if (operation === "duration") payload.seconds = Number(value);
  if (operation === "sound") payload.mood = value.trim();

  const button = document.querySelector(`[data-run="${operation}"]`);
  if (button) { button.disabled = true; button.innerHTML = `<span class="cs-spin"></span>`; }

  try {
    const result = await api(`/projects/${S.projectId}/refine`, {
      method: "POST",
      body: JSON.stringify({ operation, payload }),
    });
    toast(`${result.label} — rebuilding ${result.recomputing.length} step(s)`);
    S.stageSince = Date.now();
    S.lastStage = null;
    S.project = { ...S.project, status: "running" };
    renderProgress(S.project);
    startPolling();
  } catch (error) {
    toast(error.message, "err");
    if (button) { button.disabled = false; button.textContent = "Apply"; }
  }
}

/* ── library ─────────────────────────────────────────────────────── */

async function renderLibrary() {
  stopPolling();
  mount(main(), html`
    <div class="cs-lib-head">
      <div>
        <h1>Projects</h1>
        <p>Every campaign keeps its brief, shots, cut and package together.</p>
      </div>
      <button class="cs-primary" id="newCampaign">New campaign</button>
    </div>
    <div class="cs-grid">
      <div class="cs-skeleton"></div>
      <div class="cs-skeleton"></div>
      <div class="cs-skeleton"></div>
    </div>`);

  document.getElementById("newCampaign")?.addEventListener("click", () => {
    S.project = null;
    S.projectId = null;
    S.upload = null;
    setView("create");
  });

  try {
    const data = await api("/projects");
    const projects = data.projects || [];
    const count = document.getElementById("navCount");
    if (count) count.textContent = projects.length;

    if (!projects.length) {
      mount(main(), html`
        <div class="cs-lib-head">
          <div><h1>Projects</h1><p>Nothing here yet.</p></div>
          <button class="cs-primary" id="newCampaign">New campaign</button>
        </div>
        <div class="cs-empty">
          <strong>No campaigns yet</strong>
          Start with a sentence or a photograph — the studio does the rest.
        </div>`);
      document.getElementById("newCampaign")?.addEventListener("click", () => setView("create"));
      return;
    }

    const kinds = [...new Set(projects.map((p) => p.niche).filter(Boolean))];
    const shown = projects.filter((p) => !S.libFilter || p.niche === S.libFilter);

    mount(main(), html`
      <div class="cs-lib-head">
        <div>
          <h1>Projects</h1>
          <p>${projects.length} campaign${projects.length === 1 ? "" : "s"} · every one keeps its
             brief, shots, cut and package together.</p>
        </div>
        <button class="cs-primary" id="newCampaign">New campaign</button>
      </div>

      ${kinds.length > 1 ? html`
        <div class="cs-lib-tools">
          <span class="count">${shown.length} shown</span>
          <button class="cs-filter ${!S.libFilter ? "is-on" : ""}" data-filter="">All</button>
          ${kinds.map((kind) => html`
            <button class="cs-filter ${S.libFilter === kind ? "is-on" : ""}" data-filter="${kind}">${kind}</button>`)}
        </div>` : ""}

      <div class="cs-grid">
        ${shown.map((project, index) => html`
          <button class="cs-tile cs-in" data-open="${project.id}" style="animation-delay:${index * 35}ms">
            <span class="thumb" style="${project.poster ? `background-image:url('${mediaUrl(project.id, project.poster)}')` : ""}">
              <span class="tag ${project.status}">${project.status}</span>
            </span>
            <span class="body">
              <strong>${project.title}</strong>
              <small>${[project.concept, project.niche].filter(Boolean).join(" · ")}</small>
            </span>
          </button>`)}
      </div>`);

    $$("[data-filter]").forEach((button) => button.addEventListener("click", () => {
      S.libFilter = button.dataset.filter || "";
      renderLibrary();
    }));

    document.getElementById("newCampaign")?.addEventListener("click", () => {
      S.project = null; S.projectId = null; S.upload = null; setView("create");
    });
    $$("[data-open]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        S.projectId = button.dataset.open;
        S.project = await api(`/projects/${S.projectId}`);
        S.tab = "decision";
        setView("project");
      } catch (error) {
        toast(error.message, "err");
        button.disabled = false;
      }
    }));
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ── boot ────────────────────────────────────────────────────────── */

setMode(S.mode, { silent: true });
setView("create");
api("/projects")
  .then((data) => {
    S.recent = data.projects || [];
    const count = document.getElementById("navCount");
    if (count) count.textContent = data.count || 0;
    const untouched = !document.getElementById("briefText")?.value;
    if (S.view === "create" && untouched) renderCreate();
  })
  .catch(() => { /* the count and the latest-work card are decoration */ });
