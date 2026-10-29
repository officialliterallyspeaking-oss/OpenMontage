/* OpenMontage — Creative & Growth Studio
   One project, four systems, six honest stages. */

const API = "/api/studio";

const state = {
  view: "create",
  mode: localStorage.getItem("om-mode") || "automatic",
  path: "text",            // image | text | tiktok
  project: null,
  projectId: null,
  tab: "decision",
  upload: null,
  busy: false,
  library: [],
  capabilities: null,
  poll: null,
  advancedScene: null,
};

const el = (id) => document.getElementById(id);
const main = el("main");

/* ── utilities ──────────────────────────────────────────────── */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function toast(message, kind = "") {
  const node = el("toast");
  node.textContent = message;
  node.className = `cs-toast ${kind}`;
  node.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { node.hidden = true; }, 4200);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: options.body instanceof FormData ? {} : { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) { /* non-JSON error */ }
    throw new Error(detail);
  }
  return response.json();
}

const mediaUrl = (projectId, file) => `${API}/projects/${projectId}/media/${encodeURIComponent(file)}`;
const artifactUrl = (projectId, file) => `${API}/projects/${projectId}/artifacts/${encodeURIComponent(file)}`;

function pick(project, name) {
  const component = project?.components?.[name];
  return component && component.done ? component.data : null;
}

function provenanceLabel(project) {
  const render = pick(project, "render");
  const assets = pick(project, "assets");
  if (!render) return ["", ""];
  const kinds = new Set((assets?.assets || []).map((a) => a.provenance));
  if (kinds.has("model") && kinds.size === 1) return ["Model generated", "ok"];
  if (kinds.has("model")) return ["Mixed model + local", "warn"];
  if (kinds.has("source")) return ["From your image", "ok"];
  if (render.provenance === "local_preview") return ["Local preview · no model", "warn"];
  return ["Local render", "warn"];
}

/* ── shell ──────────────────────────────────────────────────── */

function setMode(mode) {
  state.mode = mode;
  localStorage.setItem("om-mode", mode);
  document.querySelectorAll(".cs-mode button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mode === mode);
  });
  if (state.view === "project") renderProject();
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".cs-nav-btn").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.nav === view);
  });
  if (view === "create") renderCreate();
  if (view === "library") renderLibrary();
  if (view === "project") { renderProject(); if (state.project?.status === "running") startPolling(); }
}

document.querySelectorAll(".cs-nav-btn").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.nav));
});
document.querySelectorAll(".cs-mode button").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

/* ── create ─────────────────────────────────────────────────── */

const PATHS = {
  image: {
    id: "image",
    icon: "◧",
    title: "Create from an image",
    blurb: "Drop a photo. The studio reads its light and colour, then builds the film and the post around it.",
    tag: "Image → video",
  },
  text: {
    id: "text",
    icon: "✎",
    title: "Create from text",
    blurb: "One sentence is enough. The studio decides the angle, the shots and the words.",
    tag: "",
  },
  tiktok: {
    id: "tiktok",
    icon: "▶",
    title: "Create TikTok content",
    blurb: "A complete campaign: script, storyboard, video, captions, hashtags and a posting plan.",
    tag: "Full package",
  },
};

