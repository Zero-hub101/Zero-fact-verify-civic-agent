# FactVerify Civic Agent

**Got a WhatsApp forward about a scholarship, pension or government scheme? Paste it in (any Indian language, or a photo or video of it). FactVerify tells you in simple words whether it is real or a scam, why, and what to do. If it is real, an AI helper can fill the application form for you, and it always stops and asks before submitting.**

**🔗 Live demo:** https://factverify-civic-agent.onrender.com (free server: the first visit after a quiet spell can take ~50 s to wake up) · **🎬 Demo video:** [MP4](docs/FactVerify_demo.mp4) · **📊 Deck:** [PDF](docs/FactVerify_Civic_Agent_Deck.pdf) · **Health check:** `/health`

## How to evaluate (2 minutes)

1. Open the live demo and click **💬 Hindi WhatsApp scam**. In about 10 seconds you get "This looks like a scam", the reasons in plain words, what to do, and a spoken reply in Hindi (press **Listen**).
2. Click **✅ Real scholarship notice**. It is matched to the real Central Sector Scheme of Scholarship and passes. Click **Let the agent fill the application**: the agent fills a practice copy of the form, stops for you to type the security code, then asks for approval before submitting.
3. Click **🖼️ Edited photo**, then open **Technical details** to see the highlighted pasted-in area, the AI team that worked on it, and the sources.
4. Try your own text, e.g. a PM-KISAN or Ayushman card message, or a link like `http://scholarship-gov-in.help`.

## Verdicts and thresholds (reproducible)

| Verdict | Shown to the citizen | Rule |
|---|---|---|
| `authentic` | "This looks genuine." | trust score ≥ 0.75 (the agent may run only here, and only for schemes with a playbook) |
| `unverified` | "We could not confirm this. Be careful." | 0.40 ≤ trust < 0.75 |
| `likely_fraudulent` | "This looks like a scam. Do not act on it." | trust < 0.40, or manipulated media |
| `off_topic` | "This does not look like a message about a government scheme." | no scheme, no warning sign, no civic words, no media; AI research and review are skipped (`status: "skipped"`) |

Trust score = weighted mix of the rule engine (45%), AI research (40% with live sources, 15% without) and the independent AI review (15%), then lowered by media forensics. Every response has the same keys; skipped parts are `{"status": "skipped", "reason": ...}` and `seconds` gives the processing time.

**Input rules:** messages over 4,000 characters, under 12 letters/digits, mostly symbols/emoji, or keyboard-mash/noise are rejected with a clear message before any AI call. Uploads: PNG/JPG/WEBP/MP4/MOV/WEBM up to 20 MB and 40 megapixels, content-checked. **Abuse limits:** 20 requests per minute and 60 per 10 minutes per visitor (HTTP 429 with `Retry-After`). Uploads are served with `nosniff` and a locked-down Content-Security-Policy. On the hosted server the example buttons are pre-run after every restart and the instance keeps itself awake, so examples answer in seconds. User text is HTML-escaped in reports and rendered as plain text in the UI.

## What it does

- **Plain answer first**: what it is, why, and what to do, translated into the citizen's language with a spoken reply. All scores and forensics are folded under "Technical details" for fact-checkers.
- **AI team**: each AI does one job with a backup: Gemini (research, image reading), Sarvam (Indian-language translation and voice), OCR.space (text in images), Sightengine (AI-made image check), Groq (independent second opinion). Jobs are assigned in settings, so models can be swapped without code changes.
- **Real data only**: the scheme list holds real central schemes (Central Sector Scholarship, PM-KISAN, Ayushman Bharat PM-JAY) with their official sources; every claim is also researched live by Gemini. No mock datasets.
- **Catches disguised scams**: fee requests, OTP/PIN requests (also written as "0TP", "o.t.p", "6 digit code"), personal UPI IDs, WhatsApp-only applications, look-alike "gov-in" links, edited photos and videos, in English, Hindi, Tamil, Telugu, Kannada and Hinglish.
- **Safe agent**: only runs when a claim passes; at most 10 steps on approved sites; a human solves CAPTCHAs and approves the final submit; personal details are encrypted and deleted after 24 hours; every step is written to a tamper-proof (hash-chained) record with a downloadable report.
- **Tested hard**: 62 automated tests, plus stress runs of 16,000+ generated inputs (broken links, huge or corrupt files, junk AI answers, disguised scams) with no crashes.

