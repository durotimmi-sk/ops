const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function readConversationId() {
  try {
    let id = localStorage.getItem("taskvault-conversation-id");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("taskvault-conversation-id", id);
    }
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

const state = {
  view: "assistant",
  navPanelOpen: (() => {
    try { return localStorage.getItem("taskvault-nav-panel-open") !== "false"; }
    catch { return true; }
  })(),
  messages: [],
  conversationId: readConversationId(),
  conversationStarted: (() => {
    try { return localStorage.getItem("taskvault-conversation-started") === "true"; }
    catch { return false; }
  })(),
  sources: [],
  activeTaskId: null,
  busy: false,
  pollToken: 0,
  health: null,
  inferenceCheck: null,
  tasks: [],
  watches: [],
  approvals: [],
  profile: {},
  draftApproval: null,
  watchTarget: null,
  orderTarget: null,
  brief: null,
  voiceActive: false,
  voiceRecognition: null,
  noticeAction: null,
  recentCleared: false,
  utilityAction: null,
  agentPanelOpen: (() => {
    try {
      if (window.matchMedia("(max-width: 1180px)").matches) return false;
      const saved = localStorage.getItem("taskvault-agent-panel-open");
      return saved === null ? window.matchMedia("(min-width: 1181px)").matches : saved !== "false";
    } catch { return window.matchMedia("(min-width: 1181px)").matches; }
  })(),
};

const VIEW_META = {
  assistant: {
    title: "Assistant",
    kicker: "Workspace",
    heading: "Supplier assistant",
    description: "Source, compare, and review supplier evidence.",
  },
  tasks: {
    title: "Research tasks",
    kicker: "Workspace",
    heading: "Research tasks",
    description: "Completed comparisons and runs that are still in motion.",
  },
  watches: {
    title: "Price watch",
    kicker: "Monitoring",
    heading: "Price watch",
    description: "Targets checked against the evidence attached to a completed run.",
  },
  approvals: {
    title: "Approvals",
    kicker: "Control",
    heading: "Approvals",
    description: "Drafts that need a human decision before anything leaves the workspace.",
  },
  activity: {
    title: "Activity",
    kicker: "Audit",
    heading: "Activity",
    description: "Review what TaskVault did, what evidence it saved, and whether the activity record passes its integrity check.",
  },
  connections: {
    title: "Connections",
    kicker: "Workspace setup",
    heading: "Connections",
    description: "Set buyer defaults and check which parts of the procurement workflow are ready.",
  },
};

const ICON = {
  external: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M7 7h10v10"/></svg>',
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4.2 4.2L19 6.4"/></svg>',
  quote: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14M5 11h14M5 16h8"/></svg>',
  watch: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 18V6M4 18h16"/><path d="m7 14 4-4 3 2 5-6"/></svg>',
  order: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12v16H6z"/><path d="M9 8h6m-6 4h6m-6 4h4"/></svg>',
  run: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="m8.5 12 2.2 2.2 4.8-4.8"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>',
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function money(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return "$" + number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function truncate(value, limit = 180) {
  const text = String(value ?? "").trim();
  if (text.length <= limit) return text;
  return text.slice(0, limit - 1).trimEnd() + "…";
}

function titleCase(value) {
  const text = String(value || "unknown").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function shortId(value) {
  return String(value || "").slice(0, 8);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function hostLabel(value) {
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return value;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const base = String(window.TASKVAULT_API_BASE_URL || "").replace(/\/+$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

async function request(path, options = {}) {
  const init = { method: options.method || "GET", headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(apiUrl(path), init);
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = new Error((data && data.error) || "The request could not be completed.");
    error.status = response.status;
    error.code = data && data.code;
    error.data = data;
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      showSignin("Your session ended. Sign in again to continue.");
    }
    throw error;
  }
  return data;
}

let workspaceStarted = false;

function showSignin(message = "") {
  const layer = $("#signin-layer");
  const appShell = $("#app-shell");
  layer.hidden = false;
  appShell.inert = true;
  $("#signout-button").hidden = true;
  const error = $("#signin-error");
  error.textContent = message;
  error.hidden = !message;
  window.setTimeout(() => $("#signin-password").focus(), 30);
}

function hideSignin(authEnabled) {
  $("#signin-layer").hidden = true;
  $("#app-shell").inert = false;
  $("#signout-button").hidden = !authEnabled;
  $("#signin-password").value = "";
  $("#signin-error").hidden = true;
}

function startWorkspace() {
  if (workspaceStarted) return;
  workspaceStarted = true;
  syncNavPanel();
  syncAgentPanel();
  renderSources();
  renderMessages();
  restoreConversation();
  loadHealth();
  loadProfile();
  refreshBadges();
  autoGrow();
}

async function checkSignIn() {
  try {
    const status = await request("/api/auth/session");
    if (status.auth_enabled && !status.authenticated) {
      showSignin();
      return;
    }
    hideSignin(Boolean(status.auth_enabled));
    startWorkspace();
  } catch {
    showSignin("The workspace is not responding yet. Check your connection and try again.");
  }
}

$("#signin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#signin-submit");
  const error = $("#signin-error");
  button.disabled = true;
  button.querySelector("span").textContent = "Signing in…";
  error.hidden = true;
  try {
    const result = await request("/api/auth/login", {
      method: "POST",
      body: {
        username: $("#signin-username").value.trim(),
        password: $("#signin-password").value,
      },
    });
    hideSignin(Boolean(result.authenticated));
    startWorkspace();
  } catch (loginError) {
    error.textContent = loginError.status === 429
      ? "Too many attempts. Wait 15 minutes, then try again."
      : loginError.status === 401
        ? "That username or password did not match. Try again."
        : loginError.message || "Sign-in failed. Check your connection and try again.";
    error.hidden = false;
    $("#signin-password").select();
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Sign in";
  }
});

$("#signout-button").addEventListener("click", async () => {
  try {
    await request("/api/auth/logout", { method: "POST", body: {} });
  } finally {
    showSignin("You have signed out.");
  }
});

function openModal(id) {
  const dialog = document.getElementById(id);
  if (dialog && !dialog.open) dialog.showModal();
}

function closeModal(id) {
  const dialog = document.getElementById(id);
  if (dialog && dialog.open) dialog.close();
}

function showNotice(title, body, options = {}) {
  $("#notice-title").textContent = title;
  $("#notice-body").textContent = body;
  $("#notice-action").textContent = options.actionLabel || "Got it";
  state.noticeAction = typeof options.onAction === "function" ? options.onAction : null;
  openModal("notice-dialog");
}

function showHelp() {
  showNotice(
    "How TaskVault works",
    "TaskVault is a permission-aware procurement workspace.\n\n" +
      "1. Ask for a product and quantity. The request is matched to the bundled supplier index and planned as a sourcing run.\n" +
      "2. When an isolation runtime is available, a bounded worker runs without the inference key, database path, or inherited credentials. If only the local process fallback is available, the app labels the run as unisolated. Every run leaves a receipt.\n" +
      "3. The engine compares landed cost, minimum order, lead time, rating, and documentation status. Each offer keeps a local evidence record you can open.\n" +
      "4. Quotes and purchase orders are drafts. Nothing is sent to a supplier and no payment is taken. A human approval is recorded in the audit ledger.\n\n" +
      "The supplier index is bundled with this demonstration. It is not a live web scrape. Prices and availability must be confirmed with the supplier before ordering."
  );
}

function setSandboxState(health) {
  const label = $("#sandbox-label");
  const detail = $("#sandbox-detail");
  const container = $("#sandbox-state");
  if (!health) {
    label.textContent = "Sandbox idle";
    detail.textContent = "Start the backend to run sourcing";
    container.dataset.mode = "idle";
    container.title = `${label.textContent}. ${detail.textContent}.`;
    return;
  }
  const mode = health.sandbox_mode || "unavailable";
  const isolatedModes = ["docker", "bubblewrap", "macos-seatbelt"];
  container.dataset.mode = isolatedModes.includes(mode) ? "isolated" : mode;
  if (mode === "docker") {
    label.textContent = "Isolation ready";
    detail.textContent = "Container · network denied";
  } else if (mode === "bubblewrap") {
    label.textContent = "Isolation ready";
    detail.textContent = "Linux namespace · network denied";
  } else if (mode === "macos-seatbelt") {
    label.textContent = "Isolation ready";
    detail.textContent = "macOS Seatbelt · network denied";
  } else if (mode === "process") {
    label.textContent = "Isolation unavailable";
    detail.textContent = "Local fallback · host access available";
  } else {
    label.textContent = "Worker unavailable";
    detail.textContent = "Install a supported isolation runtime";
  }
  container.title = `${label.textContent}. ${detail.textContent}.`;
}

async function loadHealth() {
  try {
    const health = await request("/api/health");
    state.health = health;
    setSandboxState(health);
  } catch {
    state.health = null;
    setSandboxState(null);
  }
}

function applyProfile(profile) {
  state.profile = profile || {};
  const name = state.profile.buyer_name || state.profile.company || "Your workspace";
  const company = state.profile.company || "Buyer profile";
  $("#profile-name").textContent = name;
  $("#profile-company").textContent = company;
}

async function loadProfile() {
  try {
    const data = await request("/api/profile");
    applyProfile(data.profile);
  } catch {
    applyProfile({});
  }
}

async function refreshBadges() {
  try {
    const [tasks, watches, approvals] = await Promise.all([
      request("/api/tasks"),
      request("/api/watches"),
      request("/api/approvals"),
    ]);
    state.tasks = tasks.tasks || [];
    state.watches = watches.watches || [];
    state.approvals = approvals.approvals || [];
    updateCounts();
    renderRecent();
  } catch {
    updateCounts();
    renderRecent();
  }
}

function updateCounts() {
  $("#task-count").textContent = String(state.tasks.length);
  $("#task-count").hidden = state.tasks.length === 0;
  const watchCount = state.watches.length;
  const approvalCount = state.approvals.filter((item) => item.status === "pending").length;
  $("#watch-count").textContent = String(watchCount);
  $("#watch-count").hidden = watchCount === 0;
  $("#approval-count").textContent = String(approvalCount);
  $("#approval-count").hidden = approvalCount === 0;
}

function renderRecent() {
  const list = $("#recent-list");
  const empty = $("#recent-empty");
  if (state.recentCleared) {
    list.innerHTML = "";
    empty.hidden = false;
    empty.textContent = "Recent history cleared.";
    return;
  }
  const recent = state.tasks.slice(0, 8);
  if (!recent.length) {
    list.innerHTML = "";
    empty.hidden = false;
    empty.textContent = "Your sourcing threads will appear here.";
    return;
  }
  empty.hidden = true;
  list.innerHTML = recent
    .map(
      (task) => `
      <button class="recent-item" type="button" data-open-task="${escapeHtml(task.id)}">
        <span>${escapeHtml(truncate(task.query, 34))}</span>
        <small>${escapeHtml(titleCase(task.status))}</small>
      </button>`
    )
    .join("");
}

function renderSources() {
  const container = $("#source-chips");
  if (!state.sources.length) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  container.hidden = false;
  container.innerHTML = state.sources
    .map(
      (source, index) => `
      <span class="source-chip" title="${escapeHtml(source)}">
        <span>${escapeHtml(hostLabel(source))}</span>
        <button type="button" data-remove-source="${index}" aria-label="Remove ${escapeHtml(hostLabel(source))}">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>
        </button>
      </span>`
    )
    .join("");
}

function syncSend() {
  const input = $("#prompt");
  $("#send-button").disabled = state.busy || (!input.value.trim() && !state.sources.length);
}

function autoGrow() {
  const input = $("#prompt");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 180) + "px";
}

function scrollToBottom(force = false) {
  const area = $("#chat-scroll");
  if (!area) return;
  const nearBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 220;
  if (!nearBottom && !force) return;
  requestAnimationFrame(() => {
    area.scrollTop = area.scrollHeight;
  });
}

function scrollToLastMessage() {
  requestAnimationFrame(() => {
    const area = $("#chat-scroll");
    const messages = $$(".message");
    const last = messages[messages.length - 1];
    if (!area || !last) return;
    const offset = last.getBoundingClientRect().top - area.getBoundingClientRect().top + area.scrollTop;
    area.scrollTop = Math.max(0, offset - 16);
  });
}

function renderMessage(message, index) {
  if (message.role === "user") {
    return `<div class="message user" data-index="${index}"><div class="user-bubble">${escapeHtml(message.text)}</div></div>`;
  }
  let body = "";
  if (message.kind === "loading") {
    body = renderLoader(message);
  } else if (message.kind === "research") {
    body = renderResearch(message);
  } else if (message.kind === "clarification") {
    const clarification = message.clarification || {};
    const product = clarification.product || {};
    body = `
      <div class="clarification-card">
        <div class="clarification-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 7.5v5m0 3.5h.01"/><circle cx="12" cy="12" r="9"/></svg></div>
        <div class="clarification-copy">
          <strong>One detail needed</strong>
          <p>${escapeHtml(message.text || clarification.prompt || "Add the quantity to continue.")}</p>
          ${product.short_name ? `<span class="clarification-product">${escapeHtml(product.short_name)}${product.specs ? ` · ${escapeHtml(product.specs)}` : ""}</span>` : ""}
        </div>
        <button class="clarification-action" type="button" data-action="clarify" data-message-index="${index}">Add quantity${ICON.arrow}</button>
      </div>`;
  } else {
    const links = Array.isArray(message.links) ? message.links : [];
    body = `
      <div class="assistant-text">${escapeHtml(message.text || "")}</div>
      ${
        links.length
          ? `<div class="message-links">${links
              .map(
                (link) => `<a class="message-link" href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer noopener">${escapeHtml(hostLabel(link.url))}${ICON.external}</a>`
              )
              .join("")}</div>`
          : ""
      }`;
  }
  return `
    <div class="message assistant${message.kind === "loading" ? " is-working" : ""}" data-index="${index}">
      <div class="assistant-avatar"><img src="./assets/${message.kind === "loading" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "taskvault-mascot-working.gif?v=20261105" : "taskvault-mascot.png"}" alt="" width="32" height="32" loading="eager" decoding="async"></div>
      <div class="assistant-body">
        <div class="assistant-label"><span>TaskVault</span></div>
        ${body}
      </div>
    </div>`;
}

function renderLoader(message) {
  const stage = message.stage || "Preparing a bounded sourcing run";
  const hasTask = Boolean(message.taskId);
  const lower = stage.toLowerCase();
  const sandboxDone = lower.includes("comparison") || lower.includes("ready");
  const sandboxActive = hasTask && !sandboxDone;
  return `
    <div class="loader">
      <div class="loader-line"><span class="loader-spinner" aria-hidden="true"></span><span>${escapeHtml(stage)}</span></div>
      <div class="loader-sub">${hasTask ? "Task " + escapeHtml(shortId(message.taskId)) + " · " : ""}Evidence is linked, not guessed.</div>
      <div class="loader-steps">
        <div class="loader-step is-done"><span class="dot"></span><span>Request accepted and checked</span></div>
        <div class="loader-step ${sandboxActive ? "is-active" : "is-done"}"><span class="dot"></span><span>Run sourcing worker</span></div>
        <div class="loader-step ${sandboxDone ? "is-done" : ""}"><span class="dot"></span><span>Capture allowed sources, compare, and store evidence</span></div>
      </div>
      <div class="loader-links">
        <button type="button" data-action="activity">Open activity</button>
        <button type="button" data-action="help">Methodology</button>
      </div>
    </div>`;
}

function renderLiveCaptures(research) {
  const captures = Array.isArray(research.captures)
    ? research.captures.filter((capture) => capture && typeof capture === "object")
    : [];
  const browser = research.browser || {};
  if (!captures.length && !browser.error) return "";
  const capturedCount = captures.filter((capture) => capture.screenshot_url).length;
  const browserInfo = browser.browser || {};
  const receipt = browser.receipt || {};
  const browserLabel = [browserInfo.name || "Chromium", browserInfo.version || receipt.browser_version || ""].filter(Boolean).join(" ");
  const proxyBlocked = Number((Array.isArray(browser.blocked_proxy_requests) ? browser.blocked_proxy_requests.length : 0) || receipt.blocked_proxy_requests || 0);
  const cards = captures.map((capture) => {
    const title = capture.title || hostLabel(capture.final_url || capture.url || "");
    const screenshotUrl = capture.screenshot_url ? apiUrl(capture.screenshot_url) : "";
    const finalUrl = /^https:\/\//i.test(capture.final_url || "") ? capture.final_url : "";
    const error = capture.error ? String(capture.error) : "";
    const excerpt = !error ? truncate(capture.text_excerpt || "", 170) : "";
    return `
      <article class="capture-card${error ? " has-error" : ""}">
        <div class="capture-frame">
          ${screenshotUrl
            ? `<a href="${escapeHtml(screenshotUrl)}" target="_blank" rel="noreferrer noopener" aria-label="Open screenshot of ${escapeHtml(title)}"><img src="${escapeHtml(screenshotUrl)}" alt="Screenshot of ${escapeHtml(title)}" loading="lazy" decoding="async"></a>`
            : `<div class="capture-placeholder"><span>Capture blocked</span><small>${escapeHtml(error || "No screenshot was retained.")}</small></div>`}
          <span class="capture-badge">${error ? "Blocked" : "Read-only"}</span>
        </div>
        <div class="capture-copy">
          <span class="capture-host">${escapeHtml(capture.host || hostLabel(capture.url || ""))}</span>
          <strong>${escapeHtml(title || "Source page")}</strong>
          ${excerpt ? `<p>${escapeHtml(excerpt)}</p>` : error ? `<p class="capture-error">${escapeHtml(error)}</p>` : ""}
          <div class="capture-meta">
            <span>${escapeHtml(formatDate(capture.captured_at))}</span>
            ${Number(capture.http_status) ? `<span>HTTP ${Number(capture.http_status)}</span>` : ""}
            ${capture.blocked_requests ? `<span>${Number(capture.blocked_requests)} request${Number(capture.blocked_requests) === 1 ? "" : "s"} blocked</span>` : ""}
          </div>
          <div class="capture-links">
            ${screenshotUrl ? `<a href="${escapeHtml(screenshotUrl)}" target="_blank" rel="noreferrer noopener">Open screenshot${ICON.external}</a>` : ""}
            ${finalUrl ? `<a href="${escapeHtml(finalUrl)}" target="_blank" rel="noreferrer noopener">Visit page${ICON.external}</a>` : ""}
          </div>
        </div>
      </article>`;
  }).join("");
  const modeLabel = receipt.mode === "browser-process" ? "Local browser process" : receipt.mode === "browser-bubblewrap" ? "Bubblewrap browser" : "Browser worker";
  const receiptMarkup = receipt.worker_id
    ? `<details class="capture-receipt${receipt.degraded ? " is-degraded" : ""}">
        <summary><span class="capture-receipt-copy"><strong>Capture receipt</strong><small>${escapeHtml(modeLabel)} · ${capturedCount} of ${captures.length} page${captures.length === 1 ? "" : "s"} retained · ${Number(receipt.duration_ms || 0)} ms</small></span><span class="capture-receipt-disclosure">View details</span></summary>
        <div class="capture-receipt-body">
          ${receipt.degraded ? '<p class="capture-warning">Local development capture: the browser shares the host network namespace. Egress is still limited to the allowlist proxy. Use the Linux/Vultr browser worker for full filesystem containment.</p>' : ""}
          <div class="capture-receipt-grid">
            <div><span>Network policy</span><strong>${escapeHtml(receipt.network || "Allowlisted HTTPS only")}</strong></div>
            <div><span>Filesystem</span><strong>${escapeHtml(receipt.filesystem || "Task-scoped browser profile")}</strong></div>
            <div><span>Secrets</span><strong>${escapeHtml(receipt.secrets_policy || "No application secrets inherited")}</strong></div>
            <div><span>Off-allowlist blocked</span><strong>${proxyBlocked} request${proxyBlocked === 1 ? "" : "s"}</strong></div>
            <div><span>Cleanup</span><strong>${escapeHtml(receipt.teardown || "Task directory removed")}</strong></div>
            <div><span>Run reference</span><strong>${escapeHtml(receipt.worker_id)}</strong></div>
          </div>
        </div>
      </details>`
    : "";
  return `
    <section class="live-captures" aria-label="Live source page capture">
      <div class="live-captures-head">
        <div><span class="live-captures-kicker">Live browser evidence</span><strong>${capturedCount ? `${capturedCount} source page${capturedCount === 1 ? "" : "s"} captured` : "Source pages were not captured"}</strong></div>
        <span class="live-captures-device">${escapeHtml(browserLabel || "Read-only browser")}${capturedCount ? " · timestamped" : ""}</span>
      </div>
      <p class="live-captures-explainer">Only the pages you supplied were opened. Each capture is read-only, allowlist-bound, and paired with a timestamped screenshot.</p>
      ${browser.error ? `<div class="capture-unavailable"><strong>Live capture unavailable</strong><span>${escapeHtml(browser.detail || browser.error)} Links remain stored references and were not opened.</span></div>` : ""}
      ${cards ? `<div class="capture-grid">${cards}</div>` : ""}
      ${receiptMarkup}
    </section>`;
}

function renderResearch(message) {
  const research = message.research || {};
  const offers = Array.isArray(research.offers) ? research.offers : [];
  const product = research.product || {};
  const bestId = research.best_value_id;
  const summary = research.summary || message.text || "The comparison is ready.";
  const bestOffer = offers.find((offer) => offer.id === bestId) || offers[0];
  const index = research.index || {};
  const isDemo = Boolean(index.is_demo);
  const rankingMethod = research.ranking_method || {};
  const quantityLabel = research.quantity?.quantity_label || "quantity not specified";
  const providedSources = Array.isArray(research.user_sources)
    ? research.user_sources.filter((source) => typeof source === "string" && /^https?:\/\//i.test(source))
    : [];
  const liveCaptures = Array.isArray(research.captures) ? research.captures : [];
  const liveCaptureCount = liveCaptures.filter((capture) => capture && capture.screenshot_url).length;
  const captureAttempted = Boolean(research.browser && (research.browser.receipt || research.browser.error));
  const duration = Number(message.sandbox?.duration_ms || 0);
  const durationLabel = duration ? `${(duration / 1000).toFixed(duration < 10000 ? 1 : 0)}s run` : "saved result";
  const sourceMarkup = providedSources.length
    ? `<section class="research-sources" aria-label="Links provided for this run">
        <span class="research-sources-label">Links you added · ${liveCaptureCount ? `${liveCaptureCount} captured read-only` : captureAttempted ? "capture attempted" : "not opened"}</span>
        <div class="research-source-list">
          ${providedSources.map((source) => `<a class="research-source" href="${escapeHtml(source)}" target="_blank" rel="noreferrer noopener" title="${escapeHtml(source)}">${escapeHtml(hostLabel(source))}${ICON.external}</a>`).join("")}
        </div>
      </section>`
    : "";
  const fasterOffer = bestOffer && offers.length > 1
    ? offers.filter((offer) => offer.id !== bestOffer.id).sort((a, b) => Number(a.lead_time_days || 0) - Number(b.lead_time_days || 0))[0]
    : null;
  const cheaperOffer = bestOffer && offers.length > 1
    ? offers.filter((offer) => offer.id !== bestOffer.id && Number(offer.landed_cost) < Number(bestOffer.landed_cost)).sort((a, b) => Number(a.landed_cost) - Number(b.landed_cost))[0]
    : null;
  const tradeoff = fasterOffer && Number(fasterOffer.lead_time_days) < Number(bestOffer?.lead_time_days)
    ? `${escapeHtml(fasterOffer.supplier)} ships faster, in ${Number(fasterOffer.lead_time_days)} days.`
    : cheaperOffer
      ? `${escapeHtml(cheaperOffer.supplier)} costs ${money(Number(bestOffer.landed_cost) - Number(cheaperOffer.landed_cost))} less, but ranks lower on the selected criteria.`
      : "Best match across the listed cost, delivery, and supplier fields.";
  const spotlightReason = Array.isArray(bestOffer?.reasons) && bestOffer.reasons.length
    ? bestOffer.reasons.slice(0, 2).join(" · ")
    : tradeoff;
  const verifiedCount = Number(research.verified_count ?? offers.filter((offer) => offer.verified).length);
  const runSteps = [
    ["Request understood", `${quantityLabel}${research.quantity?.quantity_note ? ` · ${research.quantity.quantity_note}` : ""}`],
    [isDemo ? "Sample index searched" : "Supplier sources checked", isDemo ? `${offers.length} illustrative catalog records` : `${offers.length} supplier records`],
    ...(providedSources.length ? [["Source pages captured", liveCaptureCount ? `${liveCaptureCount} read-only page${liveCaptureCount === 1 ? "" : "s"} with screenshots` : "Capture attempted; see browser receipt"]] : []),
    ["Offers compared", "Landed cost, delivery, minimum, and rating"],
    ["Evidence attached", liveCaptureCount ? "Source screenshots plus stored supplier fields" : "Open a record to inspect the fields used"],
  ];
  const runStepsMarkup = `<section class="agent-plan" aria-label="Completed research steps"><div class="agent-plan-heading"><strong>Research plan</strong><span>Complete · ${runSteps.length} steps</span></div><ol>${runSteps.map(([title, detail], index) => `<li><span class="agent-plan-number">${String(index + 1).padStart(2, "0")}</span><span class="agent-plan-copy"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></span><span class="agent-plan-status">Done</span></li>`).join("")}</ol></section>`;
  const evidenceMarkup = `<section class="research-sources" aria-label="Evidence records"><div class="sources-title"><strong>${isDemo ? "Sample evidence records" : "Evidence records"}</strong><span>${offers.length} records · stored supplier fields · live source pages captured separately</span></div><div class="research-source-list">${offers.slice(0, 4).map((offer) => `<a class="research-source evidence-chip" href="${escapeHtml(apiUrl(offer.source_url || "#"))}" target="_blank" rel="noreferrer noopener"><span class="evidence-chip-mark">${String(offer.supplier || "S").slice(0, 1).toUpperCase()}</span><span><strong>${escapeHtml(offer.supplier)}</strong><small>${isDemo ? "Bundled sample record" : "Stored evidence record"}</small></span>${ICON.external}</a>`).join("")}${offers.length > 4 ? `<span class="research-source more-sources">+${offers.length - 4} more</span>` : ""}</div></section>`;
  const limitations = Array.isArray(research.limitations) ? research.limitations : [];
  const traceMarkup = `
    <details class="run-details">
      <summary>
        <span class="run-details-heading"><strong>Agent trace &amp; evidence</strong><small>${runSteps.length} steps · ${offers.length} offer records${liveCaptureCount ? ` · ${liveCaptureCount} live capture${liveCaptureCount === 1 ? "" : "s"}` : ""} · ${escapeHtml(durationLabel)}</small></span>
        <span class="run-details-disclosure">Open</span>
      </summary>
      <div class="run-details-body">
        ${runStepsMarkup}
        ${evidenceMarkup}
        ${sourceMarkup}
        ${!isDemo && summary ? `<p class="trace-summary">${escapeHtml(summary)}</p>` : ""}
        ${limitations.length ? `<section class="trace-limitations"><strong>Known limits</strong><ul>${limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
      </div>
    </details>`;
  return `
    <div class="research">
      <div class="response-topline">
        <span class="response-state"><span class="response-state-mark" aria-hidden="true">${ICON.check}</span>${isDemo ? "Sample comparison" : "Comparison ready"}</span>
        <span>${offers.length} offer${offers.length === 1 ? "" : "s"} · ${escapeHtml(durationLabel)} · evidence attached</span>
      </div>
      ${isDemo ? '<aside class="research-demo-note" role="note"><strong>Illustrative catalog</strong><span>Sample catalog records only · no catalog supplier page was opened. Do not use this for a real purchase.</span></aside>' : ""}
      <p class="research-intro">I compared <strong>${offers.length} ${isDemo ? "sample " : ""}listings</strong> for <strong>${escapeHtml(quantityLabel)}</strong>${product.name ? ` of ${escapeHtml(product.name.toLowerCase())}` : ""}.</p>
      ${renderLiveCaptures(research)}
      ${bestOffer ? `
        <section class="recommendation-spotlight" aria-label="Recommended supplier">
          <div class="spotlight-heading">
            <span class="spotlight-kicker">${isDemo ? "Best sample match" : "Recommended"}</span>
            <span class="spotlight-score">Rank #${String(Number(bestOffer.rank || 1)).padStart(2, "0")} · ${offers.length} offers compared</span>
          </div>
          <div class="spotlight-main">
            <div>
              <h3>${escapeHtml(bestOffer.supplier)}</h3>
              <p>${escapeHtml(product.name || bestOffer.product_name || "Supplier offer")} · ${escapeHtml(quantityLabel)}</p>
            </div>
            <div class="spotlight-price">
              <strong>${money(bestOffer.landed_cost)}</strong>
              <span>landed total · ${money(bestOffer.unit_price)}/${escapeHtml(bestOffer.unit || "unit")}</span>
            </div>
          </div>
          <div class="spotlight-reason"><strong>Why it leads</strong> ${escapeHtml(spotlightReason)}</div>
          <div class="spotlight-facts">
            <span><small>Lead time</small><strong>${Number(bestOffer.lead_time_days || 0)} days</strong></span>
            <span><small>Order minimum</small><strong>${escapeHtml(bestOffer.moq_label || `${Number(bestOffer.moq_units || 0)} units`)}</strong></span>
            <span><small>Shipping</small><strong>${bestOffer.free_shipping ? "Included" : money(bestOffer.shipping)}</strong></span>
            <span><small>Documentation</small><strong>${isDemo ? `${verifiedCount} of ${offers.length} sample flags` : `${verifiedCount} of ${offers.length} verified`}</strong></span>
          </div>
          <div class="spotlight-links">
            <a class="evidence-link" href="${escapeHtml(apiUrl(bestOffer.source_url || "#"))}" target="_blank" rel="noreferrer noopener">Open evidence record${ICON.external}</a>
            <span class="spotlight-freshness">${isDemo ? "Bundled sample record · not live" : `Captured ${escapeHtml(formatDate(bestOffer.captured_at || research.generated_at))}`}</span>
          </div>
          ${renderRankingTrace(bestOffer, rankingMethod)}
        </section>` : ""}
      <div class="offer-list-heading"><h3>Supplier comparison</h3><span>${offers.length} offers · ranked by weighted fit, lowest landed cost first</span></div>
      <div class="offer-list">${offers.map((offer) => renderOffer(offer, bestId, message.taskId, isDemo, rankingMethod)).join("")}</div>
      <div class="research-actions">
        <button class="action-button primary" type="button" data-action="order" data-task="${escapeHtml(message.taskId || "")}" data-offer="${escapeHtml(bestOffer?.id || "")}">${ICON.order}Draft purchase order</button>
        <button class="action-button" type="button" data-action="quote" data-task="${escapeHtml(message.taskId || "")}" data-offer="${escapeHtml(bestOffer?.id || "")}">${ICON.quote}Draft quote</button>
        <button class="action-button" type="button" data-action="watch" data-task="${escapeHtml(message.taskId || "")}" data-offer="${escapeHtml(bestOffer?.id || "")}">${ICON.watch}Watch price</button>
      </div>
      ${traceMarkup}
      ${renderReceipt(message.sandbox)}
    </div>`;
}
function renderOffer(offer, bestId, taskId, isDemo = false, rankingMethod = {}) {
  const isBest = offer.id === bestId;
  const badges = Array.isArray(offer.badges) ? offer.badges : [];
  const movement = offer.movement;
  const movementText = movement
    ? `${movement.direction === "down" ? "↓" : "↑"} ${Math.abs(movement.percent).toFixed(1)}% vs prior`
    : "";
  return `
    <article class="offer ${isBest ? "is-best" : ""}">
      <div class="offer-card-image"><img src="${escapeHtml(offer.image_url || "./assets/taskvault-mark.svg")}" alt="${escapeHtml(offer.product_name || "Product listing")}" loading="lazy"><span class="offer-rank">#${String(Number(offer.rank || 0)).padStart(2, "0")}</span>${isBest ? `<span class="rank-pill">${isDemo ? "Best sample match" : "Top match"}</span>` : ""}</div>
      <div class="offer-card-body">
        <div class="offer-name-row">
          <strong>${escapeHtml(offer.supplier)}</strong>
          <span class="tag-pill ${offer.verified ? "verified" : ""}">${isDemo ? (offer.verified ? "Sample flag" : "Sample listing") : (offer.verified ? "Marked verified" : "Listing only")}</span>
        </div>
        <div class="offer-sub"><span>${escapeHtml(offer.location || "Location not listed")}</span><span>${isDemo ? "Sample rating" : "Rating"} ${Number(offer.rating || 0).toFixed(1)} · ${Number(offer.reviews || 0)} ${isDemo ? "sample reviews" : "reviews"}</span>${movementText ? `<span>${escapeHtml(movementText)}</span>` : ""}</div>
        <div class="offer-price"><strong>${money(offer.landed_cost)}</strong><small>landed total · ${money(offer.unit_price)}/${escapeHtml(offer.unit || "unit")}</small></div>
        <div class="offer-card-facts"><span><small>Delivery</small><strong>${Number(offer.lead_time_days || 0)} days</strong></span><span><small>Minimum</small><strong>${escapeHtml(offer.moq_label || `${Number(offer.moq_units || 0)} units`)}</strong></span></div>
      </div>
      ${renderRankingTrace(offer, rankingMethod)}
      <div class="offer-foot">
        <a class="evidence-link" href="${escapeHtml(apiUrl(offer.source_url || "#"))}" target="_blank" rel="noreferrer noopener">Evidence record${ICON.external}</a>
        <button class="evidence-link inline-action" type="button" data-action="quote" data-task="${escapeHtml(taskId || "")}" data-offer="${escapeHtml(offer.id)}">Draft quote</button>
        <button class="evidence-link inline-action" type="button" data-action="watch" data-task="${escapeHtml(taskId || "")}" data-offer="${escapeHtml(offer.id)}">Watch</button>
        <span class="offer-note">${isDemo ? "Sample fields · " : ""}${escapeHtml(offer.certifications?.length ? offer.certifications.join(" · ") : "No certifications listed")}</span>
      </div>
    </article>`;
}

function renderRankingTrace(offer, rankingMethod) {
  const breakdown = offer.score_breakdown || {};
  const components = breakdown.components || {};
  if (!Object.keys(components).length) {
    return `<div class="offer-ranking ranking-unavailable">Ranking breakdown was not saved for this earlier run.</div>`;
  }
  const labels = {
    landed_cost: "Landed cost",
    lead_time: "Delivery time",
    rating: "Rating",
    minimum_order: "Minimum order",
    verification: "Documentation",
  };
  const weights = rankingMethod.weights || {};
  const weightDescription = Object.entries(labels).map(([key, label]) => `${Math.round(Number(weights[key] || 0) * 100)}% ${label.toLowerCase()}`).join(", ");
  const rows = Object.entries(labels).map(([key, label]) => `
    <div class="ranking-row"><span>${label}</span><strong>${(Number(components[key] || 0) * 100).toFixed(1)} pts</strong></div>
  `).join("");
  const digest = offer.evidence?.record_sha256 || "";
  return `
    <details class="offer-ranking">
      <summary>Why rank #${Number(offer.rank || 0)}? <span>Score ${Number(offer.score || 0).toFixed(4)} · lower is better</span></summary>
      <div class="ranking-content">
        <div class="ranking-rows">${rows}<div class="ranking-row ranking-total"><span>Total penalty</span><strong>${(Number(breakdown.total_penalty || offer.score || 0) * 100).toFixed(1)} pts</strong></div></div>
        <p>Weighted comparison: ${escapeHtml(weightDescription)}. Values are normalized within this result set.</p>
        ${digest ? `<div class="evidence-digest"><span>Offer record SHA-256</span><code title="${escapeHtml(digest)}">${escapeHtml(digest)}</code><small>Integrity digest of this result’s offer fields and ranking inputs; it does not authenticate the supplier.</small></div>` : ""}
      </div>
    </details>`;
}

function renderReceipt(receipt) {
  if (!receipt) return "";
  const isolated = ["docker", "bubblewrap", "macos-seatbelt"].includes(receipt.mode);
  const heading = isolated ? "Execution receipt" : "Execution receipt · process isolation unavailable";
  const modeLabel = receipt.mode === "macos-seatbelt" ? "macOS Seatbelt" : receipt.mode === "docker" ? "Docker" : receipt.mode === "bubblewrap" ? "Bubblewrap" : receipt.mode || "worker";
  return `
    <details class="run-receipt${isolated ? "" : " is-unisolated"}">
      <summary><span class="receipt-summary-copy"><strong>${escapeHtml(heading)}</strong><small>${escapeHtml(modeLabel)} · ${Number(receipt.duration_ms || 0)} ms · ${Number(receipt.exit_code) === 0 ? "finished successfully" : "run stopped or failed"}</small></span><span class="receipt-disclosure">View details</span></summary>
      <p class="receipt-explainer">This is a technical record of the temporary worker that handled this task. It records the isolation mode, access limits, and cleanup result.</p>
      <div class="receipt-grid">
        <div><span>Run reference</span><strong title="Unique reference for tracing this worker run. It is not a credential.">${escapeHtml(receipt.worker_id || "—")}</strong><small>Unique trace ID, not a secret or access key.</small></div>
        <div><span>Result</span><strong>${Number(receipt.exit_code) === 0 ? "Completed successfully" : escapeHtml(receipt.exit_code ?? "—")}</strong></div>
        <div><span>Started</span><strong>${escapeHtml(receipt.started_at || "—")}</strong></div>
        <div><span>Isolation</span><strong>${escapeHtml(modeLabel)}</strong></div>
        <div><span>Network policy</span><strong>${escapeHtml(receipt.network || "—")}</strong></div>
        <div><span>Filesystem</span><strong>${escapeHtml(receipt.filesystem || "—")}</strong></div>
        <div><span>Limits</span><strong>${escapeHtml(receipt.limits || "—")}</strong></div>
        <div><span>Secrets</span><strong>${escapeHtml(receipt.secrets_policy || "—")}</strong></div>
        <div><span>Teardown</span><strong>${escapeHtml(receipt.teardown || "—")}</strong></div>
      </div>
    </details>`;
}

function renderMessages() {
  const container = $("#messages");
  container.innerHTML = state.messages.map((message, index) => renderMessage(message, index)).join("");
  $("#welcome").hidden = state.messages.length > 0;
  syncAgentRun();
  syncSend();
}

function syncAgentRun() {
  const loading = [...state.messages].reverse().find((message) => message.kind === "loading");
  const latestAssistant = [...state.messages].reverse().find((message) => message.role === "assistant");
  const status = $("#agent-run-status");
  const caption = $("#agent-run-caption");
  const steps = $$("#agent-steps li");
  if (!status || !caption || !steps.length) return;

  let activeStep = -1;
  if (loading) {
    const stage = String(loading.stage || "").toLowerCase();
    activeStep = stage.includes("queued") || stage.includes("starting") ? 0 : stage.includes("captur") ? 1 : stage.includes("compar") || stage.includes("ready") ? 3 : 2;
    status.textContent = "Running";
    status.className = "agent-run-status is-running";
    caption.textContent = loading.stage || "Working through the bundled supplier catalog.";
  } else if (latestAssistant?.kind === "research") {
    activeStep = steps.length;
    status.textContent = "Complete";
    status.className = "agent-run-status is-complete";
    caption.textContent = "Evidence attached. Review the comparison before taking action.";
  } else if (latestAssistant?.kind === "clarification") {
    activeStep = 0;
    status.textContent = "Needs detail";
    status.className = "agent-run-status is-waiting";
    caption.textContent = "Waiting for the order quantity before the comparison can start.";
  } else {
    status.textContent = "Ready";
    status.className = "agent-run-status";
    caption.textContent = "Start a request to see its progress here.";
  }

  steps.forEach((step, index) => {
    step.classList.toggle("is-done", index < activeStep);
    step.classList.toggle("is-active", index === activeStep);
  });
  syncAgentDecision(latestAssistant);
}

function syncAgentDecision(message) {
  const panel = $("#agent-decision");
  const research = message?.kind === "research" ? message.research || {} : null;
  const offers = Array.isArray(research?.offers) ? research.offers : [];
  const best = offers.find((offer) => offer.id === research?.best_value_id) || offers[0];
  if (!panel || !best) {
    if (panel) panel.hidden = true;
    return;
  }

  const cheapest = offers.find((offer) => offer.id === research.cheapest_id) || best;
  const fastest = offers.find((offer) => offer.id === research.fastest_id) || best;
  const isDemo = Boolean(research.index?.is_demo);
  let tradeoff = "Compare the offer details and evidence before creating a draft.";
  if (cheapest.id !== best.id) {
    tradeoff = `${cheapest.supplier} has a lower sample landed cost by ${money(Math.max(0, Number(best.landed_cost) - Number(cheapest.landed_cost)))}.`;
  } else if (fastest.id !== best.id) {
    tradeoff = `${fastest.supplier} has the shortest listed lead time at ${Number(fastest.lead_time_days || 0)} days.`;
  }
  $("#agent-decision-kind").textContent = isDemo ? "Sample data" : "Current comparison";
  $("#agent-decision-product").textContent = `${research.product?.name || "Supplier comparison"} · ${research.quantity?.quantity_label || "Requested quantity"}`;
  $("#agent-decision-content").innerHTML = `
    <div class="agent-decision-offer">
      <strong>${escapeHtml(best.supplier || "Top-ranked offer")}</strong>
      <span class="agent-decision-price">${money(best.landed_cost)} landed</span>
      <span class="agent-decision-meta">${Number(best.lead_time_days || 0)} days · ${escapeHtml(best.moq_label || `${best.moq_units || 0} units`)} minimum · ${offers.length} ${isDemo ? "sample offers" : "offers"}</span>
    </div>
    <p class="agent-decision-tradeoff">${escapeHtml(tradeoff)}</p>
    ${isDemo ? '<p class="agent-decision-tradeoff">Illustrative values only. Confirm current price, stock, and documents directly with a supplier.</p>' : ""}`;
  panel.hidden = false;
}

function syncAgentPanel() {
  const shell = $("#app-shell");
  const compact = window.matchMedia("(max-width: 1180px)").matches;
  shell.classList.toggle("agent-panel-collapsed", !state.agentPanelOpen);
  $("#agent-panel").inert = !state.agentPanelOpen || state.view !== "assistant";
  $("#agent-panel-toggle").setAttribute("aria-expanded", String(state.agentPanelOpen));
  const action = state.agentPanelOpen ? "Collapse" : "Expand";
  $("#agent-panel-toggle").setAttribute("aria-label", `${action} procurement panel`);
  $("#agent-panel-toggle").title = `${action} procurement panel`;
  document.body.classList.toggle("agent-panel-open", compact && state.agentPanelOpen);
}

function syncNavPanel() {
  const shell = $("#app-shell");
  const toggle = $("#sidebar-panel-toggle");
  const mobile = window.matchMedia("(max-width: 860px)").matches;
  const isOpen = mobile ? document.body.classList.contains("sidebar-open") : state.navPanelOpen;
  shell.classList.toggle("nav-panel-collapsed", !mobile && !state.navPanelOpen);
  $("#sidebar").inert = mobile ? !document.body.classList.contains("sidebar-open") : false;
  toggle.setAttribute("aria-expanded", String(isOpen));
  const action = isOpen ? "Collapse" : "Expand";
  toggle.setAttribute("aria-label", `${action} navigation`);
  toggle.title = `${action} navigation`;
}

function toggleNavPanel() {
  if (window.matchMedia("(max-width: 860px)").matches) {
    document.body.classList.contains("sidebar-open") ? closeSidebar() : openSidebar();
    return;
  }
  state.navPanelOpen = !state.navPanelOpen;
  try { localStorage.setItem("taskvault-nav-panel-open", String(state.navPanelOpen)); } catch { /* Storage can be disabled. */ }
  syncNavPanel();
}

function toggleAgentPanel() {
  const compact = window.matchMedia("(max-width: 1180px)").matches;
  if (compact && !state.agentPanelOpen && document.body.classList.contains("sidebar-open")) closeSidebar();
  state.agentPanelOpen = !state.agentPanelOpen;
  try { localStorage.setItem("taskvault-agent-panel-open", String(state.agentPanelOpen)); } catch { /* Storage can be disabled. */ }
  syncAgentPanel();
}

function closeAgentPanel() {
  state.agentPanelOpen = false;
  try { localStorage.setItem("taskvault-agent-panel-open", "false"); } catch { /* Storage can be disabled. */ }
  syncAgentPanel();
}

function findOffer(taskId, offerId) {
  for (const message of state.messages) {
    if (message.kind !== "research" || String(message.taskId) !== String(taskId)) continue;
    const offers = message.research?.offers || [];
    const found = offers.find((offer) => String(offer.id) === String(offerId));
    if (found) return found;
  }
  return null;
}

async function sendPrompt(raw) {
  const text = String(raw || "").trim();
  if (!text || state.busy) return false;
  const sources = state.sources.slice();
  const history = state.messages
    .filter((message) => message.role === "user" || ["text", "research", "clarification"].includes(message.kind))
    .slice(-12)
    .map((message) => ({
      role: message.role,
      content: message.role === "user" ? message.text : message.kind === "clarification"
        ? message.text || message.clarification?.prompt || ""
        : message.kind === "research"
        ? JSON.stringify({
            summary: message.research?.summary,
            recommendation: message.research?.recommendation,
            product: message.research?.product,
            quantity: message.research?.quantity,
            offers: (message.research?.offers || []).map((offer) => ({
              supplier: offer.supplier,
              landed_cost: offer.landed_cost,
              unit_price: offer.unit_price,
              unit: offer.unit,
              moq_label: offer.moq_label,
              lead_time_days: offer.lead_time_days,
              source_url: offer.source_url,
            })),
            is_demo: Boolean(message.research?.index?.is_demo),
          })
        : message.text || "",
    }))
    .filter((message) => message.content);

  state.busy = true;
  state.sources = [];
  renderSources();
  state.messages.push({ role: "user", text, sources });
  const loading = { role: "assistant", kind: "loading", stage: "Starting a bounded sourcing run", taskId: null };
  state.messages.push(loading);
  $("#prompt").value = "";
  autoGrow();
  renderMessages();
  scrollToBottom(true);

  try {
    const data = await request("/api/chat", {
      method: "POST",
      body: { message: text, history, sources, conversation_id: state.conversationId },
    });
    if (data.conversation_id && data.conversation_id !== state.conversationId) {
      state.conversationId = data.conversation_id;
      try { localStorage.setItem("taskvault-conversation-id", state.conversationId); } catch { /* Storage can be disabled. */ }
    }
    state.conversationStarted = true;
    try { localStorage.setItem("taskvault-conversation-started", "true"); } catch { /* Storage can be disabled. */ }
    if (data.intent === "research") {
      loading.taskId = data.task_id;
      loading.stage = data.stage || "Preparing the sourcing worker";
      state.activeTaskId = data.task_id;
      state.recentCleared = false;
      renderMessages();
      scrollToBottom(true);
      await pollTask(data.task_id, loading);
      return true;
    }
    state.messages = state.messages.filter((message) => message !== loading);
    if (data.clarification) {
      state.messages.push({ role: "assistant", kind: "clarification", text: data.answer, clarification: data.clarification });
      state.activeTaskId = null;
      renderMessages();
      finishBusy();
      scrollToLastMessage();
      openBriefDialog(data.clarification);
      return true;
    }
    state.messages.push({ role: "assistant", kind: "text", text: data.answer, links: data.sources || [] });
    state.activeTaskId = data.task_id || null;
    renderMessages();
    finishBusy();
    scrollToLastMessage();
    return true;
  } catch (error) {
    state.messages = state.messages.filter((message) => message !== loading);
    if (error.data?.conversation_id) {
      state.conversationId = error.data.conversation_id;
      try { localStorage.setItem("taskvault-conversation-id", state.conversationId); } catch { /* Storage can be disabled. */ }
      state.conversationStarted = true;
      try { localStorage.setItem("taskvault-conversation-started", "true"); } catch { /* Storage can be disabled. */ }
    }
    state.messages.push({
      role: "assistant",
      kind: "text",
      text: error.code === "inference_not_configured"
        ? "Assistant replies need a configured model endpoint. Your message is saved in this conversation."
        : error.message,
      taskId: error.data?.task_id,
    });
    renderMessages();
    finishBusy();
    if (!state.voiceActive) showNotice("The request did not complete", error.message);
    return false;
  }
}

async function pollTask(taskId, loading) {
  const token = ++state.pollToken;
  let failures = 0;
  while (state.pollToken === token) {
    await sleep(900);
    if (state.pollToken !== token) return;
    try {
      const data = await request(`/api/tasks/${taskId}`);
      if (state.pollToken !== token) return;
      if (data.status === "completed") {
        state.messages = state.messages.filter((message) => message !== loading);
        if (data.research) {
          data.research.task_id = taskId;
          state.messages.push({
            role: "assistant",
            kind: "research",
            research: data.research,
            sandbox: data.sandbox,
            taskId,
          });
        } else {
          state.messages.push({
            role: "assistant",
            kind: "text",
            text: data.summary || "The sourcing run completed.",
          });
        }
        state.activeTaskId = taskId;
        renderMessages();
        scrollToLastMessage();
        finishBusy();
        return;
      }
      if (data.status === "failed" || data.status === "stopped") {
        state.messages = state.messages.filter((message) => message !== loading);
        renderMessages();
        state.messages.push({
          role: "assistant",
          kind: "text",
          text: data.status === "stopped" ? "The sourcing run was stopped before evidence was stored." : "The sourcing run failed before evidence was stored.",
        });
        finishBusy();
        showNotice(
          data.status === "stopped" ? "Run stopped" : "Sourcing run failed",
          data.error || "No comparison was stored. Try the request again or check the activity ledger."
        );
        return;
      }
      loading.stage = data.stage || "Preparing the sourcing worker";
      renderMessages();
      scrollToBottom();
    } catch (error) {
      failures += 1;
      if (failures >= 3) {
        state.messages = state.messages.filter((message) => message !== loading);
        renderMessages();
        finishBusy();
        showNotice("Could not read the run", error.message);
        return;
      }
    }
  }
}

function finishBusy() {
  state.busy = false;
  state.recentCleared = false;
  syncSend();
  refreshBadges();
}

function newChat() {
  state.pollToken += 1;
  state.busy = false;
  state.messages = [];
  state.conversationId = crypto.randomUUID();
  try { localStorage.setItem("taskvault-conversation-id", state.conversationId); } catch { /* Storage can be disabled. */ }
  state.conversationStarted = false;
  try { localStorage.setItem("taskvault-conversation-started", "false"); } catch { /* Storage can be disabled. */ }
  state.sources = [];
  state.activeTaskId = null;
  state.brief = null;
  closeModal("brief-dialog");
  $("#prompt").value = "";
  renderSources();
  renderMessages();
  autoGrow();
  setView("assistant");
  closeSidebar();
  $("#prompt").focus();
}

async function restoreConversation() {
  if (!state.conversationStarted) return false;
  try {
    const { conversation } = await request(`/api/conversations/${state.conversationId}`);
    state.messages = (conversation.messages || []).map((message) => {
      const content = message.content || {};
      if (message.role === "user") {
        return { role: "user", text: content.text || "", sources: content.sources || [], taskId: message.task_id };
      }
      if (message.kind === "research") {
        return { role: "assistant", kind: "research", research: content.research, sandbox: content.sandbox, taskId: message.task_id };
      }
      return { role: "assistant", kind: message.kind === "error" ? "text" : message.kind, text: content.text || "", links: content.links || [], taskId: message.task_id };
    });
    state.activeTaskId = [...state.messages].reverse().find((message) => message.taskId)?.taskId || null;
    state.recentCleared = false;
    renderMessages();
    const lastUser = [...state.messages].reverse().find((message) => message.role === "user" && message.taskId);
    const hasReply = lastUser && state.messages.some((message) => message.role === "assistant" && message.taskId === lastUser.taskId);
    if (lastUser && !hasReply) {
      const data = await request(`/api/tasks/${lastUser.taskId}`);
      if (data.status === "running") {
        const loading = { role: "assistant", kind: "loading", stage: data.stage || "Resuming the sourcing run", taskId: data.id };
        state.messages.push(loading);
        state.busy = true;
        renderMessages();
        await pollTask(data.id, loading);
      } else if (data.status === "completed" && data.research) {
        data.research.task_id = data.id;
        state.messages.push({ role: "assistant", kind: "research", research: data.research, sandbox: data.sandbox, taskId: data.id });
        renderMessages();
      } else if (data.status === "failed" || data.status === "stopped") {
        state.messages.push({ role: "assistant", kind: "text", text: data.error || "This task ended before a comparison was saved.", taskId: data.id });
        renderMessages();
      }
    }
    return true;
  } catch (error) {
    if (error.status !== 404) console.warn("Could not restore this conversation:", error.message);
    return false;
  }
}

function setView(view) {
  if (!VIEW_META[view]) return;
  state.view = view;
  $$(".nav-item").forEach((item) => {
    const active = item.dataset.view === view;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  $("#topbar-title").textContent = VIEW_META[view].title;
  $("#view-assistant").hidden = view !== "assistant";
  $("#view-utility").hidden = view === "assistant";
  $("#agent-panel").hidden = view !== "assistant";
  $("#agent-panel-toggle").hidden = view !== "assistant";
  const utilityAction = $("#utility-action");
  if (view === "connections") {
    utilityAction.hidden = true;
  } else {
    utilityAction.hidden = false;
    utilityAction.innerHTML =
      view === "tasks" || view === "activity"
        ? `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>Start research</span>`
        : `<span>Open assistant</span>`;
    state.utilityAction = ["tasks", "activity"].includes(view) ? newChat : () => setView("assistant");
  }
  if (view !== "assistant") {
    $("#utility-kicker").textContent = VIEW_META[view].kicker;
    $("#utility-title").textContent = VIEW_META[view].heading;
    $("#utility-description").textContent = VIEW_META[view].description;
    renderUtilityView(view);
  } else {
    scrollToBottom();
  }
  if (window.matchMedia("(max-width: 1180px)").matches && view !== "assistant" && state.agentPanelOpen) {
    state.agentPanelOpen = false;
    try { localStorage.setItem("taskvault-agent-panel-open", "false"); } catch { /* Storage can be disabled. */ }
    syncAgentPanel();
  }
  closeSidebar();
}

function utilityLoading(title = "Loading", description = "Reading the workspace ledger.") {
  $("#utility-content").innerHTML = `<div class="empty-state"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(description)}</p></div>`;
}

function utilityError(title, description, retryView) {
  $("#utility-content").innerHTML = `
    <div class="empty-state">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(description)}</p>
      <button class="quiet-button" type="button" data-retry-view="${escapeHtml(retryView)}">Try again</button>
    </div>`;
}

async function renderUtilityView(view) {
  utilityLoading();
  try {
    if (view === "tasks") return await renderTasksView();
    if (view === "watches") return await renderWatchesView();
    if (view === "approvals") return await renderApprovalsView();
    if (view === "activity") return await renderActivityView();
    if (view === "connections") return await renderConnectionsView();
  } catch (error) {
    utilityError("This view is unavailable", error.message, view);
  }
}

async function renderTasksView() {
  const data = await request("/api/tasks");
  state.tasks = data.tasks || [];
  updateCounts();
  renderRecent();
  if (!state.tasks.length) {
    $("#utility-content").innerHTML = `
      <div class="empty-state">
        <strong>No research yet</strong>
        <p>Start with a product and quantity. TaskVault will run the sourcing worker, compare offers, and keep the evidence attached.</p>
        <button class="primary-button" type="button" data-action="new">Start research</button>
      </div>`;
    return;
  }
  $("#utility-content").innerHTML = `
    <div class="utility-grid">
      ${state.tasks
        .map(
          (task) => `
        <article class="utility-card">
          <div class="utility-card-head">
            <div>
              <h2>${escapeHtml(truncate(task.query, 120))}</h2>
              <p>${escapeHtml(task.summary ? truncate(task.summary, 260) : "No summary stored for this run.")}</p>
            </div>
            <span class="status-pill ${escapeHtml(task.status)}">${escapeHtml(titleCase(task.status))}</span>
          </div>
          <div class="meta">
            <span><strong>${escapeHtml(titleCase(task.intent || "chat"))}</strong></span>
            <span>Updated ${escapeHtml(formatDate(task.updated_at))}</span>
            <span>${task.research?.offers?.length || 0} offers</span>
          </div>
          <div class="utility-actions">
            <button class="quiet-button" type="button" data-action="open-task" data-task="${escapeHtml(task.id)}">Open</button>
          </div>
        </article>`
        )
        .join("")}
    </div>`;
}

async function renderWatchesView() {
  const data = await request("/api/watches");
  state.watches = data.watches || [];
  updateCounts();
  if (!state.watches.length) {
    $("#utility-content").innerHTML = `
      <div class="empty-state">
        <strong>No price watches yet</strong>
        <p>Run a comparison, then choose Watch on a supplier offer. The watch checks the stored evidence record and never scrapes a logged-in session.</p>
        <button class="primary-button" type="button" data-action="new">Open assistant</button>
      </div>`;
    return;
  }
  $("#utility-content").innerHTML = `
    <div class="utility-grid">
      ${state.watches
        .map(
          (watch) => `
        <article class="utility-card">
          <div class="utility-card-head">
            <div>
              <h2>${escapeHtml(watch.supplier)}</h2>
              <p>${escapeHtml(watch.product)} · target ${money(watch.target_price)} per unit</p>
            </div>
            <span class="status-pill ${escapeHtml(watch.status)}">${escapeHtml(titleCase(watch.status))}</span>
          </div>
          <div class="meta">
            <span>Current <strong>${money(watch.current_price)}</strong></span>
            <span>Checked ${escapeHtml(formatDate(watch.last_checked_at))}</span>
            <span>${escapeHtml(watch.last_result?.message || "Waiting for the next check.")}</span>
          </div>
          <div class="utility-actions">
            <button class="quiet-button" type="button" data-action="check-watch" data-watch="${escapeHtml(watch.id)}">Check now</button>
            ${watch.task_id ? `<button class="quiet-button" type="button" data-action="open-task" data-task="${escapeHtml(watch.task_id)}">Open comparison</button>` : ""}
          </div>
        </article>`
        )
        .join("")}
    </div>`;
}

async function renderApprovalsView() {
  const data = await request("/api/approvals");
  state.approvals = data.approvals || [];
  updateCounts();
  if (!state.approvals.length) {
    $("#utility-content").innerHTML = `
      <div class="empty-state">
        <strong>No drafts awaiting review</strong>
        <p>Quote requests and purchase orders become drafts here. They are never sent or paid automatically.</p>
        <button class="primary-button" type="button" data-action="new">Open assistant</button>
      </div>`;
    return;
  }
  $("#utility-content").innerHTML = `
    <div class="utility-grid">
      ${state.approvals
        .map(
          (approval) => `
        <article class="utility-card">
          <div class="utility-card-head">
            <div>
              <h2>${escapeHtml(approval.title)}</h2>
              <p>${escapeHtml(truncate(approval.body, 230))}</p>
            </div>
            <span class="status-pill ${escapeHtml(approval.status)}">${escapeHtml(titleCase(approval.status))}</span>
          </div>
          <div class="meta">
            <span><strong>${escapeHtml(approval.kind === "purchase_order" ? "Purchase order" : "Quote request")}</strong></span>
            ${approval.amount ? `<span>Amount <strong>${money(approval.amount)}</strong></span>` : ""}
            <span>Created ${escapeHtml(formatDate(approval.created_at))}</span>
          </div>
          <div class="utility-actions">
            <button class="quiet-button" type="button" data-action="review-approval" data-approval="${escapeHtml(approval.id)}">Review draft</button>
            ${
              approval.status === "pending"
                ? `<button class="quiet-button" type="button" data-action="approve-approval" data-approval="${escapeHtml(approval.id)}">Approve</button>
                   <button class="quiet-button" type="button" data-action="reject-approval" data-approval="${escapeHtml(approval.id)}">Reject</button>`
                : ""
            }
          </div>
        </article>`
        )
        .join("")}
    </div>`;
}

async function renderActivityView() {
  const data = await request("/api/activity");
  const events = data.events || [];
  const valid = data.audit_chain_valid;
  if (!events.length) {
    $("#utility-content").innerHTML = `<div class="empty-state"><strong>No activity yet</strong><p>When you start a sourcing run, TaskVault will record its progress, saved evidence, and any approval decisions here.</p></div>`;
    return;
  }
  const integrityTitle = valid ? "Integrity check passed" : "Integrity check failed";
  const integrityDescription = valid
    ? "TaskVault checked the saved activity records for unexpected changes."
    : "Some activity records may have changed. Ask your system administrator to review them before relying on this history.";
  $("#utility-content").innerHTML = `
    <section class="ledger-note ${valid ? "" : "is-invalid"}" aria-label="Activity record integrity">
      <div><strong>${integrityTitle}</strong><p>${integrityDescription}</p></div>
      <span class="ledger-count">${events.length} recent record${events.length === 1 ? "" : "s"} · newest first</span>
      <details class="integrity-details">
        <summary>About this check</summary>
        <p>TaskVault links each event to the previous one so unexpected edits can be detected. Someone with direct database access could still rewrite the full history.</p>
      </details>
    </section>
    <div class="activity-list">
      ${events
        .map(
          (event) => {
            const { title, description } = describeActivityEvent(event, state.health?.catalog?.is_demo);
            return `
        <article class="activity-row">
          <div class="activity-kind">
            <strong>${escapeHtml(title)}</strong>
            <details class="activity-technical"><summary>Event details</summary><code>${escapeHtml(event.kind)}</code></details>
          </div>
          <p>${escapeHtml(description)}</p>
          <time datetime="${escapeHtml(event.created_at || "")}">${escapeHtml(formatDate(event.created_at))}</time>
        </article>`;
          }
        )
        .join("")}
    </div>`;
}

function describeActivityEvent(event, isDemo) {
  const message = String(event.message || "");
  const kind = String(event.kind || "");
  const count = message.match(/(\d+)\s+(?:supplier listings|offers)/i)?.[1];
  const quantity = message.match(/accepted for (.+?)\.?$/i)?.[1];
  const labels = {
    "task.created": ["Request recorded", "Saved your sourcing request as a task."],
    "research.queued": ["Sourcing started", quantity ? `Started a sourcing run for ${quantity}.` : "Started a sourcing run."],
    "task.updated": ["Run in progress", "The sourcing worker is preparing your comparison."],
    "sandbox.started": ["Comparison started", "Started the worker that prepares the supplier comparison."],
    "browser.started": ["Live capture started", "Opened the buyer-provided pages read-only through an allowlist proxy."],
    "browser.captured": ["Source pages captured", message || "Timestamped screenshots were saved as evidence."],
    "browser.empty": ["No screenshots retained", "The source capture completed without a retained screenshot; errors are attached to the task."],
    "browser.failed": ["Live capture unavailable", "The stored-field comparison completed, but buyer source pages were not opened."],
    "task.completed": ["Task completed", "The sourcing comparison is ready to review."],
    "task.failed": ["Task needs attention", "The request could not be completed. Review the task for details."],
    "task.stopped": ["Task stopped", "The sourcing run stopped before the comparison was completed."],
    "task.stop_requested": ["Stop requested", "Your request to stop the sourcing run was recorded."],
    "sandbox.stopped": ["Run stopped", "The run stopped before evidence was saved."],
    "sandbox.completed": [
      "Offers compared",
      isDemo
        ? `Compared ${count || "the available"} offers from the bundled sample catalog. No catalog supplier pages were visited.`
        : `Compared ${count || "the available"} supplier offers and saved the results.`,
    ],
    "evidence.saved": [
      "Evidence attached",
      isDemo
        ? `Linked ${count || "the available"} sample offer records to this comparison. These are not live supplier quotes; buyer source captures are stored separately.`
        : `Saved source records for ${count || "the available"} supplier offers.`,
    ],
    "watch.created": ["Price watch added", message.replace(/^Price watch created for /i, "Added a price watch for ").replace(/\.$/, ".")],
    "watch.checked": ["Price watch checked", message],
    "approval.requested": ["Draft ready for review", message.replace(/^Human approval requested: /i, "Created a draft for ").replace(/\.$/, ".")],
    "approval.decided": ["Approval decision recorded", message.replace(/^Human decision recorded: /i, "Recorded your decision on ").replace(/\.$/, ".")],
  };
  const [title, description] = labels[kind] || ["Activity recorded", message || "Task activity was saved."];
  return { title, description };
}

async function renderConnectionsView() {
  const [profileData, health] = await Promise.all([
    request("/api/profile"),
    request("/api/health").catch(() => state.health),
  ]);
  applyProfile(profileData.profile);
  state.health = health || state.health;
  setSandboxState(state.health);
  const profile = state.profile;
  const catalog = state.health?.catalog || {};
  const inferencePolicy = state.health?.inference_policy || {};
  const workerMode = state.health?.sandbox_mode;
  const workerModeLabel = workerMode === "macos-seatbelt"
    ? "macOS Seatbelt"
    : workerMode === "docker"
      ? "Docker container"
      : workerMode === "process"
        ? "Process fallback"
        : "Unknown";
  const config = `{
  "mcpServers": {
    "taskvault": {
      "command": "python3",
      "args": ["mcp_server.py"]
    }
  }
}`;
  $("#utility-content").innerHTML = `
    <div class="utility-grid" style="gap:16px">
      <section class="utility-card">
        <div class="utility-card-head">
            <div><h2>Buyer profile</h2><p>Used to prefill quote and purchase-order drafts. No card numbers are collected or stored.</p></div>
        </div>
        <form id="profile-form">
          <div class="form-grid">
            <div class="field"><label for="p-company">Company</label><input id="p-company" name="company" maxlength="200" value="${escapeHtml(profile.company || "")}" placeholder="Northstar Supply"></div>
            <div class="field"><label for="p-name">Buyer name</label><input id="p-name" name="buyer_name" maxlength="200" value="${escapeHtml(profile.buyer_name || "")}" placeholder="Alex Morgan"></div>
            <div class="field"><label for="p-email">Email</label><input id="p-email" name="email" type="email" maxlength="200" value="${escapeHtml(profile.email || "")}" placeholder="buyer@example.com"></div>
            <div class="field"><label for="p-phone">Phone</label><input id="p-phone" name="phone" maxlength="200" value="${escapeHtml(profile.phone || "")}" placeholder="+1 555 0100"></div>
            <div class="field full"><label for="p-ship">Ship-to address</label><input id="p-ship" name="ship_to" maxlength="200" value="${escapeHtml(profile.ship_to || "")}" placeholder="City, region, postal code"></div>
            <div class="field"><label for="p-budget">Budget (USD)</label><input id="p-budget" name="budget" type="number" min="0" step="1" value="${escapeHtml(profile.budget || 0)}"></div>
            <div class="field"><label for="p-threshold">Approval threshold (USD)</label><input id="p-threshold" name="approval_threshold" type="number" min="0" step="1" value="${escapeHtml(profile.approval_threshold ?? 2500)}"></div>
            <div class="field"><label for="p-payment">Payment approach</label>
              <select id="p-payment" name="payment_method">
                <option value="approval_only" ${profile.payment_method === "approval_only" ? "selected" : ""}>Approval only — safest</option>
                <option value="invoice" ${profile.payment_method === "invoice" ? "selected" : ""}>Invoice after approval</option>
                <option value="hosted_checkout" ${profile.payment_method === "hosted_checkout" ? "selected" : ""}>Hosted checkout (not connected)</option>
              </select>
            </div>
            <div class="field"><label>Safety posture</label><input value="No credentials or card data stored" disabled></div>
          </div>
          <div class="utility-actions"><button class="primary-button" type="submit">Save profile</button><span class="field-help">Saving your profile does not send anything to a supplier.</span></div>
        </form>
      </section>

      <section class="utility-card">
        <div class="utility-card-head">
          <div><h2>Service readiness</h2><p>See what is available now and what still needs setup.</p></div>
          <button class="quiet-button" type="button" data-action="refresh-connections">Refresh configuration</button>
        </div>
        <div class="connection-grid">
          <div class="connection-tile">
            <h3>Assistant replies</h3>
            <p>${state.health?.inference_configured
              ? "The server has a model, endpoint, and API key configured. This status checks configuration only, not whether the endpoint can currently respond."
              : inferencePolicy.track === "blast_radius_zero" && inferencePolicy.provider_allowed === false
                ? "Challenge 1 policy is active. The configured provider is blocked; all agent model calls must use Vultr Serverless Inference."
                : "Not connected. Sourcing can still compare the bundled sample catalog, but general assistant answers need a model endpoint."}</p>
            <span class="status-pill">${state.inferenceCheck?.verified ? `Connection verified · ${escapeHtml(state.inferenceCheck.latency_ms)} ms` : inferencePolicy.track === "blast_radius_zero" && inferencePolicy.provider_allowed === false ? "Vultr required · provider blocked" : state.health?.inference_configured ? "Configured · not tested" : "Needs setup"}</span>
            <div class="utility-actions"><button class="quiet-button" type="button" data-action="inference-check">Test model connection</button><span class="field-help">Sends one short request; provider usage may apply.</span></div>
            ${state.health?.inference_configured ? "" : `
              <details class="setup-note">
                <summary>How to enable assistant replies</summary>
                <p>On the server, set these environment variables, then restart OpsPilot. For Challenge 1, also set TASKVAULT_COMPETITION_TRACK=blast_radius_zero. Keep the API key out of this browser and the worker.</p>
                <code>VULTR_INFERENCE_URL
VULTR_INFERENCE_MODEL
VULTR_INFERENCE_API_KEY
TASKVAULT_COMPETITION_TRACK</code>
              </details>`}
          </div>
          <div class="connection-tile">
            <h3>Sourcing worker</h3>
            <p>${escapeHtml(state.health?.sandbox_mode === "docker"
              ? "Container mode: no network, read-only root, dropped capabilities."
              : state.health?.sandbox_mode === "macos-seatbelt"
                ? "macOS Seatbelt blocks networking and app database reads, and protects the project and home directories from writes. Other local paths are not comprehensively isolated. Apple marks sandbox-exec deprecated; use this for local development."
                : "Process fallback: minimal environment and resource limits, but host networking and filesystem access remain available.")}</p>
            <span class="status-pill">${escapeHtml(workerModeLabel)}</span>
            <div class="utility-actions"><button class="quiet-button" type="button" data-action="containment">Check worker isolation</button></div>
          </div>
          <div class="connection-tile">
            <h3>Supplier data</h3>
            <p>${catalog.is_demo
              ? `Sample catalog only: ${escapeHtml(catalog.offer_count || 0)} illustrative offers across ${escapeHtml(catalog.product_count || 0)} products. No live supplier pages are checked.`
              : `Supplier index loaded: ${escapeHtml(catalog.offer_count || 0)} offers across ${escapeHtml(catalog.product_count || 0)} products.`}</p>
            <span class="status-pill">${catalog.is_demo ? "Sample data" : "Index loaded"} · ${escapeHtml(catalog.version || "version unknown")}</span>
          </div>
          <div class="connection-tile">
            <h3>External actions</h3>
            <p>TaskVault does not send supplier messages, place orders, or take payments. Drafts stay here for a person to review.</p>
            <span class="status-pill">Human review required</span>
          </div>
        </div>
      </section>

      <section class="utility-card">
        <div class="utility-card-head"><div><h2>MCP server</h2><p>Expose sourcing tasks, approvals, watches, and the audit ledger to an MCP client over local stdio.</p></div><span class="status-pill">Local stdio</span></div>
        <pre class="code-block"><button class="copy-button" type="button" data-action="copy" data-copy-target="mcp-code">Copy</button><code id="mcp-code">${escapeHtml(config)}</code></pre>
        <p class="field-help">The server reads the same SQLite database and audit ledger as the web app. It never receives supplier credentials.</p>
      </section>
    </div>`;
}

async function openTask(taskId) {
  try {
    const data = await request(`/api/tasks/${taskId}`);
    const task = data.task || data;
    if (task.conversation_id) {
      state.conversationId = task.conversation_id;
      try { localStorage.setItem("taskvault-conversation-id", state.conversationId); } catch { /* Storage can be disabled. */ }
      state.conversationStarted = true;
      try { localStorage.setItem("taskvault-conversation-started", "true"); } catch { /* Storage can be disabled. */ }
      const restored = await restoreConversation();
      if (restored) {
        setView("assistant");
        return;
      }
    }
    state.pollToken += 1;
    state.busy = false;
    state.sources = [];
    state.messages = [{ role: "user", text: task.query }];
    state.activeTaskId = task.id;
    state.recentCleared = false;
    if (task.status === "running") {
      const loading = { role: "assistant", kind: "loading", stage: task.stage || "Reading the sourcing run", taskId: task.id };
      state.messages.push(loading);
      setView("assistant");
      renderMessages();
      scrollToBottom(true);
      state.busy = true;
      await pollTask(task.id, loading);
      return;
    }
    if (task.research) {
      task.research.task_id = task.id;
      state.messages.push({
        role: "assistant",
        kind: "research",
        research: task.research,
        sandbox: task.sandbox,
        taskId: task.id,
      });
    } else {
      state.messages.push({
        role: "assistant",
        kind: "text",
        text: task.error || task.result || task.summary || "No result was stored for this task.",
      });
    }
    setView("assistant");
    renderMessages();
    scrollToLastMessage();
  } catch (error) {
    showNotice("Could not open the task", error.message);
  }
}

async function openApprovalDraft(kind, taskId, offerId) {
  if (!taskId || !offerId) {
    showNotice("Choose a completed comparison", "Open a research result before creating a draft.");
    return;
  }
  try {
    if (kind === "purchase_order") {
      const offer = findOffer(taskId, offerId);
      state.orderTarget = { taskId, offerId, offer };
      $("#order-lede").textContent = offer
        ? `${offer.supplier} · ${money(offer.unit_price)} per ${offer.unit}. Minimum ${offer.moq_units} units.`
        : "Choose a quantity. The server calculates the draft totals.";
      $("#order-quantity").value = String(offer?.order_units || offer?.moq_units || 1);
      openModal("order-dialog");
      return;
    }
    const data = await request("/api/approvals", {
      method: "POST",
      body: { task_id: taskId, offer_id: offerId, kind: "quote_request" },
    });
    showDraft(data.approval);
  } catch (error) {
    showNotice("Could not create the draft", error.message);
  }
}

async function createOrder() {
  const target = state.orderTarget;
  if (!target) return;
  const quantity = Number($("#order-quantity").value);
  if (!Number.isInteger(quantity) || quantity < 1) {
    showNotice("Choose a valid quantity", "The order quantity must be a whole number of at least one.");
    return;
  }
  try {
    const data = await request("/api/approvals", {
      method: "POST",
      body: {
        task_id: target.taskId,
        offer_id: target.offerId,
        kind: "purchase_order",
        quantity,
      },
    });
    closeModal("order-dialog");
    showDraft(data.approval);
  } catch (error) {
    showNotice("Could not create the draft", error.message);
  }
}

function showDraft(approval) {
  if (!approval) return;
  state.draftApproval = approval;
  const pending = approval.status === "pending";
  $("#draft-kicker").textContent = approval.kind === "purchase_order" ? "Purchase order" : "Quote request";
  $("#draft-title").textContent = approval.title;
  $("#draft-content").innerHTML = `
    <div class="draft-meta">
      <span>Status <strong>${escapeHtml(titleCase(approval.status))}</strong></span>
      ${approval.amount ? `<span>Amount <strong>${money(approval.amount)}</strong></span>` : ""}
      <span>Created ${escapeHtml(formatDate(approval.created_at))}</span>
    </div>
    <pre class="draft-body">${escapeHtml(approval.body)}</pre>
    <p class="draft-note">Approval records a human decision in the audit ledger. It does not send the message, place the order, or take a payment. Confirm the supplier evidence before acting outside TaskVault.</p>`;
  const button = $("#approve-draft");
  button.textContent = pending ? "Approve draft" : "Already decided";
  button.disabled = !pending;
  openModal("draft-dialog");
}

async function approveDraft() {
  const approval = state.draftApproval;
  if (!approval || approval.status !== "pending") return;
  try {
    await request(`/api/approvals/${approval.id}/decision`, {
      method: "POST",
      body: { decision: "approved" },
    });
    closeModal("draft-dialog");
    showNotice(
      "Approval recorded",
      "The draft is now approved in the audit ledger. No message was sent and no order or payment was made."
    );
    await Promise.all([refreshBadges(), state.view === "approvals" ? renderApprovalsView() : Promise.resolve()]);
  } catch (error) {
    showNotice("Could not record the approval", error.message);
  }
}

async function decideApproval(approvalId, decision) {
  try {
    await request(`/api/approvals/${approvalId}/decision`, {
      method: "POST",
      body: { decision },
    });
    showNotice(
      decision === "approved" ? "Approval recorded" : "Draft rejected",
      decision === "approved"
        ? "No message was sent and no order or payment was made."
        : "The draft stays closed. Nothing was sent."
    );
    await Promise.all([refreshBadges(), renderApprovalsView()]);
  } catch (error) {
    showNotice("Could not record the decision", error.message);
  }
}

function openWatchDraft(taskId, offerId) {
  const offer = findOffer(taskId, offerId);
  if (!offer) {
    showNotice("Offer not found", "Open the completed comparison and try again.");
    return;
  }
  state.watchTarget = { taskId, offerId, offer };
  $("#watch-lede").textContent = `${offer.supplier} · ${offer.product_name || offer.product_short_name}`;
  $("#watch-target").value = (Number(offer.unit_price || 0) * 0.95).toFixed(2);
  openModal("watch-dialog");
}

async function createWatch() {
  const target = state.watchTarget;
  if (!target) return;
  const value = Number($("#watch-target").value);
  if (!Number.isFinite(value) || value <= 0) {
    showNotice("Choose a target price", "The target must be a positive number.");
    return;
  }
  try {
    const data = await request("/api/watches", {
      method: "POST",
      body: { task_id: target.taskId, offer_id: target.offerId, target_price: value },
    });
    closeModal("watch-dialog");
    showNotice(
      "Price watch created",
      `${data.watch.supplier} · target ${money(data.watch.target_price)} per ${target.offer.unit}. Check it from Price watch.`
    );
    await refreshBadges();
    if (state.view === "watches") await renderWatchesView();
  } catch (error) {
    showNotice("Could not create the watch", error.message);
  }
}

async function checkWatch(watchId) {
  try {
    const data = await request(`/api/watches/${watchId}/check`, { method: "POST", body: {} });
    const watch = data.watch;
    showNotice(
      watch.status === "triggered" ? "Price target reached" : "Watch checked",
      watch.last_result?.message || `Current price ${money(watch.current_price)}.`
    );
    await Promise.all([refreshBadges(), renderWatchesView()]);
  } catch (error) {
    showNotice("Could not check the watch", error.message);
  }
}

async function runContainmentTest() {
  try {
    const data = await request("/api/sandbox/test", { method: "POST", body: { confirm: true } });
    const result = data.result || {};
    const receipt = data.receipt || {};
    showNotice(
      result.pass ? "Containment check passed" : "Containment check needs attention",
      `${result.pass ? "No inference key, database path, or secret-named environment variable was visible to the worker." : "The worker reported a secret or database path. Stop and inspect the runtime before sourcing."}\n\nMode: ${receipt.mode || "—"}\nDuration: ${receipt.duration_ms || 0} ms\nNetwork: ${receipt.network || "—"}\nFilesystem: ${receipt.filesystem || "—"}\nSecrets: ${receipt.secrets_policy || "—"}\n\n${(result.checked || []).join("\n")}`
    );
  } catch (error) {
    showNotice("Containment test failed", error.message);
  }
}

async function checkInferenceConnection() {
  state.inferenceCheck = null;
  try {
    const result = await request("/api/inference/check", { method: "POST", body: {} });
    state.inferenceCheck = result;
    await renderConnectionsView();
    showNotice("Model connection verified", `The configured endpoint returned a valid response in ${result.latency_ms} ms.`);
  } catch (error) {
    const message = error.code === "inference_not_configured"
      ? "Add the endpoint, model name, and API key to the server environment, then restart TaskVault."
      : error.message;
    showNotice("Model connection could not be verified", message);
  }
}

async function saveProfileForm(form) {
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    const data = await request("/api/profile", { method: "POST", body: values });
    applyProfile(data.profile);
    showNotice("Profile saved", "New drafts will use this buyer profile. No card data is stored.");
    await refreshBadges();
  } catch (error) {
    showNotice("Could not save the profile", error.message);
  }
}

async function copyText(button) {
  const target = document.getElementById(button.dataset.copyTarget);
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target.textContent);
    const previous = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => {
      button.textContent = previous;
    }, 1400);
  } catch {
    showNotice("Copy unavailable", "Select the configuration text and copy it manually.");
  }
}

function addSources() {
  const input = $("#source-input");
  const error = $("#source-error");
  const lines = input.value
    .split(/\s+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const accepted = [];
  for (const line of lines) {
    try {
      const url = new URL(line);
      if (!["http:", "https:"].includes(url.protocol)) throw new Error("scheme");
      if (
        url.hostname === "localhost" ||
        url.hostname.endsWith(".local") ||
        url.hostname.endsWith(".internal") ||
        /^127\./.test(url.hostname) ||
        /^10\./.test(url.hostname) ||
        /^192\.168\./.test(url.hostname) ||
        /^169\.254\./.test(url.hostname) ||
        /^172\.(1[6-9]|2\d|3[01])\./.test(url.hostname)
      ) {
        throw new Error("private");
      }
      accepted.push(url.toString());
    } catch {
      error.hidden = false;
      return;
    }
  }
  if (!accepted.length) {
    error.hidden = false;
    return;
  }
  error.hidden = true;
  state.sources = Array.from(new Set([...state.sources, ...accepted])).slice(0, 20);
  input.value = "";
  closeModal("source-dialog");
  renderSources();
  syncSend();
  $("#prompt").focus();
}

function openSourceDialog() {
  $("#source-error").hidden = true;
  openModal("source-dialog");
}

function openBriefDialog(clarification) {
  const product = clarification?.product;
  if (!product) return;
  state.brief = clarification;
  const productImage = $("#brief-image");
  productImage.src = product.image || "./assets/taskvault-mark.svg";
  productImage.alt = "";
  $("#brief-product-name").textContent = product.name || "Sourcing request";
  $("#brief-product-meta").textContent = [product.specs, product.unit].filter(Boolean).join(" · ");
  $("#brief-question").textContent = `How many ${String(product.short_name || product.name || "units").toLowerCase()} do you need?`;
  const units = Array.isArray(clarification.units) && clarification.units.length
    ? clarification.units
    : ["boxes", "cartons", "pieces"];
  $("#brief-unit").innerHTML = units
    .map((unit) => `<option value="${escapeHtml(unit)}">${escapeHtml(unit.charAt(0).toUpperCase() + unit.slice(1))}</option>`)
    .join("");
  $("#brief-quantity").value = "";
  $("#brief-error").hidden = true;
  $("#brief-hint").textContent = "TaskVault will calculate landed cost and check the supplier minimum for this exact quantity.";
  openModal("brief-dialog");
  requestAnimationFrame(() => $("#brief-quantity").focus());
}

async function submitBrief() {
  if (!state.brief) return;
  const quantity = Number($("#brief-quantity").value);
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100000) {
    $("#brief-error").hidden = false;
    $("#brief-quantity").focus();
    return;
  }
  const unit = $("#brief-unit").value || "boxes";
  $("#brief-error").hidden = true;
  closeModal("brief-dialog");
  state.brief = null;
  await sendPrompt(`${quantity} ${unit}`);
}

function openSidebar() {
  if (window.matchMedia("(max-width: 1180px)").matches && state.agentPanelOpen) {
    state.agentPanelOpen = false;
    try { localStorage.setItem("taskvault-agent-panel-open", "false"); } catch { /* Storage can be disabled. */ }
    syncAgentPanel();
  }
  document.body.classList.add("sidebar-open");
  $("#mobile-scrim").hidden = false;
  syncNavPanel();
}

function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  $("#mobile-scrim").hidden = true;
  syncNavPanel();
}

function syncResponsivePanels() {
  const compact = window.matchMedia("(max-width: 1180px)").matches;
  if (compact && state.agentPanelOpen && !document.body.classList.contains("agent-panel-open")) {
    state.agentPanelOpen = false;
  }
  syncNavPanel();
  syncAgentPanel();
}

function startVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    showNotice(
      "Voice is unavailable in this browser",
      "This browser does not expose speech recognition. You can still type the same question in the assistant."
    );
    return;
  }
  $("#voice-overlay").hidden = false;
  state.voiceActive = true;
  $("#voice-answer").hidden = true;
  $("#voice-answer").textContent = "";
  $("#voice-links").innerHTML = "";
  $("#voice-transcript").textContent = "I’m here. Tell me what you need, or ask a follow-up about a sourcing run.";
  beginListening();
}

function beginListening() {
  if (!state.voiceActive) return;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return;
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (state.voiceRecognition) {
    try {
      state.voiceRecognition.abort();
    } catch {
      return;
    }
  }
  const overlay = $("#voice-overlay");
  overlay.classList.remove("is-speaking");
  overlay.classList.add("is-listening");
  $("#voice-state").textContent = "Listening";
  const recognition = new Recognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;
  let finalText = "";
  recognition.onresult = (event) => {
    let interim = "";
    finalText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0].transcript;
      if (event.results[index].isFinal) finalText += transcript;
      else interim += transcript;
    }
    $("#voice-transcript").textContent = finalText || interim || "Listening…";
  };
  recognition.onerror = (event) => {
    overlay.classList.remove("is-listening");
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      showNotice("Microphone permission is required", "Allow microphone access in your browser to use voice. Typed questions work everywhere.");
      endVoice();
      return;
    }
    $("#voice-state").textContent = event.error === "network"
      ? "Voice service disconnected · tap to retry"
      : "I’m still here · tap the mic to retry";
  };
  recognition.onend = () => {
    overlay.classList.remove("is-listening");
    if (state.voiceRecognition === recognition) state.voiceRecognition = null;
    if (!state.voiceActive) return;
    if (finalText.trim()) {
      askVoice(finalText.trim());
    } else {
      $("#voice-state").textContent = "Tap the mic to speak";
    }
  };
  state.voiceRecognition = recognition;
  try {
    recognition.start();
  } catch {
    $("#voice-state").textContent = "Tap the mic to speak";
  }
}

async function askVoice(question) {
  $("#voice-state").textContent = "Thinking";
  $("#voice-transcript").textContent = question;
  $("#voice-answer").hidden = false;
  $("#voice-answer").textContent = "Working through that with you…";
  try {
    const completed = await sendPrompt(question);
    if (!completed) throw new Error("I couldn’t complete that turn. Your conversation is still here; try again when ready.");
    const latest = [...state.messages].reverse().find((message) => message.role === "assistant" && message.kind !== "loading");
    const answer = latest?.kind === "research"
      ? latest.research?.summary || latest.research?.recommendation || "The sourcing comparison is ready."
      : latest?.text || "I’m ready for your next question.";
    $("#voice-answer").hidden = false;
    $("#voice-answer").textContent = answer;
    $("#voice-links").innerHTML = (latest?.links || [])
      .map((link) => `<a class="voice-link" href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer noopener">${escapeHtml(hostLabel(link.url))} evidence</a>`)
      .join("");
    speakVoice(answer);
  } catch (error) {
    $("#voice-state").textContent = "Tap the mic to try again";
    $("#voice-answer").textContent = error.message;
    if (state.voiceActive) speakVoice(error.message);
  }
}

function speakVoice(text) {
  if (!text || !window.speechSynthesis) {
    $("#voice-state").textContent = "Listening for your next thought";
    if (state.voiceActive) beginListening();
    return;
  }
  const overlay = $("#voice-overlay");
  overlay.classList.remove("is-listening");
  overlay.classList.add("is-speaking");
  $("#voice-state").textContent = "Speaking";
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.98;
  utterance.pitch = 1;
  utterance.onend = () => {
    overlay.classList.remove("is-speaking");
    if (state.voiceActive) {
      $("#voice-state").textContent = "Listening for your next thought";
      beginListening();
    }
  };
  utterance.onerror = () => {
    overlay.classList.remove("is-speaking");
    if (state.voiceActive) {
      $("#voice-state").textContent = "Tap the mic to continue";
    }
  };
  window.speechSynthesis.speak(utterance);
}

function endVoice() {
  state.voiceActive = false;
  if (state.voiceRecognition) {
    try {
      state.voiceRecognition.abort();
    } catch {
      state.voiceRecognition = null;
    }
    state.voiceRecognition = null;
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  const overlay = $("#voice-overlay");
  overlay.hidden = true;
  overlay.classList.remove("is-listening", "is-speaking");
}

function handleAction(action, element) {
  const taskId = element.dataset.task;
  const offerId = element.dataset.offer;
  if (action === "quote") return openApprovalDraft("quote_request", taskId, offerId);
  if (action === "order") return openApprovalDraft("purchase_order", taskId, offerId);
  if (action === "watch") return openWatchDraft(taskId, offerId);
  if (action === "activity") return setView("activity");
  if (action === "help") return showHelp();
  if (action === "new") return newChat();
  if (action === "open-task") return openTask(taskId);
  if (action === "check-watch") return checkWatch(element.dataset.watch);
  if (action === "review-approval") {
    const approval = state.approvals.find((item) => item.id === element.dataset.approval);
    if (approval) showDraft(approval);
    return;
  }
  if (action === "approve-approval") return decideApproval(element.dataset.approval, "approved");
  if (action === "reject-approval") return decideApproval(element.dataset.approval, "rejected");
  if (action === "containment") return runContainmentTest();
  if (action === "inference-check") return checkInferenceConnection();
  if (action === "refresh-connections") return renderConnectionsView();
  if (action === "copy") return copyText(element);
  if (action === "clarify") {
    const message = state.messages[Number(element.dataset.messageIndex)];
    if (message?.clarification) openBriefDialog(message.clarification);
    return;
  }
  if (action === "review-latest") return scrollToLastMessage();
  if (action === "retry-view") return renderUtilityView(element.dataset.retryView);
  return undefined;
}

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) {
    event.preventDefault();
    setView(nav.dataset.view);
    return;
  }
  const viewLink = event.target.closest("[data-view-link]");
  if (viewLink) {
    event.preventDefault();
    setView(viewLink.dataset.viewLink);
    return;
  }
  const close = event.target.closest("[data-close-dialog]");
  if (close) {
    const dialog = close.closest("dialog");
    if (dialog) dialog.close();
    return;
  }
  const suggestion = event.target.closest("[data-prompt]");
  if (suggestion) {
    sendPrompt(suggestion.dataset.prompt);
    return;
  }
  const briefPreset = event.target.closest("[data-brief-preset]");
  if (briefPreset) {
    $("#brief-quantity").value = briefPreset.dataset.briefPreset;
    $("#brief-error").hidden = true;
    $("#brief-quantity").focus();
    return;
  }
  const removeSource = event.target.closest("[data-remove-source]");
  if (removeSource) {
    state.sources.splice(Number(removeSource.dataset.removeSource), 1);
    renderSources();
    syncSend();
    return;
  }
  const openTaskButton = event.target.closest("[data-open-task]");
  if (openTaskButton) {
    openTask(openTaskButton.dataset.openTask);
    return;
  }
  const action = event.target.closest("[data-action]");
  if (action) {
    handleAction(action.dataset.action, action);
  }
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.id === "composer") {
    event.preventDefault();
    sendPrompt($("#prompt").value);
    return;
  }
  if (form.id === "source-form") {
    event.preventDefault();
    addSources();
    return;
  }
  if (form.id === "watch-form") {
    event.preventDefault();
    createWatch();
    return;
  }
  if (form.id === "order-form") {
    event.preventDefault();
    createOrder();
    return;
  }
  if (form.id === "brief-form") {
    event.preventDefault();
    submitBrief();
    return;
  }
  if (form.id === "profile-form") {
    event.preventDefault();
    saveProfileForm(form);
  }
});