function renderCreate() {
  stopPolling();
  main.innerHTML = `
    <section class="cs-hero">
      <h1>Describe it. The studio <em>makes the decisions</em>.</h1>
      <p>You bring an idea or an image. The content director picks the angle, the creative engine
         designs the visuals, production cuts and checks the film, and growth writes the post.
         One project, four systems, no prompt engineering.</p>
    </section>

    <div class="cs-paths" role="tablist" aria-label="Starting point">
      ${Object.values(PATHS).map((path) => `
        <button class="cs-path ${state.path === path.id ? "is-on" : ""}" data-path="${path.id}"
                role="tab" aria-selected="${state.path === path.id}">
          ${path.tag ? `<span class="tag">${esc(path.tag)}</span>` : ""}
          <span class="icon" aria-hidden="true">${path.icon}</span>
          <strong>${esc(path.title)}</strong>
          <span>${esc(path.blurb)}</span>
        </button>`).join("")}
    </div>

    <section class="cs-composer" id="composer">
      <div class="cs-composer-head">
        <h2 id="composerTitle">${esc(PATHS[state.path].title)}</h2>
        <span class="cs-hint" id="capabilityHint"></span>
      </div>

      ${state.path === "image" ? `
        <div class="cs-drop" id="drop" tabindex="0" role="button" aria-label="Choose an image">
          <div class="txt" id="dropText">
            <strong>Drop an image, or click to choose</strong>
            <span>PNG · JPG · WEBP · up to 32 MB. Portrait works best.</span>
          </div>
        </div>` : ""}

      <textarea id="briefText" placeholder="${state.path === "image"
        ? "What should this image become? e.g. a quiet, cinematic reveal for autumn"
        : "e.g. why pressing beats man-marking in modern football"}"></textarea>

      <div class="cs-row" id="optionsRow">
        <div class="cs-field">
          <label for="platform">Platform</label>
          <select id="platform">
            <option value="">Let the studio choose</option>
            <option value="tiktok">TikTok</option>
            <option value="instagram">Instagram</option>
            <option value="youtube">YouTube</option>
            <option value="linkedin">LinkedIn</option>
          </select>
        </div>
        <div class="cs-field">
          <label for="length">Length</label>
          <select id="length">
            <option value="">Let the studio choose</option>
            <option value="8">8 seconds</option>
            <option value="12">12 seconds</option>
            <option value="15">15 seconds</option>
            <option value="22">22 seconds</option>
            <option value="30">30 seconds</option>
          </select>
        </div>
        <div class="cs-field">
          <label for="provider">Generator</label>
          <select id="provider">
            <option value="auto">Automatic</option>
            <option value="local">Local design (always works)</option>
          </select>
        </div>
      </div>

      <div class="cs-composer-foot">
        <button class="cs-primary" id="createBtn">Create it <span aria-hidden="true">→</span></button>
        <span class="cs-hint" id="createHint">Everything after this is automatic. You can change any single
          decision afterwards without starting over.</span>
      </div>
    </section>`;

  document.querySelectorAll(".cs-path").forEach((button) => {
    button.addEventListener("click", () => { state.path = button.dataset.path; renderCreate(); });
  });

  const drop = el("drop");
  if (drop) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp";
    input.hidden = true;
    document.body.appendChild(input);
    input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); input.click(); }
    });
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

  el("createBtn").addEventListener("click", startProject);
  loadCapabilities();
}

async function uploadFile(file) {
  const drop = el("drop");
  drop.classList.add("has-image");
  el("dropText").innerHTML = `<strong>${esc(file.name)}</strong><span>Uploading…</span>`;
  try {
    const data = new FormData();
    data.append("file", file);
    const result = await api("/upload", { method: "POST", body: data });
    state.upload = result;
    drop.innerHTML = `<img src="${esc(result.url)}" alt="" />
      <div class="txt"><strong>${esc(result.filename || file.name)}</strong>
      <span>${result.width}×${result.height} · ${Math.round(result.bytes / 1024)} KB · click to replace</span></div>`;
    el("dropText")?.parentElement?.classList.add("has-image");
  } catch (error) {
    state.upload = null;
    toast(`Upload failed: ${error.message}`, "err");
    renderCreate();
  }
}

async function loadCapabilities() {
  try {
    state.capabilities = await api("/capabilities");
    const hint = el("capabilityHint");
    if (!hint) return;
    const image = state.capabilities.image;
    const video = state.capabilities.video;
    hint.innerHTML = (image.available || video.available)
      ? `<strong>Model generation available.</strong> ${esc(image.chosen || video.chosen || "")}`
      : `<strong>No model provider is configured here.</strong> The studio will run the full
         pipeline and label every frame as a local preview.`;
  } catch (_) { /* capabilities are advisory */ }
}

async function startProject() {
  if (state.busy) return;
  const text = el("briefText").value.trim();
  if (state.path === "image" && !state.upload) {
    toast("Add an image first — or start from text.", "err");
    return;
  }
  if (!text && !state.upload) {
    toast("Give the studio a sentence to work from.", "err");
    return;
  }
  state.busy = true;
  const button = el("createBtn");
  button.disabled = true;
  button.innerHTML = `<span class="cs-spin"></span> Starting`;
  try {
    const payload = {
      mode: state.path,
      text,
      upload_id: state.upload?.upload_id || "",
      platform: el("platform").value,
      duration_seconds: el("length").value ? Number(el("length").value) : null,
      provider: el("provider").value,
    };
    const project = await api("/projects", { method: "POST", body: JSON.stringify(payload) });
    state.project = project;
    state.projectId = project.id;
    state.tab = "decision";
    setView("project");
  } catch (error) {
    toast(error.message, "err");
    button.disabled = false;
    button.innerHTML = `Create it <span aria-hidden="true">→</span>`;
  } finally {
    state.busy = false;
  }
}

