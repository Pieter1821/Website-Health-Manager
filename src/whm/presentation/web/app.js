const PAGE_SIZE_KEY = "whm.pageSize";
const STATUS_RANK = { critical: 0, warning: 1, unknown: 2, healthy: 3 };

const state = {
  sites: [],
  customers: [],
  selectedId: null,
  detail: null,
  scanning: false,
  view: "list",
  page: 1,
  pageSize: Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25,
  statusFilter: "all",
  customerFilter: "",
  sortKey: "urgency",
  sortDir: "asc", // urgency: asc = worst first
};

const el = {
  form: document.getElementById("quick-form"),
  url: document.getElementById("url-input"),
  customer: document.getElementById("customer-input"),
  checkBtn: document.getElementById("check-btn"),
  list: document.getElementById("site-list"),
  empty: document.getElementById("empty-state"),
  status: document.getElementById("status-line"),
  search: document.getElementById("search-input"),
  viewList: document.getElementById("view-list"),
  viewDetail: document.getElementById("view-detail"),
  detailEmpty: document.getElementById("detail-empty"),
  detailBody: document.getElementById("detail-body"),
  detailName: document.getElementById("detail-name"),
  detailDomain: document.getElementById("detail-domain"),
  detailSummary: document.getElementById("detail-summary"),
  pills: document.getElementById("pill-row"),
  results: document.getElementById("panel-results"),
  history: document.getElementById("panel-history"),
  changes: document.getElementById("panel-changes"),
  toast: document.getElementById("toast"),
  toastText: document.getElementById("toast-text"),
  tipBubble: document.getElementById("tip-bubble"),
  settingsModal: document.getElementById("settings-modal"),
  settingsForm: document.getElementById("settings-form"),
  loader: document.getElementById("loader"),
  loaderMsg: document.getElementById("loader-msg"),
  loaderElapsed: document.getElementById("loader-elapsed"),
  confirmModal: document.getElementById("confirm-modal"),
  confirmTitle: document.getElementById("confirm-title"),
  confirmMsg: document.getElementById("confirm-msg"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
  confirmClose: document.getElementById("confirm-close"),
  backBtn: document.getElementById("back-btn"),
  sitesWrap: document.getElementById("sites-wrap"),
  pagination: document.getElementById("pagination"),
  paginationMeta: document.getElementById("pagination-meta"),
  paginationPages: document.getElementById("pagination-pages"),
  pagePrev: document.getElementById("page-prev"),
  pageNext: document.getElementById("page-next"),
  pageSize: document.getElementById("page-size"),
  listSummary: document.getElementById("list-summary"),
  customerFilter: document.getElementById("customer-filter"),
  listFilters: document.getElementById("list-filters"),
};

function bindInfoTips(root = document) {
  root.querySelectorAll(".info-btn").forEach((btn) => {
    if (btn.dataset.boundTip === "1") return;
    btn.dataset.boundTip = "1";
    const show = () => {
      const text = btn.getAttribute("data-tip") || "";
      if (!text || !el.tipBubble) return;
      el.tipBubble.textContent = text;
      el.tipBubble.classList.remove("hidden");
      const rect = btn.getBoundingClientRect();
      const tipW = el.tipBubble.offsetWidth;
      const left = Math.min(
        window.innerWidth - tipW - 12,
        Math.max(12, rect.left + rect.width / 2 - tipW / 2)
      );
      let top = rect.bottom + 8;
      if (top + el.tipBubble.offsetHeight > window.innerHeight - 12) {
        top = rect.top - el.tipBubble.offsetHeight - 8;
      }
      el.tipBubble.style.left = `${left}px`;
      el.tipBubble.style.top = `${top}px`;
    };
    const hide = () => el.tipBubble?.classList.add("hidden");
    btn.addEventListener("mouseenter", show);
    btn.addEventListener("focus", show);
    btn.addEventListener("mouseleave", hide);
    btn.addEventListener("blur", hide);
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (el.tipBubble.classList.contains("hidden")) show();
      else hide();
    });
  });
}

function showView(view) {
  state.view = view;
  el.viewList.classList.toggle("hidden", view !== "list");
  el.viewDetail.classList.toggle("hidden", view !== "detail");
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
  return data;
}

