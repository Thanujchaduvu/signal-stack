"""Intelligence analysis + ranking. Evidence (what the source says) is stored separately from interpretation (what we think it means).
Three independent measures: source reliability, evidence strength, strategic relevance. LLM output is never treated as proof."""
import json, math
from . import db, llm
from .config import WEIGHTS
from .util import now, domain, tokens, jaccard, age_days

HIGH = ("reuters.com", "apnews.com", "bbc.", "ft.com", "wsj.com", "bloomberg.com", "nytimes.com", "economictimes", "thehindu.com", "timesofindia", "insidehighered.com",
        "chronicle.com", "forbes.com", "techcrunch.com", "livemint.com", "indianexpress.com", "theguardian.com", "washingtonpost.com", "cnbc.com", "hindustantimes.com")
FORUM = ("reddit.com", "quora.com", "news.ycombinator.com", "facebook.com", "x.com", "twitter.com", "linkedin.com", "medium.com", "trustpilot.com", "glassdoor", "youtube.com")

def reliability(dom, own_domains=()):
    d = (dom or "").lower()
    if d.endswith(".gov") or ".gov." in d or d.endswith(".edu") or ".ac." in d or ".edu." in d or d.endswith(".int") or d.endswith(".nic.in"): return 0.92
    if any(d == o or d.endswith("." + o) for o in own_domains): return 0.8   # primary source for its own claims
    if any(h in d for h in HIGH): return 0.82
    if any(h in d for h in FORUM): return 0.4
    if "wikipedia.org" in d: return 0.6
    return 0.55

def corroboration(r):
    t = tokens(r["title"]); n = set()
    for o in db.q("select title,publisher from records where company_id=? and id!=? and discovered_at>=date('now','-30 day')", (r["company_id"], r["id"])):
        if o["publisher"] != r["publisher"] and jaccard(t, tokens(o["title"])) >= 0.5: n.add(o["publisher"])
    return len(n)

def evidence_strength(r, rel, corr, primary):
    s = 0.15 + (0.2 if r.get("published_at") else 0) + (0.15 if len(r.get("snippet") or "") > 80 else 0) + (0.2 if primary else 0) + 0.15 * min(corr, 2) + (0.1 if rel >= 0.8 else 0)
    return round(min(s, 1.0), 2)

def verification(ev, rel, publisher):
    if any(f in (publisher or "") for f in FORUM): return "anecdotal"   # customer voice: real quote, not a verified fact
    if ev >= 0.65 and rel >= 0.6: return "verified"
    if ev >= 0.45: return "single-source"
    return "unverified"

def novelty(r):
    t = tokens(r["title"]); m = 0.0
    for o in db.q("select title from records where company_id=? and id!=? and discovered_at<? order by id desc limit 300", (r["company_id"], r["id"], r["discovered_at"])):
        m = max(m, jaccard(t, tokens(o["title"])))
    return round(1 - m, 2)

def score(r, a, own_domains=(), internal=False):
    rel_ = 0.7 if internal else reliability(r["publisher"], own_domains)
    primary = internal or any((r["publisher"] or "").endswith(o) for o in own_domains) or rel_ >= 0.9
    corr = 0 if internal else corroboration(r)
    ev = 0.7 if internal else evidence_strength(r, rel_, corr, primary)
    age = age_days(r.get("published_at")) if r.get("published_at") else age_days(r["discovered_at"])
    recency = math.exp(-(age if age is not None else 14) / 14) * (1 if r.get("published_at") else 0.85)
    comp = {"relevance": a["relevance"] / 10, "impact": a["impact"] / 10, "urgency": a["urgency"] / 5, "credibility": (rel_ + ev) / 2,
            "recency": round(recency, 2), "novelty": 1.0 if internal else novelty(r)}
    rank = round(100 * sum(WEIGHTS[k] * comp[k] for k in WEIGHTS), 1)
    top = sorted(comp, key=lambda k: -WEIGHTS[k] * comp[k])[:3]
    why = f"Rank {rank}: strongest drivers = " + ", ".join(f"{k} {comp[k]:.2f}" for k in top) + f"; source reliability {rel_:.2f}, evidence strength {ev:.2f}, strategic relevance {a['relevance']}/10."
    return dict(reliability=rel_, evidence=ev, strategic_relevance=a["relevance"] / 10, rank_score=rank,
                verification="internal-data" if internal else verification(ev, rel_, r["publisher"]), rank_explain=json.dumps({"components": comp, "why": why}))

def _num(x, lo, hi, d):
    try: return max(lo, min(hi, float(x)))
    except Exception: return d

def analyze_pending(cid, limit=80, batch=8):
    comp_domains = [domain(x["url"]) for x in db.q("select url from competitors where company_id=?", (cid,))] + [domain(db.company(cid)["url"])]
    rows = db.q("select r.*, s.name sname from records r join sources s on s.id=r.source_id where r.company_id=? and r.analyzed_at is null and s.kind!='upload' order by r.id desc limit ?", (cid, limit))
    done = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        items = [{"id": r["id"], "category": r["category"], "source": r["sname"], "entity": r["entity"], "title": r["title"], "snippet": (r["snippet"] or "")[:450], "published": r["published_at"]} for r in chunk]
        prompt = f"""Analyse each collected item for this company.
{db.ctx_text(cid, 5000)}
ITEMS: {json.dumps(items)}
For every item return an object in a JSON list under key "results":
{{"id": int, "relevant": bool (does it materially touch this company's customers, competitors, market or decisions? generic news = false),
 "event_type": str (e.g. product launch, pricing, partnership, funding, regulation, complaint, question, unmet need, hiring, other),
 "what_happened": str (ONLY what the item itself states; no speculation),
 "business_area": str, "impact_type": "opportunity"|"threat"|"neutral",
 "why_it_matters": str (your strategic INTERPRETATION for this company, concrete, 1-2 sentences),
 "suggested_consideration": str (a specific action to consider),
 "relevance": 0-10, "impact": 0-10, "urgency": 1-5}}
Be strict: most generic articles are NOT relevant. Do not infer facts absent from the item."""
        try:
            res = {x["id"]: x for x in llm.chat_json(prompt).get("results", []) if isinstance(x, dict) and "id" in x}
        except Exception:
            continue
        for r in chunk:
            a = res.get(r["id"])
            if not a: continue
            a["relevance"] = _num(a.get("relevance"), 0, 10, 0); a["impact"] = _num(a.get("impact"), 0, 10, 0); a["urgency"] = int(_num(a.get("urgency"), 1, 5, 1))
            sc = score(r, a, comp_domains)
            imp = a.get("impact_type") if a.get("impact_type") in ("opportunity", "threat", "neutral") else "neutral"
            db.ex("""update records set analysis_json=?, analyzed_at=?, relevant=?, impact_type=?, urgency=?, reliability=?, evidence=?, strategic_relevance=?,
                     verification=?, rank_score=?, rank_explain=? where id=?""",
                  (json.dumps({k: a.get(k) for k in ("event_type", "what_happened", "business_area", "why_it_matters", "suggested_consideration", "relevance", "impact")}),
                   now(), int(bool(a.get("relevant")) and a["relevance"] >= 4), imp, a["urgency"], sc["reliability"], sc["evidence"], sc["strategic_relevance"],
                   sc["verification"], sc["rank_score"], sc["rank_explain"], r["id"]))
            done += 1
    return {"analyzed": done, "pending": len(rows) - done}