/* ── progress + project ─────────────────────────────────────── */

function stopPolling() {
  if (state.poll) { clearTimeout(state.poll); state.poll = null; }
}

function startPolling() {
  stopPolling();
  const tick = async () => {
    if (!state.projectId) return;
    try {
      const project = await api(`/projects/${state.projectId}`);
      state.project = project;
      if (state.view !== "project") return;
      if (project.status === "running") {
        renderProgress(project);
        state.poll = setTimeout(tick, 900);
      } else {
        renderProject();
      }
    } catch (error) {
      toast(error.message, "err");
    }
  };
  tick();
}

const STAGE_ICON = { done: "✓", active: "", partial: "•", pending: "" };

function renderProgress(project) {
  const stages = project.progress || [];
  const events = (project.events || []).slice(-14).reverse();
  main.innerHTML = `
    <section class="cs-hero" style="margin-bottom:22px">
      <h1 style="font-size:clamp(24px,3vw,34px)">${esc(project.title || "Your campaign")}</h1>
      <p>Working through one shared project. Every line below is a step that has actually run.</p>
    </section>
    <div class="cs-progress">
      <div class="cs-stages">
        ${stages.map((stage) => `
          <div class="cs-stage is-${stage.status}">
            <div class="dot"><span>${STAGE_ICON[stage.status] || ""}</span></div>
            <div class="label">${esc(stage.label)}</div>
            <div class="meta">${stage.completed}/${stage.total}</div>
          </div>`).join("")}
      </div>
      <aside class="cs-feed">
        <h3>What the systems are doing</h3>
        <ul>
          ${events.length ? events.map((event) => `
            <li><span class="sys ${esc(event.system)}">${esc(event.system)}</span>
                <span class="msg">${esc(event.message)}</span></li>`).join("")
            : `<li><span class="sys studio">studio</span><span class="msg">Starting…</span></li>`}
        </ul>
      </aside>
    </div>
    ${project.status === "failed" ? `
      <div class="cs-card" style="margin-top:20px;border-color:#5b2626">
        <h3>Stopped</h3>
        <p>${esc(project.error || "Something went wrong.")}</p>
        <p>Everything already finished is kept — the render, the script and the package are not lost.</p>
        <button class="cs-primary" id="retryBtn">Resume from where it stopped</button>
      </div>` : ""}`;

  const retry = el("retryBtn");
  if (retry) {
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      try {
        await api(`/projects/${state.projectId}/retry`, { method: "POST" });
        startPolling();
      } catch (error) { toast(error.message, "err"); retry.disabled = false; }
    });
  }
}

function renderProject() {
  stopPolling();
  const project = state.project;
  if (!project) return;
  if (project.status === "running") { renderProgress(project); startPolling(); return; }
  if (project.status === "failed") { renderProgress(project); return; }

  const render = pick(project, "render");
  const assets = pick(project, "assets");
  const concept = pick(project, "concept");
  const seo = pick(project, "seo");
  const review = pick(project, "final_review");
  const [provLabel, provKind] = provenanceLabel(project);

  main.innerHTML = `
    <div class="cs-project">
      <div>
        <div class="cs-phone">
          ${render
            ? `<video src="${mediaUrl(project.id, render.url)}" poster="${render.poster_url ? mediaUrl(project.id, render.poster_url) : ""}"
                      controls playsinline preload="metadata"></video>`
            : `<img src="${(assets?.assets?.[0]?.url) ? mediaUrl(project.id, assets.assets[0].url) : ""}" alt="" />`}
          ${render ? `<span class="badge ${provKind === "warn" ? "warn" : ""}">${esc(provLabel)}</span>` : ""}
        </div>
        <div class="cs-actions" style="margin-top:12px">
          ${render ? `<a class="cs-ghost" href="${mediaUrl(project.id, render.url)}" download>Download</a>` : ""}
          <button class="cs-ghost" id="newBtn">New campaign</button>
          ${seo ? `<button class="cs-ghost" id="copyCaption">Copy caption</button>` : ""}
        </div>
      </div>

      <div class="cs-side">
        <div class="cs-headline">
          <h1>${esc(project.title || "Your campaign")}</h1>
          <div class="cs-sub">
            ${concept ? `<span class="cs-pill">${esc(concept.selected.name)}</span>` : ""}
            <span class="cs-pill">${esc(concept ? `${concept.selected.score}/100` : "")}</span>
            ${render ? `<span class="cs-pill">${render.width}×${render.height} · ${render.duration_seconds}s</span>` : ""}
            ${review ? `<span class="cs-pill ${review.status === "pass" ? "ok" : "warn"}">QA ${esc(review.status)}</span>` : ""}
            <span class="cs-pill ${provKind}">${esc(provLabel)}</span>
            ${render?.has_captions ? `<span class="cs-pill">Captions burned in</span>` : ""}
          </div>
        </div>

        ${state.mode !== "automatic" ? refineBar(project) : `
          <div class="cs-actions">
            <button class="cs-primary" id="changeBtn">Change something</button>
            <span class="cs-hint">Switch to Creative Control to change one decision without rebuilding the rest.</span>
          </div>`}

        <div class="cs-tabs" role="tablist">
          ${[["decision", "The decision"], ["package", "Publishing package"], ["quality", "Quality"],
             ["advanced", "Advanced"]]
            .filter(([key]) => key !== "advanced" || state.mode === "advanced")
            .map(([key, label]) => `
              <button class="cs-tab ${state.tab === key ? "is-active" : ""}" data-tab="${key}">${label}</button>`)
            .join("")}
        </div>
        <div id="tabBody"></div>
      </div>
    </div>`;

  document.querySelectorAll(".cs-tab").forEach((button) => {
    button.addEventListener("click", () => { state.tab = button.dataset.tab; renderProject(); });
  });
  el("newBtn")?.addEventListener("click", () => { state.project = null; state.projectId = null; state.upload = null; setView("create"); });
  el("changeBtn")?.addEventListener("click", () => setMode("control"));
  el("copyCaption")?.addEventListener("click", () => copyCaption());
  document.querySelectorAll("[data-refine]").forEach((button) => {
    button.addEventListener("click", () => openRefine(button.dataset.refine));
  });
  renderTab();
}

