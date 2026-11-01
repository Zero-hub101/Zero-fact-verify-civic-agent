"""Bounded Playwright browser agent with a human-in-the-loop approval gate.

Each task runs in its own thread with its own browser. The agent:
  * only visits hosts listed in the playbook,
  * never runs more than MAX_AGENT_STEPS steps,
  * pauses (awaiting_approval / missing_data) for CAPTCHAs, payment pages, form discrepancies,
    missing profile fields and before the final submit,
  * retries a failed step once from a checkpoint, then stops with failed_at_step_N.
"""
import json
import logging
import queue
import re
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .. import config, db

log = logging.getLogger("factverify.agent")
PLAYBOOK_DIR = Path(__file__).parent / "playbooks"
TERMINAL = {"completed", "aborted_security_risk", "cancelled"}

_live: dict[str, dict] = {}
_inbox: dict[str, "queue.Queue[dict]"] = {}
_lock = threading.Lock()


PUBLIC_FIELDS = {"state", "course", "annual_income"}   # everything else is masked in logs


def _mask(v: str) -> str:
    """Logs are persisted, so personal values are never written in full."""
    if "@" in v:
        user, dom = v.split("@", 1)
        return f"{user[:1]}•••@{dom}"
    return " ".join(w[:1] + "•" * min(len(w) - 1, 5) for w in v.split()) or "•"


class StepFailed(Exception):
    pass


class Cancelled(Exception):
    pass


# ---------------- playbooks ----------------
def load_playbook(pid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_]+", pid or ""):
        raise ValueError("Invalid playbook id")
    path = PLAYBOOK_DIR / f"{pid}.json"
    if not path.exists():
        raise ValueError(f"Unknown playbook '{pid}'")
    pb = json.loads(path.read_text(encoding="utf-8"))
    if len(pb["steps"]) > config.MAX_AGENT_STEPS:
        raise ValueError(f"Playbook '{pid}' has {len(pb['steps'])} steps; the limit is {config.MAX_AGENT_STEPS}.")
    pb["base_url"] = pb["base_url"].replace("{PUBLIC_BASE_URL}", config.PUBLIC_BASE_URL.rstrip("/"))
    host = urlparse(config.PUBLIC_BASE_URL).hostname
    if host and host not in pb.get("allowed_hosts", []) and "{PUBLIC_BASE_URL}" in path.read_text():
        pb.setdefault("allowed_hosts", []).append(host)
    return pb


def list_playbooks() -> list[dict]:
    out = []
    for p in sorted(PLAYBOOK_DIR.glob("*.json")):
        pb = json.loads(p.read_text(encoding="utf-8"))
        fields = sorted({f["profile"] for s in pb["steps"] for f in s.get("fields", [])})
        out.append({"id": pb["id"], "name": pb["name"], "description": pb.get("description", ""),
                    "steps": [s["label"] for s in pb["steps"]], "profile_fields": fields})
    return out


def required_profile_fields(pid: str) -> list[str]:
    pb = load_playbook(pid)
    return sorted({f["profile"] for s in pb["steps"] for f in s.get("fields", [])})


# ---------------- task state ----------------
def _now() -> float:
    return time.time()


def _persist(task: dict) -> None:
    task["updated_at"] = _now()
    db.save_task(task)


def get_state(tid: str) -> Optional[dict]:
    with _lock:
        t = _live.get(tid)
        if t:
            return json.loads(json.dumps(t))
    return db.get_task(tid)


def _log(task: dict, msg: str, level: str = "info") -> None:
    with _lock:
        task["logs"].append({"t": _now(), "level": level, "msg": msg})
        task["logs"] = task["logs"][-300:]
    log.info("[%s] %s", task["id"], msg)
    _persist(task)


def _set(task: dict, **kw) -> None:
    with _lock:
        task.update(kw)
    _persist(task)


def create_task(audit: dict, profile_id: Optional[str], playbook_id: str) -> dict:
    pb = load_playbook(playbook_id)
    task = {
        "id": db.new_id("tsk"), "audit_id": audit["id"], "profile_id": profile_id, "playbook_id": playbook_id,
        "playbook_name": pb["name"], "status": "queued", "current_step": 0, "max_steps": config.MAX_AGENT_STEPS,
        "steps": [{"label": s["label"], "action": s["action"], "status": "pending"} for s in pb["steps"]],
        "logs": [], "screenshots": [], "pending": None, "result": {}, "error": None,
        "created_at": _now(), "updated_at": _now(),
    }
    _persist(task)
    return task


