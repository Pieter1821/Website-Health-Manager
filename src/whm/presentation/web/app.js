const state = {
  sites: [],
  selectedId: null,
  detail: null,
  scanning: false,
  view: "list",
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
  tipBubble: document.getElementById("tip-bubble"),
  settingsModal: document.getElementById("settings-modal"),
  settingsForm: document.getElementById("settings-form"),
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

function toast(message) {
  el.toast.textContent = message;
  el.toast.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.toast.classList.add("hidden"), 3200);
}

function setStatus(text) {
  el.status.textContent = text || "";
}

function statusClass(value) {
  return (value || "unknown").toLowerCase();
}

function statusCell(label, status) {
  return `<td><span class="pill ${statusClass(status)}">${escapeHtml(label || "—")}</span></td>`;
}

function expiryCell(status, dateLabel, daysLabel, statusLabel) {
  const date = dateLabel && dateLabel !== "—" ? dateLabel : "—";
  const days = daysLabel
    ? `<div class="cell-sub">${escapeHtml(daysLabel)}</div>`
    : "";
  const tone = statusClass(status);
  return `<td class="expiry-cell">
    <div class="expiry-date ${tone}">${escapeHtml(date)}</div>
    ${days}
    <div class="cell-sub">${escapeHtml(statusLabel || "")}</div>
  </td>`;
}

function renderList() {
  const q = el.search.value.trim().toLowerCase();
  const items = state.sites.filter((s) => {
    if (!q) return true;
    return `${s.display_name} ${s.domain} ${s.url}`.toLowerCase().includes(q);
  });
  el.list.innerHTML = "";
  el.empty.classList.toggle("hidden", items.length > 0);
  items.forEach((site) => {
    const tr = document.createElement("tr");
    tr.className = `site-row${site.id === state.selectedId ? " active" : ""}`;
    tr.dataset.id = String(site.id);
    tr.innerHTML = `
      <td>
        <div class="site-name">${escapeHtml(site.display_name)}</div>
        <div class="cell-sub">${escapeHtml(site.domain)}</div>
      </td>
      ${statusCell(site.overall_label, site.overall)}
      ${statusCell(site.website_label, site.website_status)}
      ${expiryCell(site.ssl_status, site.ssl_expires, site.ssl_expires_days, site.ssl_label)}
      ${expiryCell(site.domain_status, site.domain_expires, site.domain_expires_days, site.domain_label)}
      ${statusCell(site.dns_label, site.dns_status)}
      ${statusCell(site.email_label, site.email_status)}
      <td>${escapeHtml(site.last_checked_label || "Never")}</td>
    `;
    tr.addEventListener("click", () => selectSite(site.id));
    el.list.appendChild(tr);
  });
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
  setStatus("Loading results…");
  try {
    state.detail = await api(`/api/sites/${id}`);
    renderDetail();
    setStatus("");
  } catch (err) {
    toast(err.message || "Could not open website");
    setStatus("");
    showView("list");
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
  state.scanning = true;
  el.checkBtn.classList.add("busy");
  setStatus("Checking… please wait");
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
    toast(err.message || "Could not start check");
    setStatus("");
  } finally {
    state.scanning = false;
    el.checkBtn.classList.remove("busy");
  }
}

async function runScan(id) {
  state.scanning = true;
  el.checkBtn.classList.add("busy");
  setStatus("Checking…");
  try {
    const started = await api(`/api/sites/${id}/scan`, { method: "POST" });
    const jobId = started.job_id;
    let done = false;
    while (!done) {
      await sleep(700);
      const job = await api(`/api/jobs/${jobId}`);
      if (job.message) setStatus(job.message);
      if (job.status === "done") {
        done = true;
        state.detail = job.detail;
        state.selectedId = id;
        await loadSites();
        renderDetail();
        setStatus(job.detail.overall_label || "Done");
        toast(job.detail.overall_label || "Done");
      } else if (job.status === "error") {
        done = true;
        toast(job.error || "Check failed");
        setStatus("Check failed");
      }
    }
  } catch (err) {
    toast(err.message || "Check failed");
    setStatus("Check failed");
  } finally {
    state.scanning = false;
    el.checkBtn.classList.remove("busy");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function openSettings() {
  const data = await api("/api/settings");
  const fields = data.fields || [];
  el.settingsForm.innerHTML = fields
    .map(
      (f) => `<label>${escapeHtml(f.label)}
        <input name="${escapeHtml(f.key)}" value="${escapeHtml(f.value)}" ${f.type === "password" ? 'type="password"' : 'type="text"'} />
        ${f.hint ? `<small>${escapeHtml(f.hint)}</small>` : ""}
      </label>`
    )
    .join("");
  el.settingsModal.classList.remove("hidden");
}

async function saveSettings(event) {
  event.preventDefault();
  const form = new FormData(el.settingsForm);
  const payload = {};
  for (const [key, value] of form.entries()) payload[key] = String(value);
  await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
  el.settingsModal.classList.add("hidden");
  toast("Settings saved");
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`panel-${tab.dataset.tab}`).classList.add("active");
    });
  });
}

function bind() {
  el.form.addEventListener("submit", quickCheck);
  el.search.addEventListener("input", renderList);
  document.getElementById("refresh-btn").addEventListener("click", () => loadSites());
  const importInput = document.getElementById("import-file");
  document.getElementById("import-btn").addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", async () => {
    const file = importInput.files && importInput.files[0];
    importInput.value = "";
    if (!file) return;
    setStatus(`Importing ${file.name}…`);
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
      setStatus(result.summary || "Import finished");
      toast(result.summary || "Import finished");
    } catch (err) {
      toast(err.message || "Import failed");
      setStatus("Import failed");
    }
  });
  const helpModal = document.getElementById("help-modal");
  const closeHelp = () => helpModal.classList.add("hidden");
  document.getElementById("help-btn").addEventListener("click", () => {
    helpModal.classList.remove("hidden");
  });
  document.getElementById("help-close").addEventListener("click", closeHelp);
  document.getElementById("help-ok").addEventListener("click", closeHelp);
  document.getElementById("back-btn").addEventListener("click", backToList);
  document.getElementById("settings-btn").addEventListener("click", openSettings);
  document.getElementById("settings-close").addEventListener("click", () => el.settingsModal.classList.add("hidden"));
  document.getElementById("settings-cancel").addEventListener("click", () => el.settingsModal.classList.add("hidden"));
  el.settingsForm.addEventListener("submit", saveSettings);
  document.getElementById("rescan-btn").addEventListener("click", () => {
    if (state.selectedId) runScan(state.selectedId);
  });
  document.getElementById("export-btn").addEventListener("click", async () => {
    if (!state.selectedId) return;
    try {
      const res = await fetch(`/api/sites/${state.selectedId}/export`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Download failed");
      }
      const blob = await res.blob();
      const header = res.headers.get("Content-Disposition") || "";
      const match = /filename="([^"]+)"/.exec(header);
      const filename = match ? match[1] : `whm-report-${state.selectedId}.zip`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast("Report downloaded to your PC (ZIP with HTML, CSV, JSON)");
    } catch (err) {
      toast(err.message || "Download failed");
    }
  });
  document.getElementById("delete-btn").addEventListener("click", async () => {
    if (!state.selectedId) return;
    if (!confirm("Remove this website from your list?")) return;
    await api(`/api/sites/${state.selectedId}`, { method: "DELETE" });
    backToList();
    await loadSites();
    toast("Removed");
  });
  bindTabs();
  bindInfoTips();
  showView("list");
}

bind();
loadSites().catch((err) => {
  setStatus("Could not load sites");
  toast(err.message);
});
