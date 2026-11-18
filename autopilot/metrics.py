"""Sprint health and productivity metrics."""
import re
from datetime import date
from statistics import median

DOC_MIN_WORDS = 40
AC_PATTERN = re.compile(r"acceptance criteria", re.I)

# Thresholds for the Red / Amber / Green status of each pod.
THRESHOLDS = {
    "spillover_rate": (0.15, 0.30),      # green below 15%, red at 30% or more
    "adhoc_share": (0.15, 0.25),
    "closure_delay_days": (1, 3),
    "doc_quality": (0.80, 0.60),         # higher is better: green at 80%+, red below 60%
}


def _d(s):
    return date.fromisoformat(s) if s else None


def doc_ok(issue):
    """A story is 'well documented' if it has a real description and acceptance criteria."""
    text = issue.get("description") or ""
    return len(text.split()) >= DOC_MIN_WORDS and bool(AC_PATTERN.search(text))


def sprint_metrics(sprint, today=None):
    today = today or date.today()
    issues = sprint["issues"]
    planned = [i for i in issues if not i["added_after_start"]]
    adhoc = [i for i in issues if i["added_after_start"]]
    not_done_planned = [i for i in planned if i["status"] != "Done"]
    stories = [i for i in issues if i["type"] == "Story"]
    end = _d(sprint["end"])
    closed = _d(sprint.get("closed_at"))
    if closed:
        delay = max(0, (closed - end).days)
    elif sprint["state"] == "active" and end and today > end:
        delay = (today - end).days            # overdue and still open
    else:
        delay = 0
    return {
        "sprint": sprint["name"],
        "state": sprint["state"],
        "planned": len(planned),
        "completed_planned": len(planned) - len(not_done_planned),
        "spillover": [i["key"] for i in not_done_planned],
        "spillover_rate": len(not_done_planned) / len(planned) if planned else 0.0,
        "repeat_spillover": [i["key"] for i in not_done_planned if i.get("carried_from_previous")],
        "adhoc": [i["key"] for i in adhoc],
        "adhoc_share": len(adhoc) / len(issues) if issues else 0.0,
        "closure_delay_days": delay,
        "doc_quality": sum(doc_ok(s) for s in stories) / len(stories) if stories else 1.0,
        "thin_docs": [s["key"] for s in stories if not doc_ok(s)],
        "spill_reasons": _spill_reasons(not_done_planned),
    }


def _spill_reasons(items):
    """Cheap first-pass causes for spillover, so the review starts from data, not memory."""
    reasons = {"Not started (To Do)": 0, "Stuck in review": 0, "In progress at close": 0,
               "Thin requirements": 0, "Carried over again": 0}
    for i in items:
        if i["status"] == "To Do":
            reasons["Not started (To Do)"] += 1
        elif i["status"] == "In Review":
            reasons["Stuck in review"] += 1
        else:
            reasons["In progress at close"] += 1
        if i["type"] == "Story" and not doc_ok(i):
            reasons["Thin requirements"] += 1
        if i.get("carried_from_previous"):
            reasons["Carried over again"] += 1
    return {k: v for k, v in reasons.items() if v}


def rag(metric, value):
    green, red = THRESHOLDS[metric]
    if metric == "doc_quality":
        return "green" if value >= green else "red" if value < red else "amber"
    return "green" if value < green else "red" if value >= red else "amber"


def pod_health(pod, today=None):
    closed = [s for s in pod["sprints"] if s["state"] == "closed"]
    active = [s for s in pod["sprints"] if s["state"] == "active"]
    last = sprint_metrics(closed[-1], today)
    prev = sprint_metrics(closed[-2], today) if len(closed) > 1 else None
    statuses = {m: rag(m, last[m]) for m in THRESHOLDS}
    overall = "red" if "red" in statuses.values() else "amber" if "amber" in statuses.values() else "green"
    return {
        "pod": pod["name"],
        "last": last,
        "prev": prev,
        "active": sprint_metrics(active[-1], today) if active else None,
        "status": statuses,
        "overall": overall,
    }


def cycle_time(releases):
    days = [(_d(r["released"]) - _d(r["idea_logged"])).days for r in releases]
    return {"median_days": median(days) if days else None, "count": len(days),
            "slowest": max(releases, key=lambda r: (_d(r["released"]) - _d(r["idea_logged"])).days) if releases else None}


def team_summary(data, today=None):
    pods = [pod_health(p, today) for p in data["pods"]]
    planned = sum(p["last"]["planned"] for p in pods)
    spilled = sum(len(p["last"]["spillover"]) for p in pods)
    return {
        "pods": pods,
        "team_spillover_rate": spilled / planned if planned else 0.0,
        "cycle_time": cycle_time(data.get("releases", [])),
        "source": data.get("source", "sample"),
    }
