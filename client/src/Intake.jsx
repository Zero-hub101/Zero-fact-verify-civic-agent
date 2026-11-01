import { useState } from "react";
import { api } from "./api.js";

const PROFILE_FIELDS = [
  ["full_name", "Full name", "text"],
  ["dob", "Date of birth", "date"],
  ["email", "Email", "email"],
  ["phone", "Mobile number", "tel"],
  ["state", "State", "text"],
  ["annual_income", "Annual family income (Rs)", "text"],
  ["course", "Course", "text"],
  ["institution", "Institution", "text"],
  ["id_last4", "National ID: last 4 digits only", "text"],
];
export const LANGS = [
  ["auto", "Same as the message"], ["en", "English"], ["hi", "हिन्दी Hindi"], ["ta", "தமிழ் Tamil"],
  ["te", "తెలుగు Telugu"], ["kn", "ಕನ್ನಡ Kannada"], ["ml", "മലയാളം Malayalam"], ["bn", "বাংলা Bengali"],
  ["mr", "मराठी Marathi"], ["gu", "ગુજરાતી Gujarati"], ["pa", "ਪੰਜਾਬੀ Punjabi"], ["or", "ଓଡ଼ିଆ Odia"], ["ur", "اردو Urdu"],
];
export const EMPTY_PROFILE = Object.fromEntries(PROFILE_FIELDS.map(([k]) => [k, ""]));

