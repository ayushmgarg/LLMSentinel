/* LLMSentinel Studio front-end.
   Every string that comes from a document, a model or the server is rendered with
   textContent / text nodes, never innerHTML: the context being inspected is hostile
   by assumption, and the server's CSP forbids inline script anyway. */

"use strict";

const $ = (selector, root = document) => root.querySelector(selector);

const state = {
  presets: {},
  profiles: { default: {}, models: {} },
  defaultMaxTokens: 400,
  questions: [],
  samples: [],
  manifests: [],
  revealed: false,
  selected: new Set(),
  selectedManifests: new Set(),
  uploads: [],
  maxUploads: 12,
  providerEdits: {},
  running: false,
};

const ALLOWED = [".txt", ".md", ".markdown", ".json", ".html", ".htm", ".csv"];
const MAX_BYTES = 2_000_000;
const KIND_ICON = { markdown: "i-file", text: "i-file", json: "i-braces", html: "i-code", csv: "i-table" };
const DANGEROUS = new Set(["external_send", "destructive", "privilege_escalation"]);
const OUTCOME_TONE = { allow: "success", isolate: "warning", confirm: "warning", block: "danger" };
const INDICATOR_TEXT = {
  system_prompt_leak: "Confidential code leaked",
  attacker_destination: "Attacker destination",
  dangerous_action: "Dangerous tool would run",
  planted_claim: "Planted claim repeated",
};

/* ------------------------------------------------------------------ helpers */
function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  for (const [key, value] of Object.entries(options.attrs || {})) {
    if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  svg.append(use);
  return svg;
}

function tag(text, tone = "neutral", iconName = null, extra = "") {
  return el("span", { className: `tag tag--${tone} ${extra}`.trim() }, [iconName ? icon(iconName) : null, text]);
}

function pct(value) {
  return value === null || value === undefined ? "n/a" : Number(value).toFixed(3);
}

function formatMs(ms) {
  if (ms === null || ms === undefined) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

async function api(path, body) {
  const options = body === undefined
    ? { headers: { Accept: "application/json" } }
    : { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw Object.assign(new Error("The Studio server is not reachable."), { hint: "Is `python -m studio.server` still running?" });
  }
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) {
    throw Object.assign(new Error(data.error || `Request failed (HTTP ${response.status}).`), { hint: data.hint || "" });
  }
  return data;
}

function toast(title, message = "", tone = "neutral") {
  const region = $("#toast-region");
  const node = el("div", { className: `toast toast--${tone}`, attrs: { role: tone === "danger" ? "alert" : "status" } }, [
    el("strong", { text: title }),
    message ? el("span", { text: message }) : null,
  ]);
  region.append(node);
  setTimeout(() => {
    node.classList.add("toast--out");
    setTimeout(() => node.remove(), 300);
  }, tone === "danger" ? 7000 : 4000);
}

/* ------------------------------------------------------------------- theme */
const THEME_KEY = "llmsentinel-studio-theme";

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch (error) {
    return null; // private window or blocked storage
  }
}

function systemTheme() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const button = $("#theme-toggle");
  if (!button) return;
  const dark = theme === "dark";
  button.replaceChildren(icon(dark ? "i-sun" : "i-moon"));
  button.setAttribute("aria-label", dark ? "Switch to the light theme" : "Switch to the dark theme");
  button.setAttribute("title", button.getAttribute("aria-label"));
}

function initTheme() {
  applyTheme(storedTheme() || systemTheme());
  $("#theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (error) {
      /* not stored; the choice still applies to this tab */
    }
    applyTheme(next);
  });
}

/* ---------------------------------------------------------------- detector */
let healthTimer = null;

function renderDetector(detector) {
  const box = $("#detector-status");
  box.replaceChildren();
  box.classList.remove("detector--ok", "detector--warn", "detector--error");
  clearTimeout(healthTimer);
  if (!detector || detector.error) {
    box.classList.add("detector--error");
    box.append(icon("i-alert"), el("span", { text: detector && detector.error ? detector.error : "Detector unavailable" }));
    return;
  }
  if (detector.loading) {
    box.append(el("span", { className: "spinner", attrs: { "aria-hidden": "true" } }), el("span", { text: "Loading detector…" }));
    box.setAttribute("title", (detector.notes || []).join("\n"));
    healthTimer = setTimeout(refreshDetector, 2000);
    return;
  }
  const loaded = Boolean(detector.transformer_loaded);
  box.classList.add(loaded ? "detector--ok" : "detector--warn");
  box.append(
    icon(loaded ? "i-shield-check" : "i-shield"),
    el("span", {}, [el("strong", { text: `Detector: ${detector.detector}${loaded ? "" : " (fallback)"}` })]),
  );
  const notes = [detector.decision_rule, ...(detector.notes || [])].filter(Boolean);
  box.setAttribute("title", notes.join("\n"));
}

async function refreshDetector() {
  try {
    const health = await api("/api/health");
    renderDetector(health.detector);
  } catch (error) {
    renderDetector(null);
  }
}

/* The flag rule, with the calibrated dev thresholds it uses, so a high raw score
   that stays under its threshold is explained rather than looking like a bug. */
function thresholdText(detector) {
  const fixed = (value) => (value === undefined ? "n/a" : Number(value).toFixed(4));
  const rules = detector.rule_thresholds || {};
  if (detector.transformer_loaded) {
    const model = detector.model_thresholds || {};
    return `transformer ≥ ${fixed(model["fpr=0.01"])} or rules ≥ ${fixed(rules["fpr=0.001"])}`;
  }
  return `rules ≥ ${fixed(rules["fpr=0.01"])}`;
}

/* Headline numbers come from the evaluation outputs, not from the markup. */
function applyEvidence(evidence) {
  if (!evidence) return;
  const set = (selector, value) => {
    const node = $(selector);
    if (node && value !== undefined && value !== null) node.textContent = Number(value).toFixed(3);
  };
  set("#stat-test-auprc", evidence.test_auprc);
  set("#stat-test-recall", evidence.test_tpr_at_1pct_fpr);
  const recallLabel = $("#stat-test-recall-label");
  if (recallLabel && evidence.test_realised_fpr_at_1pct !== undefined && evidence.test_realised_fpr_at_1pct !== null) {
    const realised = Number(evidence.test_realised_fpr_at_1pct);
    const over = realised > 0.01 ? ", over budget" : "";
    recallLabel.textContent = `test recall at the dev 1%-FPR threshold (realised test FPR ${(realised * 100).toFixed(1)}%${over})`;
  }
  // The seed mean is stored as 0.9515; rounding it to three places would print a
  // different number from the one the docs quote, so show the stored precision.
  const exact = (value) => Number(value).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const dev = $("#stat-dev-auprc");
  if (dev && evidence.dev_auprc_mean !== undefined && evidence.dev_auprc_mean !== null) {
    dev.replaceChildren(document.createTextNode(exact(evidence.dev_auprc_mean)));
    if (evidence.dev_auprc_std !== undefined && evidence.dev_auprc_std !== null) {
      dev.append(el("small", { text: ` ± ${exact(evidence.dev_auprc_std)}` }));
    }
  }
}