function toastTypeFromMessage(message, type) {
  if (type) return type;
  const m = (message || "").toLowerCase();
  if (
    m.includes("fail") ||
    m.includes("could not") ||
    m.includes("couldn’t") ||
    m.includes("couldn't") ||
    m.includes("error")
  ) {
    return "error";
  }
  if (m.includes("removed") || m.includes("saved") || m.includes("checked all")) {
    return "ok";
  }
  if (m.includes("worth a look") || m.includes("needs a fix") || m.includes("failed")) {
    return "warn";
  }
  return "info";
}

function hideToast() {
  if (!el.toast) return;
  el.toast.classList.add("hidden");
  clearTimeout(toast._t);
}

function toast(message, opts = {}) {
  if (!el.toast) return;
  const type = toastTypeFromMessage(message, opts.type);
  el.toastText.textContent = message || "";
  el.toast.className = `toast toast-${type}`;
  // Restart progress bar animation
  const bar = el.toast.querySelector(".toast-bar");
  if (bar) {
    bar.style.animation = "none";
    void bar.offsetWidth;
    bar.style.animation = "";
  }
  clearTimeout(toast._t);
  const ms = opts.duration || 3600;
  toast._t = setTimeout(hideToast, ms);
}

function askConfirm({
  title = "Please confirm",
  message = "",
  confirmLabel = "OK",
  cancelLabel = "Cancel",
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    if (!el.confirmModal) {
      resolve(window.confirm(message));
      return;
    }
    el.confirmTitle.textContent = title;
    el.confirmMsg.textContent = message;
    el.confirmOk.textContent = confirmLabel;
    el.confirmCancel.textContent = cancelLabel;
    el.confirmOk.className = danger ? "btn-danger" : "btn-primary";
    el.confirmModal.classList.remove("hidden");

    const finish = (value) => {
      el.confirmModal.classList.add("hidden");
      el.confirmOk.removeEventListener("click", onOk);
      el.confirmCancel.removeEventListener("click", onCancel);
      el.confirmClose.removeEventListener("click", onCancel);
      el.confirmModal.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onBackdrop = (event) => {
      if (event.target === el.confirmModal) finish(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        finish(false);
        return;
      }
      // Error prevention: never confirm destructive actions with Enter.
      if (event.key === "Enter" && !danger) finish(true);
    };
    el.confirmOk.addEventListener("click", onOk);
    el.confirmCancel.addEventListener("click", onCancel);
    el.confirmClose.addEventListener("click", onCancel);
    el.confirmModal.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
    // Safer default focus for destructive confirms.
    (danger ? el.confirmCancel : el.confirmOk).focus();
  });
}

