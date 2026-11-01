"""FactVerify Civic Agent - FastAPI application."""
import hashlib
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, ValidationError, field_validator

from . import config, db, pipeline, report
from .ai import router as ai_router
from .agent import runner
from .forensics import text as text_mod
from .portal.app import portal_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("factverify")

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
DEMO_DIR = config.BASE_DIR / "demo"
REPLY_LANGS = {"auto", "en", "hi", "ta", "te", "kn", "ml", "bn", "mr", "gu", "pa", "or", "ur"}



@asynccontextmanager
async def lifespan(_app):
    db.init()
    threading.Thread(target=_purge_loop, daemon=True, name="profile-purge").start()
    from .ai.providers.local_ai_detector import warm_up
    threading.Thread(target=warm_up, daemon=True, name="ai-detector-warmup").start()
    log.info("FactVerify ready. Portal sandbox at %s/portal/", config.PUBLIC_BASE_URL)
    yield


def _purge_loop() -> None:
    while True:
        try:
            n = db.purge_expired_profiles()
            if n:
                log.info("Wiped %d expired citizen profile(s)", n)
        except Exception as e:  # noqa: BLE001
            log.warning("Purge failed: %s", e)
        time.sleep(600)


app = FastAPI(title="FactVerify Civic Agent", version="1.0.0", lifespan=lifespan,
              description="Verify public-service claims and media, then safely complete official applications.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------------- auth ----------------
def require_token(x_api_token: Optional[str] = Header(default=None)) -> None:
    if config.API_TOKEN and x_api_token != config.API_TOKEN:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Token header.")


auth = [Depends(require_token)]


# ---------------- models ----------------
class Profile(BaseModel):
    full_name: str = Field(default="", max_length=120)
    dob: str = Field(default="", description="YYYY-MM-DD")
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=20)
    state: str = Field(default="", max_length=60)
    annual_income: str = Field(default="", max_length=15)
    course: str = Field(default="", max_length=120)
    institution: str = Field(default="", max_length=160)
    id_last4: str = Field(default="", description="Last 4 digits of the national ID only")

    @field_validator("dob")
    @classmethod
    def _dob(cls, v: str) -> str:
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("Date of birth must be YYYY-MM-DD")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if v and len(digits) < 10:
            raise ValueError("Phone number must have 10 digits")
        return digits[-10:] if v else v

    @field_validator("annual_income")
    @classmethod
    def _income(cls, v: str) -> str:
        v = v.replace(",", "").strip()
        if v and not v.isdigit():
            raise ValueError("Annual income must be a whole number")
        return v

    @field_validator("id_last4")
    @classmethod
    def _id(cls, v: str) -> str:
        if v and not re.fullmatch(r"\d{4}", v):
            raise ValueError("Provide only the last 4 digits of the national ID, never the full number")
        return v


class ForensicsRequest(BaseModel):
    audit_id: str


class RunRequest(BaseModel):
    audit_id: str
    playbook_id: Optional[str] = None


class RespondRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject|captcha|provide)$")
    captcha: Optional[str] = Field(default=None, max_length=20)
    data: Optional[dict[str, str]] = None


# ---------------- helpers ----------------
def _store_upload(src: Path, name: str) -> dict:
    ext = Path(name).suffix.lower()
    kind = "image" if ext in IMAGE_EXT else "video"
    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = config.UPLOAD_DIR / fname
    shutil.copyfile(src, dest)
    return {"name": Path(name).name[:120], "kind": kind, "path": str(dest), "public_url": f"/media/{fname}",
            "size": dest.stat().st_size, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}


def _validate_media(path: Path, kind: str) -> None:
    if kind == "image":
        try:
            with Image.open(path) as im:
                im.verify()
        except Exception:
            raise HTTPException(400, "File is not a readable image.")
    elif shutil.which("ffprobe"):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, timeout=30)
        if "video" not in out.stdout:
            raise HTTPException(400, "File is not a readable video.")