/* ---------------------------------------------------------------- provider */
const HELP = {
  simulated: {
    title: "Offline simulator",
    steps: [
      ["No download needed. The simulator is not a language model: it obeys any instruction it finds in its context, so you can see the whole pipeline work without a model.", null],
      ["For real behaviour, connect a local model with Ollama or LM Studio.", null],
    ],
  },
  ollama: {
    title: "Free local model with Ollama",
    steps: [
      ["Install Ollama from ollama.com (Windows, macOS, Linux).", null],
      ["Download a small model (about 1 GB, runs on a CPU):", "ollama pull qwen2.5:1.5b"],
      ["Keep the Ollama app running, then press Test connection. Larger: llama3.2:3b (about 2 GB).", null],
    ],
  },
  lmstudio: {
    title: "Free local model with LM Studio",
    steps: [
      ["Install LM Studio from lmstudio.ai and download a small instruct model (for example Qwen2.5 1.5B Instruct).", null],
      ["Open the Developer tab, load the model and start the server (default port 1234).", null],
      ["Press Test connection and pick the model from the list.", null],
    ],
  },
  custom: {
    title: "Any OpenAI-compatible API",
    steps: [
      ["Enter a base URL ending in /v1 (llama.cpp server, vLLM, or a hosted API).", "http://localhost:8080/v1"],
      ["Hosted free tiers have rate and token limits; a local model has none. The key stays in this tab and is sent only to the Studio server for this request.", null],
    ],
  },
};

function currentProvider() {
  return $('input[name="provider"]:checked').value;
}

function providerConfig() {
  const kind = currentProvider();
  return {
    kind,
    base_url: $("#base-url").value.trim(),
    model: $("#model").value.trim(),
    api_key: kind === "custom" ? $("#api-key").value : "",
  };
}

function applyProvider(kind) {
  const preset = state.presets[kind] || {};
  const edits = state.providerEdits[kind] || {};
  const baseUrl = $("#base-url");
  const model = $("#model");
  baseUrl.value = edits.base_url ?? preset.base_url ?? "";
  model.value = edits.model ?? preset.model ?? "";
  const simulated = kind === "simulated";
  baseUrl.disabled = simulated;
  model.disabled = simulated;
  baseUrl.placeholder = simulated ? "not needed" : kind === "lmstudio" ? "http://localhost:1234/v1" : "http://localhost:11434/v1";
  model.placeholder = simulated ? "not needed" : kind === "ollama" ? "qwen2.5:1.5b" : "model name";
  $("#api-key-field").hidden = kind !== "custom";
  $("#model-list").replaceChildren();
  setConnection("", "");
  renderHelp(kind);
  applyProfile();
}

/* Same lookup as the server: exact name, then without ":latest", else the default. */
function profileFor(model) {
  const models = state.profiles.models || {};
  const name = model.trim();
  for (const candidate of [name, name.replace(/:latest$/, "")]) {
    if (models[candidate]) return { ...state.profiles.default, ...models[candidate], matched: candidate };
  }
  return { ...state.profiles.default, matched: null };
}

function applyProfile() {
  const note = $("#model-profile");
  const maxTokens = $("#max-tokens");
  if (currentProvider() === "simulated") {
    maxTokens.disabled = true;
    note.textContent = "";
    return;
  }
  maxTokens.disabled = false;
  const model = $("#model").value;
  const profile = profileFor(model);
  maxTokens.value = String(profile.max_tokens || state.defaultMaxTokens);
  if (profile.top_k) $("#top-k").value = String(profile.top_k);
  if (!model.trim()) note.textContent = "";
  else if (profile.matched) note.textContent = `Profile ${profile.matched}: ${profile.note || "saved settings applied."}`;
  else note.textContent = "No saved profile for this model: defaults applied. Add one in studio/model_profiles.yaml.";
}

function rememberEdit() {
  const kind = currentProvider();
  if (kind === "simulated") return;
  state.providerEdits[kind] = { base_url: $("#base-url").value, model: $("#model").value };
}

function renderHelp(kind) {
  const help = HELP[kind];
  const box = $("#provider-help");
  box.replaceChildren(
    el("p", { className: "help__title" }, [icon("i-info"), help.title]),
    el("ol", { className: "help__steps" }, help.steps.map(([text, command]) =>
      el("li", {}, [el("span", { text }), command ? el("code", { text: command }) : null]),
    )),
  );
}

function setConnection(text, tone) {
  const status = $("#connection-status");
  status.className = `status${tone ? ` status--${tone}` : ""}`;
  status.textContent = text;
}

async function testConnection() {
  const button = $("#test-connection");
  button.disabled = true;
  setConnection("Connecting…", "pending");
  try {
    const result = await api("/api/models", providerConfig());
    if (!result.ok) {
      setConnection(result.error || "Connection failed.", "error");
      if (result.hint) toast("Connection failed", result.hint, "danger");
      return;
    }
    const models = result.models || [];
    $("#model-list").replaceChildren(...models.map((name) => el("option", { attrs: { value: name } })));
    const model = $("#model");
    if (!result.simulated && models.length && !models.includes(model.value.trim())) {
      model.value = models[0];
      rememberEdit();
    }
    applyProfile();
    setConnection(result.simulated ? "Simulator ready" : `Connected · ${plural(models.length, "model")}`, "ok");
    if (!result.simulated && !models.length) {
      toast("Connected, but no models found", "Download one first, e.g. `ollama pull qwen2.5:1.5b`.", "danger");
    }
  } catch (error) {
    setConnection(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

/* ----------------------------------------------------------------- context */
async function loadSamples() {
  const data = await api(`/api/samples${state.revealed ? "?reveal=1" : ""}`);
  state.samples = data.items || [];
  state.manifests = data.manifests || [];
  renderSamples();
  renderManifests();
}

function sampleTag(item) {
  if (!state.revealed) return tag("unknown", "neutral", null, "tag--unknown");
  if (item.label === "poisoned") return tag(item.attack && item.attack !== "none" ? item.attack.replace(/_/g, " ") : "poisoned", "danger", "i-alert");
  return tag("clean", "success", "i-check");
}

function selectableCard({ id, set, iconName, name, meta, preview, tagNode }) {
  const descId = `desc-${id}`;
  const checkbox = el("input", {
    className: "visually-hidden",
    attrs: { type: "checkbox", value: id, checked: set.has(id), "aria-describedby": descId },
  });
  const card = el("label", { className: `doc-card${set.has(id) ? " is-selected" : ""}` }, [
    checkbox,
    el("span", { className: "doc-card__check" }, [icon("i-check")]),
    el("span", { className: "doc-card__icon" }, [icon(iconName)]),
    el("span", { className: "doc-card__body" }, [
      el("span", { className: "doc-card__name", text: name }),
      el("span", { className: "doc-card__meta", text: meta }),
      el("span", { className: "doc-card__preview", text: preview, attrs: { id: descId, title: preview } }),
    ]),
    tagNode,
  ]);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) set.add(id);
    else set.delete(id);
    card.classList.toggle("is-selected", checkbox.checked);
    updateCount();
  });
  return card;
}