def create_blocked_task(audit: dict, playbook_id: Optional[str], reason: str) -> dict:
    task = {
        "id": db.new_id("tsk"), "audit_id": audit["id"], "profile_id": audit.get("profile_id"),
        "playbook_id": playbook_id or "none", "playbook_name": None, "status": "aborted_security_risk",
        "current_step": 0, "max_steps": config.MAX_AGENT_STEPS, "steps": [], "pending": None, "result": {},
        "logs": [{"t": _now(), "level": "error", "msg": reason},
                 {"t": _now(), "level": "error", "msg": "Browser agent was not launched. No portal was contacted."}],
        "screenshots": [], "error": reason, "created_at": _now(), "updated_at": _now(),
    }
    _persist(task)
    db.schedule_profile_wipe(audit.get("profile_id"))
    return task


def start(task: dict) -> None:
    with _lock:
        _live[task["id"]] = task
        _inbox[task["id"]] = queue.Queue()
    threading.Thread(target=_run, args=(task,), name=f"agent-{task['id']}", daemon=True).start()


def respond(tid: str, payload: dict) -> dict:
    with _lock:
        t = _live.get(tid)
        q = _inbox.get(tid)
    if not t or not q:
        raise KeyError("Task is not running")
    if not t.get("pending"):
        raise ValueError("Task is not waiting for input")
    q.put(payload)
    return {"accepted": True}


# ---------------- browser helpers ----------------
def _screenshot(task: dict, page, label: str) -> Optional[str]:
    try:
        name = f"{task['id']}_{len(task['screenshots']):02d}.png"
        page.screenshot(path=str(config.ARTIFACT_DIR / name), full_page=True)
        with _lock:
            task["screenshots"].append({"t": _now(), "label": label, "url": f"/artifacts/{name}", "page": page.url})
            task["screenshots"] = task["screenshots"][-20:]
        _persist(task)
        return f"/artifacts/{name}"
    except Exception as e:  # noqa: BLE001
        _log(task, f"Screenshot failed: {e}", "warn")
        return None


def _check_host(pb: dict, url: str) -> None:
    host = urlparse(url).hostname
    if host and host not in pb.get("allowed_hosts", []):
        raise Cancelled(f"Navigation to unapproved host '{host}' blocked")


def _wait_for_human(task: dict, kind: str, message: str, **extra) -> dict:
    status = "missing_data" if kind == "missing_data" else "awaiting_approval"
    _set(task, status=status, pending={"kind": kind, "message": message, "since": _now(), **extra})
    _log(task, f"Paused: {message}", "warn")
    try:
        reply = _inbox[task["id"]].get(timeout=config.HUMAN_WAIT_SECONDS)
    except queue.Empty:
        raise StepFailed(f"No response from the user within {config.HUMAN_WAIT_SECONDS // 60} minutes")
    _set(task, status="running", pending=None)
    if reply.get("action") == "reject":
        raise Cancelled("Stopped by the user")
    return reply


def _safety_scan(page) -> Optional[tuple[str, str]]:
    """Detect pages the agent must never act on alone."""
    try:
        text = page.inner_text("body", timeout=3000).lower()
    except Exception:  # noqa: BLE001
        text = ""
    pay_inputs = page.locator("input[name*=card i], input[name*=cvv i], input[autocomplete^=cc-], input[name*=upi i]").count()
    if pay_inputs or re.search(r"\b(pay now|payment gateway|enter card|proceed to pay)\b", text):
        return "payment", "This page asks for a payment. The agent never pays; review it yourself."
    if page.locator("iframe[src*=recaptcha], iframe[src*=hcaptcha], input[name*=captcha i]").count():
        return "captcha_page", "The portal shows a CAPTCHA that needs a person. Solve it in the portal window."
    return None


def _form_error(page) -> Optional[str]:
    loc = page.locator("#form-error, .error, [role=alert]")
    if loc.count() and loc.first.is_visible():
        return loc.first.inner_text().strip()[:500]
    return None