def _ingest(text: str, url: str, transcript: str, profile: Optional[dict], files: list[dict],
            reply_language: str = "auto") -> dict:
    if not (text.strip() or url.strip() or transcript.strip() or files):
        raise HTTPException(400, "Provide claim text, a URL, a transcript or a media file.")
    if url and not re.match(r"^(https?://)?[\w.-]+\.[a-z]{2,}|^https?://(localhost|127\.0\.0\.1)", url.strip(), re.I):
        raise HTTPException(400, "URL is not valid.")
    profile_id = db.save_profile(profile) if profile and any(profile.values()) else None
    inputs = {"text": text.strip()[:10000], "url": url.strip()[:2000], "transcript": transcript.strip()[:20000],
              "files": files, "reply_language": reply_language if reply_language in REPLY_LANGS else "auto",
              "profile_fields": sorted(k for k, v in (profile or {}).items() if v)}
    audit_id = db.create_audit(inputs, profile_id)
    return {"audit_id": audit_id, "profile_id": profile_id, "status": "ingested",
            "inputs": {**inputs, "files": [{k: f[k] for k in ("name", "kind", "public_url", "size", "sha256")} for f in files]}}


# ---------------- endpoints ----------------
@app.get("/api/health")
def health():
    from .forensics.media import ffmpeg_available
    return {"status": "healthy", "version": app.version,
            "features": {"video_forensics": ffmpeg_available(), "ai_review": bool(config.ANTHROPIC_API_KEY),
                         "gemini_research": ai_router.get("research") is not None,
                         "auth_required": bool(config.API_TOKEN), "agent_headless": config.AGENT_HEADLESS},
            "threshold": config.AUTHENTICITY_THRESHOLD, "ai_team": ai_router.lineup()}


@app.get("/api/ai/team", dependencies=auth)
def ai_team():
    """Which model is assigned to each AI role (research, translation, speech, review)."""
    return ai_router.lineup()


