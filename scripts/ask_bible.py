"""
ask_bible.py — Bible RAG REPL with switchable backends
=======================================================
Supports two backends:
  --backend gemma   → local Gemma 4 E4B via bible_rag.py (default)
  --backend claude  → Claude via Anthropic API via claude_bible_rag.py

Run:
    python scripts/ask_bible.py                          # Gemma 4 (default)
    python scripts/ask_bible.py --backend claude         # Claude
    python scripts/ask_bible.py --backend claude --quiet --log logs/qa.log

Inline commands while running:
    quit   — exit
    reset  — clear conversation history
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bible RAG Q&A with switchable backends.")
    p.add_argument("--backend",    choices=["gemma", "claude"], default="claude",
                   help="Model backend: 'gemma' (local Gemma 4) or 'claude' (Anthropic API). Default: claude.")
    p.add_argument("--quiet",      action="store_true", help="Hide tool-call traces.")
    p.add_argument("--no-history", action="store_true", help="Treat every question independently.")
    p.add_argument("--log",        type=str, default="logs/qa.log",
                   help="Path to a transcript file (Q&A will be appended). Default: logs/qa.log. Use --no-log to disable.")
    p.add_argument("--no-log",     action="store_true", help="Disable logging.")
    return p.parse_args()


def append_log(path: Path, question: str, answer: str, backend: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n[{ts}] backend={backend}\nQ: {question}\nA: {answer}\n{'-' * 70}\n")


def main() -> None:
    args     = parse_args()
    verbose  = not args.quiet
    log_path = None if args.no_log else Path(args.log)
    backend  = args.backend

    if backend == "claude":
        from claude_bible_rag import bible_query
        from fhl_tools import ALL_TOOLS
        label = "Claude (Anthropic API)"
    else:
        from bible_rag import bible_query, ALL_TOOLS
        label = "Gemma 4 E4B (local)"

    history: list = []

    print("=" * 70)
    print(f"  Bible RAG · {label}")
    print(f"  verbose={verbose}  history={not args.no_history}"
          f"  log={'on → ' + str(log_path) if log_path else 'off'}")
    print("  Type 'quit' to exit, 'reset' to clear history.")
    print("=" * 70 + "\n")

    while True:
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not question:
            continue
        if question.lower() == "quit":
            break
        if question.lower() == "reset":
            history = []
            print("  ✓ History cleared.\n")
            continue

        answer = bible_query(
            user_question=question,
            tools=ALL_TOOLS,
            history=None if args.no_history else history,
            verbose=verbose,
        )

        print(f"\nA: {answer}\n")
        print("-" * 70 + "\n")

        if log_path:
            append_log(log_path, question, answer, backend)

        if not args.no_history:
            history.append({"role": "user",      "content": question})
            history.append({"role": "assistant", "content": answer})
            if len(history) > 16:
                history = history[-16:]


if __name__ == "__main__":
    main()
