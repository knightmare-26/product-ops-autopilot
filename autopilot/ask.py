"""Ask Product: answer "How does X work?" and "What is the status of Y?" with evidence, and log what it can't answer.

Two ways to answer, same output shape:
  claude     when ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) is set and the `anthropic` package is installed.
             Claude reads the top passages and writes a short answer that cites them, or says it can't answer.
  retrieval  no key needed. Shows the best-matching ticket status or doc sentences, word for word.

Every question is appended to state/questions.jsonl. Questions without evidence are the knowledge gaps:
the weekly report lists them so someone can add a note to knowledge/team_notes/, and the bot picks the
note up on the next question.
"""
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import knowledge

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "state" / "questions.jsonl"
MODEL = os.environ.get("ASK_MODEL", "claude-opus-5-5")

MIN_COVERAGE = 0.5      # the best passage must contain at least half the question's keywords, or the bot says it doesn't know
STALE_DAYS = 14         # open tickets with no update for this long get flagged

KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
STATUS_RE = re.compile(r"\b(status|progress|blocked|stuck|eta|when will|fixed|resolved|open|closed|done yet|"
                       r"who is working|assigned|owner|ticket|bug|issue|shipped|released|overdue|due|"
                       r"happening with|where are we|update on|latest on|being worked on|done|decided?|decision)\b"
                       r"|^\s*(is|are|has|have|did|was|were)\b", re.I)   # yes/no questions are about the state of something

# How much each kind of source counts for each kind of question.
WEIGHTS = {
    "status": {"ticket": 1.6, "action": 1.6, "decision": 1.2, "doc": 0.7, "note": 1.0},
    "howto": {"doc": 1.2, "note": 1.3, "ticket": 0.8, "action": 0.8, "decision": 1.0},
}

_INDEX = None


def index():
    global _INDEX
    if _INDEX is None:
        _INDEX = knowledge.build_index()
    return _INDEX


def reset_index():
    """Call after adding a team note so the next question sees it."""
    global _INDEX
    _INDEX = None


def intent(question):
    return "status" if KEY_RE.search(question) or STATUS_RE.search(question) else "howto"


def retrieve(question, ix=None, k=8):
    ix = ix or index()
    kind = intent(question)
    hits = ix.search(question, k=k, weights=WEIGHTS[kind])
    keys = KEY_RE.findall(question)
    if keys:                                    # a ticket named in the question always comes first
        named = [p for p in ix.passages if p["kind"] == "ticket" and p["meta"]["key"] in keys]
        hits = [{**p, "score": 99.0, "coverage": 1.0} for p in named] + [h for h in hits if h["id"] not in
                                                                         {p["id"] for p in named}]
    return kind, hits[:k]


def has_evidence(hits):
    return bool(hits) and hits[0]["coverage"] >= MIN_COVERAGE


# ------------------------------------------------------------------ retrieval-only answers
def describe_ticket(t, today=None):
    today = today or date.today()
    line = f"{t['key']} \"{t['summary']}\" is {t['status']}"
    bits = [f"assignee {t['assignee']}", f"last updated {t['updated']}"]
    if t.get("resolved"):
        bits.append(f"resolved {t['resolved']}")
    if t.get("fix_versions"):
        bits.append(f"fix version {', '.join(t['fix_versions'])}")
    out = f"{line} ({'; '.join(bits)})."
    if t["status_category"] != "Done":
        idle = (today - date.fromisoformat(t["updated"])).days
        if idle >= STALE_DAYS:
            out += f" No update for {idle} days, worth a nudge."
    if t.get("last_comment"):
        c = t["last_comment"]
        out += f" Latest comment ({c['author']}, {c['date']}): \"{_trim(c['text'], 40)}\""
    return out


def describe_action(it, today=None):
    today = today or date.today()
    if it["status"] != "open":
        return f"{it['owner']}'s action \"{it['task']}\" (from {it['meeting']}, {it['date']}) is done."
    due = it.get("due")
    when = "no due date"
    if due:
        late = (today - date.fromisoformat(due)).days
        when = f"overdue by {late} days (due {due})" if late > 0 else f"due {due}"
    return f"{it['owner']}'s action \"{it['task']}\" (from {it['meeting']}, {it['date']}) is open, {when}."


def _trim(text, words):
    w = text.split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


def best_sentences(question, text, n=3):
    """The passage's opening sentence (usually the definition) plus the sentences that share most words with the question."""
    q = set(knowledge.tokens(question))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 4]
    if not sents:
        return _trim(text, 60)
    ranked = sorted(range(1, len(sents)), key=lambda i: -len(q & set(knowledge.tokens(sents[i]))))[:n - 1]
    return " ".join(sents[i] for i in sorted([0] + ranked))


def answer_retrieval(question, kind, hits, today=None):
    if not has_evidence(hits):
        return {"answered": False, "answer": "I couldn't find this in the docs, tickets or meeting notes I have. "
                                             "It's logged as a knowledge gap.", "cited": []}
    top = hits[0]
    # Supporting sources: same kind as the best match and nearly as relevant. A ticket named in the question stands alone.
    cited = [top] if top["score"] == 99.0 else [
        h for h in hits[:3] if h["kind"] == top["kind"] and h["coverage"] >= max(MIN_COVERAGE, top["coverage"] - 0.2)]
    if top["kind"] == "ticket":
        text = describe_ticket(top["meta"], today)
    elif top["kind"] == "action":
        text = describe_action(top["meta"], today)
    elif top["kind"] == "decision":
        d = top["meta"]
        text = f"Decided in {d['meeting']} on {d['date']}: {d['text']}"
    else:
        # A long section is split into several windows; quote from the first one, where the section introduces itself.
        same = [h for h in hits if h["title"] == top["title"] and "#" in h["id"]]
        first = min(same, key=lambda h: int(h["id"].rsplit("#", 1)[1])) if same else top
        text = f"From \"{top['title']}\": {best_sentences(question, first['text'])}"
    return {"answered": True, "answer": text, "cited": cited}


