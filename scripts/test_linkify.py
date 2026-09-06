from __future__ import annotations

"""
test_linkify.py — guard rails for verse / Strong's linkification.

    .venv/bin/python scripts/test_linkify.py

No pytest dependency (the venv has none); exits non-zero on failure.

Regression under test: linkify_bible_references() used to be non-idempotent.
Its '(?<!\\[)' look-behind only blocked the position right after '[', but every
Chinese full book name ends in another book's short code (以賽亞書 → 書 =
約書亞記), so a second pass re-matched at an interior offset and produced
nested links like [以賽亞[書11:1](…書…)](…賽…) — which Markdown will not render.
The second pass happened because linkified answers are replayed as history and
the model copied them back into its next answer.

The corpus regression needs logs/chat.db, which is gitignored — it is skipped
when the file is absent; the invariant checks always run.
"""

import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_bible_rag_v6_1 import (  # noqa: E402
    linkify_bible_references,
    linkify_strongs_numbers,
    _postprocess_answer,
)

failures: list[str] = []
NESTED = re.compile(r"\[[^\[\]]*\[")


def check(label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


def check_no_nesting(label: str, text: str) -> None:
    if NESTED.search(text):
        failures.append(f"{label}: nested Markdown link\n     {text!r}")


ISA = ("https://bible.fhl.net/new/read.php?chineses=%E8%B3%BD&chap=11"
       "&VERSION1=unv&TABFLAG=1&strongflag=1")

# ── basic linkification still works ───────────────────────────────────────────
check("plain citation", linkify_bible_references("以賽亞書11:1"), f"[以賽亞書11:1]({ISA})")
check("unknown book untouched", linkify_bible_references("偽經 3:16"), "偽經 3:16")

# ── idempotency: the actual defect ────────────────────────────────────────────
for label, raw in [
    ("以賽亞書 (尾字=書=約書亞記)", "與以賽亞書11:1的預言相通"),
    ("耶利米書",                    "耶利米書23:5-6"),
    ("以西結 (尾字=結)",            "以西結47:1 的活水"),
    ("哥林多前書",                  "保羅在哥林多前書1:10-13"),
    ("阿摩司書",                    "阿摩司書5:10 城門口"),
    ("撒迦利亞書",                  "撒迦利亞書14:8"),
    ("章-only form",                "羅馬書 8章"),
]:
    once = linkify_bible_references(raw)
    check(f"idempotent: {label}", linkify_bible_references(once), once)
    check_no_nesting(f"double pass: {label}", linkify_bible_references(once))

# ── self-healing: a link the model wrote by hand is normalised ────────────────
typo = ("與[以賽亞書11:1](https://bible.fhl.net/new/read.php?chieneses=賽&chap=11"
        "&VERSION1=unv&TABFLAG=1&strongflag=1)的預言")
check("model-written link repaired", linkify_bible_references(typo),
      f"與[以賽亞書11:1]({ISA})的預言")

# ── self-healing: unwind a nested link already stored in the corpus ───────────
nested = (f"與[以賽亞[書11:1](https://bible.fhl.net/new/read.php?chieneses=書&chap=11"
          f"&VERSION1=unv&TABFLAG=1&strongflag=1)]({ISA})的預言")
check("nested link repaired", linkify_bible_references(nested),
      f"與[以賽亞書11:1]({ISA})的預言")

# ── bare `[...]` brackets (model writes these) become one clean link ──────────
check("bare bracket citation", linkify_bible_references("註釋指出[以賽亞書11:1]的預言"),
      f"註釋指出[以賽亞書11:1]({ISA})的預言")
check("bare bracket strongs", linkify_strongs_numbers("字根 [SNH03709] 手掌"),
      "字根 [SNH03709](https://bible.fhl.net/new/s.php?N=1&k=3709) 手掌")
check("non-citation brackets untouched", linkify_bible_references("[註] 見下文"), "[註] 見下文")

# ── links that cannot be rebuilt from their label must survive ────────────────
LEGACY_SN = "[H5315](https://bible.fhl.net/new/s.php?N=0&k=05315&m=)"
check("legacy H-format link kept", linkify_strongs_numbers(LEGACY_SN), LEGACY_SN)
BARE = ("[34:9-10](https://bible.fhl.net/new/read.php?chineses=%E7%B5%90&chap=34"
        "&VERSION1=unv&TABFLAG=1&strongflag=1)")
check("bookless continuation kept", linkify_bible_references(BARE), BARE)
# …but its mistyped param is still repaired in place
check("mistyped param repaired in place",
      linkify_bible_references(BARE.replace("chineses=", "chieneses=")), BARE)

# ── nested pair whose inner label alone is not rebuildable (msg 592) ──────────
JN = ("https://bible.fhl.net/new/read.php?chineses=%E7%B4%84&chap=10"
      "&VERSION1=unv&TABFLAG=1&strongflag=1")
check("un-nest unrebuildable inner",
      linkify_bible_references(f"[約翰[福音10:12-13]({JN})]({JN})"),
      f"[約翰福音10:12-13]({JN})")

# ── protected regions are left alone ──────────────────────────────────────────
check("code span untouched", linkify_bible_references("`約翰福音 3:16`"), "`約翰福音 3:16`")
check("foreign link untouched",
      linkify_bible_references("[看這裡](https://example.com/約翰福音3:16)"),
      "[看這裡](https://example.com/約翰福音3:16)")
check("bare url untouched",
      linkify_bible_references("https://example.com/約翰福音3:16"),
      "https://example.com/約翰福音3:16")

# ── Strong's codes ────────────────────────────────────────────────────────────
SNG = "[SNG00026](https://bible.fhl.net/new/s.php?N=0&k=26)"
check("strongs padded", linkify_strongs_numbers("SNG26"), SNG)
check("strongs idempotent", linkify_strongs_numbers(SNG), SNG)
check("hebrew", linkify_strongs_numbers("SNH02617"),
      "[SNH02617](https://bible.fhl.net/new/s.php?N=1&k=2617)")

# ── whole pipeline ────────────────────────────────────────────────────────────
answer = "愛 (SNG00026) 見約翰福音 3:16，另參以賽亞書11:1。"
once = _postprocess_answer(answer)
check("pipeline idempotent", _postprocess_answer(once), once)
check_no_nesting("pipeline", once)

# ── corpus: every stored answer must repair to something clean and stable ─────
db = Path(__file__).resolve().parent.parent / "logs" / "chat.db"
if db.exists():
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dirty = 0
    for mid, content in conn.execute(
        "SELECT id, content FROM messages WHERE role = 'assistant'"
    ):
        if NESTED.search(content) or "chieneses" in content:
            dirty += 1
        fixed = _postprocess_answer(content)
        check_no_nesting(f"corpus msg {mid}", fixed)
        check(f"corpus msg {mid} stable", _postprocess_answer(fixed), fixed)
        if "chieneses" in fixed:
            failures.append(f"corpus msg {mid}: 'chieneses' survived repair")
    conn.close()
    print(f"corpus: {dirty} stored answers were corrupted, all repair clean")
else:
    print(f"corpus: skipped ({db} not present)")

if failures:
    print(f"\nFAILED ({len(failures)}):")
    for f in failures:
        print("  ✗", f)
    sys.exit(1)
print("linkify: all checks passed")
