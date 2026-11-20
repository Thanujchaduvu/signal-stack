"""End-to-end CLI run for any company (used to produce the three sample reports).
   python -m scripts.run_demo --name MeetUniversity --url https://www.meetuniversity.com [--answers answers.json]
Interview answers come from YOU (file: JSON list of strings, or typed interactively; blank = skip). Nothing is pre-filled."""
import argparse, json, pathlib
from app import db, research, interview, discovery, crawler, analysis, brief

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--name", required=True); ap.add_argument("--url", required=True); ap.add_argument("--answers")
    ap.add_argument("--out", default="reports"); a = ap.parse_args()
    db.init()
    cid = db.ex("insert into companies(name,url,created_at) values(?,?,datetime('now'))", (a.name, a.url))
    print("1/7 researching..."); research.research(cid)
    given = json.load(open(a.answers)) if a.answers else None
    for i in range(interview.TOTAL):
        q = interview.next_question(cid)["question"]; print(f"\nQ{i+1}: {q['question']}")
        ans = (given[i] if given and i < len(given) else "") if given else input("> ").strip()
        interview.answer(q["id"], ans or None, skip=not ans)
    print("2/7 building profile..."); interview.build_profile(cid)
    print("3/7 discovering + verifying sources (slow)..."); r = discovery.build_stack(cid); print("   added", r["added"], "dropped", len(r["rejected_candidates"]))
    db.ex("update sources set status='approved' where company_id=? and status='proposed'", (cid,))
    print("4/7 crawling..."); print("  ", crawler.crawl_company(cid, force=True))
    print("5/7 analysing..."); print("  ", analysis.analyze_pending(cid, limit=200))
    print("6/7 brief..."); bid = brief.generate(cid)
    out = pathlib.Path(a.out); out.mkdir(exist_ok=True)
    p = out / f"{a.name.lower().replace(' ', '_')}_brief.md"; p.write_text(db.one("select markdown from briefs where id=?", (bid,))["markdown"])
    print("7/7 wrote", p)

if __name__ == "__main__": main()