function renderSamples() {
  $("#sample-grid").replaceChildren(...state.samples.map((item) => selectableCard({
    id: item.doc_id,
    set: state.selected,
    iconName: KIND_ICON[item.kind] || "i-file",
    name: item.name,
    meta: `${item.kind} · ${item.chars.toLocaleString()} chars`,
    preview: state.revealed && item.note ? item.note : item.preview,
    tagNode: sampleTag(item),
  })));
  updateCount();
}

function manifestTag(item) {
  if (!state.revealed) return tag("unknown", "neutral", null, "tag--unknown");
  if (item.label === "poisoned") return tag("poisoned metadata", "danger", "i-alert");
  if (item.label === "drifted") return tag("changed after approval", "warning", "i-alert");
  return tag("clean", "success", "i-check");
}

function renderManifests() {
  $("#manifest-grid").replaceChildren(...state.manifests.map((item) => selectableCard({
    id: item.manifest_id,
    set: state.selectedManifests,
    iconName: "i-layers",
    name: item.name,
    meta: `${item.server} · ${plural(item.tools.length, "tool")} · ${item.pinned ? "approved snapshot pinned" : "not pinned"}`,
    preview: state.revealed && item.note ? item.note : item.tools.join(", "),
    tagNode: manifestTag(item),
  })));
  updateCount();
}

function updateCount() {
  const files = state.selected.size + state.uploads.length;
  $("#context-count").textContent = `${plural(files, "file")} · ${plural(state.selectedManifests.size, "tool server")}`;
}