function copyCaption() {
  const seo = pick(state.project, "seo");
  if (!seo) return;
  const text = `${seo.caption.text}\n\n${(seo.hashtags?.selected || []).join(" ")}`;
  navigator.clipboard?.writeText(text).then(
    () => toast("Caption and hashtags copied"),
    () => toast("Could not access the clipboard", "err"),
  );
}

function refineBar(project) {
  const actions = [
    ["hook", "Rewrite the opening line"],
    ["scene", "Change one scene"],
    ["palette", "Change the colour direction"],
    ["duration", "Change the length"],
    ["sound", "Change the sound brief"],
  ];
  return `
    <div class="cs-card">
      <h3>Creative control — change one thing</h3>
      <div class="cs-actions">
        ${actions.map(([key, label]) => `<button class="cs-ghost" data-refine="${key}">${esc(label)}</button>`).join("")}
      </div>
      <div id="refineForm" style="margin-top:12px"></div>
    </div>`;
}

function openRefine(operation) {
  const project = state.project;
  const host = el("refineForm");
  if (!host) return;
  const plan = pick(project, "visual_plan");
  const script = pick(project, "script");
  const options = {
    hook: `
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" placeholder="New opening line, e.g. Man-marking is dead." />
          <button class="cs-primary" data-run="hook">Apply</button>
        </div>
        <p class="cs-refine-hint">Only the words change. Captions are re-timed and the video is re-cut;
           the artwork is reused, so this is quick.</p>
      </div>`,
    scene: `
      <div class="cs-refine">
        <div class="cs-refine-row">
          <select id="refineScene">
            ${(plan?.shots || []).map((shot, index) => `
              <option value="${index}">Scene ${index + 1} · ${esc(shot.beat)}</option>`).join("")}
          </select>
          <button class="cs-primary" data-run="scene">Apply</button>
        </div>
        <textarea id="refineValue" rows="2" placeholder="What should this scene become?"></textarea>
        <p class="cs-refine-hint">Only this scene is regenerated. Every other shot is reused, then the
           timeline and captions follow automatically.</p>
      </div>`,
    palette: `
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" value="${esc((plan?.palette || []).join(", "))}" />
          <button class="cs-primary" data-run="palette">Apply</button>
        </div>
        <p class="cs-refine-hint">Comma-separated hex colours. The grade, frames and caption colours update;
           the script and timing do not.</p>
      </div>`,
    duration: `
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" type="number" min="4" max="120" value="${pick(project, "intent")?.duration_seconds || 15}" />
          <button class="cs-primary" data-run="duration">Apply</button>
        </div>
        <p class="cs-refine-hint">Length runs through every beat, so the structure is rebuilt to fit the new runtime.</p>
      </div>`,
    sound: `
      <div class="cs-refine">
        <div class="cs-refine-row">
          <input id="refineValue" placeholder="e.g. minimal cinematic, low strings" />
          <button class="cs-primary" data-run="sound">Apply</button>
        </div>
        <p class="cs-refine-hint">The export stays silent by design — this changes the brief you take into TikTok.</p>
      </div>`,
  };
  host.innerHTML = options[operation] || "";
  host.querySelector("[data-run]")?.addEventListener("click", () => runRefine(operation));
  if (operation === "hook" && script?.sections?.[0]) {
    el("refineValue").value = script.sections[0].text;
    el("refineValue").select();
  }
}

