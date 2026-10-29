/* OpenMontage Studio — client
   Talks only to the local Studio API (/api/*), which drives the repo's tools. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  mode: "image",
  presets: { aspects: [], motions: [], styles: [] },
  catalog: null,
  jobs: [],
  filter: "all",
  file: null,
  activeIds: new Set(),
  pollTimer: null,
  keys: [],
};

const SAMPLES = {
  image: [
    "A lighthouse at dusk, storm building offshore, teal and amber light",
    "Macro photo of a dew-covered spiderweb, backlit, shallow depth of field",
    "Retro-futurist poster of a floating library above the clouds",
    "A lone astronaut on a salt flat, long shadows, 35mm film grain",
  ],
  video_from_text: [
    "Drifting through a bioluminescent forest at night, slow push in",
    "Aerial glide over terraced rice fields at golden hour",
    "Neon rain-slick Tokyo alley, shallow focus, slow lateral pan",
    "Time-lapse feel: storm clouds rolling over a canyon rim",
  ],
  video_from_image: [
    "cinematic push in, subtle parallax",
    "slow pull back to reveal the scene",
    "gentle lateral drift, documentary tone",
  ],
};

/* ───────────────────────────── helpers ───────────────────────────── */

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("err", !!isError);
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 3600);
}

function fmtBytes(bytes) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let value = bytes;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
  return `${value.toFixed(value < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function fmtDuration(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(Number(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) { /* keep default */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

/* Map a port on this sandbox to a reachable preview host. */
function portHost(port) {
  const match = location.hostname.match(/^(\d+)-(.+)$/);
  if (match) return `${location.protocol}//${port}-${match[2]}`;
  return `http://127.0.0.1:${port}`;
}

/* ───────────────────────────── bootstrap ───────────────────────────── */

async function init() {
  bindEvents();
  try {
    const [presets, catalog] = await Promise.all([api("/api/presets"), api("/api/catalog")]);
    state.presets = presets;
    state.catalog = catalog;
    renderSelects();
    renderCapabilities();
    renderProviderLine();
    renderSamples();
    renderNotice();
    $("#footTools").textContent = `${catalog.tool_count} tools discovered`;
  } catch (error) {
    toast(`Could not reach the Studio API: ${error.message}`, true);
  }

  await refreshJobs();
  refreshBoardStatus();
  setInterval(refreshBoardStatus, 15000);
  if (state.activeIds.size) schedulePoll();
}

function renderSelects() {
  const aspect = $("#aspect");
  aspect.innerHTML = state.presets.aspects
    .map((a) => `<option value="${a.id}">${a.id} · ${a.px[0]}×${a.px[1]}</option>`)
    .join("");
  aspect.value = "16:9";

  const style = $("#style");
  style.innerHTML = state.presets.styles
    .map((s) => `<option value="${s.id}">${esc(s.label)}</option>`)
    .join("");
  style.value = state.presets.styles.some((s) => s.id === "clean-professional")
    ? "clean-professional"
    : (state.presets.styles[0]?.id || "");

  const motion = $("#motion");
  motion.innerHTML = state.presets.motions
    .map((m) => `<option value="${m.id}">${esc(m.label)}</option>`)
    .join("");
  motion.value = "ken_burns";

  syncProviderOptions();
  syncDurationOut();
}

function currentCapability() {
  return state.mode === "image" ? "image_generation" : "video_generation";
}

function providersFor(capability) {
  return state.catalog?.providers?.[capability] || [];
}

function syncProviderOptions() {
  const select = $("#provider");
  const capability = currentCapability();
  const providerList = state.mode === "video_from_image"
    ? [...providersFor("video_generation"), ...providersFor("image_generation")]
    : providersFor(capability);

  const unique = [];
  for (const entry of providerList) {
    if (!unique.some((u) => u.provider === entry.provider)) unique.push(entry);
  }

  select.innerHTML = [
    `<option value="auto">Auto (scored)</option>`,
    ...unique.map((p) => `<option value="${esc(p.provider)}">${esc(p.provider)}</option>`),
  ].join("");
  select.value = "auto";

  const engineHint = $("#videoModelHint");
  if (engineHint) {
    engineHint.textContent = unique.length
      ? `${unique.length} provider${unique.length === 1 ? "" : "s"} ready`
      : "needs a video provider";
  }
  renderProviderLine();
}

