"""Initial company research: real pages + public search snippets -> facts (with source URL) vs assumptions."""
import json
from . import db, fetch, llm, search
from .util import now, domain, norm_url

KEYS = ("about", "pricing", "product", "solution", "service", "program", "customer", "partner", "blog", "news", "university", "student", "how-it-works", "faq")

def research(cid):
    c = db.company(cid)
    base = c["url"] if c["url"].startswith("http") else "https://" + c["url"]
    pages, limits = [], []
    try:
        st, html, final = fetch.get(base)
        if st == 200:
            pages.append({"url": final, "text": fetch.main_text(html, final)[:3500]})
            cands = [u for u in fetch.links(html, final) if any(k in u.lower() for k in KEYS)][:6]
            for u in cands:
                try:
                    s2, h2, f2 = fetch.get(u)
                    if s2 == 200 and (t := fetch.main_text(h2, f2)):
                        pages.append({"url": f2, "text": t[:2500]})
                except Exception as e:
                    limits.append(f"Could not fetch {u}: {e}")
        else:
            limits.append(f"Homepage returned HTTP {st}")
    except Exception as e:
        limits.append(f"Homepage fetch failed: {e}")
    snippets = []
    for qy in (f'"{c["name"]}" {domain(base)}', f'"{c["name"]}" reviews customers', f'"{c["name"]}" competitors alternatives'):
        snippets += [{"url": r["url"], "title": r["title"], "snippet": r["snippet"]} for r in search.text(qy, 6)]
    if not pages and not snippets:
        raise RuntimeError("No public information could be retrieved (site unreachable and search returned nothing). " + "; ".join(limits))
    allowed_urls = {norm_url(p["url"]) for p in pages} | {norm_url(s["url"]) for s in snippets if s["url"]}
    prompt = f"""Research the company below using ONLY the provided material.
COMPANY: {c['name']} | {base}
WEBSITE PAGES:
{json.dumps(pages)[:14000]}
SEARCH SNIPPETS:
{json.dumps(snippets)[:6000]}

Return JSON with keys:
summary (3-4 sentences), industry, products_services (list), customer_segments (list), positioning (string), geographies (list),
verified_facts: list of {{"fact": str, "source_url": str}} - each fact must be directly supported by the material and source_url must be copied exactly from it,
assumptions: list of {{"assumption": str, "basis": str}} - plausible inferences NOT directly stated,
unknowns: list of important things you could not determine."""
    r = llm.chat_json(prompt)
    good, demoted = [], []
    for f in r.get("verified_facts", []):
        (good if norm_url(f.get("source_url", "")) in allowed_urls else demoted).append(f)
    r["verified_facts"] = good
    r["assumptions"] = (r.get("assumptions") or []) + [{"assumption": f.get("fact"), "basis": "Demoted: cited source not among fetched material"} for f in demoted]
    r["pages_fetched"] = [p["url"] for p in pages]
    r["limitations"] = limits
    r["researched_at"] = now()
    db.ex("update companies set research_json=? where id=?", (json.dumps(r), cid))
    return r
