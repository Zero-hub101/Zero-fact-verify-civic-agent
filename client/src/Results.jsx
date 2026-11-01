import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const SPEECH_LANG = { en: "en-IN", hi: "hi-IN", ta: "ta-IN", te: "te-IN", kn: "kn-IN", ml: "ml-IN", bn: "bn-IN",
  mr: "mr-IN", gu: "gu-IN", pa: "pa-IN", or: "or-IN", ur: "ur-IN" };

// Spoken reply. The voice service makes the audio only when Listen is pressed (so the verdict is not kept
// waiting); if there is no service or it fails, the browser's own voice reads the text instead.
function VoiceReply({ voice }) {
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;
  const [url, setUrl] = useState(voice.url);
  const [state, setState] = useState("idle");          // idle | loading | speaking | error
  const [voices, setVoices] = useState(() => (canSpeak ? window.speechSynthesis.getVoices() : []));
  useEffect(() => {
    if (!canSpeak) return undefined;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    window.speechSynthesis.addEventListener("voiceschanged", load);
    load();
    return () => { window.speechSynthesis.removeEventListener("voiceschanged", load); window.speechSynthesis.cancel(); };
  }, [canSpeak]);
  const tag = SPEECH_LANG[voice.lang] || voice.lang;
  const match = voices.find((v) => v.lang === tag) || voices.find((v) => v.lang.toLowerCase().startsWith(voice.lang));

  if (url) {
    return (
      <div className="voice">
        <span>🔊 {voice.lang_name}</span>
        <audio controls autoPlay src={url} preload="none" />
      </div>
    );
  }
  const browserSpeak = () => {
    const synth = window.speechSynthesis;
    if (state === "speaking") { synth.cancel(); setState("idle"); return; }
    const u = new SpeechSynthesisUtterance(voice.text);
    u.lang = tag;
    u.voice = match;
    u.onend = u.onerror = () => setState("idle");
    synth.cancel();
    synth.speak(u);
    setState("speaking");
  };
  const listen = async () => {
    if (state === "speaking") return browserSpeak();
    if (voice.service) {
      setState("loading");
      try {
        const out = await api.speak(voice.text, voice.lang);
        setUrl(out.url);
        setState("idle");
        return;
      } catch {
        if (!(canSpeak && match)) { setState("error"); return; }
      }
    }
    browserSpeak();
  };
  if (!voice.text || (!voice.service && !(canSpeak && match))) return null;
  return (
    <div className="voice">
      <button type="button" className="btn ghost" onClick={listen} disabled={state === "loading"}>
        {state === "loading" ? "Preparing audio…" : state === "speaking" ? "⏹ Stop" : `🔊 Listen (${voice.lang_name})`}
      </button>
      {state === "error" && <span className="small muted">Audio is not available right now.</span>}
    </div>
  );
}

const VERDICT = {
  authentic: { label: "Looks genuine", cls: "ok" },
  unverified: { label: "Not confirmed", cls: "warn" },
  likely_fraudulent: { label: "Likely a scam", cls: "bad" },
  off_topic: { label: "Not about a government scheme", cls: "warn" },
};

// The part an ordinary citizen reads first: what it is, why, and what to do (in their language when asked).
function PlainAnswer({ p }) {
  if (!p) return null;
  return (
    <div className="plain">
      <p className="plain-head">{p.headline}</p>
      {p.why && p.why.length > 0 && (<>
        <p className="plain-label">Why we think so</p>
        <ul>{p.why.map((w, i) => <li key={i}>{w}</li>)}</ul>
      </>)}
      {p.do && p.do.length > 0 && (<>
        <p className="plain-label">What you should do</p>
        <ul className="do">{p.do.map((d, i) => <li key={i}>{d}</li>)}</ul>
      </>)}
    </div>
  );
}

