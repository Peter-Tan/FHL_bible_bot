from __future__ import annotations

"""
repair_verse_links.py — one-off repair of verse / Strong's links in chat.db.

    .venv/bin/python scripts/repair_verse_links.py            # dry run
    .venv/bin/python scripts/repair_verse_links.py --apply    # write

Why: linkify_bible_references() used to be non-idempotent (its '(?<!\\[)'
look-behind did not stop the regex re-matching at an interior offset of an
already-linked citation, because 以賽亞書 ends in 書 = 約書亞記). Linkified
answers are replayed to the model as history, the model copied those links
into its next answer, and the second pass produced nested links —
[以賽亞[書11:1](…書…)](…賽…) — which Markdown will not render. The model also
began hand-copying the URLs and mistyping 'chineses=' as 'chieneses=', which
read.php ignores, so those links opened nothing and the new-UI rewrite in
web/src/lib/verseLinks.ts fell through as well.

The engine fix makes linkification idempotent and self-healing, so this script
just re-applies it to the answers that are actually broken: nested links are
flattened, hand-copied URLs collapsed back to plain citations and rebuilt from
the book table, and a mistyped param on a link that carries no book name (a
bare '[34:9-10]' continuation) repaired in place. Links that cannot be rebuilt
from their label — legacy '[H5315](…s.php…)' — are left untouched rather than
unwrapped, which would delete them. Safe to run more than once.

Backs up chat.db (via the SQLite backup API, so WAL content is included)
before writing.
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from claude_bible_rag_v6_1 import (  # noqa: E402
    linkify_bible_references,
    linkify_strongs_numbers,
)

DB_PATH = ROOT / "logs" / "chat.db"
NESTED_RE = re.compile(r"\[[^\[\]]*\[")
FHL_LINK_RE = re.compile(
    r"\[([^\[\]]*)\]\(\s*https?://bible\.fhl\.net/new/(?:read|s)\.php[^)\s]*\)"
)


def repair(text: str) -> str:
    """Link repair only.

    Deliberately NOT _postprocess_answer(): that also runs to_traditional()
    and would rebuild every link in the corpus, stripping the '&sec=' anchor
    from ~880 links written by the older v2/v3 engines and adding ~2100 links
    to answers that never had them. This migration only unwinds broken links
    and rebuilds them; stored prose is left byte-identical.
    """
    return linkify_strongs_numbers(linkify_bible_references(text))


def is_broken(text: str) -> bool:
    """Nested link (unrenderable) or a hand-copied URL with a mistyped param."""
    return bool(NESTED_RE.search(text)) or "chieneses" in text


def plain(text: str) -> str:
    """Text with all FHL links unwrapped — the content-preservation invariant."""
    prev = None
    while prev != text:
        prev = text
        text = FHL_LINK_RE.sub(lambda m: m.group(1), text)
    return text


def backup(db: Path) -> Path:
    dest = db.with_name(f"{db.stem}.backup-{datetime.now():%Y%m%d_%H%M%S}.db")
    src = sqlite3.connect(db)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"✗ {args.db} not found")
        return 1

    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT id, content FROM messages WHERE role = 'assistant' ORDER BY id"
    ).fetchall()

    changes: list[tuple[int, str]] = []
    nested_before = typo_before = 0
    for mid, content in rows:
        if NESTED_RE.search(content):
            nested_before += 1
        if "chieneses" in content:
            typo_before += 1
        if not is_broken(content):
            continue
        fixed = repair(content)
        if fixed != content:
            changes.append((mid, fixed))

    print(f"scanned  : {len(rows)} assistant messages in {args.db}")
    print(f"broken   : {nested_before} with nested links, {typo_before} with 'chieneses='")
    print(f"to repair: {len(changes)} messages")

    for mid, fixed in changes:
        assert not NESTED_RE.search(fixed), f"msg {mid} still nested"
        assert "chieneses" not in fixed, f"msg {mid} still has typo"
        assert repair(fixed) == fixed, f"msg {mid} not stable"
    print("verified : repaired messages are nesting-free and idempotent")

    # Content-preservation: with every FHL link unwrapped, the prose must be
    # unchanged apart from the stray `[...]` brackets the model wrote by hand.
    for mid, fixed in changes:
        before = plain(dict(rows)[mid]).replace("[", "").replace("]", "")
        after = plain(fixed).replace("[", "").replace("]", "")
        assert before == after, f"msg {mid} prose changed"
    print("verified : prose byte-identical (links only)")

    if not args.apply:
        print("\ndry run — rerun with --apply to write")
        conn.close()
        return 0

    dest = backup(args.db)
    print(f"backup   : {dest}")
    with conn:
        conn.executemany("UPDATE messages SET content = ? WHERE id = ?",
                         [(f, m) for m, f in changes])
    conn.close()
    print(f"✓ repaired {len(changes)} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
