"""Break-it tests against the live HTTP API: malformed requests must give clean 4xx answers, never a crash (5xx)."""
import io
import json
import random

import requests
from PIL import Image

R = random.Random(7)
JUNK = ["", " ", "\x00", "🙏" * 100, "<script>alert(1)</script>", "'; DROP TABLE audits; --", "A" * 20000,
        "{{7*7}}", "‮", "http://x.com[]", "javascript:alert(1)", "../../etc/passwd", "%00", "null"]


def _no_5xx(r, what):
    assert r.status_code < 500, f"{what} -> {r.status_code}: {r.text[:300]}"


def test_ingest_and_verify_survive_junk(server):
    for i in range(150):
        data = {"text": R.choice(JUNK) + " " + R.choice(JUNK + ["Pay Rs 499 fee and share OTP for PM Kisan"]),
                "url": R.choice(JUNK + ["", "", "https://pmkisan.gov.in"]),
                "transcript": R.choice(["", R.choice(JUNK)]),
                "reply_language": R.choice(["auto", "hi", "xx", "", "\x00", "A" * 500]),
                "profile": R.choice(["", "{}", "not json", "[]", json.dumps({"full_name": "<b>x</b>"}),
                                     json.dumps({"full_name": "A" * 5000, "email": 5}), "null", "123"])}
        r = requests.post(f"{server}/api/audit/ingest", data=data, timeout=60)
        _no_5xx(r, f"ingest {data!r:.200}")
        if r.ok:
            v = requests.post(f"{server}/api/audit/forensics", json={"audit_id": r.json()["audit_id"]}, timeout=120)
            _no_5xx(v, f"forensics {data!r:.200}")


def test_bad_uploads_are_rejected_cleanly(server):
    def jpeg(size=(50, 50)):
        b = io.BytesIO()
        Image.new("RGB", size, (9, 9, 9)).save(b, "JPEG")
        return b.getvalue()

    cases = [("x.jpg", b""), ("x.jpg", b"not an image"), ("x.png", jpeg()[:40]), ("x.exe", b"MZ" + b"\x00" * 100),
             ("../../evil.jpg", jpeg()), ("x.mp4", b"\x00" * 1000), ("x", jpeg()), ("x.JPG", jpeg()),
             ("a" * 400 + ".jpg", jpeg()), ("x.svg", b"<svg onload=alert(1)></svg>"), ("x.html", b"<script>1</script>"),
             ("x.gif", b"GIF89a"), ("x.webp", jpeg())]
    for name, body in cases:
        r = requests.post(f"{server}/api/audit/ingest", data={"text": "Pay Rs 499 fee"},
                          files={"files": (name, body, "application/octet-stream")}, timeout=60)
        _no_5xx(r, f"upload {name}")
        if r.ok:
            for f in r.json()["inputs"]["files"]:
                assert "/" not in f["public_url"][len("/media/"):], f"path escape via {name}"
                assert f["public_url"].rsplit(".", 1)[-1].lower() in ("jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"), name


def test_unknown_ids_and_bad_bodies(server):
    calls = [("post", "/api/audit/forensics", {"audit_id": "nope"}), ("post", "/api/audit/forensics", {}),
             ("post", "/api/audit/forensics", {"audit_id": 5}), ("get", "/api/audit/nope", None),
             ("get", "/api/audit/nope/report", None), ("post", "/api/tasks/run", {"audit_id": "nope"}),
             ("get", "/api/tasks/nope/state", None), ("post", "/api/tasks/nope/respond", {"x": 1}),
             ("post", "/api/tasks/nope/complete", None), ("post", "/api/voice", {"text": "", "lang": "hi"}),
             ("post", "/api/voice", {}), ("post", "/api/demo/nope", None), ("post", "/api/demo/genuine?media=../../x", None),
             ("get", "/media/..%2f..%2fapp%2fconfig.py", None), ("get", "/artifacts/..%2f..%2f.env", None),
             ("get", "/../factverify.env", None), ("get", "/%2e%2e/%2e%2e/factverify.env", None),
             ("get", "/api/receipts/verify", None), ("get", "/portal/../../factverify.env", None)]
    for method, path, body in calls:
        r = getattr(requests, method)(f"{server}{path}", json=body, timeout=60)
        _no_5xx(r, f"{method} {path}")
        assert "API_KEY" not in r.text and "ENCRYPTION_KEY" not in r.text, f"secret leak via {path}"


def test_junk_is_rejected_and_report_is_escaped(server):
    for junk in ["   ", "​​", "a", "🙏🙏🙏", "!!!", "\x00\x01"]:
        r = requests.post(f"{server}/api/audit/ingest", data={"text": junk}, timeout=30)
        assert r.status_code == 400, (junk, r.status_code)
    xss = "<script>alert(1)</script> PM Kisan pay Rs 499 fee [click](http://evil)"
    a = requests.post(f"{server}/api/audit/ingest", data={"text": xss}, timeout=30).json()
    requests.post(f"{server}/api/audit/forensics", json={"audit_id": a["audit_id"]}, timeout=60)
    rep = requests.get(f"{server}/api/audit/{a['audit_id']}/report", timeout=30).text
    assert "<script>" not in rep and "](http://evil)" not in rep
    long = requests.post(f"{server}/api/audit/ingest", data={"text": "scholarship fee " * 2000}, timeout=30)
    assert long.status_code == 400 and "too long" in long.json()["detail"]
    ok = requests.post(f"{server}/api/audit/ingest", data={"text": ("PM Kisan pay Rs 499 fee now. " * 200)[:4000]}, timeout=30)
    assert ok.status_code == 200 and len(ok.json()["inputs"]["text"]) == 4000
    for noise in ["asdfghjklqwertyuiopzxcvbnm", "A" * 2000, "sdfghjkl qwrtyp zxcvbnm", "ababababababababababab",
                  "asdf 😀😀😀 !!! @@@ qwer ### $$$ %%% zxcv ^^^ &&&", "a1!@#$%^&*()_+{}|:<>?~`-=[]\\;',./ b2 😀😀"]:
        assert requests.post(f"{server}/api/audit/ingest", data={"text": noise}, timeout=30).status_code == 400, noise
    assert requests.head(f"{server}/health", timeout=10).status_code == 200


def test_off_topic_skips_ai_research_and_review(server):
    a = requests.post(f"{server}/api/audit/ingest", data={"text": "Who won the cricket match yesterday?"}, timeout=30).json()
    res = requests.post(f"{server}/api/audit/forensics", json={"audit_id": a["audit_id"]}, timeout=60).json()
    assert res["verdict"] == "off_topic"
    assert res["ai_review"]["status"] == "skipped" and res["research"]["status"] == "skipped" and res["seconds"] >= 0
    assert res["ai_review"]["verdict"] == "skipped" and res["research"]["verdict"] == "skipped"
    r = requests.get(f"{server}/media/x.jpg", timeout=10)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
