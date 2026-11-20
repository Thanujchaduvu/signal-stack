"""Polite fetching: robots.txt, per-domain rate limit, identifiable UA. No auth/paywall bypass."""
import re, time, threading, httpx
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from .config import ua, crawl_delay
from .util import domain

class Blocked(Exception):
    pass

_robots, _last, _lock = {}, {}, threading.Lock()

def allowed(url):
    p = urlparse(url); base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = RobotFileParser()
        try:
            r = httpx.get(base + "/robots.txt", headers={"User-Agent": ua()}, timeout=8, follow_redirects=True)
            if r.status_code == 200: rp.parse(r.text.splitlines())
            elif r.status_code in (401, 403): rp.disallow_all = True
            else: rp.parse([])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(ua(), url)

def _wait(host):
    with _lock:
        d = crawl_delay() - (time.time() - _last.get(host, 0))
        if d > 0: time.sleep(d)
        _last[host] = time.time()

def get(url, check_robots=True, timeout=20):
    """Returns (status_code, text, final_url). Raises Blocked if robots.txt disallows."""
    if check_robots and not allowed(url):
        raise Blocked(f"robots.txt disallows {url}")
    _wait(domain(url))
    r = httpx.get(url, headers={"User-Agent": ua(), "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.8"}, timeout=timeout, follow_redirects=True)
    return r.status_code, r.text, str(r.url)

def main_text(html, url=None):
    import trafilatura
    t = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
    return (t or "").strip()

def links(html, base):
    out = []
    for h in re.findall(r'href=["\']([^"\'#]+)', html or ""):
        u = urljoin(base, h)
        if domain(u) == domain(base) and u.startswith("http"):
            out.append(u)
    return list(dict.fromkeys(out))
