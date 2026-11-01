import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const STATUS = {
  queued: ["Queued", "warn"], running: ["Running", "run"], awaiting_approval: ["Waiting for you", "warn"],
  missing_data: ["Missing information", "warn"], completed: ["Completed", "ok"], cancelled: ["Stopped", "bad"],
  aborted_security_risk: ["Aborted: security risk", "bad"],
};

function statusInfo(s) {
  if (s.startsWith("failed_at_step_")) return [`Failed at step ${s.split("_").pop()}`, "bad"];
  return STATUS[s] || [s, "warn"];
}

function Gate({ task, onDone }) {
  const p = task.pending;
  const [captcha, setCaptcha] = useState("");
  const [data, setData] = useState({});
  const [err, setErr] = useState("");
  const [sending, setSending] = useState(false);
  useEffect(() => { setCaptcha(""); setData({}); setErr(""); }, [p?.since]);

  async function send(body) {
    setSending(true);
    setErr("");
    try { await api.respond(task.id, body); onDone(); } catch (e) { setErr(e.message); } finally { setSending(false); }
  }
  const title = { captcha: "Solve the security check", approval: "Approve the submission", missing_data: "The portal needs more information",
    discrepancy: "The portal rejected some details", payment: "Payment page detected", captcha_page: "CAPTCHA detected" }[p.kind] || "Your input is needed";

  return (
    <div className="gate">
      <div className="gate-h">✋ {title}</div>
      <p>{p.message}</p>
      {p.kind === "captcha" && (
        <form onSubmit={(e) => { e.preventDefault(); send({ action: "captcha", captcha }); }}>
          {p.captcha_image && <img className="captcha" src={p.captcha_image} alt="Security code from the portal" />}
          <div className="inline">
            <input autoFocus value={captcha} onChange={(e) => setCaptcha(e.target.value)} placeholder="Type the characters" />
            <button className="primary" disabled={sending || !captcha}>Send to portal</button>
          </div>
        </form>
      )}
      {(p.kind === "missing_data" || p.kind === "discrepancy") && (
        <form onSubmit={(e) => { e.preventDefault(); send({ action: "provide", data }); }}>
          {(p.fields || []).map((f) => (
            <div key={f.profile} className="inline">
              <label className="lbl">{f.label}</label>
              <input value={data[f.profile] || ""} onChange={(e) => setData({ ...data, [f.profile]: e.target.value })}
                placeholder={p.kind === "discrepancy" ? "leave blank to keep" : ""} />
            </div>
          ))}
          <div className="inline">
            <button className="primary" disabled={sending}>Continue</button>
            <button type="button" className="ghost" onClick={() => send({ action: "reject" })}>Stop</button>
          </div>
        </form>
      )}
      {(p.kind === "approval" || p.kind === "payment" || p.kind === "captcha_page") && (
        <div className="inline">
          <button className="primary" disabled={sending} onClick={() => send({ action: "approve" })}>
            {p.kind === "approval" ? "Yes, submit my application" : "I have handled it, continue"}
          </button>
          <button className="ghost" disabled={sending} onClick={() => send({ action: "reject" })}>No, stop here</button>
        </div>
      )}
      {err && <p className="err">{err}</p>}
    </div>
  );
}