function renderCapabilities() {
  const chips = [];
  const caps = state.catalog?.capabilities || {};
  const image = caps.image_generation;
  const video = caps.video_generation;
  const ffmpegOk = !!state.catalog?.ffmpeg?.available;

  if (image) {
    chips.push(chip(`Image <b>${image.configured}/${image.total}</b>`, image.configured > 0));
  }
  if (video) {
    chips.push(chip(`Video <b>${video.configured}/${video.total}</b>`, video.configured > 0));
  }
  chips.push(chip(`ffmpeg ${ffmpegOk ? "ready" : "missing"}`, ffmpegOk));
  $("#capChips").innerHTML = chips.join("");

  const keysCount = state.catalog?.env?.configured?.length || 0;
  $("#keysCount").textContent = String(keysCount);
}

function chip(label, ready) {
  return `<span class="cap-chip ${ready ? "ready" : ""}"><span class="led"></span>${label}</span>`;
}

function renderProviderLine() {
  const caps = state.catalog?.capabilities || {};
  const capability = currentCapability();
  const entry = caps[capability];
  const engine = selectedEngine();
  const target = $("#providerLine");
  if (!entry) { target.innerHTML = ""; return; }

  if (state.mode === "image" || engine === "motion") {
    const ready = (caps.image_generation?.configured || 0) > 0;
    target.innerHTML = ready
      ? `<span class="pill good">image model ready</span><span class="pill">${esc(providersFor("image_generation").map((p) => p.provider).slice(0, 3).join(", "))}</span>`
      : `<span class="pill warn">no image model</span><span class="pill">labelled placeholder art</span>`;
    if (state.mode !== "image") {
      target.innerHTML += `<span class="pill good">ffmpeg motion ready</span>`;
    }
    return;
  }

  const ready = (entry.configured || 0) > 0;
  target.innerHTML = ready
    ? `<span class="pill good">video model ready</span><span class="pill">${esc(providersFor("video_generation").map((p) => p.provider).slice(0, 3).join(", "))}</span>`
    : `<span class="pill warn">no video model configured</span><span class="pill">falls back to local motion</span>`;
}

function renderNotice() {
  const caps = state.catalog?.capabilities;
  if (!caps) return;
  const imageReady = (caps.image_generation?.configured || 0) > 0;
  const videoReady = (caps.video_generation?.configured || 0) > 0;
  const notice = $("#notice");
  if (imageReady || videoReady) { notice.hidden = true; return; }

  $("#noticeTitle").textContent = "No AI provider configured yet";
  $("#noticeBody").textContent =
    "You can still render real motion video from placeholder art — add a key to unlock actual image and video models.";
  notice.hidden = false;
}

function renderSamples() {
  const samples = SAMPLES[state.mode] || [];
  $("#promptSamples").innerHTML = samples
    .map((s) => `<button type="button" class="chip" data-sample="${esc(s)}" title="${esc(s)}">${esc(s.length > 42 ? `${s.slice(0, 42)}…` : s)}</button>`)
    .join("");
}

/* ───────────────────────────── mode switching ───────────────────────────── */

