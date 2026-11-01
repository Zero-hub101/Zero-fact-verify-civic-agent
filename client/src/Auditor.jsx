import { useEffect, useState } from "react";
import { api } from "./api.js";

const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}`);

export default function Auditor({ onOpen }) {
  const [audits, setAudits] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [registry, setRegistry] = useState([]);
  const [playbooks, setPlaybooks] = useState([]);
  const [chain, setChain] = useState(null);
  const [team, setTeam] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const [a, t, r, p, tm] = await Promise.all([api.audits(), api.tasks(), api.registry(), api.playbooks(), api.team()]);
      setAudits(a); setTasks(t); setRegistry(r); setPlaybooks(p); setTeam(tm);
    } catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  const stats = {
    total: audits.filter((a) => a.verdict).length,
    fraud: audits.filter((a) => a.verdict === "likely_fraudulent").length,
    deepfakes: audits.filter((a) => a.deepfakeDetected).length,
    completed: tasks.filter((t) => t.status === "completed").length,
  };

  return (
    <div className="auditor">
      {err && <p className="err">{err}</p>}
      <div className="stats">
        <div className="stat"><b>{stats.total}</b><span>claims checked</span></div>
        <div className="stat bad"><b>{stats.fraud}</b><span>flagged fraudulent</span></div>
        <div className="stat bad"><b>{stats.deepfakes}</b><span>manipulated media</span></div>
        <div className="stat ok"><b>{stats.completed}</b><span>applications completed</span></div>
      </div>

      <div className="card">
        <h3>AI team <span className="muted small">· one model per job, swappable in <code>.env</code></span></h3>
        <table className="tbl">
          <thead><tr><th>Role</th><th>Job</th><th>Active model</th><th>Type</th><th>Preference order</th><th>Setting</th></tr></thead>
          <tbody>
            {team.map((t) => (
              <tr key={t.role}>
                <td><b>{t.role}</b></td><td>{t.label}</td>
                <td>{t.active ? <span className="mono small">{t.name} · {t.model}</span> : <span className="muted">off</span>}</td>
                <td><span className={`pill ${t.status === "specialist" ? "ok" : t.status === "stand-in" ? "warn" : "subtle"}`}>{t.status}</span></td>
                <td className="mono small">{t.assigned.join(" → ") || "–"}</td>
                <td className="mono small">{t.env}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">A role uses the first model in its preference order that has an API key. "Stand-in" means a
          general model is covering the job because no specialist key is set. Add keys in <code>.env</code>; to add a new model, copy
          <code> server/app/ai/providers/_template.py</code>.</p>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Audit log</h3>
          <div className="inline">
            <button className="ghost" onClick={async () => setChain(await api.verifyChain())}>Verify receipt chain</button>
            {chain && <span className={`pill ${chain.chain_valid ? "ok" : "bad"}`}>{chain.chain_valid ? "Receipt chain intact" : "Chain broken"}</span>}
            <button className="ghost" onClick={load}>Refresh</button>
          </div>
        </div>
        <table className="tbl">
          <thead><tr><th>When</th><th>Claim</th><th>Scheme</th><th>Trust</th><th>Media</th><th>Verdict</th><th>Agent</th><th></th></tr></thead>
          <tbody>
            {audits.map((a) => {
              const t = tasks.find((x) => x.audit_id === a.id);
              return (
                <tr key={a.id}>
                  <td className="nowrap">{new Date(a.created_at * 1000).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}</td>
                  <td className="clip">{a.summary}</td>
                  <td>{a.scheme || "–"}</td>
                  <td>{pct(a.authenticity)}</td>
                  <td>{a.deepfakeDetected ? <span className="pill bad">manipulated</span> : "–"}</td>
                  <td>{a.verdict ? <span className={`pill ${a.verdict === "authentic" ? "ok" : a.verdict === "unverified" ? "warn" : "bad"}`}>{a.verdict.replace("_", " ")}</span> : <span className="muted">not run</span>}</td>
                  <td>{t ? <span className="mono small">{t.status}{t.result?.tracking_code ? ` · ${t.result.tracking_code}` : ""}</span> : "–"}</td>
                  <td className="nowrap">
                    {a.verdict && <button className="link" onClick={() => onOpen(a.id, t?.id)}>open</button>}
                    {a.verdict && <button className="link" onClick={() => api.downloadReport(a.id, t?.id)}>report.md</button>}
                  </td>
                </tr>
              );
            })}
            {!audits.length && <tr><td colSpan={8} className="muted">No audits yet. Verify a claim first.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="two">
        <div className="card">
          <h3>Trusted scheme registry</h3>
          <p className="muted small">Edit <code>server/data/registry.json</code> to add schemes from official notifications.</p>
          {registry.map((s) => (
            <div key={s.id} className="reg">
              <b>{s.name}</b> <span className="muted small">{s.source}</span>
              <div className="small">Rs {s.benefit_amount.toLocaleString("en-IN")} {s.benefit_period} · fee {s.application_fee ? `Rs ${s.application_fee}` : "free"}{s.income_limit != null && ` · income ≤ Rs ${s.income_limit.toLocaleString("en-IN")}`}{s.deadline && ` · deadline ${s.deadline}`}</div>
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Portal playbooks</h3>
          <p className="muted small">One JSON file per portal in <code>server/app/agent/playbooks/</code>, max 10 steps.</p>
          {playbooks.map((p) => (
            <div key={p.id} className="reg">
              <b>{p.name}</b>
              <ol className="small">{p.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
              <div className="small muted">Uses profile fields: {p.profile_fields.join(", ")}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
