"""Monitoring engine: visit approved sources, detect new/changed content, dedupe, store evidence + history."""
import difflib, json, datetime as dt
import feedparser, httpx
from . import db, fetch, search
from .config import ua
from .util import now, sha, norm_url, domain, parse_dt, strip_tags, tokens, jaccard, age_days

def _items(s):
    k, t = s["kind"], s["target"]
    if k == "rss":
        st, body, _ = fetch.get(t, check_robots=False)
        if st != 200: raise RuntimeError(f"HTTP {st}")
        out = []
        for e in feedparser.parse(body).entries[:20]:
            src = e.get("source") or {}
            out.append({"title": e.get("title", ""), "url": e.get("link", ""), "snippet": strip_tags(e.get("summary", ""))[:600],
                        "published": parse_dt(e.get("published_parsed")), "publisher": src.get("title"), "publisher_url": src.get("href")})
        return out, 200
    if k == "hn":
        st, body, _ = fetch.get(t, check_robots=False)
        if st != 200: raise RuntimeError(f"HTTP {st}")
        out = []
        for h in json.loads(body).get("hits", [])[:20]:
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            out.append({"title": h.get("title") or "", "url": url, "snippet": strip_tags(h.get("story_text") or "")[:600],
                        "published": parse_dt(h.get("created_at")), "publisher": "Hacker News", "publisher_url": "https://news.ycombinator.com"})
        return out, 200
    if k == "search":
        res = search.text(t, 10, timelimit="m") or search.text(t, 10)
        if not res: raise RuntimeError("search returned no results")
        return [{"title": r["title"], "url": r["url"], "snippet": r["snippet"][:600], "published": None,
                 "publisher": domain(r["url"]), "publisher_url": r["url"]} for r in res], 200
    if k == "page":
        st, html, final = fetch.get(t)
        if st != 200: raise RuntimeError(f"HTTP {st}")
        text = fetch.main_text(html, final)
        h = sha(" ".join(text.split()))
        if not s["content_hash"]:
            db.ex("update sources set content_hash=?, snapshot_text=? where id=?", (h, text[:60000], s["id"]))
            return [], 200  # baseline snapshot only: nothing is reported as "new" on first visit
        if h == s["content_hash"]:
            return [], 200
        old = (s["snapshot_text"] or "").splitlines()
        added = [l[2:].strip() for l in difflib.ndiff(old, text.splitlines()) if l.startswith("+ ") and len(l) > 25]
        db.ex("update sources set content_hash=?, snapshot_text=? where id=?", (h, text[:60000], s["id"]))
        if not added: return [], 200
        return [{"title": f"Page changed: {s['name']}", "url": final, "snippet": " ".join(added)[:700], "published": None,
                 "publisher": domain(final), "publisher_url": final, "uniq": h}], 200
    raise RuntimeError(f"unsupported kind {k}")

def _store(s, it):
    """Insert record unless duplicate (same URL or near-identical title). Returns True if new."""
    if not it["title"] and not it["snippet"]: return False
    nu = norm_url(it["url"]) if it.get("url") else ""
    dkey = sha(nu or it["title"]) if not it.get("uniq") else sha(nu + it["uniq"])
    tkey = sha(" ".join(sorted(tokens(it["title"])))) if it["title"] and not it.get("uniq") else None
    cid = s["company_id"]
    if db.one("select id from records where company_id=? and dedupe_key=?", (cid, dkey)): return False
    if tkey and db.one("select id from records where company_id=? and title_key=?", (cid, tkey)): return False
    pub = it.get("publisher_url") or it.get("url")
    db.ex("""insert into records(company_id,source_id,category,entity,title,url,norm_url,publisher,published_at,discovered_at,snippet,dedupe_key,title_key)
             values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (cid, s["id"], s["category"], s.get("entity"), it["title"][:300], it.get("url"), nu, domain(pub) or it.get("publisher"),
           it.get("published"), now(), it["snippet"], dkey, tkey))
    return True

def crawl_source(s, force=False):
    hrs = db.get_settings().get("source_refresh_hours", 12)
    a = age_days(s["last_checked"]) if s["last_checked"] else None
    if not force and a is not None and a * 24 < float(hrs):
        return {"skipped": "refreshed recently"}
    seen = new = dup = 0; code = None; err = None
    try:
        items, code = _items(s)
        seen = len(items)
        for it in items:
            if _store(s, it): new += 1
            else: dup += 1
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
    ts = now()
    db.ex("insert into crawls(source_id,company_id,ts,status,http_code,note,items_seen,items_new,items_dup) values(?,?,?,?,?,?,?,?,?)",
          (s["id"], s["company_id"], ts, "error" if err else "ok", code, err, seen, new, dup))
    if err:
        db.ex("update sources set fail_count=fail_count+1,last_status=?,last_checked=? where id=?", (err, ts, s["id"]))
    else:
        db.ex("update sources set fail_count=0,last_status='ok',last_checked=?,last_new_at=coalesce(?,last_new_at) where id=?", (ts, ts if new else None, s["id"]))
    return {"seen": seen, "new": new, "dup": dup, "error": err}

def crawl_company(cid, force=False):
    srcs = db.q("select * from sources where company_id=? and status='approved' and kind!='upload'", (cid,))
    res = {"sources": len(srcs), "new_records": 0, "errors": 0, "skipped": 0}
    for s in srcs:
        r = crawl_source(s, force)
        if r.get("skipped"): res["skipped"] += 1
        res["new_records"] += r.get("new", 0)
        res["errors"] += 1 if r.get("error") else 0
    return res
