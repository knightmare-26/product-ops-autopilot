"""The Ask Product bot's knowledge base: load every source, cut it into passages, and search them.

Sources (all optional, each passage keeps a link back to where it came from):
  doc       product documentation       knowledge/ofbiz_docs/**/*.adoc   (AsciiDoc user guides)
  note      team notes added to fill gaps knowledge/team_notes/*.md
  ticket    Jira issues                  knowledge/jira_ofbiz.json        (snapshot from tools/fetch_knowledge.py)
  action    meeting action items         state/action_items.json          (from actions.py)
  decision  meeting decisions            state/action_items.json

Search is BM25, a standard keyword-ranking formula, written out here so the project needs no
extra packages. It is fast enough for a few thousand passages and its scores are easy to explain.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "knowledge"
DOCS = KNOW / "ofbiz_docs"
NOTES = KNOW / "team_notes"
JIRA = KNOW / "jira_ofbiz.json"
STATE = ROOT / "state" / "action_items.json"

MAX_WORDS = 220      # longer sections are split into overlapping windows of about this size
MIN_WORDS = 12       # shorter fragments (stray headings, lone links) are dropped

STOP = set("""a about above after again all also am an and any are as at be because been before being below
between both but by can could did do does doing done down during each few for from further had has have having
he her here hers him his how i if in into is it its itself just let me more most my no nor not now of off on once
only or other our out over own please same she should so some such tell than that the their them then there these
they this those through to too under until up very was we were what when where which while who whom why will with
would you your yours ofbiz""".split())


# ------------------------------------------------------------------ text helpers
def tokens(text):
    """Lowercase words with a light suffix trim, so 'returns', 'returned' and 'return' match."""
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def _clean_adoc(text):
    text = re.sub(r"^////.*?^////\s*$", "", text, flags=re.S | re.M)          # comment blocks (licence headers)
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^(//|:[\w-]+:|include::|image::|ifdef::|endif::|\[\[|\[[a-z#.]|\|===|----|====|\*\*\*\*|toc::)", s):
            continue
        s = re.sub(r"(link|image|xref):\S+?\[([^\]]*)\]", r"\2", s)              # keep link text, drop target
        s = re.sub(r"<<[^,>]+,([^>]+)>>|<<([^>]+)>>", lambda m: m[1] or m[2], s)
        s = re.sub(r"[*_`]{1,2}([^*_`]+)[*_`]{1,2}", r"\1", s)                    # bold / italic / mono
        s = re.sub(r"(^|\s)\+$", "", s.lstrip("|").strip())                       # AsciiDoc line-continuation marks
        lines.append(s.strip())
    return "\n".join(lines)


def _windows(words, size=MAX_WORDS, overlap=40):
    if len(words) <= size:
        return [words]
    step = size - overlap
    return [words[i:i + size] for i in range(0, max(len(words) - overlap, 1), step)]


# ------------------------------------------------------------------ loaders
def load_docs(root=DOCS, commit=None):
    """Split each AsciiDoc page by headings; one passage per section (long ones windowed)."""
    if not root.exists():
        return []
    commit = commit or _source().get("docs_commit", "trunk")
    passages = []
    for f in sorted(root.rglob("*.adoc")):
        if re.search(r"_[A-Z]{2}\.adoc$", f.name):        # translations (e.g. _NL, _IT): the English page is enough
            continue
        rel = f.relative_to(root).as_posix()
        url = f"https://github.com/apache/ofbiz-framework/blob/{commit}/{rel}"
        text = _clean_adoc(f.read_text(encoding="utf-8", errors="replace"))
        page, section, body = None, None, []

        def flush():
            words = " ".join(body).split()
            for n, win in enumerate(_windows(words)):
                if len(win) >= MIN_WORDS:
                    title = " › ".join(t for t in (page, section) if t) or rel
                    passages.append({"id": f"doc:{rel}#{len(passages)}", "kind": "doc", "title": title,
                                     "text": " ".join(win), "url": url, "meta": {"path": rel}})

        for line in text.splitlines():
            m = re.match(r"^(=+)\s+(.+)$", line)
            if m:
                flush()
                body = []
                if len(m[1]) == 1 and page is None:
                    page, section = m[2].strip(), None
                else:
                    section = m[2].strip()
            elif line.strip():
                body.append(line.strip())
        flush()
    return passages


def load_notes(root=NOTES):
    """Markdown notes the team adds when the bot reports a gap. One passage per '#' section."""
    if not root.exists():
        return []
    passages = []
    for f in sorted(root.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        title, body = f.stem.replace("-", " ").replace("_", " "), []
        sections = []
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^#+\s+(.+)$", line)
            if m:
                if body:
                    sections.append((title, body))
                title, body = m[1].strip(), []
            elif line.strip():
                body.append(line.strip())
        if body:
            sections.append((title, body))
        for title, body in sections:
            for win in _windows(" ".join(body).split()):
                passages.append({"id": f"note:{f.name}#{len(passages)}", "kind": "note", "title": title,
                                 "text": " ".join(win), "url": f"knowledge/team_notes/{f.name}",
                                 "meta": {"path": f.name}})
    return passages


def load_tickets(path=JIRA):
    if not path.exists():
        return []
    passages = []
    for t in json.loads(path.read_text(encoding="utf-8")):
        parts = [t["summary"], " ".join(t.get("components", [])), t.get("description") or ""]
        if t.get("last_comment"):
            parts.append(t["last_comment"]["text"])
        passages.append({"id": f"ticket:{t['key']}", "kind": "ticket", "title": f"{t['key']}: {t['summary']}",
                         "text": " ".join(" ".join(parts).split()[:MAX_WORDS]), "url": t["url"], "meta": t})
    return passages


def load_meetings(path=STATE):
    if not path.exists():
        return []
    state = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for it in state.get("items", {}).values():
        out.append({"id": f"action:{it['id']}", "kind": "action", "title": f"Action for {it['owner']}: {it['task']}",
                    "text": f"{it['owner']} {it['task']} {it['meeting']}", "url": "state/action_items.json", "meta": it})
    for n, d in enumerate(state.get("decisions", [])):
        out.append({"id": f"decision:{n}", "kind": "decision", "title": f"Decision in {d['meeting']}",
                    "text": f"{d['text']} {d['meeting']}", "url": "state/action_items.json", "meta": d})
    return out


def _source():
    p = KNOW / "SOURCE.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ------------------------------------------------------------------ search
class Index:
    """BM25 over passages. Title words count twice, because titles are short and specific."""

    def __init__(self, passages, k1=1.4, b=0.75):
        self.passages, self.k1, self.b = passages, k1, b
        self.tf = []
        df = Counter()
        for p in passages:
            c = Counter(tokens(p["text"]) + tokens(p["title"]) * 2)
            self.tf.append(c)
            df.update(c.keys())
        n = len(passages) or 1
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.avg = sum(sum(c.values()) for c in self.tf) / n

    def search(self, query, k=8, weights=None):
        q = tokens(query)
        weights = weights or {}
        scored = []
        for i, c in enumerate(self.tf):
            length = sum(c.values()) or 1
            s = 0.0
            for t in q:
                if t in c:
                    f = c[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
            if s:
                p = self.passages[i]
                scored.append((s * weights.get(p["kind"], 1.0), i))
        scored.sort(reverse=True)
        return [{**self.passages[i], "score": round(s, 3), "coverage": self.coverage(q, i)} for s, i in scored[:k]]

    def coverage(self, qtokens, i):
        """Share of the question's distinct keywords that appear in passage i (0-1)."""
        q = set(qtokens)
        return round(len(q & self.tf[i].keys()) / len(q), 2) if q else 0.0


def build_index(include=("doc", "note", "ticket", "action", "decision")):
    loaders = {"doc": load_docs, "note": load_notes, "ticket": load_tickets}
    passages = [p for kind, fn in loaders.items() if kind in include for p in fn()]
    if "action" in include or "decision" in include:
        passages += [p for p in load_meetings() if p["kind"] in include]
    return Index(passages)
