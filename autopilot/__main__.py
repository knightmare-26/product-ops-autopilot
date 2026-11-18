"""Command line entry point.

    python -m autopilot weekly                 # full weekly run on sample data
    python -m autopilot weekly --source jira   # same, using Jira Cloud (see README for env vars)
    python -m autopilot actions                # only ingest meeting notes and print the chase list
    python -m autopilot close <id>             # mark an action item as done
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import actions, metrics, notify, report, sources

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def weekly(args):
    today = date.fromisoformat(args.today) if args.today else date.today()
    print(f"Loading sprint data from {args.source}…")
    data = sources.load(args.source)
    summary = metrics.team_summary(data, today)

    print(f"Reading meeting notes from {args.meetings}…")
    state, used = actions.ingest(args.meetings)
    actions.save_state(state)
    chase = actions.chase_list(state, today)
    closure = actions.closure_rate(state)
    print(f"  extraction method: {', '.join(sorted(used)) or 'none'}")

    OUT.mkdir(exist_ok=True)
    md = report.markdown(summary, chase, state["decisions"], closure, today)
    (OUT / "weekly_report.md").write_text(md, encoding="utf-8")
    (OUT / "weekly_report.html").write_text(report.html_report(summary, chase, state["decisions"], closure, today), encoding="utf-8")
    (OUT / "metrics.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUT / 'weekly_report.html'} and weekly_report.md")

    notify.send(report.slack_text(summary, chase, closure, args.report_url), dry_run=args.dry_run)
    for owner, items in chase.items():
        msg = report.reminder_text(owner, items)
        if msg:
            notify.send(msg, dry_run=args.dry_run)


def show_actions(args):
    today = date.fromisoformat(args.today) if args.today else date.today()
    state, _ = actions.ingest(args.meetings)
    actions.save_state(state)
    for owner, items in actions.chase_list(state, today).items():
        print(f"\n{owner}")
        for i in items:
            print(f"  [{i['flag']:<11}] {i['task']}  ({i['id']})")


def close(args):
    state = actions.load_state()
    ok = actions.close(state, args.id)
    actions.save_state(state)
    print("Closed." if ok else f"No action item with id {args.id}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles/pipes default to a non-UTF-8 code page
    p = argparse.ArgumentParser(prog="autopilot", description="Product Ops Autopilot")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("weekly", help="generate the weekly report and send reminders")
    w.add_argument("--source", choices=["sample", "jira"], default="sample")
    w.add_argument("--meetings", default=str(ROOT / "sample_data" / "meetings"))
    w.add_argument("--today", help="override today's date (YYYY-MM-DD), useful for demos")
    w.add_argument("--report-url", help="link to the published report, added to the Slack message")
    w.add_argument("--dry-run", action="store_true", help="print Slack messages instead of sending")
    w.set_defaults(func=weekly)
    a = sub.add_parser("actions", help="ingest meeting notes and print the chase list")
    a.add_argument("--meetings", default=str(ROOT / "sample_data" / "meetings"))
    a.add_argument("--today")
    a.set_defaults(func=show_actions)
    c = sub.add_parser("close", help="mark an action item done")
    c.add_argument("id")
    c.set_defaults(func=close)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