export default function AgentPanel({ taskId, auditId }) {
  const [task, setTask] = useState(null);
  const [error, setError] = useState("");
  const [shot, setShot] = useState(null);
  const term = useRef(null);

  async function poll() {
    try {
      const t = await api.state(taskId);
      setTask(t);
      setError("");
      return t;
    } catch (e) { setError(e.message); return null; }
  }

  useEffect(() => {
    let stop = false;
    let timer;
    const loop = async () => {
      const t = await poll();
      const done = t && (["completed", "cancelled", "aborted_security_risk"].includes(t.status) || t.status.startsWith("failed"));
      if (!stop && !done) timer = setTimeout(loop, 900);
    };
    loop();
    return () => { stop = true; clearTimeout(timer); };
  }, [taskId]);

  useEffect(() => { if (term.current) term.current.scrollTop = term.current.scrollHeight; }, [task?.logs?.length]);

  if (!task) return <div className="card"><span className="spinner" /> Starting agent… {error && <span className="err">{error}</span>}</div>;
  const [label, cls] = statusInfo(task.status);
  const latest = shot ?? task.screenshots[task.screenshots.length - 1];
  const fmt = (t) => new Date(t * 1000).toLocaleTimeString("en-GB");

  return (
    <div className="card agent">
      <div className="card-head">
        <h2>Browser agent <span className="muted small">· {task.playbook_name || "not launched"}</span></h2>
        <span className={`status ${cls}`}>{cls === "run" && <span className="pulse" />}{label}</span>
      </div>

      {task.pending && <Gate task={task} onDone={poll} />}

      {task.status === "aborted_security_risk" && (
        <div className="abort">
          <b>⛔ aborted_security_risk</b>
          <p>{task.error}</p>
          <p>The agent did not open a browser or contact any portal. Your details were not used.</p>
        </div>
      )}

      {task.status !== "aborted_security_risk" && <div className="agent-grid">
        <div>
          {task.steps.length > 0 && (
            <ol className="steps">
              {task.steps.map((s, i) => <li key={i} className={s.status}>{s.label}</li>)}
            </ol>
          )}
          <div className="terminal" ref={term} aria-live="polite">
            {task.logs.map((l, i) => (
              <div key={i} className={`ln ${l.level}`}><span className="ts">{fmt(l.t)}</span> {l.msg}</div>
            ))}
            {cls === "run" && <div className="ln cursor">▌</div>}
          </div>
          <p className="muted small">Step limit {task.max_steps} · only approved portal hosts · never pays or solves CAPTCHAs on its own</p>
        </div>
        <div>
          {latest ? (
            <figure className="shot">
              <a href={latest.url} target="_blank" rel="noreferrer"><img src={latest.url} alt={latest.label} /></a>
              <figcaption>{latest.label}</figcaption>
            </figure>
          ) : <div className="shot empty">Portal screenshots appear here</div>}
          {task.screenshots.length > 1 && (
            <div className="thumbs">
              {task.screenshots.map((s, i) => (
                <button key={i} className={latest === s ? "sel" : ""} onClick={() => setShot(s)} title={s.label}><img src={s.url} alt="" /></button>
              ))}
            </div>
          )}
        </div>
      </div>}
      {task.status === "aborted_security_risk" && (
        <div className="terminal short">
          {task.logs.map((l, i) => <div key={i} className={`ln ${l.level}`}><span className="ts">{fmt(l.t)}</span> {l.msg}</div>)}
        </div>
      )}

      {task.status === "completed" && (
        <div className="receipt">
          <div>
            <div className="muted small">Government confirmation code</div>
            <div className="code">{task.result.tracking_code}</div>
            {task.receipt && <div className="hash">Immutable record · sha256 {task.receipt.record_hash.slice(0, 24)}…</div>}
          </div>
          <div className="receipt-actions">
            {task.result.receipt_pdf && <a className="btn primary" href={task.result.receipt_pdf} download>Download portal PDF</a>}
            <button className="btn ghost" onClick={() => api.downloadReport(auditId, task.id)}>Download audit report</button>
          </div>
        </div>
      )}
      {(task.status.startsWith("failed") || task.status === "cancelled") && (
        <div className="abort"><b>{label}</b><p>{task.error}</p><p>The run trace and screenshots above are kept for review.</p>
          <button className="btn ghost" onClick={() => api.downloadReport(auditId, task.id)}>Download audit report</button></div>
      )}
      {task.status === "aborted_security_risk" && (
        <button className="btn ghost" onClick={() => api.downloadReport(auditId, task.id)}>Download audit report</button>
      )}
    </div>
  );
}