async function runRefine(operation) {
  const value = el("refineValue")?.value ?? "";
  const payload = {};
  if (operation === "hook") payload.hook = value;
  if (operation === "scene") {
    payload.scene_index = Number(el("refineScene").value);
    payload.description = value;
  }
  if (operation === "palette") {
    payload.palette = value.split(",").map((c) => c.trim()).filter(Boolean);
  }
  if (operation === "duration") payload.seconds = Number(value);
  if (operation === "sound") payload.mood = value;
  try {
    const result = await api(`/projects/${state.projectId}/refine`, {
      method: "POST", body: JSON.stringify({ operation, payload }),
    });
    toast(`${result.label} — recomputing ${result.recomputing.length} step(s)`);
    startPolling();
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ── tabs ───────────────────────────────────────────────────── */

function renderTab() {
  const host = el("tabBody");
  if (!host) return;
  const project = state.project;
  if (state.tab === "decision") host.innerHTML = decisionPanel(project);
  if (state.tab === "package") host.innerHTML = packagePanel(project);
  if (state.tab === "quality") host.innerHTML = qualityPanel(project);
  if (state.tab === "advanced") {
    host.innerHTML = state.mode === "advanced"
      ? advancedPanel(project)
      : `<div class="cs-empty">Advanced view is hidden in ${state.mode === "control" ? "Creative Control" : "Automatic"} mode.
         Switch the mode in the header to inspect prompts and the timeline.</div>`;
  }
  wireTab(project);
}

function provenanceSummary(project) {
  const assets = pick(project, "assets")?.assets || [];
  const counts = assets.reduce((acc, asset) => {
    acc[asset.provenance] = (acc[asset.provenance] || 0) + 1;
    return acc;
  }, {});
  const parts = [];
  if (counts.source) parts.push(`${counts.source} derived from your photograph (no generative model)`);
  if (counts.model) parts.push(`${counts.model} generated by a model provider`);
  if (counts.local) parts.push(`${counts.local} composed locally by the art director (not model output)`);
  return parts.join(" · ") || "No assets were recorded.";
}

function decisionPanel(project) {
  const concept = pick(project, "concept");
  const brief = pick(project, "brief");
  const plan = pick(project, "visual_plan");
  const intent = pick(project, "intent");
  if (!concept) return `<div class="cs-empty">The creative decision has not been made yet.</div>`;
  const selected = concept.selected;
  const assets = pick(project, "assets")?.assets || [];
  const byShot = Object.fromEntries(assets.map((a) => [a.shot_id, a]));

  return `
    <div class="cs-panel">
      <div class="cs-card">
        <h3>Why this angle</h3>
        <div class="cs-score">
          <span class="num">${selected.score}</span><span class="of">/ 100</span>
          <span class="cs-meter"><i style="width:${Math.max(4, selected.score)}%"></i></span>
        </div>
        <p><strong>${esc(selected.name)}</strong> — ${esc(selected.why || "")}</p>
        ${concept.why_not ? `<p class="cs-hint">${esc(concept.why_not)}</p>` : ""}
        <ul class="cs-why">
          ${(selected.reasons || []).slice(0, 6).map((reason) => `
            <li><span class="pts ${reason.points < 0 ? "neg" : ""}">${reason.points > 0 ? "+" : ""}${reason.points}</span>
                <span>${esc(reason.why)}</span></li>`).join("")}
        </ul>
      </div>

      <div class="cs-card">
        <h3>Every angle it considered</h3>
        <div class="cs-angles">
          ${(concept.options || []).map((option) => `
            <div class="cs-angle ${option.id === selected.id ? "is-selected" : ""}">
              <div>
                <strong>${esc(option.name)}</strong>
                <small>${esc(option.description)}</small>
              </div>
              <div style="display:flex;align-items:center;gap:10px">
                <span class="n">${option.score}</span>
                ${option.id !== selected.id && state.mode !== "automatic"
                  ? `<button class="cs-ghost" data-concept="${esc(option.id)}">Use</button>` : ""}
              </div>
            </div>`).join("")}
        </div>
      </div>

      <div class="cs-card">
        <h3>What the studio understood</h3>
        <p><strong>${esc(intent?.niche_label || "")}</strong> · ${esc(intent?.deliverable || "")} ·
           ${esc(String(intent?.duration_seconds || ""))}s · ${esc(intent?.platform || "")} ·
           audience: ${esc(intent?.audience || "")}</p>
        ${intent?.assumptions?.length ? `<ul class="cs-list">
          ${intent.assumptions.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}
        <p class="cs-hint">Confidence ${Math.round((intent?.confidence || 0) * 100)}% — based on how much
           the request actually constrained the decision.</p>
      </div>

      <div class="cs-card">
        <h3>The shot list</h3>
        <div class="cs-shots">
          ${(plan?.shots || []).map((shot, index) => {
            const asset = byShot[shot.id];
            return `<div class="cs-shot">
              <img src="${asset?.url ? mediaUrl(project.id, asset.url) : ""}" alt="" loading="lazy" />
              <div class="body">
                <strong>${esc(shot.beat)}</strong>
                <span>${esc(shot.description)}</span>
                <code>${esc(shot.framing)} · ${esc(shot.movement)} · ${shot.start_seconds}–${shot.end_seconds}s</code>
              </div>
              <span class="cs-pill">${asset ? esc(asset.provenance) : ""}</span>
            </div>`;
          }).join("")}
        </div>
      </div>

      <div class="cs-card">
        <h3>Colour direction</h3>
        <div class="cs-chips">
          ${(plan?.palette || []).map((colour) => `
            <span class="cs-chip" style="background:${esc(colour)};border-color:${esc(colour)};color:#fff">${esc(colour)}</span>`).join("")}
        </div>
        <p class="cs-hint" style="margin-top:10px">${esc(plan?.grade || "")}</p>
        ${brief?.credibility_note ? `<p class="cs-hint"><strong>Guardrail:</strong> ${esc(brief.credibility_note)}</p>` : ""}
      </div>
    </div>`;
}

function packagePanel(project) {
  const seo = pick(project, "seo");
  if (!seo) return `<div class="cs-empty">The publishing package is written after the video exists.</div>`;
  return `
    <div class="cs-panel">
      <div class="cs-card">
        <h3>Caption</h3>
        <div class="cs-caption-text">${esc(seo.caption.text)}</div>
        <p class="cs-hint" style="margin-top:8px">${esc(seo.caption.why)}</p>
        <div class="cs-actions" style="margin-top:10px">
          <button class="cs-ghost" id="copyCaption">Copy caption + hashtags</button>
          ${seo.caption.alternates?.length ? `<span class="cs-hint">Alternates: ${seo.caption.alternates.map(esc).join(" · ")}</span>` : ""}
        </div>
      </div>

      <div class="cs-card">
        <h3>Hashtags · ${seo.hashtags.count}</h3>
        <div class="cs-chips">
          ${seo.hashtags.selected.map((tag) => `<button class="cs-chip" data-copy="${esc(tag)}">${esc(tag)}</button>`).join("")}
        </div>
        <p class="cs-hint" style="margin-top:8px">${esc(seo.hashtags.guidance)}</p>
      </div>

      <div class="cs-card">
        <h3>Search terms</h3>
        <div class="cs-chips">
          ${seo.keywords.targets.map((term) => `<button class="cs-chip" data-copy="${esc(term)}">${esc(term)}</button>`).join("")}
        </div>
        <ul class="cs-list" style="margin-top:8px">
          ${seo.keywords.where_they_go.map((line) => `<li>${esc(line)}</li>`).join("")}
        </ul>
        <p class="cs-hint">${esc(seo.keywords.note)}</p>
      </div>

      <div class="cs-card">
        <h3>Sound</h3>
        <p><strong>${esc(seo.sound.mood)}</strong> · ${esc(seo.sound.tempo_target)}</p>
        <p class="cs-hint">${esc(seo.sound.instruction)}</p>
        <p class="cs-hint">Search: ${seo.sound.search_terms.map((t) => `<code>${esc(t)}</code>`).join(" ")}</p>
      </div>

      <div class="cs-card">
        <h3>Posting plan</h3>
        <ul class="cs-list">
          ${seo.posting_plan.slots.map((slot) => `
            <li>${esc(slot.date)} · ${esc(slot.window_local)} — ${esc(slot.reason)}</li>`).join("")}
        </ul>
        <p class="cs-hint">${esc(seo.posting_plan.disclaimer)}</p>
      </div>

      <div class="cs-card">
        <h3>Before you post</h3>
        ${seo.checklist.map((item) => `
          <div class="cs-check ${item.done ? "done" : ""}">
            <span class="mark">${item.done ? "✓" : "○"}</span>
            <span>${esc(item.item)}</span>
            <span class="detail">${esc(item.detail || "")}</span>
          </div>`).join("")}
      </div>

      <div class="cs-card">
        <h3>What this cannot promise</h3>
        <p>${esc(seo.expectations.statement)}</p>
        <p class="cs-hint">Search volumes were ${esc(seo.evidence.search_volume)}.</p>
      </div>
    </div>`;
}

function qualityPanel(project) {
  const review = pick(project, "final_review");
  const findings = pick(project, "review");
  if (!review) return `<div class="cs-empty">Quality checks run after the render.</div>`;
  const checks = review.checks || {};
  const technical = checks.technical_probe || {};
  const subtitles = checks.subtitle_check || {};
  const promise = checks.promise_preservation || {};
  return `
    <div class="cs-panel">
      <div class="cs-card">
        <h3>Result</h3>
        <p><span class="cs-pill ${review.status === "pass" ? "ok" : "warn"}">${esc(review.status)}</span>
           ${esc(String(findings?.findings?.length ?? 0))} finding(s) ·
           recommended: ${esc(review.recommended_action)}</p>
        <div class="cs-findings" style="margin-top:10px">
          ${(findings?.findings || []).map((finding) => `
            <div class="cs-finding">
              <span class="sev ${esc(finding.severity)}">${esc(finding.severity)}</span>
              <span>${esc(finding.description)}</span>
            </div>`).join("") || `<p class="cs-hint">No findings were raised.</p>`}
        </div>
      </div>

      <div class="cs-card">
        <h3>Technical</h3>
        <p>${esc(technical.resolution || "")} · ${esc(String(technical.duration_seconds ?? ""))}s ·
           ${esc(String(technical.fps ?? ""))} fps · ${esc(String(Math.round((technical.file_size_bytes || 0) / 1024)))} KB</p>
        <p class="cs-hint">${technical.issues?.length ? technical.issues.map(esc).join(" · ") : "No technical issues."}</p>
      </div>

      <div class="cs-card">
        <h3>Captions</h3>
        <p>Coverage ${Math.round((subtitles.coverage_ratio || 0) * 100)}% ·
           ${subtitles.timing_drift_detected ? "timing drift detected" : "timing matches the script"}</p>
        <p class="cs-hint">Captions are burned from an ASS script, so they are a timeline object, not a caption file bolted on afterwards.</p>
      </div>

      <div class="cs-card">
        <h3>Where the frames came from</h3>
        <p>${esc(provenanceSummary(state.project))}</p>
        <p class="cs-hint">${promise.delivery_promise_honored
          ? "What the plan promised is what was delivered."
          : "Model generation was planned but not reachable — every frame is labelled as a local preview."}</p>
        <p class="cs-hint">Runtime: ${esc(promise.render_runtime_used || "ffmpeg")}</p>
      </div>
    </div>`;
}

function advancedPanel(project) {
  const prompts = pick(project, "prompts");
  const storyboard = pick(project, "storyboard");
  const edit = pick(project, "edit");
  return `
    <div class="cs-panel">
      <div class="cs-card">
        <h3>Prompts, per shot</h3>
        <div class="cs-prompt">
          ${(prompts?.shots || []).map((entry, index) => `
            <div>
              <label class="cs-hint" for="prompt-${index}">${esc(entry.shot_id)}</label>
              <textarea id="prompt-${index}">${esc(entry.prompt)}</textarea>
              <div class="row">
                <button class="cs-ghost" data-regen="${index}">Regenerate this shot</button>
              </div>
            </div>`).join("") || `<p class="cs-hint">No prompts yet.</p>`}
        </div>
        ${prompts?.negative_prompt ? `<p class="cs-hint" style="margin-top:10px"><strong>Negative:</strong> ${esc(prompts.negative_prompt)}</p>` : ""}
      </div>

      <div class="cs-card">
        <h3>Timeline</h3>
        <table class="cs-timeline">
          <thead><tr><th>#</th><th>In</th><th>Out</th><th>Transition</th><th>Scene</th></tr></thead>
          <tbody>
            ${(edit?.cuts || []).map((cut, index) => {
              const scene = storyboard?.scenes?.[index];
              return `<tr>
                <td>${index + 1}</td>
                <td>${cut.in_seconds.toFixed(2)}s</td>
                <td>${cut.out_seconds.toFixed(2)}s</td>
                <td>${esc(cut.transition_in || "cut")}</td>
                <td class="desc">${esc(scene?.description || "")}</td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>

      <div class="cs-card">
        <h3>Repository artifacts</h3>
        <p class="cs-hint">Written next to the project as schema-valid OpenMontage artifacts.</p>
        <div class="cs-artifacts" id="artifactList"></div>
      </div>
    </div>`;
}

function wireTab(project) {
  el("copyCaption")?.addEventListener("click", copyCaption);
  document.querySelectorAll("[data-copy]").forEach((chip) => {
    chip.addEventListener("click", () => {
      navigator.clipboard?.writeText(chip.dataset.copy);
      toast(`Copied ${chip.dataset.copy}`);
    });
  });
  document.querySelectorAll("[data-concept]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/projects/${project.id}/refine`, {
          method: "POST",
          body: JSON.stringify({ operation: "concept", payload: { concept_id: button.dataset.concept } }),
        });
        toast("Angle changed — rebuilding the piece around it");
        startPolling();
      } catch (error) { toast(error.message, "err"); }
    });
  });
  document.querySelectorAll("[data-regen]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.regen);
      const value = el(`prompt-${index}`).value;
      runSceneFromPrompt(index, value);
    });
  });
  const list = el("artifactList");
  if (list) {
    api(`/projects/${project.id}/inspect`)
      .then((data) => {
        list.innerHTML = (data.artifacts || []).map((file) =>
          `<a href="${artifactUrl(project.id, file)}" target="_blank" rel="noopener">${esc(file)}</a>`).join("");
      })
      .catch(() => { list.innerHTML = `<span class="cs-hint">Artifacts unavailable.</span>`; });
  }
}