function setMode(mode) {
  state.mode = mode;
  $$(".seg").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });

  $("#uploadField").hidden = mode !== "video_from_image";
  $("#motionRow").hidden = mode === "image";
  $("#engineRow").hidden = mode === "image";
  $("#imageCountRow").hidden = mode === "video_from_image";

  const countField = $("#count").closest(".field");
  if (mode === "video_from_image") {
    countField.style.display = "none";
    $("#prompt").rows = 2;
    $("#promptLabel").textContent = "Motion note (optional)";
    $("#promptHint").textContent = "What should the camera do";
    $("#prompt").placeholder = "cinematic push in, subtle parallax…";
    $("#submitLabel").textContent = "Animate image";
  } else if (mode === "video_from_text") {
    countField.style.display = "";
    $("#prompt").rows = 3;
    $("#promptLabel").textContent = "Prompt";
    $("#promptHint").textContent = "Describe the film";
    $("#prompt").placeholder = "A lighthouse at dusk, storm building offshore, cinematic teal and amber light…";
    $("#submitLabel").textContent = "Generate video";
  } else {
    countField.style.display = "";
    $("#prompt").rows = 4;
    $("#promptLabel").textContent = "Prompt";
    $("#promptHint").textContent = "Describe the shot";
    $("#prompt").placeholder = "A lighthouse at dusk, storm building offshore, cinematic teal and amber light…";
    $("#submitLabel").textContent = "Generate image";
  }

  // A video model can't be used for a plain image.
  if (mode === "image") {
    const radio = $('input[name="engine"][value="motion"]');
    if (radio) radio.checked = true;
  }

  renderSamples();
  syncProviderOptions();
  renderFineprint();
}

function selectedEngine() {
  const checked = $('input[name="engine"]:checked');
  return checked ? checked.value : "motion";
}

function renderFineprint() {
  const engine = selectedEngine();
  const target = $("#fineprint");
  if (state.mode === "image") {
    target.textContent = "Images are written to a real OpenMontage project workspace.";
  } else if (engine === "video_model") {
    target.textContent = "AI video models are billed per second by the provider.";
  } else {
    target.textContent = "Local camera motion is free and renders in a few seconds.";
  }
}

/* ───────────────────────────── upload ───────────────────────────── */

function setFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) { toast("That file is not an image", true); return; }
  if (file.size > 32 * 1024 * 1024) { toast("Image is larger than 32 MB", true); return; }
  state.file = file;
  const preview = $("#dzPreview");
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  $("#dzEmpty").hidden = true;
  $("#dzClear").hidden = false;
}

function clearFile() {
  state.file = null;
  const preview = $("#dzPreview");
  preview.src = "";
  preview.hidden = true;
  $("#dzEmpty").hidden = false;
  $("#dzClear").hidden = true;
  $("#fileInput").value = "";
}

/* ───────────────────────────── submit ───────────────────────────── */

async function submit(event) {
  event?.preventDefault();
  const prompt = $("#prompt").value.trim();
  const aspect = $("#aspect").value;
  const style = $("#style").value;
  const provider = $("#provider").value;

  if (state.mode === "video_from_image" && !state.file) {
    toast("Choose an image to animate first", true);
    return;
  }
  if (state.mode !== "video_from_image" && !prompt) {
    toast("Write a prompt first", true);
    $("#prompt").focus();
    return;
  }

  const button = $("#submitBtn");
  button.disabled = true;
  const spinner = $(".spinner", button);
  spinner.hidden = false;

  try {
    let job;
    if (state.mode === "image") {
      job = await api("/api/images", {
        method: "POST",
        body: JSON.stringify({
          prompt,
          aspect,
          style,
          provider,
          count: Number($("#count").value),
        }),
      });
    } else if (state.mode === "video_from_text") {
      job = await api("/api/videos/from-text", {
        method: "POST",
        body: JSON.stringify({
          prompt,
          aspect,
          style,
          provider,
          motion: $("#motion").value,
          duration_seconds: Number($("#duration").value),
          engine: selectedEngine(),
          count: Number($("#count").value),
        }),
      });
    } else {
      const form = new FormData();
      form.append("file", state.file);
      form.append("prompt", prompt);
      form.append("aspect", aspect);
      form.append("style", style);
      form.append("provider", provider);
      form.append("motion", $("#motion").value);
      form.append("duration_seconds", String(Number($("#duration").value)));
      form.append("engine", selectedEngine());
      job = await api("/api/videos/from-image", { method: "POST", body: form });
    }

    state.activeIds.add(job.id);
    upsertJob(job);
    renderActiveRun();
    schedulePoll();
    if (state.mode === "video_from_image") clearFile();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    spinner.hidden = true;
  }
}

