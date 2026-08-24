const state = { demos: {}, selectedRun: null };

const identity = () => document.querySelector("#identity").value;
const headers = (json = false) => ({
  "X-Demo-User": identity(),
  ...(json ? { "Content-Type": "application/json" } : {}),
});

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body.detail || body || `HTTP ${response.status}`);
  return body;
}

function notice(message, error = false) {
  const element = document.querySelector("#notice");
  element.hidden = false;
  element.textContent = message;
  element.classList.toggle("error", error);
}

function statusBadge(value) {
  return `<span class="status ${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}

function loadDemo(name) {
  const item = state.demos[name];
  if (!item) return;
  document.querySelector("#asset-id").value = item.asset_id;
  document.querySelector("#occurred-at").value = item.occurred_at.slice(0, 16);
  document.querySelector("#severity").value = item.severity;
  document.querySelector("#symptoms").value = item.symptoms.join(", ");
  document.querySelector("#question").value = item.question;
}

async function loadMetrics() {
  try {
    const value = await request("/api/v1/metrics", { headers: headers() });
    document.querySelector("#metric-total").textContent = value.runs_total;
    document.querySelector("#metric-review").textContent = value.runs_by_status.needs_review || 0;
    document.querySelector("#metric-completed").textContent = value.runs_by_status.completed || 0;
    document.querySelector("#metric-failed").textContent = value.runs_by_status.failed || 0;
  } catch {
    ["total", "review", "completed", "failed"].forEach((key) => {
      document.querySelector(`#metric-${key}`).textContent = "—";
    });
  }
}

async function loadRuns() {
  try {
    const runs = await request("/api/v1/runs?limit=30", { headers: headers() });
    const body = document.querySelector("#runs-body");
    body.innerHTML = runs.length ? runs.map((run) => `
      <tr data-run-id="${escapeHtml(run.run_id)}">
        <td class="mono">${escapeHtml(run.run_id.slice(-8))}</td>
        <td>${escapeHtml(run.request.asset_id)}</td>
        <td>${statusBadge(run.status)}</td>
        <td class="risk ${escapeHtml(run.risk_level)}">${escapeHtml(run.risk_level || "—")}</td>
        <td>${new Date(run.updated_at).toLocaleString()}</td>
      </tr>`).join("") : `<tr><td colspan="5">尚無執行紀錄</td></tr>`;
    body.querySelectorAll("tr[data-run-id]").forEach((row) => {
      row.addEventListener("click", () => loadRun(row.dataset.runId));
    });
  } catch (error) {
    notice(error.message, true);
  }
}

function renderDetail(run) {
  state.selectedRun = run.run_id;
  const panel = document.querySelector("#detail");
  panel.hidden = false;
  document.querySelector("#detail-title").textContent = `${run.request.asset_id} · ${run.run_id}`;
  const status = document.querySelector("#detail-status");
  status.textContent = run.status;
  status.className = `status ${run.status}`;

  const recommendation = run.recommendation;
  const tools = run.tool_executions.map((tool) => `
    <div class="trace-item">
      <strong>${escapeHtml(tool.tool_name)} · ${escapeHtml(tool.status)}</strong>
      <span>attempt ${tool.attempts} · ${tool.duration_ms.toFixed(2)} ms${tool.error ? ` · ${escapeHtml(tool.error)}` : ""}</span>
    </div>`).join("");
  const events = run.events.map((event) => `
    <div class="trace-item">
      <strong>${escapeHtml(event.event_type)}</strong>
      <span>${escapeHtml(event.from_status || "—")} → ${escapeHtml(event.to_status || "—")} · ${new Date(event.created_at).toLocaleTimeString()}</span>
    </div>`).join("");
  const approval = run.status === "needs_review" ? `
    <div class="approval-actions">
      <button class="primary" data-decision="approved">核准建議</button>
      <button class="danger" data-decision="rejected">駁回建議</button>
    </div>` : "";

  document.querySelector("#detail-content").innerHTML = `
    <div class="detail-grid">
      <div>
        <article class="detail-card">
          <h3>結論與下一步</h3>
          <p>${escapeHtml(recommendation?.summary || run.failure_reason || "工作流尚未產生結論。")}</p>
          <ul>${(recommendation?.actions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
          ${approval}
        </article>
        <article class="detail-card" style="margin-top: 16px">
          <h3>證據引用</h3>
          ${(recommendation?.citations || []).map((item) => `<code class="citation">${escapeHtml(item)}</code>`).join("") || "<p>無引用</p>"}
        </article>
      </div>
      <div>
        <article class="detail-card trace"><h3>工具執行</h3>${tools || "<p>尚無工具紀錄</p>"}</article>
        <article class="detail-card trace" style="margin-top: 16px"><h3>狀態事件</h3>${events}</article>
      </div>
    </div>`;
  document.querySelectorAll("[data-decision]").forEach((button) => {
    button.addEventListener("click", () => decide(button.dataset.decision));
  });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadRun(runId) {
  try {
    renderDetail(await request(`/api/v1/runs/${encodeURIComponent(runId)}`, { headers: headers() }));
  } catch (error) { notice(error.message, true); }
}

async function decide(decision) {
  const reviewer = identity();
  if (!["reviewer", "admin"].includes(reviewer)) {
    notice("請先把示範身分切換為 reviewer 或 admin。", true);
    return;
  }
  try {
    const run = await request(`/api/v1/runs/${encodeURIComponent(state.selectedRun)}/approval`, {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ decision, note: `${decision} through the local review dashboard` }),
    });
    notice(`工作流已${decision === "approved" ? "核准" : "駁回"}。`);
    renderDetail(run); await Promise.all([loadRuns(), loadMetrics()]);
  } catch (error) { notice(error.message, true); }
}

document.querySelector("#incident-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!["operator", "admin"].includes(identity())) {
    notice("請先把示範身分切換為 operator 或 admin。", true); return;
  }
  const submit = event.submitter;
  submit.disabled = true;
  try {
    const occurred = `${document.querySelector("#occurred-at").value}:00Z`;
    const payload = {
      idempotency_key: `web-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      asset_id: document.querySelector("#asset-id").value.trim(),
      occurred_at: occurred,
      symptoms: document.querySelector("#symptoms").value.split(",").map((item) => item.trim()).filter(Boolean),
      severity: document.querySelector("#severity").value,
      question: document.querySelector("#question").value.trim(),
    };
    const run = await request("/api/v1/runs", { method: "POST", headers: headers(true), body: JSON.stringify(payload) });
    notice(`工作流完成：${run.status}。所有工具與驗證事件已保存。`);
    renderDetail(run); await Promise.all([loadRuns(), loadMetrics()]);
  } catch (error) { notice(error.message, true); }
  finally { submit.disabled = false; }
});

document.querySelectorAll("[data-demo]").forEach((button) => button.addEventListener("click", () => loadDemo(button.dataset.demo)));
document.querySelector("#refresh").addEventListener("click", () => Promise.all([loadRuns(), loadMetrics()]));
document.querySelector("#identity").addEventListener("change", () => Promise.all([loadRuns(), loadMetrics()]));

Promise.all([
  request("/api/v1/demo-requests").then((value) => { state.demos = value; loadDemo("critical"); }),
  loadRuns(), loadMetrics(),
]).catch((error) => notice(error.message, true));
