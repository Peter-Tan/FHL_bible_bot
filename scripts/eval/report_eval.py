"""Cross-engine comparison report from one or more judged_*.json files.

Usage (from repo root):
    .venv/bin/python scripts/eval/report_eval.py scripts/eval/runs/judged_v7_*.json \
        scripts/eval/runs/judged_v6_*.json scripts/eval/runs/judged_v4_*.json

Prints a markdown report: mean scores overall and per category, engine cost,
judge cost, latency, web-search usage, and deterministic-check failures —
one column per engine run.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def load(path):
    d = json.loads(Path(path).read_text())
    return d["meta"], d["judged"]


def mean(xs):
    # Exclude non-positive scores: 0 = judge parse failure, -1 = judge
    # safety-refused even after sanitizing. Both are unscored, not zeros.
    xs = [x for x in xs if x > 0]
    return statistics.mean(xs) if xs else 0.0


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    runs = [load(p) for p in sys.argv[1:]]

    cols = [f"{m['engine']} ({m['timestamp'][:10]})" for m, _ in runs]
    print("# FHL Bible Bot — engine evaluation report\n")
    print("| metric | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))

    def row(label, fn, fmt="{:.2f}"):
        print(f"| {label} | " + " | ".join(
            fmt.format(fn(m, j)) for m, j in runs) + " |")

    row("questions", lambda m, j: m["n_questions"], "{:d}")
    row("engine errors", lambda m, j: m["n_errors"], "{:d}")
    row("**faithfulness (mean)**", lambda m, j: mean([r["faithfulness"] for r in j]))
    row("**relevancy (mean)**", lambda m, j: mean([r["relevancy"] for r in j]))
    row("**coverage (mean)**", lambda m, j: mean([r["coverage"] for r in j]))
    row("verse-link errors (total)",
        lambda m, j: sum(len(r["checks"]["verse_link_errors"]) for r in j), "{:d}")
    row("unsupported quotes (total)",
        lambda m, j: sum(len(r["checks"]["quote_check"]["quotes_not_in_tool_evidence"])
                         for r in j), "{:d}")
    row("dead article links (total)",
        lambda m, j: sum(1 for r in j for _, s in r["checks"]["article_status"]
                         if s != 200), "{:d}")
    row("web searches (total)", lambda m, j: m.get("total_web_searches", 0), "{:d}")
    row("median latency s", lambda m, j: statistics.median(r["wall_s"] for r in j))
    row("**engine cost USD**", lambda m, j: m["total_cost_usd"], "${:.2f}")
    row("cost / question USD", lambda m, j: m["total_cost_usd"] / m["n_questions"],
        "${:.3f}")
    row("judge cost USD", lambda m, j: m.get("judge_cost_usd", 0), "${:.2f}")

    print("\n## Per-category mean scores (F / R / C)\n")
    cats = sorted({r["category"] for _, j in runs for r in j})
    print("| category | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))
    for cat in cats:
        cells = []
        for _, j in runs:
            rs = [r for r in j if r["category"] == cat]
            cells.append(f"{mean([r['faithfulness'] for r in rs]):.1f} / "
                         f"{mean([r['relevancy'] for r in rs]):.1f} / "
                         f"{mean([r['coverage'] for r in rs]):.1f}"
                         if rs else "—")
        print(f"| {cat} (n={sum(1 for r in runs[0][1] if r['category'] == cat)}) | "
              + " | ".join(cells) + " |")

    print("\n## Lowest-scoring questions per run\n")
    for (m, j), col in zip(runs, cols):
        worst = sorted(j, key=lambda r: r["faithfulness"] + r["relevancy"]
                       + r["coverage"])[:5]
        print(f"**{col}**")
        for r in worst:
            v = ("; ".join(r["violations"])[:120]) if r["violations"] else r["rationale"][:120]
            print(f"- {r['id']} F{r['faithfulness']} R{r['relevancy']} "
                  f"C{r['coverage']} — {v}")
        print()


if __name__ == "__main__":
    main()