export default function Intake({ onVerified, busy, setBusy, setError }) {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [transcript, setTranscript] = useState("");
  const [files, setFiles] = useState([]);
  const [profile, setProfile] = useState(EMPTY_PROFILE);
  const [showProfile, setShowProfile] = useState(true);
  const [drag, setDrag] = useState(false);
  const [stage, setStage] = useState("");
  const [replyLang, setReplyLang] = useState("auto");

  // Enable the button only for something worth checking (8+ letters/digits, a link, a transcript or a file).
  const ready = files.length > 0 || url.trim() || transcript.trim() ||
    [...text].filter((c) => /[\p{L}\p{N}]/u.test(c)).length >= 8;
  const addFiles = (list) => setFiles((f) => [...f, ...Array.from(list)].slice(0, 5));

  async function verify(ingestPromise) {
    setBusy(true);
    setError("");
    // Progress messages so a slow check never looks stuck (the free server can take ~50 s to wake up).
    const steps = [
      [0, "Reading your message…"],
      [3000, "Checking it against official scheme rules and scam warning signs…"],
      [8000, "AI research and photo/video checks are running. This usually takes 10–30 seconds…"],
      [25000, "Still working. The free server may be waking up; this can take up to a minute the first time."],
      [60000, "Taking longer than usual. Please keep this page open; your result will appear here."],
    ];
    const timers = steps.map(([ms, msg]) => setTimeout(() => setStage(msg), ms));
    try {
      const ing = await ingestPromise;
      const result = await api.forensics(ing.audit_id);
      onVerified({ ingest: ing, result });
    } catch (e) {
      setError(e.message === "Failed to fetch"
        ? "Could not reach the server. Please check your internet connection and try again."
        : e.message);
    } finally {
      timers.forEach(clearTimeout);
      setBusy(false);
      setStage("");
    }
  }

  function submit(e) {
    e.preventDefault();
    const fd = new FormData();
    fd.append("text", text);
    fd.append("url", url);
    fd.append("transcript", transcript);
    fd.append("reply_language", replyLang);
    if (Object.values(profile).some((v) => v.trim())) fd.append("profile", JSON.stringify(profile));
    files.forEach((f) => fd.append("files", f));
    verify(api.ingest(fd));
  }

  async function loadDemo(scenario, media) {
    const p = await api.demoProfile().catch(() => null);
    if (p) setProfile(p);
    const texts = {
      genuine: "Central Sector Scheme of Scholarship 2026-27: Rs 12,000 per year for undergraduate students above the 80th percentile in Class 12 with family income up to Rs 4.5 lakh. Apply free on the National Scholarship Portal, scholarships.gov.in.",
      fraud_hindi: "जरूरी सूचना!! केंद्रीय क्षेत्र छात्रवृत्ति योजना में सभी छात्रों को ₹50,000 मिलेंगे। 24 घंटे में ₹499 पंजीकरण शुल्क UPI 9876543210@ybl पर भेजें और OTP व्हाट्सएप पर शेयर करें। कोई दस्तावेज़ नहीं चाहिए!",
      fraud: "URGENT!! Central Sector Scholarship of Rs 50,000 for ALL students. Pay Rs 499 registration fee to UPI 9876543210@ybl and share the OTP on WhatsApp within 24 hours. No documents needed. Forward to 10 groups!",
    };
    setText(texts[scenario]);
    setUrl("");
    setFiles([]);
    verify(api.demo(scenario, media, replyLang));
  }

  return (
    <form className="card intake" onSubmit={submit}>
      <div className="intro">
        <p><b>Got a message about a government scheme, scholarship or benefit?</b> Paste it here (any Indian language,
          or a photo or video of it). In a few seconds we tell you, in simple words, whether it is real or a scam and what to do.</p>
        <p className="muted small">If it is real, an AI helper can fill the application form for you; it always stops and asks you before submitting.</p>
        <p className="small"><b>New here? Try it in 60 seconds:</b> click <b>💬 Hindi WhatsApp scam</b> below, read the answer and press Listen;
          then click <b>✅ Real scholarship notice</b> and let the helper fill the practice form.</p>
      </div>
      <div className="card-head">
        <h2>1 · What did you receive?</h2>
        <div className="demo-btns">
          <span className="muted small">Try an example:</span>
          <button type="button" className="chip ok" disabled={busy} onClick={() => loadDemo("genuine", "video")}>✅ Real scholarship notice</button>
          <button type="button" className="chip bad" disabled={busy} onClick={() => loadDemo("fraud", "video")}>🎬 Edited video</button>
          <button type="button" className="chip bad" disabled={busy} onClick={() => loadDemo("fraud", "image")}>🖼️ Edited photo</button>
          <button type="button" className="chip bad" disabled={busy} onClick={() => loadDemo("fraud_hindi", "image")}>💬 Hindi WhatsApp scam</button>
        </div>
      </div>

      <div className="claim-head">
        <label className="lbl" htmlFor="claim">Message, announcement or caption <span className="muted">· any Indian language</span></label>
        <label className="lang-pick">Answer in
          <select value={replyLang} onChange={(e) => setReplyLang(e.target.value)}>
            {LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </label>
      </div>
      <textarea id="claim" rows={4} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Paste the forwarded message or the words spoken in the video…" />

      <div className="row2">
        <div>
          <label className="lbl" htmlFor="url">Link (optional)</label>
          <input id="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        </div>
        <div>
          <label className="lbl" htmlFor="tr">Video transcript (optional)</label>
          <input id="tr" value={transcript} onChange={(e) => setTranscript(e.target.value)} placeholder="What is said in the clip" />
        </div>
      </div>

      <div className={`drop ${drag ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}>
        <input id="files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.mp4,.mov,.webm"
          onChange={(e) => addFiles(e.target.files)} />
        <label htmlFor="files"><b>Drop an image or video</b> or click to choose · PNG, JPG, MP4 up to 50 MB</label>
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f, i) => (
              <li key={i}>{f.name} <span className="muted">({Math.round(f.size / 1024)} KB)</span>
                <button type="button" className="link" onClick={() => setFiles(files.filter((_, j) => j !== i))}>remove</button></li>
            ))}
          </ul>
        )}
      </div>

      <button type="button" className="collapse" onClick={() => setShowProfile(!showProfile)}>
        {showProfile ? "▾" : "▸"} Your details for the application <span className="muted small">(encrypted, deleted 24 h after the task)</span>
      </button>
      {showProfile && (
        <div className="profile-grid">
          {PROFILE_FIELDS.map(([k, label, type]) => (
            <div key={k}>
              <label className="lbl" htmlFor={`p_${k}`}>{label}</label>
              <input id={`p_${k}`} type={type} value={profile[k]} maxLength={k === "id_last4" ? 4 : 160}
                onChange={(e) => setProfile({ ...profile, [k]: e.target.value })} />
            </div>
          ))}
        </div>
      )}

      <div className="actions">
        <button className="primary" disabled={busy || !ready}
          title={ready ? "" : "Paste the message you received, add a link, or upload a photo or video"}>
          {busy ? "Checking…" : "Check this message"}</button>
        {stage && <span className="stage"><span className="spinner" /> {stage}</span>}
      </div>
    </form>
  );
}