$$("dialog").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});

$("#notice-action").addEventListener("click", () => {
  const action = state.noticeAction;
  state.noticeAction = null;
  closeModal("notice-dialog");
  if (action) action();
});

$("#approve-draft").addEventListener("click", approveDraft);
$("#new-chat").addEventListener("click", newChat);
$("#clear-recent").addEventListener("click", () => {
  state.recentCleared = true;
  renderRecent();
});
$("#attach-button").addEventListener("click", openSourceDialog);
$("#voice-button").addEventListener("click", startVoice);
$("#help-button").addEventListener("click", showHelp);
$("#topbar-profile").addEventListener("click", () => setView("connections"));
$("#menu-toggle").addEventListener("click", openSidebar);
$("#sidebar-panel-toggle").addEventListener("click", toggleNavPanel);
$("#sidebar-close").addEventListener("click", closeSidebar);
$("#mobile-scrim").addEventListener("click", closeSidebar);
$("#agent-panel-toggle").addEventListener("click", toggleAgentPanel);
$("#agent-panel-close").addEventListener("click", closeAgentPanel);
$("#agent-panel-scrim").addEventListener("click", closeAgentPanel);
$("#utility-action").addEventListener("click", () => {
  if (state.utilityAction) state.utilityAction();
});
$("#voice-close").addEventListener("click", endVoice);
$("#voice-end").addEventListener("click", endVoice);
$("#voice-mic").addEventListener("click", beginListening);
$("#prompt").addEventListener("input", () => {
  autoGrow();
  syncSend();
});
$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!$("#send-button").disabled) sendPrompt($("#prompt").value);
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    newChat();
  }
  if (event.key === "Escape" && state.voiceActive) endVoice();
  if (event.key === "Escape" && window.matchMedia("(max-width: 860px)").matches && document.body.classList.contains("sidebar-open")) closeSidebar();
  if (event.key === "Escape" && window.matchMedia("(max-width: 1180px)").matches && state.agentPanelOpen) {
    state.agentPanelOpen = false;
    try { localStorage.setItem("taskvault-agent-panel-open", "false"); } catch { /* Storage can be disabled. */ }
    syncAgentPanel();
  }
});

window.addEventListener("resize", syncResponsivePanels);
checkSignIn();
