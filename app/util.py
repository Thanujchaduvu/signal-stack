import hashlib, re, datetime as dt
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def sha(s):
    return hashlib.sha1((s or "").encode("utf-8", "ignore")).hexdigest()

def domain(u):
    h = urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h

_TRACK = ("utm_", "fbclid", "gclid", "mc_", "ref_")

def norm_url(u):
    p = urlparse((u or "").strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(_TRACK)]
    return urlunparse(((p.scheme or "https").lower(), domain(u), p.path.rstrip("/") or "/", "", urlencode(q), ""))

_STOP = set("the and for with that this from are was were has have will your you our their about into over after more than what when how why who new its not but can all one out use per via".split())

def tokens(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower()) if w not in _STOP}

def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0

def parse_dt(x):
    if not x:
        return None
    if isinstance(x, (tuple, list)) or hasattr(x, "tm_year"):
        try:
            return dt.datetime(*tuple(x)[:6], tzinfo=dt.timezone.utc).isoformat(timespec="seconds")
        except Exception:
            return None
    try:
        d = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.isoformat(timespec="seconds")
    except Exception:
        return None

def age_days(iso):
    d = parse_dt(iso)
    if not d:
        return None
    return max(0.0, (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(d)).total_seconds() / 86400)

def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()
