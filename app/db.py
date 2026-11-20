import sqlite3, json
from contextlib import closing
from .config import DB_PATH, DEFAULT_SETTINGS

SCHEMA = """
create table if not exists companies(id integer primary key, name text, url text, research_json text, profile_json text, created_at text);
create table if not exists interview(id integer primary key, company_id integer, idx integer, topic text, question text, answer text, skipped integer default 0, followup integer default 0, created_at text, updated_at text);
create table if not exists competitors(id integer primary key, company_id integer, name text, url text, type text, why text, created_at text);
create table if not exists sources(id integer primary key, company_id integer, category text, kind text, name text, target text, key text, reason text, entity text,
  status text default 'proposed', added_by text default 'ai', fail_count integer default 0, last_status text, last_checked text, last_new_at text,
  content_hash text, snapshot_text text, relevance real, retire_reason text, created_at text, unique(company_id,key));
create table if not exists crawls(id integer primary key, source_id integer, company_id integer, ts text, status text, http_code integer, note text, items_seen integer default 0, items_new integer default 0, items_dup integer default 0);
create table if not exists records(id integer primary key, company_id integer, source_id integer, category text, entity text, title text, url text, norm_url text, publisher text,
  published_at text, discovered_at text, snippet text, dedupe_key text, title_key text, analysis_json text, analyzed_at text, relevant integer,
  impact_type text, urgency integer, reliability real, evidence real, strategic_relevance real, verification text, rank_score real, rank_explain text, unique(company_id,dedupe_key));
create table if not exists briefs(id integer primary key, company_id integer, kind text, created_at text, window_days integer, title text, markdown text, json text);
create table if not exists actions(id integer primary key, brief_id integer, company_id integer, text text, reason text, owner text, priority text, status text default 'open', created_at text);
create table if not exists job_runs(id integer primary key, job text, company_id integer, started text, finished text, status text, message text);
create table if not exists stack_changes(id integer primary key, company_id integer, created_at text, note text, diff_json text);
create table if not exists settings(key text primary key, value text);
create index if not exists ix_rec_c on records(company_id, category);
"""

def conn():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=wal")
    return c

def init():
    with closing(conn()) as c:
        c.executescript(SCHEMA); c.commit()

def q(sql, args=()):
    with closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None

def ex(sql, args=()):
    with closing(conn()) as c:
        cur = c.execute(sql, args); c.commit(); return cur.lastrowid

def jl(s, default=None):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default

def company(cid):
    c = one("select * from companies where id=?", (cid,))
    if not c: return None
    c["research"] = jl(c.get("research_json"), {}); c["profile"] = jl(c.get("profile_json"), {})
    return c

def ctx_text(cid, limit=7000):
    c = company(cid)
    r = c["research"] or {}
    slim = {k: r.get(k) for k in ("summary", "industry", "products_services", "customer_segments", "positioning", "geographies") if r.get(k)}
    s = f"COMPANY: {c['name']} ({c['url']})\nRESEARCH: {json.dumps(slim)}\nFOUNDER PROFILE: {json.dumps(c['profile'] or {})}"
    return s[:limit]

def get_settings():
    s = dict(DEFAULT_SETTINGS)
    for r in q("select * from settings"):
        s[r["key"]] = jl(r["value"], r["value"])
    return s

def set_settings(d):
    for k, v in d.items():
        if k in DEFAULT_SETTINGS:
            ex("insert into settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value", (k, json.dumps(v)))
    return get_settings()