function openModal(modal, focusEl) {
  if (!modal) return;
  openModal._prevFocus = document.activeElement;
  modal.classList.remove("hidden");
  const target =
    focusEl ||
    modal.querySelector(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
  if (target) target.focus();
}

function closeModal(modal) {
  if (!modal) return;
  modal.classList.add("hidden");
  const prev = openModal._prevFocus;
  if (prev && typeof prev.focus === "function") prev.focus();
  openModal._prevFocus = null;
}

function formatElapsed(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

function setProgressTitle(text) {
  const title = el.loader && el.loader.querySelector(".progress-title");
  if (title) title.textContent = text;
}

function tickLoaderElapsed() {
  if (!el.loaderElapsed || !showLoader._started) return;
  const seconds = Math.floor((Date.now() - showLoader._started) / 1000);
  el.loaderElapsed.textContent = seconds > 0 ? formatElapsed(seconds) : "";
  // After a long wait, reassure without blocking the UI.
  if (seconds >= 20) {
    setProgressTitle("Still working…");
  }
}

function showLoader(message) {
  if (!el.loader) return;
  if (message) el.loaderMsg.textContent = message;
  setProgressTitle("Working…");
  el.loader.classList.remove("hidden");
  el.loader.setAttribute("aria-busy", "true");
  document.body.classList.add("is-working");
  showLoader._started = Date.now();
  if (el.loaderElapsed) el.loaderElapsed.textContent = "";
  clearInterval(showLoader._timer);
  showLoader._timer = setInterval(tickLoaderElapsed, 1000);
}

function hideLoader() {
  if (!el.loader) return;
  el.loader.classList.add("hidden");
  el.loader.classList.remove("progress-dock-long");
  el.loader.setAttribute("aria-busy", "false");
  document.body.classList.remove("is-working");
  clearInterval(showLoader._timer);
  showLoader._started = 0;
  if (el.loaderElapsed) el.loaderElapsed.textContent = "";
}

function setStatus(text) {
  el.status.textContent = text || "";
  if (text && el.loaderMsg && !el.loader.classList.contains("hidden")) {
    el.loaderMsg.textContent = text;
  }
}

function statusClass(value) {
  return (value || "unknown").toLowerCase();
}

function statusCell(label, status, why = "") {
  const reason = why
    ? `<div class="cell-sub status-why">${escapeHtml(why)}</div>`
    : "";
  return `<td class="status-cell">
    <span class="pill ${statusClass(status)}">${escapeHtml(label || "—")}</span>
    ${reason}
  </td>`;
}

function expiryCell(status, dateLabel, daysLabel, statusLabel) {
  const date = dateLabel && dateLabel !== "—" ? dateLabel : "—";
  const tone = statusClass(status);
  const days = daysLabel
    ? `<div class="cell-sub expiry-days ${tone}">${escapeHtml(daysLabel)}</div>`
    : "";
  return `<td class="expiry-cell">
    <div class="expiry-date ${tone}">${escapeHtml(date)}</div>
    ${days}
    <div class="cell-sub"><span class="pill pill-sm ${tone}">${escapeHtml(statusLabel || "")}</span></div>
  </td>`;
}

function daysNum(value) {
  if (value === null || value === undefined || value === "") return Number.POSITIVE_INFINITY;
  const n = Number(value);
  return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
}

function compareSites(a, b) {
  const dir = state.sortDir === "desc" ? -1 : 1;
  const key = state.sortKey;
  let cmp = 0;
  if (key === "urgency") {
    const ra = STATUS_RANK[a.overall] ?? 9;
    const rb = STATUS_RANK[b.overall] ?? 9;
    cmp = ra - rb;
    if (cmp === 0) {
      cmp = Math.min(daysNum(a.ssl_expires_days_num), daysNum(a.domain_expires_days_num))
        - Math.min(daysNum(b.ssl_expires_days_num), daysNum(b.domain_expires_days_num));
    }
  } else if (key === "name") {
    cmp = String(a.display_name || "").localeCompare(String(b.display_name || ""), undefined, {
      sensitivity: "base",
    });
  } else if (key === "website") {
    cmp = (STATUS_RANK[a.website_status] ?? 9) - (STATUS_RANK[b.website_status] ?? 9);
  } else if (key === "ssl") {
    cmp = daysNum(a.ssl_expires_days_num) - daysNum(b.ssl_expires_days_num);
  } else if (key === "domain") {
    cmp = daysNum(a.domain_expires_days_num) - daysNum(b.domain_expires_days_num);
  } else if (key === "dns") {
    cmp = (STATUS_RANK[a.dns_status] ?? 9) - (STATUS_RANK[b.dns_status] ?? 9);
  } else if (key === "checked") {
    const ta = a.last_checked_at ? Date.parse(a.last_checked_at) : 0;
    const tb = b.last_checked_at ? Date.parse(b.last_checked_at) : 0;
    cmp = ta - tb;
  }
  if (cmp === 0) {
    cmp = String(a.display_name || "").localeCompare(String(b.display_name || ""), undefined, {
      sensitivity: "base",
    });
  }
  return cmp * dir;
}

function filteredSites() {
  const q = el.search.value.trim().toLowerCase();
  let items = state.sites.slice();
  if (state.statusFilter && state.statusFilter !== "all") {
    items = items.filter((s) => (s.overall || "unknown") === state.statusFilter);
  }
  if (state.customerFilter) {
    const cid = String(state.customerFilter);
    items = items.filter((s) => String(s.customer_id || "") === cid);
  }
  if (q) {
    items = items.filter((s) =>
      `${s.display_name} ${s.domain} ${s.url} ${s.customer_name || ""}`
        .toLowerCase()
        .includes(q)
    );
  }
  items.sort(compareSites);
  return items;
}

function renderSummary() {
  if (!el.listSummary) return;
  const total = state.sites.length;
  if (!total) {
    el.listSummary.textContent = "";
    return;
  }
  const counts = { critical: 0, warning: 0, healthy: 0, unknown: 0 };
  state.sites.forEach((s) => {
    const key = s.overall || "unknown";
    if (counts[key] !== undefined) counts[key] += 1;
    else counts.unknown += 1;
  });
  const attention = counts.critical + counts.warning;
  const parts = [];
  if (counts.critical) parts.push(`${counts.critical} need${counts.critical === 1 ? "s" : ""} a fix`);
  if (counts.warning) parts.push(`${counts.warning} worth a look`);
  if (counts.healthy) parts.push(`${counts.healthy} healthy`);
  if (counts.unknown) parts.push(`${counts.unknown} unfinished`);
  const lead =
    attention > 0
      ? `${attention} need${attention === 1 ? "s" : ""} attention`
      : `${counts.healthy} healthy`;
  el.listSummary.innerHTML = `<strong>${escapeHtml(lead)}</strong><span class="list-summary-rest"> · ${escapeHtml(parts.join(" · "))} · ${total} total</span>`;
}

function renderCustomerFilter() {
  if (!el.customerFilter) return;
  const selected = state.customerFilter;
  const names = new Map();
  state.customers.forEach((c) => names.set(String(c.id), c.name));
  state.sites.forEach((s) => {
    if (s.customer_id && s.customer_name) names.set(String(s.customer_id), s.customer_name);
  });
  const options = ['<option value="">All customers</option>'];
  [...names.entries()]
    .sort((a, b) => a[1].localeCompare(b[1], undefined, { sensitivity: "base" }))
    .forEach(([id, name]) => {
      options.push(
        `<option value="${escapeHtml(id)}"${id === selected ? " selected" : ""}>${escapeHtml(name)}</option>`
      );
    });
  el.customerFilter.innerHTML = options.join("");
}

function updateSortHeaders() {
  document.querySelectorAll("#sites-table thead th.sortable").forEach((th) => {
    const key = th.dataset.sort;
    th.classList.remove("sorted-asc", "sorted-desc");
    th.setAttribute("aria-sort", "none");
    if (key === state.sortKey) {
      th.classList.add(state.sortDir === "asc" ? "sorted-asc" : "sorted-desc");
      th.setAttribute("aria-sort", state.sortDir === "asc" ? "ascending" : "descending");
    }
  });
}

function pageCount(total) {
  return Math.max(1, Math.ceil(total / state.pageSize) || 1);
}

function clampPage(total) {
  const pages = pageCount(total);
  if (state.page > pages) state.page = pages;
  if (state.page < 1) state.page = 1;
}

function renderPagination(total) {
  if (!el.pagination) return;
  clampPage(total);
  const pages = pageCount(total);
  const showBar = total > 0;
  el.pagination.hidden = !showBar;
  if (!showBar) return;

  const start = (state.page - 1) * state.pageSize + 1;
  const end = Math.min(total, state.page * state.pageSize);
  el.paginationMeta.textContent = `Showing ${start}–${end} of ${total}`;

  if (el.pageSize && String(el.pageSize.value) !== String(state.pageSize)) {
    el.pageSize.value = String(state.pageSize);
  }
  el.pagePrev.disabled = state.page <= 1;
  el.pageNext.disabled = state.page >= pages;

  el.paginationPages.innerHTML = "";
  const windowSize = 5;
  let from = Math.max(1, state.page - Math.floor(windowSize / 2));
  let to = Math.min(pages, from + windowSize - 1);
  from = Math.max(1, to - windowSize + 1);

  const addBtn = (label, page, opts = {}) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `pagination-page${opts.current ? " active" : ""}`;
    btn.textContent = label;
    btn.disabled = Boolean(opts.disabled);
    if (opts.current) btn.setAttribute("aria-current", "page");
    if (!opts.disabled && page != null) {
      btn.addEventListener("click", () => {
        state.page = page;
        renderList();
        el.sitesWrap?.scrollTo?.({ top: 0 });
      });
    }
    el.paginationPages.appendChild(btn);
  };

  if (from > 1) {
    addBtn("1", 1);
    if (from > 2) addBtn("…", null, { disabled: true });
  }
  for (let p = from; p <= to; p += 1) {
    addBtn(String(p), p, { current: p === state.page });
  }
  if (to < pages) {
    if (to < pages - 1) addBtn("…", null, { disabled: true });
    addBtn(String(pages), pages);
  }
}

function renderList() {
  renderSummary();
  updateSortHeaders();
  const items = filteredSites();
  clampPage(items.length);
  const start = (state.page - 1) * state.pageSize;
  const pageItems = items.slice(start, start + state.pageSize);

  el.list.innerHTML = "";
  el.empty.classList.toggle("hidden", items.length > 0);
  if (!items.length && state.sites.length) {
    el.empty.innerHTML = "No websites match this filter — try <strong>All</strong> or clear search.";
  } else if (!state.sites.length) {
    el.empty.innerHTML =
      'No websites yet — type one above and press <strong>Check</strong>.';
  }
  pageItems.forEach((site) => {
    const tr = document.createElement("tr");
    const tone = statusClass(site.overall);
    tr.className = `site-row row-${tone}${site.id === state.selectedId ? " active" : ""}`;
    tr.dataset.id = String(site.id);
    tr.tabIndex = 0;
    tr.setAttribute("role", "button");
    tr.setAttribute(
      "aria-label",
      `${site.display_name}, ${site.overall_label || "Not checked yet"}`
    );
    const customer = site.customer_name
      ? `<div class="cell-sub customer-tag">${escapeHtml(site.customer_name)}</div>`
      : "";
    tr.innerHTML = `
      <td>
        <div class="site-name">${escapeHtml(site.display_name)}</div>
        <div class="cell-sub">${escapeHtml(site.domain)}</div>
        ${customer}
      </td>
      ${statusCell(site.overall_label, site.overall, site.overall_why)}
      ${statusCell(site.website_label, site.website_status)}
      ${expiryCell(site.ssl_status, site.ssl_expires, site.ssl_expires_days, site.ssl_label)}
      ${expiryCell(site.domain_status, site.domain_expires, site.domain_expires_days, site.domain_label)}
      ${statusCell(site.dns_label, site.dns_status)}
      <td>${escapeHtml(site.last_checked_label || "Never")}</td>
    `;
    const open = () => selectSite(site.id);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    el.list.appendChild(tr);
  });
  renderPagination(items.length);
}

function renderDetail() {
  const d = state.detail;
  if (!d) {
    showView("list");
    return;
  }
  el.detailName.textContent = d.display_name;
  el.detailDomain.textContent = d.domain;
  el.detailSummary.textContent = d.summary;
  el.results.innerHTML = d.findings_html || "<p class='muted'>No details yet.</p>";
  el.history.innerHTML = d.history_html || "<p class='muted'>No history yet.</p>";
  el.changes.innerHTML = d.changes_html || "<p class='muted'>No changes recorded.</p>";
  bindInfoTips(el.viewDetail);
  showView("detail");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadSites() {
  const data = await api("/api/sites");
  state.sites = data.sites || [];
  state.customers = data.customers || [];
  renderCustomerFilter();
  renderList();
  if (state.selectedId) {
    const still = state.sites.some((s) => s.id === state.selectedId);
    if (!still) {
      state.selectedId = null;
      state.detail = null;
      renderDetail();
    }
  }
}

async function selectSite(id) {
  state.selectedId = id;
  renderList();
  showView("detail");
  setStatus("Loading results…");
  showLoader("Loading results…");
  try {
    state.detail = await api(`/api/sites/${id}`);
    renderDetail();
    setStatus("");
    el.detailName?.focus?.();
  } catch (err) {
    toast(err.message || "Couldn’t open that website", { type: "error" });
    setStatus("");
    showView("list");
  } finally {
    if (!state.scanning) hideLoader();
  }
}

function backToList() {
  state.selectedId = null;
  state.detail = null;
  showView("list");
  renderList();
}

async function quickCheck(event) {
  event.preventDefault();
  if (state.scanning) return;
  const url = el.url.value.trim();
  if (!url) return;
  setStatus("Checking… please wait");
  setScanBusy(true);
  try {
    const created = await api("/api/sites", {
      method: "POST",
      body: JSON.stringify({
        url,
        customer: el.customer.value.trim(),
      }),
    });
    el.url.value = "";
    await loadSites();
    state.selectedId = created.id;
    renderList();
    await runScan(created.id);
  } catch (err) {
    toast(err.message || "Couldn’t start the check", { type: "error" });
    setStatus("");
    setScanBusy(false);
  }
}

function setScanBusy(busy) {
  state.scanning = busy;
  el.checkBtn.classList.toggle("busy", busy);
  el.checkBtn.disabled = busy;
  el.checkBtn.setAttribute("aria-busy", busy ? "true" : "false");
  const checkAll = document.getElementById("check-all-btn");
  if (checkAll) {
    checkAll.classList.toggle("busy", busy);
    checkAll.disabled = busy;
    checkAll.setAttribute("aria-busy", busy ? "true" : "false");
  }
  const rescan = document.getElementById("rescan-btn");
  if (rescan) {
    rescan.classList.toggle("busy", busy);
    rescan.disabled = busy;
  }
  if (busy) {
    showLoader(el.status.textContent || "Checking…");
  } else {
    hideLoader();
  }
}

async function waitForScanJob(id, onMessage) {
  const started = await api(`/api/sites/${id}/scan`, { method: "POST" });
  const jobId = started.job_id;
  while (true) {
    await sleep(700);
    const job = await api(`/api/jobs/${jobId}`);
    if (job.message && onMessage) onMessage(job.message);
    if (job.status === "done") return job;
    if (job.status === "error") {
      throw new Error(job.error || "Check failed");
    }
  }
}

async function runScan(id, { quiet = false } = {}) {
  const alreadyBusy = state.scanning;
  if (!alreadyBusy) setScanBusy(true);
  if (!quiet) setStatus("Checking…");
  try {
    const job = await waitForScanJob(id, (message) => {
      if (!quiet) setStatus(message);
    });
    await loadSites();
    if (!quiet) {
      state.detail = job.detail;
      state.selectedId = id;
      renderDetail();
      showView("detail");
      const label = job.detail.overall_label || "Done";
      const why = job.detail.overall_why || "";
      setStatus(label);
      toast(why && why !== "No action needed" ? `${label} — ${why}` : label);
    }
    return job;
  } catch (err) {
    if (!quiet) {
      toast(err.message || "Check didn’t finish", { type: "error" });
      setStatus("Check didn’t finish");
    }
    throw err;
  } finally {
    if (!quiet) setScanBusy(false);
  }
}

async function checkAllWebsites() {
  if (state.scanning) return;
  await loadSites();
  const sites = [...state.sites];
  if (!sites.length) {
    toast("No websites yet — import a list or type one above");
    return;
  }
  const ok = await askConfirm({
    title: "Check all websites?",
    message:
      `Check all ${sites.length} website${sites.length === 1 ? "" : "s"}?\n\n` +
      "WHM will check them one by one. This can take several minutes — leave this window open.",
    confirmLabel: "Check all",
  });
  if (!ok) return;

  showView("list");
  setStatus(`Checking 1 of ${sites.length}…`);
  setScanBusy(true);
  let passed = 0;
  let failed = 0;
  try {
    for (let i = 0; i < sites.length; i++) {
      const site = sites[i];
      const label = site.display_name || site.domain || `#${site.id}`;
      setStatus(`Checking ${i + 1} of ${sites.length}: ${label}`);
      try {
        await waitForScanJob(site.id, (message) => {
          setStatus(`Checking ${i + 1} of ${sites.length}: ${label} — ${message}`);
        });
        passed += 1;
        await loadSites();
      } catch (err) {
        failed += 1;
        console.warn(`Check failed for ${label}:`, err);
      }
    }
    await loadSites();
    const summary =
      failed === 0
        ? `Checked all ${passed} website${passed === 1 ? "" : "s"}`
        : `Checked ${passed} website${passed === 1 ? "" : "s"}; ${failed} didn’t finish`;
    setStatus(summary);
    toast(summary, { type: failed ? "warn" : "ok" });
  } finally {
    setScanBusy(false);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function openSettings() {
  const data = await api("/api/settings");
  const fields = data.fields || [];
  el.settingsForm.innerHTML = fields
    .map((f) => {
      const tip = escapeHtml(f.tip || f.hint || "");
      const info = tip
        ? `<button type="button" class="info-btn" data-tip="${tip}" aria-label="About ${escapeHtml(f.label)}">i</button>`
        : "";
      const inputType = f.type === "password" ? "password" : "text";
      return `<label>
        <span class="settings-label">${escapeHtml(f.label)}${info}</span>
        <input name="${escapeHtml(f.key)}" value="${escapeHtml(f.value)}" type="${inputType}" />
        ${f.hint ? `<small>${escapeHtml(f.hint)}</small>` : ""}
      </label>`;
    })
    .join("");
  bindInfoTips(el.settingsForm);
  openModal(el.settingsModal, el.settingsForm.querySelector("input"));
}

async function saveSettings(event) {
  event.preventDefault();
  const form = new FormData(el.settingsForm);
  const payload = {};
  for (const [key, value] of form.entries()) payload[key] = String(value);
  await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
  closeModal(el.settingsModal);
  toast("Settings saved", { type: "ok" });
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      document.getElementById(`panel-${tab.dataset.tab}`).classList.add("active");
    });
  });
}

