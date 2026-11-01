import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, getToken, setToken } from "./api.js";
import Intake from "./Intake.jsx";
import Results from "./Results.jsx";
import AgentPanel from "./AgentPanel.jsx";
import Auditor from "./Auditor.jsx";
import "./styles.css";

function App() {
  const [view, setView] = useState("citizen");
  const [health, setHealth] = useState(null);
  const [data, setData] = useState(null);
  const [taskId, setTaskId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const [token, setTok] = useState(getToken());

  useEffect(() => { api.health().then(setHealth).catch((e) => setError(`Backend not reachable: ${e.message}`)); }, []);

  async function launch() {
    setLaunching(true);
    setError("");
    try {
      const t = await api.run(data.ingest.audit_id);
      setTaskId(t.id);
      setTimeout(() => document.getElementById("agent")?.scrollIntoView({ behavior: "smooth" }), 100);
    } catch (e) { setError(e.message); } finally { setLaunching(false); }
  }

  async function openAudit(auditId, tId) {
    const a = await api.audit(auditId);
    setData({ ingest: { audit_id: auditId }, result: { ...a.result, has_profile: !!a.profile_id } });
    setTaskId(tId || null);
    setView("citizen");
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <div className="logo">FV</div>
          <div><h1>FactVerify <span>Civic Agent</span></h1><p>Check it's real. Then apply safely.</p></div>
        </div>
        <nav>
          <button className={view === "citizen" ? "on" : ""} onClick={() => setView("citizen")}>Verify &amp; apply</button>
          <button className={view === "auditor" ? "on" : ""} onClick={() => setView("auditor")}>Fact-checker console</button>
        </nav>
        <div className="health">
          {health ? (
            <>
              <span className="dot ok" /> Online
              {health.features.auth_required && (
                <input className="token" type="password" placeholder="API token" value={token}
                  onChange={(e) => { setTok(e.target.value); setToken(e.target.value); }} />
              )}
            </>
          ) : <><span className="dot bad" /> Connecting…</>}
        </div>
      </header>

      {error && <div className="banner err" role="alert">{error} <button className="link" onClick={() => setError("")}>dismiss</button></div>}

      <main>
        {view === "citizen" ? (
          <>
            <Intake busy={busy} setBusy={setBusy} setError={setError}
              onVerified={(d) => { setData(d); setTaskId(null); setTimeout(() => document.getElementById("results")?.scrollIntoView({ behavior: "smooth" }), 100); }} />
            <div id="results">
              {busy && !data && <div className="card skeleton">Analysing…</div>}
              {data && <Results data={data} onLaunch={launch} launching={launching} />}
            </div>
            <div id="agent">{taskId && data && <AgentPanel key={taskId} taskId={taskId} auditId={data.ingest.audit_id} />}</div>
          </>
        ) : <Auditor onOpen={openAudit} />}
      </main>
      <footer className="disclaimer">
        FactVerify is an independent student project (FORGE '26). It is <b>not</b> a government website and is not affiliated
        with or endorsed by any government body. Always apply only on official websites ending in .gov.in or .nic.in.
        Scam already happened? Call 1930 or visit cybercrime.gov.in. Our checks give strong signals, not legal proof.
        Your personal details are encrypted and deleted automatically after 24 hours.
      </footer>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
