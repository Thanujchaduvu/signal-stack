"""Adaptive 10-question interview: one question at a time, memory of answers, follow-ups, skip, editable."""
import json
from . import db, llm
from .util import now

TOTAL = 10
AREAS = ["primary business lines and revenue streams", "highest-value customer segments", "current customer problems and unmet needs",
         "why customers choose the company over alternatives", "important competitors or substitutes", "major industry/market changes",
         "developments that could materially affect the business", "growth priorities for the next 6-12 months",
         "internal business information that should influence decisions", "decisions the intelligence system should help the founder make"]

def history(cid):
    return db.q("select * from interview where company_id=? order by idx", (cid,))

def next_question(cid):
    rows = history(cid)
    pending = [r for r in rows if r["answer"] is None and not r["skipped"]]
    if pending:
        return {"done": False, "question": pending[0]}
    if len(rows) >= TOTAL:
        return {"done": True}
    qa = [{"q": r["question"], "a": "(skipped - confidential)" if r["skipped"] else r["answer"], "topic": r["topic"]} for r in rows]
    prompt = f"""You are interviewing a founder to configure a competitive/market intelligence system for their company.
{db.ctx_text(cid, 5000)}

INTERVIEW SO FAR: {json.dumps(qa)}
This will be question {len(rows)+1} of {TOTAL}.
Coverage areas (guidance only; adapt wording to THIS company's industry, vocabulary and research): {json.dumps(AREAS)}

Rules: ask exactly ONE question. Never repeat or rephrase an earlier question. Do not re-ask skipped topics.
If the previous answer was vague, contradictory or revealed an important lead, ask a sharp follow-up (followup=true); otherwise move to the least-covered area.
Questions must be specific to this company (reference its products, segments or market), not generic.
Return JSON: {{"question": str, "topic": str, "followup": bool}}"""
    r = llm.chat_json(prompt, 0.5)
    qid = db.ex("insert into interview(company_id,idx,topic,question,followup,created_at) values(?,?,?,?,?,?)",
                (cid, len(rows) + 1, r.get("topic", ""), r["question"], int(bool(r.get("followup"))), now()))
    return {"done": False, "question": db.one("select * from interview where id=?", (qid,))}

def answer(qid, text=None, skip=False):
    db.ex("update interview set answer=?, skipped=?, updated_at=? where id=?", (None if skip else text, int(skip), now(), qid))

def build_profile(cid):
    """(Re)builds the structured company intelligence profile from research + interview answers."""
    qa = [{"q": r["question"], "a": r["answer"]} for r in history(cid) if r["answer"]]
    if not qa:
        raise RuntimeError("Answer at least one interview question first.")
    prompt = f"""Build a structured company intelligence profile from the research and founder answers.
{db.ctx_text(cid, 4000)}
FOUNDER ANSWERS: {json.dumps(qa)}
Use only what was stated; leave empty lists where unknown. Return JSON with keys:
business_lines (list), revenue_streams (list), priority_segments (list), customer_problems (list), differentiators (list),
named_competitors (list of strings the founder mentioned), market_changes_to_watch (list), material_risks (list),
growth_priorities (list), internal_data_sources (list), decisions_to_support (list), keywords (list of 8-15 monitoring keywords/phrases)."""
    p = llm.chat_json(prompt)
    p["updated_at"] = now()
    db.ex("update companies set profile_json=? where id=?", (json.dumps(p), cid))
    return p
