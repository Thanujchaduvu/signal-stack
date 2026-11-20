import os, json, shutil
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import db, research as rs, interview as iv, discovery, crawler, analysis, brief, audit, internal, scheduler, llm
from .config import BASE, UPLOADS
from .util import now

@asynccontextmanager
async def lifespan(app):
    db.init()
    if os.getenv("DISABLE_SCHEDULER") != "1": scheduler.start()
    yield

app = FastAPI(title="Signal Stack", lifespan=lifespan)

@app.exception_handler(llm.LLMUnavailable)
async def _llm_err(_, e): return JSONResponse({"detail": str(e)}, status_code=503)

@app.exception_handler(RuntimeError)
async def _rt_err(_, e): return JSONResponse({"detail": str(e)}, status_code=502)

def need(cid):
    c = db.company(cid)
    if not c: raise HTTPException(404, "Company not found")
    return c

class NewCompany(BaseModel): name: str; url: str
class SourceIn(BaseModel): category: str; kind: str; name: str; target: str; reason: str = ""; entity: Optional[str] = None
class Ans(BaseModel): answer: Optional[str] = None; skip: bool = False
class Note(BaseModel): note: str = ""

@app.get("/api/health")
def health(): return {"ok": True, "llm_provider": llm.provider() or None}

@app.post("/api/companies")
def create_company(b: NewCompany):
    url = b.url.strip() if b.url.startswith("http") else "https://" + b.url.strip()
    cid = db.ex("insert into companies(name,url,created_at) values(?,?,?)", (b.name.strip(), url, now()))
    if scheduler.sched.running: scheduler.schedule_all()
    return db.company(cid)

@app.get("/api/companies")
def companies(): return db.q("select id,name,url,created_at, (research_json is not null) researched, (profile_json is not null) profiled from companies order by id")

@app.get("/api/companies/{cid}")
def get_company(cid: int): return need(cid)

@app.post("/api/companies/{cid}/research")
def do_research(cid: int): need(cid); return rs.research(cid)

@app.get("/api/companies/{cid}/profile")
def get_profile(cid: int): return need(cid)["profile"] or {}

@app.put("/api/companies/{cid}/profile")
def put_profile(cid: int, p: dict):
    need(cid); p["updated_at"] = now(); db.ex("update companies set profile_json=? where id=?", (json.dumps(p), cid)); return p

@app.post("/api/companies/{cid}/profile/rebuild")
def rebuild(cid: int): need(cid); return iv.build_profile(cid)

# ---- interview
@app.get("/api/companies/{cid}/interview")
def interview_hist(cid: int): need(cid); return {"total": iv.TOTAL, "items": iv.history(cid)}

@app.post("/api/companies/{cid}/interview/next")
def interview_next(cid: int): need(cid); return iv.next_question(cid)

@app.post("/api/interview/{qid}/answer")
def interview_answer(qid: int, b: Ans): iv.answer(qid, b.answer, b.skip); return {"ok": True}

# ---- stack / sources
@app.post("/api/companies/{cid}/stack/build")
def stack_build(cid: int): need(cid); return discovery.build_stack(cid)

@app.get("/api/companies/{cid}/competitors")
def competitors(cid: int): return db.q("select * from competitors where company_id=?", (cid,))

@app.get("/api/companies/{cid}/sources")
def sources(cid: int):
    return [{k: v for k, v in r.items() if k != "snapshot_text"} for r in db.q("""select s.*, (select count(*) from records r where r.source_id=s.id) records,
        (select coalesce(sum(items_dup),0) from crawls c where c.source_id=s.id) dups,
        (select count(*) from crawls c where c.source_id=s.id) crawl_count,
        case when s.fail_count>=3 then 'dead' when s.fail_count>0 then 'degraded' when s.last_checked is null then 'unchecked' else 'healthy' end health
        from sources s where s.company_id=? order by s.category, s.id""", (cid,))]

