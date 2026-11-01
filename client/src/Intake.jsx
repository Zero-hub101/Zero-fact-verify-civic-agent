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

  const addFiles = (list) => setFiles((f) => [...f, ...Array.from(list)].slice(0, 5));

  async function verify(ingestPromise) {
    setBusy(true);
    setError("");
    try {
      setStage("Uploading and mapping inputs…");
      const ing = await ingestPromise;
      setStage("Researching the claim on the web, checking facts and running media forensics…");
      const result = await api.forensics(ing.audit_id);
      onVerified({ ingest: ing, result });
    } catch (e) {
      setError(e.message);
    } finally {
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
      genuine: "Post-Matric Merit Scholarship 2026-27: Rs 12,000 per year for students with family income up to Rs 2,50,000. Apply free on the official portal before 15 December 2026.",
      fraud_hindi: "जरूरी सूचना!! पोस्ट मैट्रिक मेरिट छात्रवृत्ति में सभी छात्रों को ₹50,000 मिलेंगे। 24 घंटे में ₹499 पंजीकरण शुल्क UPI 9876543210@ybl पर भेजें और OTP व्हाट्सएप पर शेयर करें। कोई दस्तावेज़ नहीं चाहिए!",
      fraud: "URGENT!! PM Merit Scholarship of Rs 50,000 for ALL students. Pay Rs 499 registration fee to UPI 9876543210@ybl and share the OTP on WhatsApp within 24 hours. No documents needed. Forward to 10 groups!",
    };
    setText(texts[scenario]);
    setUrl("");
    setFiles([]);
    verify(api.demo(scenario, media, replyLang));
  }

  return (
    <form className="card intake" onSubmit={submit}>
      <div className="card-head">
        <h2>1 · What did you receive?</h2>
        <div className="demo-btns">
          <span className="muted small">Demo cases:</span>
          <button type="button" className="chip ok" disabled={busy} onClick={() => loadDemo("genuine", "video")}>Genuine notice</button>
          <button type="button" className="chip bad" disabled={busy} onClick={() => loadDemo("fraud", "video")}>Deepfake video</button>
          <button type="button" className="chip bad" disabled={busy} onClick={() => loadDemo("fraud", "image")}>Edited image</button>
          <button type="button" className="chip bad" disabled={busy} onClick={() => loadDemo("fraud_hindi", "image")}>हिन्दी forward</button>
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
        <button className="primary" disabled={busy}>{busy ? "Verifying…" : "Verify claim"}</button>
        {stage && <span className="stage"><span className="spinner" /> {stage}</span>}
      </div>
    </form>
  );
}