# ------------------------------------------------------------------ Claude answers
SYSTEM = """You answer questions from a product team using only the numbered sources provided.
Rules:
- Use only facts stated in the sources. If they don't answer the question, set answered to false and say in
  `missing` what information would be needed. Never fill gaps from general knowledge.
- Cite every claim with the source number in square brackets, like [2].
- For status questions, give the current status, owner and last update date, and say if something looks stuck.
- Keep the answer under 120 words, plain language, no headings."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answered": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "integer"}},
        "missing": {"type": "string"},
    },
    "required": ["answered", "answer", "citations", "missing"],
    "additionalProperties": False,
}


def claude_available():
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _source_block(n, h, today):
    if h["kind"] == "ticket":
        body = describe_ticket(h["meta"], today) + " Details: " + _trim(h["text"], 120)
    elif h["kind"] == "action":
        body = describe_action(h["meta"], today)
    else:
        body = h["text"]
    return f"[{n}] ({h['kind']}) {h['title']}\n{body}"


def answer_claude(question, kind, hits, today=None):
    import anthropic

    today = today or date.today()
    sources = "\n\n".join(_source_block(n, h, today) for n, h in enumerate(hits, 1))
    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                       # if the model declines, the API retries on a fallback model
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": f"Today is {today}. Question type: {kind}.\n\n"
                                              f"Sources:\n{sources}\n\nQuestion: {question}"}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined")
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    cited = [hits[i - 1] for i in out["citations"] if 1 <= i <= len(hits)]
    answered = out["answered"] and bool(cited)
    text = out["answer"] if answered else (out["answer"] + (f" Missing: {out['missing']}" if out["missing"] else ""))
    return {"answered": answered, "answer": text, "cited": cited if answered else [], "missing": out["missing"]}


# ------------------------------------------------------------------ main entry point
def ask(question, ix=None, today=None, log=True, asker=None, log_path=None, use_claude=None):
    kind, hits = retrieve(question, ix)
    method = "retrieval"
    if use_claude if use_claude is not None else claude_available():
        try:
            result, method = answer_claude(question, kind, hits, today), "claude"
        except Exception as e:  # a bad response or network error should never leave the asker with nothing
            print(f"  Claude answer failed ({e}); falling back to retrieval")
            result = answer_retrieval(question, kind, hits, today)
    else:
        result = answer_retrieval(question, kind, hits, today)
    result.update(question=question, intent=kind, method=method)
    if log:
        _log(result, hits, asker, log_path or LOG)
    return result


def _log(result, hits, asker, path):
    path = Path(path)
    path.parent.mkdir(exist_ok=True)
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "question": result["question"],
             "intent": result["intent"], "answered": result["answered"], "method": result["method"],
             "sources": [h["id"] for h in result["cited"]],
             "closest": hits[0]["title"] if hits else None,
             "closest_coverage": hits[0]["coverage"] if hits else 0, "asker": asker}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def format_answer(result):
    lines = [result["answer"]]
    if result["cited"]:
        lines.append("")
        lines.append("Sources:")
        lines += [f"[{n}] {h['title']} ({h['kind']}) {h['url']}" for n, h in enumerate(result["cited"], 1)]
    lines.append(f"\n({result['method']} · {'answered with evidence' if result['answered'] else 'knowledge gap logged'})")
    return "\n".join(lines)


# ------------------------------------------------------------------ usage and gap reporting
def read_log(path=None):
    path = Path(path or LOG)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _cluster(question):
    """Questions with the same keywords count as the same question (catches simple rewordings)."""
    return " ".join(sorted(set(knowledge.tokens(question))))


def stats(today=None, days=7, path=None):
    today = today or date.today()
    since = today - timedelta(days=days - 1)
    entries = [e for e in read_log(path) if since <= date.fromisoformat(e["ts"][:10]) <= today]
    groups = defaultdict(list)
    for e in entries:
        groups[_cluster(e["question"])].append(e)
    recurring = [g for g in groups.values() if len(g) > 1]
    gaps = sorted(([g for g in groups.values() if not any(e["answered"] for e in g)]),
                  key=lambda g: (-len(g), g[-1]["ts"]))
    answered = sum(e["answered"] for e in entries)
    return {
        "window_days": days, "since": since.isoformat(),
        "asked": len(entries),
        "answered": answered,
        "answer_rate": answered / len(entries) if entries else 0.0,
        "recurring_questions": len(recurring),
        "recurring_answer_rate": (sum(any(e["answered"] for e in g) for g in recurring) / len(recurring))
        if recurring else 0.0,
        "by_intent": dict(Counter(e["intent"] for e in entries)),
        "askers": len({e["asker"] for e in entries if e.get("asker")}),
        "gaps": [{"question": g[-1]["question"], "times": len(g), "closest": g[-1].get("closest"),
                  "last_asked": g[-1]["ts"][:10]} for g in gaps[:8]],
    }


def gap_report(s):
    lines = [f"Ask Product bot, last {s['window_days']} days: {s['asked']} questions, "
             f"{s['answer_rate'] * 100:.0f}% answered with evidence, "
             f"{s['recurring_questions']} asked more than once."]
    if not s["gaps"]:
        lines.append("No knowledge gaps.")
    for g in s["gaps"]:
        lines.append(f"- \"{g['question']}\" (asked {g['times']}x, last {g['last_asked']}). "
                     f"Closest match: {g['closest'] or 'nothing'}. Add a note to knowledge/team_notes/.")
    return "\n".join(lines)
