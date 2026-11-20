import hashlib
import hmac
import json
import sys
import types
from datetime import date

from autopilot import ask, knowledge, report, slack_bot

TICKET = {"key": "SHOP-7", "url": "https://jira.example/browse/SHOP-7", "type": "Bug", "summary": "Refund button fails on partial returns",
          "status": "In Progress", "status_category": "In Progress", "priority": "Major", "assignee": "Asha",
          "created": "2026-10-01", "updated": "2026-10-20", "resolved": None, "fix_versions": [], "components": ["order"],
          "description": "Clicking refund on a partially returned order throws an error.", "comment_count": 1,
          "last_comment": {"author": "Asha", "date": "2026-10-20", "text": "Waiting on payments team review."}}


def passages():
    return [
        {"id": "doc:returns.adoc#0", "kind": "doc", "title": "Returns › Overview", "url": "https://docs/returns",
         "text": "A sales return is merchandise sent back by a customer. Returns can be refunded or given as store credit. "
                 "The warehouse receives the item and inspects it.", "meta": {}},
        {"id": "doc:invoices.adoc#1", "kind": "doc", "title": "Invoices", "url": "https://docs/invoices",
         "text": "An invoice is created when an order ships. Invoices can be paid in part or in full.", "meta": {}},
        {"id": "ticket:SHOP-7", "kind": "ticket", "title": "SHOP-7: " + TICKET["summary"], "url": TICKET["url"],
         "text": TICKET["summary"] + " " + TICKET["description"], "meta": TICKET},
    ]


def test_tokens_drop_stopwords_and_trim_suffixes():
    assert knowledge.tokens("How do the Returns work?") == ["return", "work"]
    assert knowledge.tokens("returned returning") == ["return", "return"]


def test_clean_adoc_removes_licence_block_and_markup():
    text = "////\nLicensed to the ASF\n////\n= Returns\n:toc:\nSee *bold* link:x.html[the guide] +\n"
    cleaned = knowledge._clean_adoc(text)
    assert "Licensed" not in cleaned and ":toc:" not in cleaned
    assert "See bold the guide" in cleaned


def test_search_ranks_the_matching_doc_first():
    hits = knowledge.Index(passages()).search("can a sales return be given as store credit")
    assert hits[0]["id"] == "doc:returns.adoc#0"
    assert hits[0]["coverage"] == 1.0


def test_intent():
    assert ask.intent("What is the status of the refund bug?") == "status"
    assert ask.intent("Where are we on SHOP-7") == "status"
    assert ask.intent("How do returns work?") == "howto"


def test_named_ticket_comes_first_and_stale_work_is_flagged():
    ix = knowledge.Index(passages())
    kind, hits = ask.retrieve("Any news on SHOP-7?", ix)
    assert hits[0]["id"] == "ticket:SHOP-7"
    r = ask.answer_retrieval("Any news on SHOP-7?", kind, hits, today=date(2026, 11, 20))
    assert r["answered"] and "In Progress" in r["answer"]
    assert "No update for 31 days" in r["answer"]
    assert [h["id"] for h in r["cited"]] == ["ticket:SHOP-7"]


def test_unrelated_question_is_declined_not_guessed():
    ix = knowledge.Index(passages())
    r = ask.ask("What is the refund SLA for students in London?", ix=ix, log=False, use_claude=False)
    assert not r["answered"] and r["cited"] == []


def test_log_and_weekly_stats(tmp_path):
    ix, log = knowledge.Index(passages()), tmp_path / "q.jsonl"
    for q in ["How are returns refunded?", "how are returns refunded", "Who is the onboarding buddy?",
              "Who is the onboarding buddy?"]:
        ask.ask(q, ix=ix, log_path=log, use_claude=False, asker="kabir")
    s = ask.stats(date.today(), path=log)
    assert s["asked"] == 4 and s["answered"] == 2 and s["answer_rate"] == 0.5
    assert s["recurring_questions"] == 2 and s["recurring_answer_rate"] == 0.5
    assert [g["question"] for g in s["gaps"]] == ["Who is the onboarding buddy?"]
    assert s["gaps"][0]["times"] == 2
    assert "asked 2x" in ask.gap_report(s)


def test_adding_a_team_note_closes_the_gap(tmp_path):
    q = "Who is the onboarding buddy for new PMs?"
    assert not ask.ask(q, ix=knowledge.Index(passages()), log=False, use_claude=False)["answered"]
    (tmp_path / "onboarding.md").write_text("# Onboarding buddy\nEvery new PM gets an onboarding buddy from the "
                                            "same pod for the first month.\n", encoding="utf-8")
    ix = knowledge.Index(passages() + knowledge.load_notes(tmp_path))
    r = ask.ask(q, ix=ix, log=False, use_claude=False)
    assert r["answered"] and r["cited"][0]["kind"] == "note"


def test_claude_answer_keeps_only_real_citations(monkeypatch):
    calls = {}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            body = {"answered": True, "answer": "Returns can be refunded or given as store credit [1].",
                    "citations": [1, 9], "missing": ""}
            return types.SimpleNamespace(stop_reason="end_turn",
                                         content=[types.SimpleNamespace(type="text", text=json.dumps(body))])

    fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(beta=types.SimpleNamespace(messages=FakeMessages())))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    r = ask.ask("How are returns refunded?", ix=knowledge.Index(passages()), log=False, use_claude=True)
    assert r["method"] == "claude" and r["answered"]
    assert [h["id"] for h in r["cited"]] == ["doc:returns.adoc#0"]          # citation 9 doesn't exist, so it's dropped
    assert calls["model"] == ask.MODEL and calls["output_config"]["format"]["type"] == "json_schema"


def test_claude_failure_falls_back_to_retrieval(monkeypatch):
    def boom():
        raise RuntimeError("network down")
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=boom))
    r = ask.ask("How are returns refunded?", ix=knowledge.Index(passages()), log=False, use_claude=True)
    assert r["method"] == "retrieval" and r["answered"]


def test_slack_signature_check():
    body, ts, secret = "text=hello", "1700000000", "s3cret"
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    assert slack_bot.verify(secret, ts, body, sig, now=1700000010)
    assert not slack_bot.verify(secret, ts, body + "x", sig, now=1700000010)      # tampered body
    assert not slack_bot.verify(secret, ts, body, sig, now=1700000000 + 600)      # replayed after 5 minutes
    assert not slack_bot.verify(None, ts, body, sig)


def test_report_includes_bot_section_only_when_given():
    summary = {"pods": [], "team_spillover_rate": 0.1, "cycle_time": {"median_days": 30, "count": 2}, "source": "sample"}
    bot = {"asked": 3, "answered": 2, "answer_rate": 2 / 3, "recurring_questions": 1, "recurring_answer_rate": 1.0,
           "by_intent": {"status": 1, "howto": 2}, "gaps": [{"question": "Who is the buddy?", "times": 1}]}
    md = report.markdown(summary, {}, [], 0.5, date(2026, 11, 20), bot=bot)
    assert "## Ask Product bot" in md and "67% answered with evidence" in md and "Who is the buddy?" in md
    assert "Ask Product bot" not in report.markdown(summary, {}, [], 0.5, date(2026, 11, 20))
    assert "Ask Product bot" in report.html_report(summary, {}, [], 0.5, date(2026, 11, 20), bot=bot)