function extensionOf(name) {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

async function addFiles(fileList) {
  for (const file of Array.from(fileList)) {
    if (state.uploads.length >= state.maxUploads) {
      toast("Upload limit reached", `At most ${state.maxUploads} files per comparison.`, "danger");
      break;
    }
    if (!ALLOWED.includes(extensionOf(file.name))) {
      toast(`${file.name} skipped`, `Allowed types: ${ALLOWED.join(", ")}.`, "danger");
      continue;
    }
    if (file.size > MAX_BYTES) {
      toast(`${file.name} skipped`, "Files are limited to 2 MB.", "danger");
      continue;
    }
    const content = await file.text();
    if (!content.trim()) {
      toast(`${file.name} skipped`, "The file is empty.", "danger");
      continue;
    }
    state.uploads = state.uploads.filter((u) => u.name !== file.name);
    state.uploads.push({ name: file.name, content });
  }
  renderUploads();
}

function renderUploads() {
  $("#upload-list").replaceChildren(...state.uploads.map((upload) => {
    const remove = el("button", { className: "chip__remove", attrs: { type: "button", "aria-label": `Remove ${upload.name}` } }, [icon("i-x")]);
    remove.addEventListener("click", () => {
      state.uploads = state.uploads.filter((u) => u !== upload);
      renderUploads();
    });
    return el("li", { className: "chip" }, [icon(KIND_ICON[extensionOf(upload.name).slice(1)] || "i-file"), el("span", { text: upload.name }), remove]);
  }));
  updateCount();
}

function wireDropzone() {
  const zone = $("#dropzone");
  const input = $("#file-input");
  ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (event) => {
    event.preventDefault();
    zone.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((type) => zone.addEventListener(type, (event) => {
    event.preventDefault();
    zone.classList.remove("is-over");
  }));
  zone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
  input.addEventListener("change", () => {
    addFiles(input.files);
    input.value = "";
  });
}

/* ---------------------------------------------------------------- question */
function renderPresets() {
  $("#preset-list").replaceChildren(...state.questions.map((question) => {
    const button = el("button", { className: "preset", text: question, attrs: { type: "button" } });
    button.addEventListener("click", () => {
      $("#question").value = question;
      $("#question").focus();
    });
    return button;
  }));
}

/* ------------------------------------------------------------------ results */
function setRunning(running) {
  state.running = running;
  const button = $("#run");
  button.disabled = running;
  button.classList.toggle("is-loading", running);
  button.setAttribute("aria-busy", running ? "true" : "false");
  $("#run-label").textContent = running ? "Running both models…" : "Run comparison";
}

function showSkeleton() {
  $("#results-empty").hidden = true;
  $("#results-body").replaceChildren(
    el("div", { className: "skeleton skeleton--banner" }),
    el("div", { className: "compare" }, [el("div", { className: "skeleton skeleton--panel" }), el("div", { className: "skeleton skeleton--panel" })]),
    el("div", { className: "skeleton skeleton--panel" }),
  );
}

const TONE_ICON = { success: "i-shield-check", danger: "i-alert", warning: "i-shield", neutral: "i-info" };

function renderBanner(result) {
  const summary = result.summary;
  const bits = [
    `${plural(summary.retrieved, "passage")} retrieved`,
    `${summary.flagged} flagged`,
    `${summary.stripped} stripped`,
    `${summary.withheld} withheld`,
    summary.tools ? `${summary.quarantined} of ${plural(summary.tools, "tool")} quarantined` : null,
    `Sentinel ${formatMs(result.sentinel.latency_ms)}`,
    result.detector.detector,
  ].filter(Boolean);
  return el("div", { className: `banner banner--${summary.tone}`, attrs: { role: "status" } }, [
    icon(TONE_ICON[summary.tone] || "i-info", "icon icon--lg"),
    el("div", {}, [
      el("p", { className: "banner__headline", text: summary.headline }),
      el("p", { className: "banner__meta", text: bits.join(" · ") }),
    ]),
  ]);
}

function highlighted(text, spans) {
  const container = el("div", { className: "passage" });
  let cursor = 0;
  for (const span of [...(spans || [])].sort((a, b) => a.start - b.start)) {
    const start = Math.max(cursor, span.start);
    const end = Math.min(text.length, span.end);
    if (end <= start) continue;
    container.append(document.createTextNode(text.slice(cursor, start)));
    container.append(el("mark", { className: "flag", text: text.slice(start, end) }));
    cursor = end;
  }
  container.append(document.createTextNode(text.slice(cursor)));
  return container;
}

function kv(key, value) {
  return el("div", { className: "kv" }, [el("span", { className: "kv__k", text: key }), el("span", { text: value })]);
}

function meter(value, band) {
  const bar = el("span", { className: `meter meter--${band || "low"}`, attrs: { "aria-hidden": "true" } }, [el("span", { className: "meter__fill" })]);
  bar.firstChild.style.setProperty("--value", String(Math.max(0, Math.min(1, Number(value) || 0))));
  return bar;
}

const DECISION_TEXT = { keep: "passed", strip: "stripped", withhold: "withheld" };

function renderChunk(chunk, labels, detector) {
  const panelId = `chunk-${chunk.rank}`;
  const head = el("button", { className: "chunk__head", attrs: { type: "button", "aria-expanded": "false", "aria-controls": panelId } }, [
    el("span", { className: "chunk__rank", text: `#${chunk.rank}` }),
    el("span", { className: "chunk__source" }, [
      el("span", { className: "chunk__name", text: chunk.source }),
      el("span", { className: "chunk__path", text: chunk.json_path || chunk.channel.replace(/_/g, " ") }),
    ]),
    labels[chunk.doc_id] ? labels[chunk.doc_id] : el("span", { className: "tag--xs", attrs: { "aria-hidden": "true" } }),
    el("span", { className: "chunk__risk" }, [meter(chunk.risk, chunk.band), el("span", { className: "mono", text: pct(chunk.risk) })]),
    tag(chunk.band, `band-${chunk.band}`, null, "tag--xs"),
    tag(DECISION_TEXT[chunk.action] || chunk.action, `action-${chunk.action}`, chunk.action === "keep" ? "i-check" : "i-shield"),
    el("span", { className: "chunk__chev" }, [icon("i-chevron")]),
  ]);

  const side = el("div", { className: "chunk__side" }, [
    kv("Decision", `${DECISION_TEXT[chunk.action] || chunk.action} (${chunk.decided_by})`),
    kv("Risk used", pct(chunk.risk)),
    kv("Flags at", thresholdText(detector)),
    kv("Transformer", chunk.model_risk === null ? "not loaded" : `${pct(chunk.model_risk)} · ${chunk.model_band}`),
    kv("Rules", `${pct(chunk.rule_risk)} · ${chunk.rule_band}`),
    kv("Retrieval score", pct(chunk.retrieval_score)),
    kv("Channel", chunk.channel.replace(/_/g, " ")),
  ]);
  if (chunk.evidence && chunk.evidence.length) {
    side.append(el("div", {}, [el("p", { className: "label", text: "Normalisation evidence" }), el("div", { className: "tags" }, chunk.evidence.map((e) => tag(e.replace(/_/g, " "), "warning", null, "tag--xs")))]));
  }

  const main = el("div", { className: "chunk__main" }, [
    el("p", {
      className: "label",
      text: chunk.cuts && chunk.cuts.length
        ? "Retrieved passage (removed segments marked)"
        : chunk.flagged ? "Retrieved passage (rule spans marked)" : "Retrieved passage (rule hits below the flag threshold marked)",
    }),
    highlighted(chunk.text, chunk.cuts && chunk.cuts.length ? chunk.cuts : chunk.spans),
  ]);
  if (chunk.decoded && chunk.decoded.length) {
    main.append(el("p", { className: "label", text: "Decoded hidden payload" }), el("pre", { className: "code", text: chunk.decoded.join("\n\n") }));
  }
  if (chunk.reasons && chunk.reasons.length) {
    main.append(el("p", { className: "label", text: "Why (rule trace)" }), el("ul", { className: "reasons" }, chunk.reasons.map((r) => el("li", { text: r }))));
  }
  if (chunk.action === "strip") {
    main.append(
      el("p", { className: "label", text: "Removed before the model saw it" }),
      el("pre", { className: "code code--removed", text: chunk.removed.join("\n\n") }),
      el("p", { className: "label", text: "What the guarded model received" }),
      el("pre", { className: "code", text: chunk.sanitized_text }),
    );
  } else if (chunk.action === "withhold") {
    main.append(el("p", { className: "label", text: "Withheld" }), el("p", { className: "muted fine", text: "The whole passage was withheld: either nothing localised the problem, or what remained after removal was still flagged." }));
  }

  const panel = el("div", { className: "chunk__panel", attrs: { id: panelId, hidden: true } }, [el("div", { className: "chunk__grid" }, [main, side])]);
  head.addEventListener("click", () => {
    const open = head.getAttribute("aria-expanded") === "true";
    head.setAttribute("aria-expanded", open ? "false" : "true");
    panel.hidden = open;
  });
  const item = el("li", { className: `chunk${chunk.flagged ? " chunk--flagged" : ""}` }, [head, panel]);
  return { item, head, panel };
}

const DRIFT_TEXT = {
  unchanged: ["matches approved digest", "success"],
  changed: ["changed after approval", "danger"],
  added: ["not in approved snapshot", "danger"],
  unpinned: ["not pinned", "neutral"],
};

function renderToolRow(tool, index, detector) {
  const panelId = `tool-${index}`;
  const [driftText, driftTone] = DRIFT_TEXT[tool.drift] || [tool.drift, "neutral"];
  const head = el("button", { className: "chunk__head", attrs: { type: "button", "aria-expanded": "false", "aria-controls": panelId } }, [
    el("span", { className: "chunk__rank", text: `T${index + 1}` }),
    el("span", { className: "chunk__source" }, [
      el("span", { className: "chunk__name", text: tool.tool }),
      el("span", { className: "chunk__path", text: `${tool.server} · ${tool.source}` }),
    ]),
    tag(driftText, driftTone, null, "tag--xs"),
    el("span", { className: "chunk__risk" }, [meter(tool.risk, tool.band), el("span", { className: "mono", text: pct(tool.risk) })]),
    tag(tool.band, `band-${tool.band}`, null, "tag--xs"),
    tool.quarantined ? tag("quarantined", "danger", "i-shield") : tag("trusted", "success", "i-check"),
    el("span", { className: "chunk__chev" }, [icon("i-chevron")]),
  ]);

  const main = el("div", { className: "chunk__main" });
  for (const field of tool.fields) {
    main.append(
      el("p", { className: "label", text: `${field.path} · risk ${pct(field.risk)}${field.flagged ? " · flagged" : ""}` }),
      highlighted(field.text, field.flagged ? field.spans : []),
    );
  }
  if (!tool.fields.length) main.append(el("p", { className: "muted fine", text: "No description fields to scan." }));
  if (tool.approved_declaration) {
    main.append(
      el("p", { className: "label", text: "Approved declaration (pinned at review)" }),
      el("pre", { className: "code", text: tool.approved_declaration }),
      el("p", { className: "label", text: "Live declaration" }),
      el("pre", { className: "code code--changed", text: tool.live_declaration }),
    );
  }
  main.append(el("p", { className: "label", text: "Why" }), el("ul", { className: "reasons" }, tool.reasons.map((r) => el("li", { text: r }))));

  const side = el("div", { className: "chunk__side" }, [
    kv("Decision", tool.quarantined ? "quarantined" : "trusted"),
    kv("Drift", driftText),
    kv("Policy class", `${tool.category.replace(/_/g, " ")}${tool.unknown_tool ? " (fallback)" : ""}`),
    kv("Worst field risk", pct(tool.risk)),
    kv("Flags at", thresholdText(detector)),
    kv("Live digest", tool.live_digest),
    kv("Approved digest", tool.approved_digest || "none pinned"),
  ]);

  const panel = el("div", { className: "chunk__panel", attrs: { id: panelId, hidden: true } }, [el("div", { className: "chunk__grid" }, [main, side])]);
  head.addEventListener("click", () => {
    const open = head.getAttribute("aria-expanded") === "true";
    head.setAttribute("aria-expanded", open ? "false" : "true");
    panel.hidden = open;
  });
  const item = el("li", { className: `chunk${tool.quarantined ? " chunk--flagged" : ""}` }, [head, panel]);
  return { item, head, panel };
}

function renderManifestPanel(result) {
  const { tools, servers } = result.manifests;
  const rendered = tools.map((tool, i) => ({ tool, ...renderToolRow(tool, i, result.detector) }));
  const first = rendered.find((r) => r.tool.quarantined);
  if (first) {
    first.head.setAttribute("aria-expanded", "true");
    first.panel.hidden = false;
  }
  const removed = servers.filter((s) => s.removed.length).map((s) => `${s.server}: ${s.removed.join(", ")} removed since approval`);
  return el("section", { className: "panel inspection", attrs: { "aria-label": "Tool manifest scan" } }, [
    el("div", { className: "inspection__head" }, [
      el("h4", {}, [icon("i-layers"), "Tool manifests from connected servers"]),
      el("p", { className: "muted", text: "A tool is quarantined when a description field is flagged or its declaration no longer matches the approved snapshot. Quarantined tools are left out of the guarded run." }),
    ]),
    removed.length ? el("p", { className: "muted fine", text: removed.join(" · ") }) : null,
    el("ul", { className: "chunks" }, rendered.map((r) => r.item)),
  ]);
}

function renderInspection(result) {
  const labels = {};
  if (state.revealed) {
    for (const sample of state.samples) {
      labels[sample.doc_id] = sample.label === "poisoned" ? tag("poisoned", "danger", null, "tag--xs") : tag("clean", "success", null, "tag--xs");
    }
  }
  const rendered = result.sentinel.chunks.map((chunk) => renderChunk(chunk, labels, result.detector));
  const firstFlagged = rendered.find((_, i) => result.sentinel.chunks[i].flagged);
  if (firstFlagged) {
    firstFlagged.head.setAttribute("aria-expanded", "true");
    firstFlagged.panel.hidden = false;
  }
  return el("section", { className: "panel inspection", attrs: { "aria-label": "What Sentinel found" } }, [
    el("div", { className: "inspection__head" }, [
      el("h4", {}, [icon("i-scan"), "What Sentinel found in the retrieved context"]),
      el("p", { className: "muted", text: result.detector.decision_rule }),
    ]),
    el("ul", { className: "chunks" }, rendered.map((r) => r.item)),
  ]);
}

function renderActions(actions, guarded) {
  if (!actions.length) return null;
  return el("div", {}, [
    el("p", { className: "label", text: guarded ? "Tool requests, decided by the capability policy" : "Tool requests (no gate)" }),
    el("ul", { className: "actions" }, actions.map((action) => {
      const dangerous = DANGEROUS.has(action.category);
      const tone = guarded ? OUTCOME_TONE[action.outcome] || "neutral" : dangerous ? "danger" : "neutral";
      const outcomeText = guarded ? action.outcome : "would run";
      const args = typeof action.arguments === "string" ? action.arguments : JSON.stringify(action.arguments);
      return el("li", { className: "action" }, [
        el("code", { className: "action__tool", text: action.tool }),
        tag(action.category.replace(/_/g, " "), dangerous ? "danger" : "neutral", null, "tag--xs"),
        tag(outcomeText, tone, guarded && action.outcome === "block" ? "i-shield-check" : dangerous ? "i-alert" : null),
        el("details", { className: "action__why" }, [
          el("summary", { text: "Arguments and reasons" }),
          el("pre", { className: "code", text: args || "{}" }),
          el("ul", { className: "reasons" }, action.reasons.map((r) => el("li", { text: r }))),
        ]),
      ]);
    })),
  ]);
}

function renderSide(side, guarded) {
  const title = guarded ? "With LLMSentinel" : "Without Sentinel";
  if (!side.ok) {
    return el("article", { className: "side side--error" }, [
      el("header", { className: "side__head" }, [
        el("span", { className: `side__icon${guarded ? " is-guarded" : ""}` }, [icon(guarded ? "i-shield-check" : "i-shield-off")]),
        el("h4", { text: title }),
        tag("no answer", "neutral"),
      ]),
      el("div", { className: "side__body" }, [
        el("p", { className: "side__error", text: side.error }),
        side.hint ? el("p", { className: "muted fine", text: side.hint }) : null,
      ]),
    ]);
  }
  const tone = side.compromised ? "danger" : "success";
  const body = el("div", { className: "side__body" }, [
    el("div", { className: "answer", text: side.answer || (side.actions.length
      ? "(no prose: the model replied with a tool request only — see below)"
      : "(the model returned no text)") }),
  ]);
  if (side.indicators.length) {
    body.append(el("div", {}, [
      el("p", { className: "label", text: "Signs of compromise" }),
      el("ul", { className: "indicators" }, side.indicators.map((item) => el("li", {}, [
        icon("i-alert"),
        el("span", {}, [el("strong", { text: `${INDICATOR_TEXT[item.kind] || item.kind}: ` }), item.evidence]),
      ]))),
    ]));
  }
  const actions = renderActions(side.actions, guarded);
  if (actions) body.append(actions);
  if (side.notes && side.notes.length) {
    body.append(el("div", {}, [
      el("p", { className: "label", text: side.simulated ? "Simulator log (what it obeyed)" : "Provider notes" }),
      el("ul", { className: "reasons" }, side.notes.map((n) => el("li", { text: n }))),
    ]));
  }
  body.append(
    el("details", { className: "prompt" }, [
      el("summary", {}, [icon("i-eye"), `Exact messages sent (${(side.system_prompt.length + side.prompt_chars).toLocaleString()} chars)`]),
      el("pre", { className: "code", text: `SYSTEM\n${side.system_prompt}\n\nUSER\n${side.prompt}` }),
    ]),
    el("p", { className: "side__meta", text: `${side.provider} · ${side.model} · ${formatMs(side.latency_ms)}` }),
  );
  return el("article", { className: `side side--${tone}`, attrs: { "aria-label": title } }, [
    el("header", { className: "side__head" }, [
      el("span", { className: `side__icon${guarded ? " is-guarded" : ""}` }, [icon(guarded ? "i-shield-check" : "i-shield-off")]),
      el("h4", { text: title }),
      side.compromised ? tag("compromised", "danger", "i-alert") : tag("no compromise signs", "success", "i-check"),
    ]),
    body,
  ]);
}

function renderResults(result) {
  $("#results-empty").hidden = true;
  const fallback = result.detector && result.detector.transformer_loaded === false;
  $("#results-body").replaceChildren(...[
    renderBanner(result),
    fallback ? el("div", { className: "notice notice--quiet" }, [
      icon("i-alert"),
      el("div", {}, [
        el("p", {}, [el("strong", { text: "Rules-only fallback. " }),
          "The transformer checkpoint is not loaded, so these results come from the rule engine alone. It is markedly weaker: on this sample pack it contains 3 of 6 preset attacks, against 6 of 6 with the transformer."]),
        el("p", { className: "fine muted", text: (result.detector.notes || []).join(" ") }),
      ]),
    ]) : null,
    el("div", { className: "compare" }, [renderSide(result.unguarded, false), renderSide(result.guarded, true)]),
    result.manifests && result.manifests.tools.length ? renderManifestPanel(result) : null,
    result.sentinel.chunks.length ? renderInspection(result) : null,
  ].filter(Boolean));
}

async function runComparison() {
  if (state.running) return;
  const question = $("#question").value.trim();
  if (!question) {
    toast("Ask a question first", "Pick an example question or type your own.", "danger");
    $("#question").focus();
    return;
  }
  if (!state.selected.size && !state.uploads.length && !state.selectedManifests.size) {
    toast("No context selected", "Select at least one document or tool server, or upload a file.", "danger");
    return;
  }
  setRunning(true);
  showSkeleton();
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const result = await api("/api/compare", {
      question,
      sample_ids: [...state.selected],
      manifest_ids: [...state.selectedManifests],
      uploads: state.uploads,
      provider: providerConfig(),
      top_k: Number($("#top-k").value),
      max_tokens: Number($("#max-tokens").value) || undefined,
    });
    renderResults(result);
    $("#results").focus({ preventScroll: true });
    if (result.history && result.history.recorded) {
      toast("Recorded for review", `${result.history.recorded} scan(s) saved, ${result.history.queued} queued for review. See the Analyst section.`, "success");
      refreshAnalyst();
    }
  } catch (error) {
    $("#results-body").replaceChildren();
    $("#results-empty").hidden = false;
    toast(error.message, error.hint || "", "danger");
  } finally {
    setRunning(false);
  }
}

/* ----------------------------------------------------------------- analyst */
const REVIEWER_KEY = "llmsentinel-studio-reviewer";
const analyst = { enabled: true, view: "queue" };

function reviewerName() {
  return $("#reviewer-name").value.trim();
}

function rememberReviewer() {
  try {
    localStorage.setItem(REVIEWER_KEY, reviewerName());
  } catch (error) {
    /* per-browser convenience only */
  }
}

function requireReviewer() {
  const name = reviewerName();
  if (!name) {
    toast("Reviewer name needed", "Type your name in the Reviewer box first; every decision is attributed.", "danger");
    $("#reviewer-name").focus();
  }
  return name;
}

function query(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

function shortTime(iso) {
  return iso ? iso.replace("T", " ").replace("+00:00", "Z").slice(0, 20) : "";
}

async function refreshAnalystSummary() {
  const box = $("#analyst-summary");
  try {
    const data = await api("/api/analyst/summary");
    analyst.enabled = true;
    const pills = [
      ["scans", "scans recorded"], ["flagged", "flagged"], ["queued", "awaiting review"],
      ["reviewed", "reviewed"], ["open_alerts", "open manifest alerts"],
    ];
    box.replaceChildren(...pills.map(([key, label]) => el("div", { className: "summary-pill" }, [el("strong", { text: data[key] }), el("span", { text: label })])));
  } catch (error) {
    analyst.enabled = false;
    box.replaceChildren(el("p", { className: "muted", text: `${error.message} ${error.hint || ""}` }));
  }
}

function scanWhere(item) {
  if (item.kind === "action") return item.action_tool || item.tool || "-";
  if (item.kind === "manifest") return `${item.server || "?"} / ${item.tool || "?"}`;
  return [item.source, item.json_path].filter(Boolean).join(" · ") || item.channel || "-";
}

function scanCall(item) {
  if (item.kind === "action") return tag(item.decision || "-", OUTCOME_TONE[item.decision] || "neutral", null, "tag--xs");
  return item.flagged ? tag("flagged", "danger", null, "tag--xs") : tag("passed", "success", null, "tag--xs");
}

function renderScanTable(items, emptyText) {
  if (!items.length) return el("p", { className: "muted", text: emptyText });
  const head = el("tr", {}, ["Scan", "When", "Kind", "Where", "Call", "Risk", "Families", "Review"].map((h) => el("th", { text: h, attrs: { scope: "col" } })));
  const rows = items.map((item) => {
    const open = el("button", { className: "row-button", text: item.scan_id.slice(0, 10), attrs: { type: "button", "aria-label": `Open scan ${item.scan_id.slice(0, 10)}` } });
    open.addEventListener("click", () => openScan(item.scan_id));
    return el("tr", {}, [
      el("td", {}, [open]),
      el("td", { className: "num", text: shortTime(item.created_at) }),
      el("td", { text: item.kind }),
      el("td", { className: "excerpt", text: scanWhere(item) }),
      el("td", {}, [scanCall(item)]),
      el("td", { className: "num", text: item.kind === "action" ? "-" : pct(item.risk) }),
      el("td", { text: (item.families || []).join(", ") || "-" }),
      el("td", { className: "excerpt", text: (item.review_reasons || [])[0] || "-" }),
    ]);
  });
  return el("div", { className: "table-wrap" }, [el("table", { className: "data-table" }, [el("thead", {}, [head]), el("tbody", {}, rows)])]);
}

async function loadQueue() {
  const data = await api(`/api/analyst/queue${query({ limit: 100 })}`);
  $("#analyst-body").replaceChildren(
    el("p", { className: "fine muted", text: "Uncertain, unexplained or elevated-but-not-high scans nobody has reviewed yet, riskiest first. Confident detections are not queued." }),
    renderScanTable(data.items, "Nothing awaiting review."),
  );
}

function historyFilters() {
  return {
    kind: $("#f-kind").value, channel: $("#f-channel").value, family: $("#f-family").value,
    decision: $("#f-decision").value, action_class: $("#f-class").value, flagged: $("#f-flagged").value,
    reviewed: $("#f-reviewed").value, tool: $("#f-tool").value.trim(), server: $("#f-server").value.trim(),
    source: $("#f-source").value.trim(), limit: 200,
  };
}

async function loadHistory() {
  const data = await api(`/api/analyst/scans${query(historyFilters())}`);
  $("#analyst-body").replaceChildren(
    el("p", { className: "fine muted", text: `${data.total} matching scan(s); showing the newest ${data.items.length}.` }),
    renderScanTable(data.items, "No scans match these filters."),
  );
}

async function loadInsights() {
  const by = $("#insights-by").value;
  const data = await api(`/api/analyst/stats${query({ by })}`);
  if (!data.rows.length) {
    $("#analyst-body").replaceChildren(el("p", { className: "muted", text: "No scans recorded yet." }));
    return;
  }
  const head = el("tr", {}, [by.replace(/_/g, " "), "Scans", "Flagged", "Rate", "Mean risk", "Max risk", "Reviewed"].map((h) => el("th", { text: h, attrs: { scope: "col" } })));
  const rows = data.rows.map((row) => el("tr", {}, [
    el("td", { className: "excerpt", text: row.key }),
    el("td", { className: "num", text: row.scans }),
    el("td", { className: "num", text: row.flagged }),
    el("td", { className: "num", text: `${(row.flagged_rate * 100).toFixed(0)}%` }),
    el("td", { className: "num", text: pct(row.mean_risk) }),
    el("td", { className: "num", text: pct(row.max_risk) }),
    el("td", { className: "num", text: row.reviewed }),
  ]));
  $("#analyst-body").replaceChildren(el("div", { className: "table-wrap" }, [el("table", { className: "data-table" }, [el("thead", {}, [head]), el("tbody", {}, rows)])]));
}

async function loadAlerts() {
  const data = await api("/api/analyst/alerts");
  if (!data.items.length) {
    $("#analyst-body").replaceChildren(el("p", { className: "muted", text: "No open manifest alerts. Upload a tool manifest (.json with a \"tools\" list) in the console to see one." }));
    return;
  }
  const servers = [...new Set(data.items.map((a) => a.server))];
  const approveButtons = servers.map((server) => {
    const button = el("button", { className: "btn btn--small", text: `Approve current ${server} manifest`, attrs: { type: "button" } });
    button.addEventListener("click", async () => {
      const by = requireReviewer();
      if (!by) return;
      try {
        const result = await api(`/api/analyst/manifests/${encodeURIComponent(server)}/approve`, { by });
        toast("Manifest approved", `Pinned ${result.pinned.join(", ")} on ${server}. Later changes will raise alerts.`, "success");
      } catch (error) {
        toast(error.message, error.hint || "", "danger");
      }
    });
    return button;
  });
  const items = data.items.map((alert) => {
    const ack = el("button", { className: "btn btn--small btn--ghost", text: "Acknowledge", attrs: { type: "button" } });
    ack.addEventListener("click", async () => {
      const by = requireReviewer();
      if (!by) return;
      try {
        await api(`/api/analyst/alerts/${alert.alert_id}/ack`, { by, note: "acknowledged in the Studio" });
        await refreshAnalyst();
      } catch (error) {
        toast(error.message, error.hint || "", "danger");
      }
    });
    return el("li", { className: "alert-item" }, [
      tag(alert.kind, alert.kind === "unapproved" ? "warning" : "danger", "i-alert", "tag--xs"),
      el("p", { text: `${alert.description} · ${shortTime(alert.created_at)}` }),
      ack,
    ]);
  });
  $("#analyst-body").replaceChildren(
    el("p", { className: "fine muted", text: "Approving pins each tool's name, description and parameter schema as reviewed. Acknowledging closes an alert; it stays in the history." }),
    el("div", { className: "row" }, approveButtons),
    el("ul", { className: "alert-list" }, items),
  );
}

async function refreshAnalyst() {
  await refreshAnalystSummary();
  if (!analyst.enabled) {
    $("#analyst-body").replaceChildren();
    return;
  }
  $("#history-filters").hidden = analyst.view !== "history";
  $("#insights-controls").hidden = analyst.view !== "insights";
  try {
    if (analyst.view === "queue") await loadQueue();
    else if (analyst.view === "history") await loadHistory();
    else if (analyst.view === "insights") await loadInsights();
    else await loadAlerts();
  } catch (error) {
    $("#analyst-body").replaceChildren(el("p", { className: "side__error", text: error.message }));
  }
}

async function openScan(scanId) {
  const panel = $("#analyst-detail");
  let data;
  try {
    data = await api(`/api/analyst/scans/${scanId}`);
  } catch (error) {
    toast(error.message, error.hint || "", "danger");
    return;
  }
  const scan = data.scan;
  const side = el("div", { className: "detail-side" }, [
    kv("Kind", scan.kind),
    kv("Detector said", data.detector_label),
    kv("Effective label", data.effective_label),
    kv("Risk", scan.kind === "action" ? "-" : pct(scan.risk)),
    kv("Band", scan.band || "-"),
    kv("Decided by", scan.decided_by || scan.decision || "-"),
    kv("Channel", scan.channel || "-"),
    kv("Source", scan.source || "-"),
    kv("Tool / server", [scan.tool, scan.server].filter(Boolean).join(" @ ") || "-"),
    kv("Drift", scan.drift || "-"),
    kv("Detector", scan.detector || "-"),
    kv("Recorded", shortTime(scan.created_at)),
  ]);

  const main = el("div", {}, []);
  if (scan.text) main.append(el("p", { className: "label", text: scan.kind === "manifest" ? "Declaration as scanned" : "Text as scanned (flagged spans marked)" }), highlighted(scan.text, scan.kind === "content" ? scan.spans : []));
  if (scan.review_reasons.length) main.append(el("p", { className: "label", text: "Why it is in the review queue" }), el("ul", { className: "reasons" }, scan.review_reasons.map((r) => el("li", { text: r }))));
  if (scan.rule_trace.length) main.append(el("p", { className: "label", text: "Rule trace" }), el("ul", { className: "reasons" }, scan.rule_trace.map((r) => el("li", { text: r }))));
  if (scan.decision_reasons.length) main.append(el("p", { className: "label", text: "Policy reasons" }), el("ul", { className: "reasons" }, scan.decision_reasons.map((r) => el("li", { text: r }))));

  const overrides = data.overrides.length
    ? el("ul", { className: "override-list" }, data.overrides.map((o) => el("li", {}, [
      el("strong", { text: `${o.reviewer} labelled it ${o.label}` }),
      el("span", { className: "muted fine", text: shortTime(o.created_at) }),
      el("span", { text: o.rationale }),
    ])))
    : el("p", { className: "muted fine", text: "No reviewer has labelled this scan yet." });

  const labelSelect = el("select", { attrs: { id: "override-label" } }, [el("option", { text: "injection", attrs: { value: "injection" } }), el("option", { text: "benign", attrs: { value: "benign" } })]);
  labelSelect.value = data.detector_label === "injection" ? "benign" : "injection";
  const rationale = el("textarea", { attrs: { id: "override-rationale", rows: "3", maxlength: "2000", placeholder: "Why? At least 15 characters; this is the audit trail." } });
  const save = el("button", { className: "btn btn--small btn--primary", text: "Record label", attrs: { type: "submit" } });
  const form = el("form", { className: "override-form" }, [
    el("p", { className: "label", text: "Add a reviewer label (the original verdict is kept)" }),
    el("div", { className: "field" }, [el("label", { text: "Label", attrs: { for: "override-label" } }), labelSelect]),
    el("div", { className: "field" }, [el("label", { text: "Rationale", attrs: { for: "override-rationale" } }), rationale]),
    save,
  ]);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const reviewer = requireReviewer();
    if (!reviewer) return;
    try {
      await api(`/api/analyst/scans/${scanId}/override`, { label: labelSelect.value, reviewer, rationale: rationale.value });
      toast("Label recorded", "Saved beside the detector's original call.", "success");
      await openScan(scanId);
      await refreshAnalyst();
    } catch (error) {
      toast(error.message, error.hint || "", "danger");
    }
  });

  const actions = [];
  if (scan.kind === "content" && data.overrides.length) {
    const promote = el("button", { className: "btn btn--small", text: "Promote to regression fixture", attrs: { type: "button" } });
    promote.addEventListener("click", async () => {
      const by = requireReviewer();
      if (!by) return;
      try {
        const result = await api(`/api/analyst/scans/${scanId}/promote`, { by });
        const changes = result.fixture.sanitisation.length ? result.fixture.sanitisation.join("; ") : "no changes needed";
        toast(`Fixture ${result.fixture.id} added`, `Sanitised: ${changes}.`, "success");
      } catch (error) {
        toast(error.message, error.hint || "", "danger");
      }
    });
    actions.push(promote);
  }
  const close = el("button", { className: "btn btn--small btn--ghost", text: "Close", attrs: { type: "button" } });
  close.addEventListener("click", () => { panel.hidden = true; });
  actions.push(close);

  panel.replaceChildren(
    el("div", { className: "detail-head" }, [
      el("h3", { text: `Scan ${scanId.slice(0, 12)}`, attrs: { id: "detail-title" } }),
      el("div", { className: "row" }, actions),
    ]),
    el("div", { className: "detail-grid" }, [main, side]),
    el("div", {}, [el("p", { className: "label", text: "Reviewer labels" }), overrides]),
    form,
  );
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initAnalyst() {
  try {
    $("#reviewer-name").value = localStorage.getItem(REVIEWER_KEY) || "";
  } catch (error) {
    /* storage unavailable */
  }
  $("#reviewer-name").addEventListener("change", rememberReviewer);
  $("#analyst-refresh").addEventListener("click", refreshAnalyst);
  document.querySelectorAll('input[name="analyst-view"]').forEach((radio) => radio.addEventListener("change", () => {
    analyst.view = radio.value;
    refreshAnalyst();
  }));
  $("#history-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    refreshAnalyst();
  });
  $("#insights-by").addEventListener("change", refreshAnalyst);
  refreshAnalyst();
}

