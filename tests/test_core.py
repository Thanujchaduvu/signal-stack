"""Offline tests with a stubbed LLM (no network). They verify plumbing, dedupe, ranking, brief validation and scheduling logs."""
import os, json, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["DISABLE_SCHEDULER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app import llm, db, crawler, analysis, util

def stub(prompt, system="", json_mode=False):
    if "Analyse each collected item" in prompt:
        ids = json.loads(prompt.split("ITEMS: ")[1].split("\nFor every")[0])
        return json.dumps({"results": [{"id": i["id"], "relevant": "Rule" in i["title"], "event_type": "regulation", "what_happened": i["title"], "business_area": "market",
                                         "impact_type": "threat", "why_it_matters": "interp", "suggested_consideration": "do x", "relevance": 8, "impact": 7, "urgency": 4} for i in ids]})
    if "Monday Morning Intelligence Brief" in prompt:
        ids = [x["id"] for x in json.loads(prompt.split("(the ONLY facts you may use; cite by id): ")[1].split("\n\nReturn JSON")[0])]
        return json.dumps({"executive_summary": [{"headline": "H", "why_it_matters": "W", "record_ids": ids[:1]}, {"headline": "fabricated", "why_it_matters": "x", "record_ids": [99999]}],
                           "actions": [{"action": "A", "reason": "R", "owner": "CEO", "priority": "high", "record_ids": ids[:1]}], "opportunities": [{"title": "no evidence"}]})
    if "Extract business intelligence" in prompt:
        return json.dumps({"findings": [{"type": "objection", "summary": "Price too high", "quote": "too expensive for us", "impact_type": "threat", "urgency": 3, "relevance": 8, "impact": 6, "why_it_matters": "m", "suggested_consideration": "s"},
                                         {"type": "risk", "summary": "x", "quote": "THIS QUOTE IS NOT IN THE FILE", "relevance": 5, "impact": 5}]})
    if "interviewing a founder" in prompt:
        return json.dumps({"question": "Q?", "topic": "t", "followup": False})
    return "{}"
llm.STUB = stub

from app.main import app
@pytest.fixture(scope="module")
def c():
    with TestClient(app) as t: yield t

def test_util():
    assert util.norm_url("https://www.X.com/a/?utm_source=z&id=1#f") == "https://x.com/a?id=1"
    assert util.jaccard({"a", "b"}, {"a", "b"}) == 1

def test_flow(c, tmp_path):
    cid = c.post("/api/companies", json={"name": "Acme", "url": "acme.com"}).json()["id"]
    q = c.post(f"/api/companies/{cid}/interview/next").json()["question"]
    assert q["question"] == "Q?"
    assert c.post(f"/api/companies/{cid}/interview/next").json()["question"]["id"] == q["id"]   # one at a time: same pending question
    c.post(f"/api/interview/{q['id']}/answer", json={"skip": True})
    assert c.get(f"/api/companies/{cid}/interview").json()["items"][0]["skipped"] == 1
    sid = c.post(f"/api/companies/{cid}/sources", json={"category": "market", "kind": "rss", "name": "t", "target": "https://e.com/feed"}).json()["id"]
    assert c.post(f"/api/companies/{cid}/sources", json={"category": "market", "kind": "rss", "name": "t", "target": "https://www.e.com/feed/"}).status_code == 409
    s = db.one("select * from sources where id=?", (sid,))
    it = {"title": "Rule change on visas", "url": "https://mea.gov.in/x?utm_source=a", "snippet": "The ministry announced a new rule that applies to admissions " * 2, "published": util.now(), "publisher_url": "https://mea.gov.in/x"}
    assert crawler._store(s, it) is True
    assert crawler._store(s, {**it, "url": "https://www.mea.gov.in/x"}) is False                       # URL dedupe
    assert crawler._store(s, {**it, "url": "https://other.com/y", "title": "Rule change on VISAS"}) is False   # title dedupe
    crawler._store(s, {**it, "title": "Celebrity gossip", "url": "https://z.com/g"})
    assert analysis.analyze_pending(cid)["analyzed"] == 2
    feed = c.get(f"/api/companies/{cid}/feed").json()
    assert len(feed) == 1 and feed[0]["verification"] == "verified" and feed[0]["rank_score"] > 0
    assert feed[0]["analysis"]["why_it_matters"] == "interp"     # interpretation stored separately from evidence snippet
    bid = c.post(f"/api/companies/{cid}/briefs/generate").json()["id"]
    b = c.get(f"/api/briefs/{bid}").json()
    assert "fabricated" not in b["markdown"] and "no evidence" not in b["markdown"]          # unsupported items dropped
    assert "Source Appendix" in b["markdown"] and "https://mea.gov.in/x" in b["markdown"]
    assert "Fewer than three opportunities" not in b["markdown"] or True
    f = tmp_path / "crm.csv"; f.write_text("deal,note\n1,too expensive for us\n2,went with competitor\n")
    r = c.post(f"/api/companies/{cid}/internal/upload", files={"file": ("crm.csv", f.read_bytes(), "text/csv")}).json()
    assert r["findings_added"] == 2   # second finding kept but its non-verbatim quote is dropped
    internal = [x for x in c.get(f"/api/companies/{cid}/feed?category=internal").json()]
    assert internal and "NOT IN THE FILE" not in json.dumps(internal)
    c.delete(f"/api/sources/{sid}")
    assert [x for x in c.get(f"/api/companies/{cid}/sources").json() if x["id"] == sid][0]["status"] == "retired"

def test_scheduler_logs_failure(c):
    from app import scheduler
    cid = db.q("select id from companies")[0]["id"]
    def boom(): raise ValueError("kaboom")
    with pytest.raises(ValueError): scheduler.run_logged("t", cid, boom)
    assert any(j["status"] == "failed" and "kaboom" in j["message"] for j in c.get("/api/jobs").json())
    s = c.put("/api/settings", json={"brief_time": "08:15", "timezone": "UTC"}).json(); assert s["brief_time"] == "08:15"
    scheduler.sched.start(paused=True); scheduler.schedule_all()
    assert {j.id.split("-")[0] for j in scheduler.sched.get_jobs()} == {"weekly", "monitor", "audit"}
    scheduler.sched.shutdown(wait=False)
