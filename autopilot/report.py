"""Render the weekly report as Markdown, HTML and a short Slack message."""
import html
from datetime import date

DOT = {"green": "🟢", "amber": "🟠", "red": "🔴"}
LABELS = {"spillover_rate": "Spillover", "adhoc_share": "Ad-hoc work",
          "closure_delay_days": "Closure delay", "doc_quality": "Docs with AC"}


def pct(x):
    return f"{x * 100:.0f}%"


def fmt(metric, v):
    return f"{v}d" if metric == "closure_delay_days" else pct(v)


def trend(metric, now, before):
    if before is None:
        return ""
    diff = now - before
    if abs(diff) < 1e-9:
        return "→"
    return "▲" if diff > 0 else "▼"


def suggestions(summary, chase):
    """Plain-language next steps derived from the numbers."""
    out = []
    for p in summary["pods"]:
        last, st = p["last"], p["status"]
        if st["spillover_rate"] != "green":
            top = max(last["spill_reasons"], key=last["spill_reasons"].get) if last["spill_reasons"] else None
            out.append(f"{p['pod']}: {pct(last['spillover_rate'])} of planned work spilled"
                       + (f", mostly '{top}'" if top else "") + ". Review scope at next planning.")
        if st["adhoc_share"] == "red":
            out.append(f"{p['pod']}: {pct(last['adhoc_share'])} of the sprint was unplanned. "
                       "Agree an intake rule with the PM (e.g. a fixed buffer).")
        if st["doc_quality"] != "green":
            out.append(f"{p['pod']}: {len(last['thin_docs'])} stories lack a full description or acceptance "
                       f"criteria ({', '.join(last['thin_docs'][:4])}). Fix before they enter a sprint.")
        if st["closure_delay_days"] == "red":
            out.append(f"{p['pod']}: sprint closed {last['closure_delay_days']} days late.")
    overdue = [i for items in chase.values() for i in items if i["flag"] == "overdue"]
    if overdue:
        out.append(f"{len(overdue)} meeting action items are overdue. Reminders sent to owners.")
    return out


