"""Sandbox scholarship portal: a deliberately "legacy" multi-page HTML form site.

It lets the browser agent be demonstrated and tested end to end without touching a live government system.
It has a session login, a long form with server-side validation, a human CAPTCHA, a declaration page,
a confirmation number and a downloadable PDF receipt.
"""
import base64
import io
import random
import re
import secrets
import string
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

SESSIONS: dict[str, dict] = {}
APPLICATIONS: dict[str, dict] = {}
STATES = ["Andhra Pradesh", "Bihar", "Delhi", "Gujarat", "Karnataka", "Kerala", "Maharashtra", "Rajasthan",
          "Tamil Nadu", "Telangana", "Uttar Pradesh", "West Bengal"]

STYLE = """
body{font-family:Verdana,Arial,sans-serif;background:#e9e6dc;margin:0;color:#222;font-size:14px}
.top{background:#1d3f72;color:#fff;padding:10px 24px;border-bottom:4px solid #f39c12}
.top h1{margin:0;font-size:20px}.top small{color:#cfd8e6}
.wrap{max-width:760px;margin:24px auto;background:#fff;border:1px solid #b9b39f;padding:20px 28px}
label{display:block;margin-top:12px;font-weight:bold}input,select{width:100%;padding:6px;border:1px solid #888;
box-sizing:border-box;font-size:14px}button{margin-top:18px;background:#1d3f72;color:#fff;border:0;padding:9px 22px;
cursor:pointer;font-size:14px}.error{background:#fde2e1;border:1px solid #c0392b;color:#922;padding:8px;margin:8px 0}
.note{background:#fff8dc;border:1px solid #e0c96c;padding:8px;margin:8px 0}table{border-collapse:collapse;width:100%}
td{border:1px solid #ccc;padding:6px}.steps{color:#666;font-size:12px}.code{font-size:28px;font-weight:bold;color:#1d6b2c}
"""


def page(title: str, body: str, step: str = "") -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>{title} - Scholarship Portal (Sandbox)</title>
<style>{STYLE}</style></head><body><div class="top"><h1>Scholarship Application Portal</h1>
<small>SANDBOX for FactVerify demos - not a government website</small></div>
<div class="wrap"><div class="steps">{step}</div><h2>{title}</h2>{body}</div></body></html>""")


def _session(request: Request) -> dict | None:
    sid = request.cookies.get("portal_sid")
    return SESSIONS.get(sid) if sid else None


def _esc(v) -> str:
    return (str(v or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


async def home(request: Request):
    return page("Welcome", """<p>Apply for the <b>Post-Matric Merit Scholarship 2026-27</b>.</p>
<div class="note">There is <b>no application fee</b>. Last date: 15 December 2026.</div>
<p><a id="start-application" href="login">Start a new application</a></p>""")


async def login(request: Request):
    error = ""
    if request.method == "POST":
        form = await request.form()
        name, dob = (form.get("full_name") or "").strip(), (form.get("dob") or "").strip()
        if len(name) < 3 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):
            error = '<div class="error" id="form-error">Enter your full name and date of birth (YYYY-MM-DD).</div>'
        else:
            sid = secrets.token_hex(16)
            SESSIONS[sid] = {"full_name": name, "dob": dob, "created": time.time()}
            resp = RedirectResponse("apply", status_code=303)
            resp.set_cookie("portal_sid", sid, httponly=True, samesite="lax")
            return resp
    return page("Applicant login", f"""{error}<form method="post">
<label for="full_name">Full name (as in records)</label><input id="full_name" name="full_name">
<label for="dob">Date of birth (YYYY-MM-DD)</label><input id="dob" name="dob">
<button id="login-btn" type="submit">Login</button></form>""", "Step 1 of 4")


async def apply(request: Request):
    s = _session(request)
    if not s:
        return RedirectResponse("login", status_code=303)
    errors = []
    if request.method == "POST":
        f = await request.form()
        data = {k: (f.get(k) or "").strip() for k in ("email", "phone", "state", "income", "course", "institution", "id_last4")}
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", data["email"]):
            errors.append("Valid email required.")
        if not re.fullmatch(r"\d{10}", re.sub(r"\D", "", data["phone"])[-10:] or ""):
            errors.append("10-digit mobile number required.")
        if data["state"] not in STATES:
            errors.append("Select your state.")
        if not data["income"].replace(",", "").isdigit():
            errors.append("Annual family income must be a number.")
        elif int(data["income"].replace(",", "")) > 250000:
            errors.append("Family income exceeds the Rs 2,50,000 limit for this scholarship.")
        if not data["course"] or not data["institution"]:
            errors.append("Course and institution are required.")
        if not re.fullmatch(r"\d{4}", data["id_last4"]):
            errors.append("Enter the last 4 digits of your national ID.")
        if not errors:
            s.update(data)
            return RedirectResponse("verify", status_code=303)
    opts = "".join(f'<option value="{st}">{st}</option>' for st in STATES)
    err = f'<div class="error" id="form-error">{"<br>".join(errors)}</div>' if errors else ""
    return page("Application form", f"""{err}<form method="post">
