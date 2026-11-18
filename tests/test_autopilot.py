from datetime import date

from autopilot import actions, metrics


def issue(key, status="Done", adhoc=False, story=True, desc="", carried=False):
    return {"key": key, "type": "Story" if story else "Bug", "status": status, "added_after_start": adhoc,
            "carried_from_previous": carried, "description": desc}


GOOD = "word " * 45 + "Acceptance criteria: works."


def test_spillover_and_adhoc():
    sprint = {"name": "S1", "state": "closed", "start": "2026-11-03", "end": "2026-11-14", "closed_at": "2026-11-17",
              "issues": [issue("A-1"), issue("A-2", status="In Progress"), issue("A-3", status="To Do"),
                         issue("A-4"), issue("A-5", adhoc=True)]}
    m = metrics.sprint_metrics(sprint)
    assert m["planned"] == 4
    assert m["spillover"] == ["A-2", "A-3"]
    assert m["spillover_rate"] == 0.5
    assert m["adhoc_share"] == 0.2
    assert m["closure_delay_days"] == 3


def test_doc_quality_needs_length_and_acceptance_criteria():
    assert metrics.doc_ok({"description": GOOD})
    assert not metrics.doc_ok({"description": "word " * 60})        # long but no AC
    assert not metrics.doc_ok({"description": "Acceptance criteria: x"})  # AC but too short


def test_rag_direction():
    assert metrics.rag("spillover_rate", 0.10) == "green"
    assert metrics.rag("spillover_rate", 0.40) == "red"
    assert metrics.rag("doc_quality", 0.90) == "green"
    assert metrics.rag("doc_quality", 0.50) == "red"


def test_rule_parser_extracts_actions_and_decisions():
    text = "Decision: Ship it\nAction: Kabir - Share funnel data - due 2026-11-12\nAction: Meera - Get sign-off\nnoise"
    out = actions.parse_rules(text)
    assert out["decisions"] == ["Ship it"]
    assert out["actions"][0] == {"owner": "Kabir", "task": "Share funnel data", "due": "2026-11-12"}
    assert out["actions"][1]["due"] is None


def test_chase_flags():
    state = {"items": {
        "a": {"id": "a", "owner": "X", "task": "t1", "due": "2026-11-10", "meeting": "m", "date": "d", "status": "open"},
        "b": {"id": "b", "owner": "X", "task": "t2", "due": "2026-11-19", "meeting": "m", "date": "d", "status": "open"},
        "c": {"id": "c", "owner": "Y", "task": "t3", "due": None, "meeting": "m", "date": "d", "status": "open"},
        "d": {"id": "d", "owner": "Y", "task": "t4", "due": "2026-11-01", "meeting": "m", "date": "d", "status": "done"},
    }, "decisions": []}
    chase = actions.chase_list(state, date(2026, 11, 18))
    assert [i["flag"] for i in chase["X"]] == ["overdue", "due soon"]
    assert chase["X"][0]["days_overdue"] == 8
    assert [i["flag"] for i in chase["Y"]] == ["no due date"]
    assert actions.closure_rate(state) == 0.25