async function runSceneFromPrompt(index, prompt) {
  const plan = pick(state.project, "visual_plan");
  const shot = plan?.shots?.[index];
  if (!shot) return;
  const description = prompt.split(".")[0].slice(0, 240);
  try {
    await api(`/projects/${state.projectId}/refine`, {
      method: "POST",
      body: JSON.stringify({ operation: "scene", payload: { scene_index: index, description } }),
    });
    toast(`Regenerating ${shot.id} only`);
    startPolling();
  } catch (error) { toast(error.message, "err"); }
}

/* ── library ────────────────────────────────────────────────── */

async function renderLibrary() {
  stopPolling();
  main.innerHTML = `
    <div class="cs-lib-head">
      <h1>Projects</h1>
      <button class="cs-primary" id="newFromLib">New campaign</button>
    </div>
    <div id="libGrid"><div class="cs-grid">
      <div class="cs-skeleton"></div><div class="cs-skeleton"></div><div class="cs-skeleton"></div>
    </div></div>`;

  el("newFromLib").addEventListener("click", () => { state.project = null; state.projectId = null; setView("create"); });

  try {
    const data = await api("/projects");
    state.library = data.projects || [];
    el("navCount").textContent = state.library.length;
    const host = el("libGrid");
    if (!state.library.length) {
      host.innerHTML = `<div class="cs-empty">No campaigns yet. Start with an image or a sentence.</div>`;
      return;
    }
    host.innerHTML = `<div class="cs-grid">
      ${state.library.map((project) => `
        <button class="cs-tile" data-open="${esc(project.id)}">
          <div class="thumb" style="${project.poster ? `background-image:url('${mediaUrl(project.id, project.poster)}')` : ""}">
            <span class="tag">${esc(project.status)}</span>
          </div>
          <div class="body">
            <strong>${esc(project.title)}</strong>
            <small>${esc(project.concept || "")}${project.niche ? ` · ${esc(project.niche)}` : ""}</small>
          </div>
        </button>`).join("")}
    </div>`;

    document.querySelectorAll("[data-open]").forEach((button) => {
      button.addEventListener("click", async () => {
        state.projectId = button.dataset.open;
        state.project = await api(`/projects/${state.projectId}`);
        state.tab = "decision";
        setView("project");
      });
    });
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ── boot ───────────────────────────────────────────────────── */

setMode(state.mode);
setView("create");
api("/projects").then((data) => { el("navCount").textContent = data.count || 0; }).catch(() => {});
