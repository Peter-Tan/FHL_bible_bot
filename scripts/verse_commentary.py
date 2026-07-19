#!/usr/bin/env python3
"""
verse_commentary.py — Generate per-verse original-language commentary for a Bible chapter.

Usage:
    python verse_commentary.py 創19
    python verse_commentary.py Gen19
    python verse_commentary.py 約翰福音3
    python verse_commentary.py Rom 8

Behaviour:
  • Prints an abbreviation-hint table so you know every alias for the book.
  • Fetches the chapter from FHL to discover total verse count.
  • For each verse calls claude_bible_rag.bible_query() with the prompt:
        請針對{book}{ch}:{v}進行原文分析 請記得附上Strong number
        並針對這一節產生合適的註釋內容
  • Saves each verse to  output/<EngsCode><ch>/<EngsCode><ch>-<v>.txt
  • Already-existing files are skipped (safe to re-run after interruption).
  • Zips the finished folder to  output/<EngsCode><ch>.zip
"""

from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path

# ── Bootstrap path so siblings are importable ─────────────────────────────────
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from fhl_tools import (
    _BOOK_FALLBACK_LIST,
    _BOOK_TO_SHORT,
    _BOOK_TO_ENGS,
    _BOOK_TO_NUM,
    get_bible_chapter,
)
from claude_bible_rag import bible_query

# ── Secondary lookup tables built from the static fallback list ───────────────
_NUM_TO_INFO: dict[int, dict] = {}
_LC_TO_SHORT: dict[str, str] = {}   # lowercase English alias → zh_short

for _num, _engs, _full_en, _zh_short, _zh_full in _BOOK_FALLBACK_LIST:
    _NUM_TO_INFO[_num] = {
        "engs":    _engs,
        "full_en": _full_en,
        "zh_short": _zh_short,
        "zh_full":  _zh_full,
    }
    for _alias in (_engs, _full_en):
        _LC_TO_SHORT[_alias.lower()] = _zh_short


# ── Book resolution ───────────────────────────────────────────────────────────

def _resolve_book(raw: str) -> tuple[str, str, int]:
    """
    Map any book alias (Chinese full/short, English full/abbrev) to
    (zh_short, engs, book_number).  Raises ValueError if unknown.
    """
    # Direct lookup (covers zh_short, zh_full, engs, alt_engs as loaded)
    if raw in _BOOK_TO_SHORT:
        return _BOOK_TO_SHORT[raw], _BOOK_TO_ENGS[raw], _BOOK_TO_NUM[raw]

    # Case-insensitive English fallback
    lower = raw.lower()
    if lower in _LC_TO_SHORT:
        zh = _LC_TO_SHORT[lower]
        return zh, _BOOK_TO_ENGS[zh], _BOOK_TO_NUM[zh]

    raise ValueError(
        f"找不到書卷: {raw!r}\n"
        "支援格式範例: 創 / 創世記 / Gen / Genesis / 約 / 約翰福音 / John / Rom …"
    )


def parse_chapter_ref(raw: str) -> tuple[str, str, int, int]:
    """
    Parse a chapter-reference string like '創19', 'Gen 19', '約翰福音3', 'Rom8'
    into (zh_short, engs, book_number, chapter).
    """
    raw = raw.strip()
    # Split at the trailing digit(s); book name may itself contain digits (e.g. 1Cor)
    m = re.match(r'^(.+?)\s*(\d+)$', raw)
    if not m:
        raise ValueError(
            f"無法解析章節: {raw!r}\n"
            "格式: <書卷名><章數>，例如 創19 / Gen19 / 約翰福音3"
        )
    book_raw = m.group(1).strip()
    chapter  = int(m.group(2))
    zh_short, engs, num = _resolve_book(book_raw)
    return zh_short, engs, num, chapter


# ── Abbreviation hint display ─────────────────────────────────────────────────

