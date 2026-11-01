"""Provenance / audit report in Markdown."""
import html
import time
from typing import Optional


def _ts(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _safe(v) -> str:
    """User text in the report: escape HTML and Markdown link/image syntax so nothing renders as code or links."""
    return html.escape(str(v or ""), quote=True).replace("[", "&#91;").replace("]", "&#93;").replace("`", "&#96;")


def build(audit: dict, task: Optional[dict], receipt: Optional[dict]) -> str:
    r = audit.get("result") or {}
    lines = [
        "# FactVerify provenance report", "",
        f"- Audit ID: `{audit['id']}`",
        f"- Created: {_ts(audit['created_at'])}",
        f"- Verdict: **{r.get('verdict', 'not analysed').replace('_', ' ')}**",
        f"- Authenticity score: **{r.get('authenticity', '-')}** (threshold {r.get('threshold', '-')})",
        f"- manipulationScore: **{r.get('manipulationScore', '-')}**",
        f"- deepfakeDetected: **{str(r.get('deepfakeDetected', False)).lower()}**",
        f"- Browser agent permitted: **{'yes' if r.get('agentAllowed') else 'no'}**", "",
    ]
    inputs = audit.get("inputs", {})
    lines += ["## Inputs", ""]
    if inputs.get("text"):
        lines += ["Claim text:", "", "> " + _safe(inputs["text"]).replace("\n", "\n> "), ""]
    if inputs.get("url"):
        lines.append(f"- URL: `{_safe(inputs['url'])}`")
    for f in inputs.get("files", []):
        lines.append(f"- File: {_safe(f['name'])} ({f['kind']}, {f['size'] // 1024} KB, sha256 `{f['sha256'][:16]}…`)")
    lines.append("")

    s = r.get("matched_scheme")
    lines += ["## Registry match", ""]
    if s:
        lines += [f"- Scheme: **{s['name']}** ({s['source']})",
                  f"- Official benefit: Rs {s['benefit_amount']:,} {s['benefit_period']}; application fee Rs {s['application_fee']}",
                  f"- Income limit: {'Rs ' + format(s['income_limit'], ',') if s.get('income_limit') else 'none'}; "
                  f"deadline {s.get('deadline') or 'none (ongoing scheme)'}",
                  f"- Official domains: {', '.join(s['official_domains'])}", ""]
    else:
        lines += ["No matching scheme in the trusted registry.", ""]

    t = r.get("text") or {}
    if t.get("present"):
        lines += ["## Claim checks", ""]
        for c in t.get("confirmations", []):
            lines.append(f"- ✅ {c['detail']}")
        for c in t.get("contradictions", []):
            lines.append(f"- ❌ ({c['severity']}) {c['detail']}")
        for h in t.get("scam_flags", []):
            lines.append(f"- ⚠️ Scam pattern: {h['label']} — evidence: \"{h['evidence']}\"")
        for src in t.get("sources", []):
            lines.append(f"- Source `{src['host']}`: {src['trust']}")
        lines.append("")

    if r.get("media"):
        lines += ["## Media forensics", ""]
        for m in r["media"]:
            lines.append(f"### {m.get('file_name', m['kind'])}")
            lines.append(f"- Tamper score: {m.get('tamper_score')}")
            for k, v in (m.get("signals") or {}).items():
                lines.append(f"- Signal `{k}`: {v}")
            for f in m.get("findings", []):
                lines.append(f"- {f}")
            lines.append("")

    rs = r.get("research")
    if rs and not rs.get("error") and rs.get("status") != "skipped":
        lines += ["## Live web research (with sources)", "",
                  f"- Engine: {rs['provider']} · model `{rs['model']}` · {rs['seconds']} s",
                  f"- Claim language: {rs['language']['name']}",
                  f"- Verdict: **{rs['verdict']}** (authenticity {rs['authenticity']})"
                  + (" · already debunked by fact-checkers" if rs.get("already_debunked") else ""), ""]
        if rs.get("claim_en") and rs["language"]["code"] != "en":
            lines += ["English translation:", "", "> " + _safe(rs["claim_en"]).replace("\n", "\n> "), ""]
        if rs.get("summary"):
            lines += [rs["summary"], ""]
        loc = rs.get("localized")
        if loc:
            lines += [f"In {loc.get('lang_name', loc['lang'])}: {loc.get('summary', '')} {loc.get('advice', '')}", ""]
        icon = {"supported": "✅", "contradicted": "❌", "unverified": "❔"}
        for f in rs.get("findings", []):
            refs = "".join(f" [{i + 1}]" for i in f.get("source_ids", []))
            lines.append(f"- {icon[f['status']]} **{f['point']}**: {f['evidence']}{refs}")
        if rs.get("sources"):
            lines += ["", "Sources retrieved by Google Search:"]
            lines += [f"{i + 1}. [{s['title']}]({s['url']}) · {s['trust'].replace('_', ' ')}" for i, s in enumerate(rs["sources"])]
        if rs.get("search_queries"):
            lines += ["", "Search queries used: " + "; ".join(f"`{q}`" for q in rs["search_queries"])]
        lines.append("")

    if r.get("ai_team"):
        lines += ["## AI models used", "", "| Role | Model | Provider | Type | Time |", "|---|---|---|---|---|"]
        for c in r["ai_team"]:
            kind = "specialist" if c.get("specialist") else "stand-in"
            lines.append(f"| {c['role']} | `{c['model']}` | {c['name']} | {kind} | "
                         f"{c.get('note') or str(c.get('seconds', '')) + ' s'}{' · error' if c.get('error') else ''} |")
        lines.append("")

    ai = r.get("ai_review")
    if ai and "verdict" in ai and ai.get("status") != "skipped":
        lines += ["## AI review", "", f"- Model: {ai.get('model')}; verdict: {ai['verdict']}; authenticity {ai['authenticity']}"]
        lines += [f"- {x}" for x in ai.get("reasons", [])] + [""]

    if r.get("warnings"):
        lines += ["## Warnings", ""] + [f"- {w}" for w in r["warnings"]] + [""]

    if task:
        lines += ["## Browser agent run", "", f"- Task ID: `{task['id']}`", f"- Portal: {task.get('playbook_name')}",
                  f"- Final status: **{task['status']}**", ""]
        lines += ["| Time | Event |", "|---|---|"]
        lines += [f"| {time.strftime('%H:%M:%S', time.localtime(l['t']))} | {l['msg'].strip()} |" for l in task["logs"]]
        lines.append("")

    if receipt:
        lines += ["## Tracking receipt (immutable record)", "",
                  f"- Application number: **{receipt['tracking_code']}**",
                  f"- Recorded: {_ts(receipt['created_at'])}",
                  f"- Record hash: `{receipt['record_hash']}`",
                  f"- Previous hash: `{receipt['prev_hash']}`", ""]

    lines += ["---", "Forensic scores are signals, not proof. Confirm important decisions with the official source."]
    return "\n".join(lines)