# ---------------- step execution ----------------
def _fill_form(task: dict, page, step: dict) -> None:
    profile = db.load_profile(task["profile_id"]) or {}
    missing = [f for f in step["fields"] if not str(profile.get(f["profile"], "")).strip()]
    if missing:
        for f in missing:
            try:
                page.eval_on_selector(f["selector"], "el => { el.style.outline = '4px solid #e11d48'; el.style.background = '#ffe4e6'; el.scrollIntoView({block: 'center'}); }")
            except Exception:  # noqa: BLE001
                pass
        shot = _screenshot(task, page, "Missing information highlighted")
        reply = _wait_for_human(task, "missing_data", "The portal needs information that is not in your profile.",
                                fields=[{"profile": f["profile"], "label": f["label"]} for f in missing], screenshot=shot)
        data = {k: str(v).strip() for k, v in (reply.get("data") or {}).items() if str(v).strip()}
        profile.update(data)
        db.update_profile(task["profile_id"], profile)
        still = [f["label"] for f in missing if not str(profile.get(f["profile"], "")).strip()]
        if still:
            raise StepFailed(f"Still missing: {', '.join(still)}")
        _log(task, f"Profile updated with {', '.join(data)}")
    for f in step["fields"]:
        value = str(profile[f["profile"]])
        if f.get("type") == "select":
            page.select_option(f["selector"], label=value)
        else:
            page.fill(f["selector"], value)
        shown = value if f["profile"] in PUBLIC_FIELDS else _mask(value)
        _log(task, f"   {f['label']}: {shown}")


def _expect(page, step: dict) -> None:
    if step.get("expect_url"):
        page.wait_for_url(re.compile(re.escape(step["expect_url"])), timeout=config.STEP_TIMEOUT_MS)


def _execute(task: dict, page, pb: dict, step: dict) -> None:
    a = step["action"]
    if a == "goto":
        url = step["url"].replace("{base_url}", pb["base_url"])
        _check_host(pb, url)
        page.goto(url, wait_until="domcontentloaded")
    elif a == "fill_form":
        _fill_form(task, page, step)
    elif a == "click":
        page.click(step["selector"])
        try:
            _expect(page, step)
        except Exception:
            err = _form_error(page)
            if err:
                raise PortalDiscrepancy(err)
            raise
    elif a == "human_captcha":
        for attempt in range(3):
            img = page.locator(step["image"]).get_attribute("src") if step.get("image") else None
            shot = _screenshot(task, page, "CAPTCHA waiting for you")
            reply = _wait_for_human(task, "captcha", "Type the security code shown by the portal.",
                                    captcha_image=img, screenshot=shot)
            page.fill(step["input"], str(reply.get("captcha", "")).strip())
            page.click(step["submit"])
            page.wait_for_load_state("domcontentloaded")
            if step.get("expect_url") and step["expect_url"] in page.url:
                return
            _log(task, f"Portal rejected the security code (attempt {attempt + 1} of 3)", "warn")
        raise StepFailed("Security code rejected 3 times")
    elif a == "approval_gate":
        shot = _screenshot(task, page, "Ready to submit")
        _wait_for_human(task, "approval", step["message"], screenshot=shot, consequential=True)
        _log(task, "You approved the submission")
        for sub in step.get("then", []):
            if "check" in sub:
                page.check(sub["check"])
            if "click" in sub:
                page.click(sub["click"])
        _expect(page, step)
    elif a == "extract":
        text = page.inner_text(step["selector"])
        m = re.search(step["pattern"], text)
        if not m:
            raise StepFailed(f"Could not find {step['save_as']} on the page")
        with _lock:
            task["result"][step["save_as"]] = m.group(0)
        _log(task, f"Captured {step['save_as']}: {m.group(0)}", "success")
    elif a == "download":
        with page.expect_download(timeout=config.STEP_TIMEOUT_MS) as dl:
            page.click(step["selector"])
        name = f"{task['id']}_{re.sub(r'[^A-Za-z0-9_.-]', '_', dl.value.suggested_filename)}"
        dl.value.save_as(str(config.ARTIFACT_DIR / name))
        with _lock:
            task["result"][step["save_as"]] = f"/artifacts/{name}"
        _log(task, f"Saved acknowledgement PDF ({dl.value.suggested_filename})", "success")
    else:
        raise StepFailed(f"Unknown action '{a}'")


class PortalDiscrepancy(Exception):
    pass


def finalize(task: dict) -> Optional[dict]:
    code = task["result"].get("tracking_code")
    if not code:
        return None
    audit = db.get_audit(task["audit_id"]) or {}
    res = audit.get("result") or {}
    return db.add_receipt(task["id"], task["audit_id"], code, task["result"].get("receipt_pdf"), {
        "playbook": task["playbook_name"], "scheme": (res.get("matched_scheme") or {}).get("name"),
        "authenticity": res.get("authenticity"), "manipulationScore": res.get("manipulationScore"),
        "steps_executed": sum(1 for s in task["steps"] if s["status"] == "done"),
    })