Stack: React dashboard (prebuilt in `client/dist`) · FastAPI · Playwright · SQLite · AES-256-GCM.

---

## Run it

Requires **Python 3.10+**. You don't need Node, because the dashboard is already built. ffmpeg is optional and enables video forensics.

**Windows:** double-click `start.bat`.
**macOS / Linux:** `./start.sh`

Or manually:

```bash
cd server
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. API docs are at http://127.0.0.1:8000/docs and the sandbox portal is at http://127.0.0.1:8000/portal/.

**Turn on live research:** get a free key at https://aistudio.google.com/apikey, copy `.env.example` to `.env` and set `GEMINI_API_KEY=...`. The header then shows "Live research: Gemini".

Your settings file can be named `.env` or `factverify.env` and goes in the project's main folder, next to `start.bat`. Both names are blocked from git, so keys never reach GitHub.

Other optional settings: Set `FACTVERIFY_ENCRYPTION_KEY` for a stable AES key; without it, a development key is generated in `server/runtime/`. Add `ANTHROPIC_API_KEY` to get a Claude second opinion on each claim. Set `AGENT_HEADLESS=false` to watch the agent drive a visible Chrome window.

Optional extras: **ffmpeg** (`winget install ffmpeg` / `brew install ffmpeg`) for video. `pip install pytesseract` plus the Tesseract program reads text from uploaded images. `pip install faster-whisper` transcribes video speech.

## Deploy on Render (for the submission link)

1. Go to https://render.com and sign in with GitHub.
2. Click **New → Blueprint** and pick this repository. Render reads `render.yaml` and builds the `Dockerfile`; the first build takes about 10 minutes.
3. When Render asks for the secret values, paste the API keys from your private settings file. Leave any you don't have empty.
4. When the build is live, open `https://<your-app>.onrender.com/api/health`. It should show `"status": "healthy"`. Then submit `https://<your-app>.onrender.com`.

Notes:
- The free plan sleeps after inactivity. Open the link about a minute before judging so it wakes up.
- Offline extras (Ollama, the local AI-image detector, offline Whisper) are switched off in the cloud; the cloud keys cover those jobs.
- Anyone with the link can use your API credit, so set usage limits in each provider's dashboard.

## Test