function bind() {
  el.form.addEventListener("submit", quickCheck);
  el.search.addEventListener("input", () => {
    state.page = 1;
    renderList();
  });
  document.querySelectorAll("[data-status-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.statusFilter = btn.getAttribute("data-status-filter") || "all";
      document.querySelectorAll("[data-status-filter]").forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      state.page = 1;
      renderList();
    });
  });
  if (el.customerFilter) {
    el.customerFilter.addEventListener("change", () => {
      state.customerFilter = el.customerFilter.value || "";
      state.page = 1;
      renderList();
    });
  }
  document.querySelectorAll("#sites-table thead th.sortable").forEach((th) => {
    const btn = th.querySelector(".th-sort");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (!key) return;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        // Urgency / expiry: soonest / worst first by default.
        state.sortDir = key === "name" || key === "checked" ? "asc" : "asc";
        if (key === "checked") state.sortDir = "desc";
      }
      state.page = 1;
      renderList();
    });
  });
  const removeAllBtn = document.getElementById("remove-all-btn");
  if (removeAllBtn) {
    removeAllBtn.addEventListener("click", async () => {
      if (!state.sites.length) {
        toast("No websites to remove", { type: "ok" });
        return;
      }
      const ok = await askConfirm({
        title: "Remove all websites?",
        message: `Remove all ${state.sites.length} websites from your list?\nPast check history for each will also be removed. This cannot be undone.`,
        confirmLabel: "Remove all",
        danger: true,
      });
      if (!ok) return;
      try {
        showLoader("Removing all websites…");
        const result = await api("/api/sites/clear-all", {
          method: "POST",
          body: JSON.stringify({ confirm: "remove-all" }),
        });
        state.selectedId = null;
        state.detail = null;
        showView("list");
        await loadSites();
        toast(`Removed ${result.removed ?? 0} websites`, { type: "ok" });
      } catch (err) {
        toast(err.message || "Couldn’t remove websites", { type: "error" });
      } finally {
        if (!state.scanning) hideLoader();
      }
    });
  }
  if (el.pagePrev) {
    el.pagePrev.addEventListener("click", () => {
      if (state.page > 1) {
        state.page -= 1;
        renderList();
        el.sitesWrap?.scrollTo?.({ top: 0 });
      }
    });
  }
  if (el.pageNext) {
    el.pageNext.addEventListener("click", () => {
      const total = filteredSites().length;
      if (state.page < pageCount(total)) {
        state.page += 1;
        renderList();
        el.sitesWrap?.scrollTo?.({ top: 0 });
      }
    });
  }
  if (el.pageSize) {
    el.pageSize.value = String(state.pageSize);
    el.pageSize.addEventListener("change", () => {
      state.pageSize = Number(el.pageSize.value) || 25;
      localStorage.setItem(PAGE_SIZE_KEY, String(state.pageSize));
      state.page = 1;
      renderList();
    });
  }
  document.getElementById("refresh-btn").addEventListener("click", () => loadSites());
  document.getElementById("check-all-btn").addEventListener("click", checkAllWebsites);
  document.getElementById("export-all-excel-btn").addEventListener("click", async () => {
    showLoader("Building report for all websites…");
    try {
      const data = await api("/api/export-all", {
        method: "POST",
        body: JSON.stringify({ format: "excel" }),
      });
      toast(`Saved to Downloads: ${data.filename || "report"}`, { type: "ok" });
      setStatus(`Exported ${data.site_count || ""} websites`);
    } catch (err) {
      toast(err.message || "Couldn’t save the report", { type: "error" });
    } finally {
      if (!state.scanning) hideLoader();
    }
  });
  const importInput = document.getElementById("import-file");
  document.getElementById("import-btn").addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", async () => {
    const file = importInput.files && importInput.files[0];
    importInput.value = "";
    if (!file) return;
    setStatus(`Importing ${file.name}…`);
    showLoader(`Importing ${file.name}…`);
    try {
      const buffer = await file.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = "";
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
      }
      const content_base64 = btoa(binary);
      const result = await api("/api/import", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_base64 }),
      });
      await loadSites();
      const summary = result.summary || "Import finished";
      setStatus(summary);
      toast(summary);
    } catch (err) {
      toast(err.message || "Import didn’t finish", { type: "error" });
      setStatus("Import didn’t finish");
    } finally {
      if (!state.scanning) hideLoader();
    }
  });
  const helpModal = document.getElementById("help-modal");
  const closeHelp = () => closeModal(helpModal);
  document.getElementById("help-btn").addEventListener("click", () => {
    openModal(helpModal, document.getElementById("help-ok"));
  });
  document.getElementById("help-close").addEventListener("click", closeHelp);
  document.getElementById("help-ok").addEventListener("click", closeHelp);
  document.getElementById("back-btn").addEventListener("click", backToList);
  document.getElementById("settings-btn").addEventListener("click", openSettings);
  document.getElementById("settings-close").addEventListener("click", () => closeModal(el.settingsModal));
  document.getElementById("settings-cancel").addEventListener("click", () => closeModal(el.settingsModal));
  el.settingsForm.addEventListener("submit", saveSettings);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!el.confirmModal.classList.contains("hidden")) return;
    if (!helpModal.classList.contains("hidden")) {
      closeHelp();
      return;
    }
    if (!el.settingsModal.classList.contains("hidden")) {
      closeModal(el.settingsModal);
      return;
    }
    if (state.view === "detail") backToList();
  });
  document.getElementById("rescan-btn").addEventListener("click", () => {
    if (state.selectedId) runScan(state.selectedId);
  });
  async function downloadReport(format) {
    if (!state.selectedId) return;
    try {
      const data = await api(
        `/api/sites/${state.selectedId}/export?format=${format}`,
        { method: "POST" }
      );
      toast(`Saved to Downloads: ${data.filename || "report"}`);
    } catch (err) {
      toast(err.message || "Couldn’t save the report", { type: "error" });
    }
  }
  document.getElementById("export-excel-btn").addEventListener("click", () => downloadReport("excel"));
  document.getElementById("export-csv-btn").addEventListener("click", () => downloadReport("csv"));
  document.getElementById("delete-btn").addEventListener("click", async () => {
    if (!state.selectedId) return;
    const ok = await askConfirm({
      title: "Remove website?",
      message: "Remove this website from your list?\nPast check history will also be removed.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/sites/${state.selectedId}`, { method: "DELETE" });
      backToList();
      await loadSites();
      toast("Removed from your list", { type: "ok" });
    } catch (err) {
      toast(err.message || "Couldn’t remove that website", { type: "error" });
    }
  });
  const toastDismiss = document.getElementById("toast-dismiss");
  if (toastDismiss) toastDismiss.addEventListener("click", hideToast);
  bindTabs();
  bindInfoTips();
  showView("list");
}

bind();
showLoader("Loading websites…");
loadSites()
  .then(() => {
    setStatus("");
    hideLoader();
  })
  .catch((err) => {
    setStatus("Couldn’t load sites");
    toast(err.message || "Couldn’t load sites", { type: "error" });
    hideLoader();
  });