def markdown(summary, chase, decisions, closure, today=None):
    today = today or date.today()
    ct = summary["cycle_time"]
    lines = [f"# Product Team Weekly Health · {today:%d %b %Y}", "",
             f"Data source: **{summary['source']}** · Team spillover **{pct(summary['team_spillover_rate'])}** · "
             f"Median idea→release **{ct['median_days']} days** ({ct['count']} releases) · "
             f"Action-item closure **{pct(closure)}**", "", "## Sprint health by pod", "",
             "| Pod | Sprint | Overall | " + " | ".join(LABELS.values()) + " |",
             "|---|---|---|" + "---|" * len(LABELS)]
    for p in summary["pods"]:
        cells = []
        for m in LABELS:
            prev = p["prev"][m] if p["prev"] else None
            cells.append(f"{DOT[p['status'][m]]} {fmt(m, p['last'][m])} {trend(m, p['last'][m], prev)}")
        lines.append(f"| {p['pod']} | {p['last']['sprint']} | {DOT[p['overall']]} | " + " | ".join(cells) + " |")
    lines += ["", "## What to look at", ""] + [f"- {s}" for s in suggestions(summary, chase)]
    lines += ["", "## Open action items", ""]
    for owner, items in chase.items():
        lines.append(f"**{owner}**")
        for i in items:
            lines.append(f"- [{i['flag']}] {i['task']} (from {i['meeting']}, {i['date']}"
                         + (f", due {i['due']}" if i.get("due") else "") + f") `{i['id']}`")
    lines += ["", "## Decisions logged this week", ""] + [f"- {d['text']} ({d['meeting']}, {d['date']})"
                                                          for d in decisions]
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e6e5e0;--green:#2f8f5b;--amber:#c9821b;--red:#c2413b;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;--muted:#a3a29b;--line:#33332f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Inter,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 12px}
.sub{color:var(--muted);margin:0 0 20px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.kpi b{display:block;font-size:26px}
.kpi span{color:var(--muted);font-size:13px}.wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.pill{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}.green{background:var(--green)}.amber{background:var(--amber)}.red{background:var(--red)}
.t{color:var(--muted);font-size:12px;margin-left:4px}ul{padding-left:18px}li{margin:4px 0}.owner{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:10px}
.tag{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);margin-right:6px;color:var(--muted)}.tag.overdue{color:var(--red);border-color:var(--red)}
.tag.due{color:var(--amber);border-color:var(--amber)}code{font-size:12px;color:var(--muted)}footer{margin-top:40px;color:var(--muted);font-size:13px}
"""


def html_report(summary, chase, decisions, closure, today=None):
    today = today or date.today()
    e = html.escape
    ct = summary["cycle_time"]
    overdue = sum(i["flag"] == "overdue" for items in chase.values() for i in items)
    rows = []
    for p in summary["pods"]:
        cells = "".join(
            f"<td><span class='pill {p['status'][m]}'></span>{fmt(m, p['last'][m])}"
            f"<span class='t'>{trend(m, p['last'][m], p['prev'][m] if p['prev'] else None)}</span></td>"
            for m in LABELS)
        rows.append(f"<tr><td><b>{e(p['pod'])}</b></td><td>{e(p['last']['sprint'])}</td>"
                    f"<td><span class='pill {p['overall']}'></span>{p['overall'].title()}</td>{cells}</tr>")
    owners = []
    for owner, items in chase.items():
        lis = "".join(
            f"<li><span class='tag {'overdue' if i['flag'] == 'overdue' else 'due' if i['flag'] == 'due soon' else ''}'>"
            f"{e(i['flag'])}</span>{e(i['task'])} <code>{i['id']}</code><br><small>{e(i['meeting'])} · {i['date']}"
            + (f" · due {i['due']}" if i.get('due') else "") + "</small></li>" for i in items)
        owners.append(f"<div class='owner'><b>{e(owner)}</b><ul>{lis}</ul></div>")
    sug = "".join(f"<li>{e(s)}</li>" for s in suggestions(summary, chase))
    dec = "".join(f"<li>{e(d['text'])} <small>({e(d['meeting'])}, {d['date']})</small></li>" for d in decisions)
    head = "".join(f"<th>{v}</th>" for v in LABELS.values())
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Team Weekly Health</title><style>{CSS}</style></head><body><main>
<h1>Product Team Weekly Health</h1><p class="sub">Week of {today:%d %b %Y} · generated automatically · data source: {e(summary['source'])}</p>
<div class="kpis"><div class="kpi"><b>{pct(summary['team_spillover_rate'])}</b><span>Team sprint spillover</span></div>
<div class="kpi"><b>{ct['median_days']} days</b><span>Median idea → release ({ct['count']} releases)</span></div>
<div class="kpi"><b>{pct(closure)}</b><span>Meeting action items closed</span></div>
<div class="kpi"><b>{overdue}</b><span>Action items overdue</span></div></div>
<h2>Sprint health by pod</h2><div class="wrap"><table><thead><tr><th>Pod</th><th>Sprint</th><th>Overall</th>{head}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div><p class="sub" style="margin-top:8px">▲▼ change vs previous sprint · Docs with AC = stories with a full description and acceptance criteria</p>
<h2>What to look at</h2><ul>{sug}</ul><h2>Open action items by owner</h2>{''.join(owners)}
<h2>Decisions logged</h2><ul>{dec}</ul><footer>Product Ops Autopilot · built by Elijah DSouza</footer></main></body></html>"""


def slack_text(summary, chase, closure, report_url=None):
    worst = [p for p in summary["pods"] if p["overall"] != "green"]
    overdue = [i for items in chase.values() for i in items if i["flag"] == "overdue"]
    lines = [f"*Product team weekly health* · spillover {pct(summary['team_spillover_rate'])} · "
             f"action items closed {pct(closure)}"]
    for p in summary["pods"]:
        lines.append(f"{DOT[p['overall']]} *{p['pod']}*: spillover {pct(p['last']['spillover_rate'])}, "
                     f"ad-hoc {pct(p['last']['adhoc_share'])}, docs {pct(p['last']['doc_quality'])}")
    if overdue:
        lines.append(f"\n*Overdue actions ({len(overdue)})*")
        lines += [f"• {i['owner']}: {i['task']} ({i['days_overdue']}d overdue)" for i in overdue[:8]]
    if worst:
        lines.append(f"\nNeeds attention: {', '.join(p['pod'] for p in worst)}")
    if report_url:
        lines.append(f"<{report_url}|Full report>")
    return "\n".join(lines)


def reminder_text(owner, items):
    lines = [f"Hi {owner}, quick nudge on your open action items:"]
    for i in items:
        if i["flag"] in ("overdue", "due soon", "no due date"):
            lines.append(f"• {i['task']} ({i['flag']}, from {i['meeting']} on {i['date']}) [id {i['id']}]")
    lines.append("When it's done, close it with: python -m autopilot close <id>. Thanks!")
    return "\n".join(lines) if len(lines) > 2 else None
