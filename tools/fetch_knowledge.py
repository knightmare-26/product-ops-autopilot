"""Snapshot a real product's docs and Jira tickets into knowledge/ for the Ask Product bot.

Source: Apache OFBiz, an open-source e-commerce / ERP product (orders, returns, payments,
catalogue). Its user docs live in GitHub and its Jira is public, so the bot can be shown on
real data without any private credentials.

    python tools/fetch_knowledge.py                 # docs at the latest trunk commit + last 90 days of Jira
    python tools/fetch_knowledge.py --days 30       # smaller Jira window

Only the Python standard library is used.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "knowledge"
REPO = "apache/ofbiz-framework"
JIRA = "https://issues.apache.org/jira"
PROJECT = "OFBIZ"
UA = {"User-Agent": "product-ops-autopilot/1.0 (knowledge snapshot)"}


def get(url, binary=False):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
                return data if binary else json.loads(data)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def fetch_docs():
    sha = get(f"https://api.github.com/repos/{REPO}/commits/trunk")["sha"]
    tree = get(f"https://api.github.com/repos/{REPO}/git/trees/{sha}?recursive=1")["tree"]
    paths = [t["path"] for t in tree if t["path"].endswith(".adoc")] + ["LICENSE", "NOTICE"]
    out = KNOW / "ofbiz_docs"

    def one(path):
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(get(f"https://raw.githubusercontent.com/{REPO}/{sha}/{path}", binary=True))

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, paths))
    print(f"docs: {len(paths)} files from {REPO}@{sha[:10]}")
    return sha


def fetch_jira(days):
    fields = "summary,status,assignee,priority,issuetype,created,updated,resolutiondate,fixVersions,components,description,comment"
    jql = f"project = {PROJECT} AND updated >= -{days}d ORDER BY updated DESC"
    issues, start = [], 0
    while True:
        q = urllib.parse.urlencode({"jql": jql, "startAt": start, "maxResults": 100, "fields": fields})
        page = get(f"{JIRA}/rest/api/2/search?{q}")
        for it in page["issues"]:
            f = it["fields"]
            comments = (f.get("comment") or {}).get("comments", [])
            last = comments[-1] if comments else None
            issues.append({
                "key": it["key"],
                "url": f"{JIRA}/browse/{it['key']}",
                "type": f["issuetype"]["name"],
                "summary": f["summary"],
                "status": f["status"]["name"],
                "status_category": f["status"]["statusCategory"]["name"],
                "priority": (f.get("priority") or {}).get("name"),
                "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
                "created": f["created"][:10],
                "updated": f["updated"][:10],
                "resolved": (f.get("resolutiondate") or "")[:10] or None,
                "fix_versions": [v["name"] for v in f.get("fixVersions") or []],
                "components": [c["name"] for c in f.get("components") or []],
                "description": (f.get("description") or "")[:1500],
                "comment_count": len(comments),
                "last_comment": {"author": last["author"]["displayName"], "date": last["created"][:10],
                                 "text": last["body"][:600]} if last else None,
            })
        start += len(page["issues"])
        if not page["issues"] or start >= page["total"]:
            break
    print(f"jira: {len(issues)} {PROJECT} issues updated in the last {days} days")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    KNOW.mkdir(exist_ok=True)
    sha = fetch_docs()
    issues = fetch_jira(args.days)
    (KNOW / "jira_ofbiz.json").write_text(json.dumps(issues, indent=1, ensure_ascii=False), encoding="utf-8")
    (KNOW / "SOURCE.json").write_text(json.dumps({
        "product": "Apache OFBiz", "docs_repo": REPO, "docs_commit": sha, "jira": f"{JIRA}/projects/{PROJECT}",
        "jira_window_days": args.days, "snapshot_date": date.today().isoformat(),
        "license": "Apache License 2.0 (see ofbiz_docs/LICENSE and ofbiz_docs/NOTICE)",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