@app.post("/api/companies/{cid}/sources")
def add_source(cid: int, b: SourceIn):
    need(cid)
    if b.category not in ("customers", "competitors", "market", "internal") or b.kind not in ("rss", "page", "search", "hn"):
        raise HTTPException(400, "category must be customers|competitors|market|internal and kind rss|page|search|hn")
    from .util import norm_url
    key = f"search:{b.target.lower()}" if b.kind == "search" else norm_url(b.target)
    if db.one("select id from sources where company_id=? and key=?", (cid, key)): raise HTTPException(409, "Duplicate source")
    sid = db.ex("insert into sources(company_id,category,kind,name,target,key,reason,entity,status,added_by,created_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                (cid, b.category, b.kind, b.name, b.target, key, b.reason or "Added manually by founder", b.entity, "approved", "user", now()))
    return {"id": sid}

@app.post("/api/sources/{sid}/approve")
def approve(sid: int): db.ex("update sources set status='approved' where id=?", (sid,)); return {"ok": True}

@app.post("/api/companies/{cid}/sources/approve_all")
def approve_all(cid: int): db.ex("update sources set status='approved' where company_id=? and status='proposed'", (cid,)); return {"ok": True}

@app.delete("/api/sources/{sid}")
def remove_source(sid: int):
    db.ex("update sources set status='retired', retire_reason='Removed by user' where id=?", (sid,)); return {"ok": True}

@app.get("/api/sources/{sid}/history")
def src_history(sid: int):
    return {"crawls": db.q("select * from crawls where source_id=? order by id desc limit 50", (sid,)),
            "records": db.q("select id,title,url,discovered_at,rank_score,verification from records where source_id=? order by id desc limit 30", (sid,))}

# ---- monitoring / analysis / feed
@app.post("/api/companies/{cid}/crawl")
def crawl(cid: int, force: bool = True): need(cid); return scheduler.run_logged("manual_crawl", cid, lambda: crawler.crawl_company(cid, force))

@app.post("/api/companies/{cid}/analyze")
def analyze(cid: int): need(cid); return scheduler.run_logged("manual_analyze", cid, lambda: analysis.analyze_pending(cid))

@app.get("/api/companies/{cid}/feed")
def feed(cid: int, category: str = "", entity: str = "", since: str = "", min_rank: float = 0, impact: str = "", verification: str = "", include_irrelevant: bool = False, limit: int = 200):
    sql, a = "select r.*, s.name source_name from records r join sources s on s.id=r.source_id where r.company_id=?", [cid]
    if not include_irrelevant: sql += " and r.relevant=1"
    for col, v in (("r.category", category), ("r.entity", entity), ("r.impact_type", impact), ("r.verification", verification)):
        if v: sql += f" and {col}=?"; a.append(v)
    if since: sql += " and coalesce(r.published_at,r.discovered_at)>=?"; a.append(since)
    if min_rank: sql += " and r.rank_score>=?"; a.append(min_rank)
    rows = db.q(sql + " order by coalesce(r.published_at,r.discovered_at) desc limit ?", (*a, limit))
    for r in rows:
        r["analysis"] = db.jl(r.pop("analysis_json"), {}); r["rank_explain"] = db.jl(r["rank_explain"], {})
    return rows

@app.get("/api/companies/{cid}/stats")
def stats(cid: int):
    return {"records": db.one("select count(*) n from records where company_id=?", (cid,))["n"],
            "analyzed": db.one("select count(*) n from records where company_id=? and analyzed_at is not null", (cid,))["n"],
            "relevant": db.one("select count(*) n from records where company_id=? and relevant=1", (cid,))["n"],
            "sources_approved": db.one("select count(*) n from sources where company_id=? and status='approved'", (cid,))["n"],
            "crawls": db.one("select count(*) n from crawls where company_id=?", (cid,))["n"]}

# ---- briefs
@app.post("/api/companies/{cid}/briefs/generate")
def gen_brief(cid: int, window_days: Optional[int] = None): need(cid); return {"id": scheduler.run_logged("manual_brief", cid, lambda: brief.generate(cid, window_days))}

@app.get("/api/companies/{cid}/briefs")
def briefs(cid: int, kind: str = ""):
    return db.q("select id,kind,created_at,title,window_days from briefs where company_id=?" + (" and kind=?" if kind else "") + " order by id desc", (cid, kind) if kind else (cid,))

@app.get("/api/briefs/{bid}")
def get_brief(bid: int):
    b = db.one("select * from briefs where id=?", (bid,))
    if not b: raise HTTPException(404)
    b["html"] = brief.render_html(b["markdown"], b["title"]); return b

@app.get("/api/briefs/{bid}/export")
def export(bid: int, fmt: str = "md"):
    b = db.one("select * from briefs where id=?", (bid,))
    if not b: raise HTTPException(404)
    if fmt == "html": return HTMLResponse(brief.render_html(b["markdown"], b["title"]), headers={"Content-Disposition": f'attachment; filename="brief-{bid}.html"'})
    return PlainTextResponse(b["markdown"], headers={"Content-Disposition": f'attachment; filename="brief-{bid}.md"'})

@app.get("/api/companies/{cid}/actions")
def actions(cid: int): return db.q("select * from actions where company_id=? order by id desc", (cid,))

@app.put("/api/actions/{aid}")
def upd_action(aid: int, b: dict):
    if b.get("status") not in ("open", "in_progress", "done", "dismissed"): raise HTTPException(400, "bad status")
    db.ex("update actions set status=? where id=?", (b["status"], aid)); return {"ok": True}

# ---- internal / audit / reassess
@app.post("/api/companies/{cid}/internal/upload")
def upload(cid: int, file: UploadFile = File(...)):
    need(cid)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xlsx", ".xls", ".pdf", ".txt", ".md"): raise HTTPException(400, "Supported: CSV, Excel, PDF, TXT")
    dest = UPLOADS / f"{cid}_{os.path.basename(file.filename)}"
    with open(dest, "wb") as f: shutil.copyfileobj(file.file, f)
    return internal.ingest(cid, dest, os.path.basename(file.filename))

@app.post("/api/companies/{cid}/audit/run")
def run_audit(cid: int): need(cid); return {"id": scheduler.monthly(cid) and db.one("select max(id) i from briefs where company_id=? and kind='audit'", (cid,))["i"]}

@app.post("/api/companies/{cid}/reassess")
def reassess(cid: int, b: Note): need(cid); return scheduler.run_logged("reassess", cid, lambda: audit.reassess(cid, b.note))

@app.get("/api/companies/{cid}/stack_changes")
def changes(cid: int):
    return [{**r, "diff": db.jl(r.pop("diff_json"), {})} for r in db.q("select * from stack_changes where company_id=? order by id desc", (cid,))]

# ---- settings / jobs
@app.get("/api/settings")
def get_settings(): return {**db.get_settings(), "_next_runs": scheduler.next_runs() if scheduler.sched.running else []}

@app.put("/api/settings")
def put_settings(b: dict):
    s = db.set_settings(b)
    if scheduler.sched.running: scheduler.schedule_all()
    return s

@app.get("/api/jobs")
def jobs(): return db.q("select j.*, c.name company from job_runs j left join companies c on c.id=j.company_id order by j.id desc limit 100")

@app.post("/api/companies/{cid}/jobs/{job}")
def trigger(cid: int, job: str):
    fn = {"weekly": scheduler.weekly, "monitor": scheduler.monitor, "audit": scheduler.monthly}.get(job)
    if not fn: raise HTTPException(400, "job must be weekly|monitor|audit")
    fn(cid); return {"ok": True}

app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