/* -------------------------------------------------------------------- init */
async function init() {
  initTheme();
  initAnalyst();
  document.querySelectorAll('input[name="provider"]').forEach((radio) => radio.addEventListener("change", () => applyProvider(radio.value)));
  $("#base-url").addEventListener("input", rememberEdit);
  $("#model").addEventListener("input", rememberEdit);
  $("#model").addEventListener("change", applyProfile);
  $("#test-connection").addEventListener("click", testConnection);
  $("#select-all").addEventListener("click", () => {
    state.samples.forEach((s) => state.selected.add(s.doc_id));
    state.manifests.forEach((m) => state.selectedManifests.add(m.manifest_id));
    renderSamples();
    renderManifests();
  });
  $("#clear-all").addEventListener("click", () => {
    state.selected.clear();
    state.selectedManifests.clear();
    renderSamples();
    renderManifests();
  });
  $("#reveal-toggle").addEventListener("change", async (event) => {
    state.revealed = event.target.checked;
    try {
      await loadSamples();
    } catch (error) {
      toast(error.message, error.hint || "", "danger");
    }
  });
  $("#run").addEventListener("click", runComparison);
  $("#question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      runComparison();
    }
  });
  wireDropzone();

  try {
    const [health, samples] = await Promise.all([api("/api/health"), api("/api/samples")]);
    state.presets = health.presets || {};
    state.profiles = health.model_profiles || state.profiles;
    state.defaultMaxTokens = health.default_max_tokens || state.defaultMaxTokens;
    state.questions = health.questions || [];
    state.maxUploads = (health.limits && health.limits.max_uploads) || state.maxUploads;
    state.samples = samples.items || [];
    state.samples.forEach((s) => state.selected.add(s.doc_id));
    state.manifests = samples.manifests || [];
    state.manifests.forEach((m) => state.selectedManifests.add(m.manifest_id));
    applyEvidence(health.evidence);
    renderDetector(health.detector);
    renderSamples();
    renderManifests();
    renderPresets();
    applyProvider(currentProvider());
  } catch (error) {
    renderDetector(null);
    toast(error.message, error.hint || "", "danger");
  }
}

document.addEventListener("DOMContentLoaded", init);