@app.post("/api/audit/ingest", dependencies=auth)
async def ingest(text: str = Form(""), url: str = Form(""), transcript: str = Form(""), profile: str = Form(""),
                 reply_language: str = Form("auto"), files: list[UploadFile] = File(default=[])):
    """F1: accept claim text, a URL, media files and the citizen profile."""
    prof = None
    if profile.strip():
        try:
            prof = Profile(**json.loads(profile)).model_dump()
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(400, "Profile must be a JSON object.")
        except ValidationError as e:
            raise HTTPException(422, "; ".join(err["msg"].replace("Value error, ", "") for err in e.errors()))
    stored = []
    for uf in files[:5]:
        ext = Path(uf.filename or "").suffix.lower()
        if ext not in IMAGE_EXT | VIDEO_EXT:
            raise HTTPException(400, f"Unsupported file type '{ext}'. Use PNG, JPG, WEBP, MP4, MOV or WEBM.")
        tmp = config.UPLOAD_DIR / f"tmp_{uuid.uuid4().hex}"
        size = 0
        with tmp.open("wb") as out:
            while chunk := await uf.read(1 << 20):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * (1 << 20):
                    out.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(413, f"File larger than {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        try:
            _validate_media(tmp, "image" if ext in IMAGE_EXT else "video")
            stored.append(_store_upload(tmp, uf.filename or f"upload{ext}"))
        finally:
            tmp.unlink(missing_ok=True)
    return _ingest(text, url, transcript, prof, stored, reply_language)


@app.post("/api/audit/forensics", dependencies=auth)
def forensics(req: ForensicsRequest):
    """F2: run text, source and media verification and store the result."""
    audit = db.get_audit(req.audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found.")
    result = pipeline.run(audit["inputs"])
    result["audit_id"] = audit["id"]
    result["has_profile"] = bool(audit.get("profile_id"))
    db.set_audit_result(audit["id"], result, "verified" if result["agentAllowed"] else "blocked")
    return result


@app.get("/api/audit/{audit_id}", dependencies=auth)
def get_audit(audit_id: str):
    audit = db.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found.")
    for f in audit["inputs"].get("files", []):
        f.pop("path", None)
    return audit


@app.get("/api/audits", dependencies=auth)
def list_audits():
    out = []
    for a in db.list_audits():
        r = a.get("result") or {}
        out.append({"id": a["id"], "created_at": a["created_at"], "status": a["status"],
                    "verdict": r.get("verdict"), "authenticity": r.get("authenticity"),
                    "manipulationScore": r.get("manipulationScore"), "deepfakeDetected": r.get("deepfakeDetected"),
                    "scheme": (r.get("matched_scheme") or {}).get("name"),
                    "summary": (a["inputs"].get("text") or a["inputs"].get("url") or
                                ", ".join(f["name"] for f in a["inputs"].get("files", [])))[:140]})
    return out


@app.get("/api/audit/{audit_id}/report", dependencies=auth)
def audit_report(audit_id: str, task_id: Optional[str] = None):
    audit = db.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found.")
    task = runner.get_state(task_id) if task_id else next((t for t in db.list_tasks(200) if t["audit_id"] == audit_id), None)
    receipt = db.get_receipt(task["id"]) if task else None
    return PlainTextResponse(report.build(audit, task, receipt), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="factverify_{audit_id}.md"'})


@app.get("/api/registry", dependencies=auth)
def registry():
    return text_mod.registry()


@app.get("/api/playbooks", dependencies=auth)
def playbooks():
    return runner.list_playbooks()


@app.post("/api/tasks/run", dependencies=auth)
def run_task(req: RunRequest):
    """F3: launch the browser agent, only for audits that passed verification."""
    audit = db.get_audit(req.audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found.")
    result = audit.get("result")
    if not result:
        raise HTTPException(409, "Run verification (/api/audit/forensics) first.")
    scheme = result.get("matched_scheme") or {}
    playbook_id = req.playbook_id or scheme.get("playbook")
    if result.get("deepfakeDetected") or result["authenticity"] < config.AUTHENTICITY_THRESHOLD:
        reason = (f"Security abort: authenticity {result['authenticity']} is below the {config.AUTHENTICITY_THRESHOLD} "
                  f"threshold" + (" and manipulated media was detected" if result.get("deepfakeDetected") else ""))
        return runner.create_blocked_task(audit, playbook_id, reason)
    if not playbook_id:
        raise HTTPException(409, "No portal playbook is linked to this claim.")
    if not audit.get("profile_id") or not db.load_profile(audit["profile_id"]):
        raise HTTPException(409, "A citizen profile is required to run the agent (it may have been wiped).")
    try:
        task = runner.create_task(audit, audit["profile_id"], playbook_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    runner.start(task)
    return task


@app.get("/api/tasks/{task_id}/state", dependencies=auth)
def task_state(task_id: str):
    """F4: live trace, screenshots and any pending approval."""
    t = runner.get_state(task_id)
    if not t:
        raise HTTPException(404, "Task not found.")
    t["receipt"] = db.get_receipt(task_id)
    return t


@app.post("/api/tasks/{task_id}/respond", dependencies=auth)
def task_respond(task_id: str, req: RespondRequest):
    """F4: the citizen approves, rejects, solves a CAPTCHA or supplies missing data."""
    data = req.data
    if data:
        allowed = set(Profile.model_fields)
        bad = [k for k in data if k not in allowed]
        if bad:
            raise HTTPException(400, f"Unknown profile fields: {', '.join(bad)}")
        try:
            data = {k: v for k, v in Profile(**data).model_dump().items() if k in data}
        except ValidationError as e:
            raise HTTPException(422, "; ".join(err["msg"].replace("Value error, ", "") for err in e.errors()))
    try:
        return runner.respond(task_id, {"action": req.action, "captcha": req.captcha, "data": data})
    except KeyError:
        raise HTTPException(404, "Task is not running.")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/tasks/{task_id}/complete", dependencies=auth)
def task_complete(task_id: str):
    """F5: store the confirmation as an immutable receipt (idempotent)."""
    t = runner.get_state(task_id)
    if not t:
        raise HTTPException(404, "Task not found.")
    receipt = db.get_receipt(task_id) or (runner.finalize(t) if t["status"] == "completed" else None)
    if not receipt:
        raise HTTPException(409, f"Task is '{t['status']}'; no confirmation code has been captured.")
    return {"task_id": task_id, "status": t["status"], "receipt": receipt, "chain_valid": db.verify_receipt_chain()}


@app.get("/api/tasks", dependencies=auth)
def list_tasks():
    return [{k: t.get(k) for k in ("id", "audit_id", "status", "playbook_name", "created_at", "updated_at", "result")}
            for t in db.list_tasks()]


@app.get("/api/receipts/verify", dependencies=auth)
def verify_receipts():
    return {"chain_valid": db.verify_receipt_chain()}


DEMO_SCENARIOS = {
    "genuine": {
        "text": "Post-Matric Merit Scholarship 2026-27: Rs 12,000 per year for students with family income up to "
                "Rs 2,50,000. Apply free on the official portal before 15 December 2026.",
        "file": "genuine_notice.mp4",
    },
    "fraud": {
        "text": "URGENT!! PM Merit Scholarship of Rs 50,000 for ALL students. Pay Rs 499 registration fee to UPI "
                "9876543210@ybl and share the OTP on WhatsApp within 24 hours. No documents needed. Forward to 10 groups!",
        "file": "tampered_notice.mp4",
    },
    "fraud_hindi": {
        "text": "जरूरी सूचना!! पोस्ट मैट्रिक मेरिट छात्रवृत्ति में सभी छात्रों को ₹50,000 मिलेंगे। 24 घंटे में ₹499 "
                "पंजीकरण शुल्क UPI 9876543210@ybl पर भेजें और OTP व्हाट्सएप पर शेयर करें। कोई दस्तावेज़ नहीं चाहिए!",
        "file": "tampered_notice.mp4",
    },
}


@app.get("/api/demo/profile", dependencies=auth)
def demo_profile():
    return json.loads((DEMO_DIR / "demo_profile.json").read_text())


@app.post("/api/demo/{scenario}", dependencies=auth)
def demo(scenario: str, media: str = "video", reply_language: str = "auto"):
    """Load a ready-made demo case (genuine or fraud) with sample media and a sample citizen profile."""
    if scenario not in DEMO_SCENARIOS:
        raise HTTPException(404, "Unknown scenario. Use 'genuine', 'fraud' or 'fraud_hindi'.")
    sc = DEMO_SCENARIOS[scenario]
    fname = sc["file"] if media == "video" else sc["file"].replace(".mp4", ".jpg")
    src = DEMO_DIR / "media" / fname
    if not src.exists() or (src.suffix == ".mp4" and not shutil.which("ffmpeg")):
        src = DEMO_DIR / "media" / sc["file"].replace(".mp4", ".jpg")
    files = [_store_upload(src, src.name)] if src.exists() else []
    return _ingest(sc["text"], "", "", demo_profile(), files, reply_language)


# ---------------- static ----------------
app.mount("/portal", portal_app)
app.mount("/artifacts", StaticFiles(directory=config.ARTIFACT_DIR), name="artifacts")
app.mount("/media", StaticFiles(directory=config.UPLOAD_DIR), name="media")

if config.CLIENT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.CLIENT_DIST / "assets", check_dir=False), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "portal", "artifacts/", "media/")):
            raise HTTPException(404)
        target = config.CLIENT_DIST / path
        if path and target.is_file() and config.CLIENT_DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(config.CLIENT_DIST / "index.html")
