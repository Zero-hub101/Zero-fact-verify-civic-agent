# FactVerify Civic Agent

Check whether a public-service claim is real, then let a browser agent complete the official application, with the citizen approving every consequential step.

- **AI team**: several AI models work together, each with one job: research, translation, speech or review. Each job is assigned in `.env`, so a specialist model can be plugged in without touching the rest of the app.
- **Research (any Indian language)**: Google Gemini 4 Argon searches the live web with Grounding with Google Search, checks every detail against official sites and fact-checkers, and links each finding to the page that proves it. It answers in the citizen's language.
- **Verify**: claim text, links, images and videos are checked in parallel against a trusted scheme registry, scam-pattern rules and media forensics. The result is a 0–1 trust score with `manipulationScore` and `deepfakeDetected`.
- **Gate**: the agent only launches above the 0.75 threshold. Manipulated media aborts with `aborted_security_risk` and no browser is opened.
- **Execute**: a Playwright agent runs at most 10 steps on approved hosts, pausing for the CAPTCHA, the final-submit approval, missing data, portal errors and payment pages.
- **Receipt**: the confirmation code and the portal's PDF are stored as a hash-chained, append-only record, and a Markdown provenance report can be downloaded.

Stack: React dashboard (prebuilt in `frontend/dist`) · FastAPI · Playwright · SQLite · AES-256-GCM.

---

## Run it

Requires **Python 3.10+**. You don't need Node, because the dashboard is already built. ffmpeg is optional and enables video forensics.

**Windows:** double-click `start.bat`.
**macOS / Linux:** `./start.sh`

Or manually:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. API docs are at http://127.0.0.1:8000/docs and the sandbox portal is at http://127.0.0.1:8000/portal/.

**Turn on live research:** get a free key at https://aistudio.google.com/apikey, copy `.env.example` to `.env` and set `GEMINI_API_KEY=...`. The header then shows "Live research: Gemini".

Other optional settings in `.env`: Set `FACTVERIFY_ENCRYPTION_KEY` for a stable AES key; without it, a development key is generated in `backend/runtime/`. Add `ANTHROPIC_API_KEY` to get a Claude second opinion on each claim. Set `AGENT_HEADLESS=false` to watch the agent drive a visible Chrome window.

Optional extras: **ffmpeg** (`winget install ffmpeg` / `brew install ffmpeg`) for video. `pip install pytesseract` plus the Tesseract program reads text from uploaded images. `pip install faster-whisper` transcribes video speech.

## Test

```bash
cd backend
python -m pytest -v
```

| Test | Spec item |
|---|---|
| `test_health` | AC_01 – `GET /api/health` → 200 `healthy` |
| `test_happy_path` | Scenario 1 – genuine video + profile → agent completes → `REC-NNNNN` + PDF + receipt |
| `test_fraud_abort[jpg/mp4]` | Scenario 2 – tampered media → `manipulationScore ≥ 0.75`, `deepfakeDetected`, `aborted_security_risk`, no browser |
| `test_missing_profile_field_pauses` | Missing field → `missing_data`, field highlighted, resumes after input |
| `test_portal_discrepancy_pauses` | Portal rejects data → `awaiting_approval` with the portal's message |
| `test_portal_unreachable_retries_then_fails` | Timeout → checkpoint, one retry → `failed_at_step_1`, trace kept |
| `test_low_resolution_warning` | < 240p → `low_resolution_confidence_degraded` |
| `test_profile_encrypted_at_rest` | No personal data in plain text in the database |
| `test_receipts_are_immutable` | UPDATE/DELETE on receipts blocked; hash chain verifies |
| `test_validation_errors` | Empty input, full national ID, bad file type rejected |
| `test_research.py` (9 tests) | Gemini parsing for both API formats, each finding linked to its proof, Hindi translation feeding the rule engine, role routing, plugging in a specialist translation model, error handling (network mocked) |

## 3-minute demo script

