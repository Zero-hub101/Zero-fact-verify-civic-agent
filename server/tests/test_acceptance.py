"""Acceptance criteria from specs.md plus key edge cases.

Run:  cd server && python -m pytest -v
"""
import json
import re
import shutil
import time

import pytest
import requests

GENUINE = ("Post-Matric Merit Scholarship 2026-27: Rs 12,000 per year for students with family income up to "
           "Rs 2,50,000. Apply free on the official portal before 15 December 2026.")
FRAUD = ("URGENT!! PM Merit Scholarship of Rs 50,000 for ALL students. Pay Rs 499 registration fee to UPI "
         "9876543210@ybl and share the OTP on WhatsApp within 24 hours. No documents needed. Forward to 10 groups!")
PROFILE = {"full_name": "Asha Kumar", "dob": "2005-04-12", "email": "asha@example.com", "phone": "9876543210",
           "state": "Tamil Nadu", "annual_income": "180000", "course": "B.Sc Physics",
           "institution": "Government Arts College", "id_last4": "4821"}


def ingest(base, text, media_path=None, profile=PROFILE):
    files = [("files", (media_path.name, media_path.open("rb")))] if media_path else []
    r = requests.post(f"{base}/api/audit/ingest", data={"text": text, "profile": json.dumps(profile)}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def verify(base, audit_id):
    r = requests.post(f"{base}/api/audit/forensics", json={"audit_id": audit_id})
    assert r.status_code == 200, r.text
    return r.json()


def wait_for(base, task_id, predicate, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        s = requests.get(f"{base}/api/tasks/{task_id}/state").json()
        if predicate(s):
            return s
        time.sleep(0.4)
    raise AssertionError(f"Timed out; last state {s['status']}: {s['logs'][-3:]}")


def portal_captcha():
    from app.portal.app import SESSIONS
    return list(SESSIONS.values())[-1]["captcha"]


# AC_01
def test_health(server):
    r = requests.get(f"{server}/api/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


# Scenario 1: validated claim -> successful registration
def test_happy_path(server, demo_media):
    media = demo_media / ("genuine_notice.mp4" if shutil.which("ffmpeg") else "genuine_notice.jpg")
    ing = ingest(server, GENUINE, media)
    res = verify(server, ing["audit_id"])
    assert res["manipulationScore"] <= 0.25
    assert res["deepfakeDetected"] is False and res["agentAllowed"] is True

    task = requests.post(f"{server}/api/tasks/run", json={"audit_id": ing["audit_id"]}).json()
    s = wait_for(server, task["id"], lambda s: (s.get("pending") or {}).get("kind") == "captcha")
    assert s["status"] == "awaiting_approval"
    requests.post(f"{server}/api/tasks/{task['id']}/respond", json={"action": "captcha", "captcha": portal_captcha()})
    s = wait_for(server, task["id"], lambda s: (s.get("pending") or {}).get("kind") == "approval")
    requests.post(f"{server}/api/tasks/{task['id']}/respond", json={"action": "approve"})
    s = wait_for(server, task["id"], lambda s: s["status"] == "completed")
    assert re.fullmatch(r"REC-\d{5}", s["result"]["tracking_code"])
    assert s["result"]["receipt_pdf"].endswith(".pdf")
    assert sum(1 for x in s["steps"] if x["status"] == "done") <= 10

    done = requests.post(f"{server}/api/tasks/{task['id']}/complete").json()
    assert done["receipt"]["tracking_code"] == s["result"]["tracking_code"] and done["chain_valid"]
    report = requests.get(f"{server}/api/audit/{ing['audit_id']}/report?task_id={task['id']}").text
    assert s["result"]["tracking_code"] in report


# Scenario 2: deepfake -> security abort, no browser
@pytest.mark.parametrize("media_name", ["tampered_notice.jpg", "tampered_notice.mp4"])
def test_fraud_abort(server, demo_media, media_name):
    if media_name.endswith(".mp4") and not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ing = ingest(server, FRAUD, demo_media / media_name)
    res = verify(server, ing["audit_id"])
    assert res["manipulationScore"] >= 0.75
    assert res["deepfakeDetected"] is True and res["agentAllowed"] is False
    task = requests.post(f"{server}/api/tasks/run", json={"audit_id": ing["audit_id"]}).json()
    assert task["status"] == "aborted_security_risk"
    assert task["screenshots"] == [] and task["steps"] == []


def test_missing_profile_field_pauses(server, demo_media):
    prof = {**PROFILE, "id_last4": ""}
    ing = ingest(server, GENUINE, None, prof)
    assert verify(server, ing["audit_id"])["agentAllowed"]
    task = requests.post(f"{server}/api/tasks/run", json={"audit_id": ing["audit_id"]}).json()
    s = wait_for(server, task["id"], lambda s: s["status"] == "missing_data")
    assert s["pending"]["fields"][0]["profile"] == "id_last4"
    requests.post(f"{server}/api/tasks/{task['id']}/respond", json={"action": "provide", "data": {"id_last4": "1234"}})
    wait_for(server, task["id"], lambda s: (s.get("pending") or {}).get("kind") == "captcha")
    requests.post(f"{server}/api/tasks/{task['id']}/respond", json={"action": "reject"})
    s = wait_for(server, task["id"], lambda s: s["status"] == "cancelled")


def test_portal_discrepancy_pauses(server):
    ing = ingest(server, GENUINE, None, {**PROFILE, "annual_income": "900000"})
    verify(server, ing["audit_id"])
    task = requests.post(f"{server}/api/tasks/run", json={"audit_id": ing["audit_id"]}).json()
    s = wait_for(server, task["id"], lambda s: (s.get("pending") or {}).get("kind") == "discrepancy")
    assert "income" in s["pending"]["message"].lower()
    requests.post(f"{server}/api/tasks/{task['id']}/respond", json={"action": "reject"})
    wait_for(server, task["id"], lambda s: s["status"] == "cancelled")


def test_portal_unreachable_retries_then_fails(server, monkeypatch):
    from app import config
    from app.agent import runner
    ing = ingest(server, GENUINE)
    verify(server, ing["audit_id"])
    from app import db
    audit = db.get_audit(ing["audit_id"])
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://127.0.0.1:9")   # nothing listens on port 9
    task = runner.create_task(audit, audit["profile_id"], "sandbox_scholarship")
    runner.start(task)
    s = wait_for(server, task["id"], lambda s: s["status"].startswith("failed"), timeout=60)
    assert s["status"] == "failed_at_step_1"
    assert any("Retrying once" in l["msg"] for l in s["logs"])


def test_validation_errors(server):
    r = requests.post(f"{server}/api/audit/ingest", data={"text": ""})
    assert r.status_code == 400
    r = requests.post(f"{server}/api/audit/ingest", data={"text": "x", "profile": json.dumps({"id_last4": "123456789012"})})
    assert r.status_code == 422
    r = requests.post(f"{server}/api/audit/ingest", data={"text": "x"}, files=[("files", ("a.exe", b"MZ"))])
    assert r.status_code == 400


def test_profile_encrypted_at_rest(server):
    from app import config
    ing = ingest(server, GENUINE)
    raw = config.DB_PATH.read_bytes()
    assert b"Asha Kumar" not in raw and b"4821" not in raw
    assert ing["profile_id"]


def test_receipts_are_immutable(server):
    import sqlite3
    from app import config, db
    db.add_receipt("tsk_test", "aud_test", "REC-00001", None, {})
    conn = sqlite3.connect(config.DB_PATH)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE receipts SET tracking_code='REC-99999'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM receipts")
    conn.close()
    assert db.verify_receipt_chain()


def test_low_resolution_warning(server, demo_media, tmp_path):
    from PIL import Image
    small = tmp_path / "small.jpg"
    Image.open(demo_media / "genuine_notice.jpg").resize((300, 200)).save(small, quality=80)
    ing = ingest(server, GENUINE, small)
    res = verify(server, ing["audit_id"])
    assert res["low_resolution_confidence_degraded"] is True
