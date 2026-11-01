# FactVerify: verdicts, thresholds and input rules

| Verdict | Shown to the citizen | Rule |
|---|---|---|
| `authentic` | "This looks genuine." | trust score ≥ 0.75 (the agent may run only here, and only for schemes with a playbook) |
| `unverified` | "We could not confirm this. Be careful." | 0.40 ≤ trust < 0.75 |
| `likely_fraudulent` | "This looks like a scam. Do not act on it." | trust < 0.40, or manipulated media |
| `off_topic` | "This does not look like a message about a government scheme." | no scheme, no warning sign, no civic words, no media; AI research and review are skipped (`status: "skipped"`) |

Trust score = weighted mix of the rule engine (45%), AI research (40% with live sources, 15% without) and the independent AI review (15%), then lowered by media forensics. Every response has the same keys; skipped parts are `{"status": "skipped", "reason": ...}` and `seconds` gives the processing time.

**Input rules:** messages over 4,000 characters, under 12 letters/digits, mostly symbols/emoji, or keyboard-mash/noise are rejected with a clear message before any AI call. Uploads: PNG/JPG/WEBP/MP4/MOV/WEBM up to 20 MB and 40 megapixels, content-checked. **Abuse limits:** 20 requests per minute and 60 per 10 minutes per visitor (HTTP 429 with `Retry-After`). Uploads are served with `nosniff` and a locked-down Content-Security-Policy. On the hosted server the example buttons are pre-run after every restart and the instance keeps itself awake, so examples answer in seconds. User text is HTML-escaped in reports and rendered as plain text in the UI.


## How the trust score is shown to citizens

The result opens with a plain headline, "why we think so" and "what you should do", in the citizen's language (headings included).
Under the score: "Trust score: higher means more likely genuine. Below 40 usually means a scam."
Technical numbers (manipulation score, forensics, AI team, sources, audit ID, timing) are folded under "Technical details for fact-checkers".

## What each part contributes

| Part | Weight | Notes |
|---|---|---|
| Rule engine (real scheme facts + scam patterns) | 45% | deterministic, multi-script, disguise-aware ("0TP", look-alike gov-in links) |
| AI research (Gemini) | 40% with live sources, 15% without | marked "without live web sources" when search is unavailable |
| Independent AI review (Groq) | 15% | different model family from research |
| Media forensics | lowers the score | edited / AI-made media caps the verdict at "likely a scam" |

The form-filling agent runs only when the score is at least **0.75** *and* the claim matches a real scheme with a playbook. It stops for the human to solve CAPTCHAs and approve the final submit.
