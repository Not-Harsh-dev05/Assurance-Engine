const state = { page: 1, pageSize: 12, search: "", status: "", pages: 1, selectedCase: null, debounce: null };
const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const error = payload?.error;
    throw new Error(error?.message || `Request failed (${response.status})`);
  }
  return payload;
}

function showError(message) {
  const banner = byId("error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
  byId("notice-banner").classList.add("hidden");
}

function showNotice(message) {
  const banner = byId("notice-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
  byId("error-banner").classList.add("hidden");
  window.setTimeout(() => banner.classList.add("hidden"), 6500);
}

function statusPill(status) {
  if (!status) return '<span class="pill pill-unverified">NOT RUN</span>';
  const classes = { COMPLETE: "pill-complete", INCOMPLETE: "pill-incomplete", NOT_APPLICABLE: "pill-na" };
  return `<span class="pill ${classes[status] || "pill-na"}">${escapeHtml(status)}</span>`;
}

function reportedPill(status) {
  return `<span class="pill pill-reported">${escapeHtml(status)} · CLAIM</span>`;
}

async function loadDashboard() {
  const dashboard = await api("/api/dashboard");
  byId("metric-total").textContent = dashboard.request_count.toLocaleString();
  byId("nav-case-count").textContent = dashboard.request_count.toLocaleString();
  byId("cases-total").textContent = dashboard.request_count.toLocaleString();
  byId("metric-complete").textContent = dashboard.status_counts.COMPLETE.toLocaleString();
  byId("metric-incomplete").textContent = dashboard.status_counts.INCOMPLETE.toLocaleString();
  byId("metric-na").textContent = dashboard.status_counts.NOT_APPLICABLE.toLocaleString();
  byId("export-link").setAttribute("aria-disabled", dashboard.has_results ? "false" : "true");
  const alert = byId("audit-alert");
  if (dashboard.request_count && !dashboard.audit_ready) {
    byId("audit-alert-title").textContent = dashboard.has_results ? "Verification is incomplete" : "Evidence gaps need attention";
    byId("audit-alert-copy").textContent = dashboard.has_results
      ? `${dashboard.status_counts.INCOMPLETE} request(s) remain unverified because source evidence is missing or its schema is not mapped to policy checks.`
      : dashboard.missing_inputs.length
        ? `${dashboard.missing_inputs.length} audit source(s) are missing or empty. Run verification to record explicit evidence gaps; no request will be marked complete from its reported status.`
        : "The source files are present, but their schemas are not mapped to deletion-policy checks. Results will remain unverified.";
    alert.classList.remove("hidden");
  } else if (!dashboard.request_count) {
    byId("audit-alert-title").textContent = "Load deletion requests to begin";
    byId("audit-alert-copy").textContent = dashboard.load_error || "Import a CSV with the required request columns. Results remain unverified until supporting audit evidence is available.";
    alert.classList.remove("hidden");
  } else {
    alert.classList.add("hidden");
  }
  byId("run-audit").disabled = dashboard.request_count === 0;
}

async function loadCases() {
  const body = byId("cases-body");
  body.innerHTML = '<tr><td colspan="5" class="table-loading"><span class="spinner"></span> Loading requests…</td></tr>';
  const query = new URLSearchParams({ page: String(state.page), page_size: String(state.pageSize), search: state.search, status: state.status });
  const result = await api(`/api/cases?${query}`);
  state.pages = Math.max(result.pages, 1);
  if (!result.items.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty-row">No requests match these filters.</td></tr>';
  } else {
    body.innerHTML = result.items.map((item) => {
      const selected = state.selectedCase === item.case_id ? ' class="selected-row"' : "";
      return `<tr${selected}>
        <td><div class="case-cell"><button class="case-link" data-case="${escapeHtml(item.case_id)}" type="button">${escapeHtml(item.case_id)}</button><span class="case-email">${escapeHtml(item.email)}</span></div></td>
        <td class="date-cell">${escapeHtml(formatDate(item.requested_at))}</td>
        <td>${reportedPill(item.reported_status)}</td>
        <td>${statusPill(item.result?.deletion_status)}</td>
        <td><button class="detail-open" type="button" data-case="${escapeHtml(item.case_id)}" aria-label="Open ${escapeHtml(item.case_id)} details">›</button></td>
      </tr>`;
    }).join("");
    body.querySelectorAll("[data-case]").forEach((button) => button.addEventListener("click", () => selectCase(button.dataset.case)));
  }
  byId("pagination-summary").textContent = result.total
    ? `Showing ${((state.page - 1) * state.pageSize) + 1}–${Math.min(state.page * state.pageSize, result.total)} of ${result.total} requests`
    : "No requests to display";
  byId("page-number").textContent = `${state.page} / ${state.pages}`;
  byId("page-prev").disabled = state.page <= 1;
  byId("page-next").disabled = state.page >= state.pages;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? escapeHtml(value) : new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }).format(date);
}

