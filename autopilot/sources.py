"""Load sprint data from the bundled sample file or from Jira Cloud.

Both sources return the same shape:
{"source": str, "pods": [{"name", "sprints": [{"id","name","state","start","end","closed_at","issues": [...]}]}],
 "releases": [{"feature","pod","idea_logged","released"}]}
"""
import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data" / "sprints.json"


def load_sample(path=SAMPLE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Jira Cloud
class JiraClient:
    """Minimal Jira Cloud client using the Agile REST API (no third-party packages)."""

    def __init__(self, base_url, email, token):
        self.base = base_url.rstrip("/")
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    def get(self, path, **params):
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def paged(self, path, key, **params):
        start = 0
        while True:
            page = self.get(path, startAt=start, maxResults=50, **params)
            items = page.get(key, [])
            yield from items
            start += len(items)
            done = page["isLast"] if "isLast" in page else start >= page.get("total", 0)
            if done or not items:
                break


def _adf_to_text(node):
    """Jira Cloud may return descriptions as Atlassian Document Format; flatten to text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return node.get("text", "") + " ".join(_adf_to_text(c) for c in node.get("content", []))
    return ""


def load_jira():
    """Read config from env vars.

    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
    JIRA_BOARDS            e.g. "Search & Discovery:12,Booking Flow:15"  (pod name : board id)
    JIRA_SPRINT_FIELD      sprint custom field id (default customfield_10020)
    JIRA_POINTS_FIELD      story points field id (default customfield_10016)
    """
    client = JiraClient(os.environ["JIRA_BASE_URL"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
    sprint_field = os.environ.get("JIRA_SPRINT_FIELD", "customfield_10020")
    points_field = os.environ.get("JIRA_POINTS_FIELD", "customfield_10016")
    fields = ",".join(["summary", "status", "issuetype", "created", "labels", "description", "assignee",
                       sprint_field, points_field])
    data = {"source": "jira", "pods": [], "releases": []}
    for pair in os.environ["JIRA_BOARDS"].split(","):
        pod, board_id = pair.rsplit(":", 1)
        sprints = list(client.paged(f"/rest/agile/1.0/board/{board_id.strip()}/sprint", "values",
                                    state="active,closed"))
        sprints = sorted(sprints, key=lambda s: s.get("startDate", ""))[-3:]
        out = []
        for sp in sprints:
            start = (sp.get("startDate") or "")[:10]
            issues = []
            for it in client.paged(f"/rest/agile/1.0/sprint/{sp['id']}/issue", "issues", fields=fields):
                f = it["fields"]
                sprint_hist = f.get(sprint_field) or []
                labels = f.get("labels") or []
                created = (f.get("created") or "")[:10]
                issues.append({
                    "key": it["key"],
                    "type": f["issuetype"]["name"],
                    "summary": f.get("summary", ""),
                    "status": "Done" if f["status"]["statusCategory"]["key"] == "done" else f["status"]["name"],
                    "points": f.get(points_field) or 0,
                    "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
                    "created": created,
                    # Approximation: created after sprint start, or labelled unplanned.
                    "added_after_start": bool(start and created > start) or "unplanned" in labels,
                    "carried_from_previous": len(sprint_hist) > 1,
                    "labels": labels,
                    "description": _adf_to_text(f.get("description")),
                })
            out.append({"id": sp["id"], "name": sp["name"], "state": sp["state"], "start": start,
                        "end": (sp.get("endDate") or "")[:10],
                        "closed_at": (sp.get("completeDate") or "")[:10] or None, "issues": issues})
        data["pods"].append({"name": pod.strip(), "sprints": out})
    return data


def load(source="sample"):
    return load_jira() if source == "jira" else load_sample()
