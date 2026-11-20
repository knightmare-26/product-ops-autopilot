# Product Ops Autopilot

A small automation that does three recurring Product Ops jobs, so nobody has to compile them by hand:

1. **Sprint health report.** It pulls sprint data from Jira, scores each pod on spillover, unplanned (ad-hoc) work, late sprint closure and requirement quality, compares it with the previous sprint, and writes a plain-language "what to look at" list.
2. **Meeting action-item tracker.** It reads meeting notes, extracts decisions and action items with owners and due dates (using Claude), keeps a running tracker, and sends each owner a Slack nudge for anything overdue, due soon or missing a due date.
3. **Ask Product bot.** It answers "How does X work?" and "What is the status of Y?" from product docs, Jira and the meeting tracker, always with links to its sources. When it can't find evidence it says so instead of guessing, logs the question as a knowledge gap, and the weekly report lists the gaps to fill.

It runs on a schedule (every Monday 09:30 IST via GitHub Actions), posts a summary to Slack, and saves a full HTML report.

![Weekly report](output/report_screenshot.png)

> **Data.** The sprint and meeting data is **fictional sample data** (pods, people and meetings are invented), so the report runs without access to any real Jira, Slack or notes. The Ask Product bot runs on **real public data**: the user docs and Jira tickets of [Apache OFBiz](https://ofbiz.apache.org/), an open-source e-commerce and ERP product (see [Where the bot's data comes from](#where-the-bots-data-comes-from)).

---

## Why I built it

Status updates, sprint health checks, chasing action items and answering the same questions again are the work that quietly eats a PM or PMO's week. In my PMO role I run sprint cadences and Agile ceremonies across US and India teams, and I wanted the weekly "how are the pods doing and what's slipping" picture to build itself, so the meeting time goes on decisions instead of collecting numbers.

## What it measures

| Metric | Definition | Green / Red |
|---|---|---|
| Spillover rate | Planned issues not Done when the sprint closed ÷ planned issues | < 15% / ≥ 30% |
| Ad-hoc work | Issues added after sprint start ÷ all sprint issues | < 15% / ≥ 25% |
| Closure delay | Days between planned sprint end and actual close | < 1 day / ≥ 3 days |
| Docs with AC | Stories with a 40+ word description that includes acceptance criteria | ≥ 80% / < 60% |
| Idea → release | Median days from idea logged to release | trend only |
| Action-item closure | Tracked action items marked done ÷ all tracked | trend only |
| Bot answer rate | Questions answered with a cited source ÷ questions asked (last 7 days) | trend only |
| Recurring questions resolved | Questions asked more than once that the bot answered ÷ all repeated questions | trend only |

For each pod it also gives a first-pass reason for spillover (not started, stuck in review, in progress at close, thin requirements, carried over again), so the sprint review starts from data.

## Quick start (no accounts needed)

```bash
python -m autopilot weekly --today 2026-11-20 --dry-run
python -m autopilot ask "How does a sales return work?"
```

Output of `weekly`:
- `output/weekly_report.html`: the full report (open it in a browser)
- `output/weekly_report.md`: the same report in Markdown (paste it into Notion or Confluence)
- `output/metrics.json`: the raw numbers
- the Slack summary and per-owner reminders, printed to the terminal (`--dry-run`)

The bot section of the report counts questions asked in the 7 days up to the report date.

Other commands:

```bash
python -m autopilot ask "What's the status of OFBIZ-13874?"   # ask the bot (add --json for the full result)
python -m autopilot ask --file tools/demo_questions.txt        # ask one question per line
python -m autopilot gaps                                       # questions the bot couldn't answer this week
python -m autopilot serve --port 3000                          # Slack /ask endpoint (see below)
python -m autopilot actions --today 2026-11-20                 # just the action-item chase list
python -m autopilot close <id>                                 # mark an action item done
python tools/fetch_knowledge.py                                # refresh the bot's docs and Jira snapshot
python tools/eval_ask.py                                       # score the bot on labelled questions
python -m pytest tests                                         # run the tests
```

Python 3.10+ and the standard library only. Two optional packages: `pytest` for the tests, and `anthropic` if you want Claude to write the bot's answers.

## The Ask Product bot

### What an answer looks like

```
Q: What's the status of the Hugo website migration?
OFBIZ-13874 "Migrate Apache OFBiz website to Hugo" is Open (assignee Michael Brohl; last updated 2026-11-18).
Latest comment (Michael Brohl, 2026-11-18): "From there I would work out the next changes necessary to deploy…"

Sources:
[1] OFBIZ-13874: Migrate Apache OFBiz website to Hugo (ticket) https://issues.apache.org/jira/browse/OFBIZ-13874

Q: What is our refund SLA for students in London?
I couldn't find this in the docs, tickets or meeting notes I have. It's logged as a knowledge gap.
```

### How it answers

1. **Search.** Every source is split into short passages: each doc section, each Jira ticket (summary, description, latest comment), each action item and each decision. A keyword ranking (BM25) finds the best passages. Status questions favour tickets and action items; how-to questions favour docs. A ticket key in the question (e.g. `OFBIZ-13874`) always goes first.
2. **Check for evidence.** If the best passage contains fewer than half of the question's keywords, the bot answers "I don't know" and logs a gap. It never answers without a source.
3. **Answer.**
   - **With Claude** (set `ANTHROPIC_API_KEY` and `pip install anthropic`): Claude reads the top 8 passages and writes a short answer that cites them by number. It's told to use only the sources and to say what's missing if they don't cover the question. The answer comes back as JSON with a fixed schema, so the code can check every citation points to a real passage.
   - **Without a key**: the bot quotes the source directly. For a ticket that's the status, assignee, last update, fix version and latest comment, and it flags open tickets with no update for 14+ days. For a doc it's the section's opening sentence plus the sentences closest to the question.
4. **Log.** Every question goes into `state/questions.jsonl`: the question, its type, whether it was answered, the sources used and who asked.

### Closing knowledge gaps

The weekly report and `python -m autopilot gaps` list the unanswered questions, how often each was asked, and the closest thing the bot did find. To close a gap, add a short Markdown note to `knowledge/team_notes/`. The bot indexes it straight away and cites it from then on. `tests/test_ask.py::test_adding_a_team_note_closes_the_gap` checks this loop.

### How well it works

`tools/eval_ask.py` scores the bot on 24 labelled questions in `tests/ask_eval.json`: 20 that the docs or tickets can answer, and 4 that it should decline (for example "What is our refund SLA for students in London?"). An answerable question passes only if the bot cites the right source; a decline question passes only if the bot declines.

| Run | Retrieval mode (no API key) |
|---|---|
| First run, questions written before any tuning | 20 / 24 (83%) |
| After one general fix (recognising "What's happening with…" as a status question) | 21 / 24 (88%) |

The 3 it still gets wrong:
- "How does MRP work?" finds the manufacturing intro instead of the MRP page.
- "How do I add a new employee?" misses the page titled "Create New Employee", because keyword search doesn't know "add" and "create" mean the same here.
- "When is the next Product All Hands?" should be declined, but matches an unrelated page on "product" and "next".

Claude mode can be scored the same way with `python tools/eval_ask.py --claude`. It hasn't been scored yet because I didn't have an API key on the build machine.

### Slack

1. Create a Slack app with a slash command `/ask` whose Request URL is `https://<your-host>/slack/ask`.
2. Set `SLACK_SIGNING_SECRET` (Slack app → Basic Information) and run `python -m autopilot serve --port 3000`.
3. For a local demo, expose the port with a tunnel such as ngrok or cloudflared.

Every request is checked against Slack's signature, and anything older than 5 minutes is rejected. Retrieval answers go back immediately. Claude answers are acknowledged straight away and posted to the channel when ready, because Slack expects a reply within 3 seconds. The endpoint was tested locally with signed and forged requests; I haven't connected it to a live Slack workspace yet.

### Where the bot's data comes from

`tools/fetch_knowledge.py` takes a snapshot of:
- the 213 AsciiDoc user-guide pages in [apache/ofbiz-framework](https://github.com/apache/ofbiz-framework), pinned to one commit (translations are skipped when indexing);
- every OFBIZ ticket updated in the last 90 days from the public [Apache Jira](https://issues.apache.org/jira/projects/OFBIZ) (445 tickets in the 20 Nov 2026 snapshot).

The source commit and date are in `knowledge/SOURCE.json`. The docs are © The Apache Software Foundation under the Apache License 2.0, whose licence and notice files are included in `knowledge/ofbiz_docs/`. For a real team you would point the same loaders at your own Notion export or docs folder and your Jira project.

## Connecting real tools

Set environment variables (or GitHub Actions secrets):

| Variable | What it does |
|---|---|
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | Jira Cloud access (API token from id.atlassian.com) |
| `JIRA_BOARDS` | Pods and their board ids, e.g. `Search:12,Booking:15` |
| `JIRA_SPRINT_FIELD`, `JIRA_POINTS_FIELD` | Custom field ids if yours differ from the defaults |
| `ANTHROPIC_API_KEY` | Uses Claude to extract action items from free-form notes, and to write the bot's answers |
| `ASK_MODEL` | Claude model for the bot (default `claude-opus-5-5`) |
| `SLACK_WEBHOOK_URL` | Posts the weekly summary and reminders to Slack |
| `SLACK_SIGNING_SECRET` | Verifies requests to the `/ask` slash command |

Then run `python -m autopilot weekly --source jira`.

Without `ANTHROPIC_API_KEY`, notes are parsed with simple rules: lines starting `Decision:` and `Action: Owner - task - due YYYY-MM-DD`. With the key, Claude handles messy, unstructured notes.

## How it's built

```
autopilot/
  sources.py     sample data loader + Jira Cloud Agile API client (standard library only)
  metrics.py     sprint health metrics, RAG thresholds, cycle time
  actions.py     notes → decisions and action items (Claude or rules), tracker, chase list
  knowledge.py   loads docs, team notes, tickets and meeting items into passages; BM25 search
  ask.py         the bot: question type, evidence check, answer (Claude or quoted), question log, gap stats
  slack_bot.py   Slack slash-command endpoint with signature checks
  report.py      Markdown, HTML and Slack message rendering
  notify.py      Slack incoming-webhook sender (dry-run by default without a webhook)
knowledge/       the bot's data: OFBiz docs and Jira snapshot, plus team_notes/ for filling gaps
tools/           data snapshot, sample-data generator, demo questions, bot evaluation
.github/workflows/weekly.yml   runs every Monday and keeps the report as an artifact
```

Built with Claude Code.

## Known limits

- In Jira mode, "added after sprint start" is approximated from the issue's created date or an `unplanned` label; reading the sprint-change history would be more exact.
- The tracker is a JSON file. A team version would live in a Notion database or a Jira filter so people can close items where they already work.
- The Jira connector has been written against the documented Agile REST API but tested here only with the sample data.
- The bot's search matches keywords, not meaning, so it misses synonyms ("add" vs "create"). Adding embeddings would help; the evaluation script would show whether it does.
- The bot reads a Jira snapshot, not live Jira. Rerun `tools/fetch_knowledge.py` (or schedule it) to refresh it.
- The questions in `state/questions.jsonl` are demo questions I asked from `tools/demo_questions.txt`, not real team usage.

## Ideas for next steps

- New-hire onboarding workflow: checklist from a template, buddy assignment, day 1/3/5 nudges and a day-30 feedback survey.
- Store action items in Notion instead of a JSON file, so owners can close them where they already work.
- Track "hours saved" by logging each run against the time the manual version took.