def print_abbreviation_hint(zh_short: str, engs: str, book_num: int, chapter: int) -> None:
    info    = _NUM_TO_INFO.get(book_num, {})
    zh_full = info.get("zh_full", zh_short)
    full_en = info.get("full_en", engs)

    print()
    print("═" * 62)
    print("  書卷別名提示 (Book Abbreviation Reference)")
    print("═" * 62)
    print(f"  繁體全名   : {zh_full}")
    print(f"  中文簡稱   : {zh_short}")
    print(f"  英文全名   : {full_en}")
    print(f"  英文代碼   : {engs}  (FHL API 代碼)")
    print(f"  書卷編號   : {book_num} / 66")
    print()
    print(f"  章節輸入格式 (等效寫法):")
    print(f"    {zh_short}{chapter}  /  {engs}{chapter}  /  {full_en} {chapter}")
    print("═" * 62)
    print()


# ── Verse count ───────────────────────────────────────────────────────────────

def get_verse_count(zh_short: str, chapter: int) -> int:
    """Query FHL for the chapter and return number of verses."""
    data = get_bible_chapter(zh_short, chapter)
    if "error" in data:
        raise RuntimeError(f"FHL API 錯誤: {data['error']}")
    verses = data.get("verses", [])
    if not verses:
        raise RuntimeError(f"FHL 未返回 {zh_short}{chapter} 的節數 (章節可能不存在)")
    return len(verses)


# ── Single-verse query ────────────────────────────────────────────────────────

def query_verse(zh_short: str, chapter: int, verse: int) -> str:
    prompt = (
        f"請針對{zh_short}{chapter}:{verse}進行原文分析 "
        f"請記得附上Strong number 並針對這一節產生合適的註釋內容"
    )
    return bible_query(prompt, verbose=True)


# ── Main chapter processor ────────────────────────────────────────────────────

def process_chapter(zh_short: str, engs: str, book_num: int, chapter: int) -> None:
    print_abbreviation_hint(zh_short, engs, book_num, chapter)

    # ── 1. Get total verse count ──────────────────────────────────────────────
    print(f"正在從 FHL API 取得 {zh_short}{chapter} 的節數 ...", flush=True)
    total = get_verse_count(zh_short, chapter)
    print(f"共 {total} 節\n")

    # ── 2. Prepare output directory ───────────────────────────────────────────
    chapter_tag = f"{engs}{chapter}"                      # e.g. "Gen19"
    out_dir     = _SCRIPTS / "output" / chapter_tag
    zip_path    = _SCRIPTS / "output" / f"{chapter_tag}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"輸出資料夾 : {out_dir}")
    print(f"壓縮目標   : {zip_path}")
    print()

    # ── 3. Loop through every verse ───────────────────────────────────────────
    for verse in range(1, total + 1):
        out_file = out_dir / f"{chapter_tag}-{verse}.txt"

        if out_file.exists():
            print(f"[{verse:>3}/{total}] ⏭  {out_file.name} 已存在，跳過")
            continue

        print(f"[{verse:>3}/{total}] ▶  {zh_short}{chapter}:{verse} ...", flush=True)
        t0 = time.time()
        try:
            result = query_verse(zh_short, chapter, verse)
        except Exception as exc:
            result = f"[ERROR] {exc}"
            print(f"         ✗ 錯誤: {exc}")

        elapsed = time.time() - t0
        header = (
            f"# {zh_short}{chapter}:{verse}　原文分析與註釋\n"
            f"# 生成時間: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# 耗時: {elapsed:.1f}s\n\n"
        )
        out_file.write_text(header + result, encoding="utf-8")
        print(f"         ✓ 已儲存 → {out_file.name}  ({elapsed:.1f}s)\n")

        # Polite pause so we don't hammer the API back-to-back
        if verse < total:
            time.sleep(2)

    # ── 4. Zip the finished folder ────────────────────────────────────────────
    print(f"\n壓縮 {chapter_tag}/ → {zip_path.name} ...", flush=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for txt in sorted(out_dir.glob("*.txt")):
            zf.write(txt, arcname=f"{chapter_tag}/{txt.name}")
    kb = zip_path.stat().st_size // 1024
    print(f"✓ 壓縮完成: {zip_path}  ({kb} KB)")
    print(f"\n全部完成！共處理 {zh_short}{chapter} 第 1–{total} 節。")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    raw = " ".join(sys.argv[1:])
    try:
        zh_short, engs, book_num, chapter = parse_chapter_ref(raw)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    try:
        process_chapter(zh_short, engs, book_num, chapter)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
