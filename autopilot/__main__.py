"""Command line entry point.

    python -m autopilot weekly                 # full weekly run on sample data
    python -m autopilot weekly --source jira   # same, using Jira Cloud (see README for env vars)
    python -m autopilot actions                # only ingest meeting notes and print the chase list
    python -m autopilot close <id>             # mark an action item as done
    python -m autopilot ask "How do returns work?"   # Ask Product bot (answers with sources)
    python -m autopilot ask --file questions.txt     # ask one question per line
    python -m autopilot gaps                   # questions the bot couldn't answer this week
    python -m autopilot serve                  # Slack slash-command endpoint for the bot
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import actions, ask, metrics, notify, report, sources

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
    bot = ask.stats(today)
    print(f"Ask Product bot: {bot['asked']} questions in the last 7 days, {len(bot['gaps'])} knowledge gaps")

    OUT.mkdir(exist_ok=True)
    md = report.markdown(summary, chase, state["decisions"], closure, today, bot=bot)
    (OUT / "weekly_report.md").write_text(md, encoding="utf-8")
    (OUT / "weekly_report.html").write_text(
        report.html_report(summary, chase, state["decisions"], closure, today, bot=bot), encoding="utf-8")
    (OUT / "metrics.json").write_text(json.dumps({**summary, "ask_bot": bot}, indent=2, default=str),
                                      encoding="utf-8")
    print(f"Wrote {OUT / 'weekly_report.html'} and weekly_report.md")

    notify.send(report.slack_text(summary, chase, closure, args.report_url, bot=bot), dry_run=args.dry_run)
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


def ask_cmd(args):
    today = date.fromisoformat(args.today) if args.today else date.today()
    if args.file:
        questions = [q.strip() for q in Path(args.file).read_text(encoding="utf-8").splitlines()
                     if q.strip() and not q.startswith("#")]
    else:
        questions = [" ".join(args.question)]
    if not questions or not questions[0]:
        sys.exit('Ask a question, e.g.  python -m autopilot ask "How do sales returns work?"')
    for q in questions:
        result = ask.ask(q, today=today, log=not args.no_log, asker=args.asker)
        if args.json:
            print(json.dumps({**result, "cited": [{k: h[k] for k in ("id", "title", "url", "kind")}
                                                  for h in result["cited"]]}, indent=2, ensure_ascii=False))
        else:
            print(f"\nQ: {q}\n{ask.format_answer(result)}")


def gaps(args):
    today = date.fromisoformat(args.today) if args.today else date.today()
    print(ask.gap_report(ask.stats(today, days=args.days)))


def serve(args):
    from . import slack_bot
    slack_bot.run(args.port)


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
    q = sub.add_parser("ask", help="ask the product bot a question")
    q.add_argument("question", nargs="*")
    q.add_argument("--file", help="text file with one question per line")
    q.add_argument("--json", action="store_true", help="print the full result as JSON")
    q.add_argument("--no-log", action="store_true", help="don't record the question in state/questions.jsonl")
    q.add_argument("--asker", help="who asked (recorded in the log for adoption metrics)")
    q.add_argument("--today")
    q.set_defaults(func=ask_cmd)
    g = sub.add_parser("gaps", help="show questions the bot couldn't answer")
    g.add_argument("--days", type=int, default=7)
    g.add_argument("--today")
    g.set_defaults(func=gaps)
    s = sub.add_parser("serve", help="run the Slack slash-command endpoint")
    s.add_argument("--port", type=int, default=3000)
    s.set_defaults(func=serve)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