async function selectCase(caseId) {
  state.selectedCase = caseId;
  try {
    const data = await api(`/api/cases/${encodeURIComponent(caseId)}`);
    renderCase(data);
    await loadCases();
  } catch (error) {
    showError(error.message);
  }
}

function renderCase(data) {
  const item = data.case;
  const result = data.result;
  const detail = byId("case-detail");
  const findingHtml = result
    ? result.findings.map((finding) => `<li><strong>${escapeHtml(finding.code.replaceAll("_", " "))}:</strong> ${escapeHtml(finding.message)}</li>`).join("")
    : "<li>Verification has not been run for this request.</li>";
  const evidenceHtml = result?.supporting_evidence?.length
    ? `<ul>${result.supporting_evidence.map((evidence) => `<li>${escapeHtml(evidence.label || evidence.source)}${evidence.reference ? ` — ${escapeHtml(evidence.reference)}` : ""}</li>`).join("")}</ul>`
    : '<p class="evidence-empty"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2.8 19h18.4L12 3Z"/><path d="M12 9v4m0 3h.01"/></svg>No supporting deletion evidence is available. The reported status is not proof.</p>';
  const stepsHtml = result?.steps?.length
    ? `<ol>${result.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>`
    : "<p>Run verification to generate ordered next steps.</p>";
  const gapsHtml = result?.evidence_gaps?.length
    ? `<ul>${result.evidence_gaps.map((gap) => `<li><strong>${escapeHtml(gap.source)}:</strong> ${escapeHtml(gap.message)}</li>`).join("")}</ul>`
    : "<p>No audit evidence gaps have been evaluated yet.</p>";
  detail.innerHTML = `
    <div class="detail-case-head"><strong>${escapeHtml(item.case_id)}</strong>${statusPill(result?.deletion_status)}</div>
    <dl class="detail-fields">
      <div><dt>Requester</dt><dd>${escapeHtml(item.email)}</dd></div>
      <div><dt>Reported status · claim only</dt><dd>${reportedPill(item.reported_status)}</dd></div>
      <div><dt>Requested</dt><dd>${escapeHtml(formatDate(item.requested_at))}</dd></div>
      <div><dt>Reported complete</dt><dd>${escapeHtml(formatDate(item.reported_at))}</dd></div>
      <div><dt>Audit reference date</dt><dd>${escapeHtml(formatDate(item.audit_at))}</dd></div>
      <div><dt>Engine verdict</dt><dd>${escapeHtml(result?.engine_verdict || "Not run")}</dd></div>
    </dl>
    <section class="detail-section"><h3>REQUEST</h3><p>${escapeHtml(item.request_text)}</p></section>
    <section class="detail-section"><h3>FINDINGS</h3><ul>${findingHtml}</ul></section>
    <section class="detail-section"><h3>SUPPORTING EVIDENCE</h3>${evidenceHtml}</section>
    <section class="detail-section"><h3>EVIDENCE GAPS</h3>${gapsHtml}</section>
    <section class="detail-section"><h3>ORDERED NEXT STEPS</h3>${stepsHtml}</section>`;
}

