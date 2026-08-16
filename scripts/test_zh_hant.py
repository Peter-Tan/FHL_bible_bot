from __future__ import annotations

"""
test_zh_hant.py — guard rails for the simplified→Traditional table.

    .venv/bin/python scripts/test_zh_hant.py

No pytest dependency (the venv has none); exits non-zero on failure. The
corpus regression needs logs/chat.db, which is gitignored — it is skipped
when the file is absent, the invariant checks always run.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zh_hant import simplified_chars, to_traditional  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


# ── must convert: the real defects found in logs/chat.db ──────────────────────
check("msg 426", to_traditional("核心问题"), "核心問題")
check("msg 488", to_traditional("强调绝对式+限定动词"), "強調絕對式+限定動詞")
check(
    "msg 490",
    to_traditional("①银子作为在众人眼前证明撒拉清白；②使人「视而不见」此事之尴尬"),
    "①銀子作為在眾人眼前證明撒拉清白；②使人「視而不見」此事之尷尬",
)
check("msg 552", to_traditional("必須被完全內化才能被忠心地传讲"), "必須被完全內化才能被忠心地傳講")

# ── must NOT touch: correct Traditional text ─────────────────────────────────
# Big5 characters full OpenCC would "fix" (吃→喫, 群→羣, 才→纔, 里→裏, 台→臺).
INTACT = "他們吃了那群羊，才到山裡去，站在台上，秘密地游到山峰"
check("Big5 traditional untouched", to_traditional(INTACT), INTACT)

# Traditional variants outside Big5 — 和合本 quotes them verbatim.
for variant in ("裏", "麽", "衆"):
    check(f"variant {variant} untouched", to_traditional(variant), variant)

# 祢 is the Christian honorific, not a simplified form (KEEP list).
check("祢 untouched", to_traditional("願祢的旨意成就"), "願祢的旨意成就")

# Markdown links and Strong's codes are ASCII — conversion must not disturb
# them (it runs before linkify, so only raw URLs can be present).
URL = "[SNH02617](https://bible.fhl.net/new/s.php?N=1&k=2617)"
check("url untouched", to_traditional(URL), URL)

check("simplified_chars", simplified_chars("这项问题"), ["这", "项", "问", "题"])
check("simplified_chars clean", simplified_chars("這項問題"), [])

# ── corpus regression: exactly 8 assistant answers, no collateral ────────────
db = Path(__file__).resolve().parent.parent / "logs" / "chat.db"
if db.exists():
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    altered = [
        (mid, role)
        for mid, role, content in conn.execute("SELECT id, role, content FROM messages")
        if to_traditional(content) != content
    ]
    conn.close()
    ids = sorted(mid for mid, role in altered if role == "assistant")
    check("assistant answers altered", ids, [426, 450, 488, 490, 494, 496, 526, 552])
    print(f"corpus: {len(altered)} of all messages altered, {len(ids)} of them answers")
else:
    print(f"corpus: skipped ({db} not present)")

if failures:
    print(f"\nFAILED ({len(failures)}):")
    for f in failures:
        print("  ✗", f)
    sys.exit(1)
print("zh_hant: all checks passed")