1. **Fraud first.** Click **Deepfake video**. The trust score drops to about 14, scam phrases are highlighted, the claim contradicts the registry on amount and fee, and the frame strip turns red at 1.25 s. Click the red frame to see the replaced region.
2. Click **Try to launch anyway**. The result is `aborted_security_risk`: no browser opens and no data is used.
3. Click **Edited image**. The heatmap boxes exactly the two pasted-in lines.
4. **Genuine case.** Click **Genuine notice**. Trust is about 99 and every fact matches. Click **Apply on the official portal**. The live terminal and screenshots show the agent logging in and filling the form.
5. The agent pauses for the **CAPTCHA**, which you type, then asks for **approval to submit**, which you give. It returns `REC-xxxxx`, the portal PDF and an immutable receipt hash.
6. **Multi-language:** click **हिन्दी forward**. The Hindi message is detected and translated, and the verdict and advice appear in Hindi. Each contradicted fact has a clickable proof link from Google Search, such as PIB Fact Check or the official portal. Use **Answer in** to switch the reply to Tamil, Telugu or another language.
7. Open the **Fact-checker console** for the audit log, registry, playbooks, receipt-chain check and `report.md` export.

To show `missing_data`, clear "National ID: last 4 digits" before verifying.

## AI team (multi-model)

| Role | Job | Default model | Setting |
|---|---|---|---|
| research | Live web research; every finding linked to its source | **Gemini 4 Argon** with Grounding with Google Search (specialist) | `AI_RESEARCH=gemini` |
| translation | Claim → English for the fact checks; verdict → citizen's language | Gemini Flash as a stand-in until a language specialist is added | `AI_TRANSLATION=gemini` |
| speech | Audio in videos → text, any language | Whisper (offline, if installed), else Gemini as a stand-in | `AI_SPEECH=whisper,gemini` |
| review | Independent second opinion | Claude (if `ANTHROPIC_API_KEY` is set) | `AI_REVIEW=claude` |

- **Efficient:** when the same model holds research and translation, the localised verdict is written in the same call, saving a round trip. When a specialist translation model is assigned, Gemini only researches.
- **Visible:** the header, each result and the Fact-checker console show which model did each job. The audit report lists the models used and their timings.
- **Adding a model:**
  1. Copy `backend/app/ai/providers/_template.py`.
  2. Implement `translate()` and/or `transcribe()`.
  3. Add it to `PROVIDERS` in `backend/app/ai/router.py`.
  4. Set `AI_TRANSLATION=<id>` / `AI_SPEECH=<id>`.
  
  Nothing else changes. `tests/test_research.py::test_specialist_model_plugs_in` proves this with a dummy specialist.

## How verification works

| Signal | Technique | File |
|---|---|---|
| Registry match | Token coverage + aliases against `data/registry.json` | `forensics/text.py` |
| Fact check | Extracts amounts (Rs, lakh, crore), fees, income limits and dates, and compares them to the official record | `forensics/text.py` |
| Scam patterns | Upfront fee, OTP request, personal UPI, WhatsApp/Telegram, urgency, guaranteed approval, chain-forward, short links | `data/scam_patterns.json` |
| Source trust | Official domains (`*.gov.in`, `*.nic.in`…) vs shorteners/messaging hosts | `data/trusted_domains.json` |
| Image splice | **JPEG ghost** (Farid 2009): pasted content lacks the compression history of the rest of the image | `forensics/media.py` |
| Clone | Duplicated textured blocks at a consistent offset | `forensics/media.py` |
| Metadata | Editing or AI-generation software, AI prompt chunks, C2PA manifests | `forensics/media.py` |
| Video | Frames sampled with ffmpeg; detects a localised region changing while the rest of the frame stays consistent (content replaced mid-clip), plus per-frame splice checks | `forensics/media.py` |
| Live web research | Gemini (`gemini-4-argon`, falling back to `gemini-3.8-flash`, then `gemini-2.5-pro`) with Grounding with Google Search. It prefers `*.gov.in`, PIB Fact Check and Indian fact-checkers, and returns findings, sources, search queries and an already-debunked flag. Each finding is linked to the citation span that supports it | `ai/providers/gemini.py` |
| Languages | Offline script detection (Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati, Punjabi, Odia, Urdu). Gemini translates the claim so the English rule engine and registry can check it, and writes the verdict and advice in the chosen language. Scam rules also include Hindi, Tamil and Telugu keywords | `forensics/language.py` |
| Speech | Video audio is extracted with ffmpeg and sent to the speech-role model | `ai/router.py` |
| AI review (optional) | Claude compares the claim with the official record | `ai/providers/claude.py` |