async function loadSources() {
  const data = await api("/api/datasets");
  const sources = data.inputs;
  const missing = sources.filter((item) => !item.available || !item.has_data).length;
  byId("source-summary").textContent = missing ? `${missing} INPUTS MISSING` : "ALL INPUTS PRESENT";
  byId("source-list").innerHTML = sources.map((item) => {
    const present = item.available && item.has_data;
    const suffix = item.available ? `${item.record_count} ${item.kind === "directory" ? "files" : "records"}` : "Missing";
    return `<article class="source-item ${present ? "source-present" : "source-missing"}">
      <div class="source-item-top"><i class="source-indicator"></i><span class="source-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}${item.name === "deletion_requests.csv" && item.available ? " · loaded" : ""}</span><span class="source-state">${escapeHtml(suffix)}</span></div>
      <p class="source-path" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</p>
    </article>`;
  }).join("");
  if (data.request_load_error) showError(`The on-disk request CSV could not be loaded: ${data.request_load_error}`);
}

async function refresh() {
  byId("refresh-button").disabled = true;
  try {
    await Promise.all([loadDashboard(), loadCases(), loadSources()]);
    byId("error-banner").classList.add("hidden");
  } catch (error) {
    showError(`Could not refresh the audit workspace. ${error.message}`);
  } finally {
    byId("refresh-button").disabled = false;
  }
}

byId("run-audit").addEventListener("click", async () => {
  const button = byId("run-audit");
  button.disabled = true;
  button.querySelector("span").textContent = "Verifying…";
  byId("notice-banner").classList.add("hidden");
  try {
    const result = await api("/api/audits/run", { method: "POST" });
    state.page = 1;
    await Promise.all([loadDashboard(), loadCases(), loadSources()]);
    showNotice(`Verification completed for ${result.request_count.toLocaleString()} requests. Results are available with explicit evidence gaps.`);
  } catch (error) {
    showError(`Verification could not be completed. ${error.message}`);
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Run verification";
  }
});

byId("csv-upload").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  try {
    const result = await api("/api/import/requests", {
      method: "POST",
      headers: { "Content-Type": "text/csv", "X-Filename": file.name },
      body: file,
    });
    state.page = 1;
    state.selectedCase = null;
    byId("case-detail").innerHTML = '<div class="empty-detail"><span class="empty-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4h12v16H4V8l4-4Z"/><path d="M8 4v4H4"/></svg></span><strong>Requests imported</strong><p>Run verification to inspect every case and its evidence gaps.</p></div>';
    await refresh();
    showNotice(`${result.request_count.toLocaleString()} requests validated and loaded. The source dataset file was not overwritten.`);
  } catch (error) {
    showError(`CSV import failed. ${error.message}`);
  } finally {
    event.target.value = "";
  }
});

byId("search-input").addEventListener("input", (event) => {
  window.clearTimeout(state.debounce);
  state.debounce = window.setTimeout(() => {
    state.search = event.target.value;
    state.page = 1;
    loadCases().catch((error) => showError(error.message));
  }, 220);
});

byId("status-filter").addEventListener("change", (event) => {
  state.status = event.target.value;
  state.page = 1;
  loadCases().catch((error) => showError(error.message));
});

byId("page-prev").addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    loadCases().catch((error) => showError(error.message));
  }
});
byId("page-next").addEventListener("click", () => {
  if (state.page < state.pages) {
    state.page += 1;
    loadCases().catch((error) => showError(error.message));
  }
});
byId("refresh-button").addEventListener("click", refresh);
byId("export-link").addEventListener("click", (event) => {
  if (event.currentTarget.getAttribute("aria-disabled") === "true") {
    event.preventDefault();
    showError("Run verification before exporting a results CSV.");
  }
});

refresh();
