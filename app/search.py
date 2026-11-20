"""Thin wrapper over the free `ddgs` metasearch library. Failures return [] (never fabricate)."""
def _client():
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    return DDGS()

def text(query, n=8, timelimit=None):
    try:
        return [{"title": r.get("title", ""), "url": r.get("href") or r.get("url", ""), "snippet": r.get("body", "")}
                for r in _client().text(query, max_results=n, timelimit=timelimit) or []]
    except Exception:
        return []

def news(query, n=8, timelimit="m"):
    try:
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("body", ""), "date": r.get("date"), "publisher": r.get("source")}
                for r in _client().news(query, max_results=n, timelimit=timelimit) or []]
    except Exception:
        return []