/* ───────────────────────────── jobs / polling ───────────────────────────── */

async function refreshJobs() {
  try {
    const payload = await api("/api/jobs");
    state.jobs = payload.jobs;
    for (const job of state.jobs) {
      if (job.status === "queued" || job.status === "running") state.activeIds.add(job.id);
    }
    if (state.activeIds.size && !state.pollTimer) schedulePoll();
    renderStats(payload.stats);
    renderGallery();
    renderActiveRun();
  } catch (error) {
    /* keep the last known list */
  }
}

function upsertJob(job) {
  const index = state.jobs.findIndex((j) => j.id === job.id);
  if (index === -1) state.jobs.unshift(job);
  else state.jobs[index] = job;
  renderGallery();
  renderStats();
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(pollActive, 700);
}

async function pollActive() {
  if (!state.activeIds.size) return;
  const finished = [];
  for (const id of Array.from(state.activeIds)) {
    try {
      const job = await api(`/api/jobs/${id}`);
      upsertJob(job);
      if (job.status === "done" || job.status === "failed") {
        finished.push(job);
        state.activeIds.delete(id);
      }
    } catch (_) { /* transient */ }
  }
  renderActiveRun();
  await refreshJobs();
  if (finished.length) {
    const last = finished[finished.length - 1];
    if (last.status === "done") {
      toast(last.video ? "Video ready" : "Image ready");
      openDetail(last.id);
    } else {
      toast(`Run failed: ${last.error || "unknown error"}`, true);
    }
  }
  if (state.activeIds.size) schedulePoll();
}

function renderStats(stats) {
  const data = stats || {
    total: state.jobs.length,
    images: state.jobs.reduce((n, j) => n + (j.assets?.length || 0), 0),
    videos: state.jobs.filter((j) => j.video).length,
    running: state.jobs.filter((j) => ["queued", "running"].includes(j.status)).length,
  };
  $("#stats").innerHTML = [
    `runs <b>${data.total ?? 0}</b>`,
    `images <b>${data.images ?? 0}</b>`,
    `videos <b>${data.videos ?? 0}</b>`,
    data.running ? `<b>${data.running}</b> in flight` : null,
  ].filter(Boolean).join(" · ");
}

/* ───────────────────────────── rendering ───────────────────────────── */

function jobKindLabel(kind) {
  return { image: "image", video_from_text: "text → video", video_from_image: "image → video" }[kind] || kind;
}

function statusBadge(job) {
  if (job.status === "failed") return `<span class="badge fail">failed</span>`;
  if (job.status === "queued") return `<span class="badge run">queued</span>`;
  if (job.status === "running") return `<span class="badge run">rendering</span>`;
  if (job.placeholder) return `<span class="badge warn">placeholder</span>`;
  return `<span class="badge ok">done</span>`;
}

function previewUrl(job) {
  if (job.video?.poster_url) return job.video.poster_url;
  if (job.assets?.[0]?.url) return job.assets[0].url;
  if (job.video?.url) return job.video.url;
  return null;
}