Text score: a weighted mix of rules (0.45), Gemini research (0.40 when backed by sources, 0.15 when not) and Claude (0.15). It is capped at 0.3 when grounded research says fraudulent, and at 0.25 when the claim is already debunked.
Overall score: `0.5 × text + 0.5 × (1 − media tamper)`. It is capped at 0.3 when manipulated media is found and at 0.45 on a high-severity contradiction.

## Adding a real scheme or portal

- **Scheme:** add an entry to `backend/data/registry.json` with figures from the official notification and the `playbook` id to use.
- **Portal:** copy `backend/app/agent/playbooks/sandbox_scholarship.json`, set `base_url` and `allowed_hosts`, and map each form field to a profile field. A playbook can have at most 10 steps. The actions are `goto`, `fill_form`, `click`, `human_captcha`, `approval_gate`, `extract` and `download`. Only automate portals whose terms allow assisted access. CAPTCHAs always go to the human.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health and feature flags |
| POST | `/api/audit/ingest` | F1 – multipart: `text`, `url`, `transcript`, `profile` (JSON), `files[]` |
| POST | `/api/audit/forensics` | F2 – `{audit_id}` → scores, findings, heatmaps |
| POST | `/api/tasks/run` | F3 – `{audit_id}` → starts the agent or returns `aborted_security_risk` |
| GET | `/api/tasks/{id}/state` | F4 – status, live logs, screenshots, pending approval |
| POST | `/api/tasks/{id}/respond` | F4 – `{action: approve\|reject\|captcha\|provide, captcha?, data?}` |
| POST | `/api/tasks/{id}/complete` | F5 – immutable receipt (idempotent) |
| GET | `/api/audit/{id}/report` | Markdown provenance report |
| GET | `/api/audits`, `/api/tasks`, `/api/registry`, `/api/playbooks`, `/api/receipts/verify` | Fact-checker console |
| POST | `/api/demo/{genuine\|fraud}?media=video\|image` | Load a demo case |

## Security and privacy

- Profiles are encrypted with AES-256-GCM. Only the last 4 digits of a national ID are accepted. Profiles are wiped 24 h after a task ends (the check runs every 10 minutes).
- Agent logs mask names, contact details, date of birth and ID digits.
- The agent never pays, never solves CAPTCHAs, and never navigates outside `allowed_hosts`. Final submission requires explicit approval.
- Set `FACTVERIFY_API_TOKEN` to require a token on every `/api` call.
- Receipts are append-only: SQLite triggers block UPDATE/DELETE and records are SHA-256 hash-chained.

## Known limitations

- Forensics produce **signals, not proof**. JPEG-ghost detection needs a JPEG with prior compression. Heavily re-encoded social-media video and fully AI-generated faces need a trained deepfake model, which can be added in `forensics/media.py`.
- The registry ships with **sample entries**. Replace them with official figures before real use.
- The bundled portal is a **sandbox**. Live portals need their own playbook and permission.
- SQLite suits a single machine. For production, move `db.py` to PostgreSQL.
- Live research needs `GEMINI_API_KEY` and internet. Without it, the app falls back to the registry and rules. Google bills grounded searches per query on Gemini 3+ models, so research runs once per claim.
- Speech transcription uses Gemini (or local faster-whisper). Image OCR needs Tesseract.

## Rebuilding the dashboard (only if you edit `frontend/src`)

```bash
cd frontend && npm install && npm run build
```