def _run(task: dict) -> None:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright

    pb = load_playbook(task["playbook_id"])
    steps = pb["steps"]
    _set(task, status="running")
    _log(task, f"Launching browser agent for '{pb['name']}' ({len(steps)} steps, limit {config.MAX_AGENT_STEPS})")
    i, executed = 0, 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=config.AGENT_HEADLESS)
            ctx = browser.new_context(accept_downloads=True, viewport={"width": 1100, "height": 800})
            page = ctx.new_page()
            page.set_default_timeout(config.STEP_TIMEOUT_MS)
            page.on("framenavigated", lambda fr: fr == page.main_frame and _check_nav(task, pb, fr.url))
            try:
                while i < len(steps):
                    if executed >= config.MAX_AGENT_STEPS:
                        raise StepFailed("Step limit reached")
                    step = steps[i]
                    _set(task, current_step=i + 1)
                    task["steps"][i]["status"] = "running"
                    _log(task, f"▶ Step {i + 1}/{len(steps)}: {step['label']}")
                    if step["action"] not in ("goto", "human_captcha", "approval_gate") and i > 0:
                        hit = _safety_scan(page)
                        if hit:
                            shot = _screenshot(task, page, "Safety intercept")
                            _wait_for_human(task, hit[0], hit[1] + " Approve only after you have handled it in the portal.",
                                            screenshot=shot)
                    attempts = 0
                    while True:
                        try:
                            _execute(task, page, pb, step)
                            break
                        except PortalDiscrepancy as d:
                            shot = _screenshot(task, page, "Portal reported a problem")
                            prev = next((j for j in range(i - 1, -1, -1) if steps[j]["action"] == "fill_form"), None)
                            fields = [{"profile": f["profile"], "label": f["label"]} for f in steps[prev]["fields"]] if prev is not None else []
                            reply = _wait_for_human(task, "discrepancy", f"The portal rejected the data: {d}",
                                                    fields=fields, screenshot=shot)
                            data = {k: str(v).strip() for k, v in (reply.get("data") or {}).items() if str(v).strip()}
                            if data:
                                prof = db.load_profile(task["profile_id"]) or {}
                                prof.update(data)
                                db.update_profile(task["profile_id"], prof)
                            if prev is None:
                                raise StepFailed(str(d))
                            _execute(task, page, pb, steps[prev])
                            executed += 1
                        except (PWError, StepFailed) as e:
                            if isinstance(e, StepFailed) and "No response" in str(e):
                                raise
                            attempts += 1
                            _screenshot(task, page, f"Checkpoint before retry (step {i + 1})")
                            if attempts > 1:
                                raise StepFailed(f"Step {i + 1} failed twice: {str(e).splitlines()[0][:200]}")
                            _log(task, f"Step {i + 1} failed ({str(e).splitlines()[0][:160]}). Retrying once from checkpoint.", "warn")
                            time.sleep(1.5)
                    executed += 1
                    task["steps"][i]["status"] = "done"
                    _screenshot(task, page, step["label"])
                    i += 1
                receipt = finalize(task)
                _set(task, status="completed", pending=None)
                _log(task, f"Completed. Application number {task['result'].get('tracking_code')}"
                           + (" (receipt recorded)" if receipt else ""), "success")
            finally:
                ctx.close()
                browser.close()
    except Cancelled as e:
        if i < len(task["steps"]):
            task["steps"][i]["status"] = "stopped"
        _set(task, status="cancelled", pending=None, error=str(e))
        _log(task, f"Stopped: {e}", "error")
    except Exception as e:  # noqa: BLE001
        if i < len(task["steps"]):
            task["steps"][i]["status"] = "failed"
        _set(task, status=f"failed_at_step_{i + 1}", pending=None, error=str(e))
        _log(task, f"Failed at step {i + 1}: {e}. Run trace preserved for review.", "error")
    finally:
        db.schedule_profile_wipe(task["profile_id"])
        with _lock:
            _inbox.pop(task["id"], None)
            _live.pop(task["id"], None)
        _persist(task)


def _check_nav(task: dict, pb: dict, url: str) -> None:
    host = urlparse(url).hostname
    if url.startswith("http") and host and host not in pb.get("allowed_hosts", []):
        _log(task, f"Warning: portal navigated to unapproved host {host}", "error")