function cardMarkup(job) {
  const preview = previewUrl(job);
  const isVideo = !!job.video;
  const meta = [];
  if (job.video) {
    meta.push(`${job.video.width || "?"}×${job.video.height || "?"}`);
    meta.push(fmtDuration(job.video.duration_seconds));
  } else if (job.assets?.[0]) {
    const a = job.assets[0];
    meta.push(`${a.width || "?"}×${a.height || "?"}`);
    meta.push(a.provider || "local");
  }
  meta.push(job.aspect || "");
  meta.push(job.engine === "video_model" ? "model" : "motion");

  return `
    <article class="card" data-job="${job.id}" tabindex="0" role="button" aria-label="Open run: ${esc(job.prompt).slice(0, 80)}">
      <div class="card-media" ${preview ? `style="background-image:url('${preview}')"` : ""}>
        ${preview ? `<img src="${preview}" alt="" loading="lazy" />` : `<span class="ph">no preview</span>`}
        <div class="card-badges">
          ${statusBadge(job)}
          <span class="badge">${isVideo ? "video" : "image"}</span>
        </div>
        ${job.status === "running" || job.status === "queued" ? `<div class="progress indeterminate" style="position:absolute;left:0;right:0;bottom:0;border-radius:0"><i></i></div>` : ""}
      </div>
      <div class="card-body">
        <div class="card-prompt">${esc(job.prompt || jobKindLabel(job.kind))}</div>
        <div class="card-meta">
          <span>${jobKindLabel(job.kind)}</span>
          ${meta.filter(Boolean).map((m) => `<span class="sep">·</span><span>${esc(m)}</span>`).join("")}
        </div>
      </div>
    </article>`;
}

