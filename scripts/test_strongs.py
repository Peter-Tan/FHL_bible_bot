"""
test_strongs.py — guard rails for Strong's-number argument parsing.

    .venv/bin/python scripts/test_strongs.py           # offline only
    .venv/bin/python scripts/test_strongs.py --live    # + real FHL lookups

No pytest dependency; exits non-zero on failure.

Regression under test: lookup_strongs('SNH01285') (the SNH#####/SNG#####
form the engines' prompts teach the model) returned FHL's generic SN 00000
entry instead of H1285, so every v8 dictionary lookup came back empty and the
model fabricated or omitted Strong's numbers (2026-11-08 eval, word_study).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fhl_tools import _split_strongs, get_word_analysis, lookup_strongs  # noqa: E402

CASES = [
    # (input, default_lang, expected)
    ("H25", "H", ("H", "25")),
    ("SNH00025", "H", ("H", "25")),
    ("snh01285", "H", ("H", "1285")),
    (" G26 ", "H", ("G", "26")),
    ("SNG00026", "H", ("G", "26")),
    ("1285", "H", ("H", "1285")),   # bare → tool's default language
    ("26", "G", ("G", "26")),
    ("SNH00000", "H", ("H", "0")),
]

failures = 0
for raw, default, want in CASES:
    got = _split_strongs(raw, default)
    if got != want:
        failures += 1
        print(f"FAIL _split_strongs({raw!r}, {default!r}) = {got}, want {want}")

if "--live" in sys.argv:
    for raw, want_sn in [("H25", "00025"), ("SNH00025", "00025"),
                         ("G26", "00026"), ("SNG00026", "00026"),
                         ("SNH01285", "01285")]:
        sns = [e["sn"] for e in lookup_strongs(raw).get("entries", [])]
        if want_sn not in sns:
            failures += 1
            print(f"FAIL lookup_strongs({raw!r}) → {sns}, want {want_sn}")

    # get_word_analysis must expose real Strong's codes (it used to return the
    # Chinese gloss under 'strongs'), and they must round-trip to lookup_strongs.
    # (Matched by gloss, not lemma: FHL's Greek accents are not NFC-stable.)
    for book, chap, verse, gloss, want in [("創世記", 22, 2, "說、回答、承諾、吩咐", "SNH00559"),
                                           ("約翰福音", 3, 16, "愛", "SNG00025")]:
        words = get_word_analysis(book, chap, verse).get("words", [])
        got = next((w["strongs"] for w in words if w["gloss"] == gloss), None)
        if got != want:
            failures += 1
            print(f"FAIL get_word_analysis({book} {chap}:{verse}) {gloss} → {got}, want {want}")
        elif want[3:] not in [e["sn"] for e in lookup_strongs(got).get("entries", [])]:
            failures += 1
            print(f"FAIL lookup_strongs({got!r}) did not return {want[3:]}")

print("OK" if not failures else f"{failures} failure(s)")
sys.exit(1 if failures else 0)