```bash
cd server
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
| `test_ai_team.py` (6 tests) | Every provider's request format and response parsing (Sarvam, ElevenLabs, Groq, Sightengine, OCR.space, OpenAI), the full pipeline with all 8 roles at once, and graceful fallback when a service fails (network mocked) |
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

## AI team: 12 AI services, one job each

| # | Service | Job in FactVerify | Get the key | Setting |
|---|---|---|---|---|
| 1 | **Google Gemini 4 Argon** | Live web research with Google Search; each finding linked to its proof | https://aistudio.google.com/apikey | `GEMINI_API_KEY` |
| 2 | **Sarvam AI** (Mayura, Saaras v3, Bulbul v3) | Indian-language translation, speech-to-text and spoken replies | https://dashboard.sarvam.ai | `SARVAM_API_KEY` |
| 3 | **ElevenLabs** | Natural multilingual voice; backup speech-to-text (Scribe) | https://elevenlabs.io/app/settings/api-keys | `ELEVENLABS_API_KEY` |
| 4 | **Groq** (Whisper Large v3) | Very fast speech-to-text and speech-to-English | https://console.groq.com/keys | `GROQ_API_KEY` |
| 5 | **Local AI-image detector** (`Organika/sdxl-detector`, runs on your laptop) | Detects AI-generated images, free with **no account or key** | `pip install transformers torch` (model downloads on first start) | `LOCAL_AI_IMAGE_MODEL` |
| 5b | **Sightengine** (optional backup) | AI-generated image and deepfake detection in the cloud | https://sightengine.com | `SIGHTENGINE_API_USER`, `SIGHTENGINE_API_SECRET` |
| 6 | **OCR.space** | Reads text in images, including Hindi, Tamil, Telugu and Kannada | https://ocr.space/ocrapi | `OCR_SPACE_API_KEY` |
| 7 | **OpenAI** (`gpt-5.4-mini`) | Image understanding: what a picture shows, claims and red flags; backup reviewer | https://platform.openai.com/api-keys | `OPENAI_API_KEY` |
| 8 | **Anthropic Claude** (Sonnet 5.5) | Independent second opinion on the claim | https://console.anthropic.com/settings/keys | `ANTHROPIC_API_KEY` |
| 9 | **Mistral AI** (`mistral-small-latest`) | Free second opinion (Experiment plan) | https://console.mistral.ai/api-keys | `MISTRAL_API_KEY` |
| 10 | **Cohere** (Command A) | Free second opinion (trial key) | https://dashboard.cohere.com/api-keys | `COHERE_API_KEY` |
| 11 | **Ollama** (`qwen3:8b` on your laptop) | Free offline second opinion: **no account and no key** | https://ollama.com/download, then `ollama pull qwen3:8b` | `OLLAMA_MODEL` |
| + | Whisper and Tesseract (offline, optional) | Speech-to-text and OCR without internet | `pip install faster-whisper pytesseract` | – |

**Roles and fallbacks** (set in `.env`; the first service with a key is used):

| Role | Default order | What the citizen sees |
|---|---|---|
| research | gemini | Verdict with clickable proof links |
| translation | sarvam → gemini | Claims understood in any Indian language; replies in theirs |
| speech | sarvam → groq → elevenlabs → whisper → gemini | Transcript of what is said in a video |
| voice | sarvam → elevenlabs | 🔊 "Listen" button reading the verdict in their language |
| ocr | ocrspace → tesseract | Text read from screenshots and posters |
| image_ai | localdetector → sightengine | "93% AI-generated" warning on images and video frames |
| vision | openai → gemini | What the image shows, its claims and red flags |
| review | mistral → cohere → ollama → claude → openai | Second opinion blended into the score (free options first) |

- **You don't need every key.** Any role without a key is skipped and the app still works. Gemini alone covers research, translation, speech and vision as a stand-in.
- **Failures are contained.** If one service errors (wrong key, quota), its role is marked with an error, a warning is shown, and the rest of the audit continues.
- **Visible:** the header shows how many roles are active. Each result lists which models were used, and the Fact-checker console shows the full lineup.
- **Adding another model:** copy `server/app/ai/providers/_template.py`, add it to `PROVIDERS` in `server/app/ai/router.py`, and list it in the role's setting.

Most of these services offer a free tier or free starter credits, which is enough for a hackathon. Check each site for current limits. OpenAI and Anthropic usually need billing set up.

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

- **Scheme:** add an entry to `server/data/registry.json` with figures from the official notification and the `playbook` id to use.
- **Portal:** copy `server/app/agent/playbooks/sandbox_scholarship.json`, set `base_url` and `allowed_hosts`, and map each form field to a profile field. A playbook can have at most 10 steps. The actions are `goto`, `fill_form`, `click`, `human_captcha`, `approval_gate`, `extract` and `download`. Only automate portals whose terms allow assisted access. CAPTCHAs always go to the human.

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
- The scheme list covers 3 real central schemes; other schemes are checked by live AI research only.
- The agent fills a **practice copy** of the scholarship form (`/portal`), clearly labelled; it never submits to a real government site. Real portals need their own playbook and permission.
- On free Gemini keys, Google Search grounding has no quota, so research runs without live web sources and is marked as such (and weighted lower).
- SQLite suits a single machine. For production, move `db.py` to PostgreSQL.
- Live research needs `GEMINI_API_KEY` and internet. Without it, the app falls back to the registry and rules. Google bills grounded searches per query on Gemini 3+ models, so research runs once per claim.
- Speech transcription uses Gemini (or local faster-whisper). Image OCR needs Tesseract.

## Rebuilding the dashboard (only if you edit `client/src`)

```bash
cd client && npm install && npm run build
```
