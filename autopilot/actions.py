"""Turn meeting notes into tracked action items and decisions, then chase them to closure.

Extraction uses Claude when ANTHROPIC_API_KEY is set (handles messy, free-form notes).
Without a key it falls back to a rule-based parser that reads lines like:
    Decision: <text>
    Action: <Owner> - <task> - due 2026-11-20
"""
import hashlib
import json
import os
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "action_items.json"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

ACTION_RE = re.compile(r"^\s*(?:action|ai|todo)\s*:\s*(?P<owner>[^-–—]+?)\s*[-–—]\s*(?P<task>.+?)"
                       r"(?:\s*[-–—]\s*due\s*(?P<due>\d{4}-\d{2}-\d{2}))?\s*$", re.I)
DECISION_RE = re.compile(r"^\s*decision\s*:\s*(?P<text>.+)$", re.I)

PROMPT = """You extract decisions and action items from product meeting notes.
Return ONLY JSON: {{"decisions": [str], "actions": [{{"owner": str, "task": str, "due": "YYYY-MM-DD" or null}}]}}
Rules: one owner per action (a person's first name); keep tasks short and specific; only include a due date
if the notes state or clearly imply one (meeting date is {meeting_date}); never invent owners.

Notes:
{notes}"""


def parse_rules(text):
    decisions, actions = [], []
    for line in text.splitlines():
        if m := DECISION_RE.match(line):
            decisions.append(m["text"].strip())
        elif m := ACTION_RE.match(line):
            actions.append({"owner": m["owner"].strip(), "task": m["task"].strip(), "due": m["due"]})
    return {"decisions": decisions, "actions": actions}


def parse_claude(text, meeting_date):
    body = json.dumps({
        "model": MODEL, "max_tokens": 1500,
        "messages": [{"role": "user", "content": PROMPT.format(notes=text, meeting_date=meeting_date)}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    raw = "".join(b.get("text", "") for b in out["content"])
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    return json.loads(raw)


def extract(text, meeting_date):
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return parse_claude(text, meeting_date), "claude"
        except Exception as e:  # never let the weekly run die on one bad response
            print(f"  Claude extraction failed ({e}); using rule-based parser")
    return parse_rules(text), "rules"


def _id(meeting, task):
    return hashlib.sha1(f"{meeting}|{task.lower()}".encode()).hexdigest()[:8]


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"items": {}, "decisions": []}


def save_state(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ingest(meetings_dir, state=None):
    """Read every notes file (named YYYY-MM-DD_<meeting>.txt) and merge into the tracker."""
    state = state or load_state()
    used = set()
    for f in sorted(Path(meetings_dir).glob("*.txt")):
        meeting_date, _, name = f.stem.partition("_")
        meeting = name.replace("-", " ").title()
        result, how = extract(f.read_text(encoding="utf-8"), meeting_date)
        used.add(how)
        for d in result.get("decisions", []):
            if not any(x["text"] == d for x in state["decisions"]):
                state["decisions"].append({"text": d, "meeting": meeting, "date": meeting_date})
        for a in result.get("actions", []):
            key = _id(meeting, a["task"])
            if key not in state["items"]:            # keep status of items we already track
                state["items"][key] = {"id": key, "owner": a["owner"], "task": a["task"], "due": a.get("due"),
                                       "meeting": meeting, "date": meeting_date, "status": "open"}
    return state, used


def close(state, item_id):
    if item_id in state["items"]:
        state["items"][item_id]["status"] = "done"
        return True
    return False


def chase_list(state, today=None):
    """Group open items by owner and flag overdue / due soon / no due date."""
    today = today or date.today()
    soon = today + timedelta(days=2)
    by_owner = {}
    for it in state["items"].values():
        if it["status"] != "open":
            continue
        due = date.fromisoformat(it["due"]) if it.get("due") else None
        flag = ("overdue" if due and due < today else "due soon" if due and due <= soon
                else "no due date" if not due else "on track")
        by_owner.setdefault(it["owner"], []).append({**it, "flag": flag,
                                                     "days_overdue": (today - due).days if due and due < today else 0})
    order = {"overdue": 0, "due soon": 1, "no due date": 2, "on track": 3}
    for items in by_owner.values():
        items.sort(key=lambda x: (order[x["flag"]], x.get("due") or "9999"))
    return dict(sorted(by_owner.items()))


def closure_rate(state):
    items = list(state["items"].values())
    return (sum(i["status"] == "done" for i in items) / len(items)) if items else 0.0
