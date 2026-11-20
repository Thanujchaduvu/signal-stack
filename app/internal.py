"""Internal intelligence: CSV / Excel / PDF / text uploads -> objections, lost-deal reasons, requests, patterns, risks (with verbatim quotes)."""
import json, io
from pathlib import Path
from . import db, llm
from .analysis import score
from .util import now, sha

MAX_CHUNKS = 6   # free-tier guard

def to_chunks(path: Path, size=6000):
    ext = path.suffix.lower(); text = ""
    if ext in (".csv", ".xlsx", ".xls"):
        import pandas as pd
        df = pd.read_csv(path) if ext == ".csv" else pd.read_excel(path)
        text = "\n".join(" | ".join(f"{c}: {v}" for c, v in row.items() if str(v) != "nan") for _, row in df.iterrows())
    elif ext == ".pdf":
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    else:
        text = path.read_text(errors="ignore")
    return [text[i:i + size] for i in range(0, len(text), size)][:MAX_CHUNKS], len(text)

def ingest(cid, path: Path, filename: str):
    chunks, n = to_chunks(path)
    if not n: raise RuntimeError("No readable text found in the file.")
    key = f"upload:{filename}"
    s = db.one("select * from sources where company_id=? and key=?", (cid, key))
    sid = s["id"] if s else db.ex("insert into sources(company_id,category,kind,name,target,key,reason,status,added_by,created_at) values(?,?,?,?,?,?,?,?,?,?)",
                                  (cid, "internal", "upload", f"Upload: {filename}", filename, key, "Founder-provided first-party data (CRM / feedback / transcripts).", "approved", "user", now()))
    added = 0
    for ch in chunks:
        prompt = f"""Extract business intelligence from this internal data (CRM export, feedback, transcript or report).
{db.ctx_text(cid, 3000)}
DATA:
{ch}
Return JSON {{"findings": [{{"type": "objection"|"lost_deal_reason"|"product_request"|"sales_pattern"|"risk"|"praise",
 "summary": str (what the data shows, with counts if the data itself supports counting), "quote": str (VERBATIM text copied from the data, <=300 chars, or ""),
 "impact_type": "opportunity"|"threat"|"neutral", "urgency": 1-5, "relevance": 0-10, "impact": 0-10, "why_it_matters": str, "suggested_consideration": str}}]}}
Only report patterns actually present in the data. Return an empty list if there are none."""
        for f in llm.chat_json(prompt).get("findings", []):
            q = (f.get("quote") or "").strip()
            if q and q not in ch: q = ""          # drop non-verbatim quotes: no fabricated evidence
            title = f"{f.get('type','finding').replace('_',' ').title()}: {f.get('summary','')[:120]}"
            dk = sha(key + title)
            if db.one("select id from records where company_id=? and dedupe_key=?", (cid, dk)): continue
            rid = db.ex("insert into records(company_id,source_id,category,title,url,norm_url,publisher,discovered_at,snippet,dedupe_key) values(?,?,?,?,?,?,?,?,?,?)",
                        (cid, sid, "internal", title, f"upload://{filename}", f"upload://{filename}", "internal-upload", now(), q or f.get("summary", ""), dk))
            r = db.one("select * from records where id=?", (rid,))
            a = {"relevance": min(10, max(0, float(f.get("relevance", 5)))), "impact": min(10, max(0, float(f.get("impact", 5)))), "urgency": int(min(5, max(1, int(f.get("urgency", 3)))))}
            sc = score(r, a, internal=True)
            imp = f.get("impact_type") if f.get("impact_type") in ("opportunity", "threat", "neutral") else "neutral"
            db.ex("""update records set analysis_json=?,analyzed_at=?,relevant=1,impact_type=?,urgency=?,reliability=?,evidence=?,strategic_relevance=?,verification=?,rank_score=?,rank_explain=? where id=?""",
                  (json.dumps({"event_type": f.get("type"), "what_happened": f.get("summary"), "business_area": "internal", "why_it_matters": f.get("why_it_matters"),
                               "suggested_consideration": f.get("suggested_consideration"), "relevance": a["relevance"], "impact": a["impact"]}),
                   now(), imp, a["urgency"], sc["reliability"], sc["evidence"], sc["strategic_relevance"], sc["verification"], sc["rank_score"], sc["rank_explain"], rid))
            added += 1
    db.ex("update sources set last_checked=?, last_status='ok', last_new_at=? where id=?", (now(), now(), sid))
    return {"chars_read": n, "chunks_analysed": len(chunks), "findings_added": added, "note": f"Only first {MAX_CHUNKS} chunks are analysed (free-tier guard)." if n > MAX_CHUNKS * 6000 else ""}
