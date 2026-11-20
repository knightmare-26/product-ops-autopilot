"""Score the Ask Product bot against the labelled questions in tests/ask_eval.json.

    python tools/eval_ask.py            # retrieval mode (free, no API key)
    python tools/eval_ask.py --claude   # also let Claude write the answers (needs ANTHROPIC_API_KEY; costs a few cents)

A question passes when:
  answerable   the bot answers AND one of its cited sources is an expected one
  GAP          the bot declines to answer (it must not make something up)
Nothing is written to the question log.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autopilot import ask  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cases = json.loads((ROOT / "tests" / "ask_eval.json").read_text(encoding="utf-8"))["questions"]
    ix = ask.index()
    passed, rows = 0, []
    for c in cases:
        r = ask.ask(c["q"], ix=ix, log=False, use_claude=args.claude)
        cited = [h["id"] for h in r["cited"]]
        if c["expect"] == "GAP":
            ok = not r["answered"]
        else:
            ok = r["answered"] and any(e in cid for cid in cited for e in c["expect"])
        passed += ok
        rows.append((ok, c["q"], "declined" if not r["answered"] else (cited[0] if cited else "-")))
    for ok, q, got in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {q}\n      -> {got}")
    gaps = [c for c in cases if c["expect"] == "GAP"]
    print(f"\n{passed}/{len(cases)} passed ({passed / len(cases):.0%}) · "
          f"{len(cases) - len(gaps)} answerable, {len(gaps)} that should be declined · "
          f"mode: {'claude' if args.claude else 'retrieval'}")


if __name__ == "__main__":
    main()
