"""Source discovery: LLM *proposes*, real network checks *verify*. No hard-coded competitors or sources."""
import json, re
from urllib.parse import quote_plus
import feedparser
from . import db, fetch, llm, search
from .util import now, domain, norm_url

def gnews(q, region="US"):
    gl = region.upper()
    return f"https://news.google.com/rss/search?q={quote_plus(q + ' when:30d')}&hl=en-{gl}&gl={gl}&ceid={gl}:en"

def hn(q):
    return f"https://hn.algolia.com/api/v1/search_by_date?tags=story&query={quote_plus(q)}"

def _verify(kind, target):
    """Returns (ok, note). Verification = the source really answers right now."""
    try:
        if kind == "search":
            return (len(search.text(target, 3)) > 0, "search returns results")
        st, body, final = fetch.get(target, check_robots=(kind == "page"))
        if st != 200: return False, f"HTTP {st}"
        if kind == "rss":
            return (len(feedparser.parse(body).entries) > 0, "feed has entries")
        if kind == "hn":
            return ("hits" in body, "api ok")
        return (len(fetch.main_text(body, final)) > 200, "page has readable text")
    except Exception as e:
        return False, str(e)[:120]

def _add(cid, category, kind, name, target, reason, entity=None, added_by="ai", log=None):
    key = f"search:{target.lower()}" if kind == "search" else norm_url(target)
    if db.one("select id from sources where company_id=? and key=?", (cid, key)):
        return None
    ok, note = _verify(kind, target)
    if not ok:
        if log is not None: log.append({"name": name, "target": target, "dropped": note})
        return None
    return db.ex("insert into sources(company_id,category,kind,name,target,key,reason,entity,status,added_by,created_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                 (cid, category, kind, name, target, key, reason, entity, "proposed", added_by, now()))

def _find_site(name, hint=None):
    cands = []
    if hint:
        h = hint if hint.startswith("http") else "https://" + hint
        cands.append(h)
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    for r in search.text(f"{name} official website", 5):
        if slug[:6] in re.sub(r"[^a-z0-9]", "", domain(r["url"])):
            cands.append(r["url"])
    for u in cands:
        try:
            st, html, final = fetch.get(u)
            if st == 200: return f"{final.split('//')[0]}//{domain(final)}/"
        except Exception:
            continue
    return None

def build_stack(cid, mode="initial", max_competitors=8):
    """Create/extend the four-category Signal Stack. Returns a summary incl. candidates that failed verification."""
    c = db.company(cid); region = db.get_settings().get("region", "US")
    existing = [f"{s['category']}: {s['name']}" for s in db.q("select * from sources where company_id=? and status!='retired'", (cid,))]
    prompt = f"""Design a customised intelligence Signal Stack for this company.
{db.ctx_text(cid)}
MODE: {mode}. ALREADY MONITORED (do not repeat): {json.dumps(existing)[:3000]}

Return JSON:
{{"competitors": [{{"name": str, "website": str|null, "type": "direct"|"substitute"|"adjacent", "why": str}}]   // {5 if mode!='initial' else 7}-{max_competitors} REAL organisations a founder would care about; include substitutes
 "customer_queries": [{{"query": str, "why": str}}]   // 6-8 web-search queries (may use site:reddit.com, site:quora.com, site:linkedin.com, forums) that surface customers describing the problems this company solves: complaints, questions, alternatives considered. Phrase like real customers speak
 "customer_hn_queries": [{{"query": str, "why": str}}] // 1-2 short Hacker News queries (only if the audience is tech-savvy; else empty)
 "market_topics": [{{"query": str, "type": "regulatory"|"industry"|"economic"|"technology", "why": str}}] // 7-9 news queries about developments that would MATERIALLY affect this business (policy, regulation, admissions/industry requirements, country developments, consolidation, funding)
 "authorities": [{{"name": str, "website": str|null, "why": str}}] // 2-4 official bodies/regulators/industry associations whose press/news pages matter
}}
Be specific to this company's market and geography; no generic sources. Every 'why' must explain the relevance to THIS company."""
    plan = llm.chat_json(prompt, 0.4)
    log, added = [], []

    def add(*a, **k):
        i = _add(cid, *a, log=log, **k)
        if i: added.append(i)

    for comp in (plan.get("competitors") or [])[:max_competitors]:
        name = comp.get("name");
        if not name: continue
        site = _find_site(name, comp.get("website"))
        if not site:
            log.append({"name": name, "dropped": "could not verify an official website"}); continue
        if not db.one("select id from competitors where company_id=? and lower(name)=?", (cid, name.lower())):
            db.ex("insert into competitors(company_id,name,url,type,why,created_at) values(?,?,?,?,?,?)", (cid, name, site, comp.get("type"), comp.get("why"), now()))
        why = comp.get("why", "")
        add("competitors", "page", f"{name} - website changes", site, f"{comp.get('type','competitor').title()} competitor. {why} Watching the site for launches, pricing and positioning changes.", entity=name)
        add("competitors", "rss", f"{name} - news", gnews(f'"{name}"', region), f"News coverage of {name}: launches, partnerships, funding, expansion. {why}", entity=name)
        add("competitors", "search", f"{name} - reviews & complaints", f'"{name}" reviews complaints', f"Customer-voice evidence about {name}: what users dislike or praise, i.e. where {c['name']} can win or must defend.", entity=name)
    for q in plan.get("customer_queries") or []:
        add("customers", "search", f"Customer voice: {q['query'][:60]}", q["query"], q.get("why", ""))
    for q in plan.get("customer_hn_queries") or []:
        add("customers", "hn", f"Hacker News: {q['query']}", hn(q["query"]), q.get("why", ""))
    for t in plan.get("market_topics") or []:
        add("market", "rss", f"{t.get('type','market').title()}: {t['query'][:60]}", gnews(t["query"], region), t.get("why", ""))
    for a in plan.get("authorities") or []:
        site = _find_site(a.get("name", ""), a.get("website"))
        if site:
            add("market", "page", f"{a['name']} - official updates", site, a.get("why", "Official body; primary source for rules and requirements."))
        else:
            log.append({"name": a.get("name"), "dropped": "could not verify website"})
    return {"added": len(added), "source_ids": added, "rejected_candidates": log}
