"""Run the 50-question eval set through one engine version (v4-v7).

Usage (from repo root):
    .venv/bin/python scripts/eval/run_eval.py --engine v7
    .venv/bin/python scripts/eval/run_eval.py --engine v6 --limit 3
    .venv/bin/python scripts/eval/run_eval.py --engine v4 --ids exeg01 adve06

Writes scripts/eval/runs/results_{engine}_{timestamp}.json with, per
question: the answer, tool log, FULL tool results (captured by wrapping
fhl_tools.TOOL_MAP — the shared dict all engines dispatch through), token
usage, per-query cost, and wall time. The judge (judge_eval.py) consumes
this file; nothing here calls an LLM other than the engine itself.
"""
import argparse
import importlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(EVAL_DIR.parent))  # scripts/ — engines + fhl_tools

from eval_pricing import engine_cost_usd  # noqa: E402

ENGINES = ["v4", "v5", "v6", "v7", "v8"]

# v8 is the local Gemma engine and breaks the claude_bible_rag_* naming,
# so map engine id -> module name rather than string-formatting the prefix.
ENGINE_MODULES = {
    "v4": "claude_bible_rag_v4",
    "v5": "claude_bible_rag_v5",
    "v6": "claude_bible_rag_v6",
    "v7": "claude_bible_rag_v7",
    "v8": "gemma_bible_rag_v8",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=ENGINES)
    ap.add_argument("--limit", type=int, help="run only the first N questions")
    ap.add_argument("--ids", nargs="*", help="run only these question ids")
    ap.add_argument("--out", help="output path (default: runs/results_...)")
    args = ap.parse_args()

    eng = importlib.import_module(ENGINE_MODULES[args.engine])
    import fhl_tools

    qpath = EVAL_DIR / "questions.json"
    if not qpath.exists():
        qpath = EVAL_DIR / "questions.sample.json"
        print(f"[warn] questions.json not found — using {qpath.name} "
              f"(generic samples, not the real 50-question set)")
    questions = json.loads(qpath.read_text())
    if args.ids:
        questions = [q for q in questions if q["id"] in args.ids]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        sys.exit("no questions selected")

    # Capture full tool results: every engine holds a reference to this same
    # TOOL_MAP dict and dispatches through it, so swapping the entries here
    # records each call without touching engine code.
    records: list = []
    originals = dict(fhl_tools.TOOL_MAP)

    def _wrap(name, fn):
        def inner(**kw):
            result = fn(**kw)
            records.append({"tool": name, "args": kw, "result": result})
            return result
        return inner

    for name, fn in originals.items():
        fhl_tools.TOOL_MAP[name] = _wrap(name, fn)

    out = Path(args.out) if args.out else (
        EVAL_DIR / "runs" /
        f"results_{args.engine}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    results = []
    t_run = time.time()

    def _save(final: bool) -> None:
        """Write after every question — a 25-min run must survive a crash."""
        meta = {
            "engine": args.engine,
            "model": next((r["usage"].get("model") for r in results if r["usage"]), ""),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "complete": final,
            "n_questions": len(results),
            "n_errors": sum(1 for r in results if r["error"]),
            "total_cost_usd": round(sum(r["cost_usd"] for r in results), 4),
            "total_web_searches": sum(r["usage"].get("web_search", 0) for r in results),
            "total_wall_s": round(time.time() - t_run, 1),
        }
        out.write_text(json.dumps({"meta": meta, "results": results},
                                  ensure_ascii=False, indent=1))
        return meta

    for i, q in enumerate(questions, 1):
        records.clear()
        logs: list = []
        usage: dict = {}
        t0 = time.time()
        try:
            answer = eng.bible_query(
                user_question=q["question"],
                tools=fhl_tools.ALL_TOOLS,
                verbose=False,
                log_callback=logs.append,
                style="brief",
                usage_out=usage,
            ) or ""
            error = None
        except Exception as exc:
            answer, error = "", repr(exc)
        cost = engine_cost_usd(usage)
        results.append({
            "id": q["id"],
            "category": q["category"],
            "subtype": q.get("subtype"),
            "question": q["question"],
            "expected_behavior": q.get("expected_behavior"),
            "expected": q["expected"],
            "answer": answer,
            "error": error,
            "tool_log": logs,
            "tool_records": list(records),
            "usage": usage,
            "cost_usd": round(cost, 5),
            "wall_s": round(time.time() - t0, 1),
        })
        status = "ERR " + error[:60] if error else f"${cost:.3f}"
        print(f"[{i}/{len(questions)}] {q['id']} {results[-1]['wall_s']:.0f}s "
              f"searches={usage.get('web_search', 0)} {status}", flush=True)
        _save(final=False)

    for name, fn in originals.items():
        fhl_tools.TOOL_MAP[name] = fn

    meta = _save(final=True)
    print(f"\n{meta['engine']}: {meta['n_questions']} questions, "
          f"{meta['n_errors']} errors, engine cost ${meta['total_cost_usd']:.2f}, "
          f"{meta['total_web_searches']} web searches, {meta['total_wall_s']:.0f}s")
    print("saved", out)


if __name__ == "__main__":
    main()
