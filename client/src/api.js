// Thin client for the FactVerify FastAPI server.
let token = "";
try { token = localStorage.getItem("fv_token") || ""; } catch { /* storage unavailable */ }

export function setToken(t) {
  token = t;
  try { localStorage.setItem("fv_token", t); } catch { /* ignore */ }
}
export const getToken = () => token;

async function request(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (token) headers["X-API-Token"] = token;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, { ...opts, headers });
  const type = res.headers.get("content-type") || "";
  const body = type.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = typeof body === "object" ? body.detail : body;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

export const api = {
  health: () => request("/api/health"),
  ingest: (form) => request("/api/audit/ingest", { method: "POST", body: form }),
  forensics: (audit_id) => request("/api/audit/forensics", { method: "POST", json: { audit_id } }),
  demo: (scenario, media = "video", lang = "auto") =>
    request(`/api/demo/${scenario}?media=${media}&reply_language=${lang}`, { method: "POST" }),
  demoProfile: () => request("/api/demo/profile"),
  audit: (id) => request(`/api/audit/${id}`),
  audits: () => request("/api/audits"),
  registry: () => request("/api/registry"),
  playbooks: () => request("/api/playbooks"),
  team: () => request("/api/ai/team"),
  tasks: () => request("/api/tasks"),
  run: (audit_id) => request("/api/tasks/run", { method: "POST", json: { audit_id } }),
  state: (id) => request(`/api/tasks/${id}/state`),
  respond: (id, body) => request(`/api/tasks/${id}/respond`, { method: "POST", json: body }),
  complete: (id) => request(`/api/tasks/${id}/complete`, { method: "POST" }),
  verifyChain: () => request("/api/receipts/verify"),
  reportUrl: (auditId, taskId) => `/api/audit/${auditId}/report${taskId ? `?task_id=${taskId}` : ""}`,
  downloadReport: async (auditId, taskId) => {
    const text = await request(`/api/audit/${auditId}/report${taskId ? `?task_id=${taskId}` : ""}`);
    const blob = new Blob([text], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `factverify_${auditId}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  },
};