<label for="email">Email</label><input id="email" name="email">
<label for="phone">Mobile number</label><input id="phone" name="phone">
<label for="state">State of domicile</label><select id="state" name="state"><option value="">-- select --</option>{opts}</select>
<label for="income">Annual family income (Rs)</label><input id="income" name="income">
<label for="course">Course</label><input id="course" name="course">
<label for="institution">Institution</label><input id="institution" name="institution">
<label for="id_last4">National ID - last 4 digits</label><input id="id_last4" name="id_last4" maxlength="4">
<button id="continue" type="submit">Save and continue</button></form>""", "Step 2 of 4")


def _captcha_image(text: str) -> str:
    img = Image.new("RGB", (220, 70), (238, 238, 230))
    d = ImageDraw.Draw(img)
    try:
        fnt = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
    except OSError:
        fnt = ImageFont.load_default(34)
    for _ in range(8):
        d.line([(random.randint(0, 220), random.randint(0, 70)), (random.randint(0, 220), random.randint(0, 70))],
               fill=(random.randint(100, 180),) * 3, width=2)
    for i, ch in enumerate(text):
        d.text((18 + i * 32, random.randint(8, 22)), ch, font=fnt, fill=(random.randint(10, 80), 40, 90))
    buf = io.BytesIO()
    img.filter(ImageFilter.SMOOTH).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def verify(request: Request):
    s = _session(request)
    if not s or "email" not in s:
        return RedirectResponse("login", status_code=303)
    err = ""
    if request.method == "POST":
        f = await request.form()
        if (f.get("captcha") or "").strip().upper() == s.get("captcha"):
            s["verified"] = True
            return RedirectResponse("review", status_code=303)
        err = '<div class="error" id="form-error">Incorrect security code. Try again.</div>'
    s["captcha"] = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=6))
    return page("Security check", f"""{err}<p>Type the characters shown in the image.</p>
<img id="captcha-img" alt="security code" src="{_captcha_image(s['captcha'])}">
<form method="post"><label for="captcha">Security code</label><input id="captcha" name="captcha" autocomplete="off">
<button id="verify-btn" type="submit">Verify</button></form>""", "Step 3 of 4")


async def review(request: Request):
    s = _session(request)
    if not s or not s.get("verified"):
        return RedirectResponse("login", status_code=303)
    if request.method == "POST":
        f = await request.form()
        if f.get("declare") != "yes":
            return page("Review and submit", '<div class="error" id="form-error">You must accept the declaration.</div>'
                        '<p><a href="review">Back</a></p>', "Step 4 of 4")
        code = f"REC-{random.randint(10000, 99999)}"
        while code in APPLICATIONS:
            code = f"REC-{random.randint(10000, 99999)}"
        APPLICATIONS[code] = {**{k: v for k, v in s.items() if k not in ("captcha",)}, "submitted": time.time()}
        return RedirectResponse(f"confirmation/{code}", status_code=303)
    rows = "".join(f"<tr><td>{k.replace('_', ' ').title()}</td><td>{_esc(s.get(k))}</td></tr>" for k in
                   ("full_name", "dob", "email", "phone", "state", "income", "course", "institution", "id_last4"))
    return page("Review and submit", f"""<table id="summary">{rows}</table>
<form method="post"><label><input type="checkbox" id="declare" name="declare" value="yes" style="width:auto">
I declare that the information given is true.</label>
<button id="submit-application" type="submit">Submit application</button></form>""", "Step 4 of 4")


async def confirmation(request: Request):
    code = request.path_params["code"]
    app = APPLICATIONS.get(code)
    if not app:
        return page("Not found", '<div class="error">Unknown application number.</div>')
    return page("Application submitted", f"""<p>Your application has been received.</p>
<p>Application number:</p><p class="code" id="tracking-code">{code}</p>
<p>Applicant: {_esc(app['full_name'])}<br>Submitted: {time.strftime('%d %b %Y %H:%M', time.localtime(app['submitted']))}</p>
<p><a id="download-receipt" href="../receipt/{code}.pdf">Download acknowledgement (PDF)</a></p>""")


async def receipt_pdf(request: Request):
    code = request.path_params["code"]
    app = APPLICATIONS.get(code)
    if not app:
        return Response("Not found", status_code=404)
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, 790, "Scholarship Application Portal (Sandbox)")
    c.setFont("Helvetica", 11)
    c.drawString(60, 770, "Acknowledgement of application - Post-Matric Merit Scholarship 2026-27")
    c.setFont("Helvetica-Bold", 22)
    c.drawString(60, 730, f"Application number: {code}")
    c.setFont("Helvetica", 11)
    y = 700
    for k in ("full_name", "dob", "email", "state", "course", "institution"):
        c.drawString(60, y, f"{k.replace('_', ' ').title()}: {app.get(k, '')}")
        y -= 18
    c.drawString(60, y - 10, "Submitted: " + time.strftime("%d %b %Y %H:%M", time.localtime(app["submitted"])))
    c.drawString(60, 80, "This is a sandbox document generated for demonstration purposes.")
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{code}.pdf"'})


portal_app = Starlette(routes=[
    Route("/", home),
    Route("/login", login, methods=["GET", "POST"]),
    Route("/apply", apply, methods=["GET", "POST"]),
    Route("/verify", verify, methods=["GET", "POST"]),
    Route("/review", review, methods=["GET", "POST"]),
    Route("/confirmation/{code}", confirmation),
    Route("/receipt/{code}.pdf", receipt_pdf),
])
