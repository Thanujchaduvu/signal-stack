"""Monthly Signal Stack audit + context-change reassessment."""
import json
from . import db, llm, discovery
from .util import now, age_days

def audit(cid):
    srcs = db.q("select * from sources where company_id=? and status in ('approved','proposed')", (cid,))
    dead, inactive, declining, dups = [], [], [], []
    seen_keys, seen_hash = {}, {}
    for s in srcs:
        if s["fail_count"] >= 3: dead.append(s)
        if s["status"] == "approved" and s["kind"] != "upload":
            ref = s["last_new_at"] or s["created_at"]
            if (age_days(ref) or 0) > 60: inactive.append(s)
            st = db.one("""select count(*) n, sum(case when relevant=1 then 1 else 0 end) rel from records where source_id=? and discovered_at>=date('now','-60 day')""", (s["id"],))
            if st["n"] >= 5 and (st["rel"] or 0) / st["n"] < 0.1: declining.append({**s, "n": st["n"], "rel": st["rel"] or 0})
        k = s["key"]
        if k in seen_keys: dups.append((s, seen_keys[k]))
        seen_keys[k] = s
        if s["content_hash"]:
            if s["content_hash"] in seen_hash: dups.append((s, seen_hash[s["content_hash"]]))
            seen_hash[s["content_hash"]] = s
    new_note = ""
    try:
        res = discovery.build_stack(cid, mode="audit", max_competitors=3)
        new = db.q(f"select * from sources where id in ({','.join(map(str, res['source_ids'])) or 0})")
    except Exception as e:
        new, new_note = [], f"(new-source discovery failed: {e})"
    L = [f"# Monthly Signal Stack Audit: {db.company(cid)['name']}", f"*Generated {now()} UTC*", "",
         f"Sources reviewed: {len(srcs)}", "", "## Dead URLs (3+ consecutive failures)"]
    L += [f"- {s['name']} ({s['target']}): {s['last_status']}. **Recommend removal**" for s in dead] or ["- None."]
    L += ["", "## Inactive sources (no new items in 60+ days)"] + ([f"- {s['name']}. Recommend review" for s in inactive] or ["- None."])
    L += ["", "## Declining relevance (<10% relevant over 60 days, 5+ items)"] + ([f"- {s['name']}: {s['rel']}/{s['n']} relevant. Recommend removal or re-scoping" for s in declining] or ["- None."])
    L += ["", "## Duplicates"] + ([f"- {a['name']} duplicates {b['name']}" for a, b in dups] or ["- None."])
    L += ["", "## Newly discovered sources (status: proposed, awaiting approval)" + (" " + new_note if new_note else "")]
    L += [f"- [{s['category']}] {s['name']}: {s['reason']}" for s in new] or ["- None."]
    md = "\n".join(L)
    return db.ex("insert into briefs(company_id,kind,created_at,title,markdown,json) values(?,?,?,?,?,?)",
                 (cid, "audit", now(), f"Source health audit {now()[:10]}", md,
                  json.dumps({"dead": [s["id"] for s in dead], "inactive": [s["id"] for s in inactive], "declining": [s["id"] for s in declining], "new": [s["id"] for s in new]})))

def reassess(cid, note=""):
    """After business context changed: re-score every source against the updated profile, retire the stale, add new, explain the diff."""
    srcs = db.q("select id,category,name,reason,entity from sources where company_id=? and status in ('approved','proposed') and kind!='upload'", (cid,))
    prompt = f"""The company's business context CHANGED. Re-assess each monitored source against the UPDATED context.
{db.ctx_text(cid, 6000)}
CHANGE NOTE FROM FOUNDER: {note or '(profile edited)'}
SOURCES: {json.dumps(srcs)[:14000]}
Return JSON {{"results": [{{"id": int, "relevance": 0-10, "keep": bool, "reason": str (what changed and why this source is still/no longer useful)}}]}}"""
    res = {x["id"]: x for x in llm.chat_json(prompt).get("results", []) if isinstance(x, dict) and "id" in x}
    kept, retired = [], []
    for s in srcs:
        r = res.get(s["id"])
        if not r: continue
        db.ex("update sources set relevance=? where id=?", (r.get("relevance"), s["id"]))
        if not r.get("keep", True):
            db.ex("update sources set status='retired', retire_reason=? where id=?", (r.get("reason"), s["id"])); retired.append({"id": s["id"], "name": s["name"], "reason": r.get("reason")})
        else:
            kept.append({"id": s["id"], "name": s["name"], "relevance": r.get("relevance"), "reason": r.get("reason")})
    new = discovery.build_stack(cid, mode="reassess")
    added = db.q(f"select id,category,name,reason from sources where id in ({','.join(map(str, new['source_ids'])) or 0})")
    diff = {"kept": kept, "retired": retired, "added": added, "rejected_candidates": new["rejected_candidates"]}
    db.ex("insert into stack_changes(company_id,created_at,note,diff_json) values(?,?,?,?)", (cid, now(), note, json.dumps(diff)))
    return diff
