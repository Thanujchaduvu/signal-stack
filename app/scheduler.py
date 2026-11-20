"""APScheduler: weekly brief, periodic monitoring, monthly audit. Every run is logged; failures are visible in the dashboard."""
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from . import db, crawler, analysis, brief, audit
from .util import now

sched = BackgroundScheduler(job_defaults={"coalesce": True, "misfire_grace_time": 3600, "max_instances": 1})

def run_logged(job, cid, fn):
    rid = db.ex("insert into job_runs(job,company_id,started,status) values(?,?,?,?)", (job, cid, now(), "running"))
    try:
        msg = fn()
        db.ex("update job_runs set finished=?,status='ok',message=? where id=?", (now(), str(msg)[:1500], rid)); return msg
    except Exception as e:
        db.ex("update job_runs set finished=?,status='failed',message=? where id=?", (now(), (f"{type(e).__name__}: {e}\n" + traceback.format_exc())[-1500:], rid)); raise

def weekly(cid):
    def f():
        c = crawler.crawl_company(cid, force=True); a = analysis.analyze_pending(cid); b = brief.generate(cid)
        return f"crawl={c} analysis={a} brief_id={b}"
    return run_logged("weekly_brief", cid, f)

def monitor(cid):
    return run_logged("monitor", cid, lambda: f"crawl={crawler.crawl_company(cid)} analysis={analysis.analyze_pending(cid)}")

def monthly(cid):
    return run_logged("monthly_audit", cid, lambda: f"audit_brief_id={audit.audit(cid)}")

def _safe(fn, cid):
    try: fn(cid)
    except Exception: pass   # already logged in job_runs

def schedule_all():
    s = db.get_settings(); tz = s["timezone"]; hh, mm = str(s["brief_time"]).split(":")
    for j in sched.get_jobs(): j.remove()
    for c in db.q("select id from companies"):
        i = c["id"]
        sched.add_job(_safe, CronTrigger(day_of_week=s["brief_day"], hour=int(hh), minute=int(mm), timezone=tz), args=[weekly, i], id=f"weekly-{i}")
        sched.add_job(_safe, IntervalTrigger(hours=int(s["monitor_hours"])), args=[monitor, i], id=f"monitor-{i}")
        sched.add_job(_safe, CronTrigger(day=int(s["audit_day"]), hour=3, minute=0, timezone=tz), args=[monthly, i], id=f"audit-{i}")

def start():
    db.ex("update job_runs set status='failed', finished=?, message='Interrupted by restart' where status='running'", (now(),))
    if not sched.running: sched.start()
    schedule_all()

def next_runs():
    return [{"id": j.id, "next_run": str(j.next_run_time)} for j in sched.get_jobs()]
