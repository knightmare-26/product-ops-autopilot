"""Generate the fictional sample data used for demos.

Everything here is made up: pods, people, tickets and meetings are invented so the
tool can be demoed without access to any real company's Jira, Slack or notes.
Run:  python tools/generate_sample_data.py
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(7)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data" / "sprints.json"

PODS = {
    "Search & Discovery": {"prefix": "SRCH", "people": ["Aisha", "Rohan", "Meera"], "spill": 0.10, "adhoc": 0.08, "docs": 0.97, "close_delay": 0},
    "Booking Flow": {"prefix": "BOOK", "people": ["Kabir", "Sana", "Dev"], "spill": 0.35, "adhoc": 0.30, "docs": 0.55, "close_delay": 3},
    "Payments": {"prefix": "PAY", "people": ["Nikhil", "Tara", "Imran"], "spill": 0.22, "adhoc": 0.15, "docs": 0.70, "close_delay": 1},
}

SUMMARIES = [
    "Filter listings by distance to university", "Show room availability calendar", "Add instant-book badge",
    "Fix currency rounding on checkout", "Send booking confirmation via WhatsApp", "Improve map pin clustering",
    "Allow guarantor upload during booking", "Refund status tracking page", "Cache popular city search results",
    "Add tour scheduling for properties", "Retry failed payment webhooks", "Show price breakdown before payment",
    "Saved searches with alerts", "Landlord document verification flow", "Split payment between roommates",
    "Reduce search API p95 latency", "Lead form validation for phone numbers", "Add sort by move-in date",
]

GOOD_DESC = ("As a student comparing properties I want to {s} so that I can decide faster. "
             "Context: raised by support in the last two weeks with 40+ tickets. "
             "Acceptance criteria: 1) works on web and app 2) handles empty states 3) tracked with an analytics event. "
             "Out of scope: landlord dashboard changes.")
THIN_DESC = "{s}. See slack thread."


def make_sprint(pod, cfg, n, start, closed_offset, state):
    end = start + timedelta(days=11)
    issues = []
    total = 14
    for i in range(total):
        s = random.choice(SUMMARIES)
        adhoc = random.random() < cfg["adhoc"]
        created = start + timedelta(days=random.randint(1, 8)) if adhoc else start - timedelta(days=random.randint(3, 30))
        good_doc = random.random() < cfg["docs"]
        is_story = random.random() < 0.7
        done = random.random() > cfg["spill"] if state == "closed" else random.random() > 0.55
        carried = random.random() < cfg["spill"] * 0.6 and not adhoc
        issues.append({
            "key": f"{cfg['prefix']}-{400 + n * 20 + i}",
            "type": "Story" if is_story else random.choice(["Bug", "Task"]),
            "summary": s,
            "status": "Done" if done else random.choice(["In Progress", "In Review", "To Do"]),
            "points": random.choice([1, 2, 3, 5, 8]),
            "assignee": random.choice(cfg["people"]),
            "created": created.isoformat(),
            "added_after_start": adhoc,
            "carried_from_previous": carried,
            "labels": ["unplanned"] if adhoc else [],
            "description": (GOOD_DESC if good_doc else THIN_DESC).format(s=s.lower()),
        })
    closed_at = (end + timedelta(days=closed_offset)).isoformat() if state == "closed" else None
    return {"id": n, "name": f"{cfg['prefix']} Sprint {n}", "state": state, "start": start.isoformat(),
            "end": end.isoformat(), "closed_at": closed_at, "issues": issues}


def main():
    sprint_start = date(2026, 11, 3)   # last closed sprint: 3–14 Nov 2026
    data = {"source": "sample", "pods": [], "releases": []}
    for pod, cfg in PODS.items():
        sprints = [
            make_sprint(pod, cfg, 40, sprint_start - timedelta(days=14), max(0, cfg["close_delay"] - 1), "closed"),
            make_sprint(pod, cfg, 41, sprint_start, cfg["close_delay"], "closed"),
            make_sprint(pod, cfg, 42, sprint_start + timedelta(days=14), 0, "active"),
        ]
        data["pods"].append({"name": pod, "sprints": sprints})
    for i, s in enumerate(random.sample(SUMMARIES, 9)):
        idea = date(2026, 7, 1) + timedelta(days=random.randint(0, 80))
        data["releases"].append({
            "feature": s, "pod": random.choice(list(PODS)),
            "idea_logged": idea.isoformat(),
            "released": (idea + timedelta(days=random.randint(21, 75))).isoformat(),
        })
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