export function TrustGauge({ value, threshold }) {
  const r = 80, cx = 100, cy = 95;
  const pt = (v) => {
    const a = Math.PI * (1 - v);
    return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
  };
  const [x, y] = pt(Math.max(0.001, value));
  const [tx, ty] = pt(threshold);
  const color = value >= threshold ? "var(--ok)" : value >= 0.4 ? "var(--warn)" : "var(--bad)";
  return (
    <svg viewBox="0 0 200 120" className="gauge" role="img" aria-label={`Trust score ${Math.round(value * 100)} out of 100`}>
      <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} className="gauge-track" />
      <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`} style={{ stroke: color }} className="gauge-fill" />
      <line x1={tx} y1={ty} x2={cx + (tx - cx) * 0.78} y2={cy + (ty - cy) * 0.78} className="gauge-thr" />
      <text x={cx} y={cy - 18} textAnchor="middle" className="gauge-num">{Math.round(value * 100)}</text>
      <text x={cx} y={cy + 2} textAnchor="middle" className="gauge-sub">trust score</text>
      <text x={cx + r + 2} y={cy + 16} textAnchor="end" className="gauge-sub">100</text>
      <text x={cx - r - 2} y={cy + 16} textAnchor="start" className="gauge-sub">0</text>
    </svg>
  );
}

function Regions({ regions }) {
  return (regions || []).map((r, i) => (
    <div key={i} className="region" style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }} />
  ));
}

function ImageForensics({ m }) {
  const [overlay, setOverlay] = useState(true);
  const flagged = m.tamper_score >= 0.5;
  return (
    <div className={`media-box ${flagged ? "flagged" : ""}`}>
      <div className="media-stage">
        <div className="media-frame">
          <img src={m.media_url} alt={m.file_name} />
          {overlay && <img className="heat" src={m.heatmap_url} alt="" />}
          {overlay && <Regions regions={m.regions} />}
        </div>
        {flagged && <div className="stamp">EDITED REGION DETECTED</div>}
      </div>
      <div className="media-tools">
        <label><input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} /> Heatmap overlay</label>
        <Signals m={m} />
      </div>
    </div>
  );
}

function AiExtras({ m }) {
  const d = m.ai_detection;
  const v = m.vision;
  if (!d && !v && !m.ocr_text) return null;
  return (
    <div className="ai-extras">
      {d && (
        <div className={`ai-det ${Math.max(d.ai_generated || 0, d.deepfake || 0) >= 0.7 ? "bad" : "ok"}`}>
          <b>AI-generated check:</b> {Math.round((d.ai_generated || 0) * 100)}% AI-generated
          {d.deepfake !== null && d.deepfake !== undefined && <> · {Math.round(d.deepfake * 100)}% face deepfake</>}
          {d.frame_time !== null && d.frame_time !== undefined && <> · frame {d.frame_time}s</>}
        </div>
      )}
      {v && (
        <div className="vision">
          <b>What the image shows:</b> {v.description}
          {v.claims?.length > 0 && <div className="small">Claims: {v.claims.join(" · ")}</div>}
          {v.red_flags?.length > 0 && <div className="small bad-text">Red flags: {v.red_flags.join(" · ")}</div>}
        </div>
      )}
      {m.ocr_text && (
        <details className="ocr"><summary>Text read from the image</summary><p>{m.ocr_text}</p></details>
      )}
    </div>
  );
}

function Signals({ m }) {
  return (
    <div className="signals">
      <span className={`pill ${m.tamper_score >= 0.6 ? "bad" : m.tamper_score > 0.3 ? "warn" : "ok"}`}>
        Tamper {Math.round((m.tamper_score || 0) * 100)}%
      </span>
      {m.signals && Object.entries(m.signals).map(([k, v]) => (
        <span key={k} className="pill subtle">{k.replace("_", " ")}: {Math.round(v * 100)}%</span>
      ))}
      {m.low_resolution_confidence_degraded && <span className="pill warn">low resolution</span>}
    </div>
  );
}

function VideoForensics({ m }) {
  const vid = useRef(null);
  const [t, setT] = useState(0);
  const [sel, setSel] = useState(null);
  const frames = m.frames || [];
  const active = frames.find((f) => f.flagged && t >= f.time - 0.05);
  const anyFlag = frames.some((f) => f.flagged);
  const selected = sel !== null ? frames[sel] : null;
  return (
    <div className={`media-box ${active ? "flagged live" : ""}`}>
      <div className="media-stage">
        {selected ? (
          <>
            <div className="media-frame">
              <img src={selected.thumb_url} alt={`frame at ${selected.time}s`} />
              {selected.heatmap_url && <img className="heat" src={selected.heatmap_url} alt="" />}
              <Regions regions={selected.regions} />
            </div>
            <button className="back" onClick={() => setSel(null)}>◀ back to video</button>
          </>
        ) : (
          <video ref={vid} src={m.media_url} controls muted playsInline onTimeUpdate={(e) => setT(e.target.currentTime)} />
        )}
        {(active && !selected) && <div className="stamp">MANIPULATION FROM {active.time}s</div>}
      </div>
      {m.error ? <p className="warn-text">{m.error}</p> : (
        <>
          <div className="frames">
            {frames.map((f, i) => (
              <button key={i} className={`frame ${f.flagged ? "bad" : ""} ${sel === i ? "sel" : ""}`}
                onClick={() => { setSel(i); }} title={`${f.time}s · ${Math.round(f.score * 100)}%`}>
                <img src={f.thumb_url} alt="" />
                <span>{f.time}s</span>
              </button>
            ))}
          </div>
          <div className="media-tools">
            <span className="muted small">{anyFlag ? "Red frames: manipulation signals. Click a frame to inspect it." : "Sampled frames · click to inspect"}</span>
            <Signals m={m} />
          </div>
        </>
      )}
    </div>
  );
}

function highlight(text, flags) {
  const ev = (flags || []).map((f) => f.evidence).filter(Boolean);
  if (!ev.length) return text;
  const re = new RegExp(`(${ev.map((e) => e.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}


const STATUS_ICON = { supported: ["✓", "ok"], contradicted: ["✗", "bad"], unverified: ["?", "warn"] };
const RS_VERDICT = { authentic: "ok", misleading: "warn", fraudulent: "bad", unverifiable: "warn" };

const ROLE_LABEL = { research: "Research", translation: "Translation", speech: "Speech", voice: "Voice", ocr: "OCR",
  image_ai: "AI-image check", vision: "Vision", review: "Review" };

function TeamStrip({ team }) {
  if (!team || !team.length) return null;
  return (
    <div className="team-strip">
      <span className="muted small">AI models used:</span>
      {team.map((c, i) => (
        <span key={i} className={`team-chip ${c.error ? "err" : c.specialist ? "spec" : "stand"}`}
          title={c.error || c.note || `${c.seconds}s`}>
          <b>{ROLE_LABEL[c.role] || c.role}</b> {c.model}{!c.specialist && <i> stand-in</i>}
        </span>
      ))}
    </div>
  );
}

function Research({ r }) {
  const rs = r.research;
  if (!rs || rs.status === "skipped") {
    return (
      <div className="card research off">
        <h3>AI research</h3>
        <p className="muted small">{(rs && rs.reason) || "AI research was not run for this message."}</p>
      </div>
    );
  }
  if (rs.error) return <div className="card research"><h3>AI research</h3><p className="warn-text">{rs.error}</p></div>;
  const local = rs.localized && rs.localized.lang !== "en" ? rs.localized : null;
  return (
    <div className="card research">
      <div className="card-head">
        <h3>AI research {rs.grounded
          ? <span className="muted small">· live web search, every finding linked to its source</span>
          : <span className="muted small">· AI reasoning without live web sources</span>}</h3>
        <div>
          <span className="pill subtle">{rs.language.native} detected</span>
          <span className="pill subtle" title={rs.api}>research: {rs.model} · {rs.seconds}s</span>
        </div>
      </div>
      <div className="rs-top">
        <span className={`verdict ${RS_VERDICT[rs.verdict]}`}>{rs.verdict}</span>
        {rs.already_debunked && <span className="pill bad">Already debunked by fact-checkers</span>}
        {!rs.grounded && <span className="pill warn">{rs.search_unavailable ? "Web search not available on this key: low weight" : "No web sources returned: low weight"}</span>}
      </div>
      {local && (
        <div className="local" lang={local.lang}>
          <p className="big-local">{local.summary}</p>
          {local.advice && <p className="advice">👉 {local.advice}</p>}
          <span className="muted small">{local.lang_name} reply by the translation model</span>
        </div>
      )}
      {rs.summary && <p className={local ? "muted small" : ""}>{rs.summary}</p>}
      {!local && rs.advice && <p className="advice">👉 {rs.advice}</p>}
      {rs.claim_en && rs.language.code !== "en" && (
        <details className="translation"><summary>English translation of the claim</summary><p>{rs.claim_en}</p></details>
      )}
      <ul className="evidence">
        {rs.findings.map((f, i) => {
          const [icon, cls] = STATUS_ICON[f.status];
          return (
            <li key={i} className={cls}>
              <span className="ev-icon">{icon}</span>
              <div>
                <b>{f.point}</b>
                <p>{f.evidence}</p>
                {f.source_ids.length > 0 && (
                  <div className="proof">Proof: {f.source_ids.map((sid) => rs.sources[sid] && (
                    <a key={sid} href={rs.sources[sid].url} target="_blank" rel="noreferrer" className={`src ${rs.sources[sid].trust}`}>
                      [{sid + 1}] {rs.sources[sid].title}</a>
                  ))}</div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {rs.sources.length > 0 && (
        <div className="sources">
          <div className="col-h">Sources found by Google Search</div>
          <ol>
            {rs.sources.map((src, i) => (
              <li key={i}>
                <a href={src.url} target="_blank" rel="noreferrer">{src.title}</a>
                <span className={`pill ${src.trust === "official" ? "ok" : src.trust === "fact_checker" ? "ok" : "subtle"}`}>
                  {src.trust === "official" ? "official" : src.trust === "fact_checker" ? "fact-checker" : "web"}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {rs.search_queries.length > 0 && (
        <p className="muted small">Searched: {rs.search_queries.map((q, i) => <code key={i} className="q">{q}</code>)}</p>
      )}
    </div>
  );
}

function ClaimMatch({ r }) {
  const t = r.text || {};
  const s = r.matched_scheme;
  if (!t.present) return null;
  return (
    <div className="card">
      <h3>Claim vs official record</h3>
      <div className="compare">
        <div>
          <div className="col-h">What the claim says</div>
          <p className="claim-text">{highlight(r.claim_text, t.scam_flags)}</p>
          {(t.sources || []).map((src, i) => (
            <span key={i} className={`pill ${src.trust === "official" ? "ok" : src.trust === "low" ? "bad" : "warn"}`}>{src.host}: {src.trust}</span>
          ))}
        </div>
        <div>
          <div className="col-h">Trusted registry</div>
          {s ? (
            <dl className="record">
              <dt>Scheme</dt><dd>{s.name}</dd>
              <dt>Benefit</dt><dd>Rs {s.benefit_amount.toLocaleString("en-IN")} {s.benefit_period}</dd>
              <dt>Application fee</dt><dd>{s.application_fee ? `Rs ${s.application_fee}` : "Free"}</dd>
              {s.income_limit != null && <><dt>Income limit</dt><dd>Rs {s.income_limit.toLocaleString("en-IN")}</dd></>}
              {s.deadline && <><dt>Deadline</dt><dd>{new Date(s.deadline).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</dd></>}
              <dt>Official sites</dt><dd>{s.official_domains.filter((d) => !/localhost|127\./.test(d)).join(", ")}</dd>
            </dl>
          ) : <p className="muted">No matching scheme in the registry.</p>}
        </div>
      </div>
      <ul className="checks">
        {(t.confirmations || []).map((c, i) => <li key={`c${i}`} className="ok">✓ {c.detail}</li>)}
        {(t.contradictions || []).map((c, i) => <li key={`x${i}`} className="bad">✗ {c.detail}</li>)}
        {(t.scam_flags || []).map((h, i) => <li key={`s${i}`} className="warn">⚠ {h.label} <span className="muted">“{h.evidence}”</span></li>)}
      </ul>
      {r.ai_review && r.ai_review.verdict && r.ai_review.status !== "skipped" && (
        <div className="ai-review"><b>AI review ({r.ai_review.model}):</b> {r.ai_review.verdict}. {(r.ai_review.reasons || []).join(" ")}</div>
      )}
    </div>
  );
}

export default function Results({ data, onLaunch, launching }) {
  const r = data.result;
  const v = VERDICT[r.verdict];
  const findings = (r.media || []).flatMap((m) => m.findings || []);
  return (
    <div className="results">
      <div className="card summary">
        {r.verdict === "off_topic"
          ? <div className="gauge-off">?</div>
          : <TrustGauge value={r.authenticity} threshold={r.threshold} />}
        <div className="summary-body">
          <span className={`verdict ${v.cls}`}>{v.label}</span>
          <PlainAnswer p={r.plain} />
          {r.matched_scheme && <p className="small">Scheme: <b>{r.matched_scheme.name}</b></p>}
          {r.language && r.language.code !== "en" && <p className="small">Message language: <b>{r.language.native}</b> ({r.language.name})</p>}
          {r.voice && <VoiceReply voice={r.voice} />}
          {r.warnings.map((w, i) => <p key={i} className="warn-text small">⚠ {w}</p>)}
          <div className="launch">
            {r.verdict === "off_topic" ? null
            : r.verdict === "authentic" && r.matched_scheme && !r.matched_scheme.playbook ? (
              <a className="primary big link-btn" href={r.matched_scheme.official_url || `https://${r.matched_scheme.official_domains[0]}`}
                target="_blank" rel="noreferrer">Open the official website ↗</a>
            ) : r.agentAllowed ? (
              <button className="primary big" disabled={launching || !r.has_profile} onClick={onLaunch}>
                {launching ? "Starting agent…" : "2 · Let the agent fill the application (practice portal)"}
              </button>
            ) : (
              <div className="locked">
                <b>🔒 Form-filling helper switched off.</b> This message did not pass our checks, so we will not use your details anywhere.
                <button className="ghost" disabled={launching} onClick={onLaunch}>Show what happens if I try anyway</button>
              </div>
            )}
            {r.agentAllowed && !r.has_profile && <p className="warn-text small">To let the helper fill the form, add your details above and check again.</p>}
          </div>
        </div>
      </div>

      <details className="tech">
      <summary>Technical details for fact-checkers (scores, image forensics, AI research, sources)</summary>
      <div className="card kv-card">
        <span>Trust score <b>{Math.round(r.authenticity * 100)}/100</b> (needs {Math.round(r.threshold * 100)} to pass)</span>
        <span>Manipulation score <b>{r.manipulationScore.toFixed(2)}</b></span>
        <span>Edited or AI-made media <b className={r.deepfakeDetected ? "bad-text" : ""}>{r.deepfakeDetected ? "yes" : "no"}</b></span>
        {r.audit_id && <span>Audit ID <b><code>{r.audit_id}</code></b> · <a href={`/api/audit/${r.audit_id}/report`} target="_blank" rel="noreferrer">report</a></span>}
        {r.seconds != null && <span>Checked in <b>{r.seconds}s</b></span>}
      </div>
      {(r.media || []).length > 0 && (
        <div className="card">
          <h3>Media forensics</h3>
          {r.media.map((m, i) => (
            <div key={i}>
              {m.kind === "image" ? <ImageForensics m={m} /> : <VideoForensics m={m} />}
              <AiExtras m={m} />
              {m.transcript && (
                <details className="ocr" open><summary>Speech in the video{m.transcript_language ? ` (${m.transcript_language})` : ""}</summary>
                  <p>{m.transcript}</p>{m.transcript_en && <p className="muted">{m.transcript_en}</p>}</details>
              )}
            </div>
          ))}
          <ul className="findings">{findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
          <p className="muted small">Forensic scores are signals, not proof: compression-history (JPEG ghost), clone detection, metadata and frame-consistency checks.</p>
        </div>
      )}

      <TeamStrip team={r.ai_team} />
      <Research r={r} />
      <ClaimMatch r={r} />
      </details>
    </div>
  );
}
