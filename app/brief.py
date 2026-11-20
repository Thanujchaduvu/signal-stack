"""Monday Morning Brief. The LLM may only cite record IDs we give it; items with no valid record are dropped (no unsupported claims)."""
import json, html as _h, datetime as dt
import markdown as md
from . import db, llm
from .util import now

def _clean(items, valid, need=True):
    out = []
    for it in items or []:
        if not isinstance(it, dict): continue
        ids = [int(i) for i in it.get("record_ids", []) if str(i).lstrip("-").isdigit() and int(i) in valid]
        if need and not ids: continue
        it["record_ids"] = ids; out.append(it)
    return out

def _e(s): return _h.escape(str(s or "")).replace("|", "/").replace("\n", " ")

def _refs(ids, recs):
    return " ".join(f"[[R{i}]]({recs[i]['url']})" if (recs[i]['url'] or '').startswith('http') else f"[R{i}]" for i in ids)

def generate(cid, window_days=None):
    st = db.get_settings(); window_days = int(window_days or st.get("brief_window_days", 14))
    c = db.company(cid)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=window_days)).isoformat()
    rows = db.q("""select * from records where company_id=? and relevant=1 and coalesce(published_at,discovered_at)>=? order by rank_score desc limit 40""", (cid, cutoff))
    recs = {r["id"]: r for r in rows}
    srcs = db.q("select status,fail_count,category from sources where company_id=?", (cid,))
    approved = [s for s in srcs if s["status"] == "approved"]; failing = [s for s in approved if s["fail_count"] >= 1]
    by_cat = {k: sum(1 for r in rows if r["category"] == k) for k in ("customers", "competitors", "market", "internal")}
    pay = []
    for r in rows:
        a = db.jl(r["analysis_json"], {})
        pay.append({"id": r["id"], "category": r["category"], "entity": r["entity"], "title": r["title"], "evidence_snippet": (r["snippet"] or "")[:300], "published": r["published_at"],
                    "what_happened": a.get("what_happened"), "interpretation": a.get("why_it_matters"), "suggested": a.get("suggested_consideration"),
                    "impact_type": r["impact_type"], "urgency": r["urgency"], "verification": r["verification"], "rank": r["rank_score"]})
    data = {}
    if pay:
        prompt = f"""Write the content for a Monday Morning Intelligence Brief for the founder/CEO.
{db.ctx_text(cid, 5000)}
EVIDENCE RECORDS (the ONLY facts you may use; cite by id): {json.dumps(pay)[:22000]}

Return JSON with these keys; every item MUST have "record_ids" (ids from above that support it). Do not invent anything not in the records.
 executive_summary: up to 5 [{{"headline","why_it_matters","record_ids"}}] (most decision-relevant first)
 customer: [{{"headline","detail","sentiment","record_ids"}}]  competitor: [{{"headline","what_changed","why_it_matters","implication","record_ids"}}]
 market: [{{"headline","detail","affects_business_because","record_ids"}}]  internal: [{{"headline","detail","record_ids"}}]
 opportunities: [{{"title","evidence","impact","next_step","priority":"high|medium|low","record_ids"}}] (aim for 3+, only if evidence supports)
 risks: [{{"title","possible_impact","urgency","record_ids"}}]
 actions: [{{"action","reason","owner" (a role e.g. Head of Growth),"priority":"high|medium|low","record_ids"}}]
 watch: [{{"item","why","record_ids"}}]
Where a category has nothing material, return an empty list for it. Anchor everything in this company's profile and the founder's stated decisions; avoid generic advice."""
        data = llm.chat_json(prompt, 0.2)
    for k, need in (("executive_summary", 1), ("customer", 1), ("competitor", 1), ("market", 1), ("internal", 1), ("opportunities", 1), ("risks", 1), ("actions", 1), ("watch", 1)):
        data[k] = _clean(data.get(k), recs, bool(need))
    data["executive_summary"] = data["executive_summary"][:5]
    used = sorted({i for k in data if isinstance(data[k], list) for it in data[k] for i in it.get("record_ids", [])})
    L = [f"# Monday Morning Brief: {c['name']}", f"*Generated {now()} UTC. Window: last {window_days} days. Evidence-linked: every claim cites a record [R#] that links to its original source.*", ""]
    L += ["## Coverage and limitations",
          f"- {len(approved)} approved sources; {len(failing)} had recent fetch failures. {len(rows)} relevant evidence records in window ({', '.join(f'{k}: {v}' for k, v in by_cat.items())}).",
          "- Customer-voice items are real posts/snippets but are **anecdotal**, not verified facts. 'Interpretation' lines are the system's strategic reading, not source claims."]
    if not rows:
        L.append("- **No relevant records were collected in this window.** Run source checks and analysis first; nothing has been invented to fill this report.")
    def sec(title, key, fmt, empty):
        L.extend(["", f"## {title}"])
        if not data[key]: L.append(f"_{empty}_"); return
        for i, it in enumerate(data[key], 1): L.append(fmt(i, it))
    sec("1. Executive Summary", "executive_summary", lambda i, x: f"{i}. **{_e(x.get('headline'))}**: {_e(x.get('why_it_matters'))} {_refs(x['record_ids'], recs)}", "No material developments this period.")
    sec("2. Customer Signals", "customer", lambda i, x: f"- **{_e(x.get('headline'))}** ({_e(x.get('sentiment'))}). {_e(x.get('detail'))} {_refs(x['record_ids'], recs)}", "No meaningful customer signals this period.")
    sec("3. Competitor Intelligence", "competitor", lambda i, x: f"- **{_e(x.get('headline'))}**\n  - What changed (evidence): {_e(x.get('what_changed'))}\n  - Why it matters (interpretation): {_e(x.get('why_it_matters'))}\n  - Implication: {_e(x.get('implication'))} {_refs(x['record_ids'], recs)}", "No meaningful competitor developments this period.")
    sec("4. Market Intelligence", "market", lambda i, x: f"- **{_e(x.get('headline'))}**: {_e(x.get('detail'))}\n  - Affects the business because (interpretation): {_e(x.get('affects_business_because'))} {_refs(x['record_ids'], recs)}", "No material regulatory/industry developments this period.")
    sec("5. Internal Business Intelligence", "internal", lambda i, x: f"- **{_e(x.get('headline'))}**: {_e(x.get('detail'))} {_refs(x['record_ids'], recs)}", "No internal data uploaded or no internal findings this period.")
    sec("6. Opportunities Identified", "opportunities", lambda i, x: f"{i}. **{_e(x.get('title'))}** [{_e(x.get('priority'))}]\n   - Evidence: {_e(x.get('evidence'))} {_refs(x['record_ids'], recs)}\n   - Impact: {_e(x.get('impact'))}\n   - Next step: {_e(x.get('next_step'))}", "No evidence-backed opportunities this period.")
    if 0 < len(data["opportunities"]) < 3: L.append("\n_Fewer than three opportunities are supported by this period's evidence; none were manufactured._")
    sec("7. Risks & Threats", "risks", lambda i, x: f"- **{_e(x.get('title'))}** (urgency: {_e(x.get('urgency'))}). Possible impact: {_e(x.get('possible_impact'))} {_refs(x['record_ids'], recs)}", "No material risks identified this period.")
    sec("8. Recommended Actions for This Week", "actions", lambda i, x: f"{i}. **{_e(x.get('action'))}** [{_e(x.get('priority'))}] Owner: {_e(x.get('owner'))}. Reason: {_e(x.get('reason'))} {_refs(x['record_ids'], recs)}", "No actions recommended without supporting evidence.")
    sec("9. What We Should Watch", "watch", lambda i, x: f"- **{_e(x.get('item'))}**: {_e(x.get('why'))} {_refs(x['record_ids'], recs)}", "Nothing flagged for continued monitoring.")
    L += ["", "## 10. Source Appendix", "", "| Ref | Title | Source (link) | Published | Discovered | Evidence snippet | Verification | Reliability / Evidence / Relevance |", "|---|---|---|---|---|---|---|---|"]
    for i in used:
        r = recs[i]
        link = f"[{_e(r['publisher'])}]({r['url']})" if (r["url"] or "").startswith("http") else _e(r["publisher"] or r["url"])
        L.append(f"| R{i} | {_e(r['title'])[:90]} | {link} | {_e(r['published_at']) or 'not stated'} | {_e(r['discovered_at'])} | {_e(r['snippet'])[:200]} | {_e(r['verification'])} | {r['reliability']} / {r['evidence']} / {r['strategic_relevance']} |")
    mdown = "\n".join(L)
    bid = db.ex("insert into briefs(company_id,kind,created_at,window_days,title,markdown,json) values(?,?,?,?,?,?,?)",
                (cid, "weekly", now(), window_days, f"Monday Brief {now()[:10]}", mdown, json.dumps(data)))
    for a in data["actions"]:
        db.ex("insert into actions(brief_id,company_id,text,reason,owner,priority,created_at) values(?,?,?,?,?,?,?)",
              (bid, cid, a.get("action"), a.get("reason"), a.get("owner"), a.get("priority"), now()))
    return bid

def render_html(markdown_text, title="Brief"):
    body = md.markdown(markdown_text, extensions=["tables"])
    return (f"<!doctype html><meta charset=utf-8><title>{_h.escape(title)}</title><style>body{{font:15px/1.55 system-ui;max-width:900px;margin:2rem auto;padding:0 1rem;color:#14202b}}"
            "table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #cfd8dd;padding:4px 6px;vertical-align:top}</style>" + body)
