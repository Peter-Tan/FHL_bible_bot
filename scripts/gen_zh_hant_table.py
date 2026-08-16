from __future__ import annotations

"""
gen_zh_hant_table.py — regenerate the character table used by zh_hant.py.

Run manually, NOT at runtime; the output is committed as scripts/zh_hant.py so
the server has no OpenCC dependency:

    .venv/bin/python -m pip install opencc-python-reimplemented
    .venv/bin/python scripts/gen_zh_hant_table.py > /tmp/table.txt

then paste /tmp/table.txt over the `_PAIRS` literal in zh_hant.py (the module
docstring around it is hand-maintained) and re-run scripts/test_zh_hant.py.

Selection rule (deliberately narrow — see zh_hant.py for the rationale):

  a character is included iff
    1. it CANNOT be encoded in Big5   → it is not a Big5 Traditional character,
    2. OpenCC t2s leaves it unchanged → it is not on the Traditional side of
       the dictionary either, i.e. not a Traditional variant, and
    3. OpenCC s2tw maps it to exactly one different character.

Condition (1) is what keeps the table from touching the ~114 messages in
logs/chat.db where full OpenCC conversion would "fix" perfectly good
Traditional text (吃→喫, 群→羣, 才→纔, 里→裏, 台→臺 … all Big5, all excluded).

Condition (2) catches Traditional variants that Big5 happens not to encode —
裏 (the 裡/裏 pair; 和合本 uses both and quotations must stay verbatim), 麽, 衆.
Without it the table rewrote 裏→裡 in 10 messages, including quoted scripture.

s2tw — not s2t — because s2t emits mainland-Traditional variants where Taiwan
uses another form: 为→爲 (want 為), 众→衆 (want 眾), 启→啓 (want 啟).
"""

import sys

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - manual tool
    sys.exit("need: .venv/bin/python -m pip install opencc-python-reimplemented")

# Simplified-looking characters that are legitimate Traditional usage and must
# never be rewritten. 祢 is the Christian honorific second person for God
# (「願祢的旨意成就」); OpenCC would turn it into the unrelated 禰 (ancestral
# shrine). It appears 3x in logs/chat.db, every time correctly.
KEEP = "祢"


def build() -> dict[str, str]:
    s2tw, t2s = OpenCC("s2tw"), OpenCC("t2s")
    table: dict[str, str] = {}
    for cp in range(0x4E00, 0xA000):  # CJK Unified Ideographs
        ch = chr(cp)
        if ch in KEEP:
            continue
        try:
            ch.encode("big5")
            continue  # a Big5 Traditional character — leave alone
        except UnicodeEncodeError:
            pass
        if t2s.convert(ch) != ch:
            continue  # a Traditional variant outside Big5 (裏, 麽, 衆)
        trad = s2tw.convert(ch)
        if trad != ch and len(trad) == 1:
            table[ch] = trad
    return table


if __name__ == "__main__":
    table = build()
    pairs = "".join(s + t for s, t in sorted(table.items()))
    print(f"# {len(table)} pairs", file=sys.stderr)
    for i in range(0, len(pairs), 72):
        print(f'    "{pairs[i:i + 72]}"')