function renderGallery() {
  const gallery = $("#gallery");
  const filtered = state.jobs.filter((job) => {
    if (state.filter === "image") return job.kind === "image" || (!job.video && job.assets?.length);
    if (state.filter === "video") return !!job.video;
    return true;
  });

  $("#emptyState").hidden = filtered.length > 0;
  gallery.innerHTML = filtered.map(cardMarkup).join("");
  $$(".card", gallery).forEach((card) => {
    const open = () => openDetail(card.dataset.job);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
}

function renderActiveRun() {
  const active = state.jobs.filter((job) => state.activeIds.has(job.id));
  const host = $("#activeRun");
  if (!active.length) { host.hidden = true; host.innerHTML = ""; return; }

  host.hidden = false;
  host.innerHTML = active.map((job) => `
    <div class="active-card">
      <div class="active-top">
        <span class="kind">${jobKindLabel(job.kind)}</span>
        <p class="active-prompt">${esc(job.prompt || "Animating your image")}</p>
      </div>
      <div class="steps">
        ${(job.steps || []).map((step) => `
          <div class="step ${step.status}">
            <span class="mark">${step.status === "done" ? "✓" : step.status === "failed" ? "!" : step.status === "running" ? "•" : "○"}</span>
            <span>${esc(step.name)}</span>
            <span class="detail">${esc(step.detail || "")}</span>
          </div>`).join("")}
      </div>
      ${job.log?.length ? `<div class="log">${job.log.slice(-6).map((line) => `<div>${esc(line)}</div>`).join("")}</div>` : ""}
    </div>`).join("");
}

/* ───────────────────────────── detail modal ───────────────────────────── */

async function openDetail(jobId) {
  let job = state.jobs.find((j) => j.id === jobId);
  try { job = await api(`/api/jobs/${jobId}`); } catch (_) { /* use cached */ }
  if (!job) return;

  $("#detailTitle").textContent = job.prompt || jobKindLabel(job.kind);
  $("#detailSub").textContent =
    `${jobKindLabel(job.kind)} · ${new Date(job.created_at).toLocaleString()} · ${job.status}`;

  const stats = [
    ["Aspect", job.aspect],
    ["Style", job.style],
    ["Motion", job.motion],
    ["Duration", job.video ? `${job.video.duration_seconds}s` : `${job.duration_seconds}s`],
    ["Engine", job.engine === "video_model" ? "AI video model" : "Local camera motion"],
    ["Cost", `$${(job.cost_usd || 0).toFixed(3)}`],
  ];

  const announcement = job.provider_announcement || {};
  const providerText = announcement.selected
    || (announcement.available?.length ? announcement.available.join(", ") : "none configured");

  const media = [];
  if (job.video?.url) media.push(`<video src="${job.video.url}" controls playsinline poster="${job.video.poster_url || ""}"></video>`);
  for (const asset of job.assets || []) {
    if (job.video?.url && asset.provenance === "upload") continue;
    media.push(`<img src="${asset.url}" alt="${esc(job.prompt).slice(0, 60)}" data-full="${asset.url}" />`);
  }

  const actions = [];
  if (job.video?.url) actions.push(`<a href="${job.video.url}" download>Download MP4</a>`);
  for (const asset of job.assets || []) {
    actions.push(`<a href="${asset.url}" download="${asset.filename}">${esc(asset.filename)}</a>`);
  }
  if (job.project_id) {
    const boardHref = `${state.boardOrigin || portHost(4750)}/p/${job.project_id}`;
    actions.push(`<a href="${boardHref}" target="_blank" rel="noreferrer">Open in Backlot board ↗</a>`);
  }

  $("#detailBody").innerHTML = `
    <div class="detail-grid">
      ${stats.map(([label, value]) => `<div class="detail-stat"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join("")}
      <div class="detail-stat"><span>Provider</span><b>${esc(providerText)}</b></div>
      <div class="detail-stat"><span>Project</span><b>${esc(job.project_id || "—")}</b></div>
    </div>
    ${media.length ? `<div class="detail-media">${media.join("")}</div>` : ""}
    ${actions.length ? `<div class="detail-actions">${actions.join("")}</div>` : ""}
    ${job.log?.length ? `<div class="log">${job.log.map((line) => `<div>${esc(line)}</div>`).join("")}</div>` : ""}
    ${job.error ? `<div class="key-note" style="border-color:rgba(239,68,68,.4);color:#ffc9c9"><b>Error:</b> ${esc(job.error)}</div>` : ""}
  `;

  $$("#detailBody img[data-full]").forEach((img) => {
    img.addEventListener("click", () => openLightbox(img.dataset.full));
  });

  $("#detailDialog").showModal();
}

function openLightbox(src) {
  $("#lightboxImg").src = src;
  $("#lightbox").hidden = false;
}

/* ───────────────────────────── keys modal ───────────────────────────── */

async function openKeys() {
  try {
    const payload = await api("/api/keys");
    state.keys = payload.keys;
  } catch (error) {
    toast(`Could not load keys: ${error.message}`, true);
    return;
  }

  const configured = state.keys.filter((k) => k.configured).length;
  $("#keysStatus").textContent = `${configured} of ${state.keys.length} keys set`;
  $("#keyNote").innerHTML = configured
    ? `Keys are stored in <code>.env</code> (never sent anywhere by the Studio). Restart-free: they apply to the next run.`
    : `Nothing is configured yet. Pick <b>one</b> key to start — <code>FAL_KEY</code> alone unlocks a large share of the image and video providers.`;

  $("#keysList").innerHTML = state.keys.map((key) => `
    <div class="key-row ${key.configured ? "configured" : ""}">
      <div>
        <div class="key-name">${esc(key.name)}</div>
        <div class="key-unlocks">${key.unlocks?.length ? `unlocks ${esc(key.unlocks.slice(0, 4).join(", "))}${key.unlocks.length > 4 ? " +" + (key.unlocks.length - 4) : ""}` : "provider credential"}</div>
      </div>
      <input class="key-input" type="password" data-key="${esc(key.name)}"
             placeholder="${key.configured ? "•••••••• set" : "paste key"}"
             autocomplete="off" spellcheck="false" />
    </div>`).join("");

  $("#keysDialog").showModal();
}

async function saveKeys(event) {
  event.preventDefault();
  const payload = {};
  $$(".key-input").forEach((input) => {
    const value = input.value.trim();
    if (value) payload[input.dataset.key] = value;
  });
  if (!Object.keys(payload).length) { toast("No new keys entered"); return; }

  try {
    const result = await api("/api/keys", { method: "POST", body: JSON.stringify({ keys: payload }) });
    $("#keysDialog").close();
    toast(`Saved ${result.saved.length} key(s) — capabilities refreshed`);
    const catalog = await api("/api/catalog");
    state.catalog = catalog;
    renderCapabilities();
    renderProviderLine();
    renderNotice();
    syncProviderOptions();
  } catch (error) {
    toast(error.message, true);
  }
}

/* ───────────────────────────── board ───────────────────────────── */

async function refreshBoardStatus() {
  try {
    const status = await api("/api/board/status");
    $("#boardDot").classList.toggle("on", status.alive);
    try {
      const payload = await api("/api/board/url");
      state.boardOrigin = (payload.url || "").replace(/\/$/, "");
    } catch (_) { /* keep default */ }
    $("#boardBtn").title = status.alive
      ? "Open the Backlot live storyboard"
      : "Start the Backlot live storyboard";
  } catch (_) { /* ignore */ }
}

async function openBoard() {
  const button = $("#boardBtn");
  button.disabled = true;
  try {
    await api("/api/board/open", { method: "POST" });
    $("#boardDot").classList.add("on");
    let origin = portHost(4750);
    try {
      const payload = await api("/api/board/url");
      if (payload.url) origin = payload.url.replace(/\/$/, "");
    } catch (_) { /* fall back to the port-mapped origin */ }
    const latest = state.jobs.find((j) => j.project_id);
    const target = latest ? `${origin}/p/${latest.project_id}` : `${origin}/`;
    window.open(target, "_blank", "noreferrer");
    toast("Backlot board opened");
  } catch (error) {
    toast(`Board: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

/* ───────────────────────────── events ───────────────────────────── */

function bindEvents() {
  $$(".seg").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));
  $("#composerForm").addEventListener("submit", submit);
  $("#dzClear").addEventListener("click", (event) => { event.preventDefault(); clearFile(); });

  $("#promptSamples").addEventListener("click", (event) => {
    const chipEl = event.target.closest("[data-sample]");
    if (!chipEl) return;
    $("#prompt").value = chipEl.dataset.sample;
    $("#prompt").focus();
  });

  $("#fileInput").addEventListener("change", (event) => setFile(event.target.files?.[0]));

  const dropzone = $("#dropzone");
  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove("drag");
  }));
  dropzone.addEventListener("drop", (event) => setFile(event.dataTransfer?.files?.[0]));
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("#fileInput").click(); }
  });

  $("#duration").addEventListener("input", syncDurationOut);
  $$('input[name="engine"]').forEach((radio) => radio.addEventListener("change", () => {
    renderProviderLine();
    renderFineprint();
    syncProviderOptions();
  }));

  $$(".filters .chip").forEach((chipEl) => chipEl.addEventListener("click", () => {
    state.filter = chipEl.dataset.filter;
    $$(".filters .chip").forEach((c) => c.classList.toggle("active", c === chipEl));
    renderGallery();
  }));

  $("#keysBtn").addEventListener("click", openKeys);
  $("#keysForm").addEventListener("submit", saveKeys);
  $$("[data-close-keys]").forEach((button) => button.addEventListener("click", () => $("#keysDialog").close()));
  $("#noticeAction").addEventListener("click", openKeys);
  $("#noticeClose").addEventListener("click", () => { $("#notice").hidden = true; });
  $("#boardBtn").addEventListener("click", openBoard);

  $("#detailClose").addEventListener("click", () => $("#detailDialog").close());
  $("#lightboxClose").addEventListener("click", () => { $("#lightbox").hidden = true; });
  $("#lightbox").addEventListener("click", (event) => {
    if (event.target.id === "lightbox") $("#lightbox").hidden = true;
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(event);
    if (event.key === "Escape") {
      $("#lightbox").hidden = true;
      if ($("#detailDialog").open) $("#detailDialog").close();
    }
  });

  $("#prompt").addEventListener("input", renderFineprint);
}

function syncDurationOut() {
  const input = $("#duration");
  const value = Number(input.value);
  $("#durationOut").textContent = `${value}s`;
  const pct = ((value - input.min) / (input.max - input.min)) * 100;
  input.style.setProperty("--fill", `${pct}%`);
}

document.addEventListener("DOMContentLoaded", () => { setMode("image"); init(); });
