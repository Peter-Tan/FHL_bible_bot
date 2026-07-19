"""
fhl_tools.py — 13 Bible tools backed by the 信望愛站 (FHL) JSON API
==================================================================
Endpoints are the real ones served under https://bible.fhl.net/json/*.php.
Book names are auto-normalised: the model may pass '約翰福音', '約', 'John',
or 'Jn' — all get mapped to the short Chinese / English codes the API wants.

Tool registry:
    ALL_TOOLS  — list of all 13 tool functions (in declaration order)
    TOOL_MAP   — dict mapping tool name → function, used for dispatch

Manual selection helpers:
    list_tools_menu()          — print a numbered menu
    select_tools_interactive() — prompt user to pick a subset
"""

import requests
from typing import Optional

FHL_BASE = "https://bible.fhl.net/json"


def _get(endpoint: str, params: dict) -> dict:
    """Shared HTTP GET wrapper. Auto-appends .php if missing."""
    if not endpoint.endswith(".php") and not endpoint.endswith(".html"):
        endpoint = endpoint + ".php"
    try:
        r = requests.get(f"{FHL_BASE}/{endpoint}", params=params, timeout=10)
        r.raise_for_status()
        # Some endpoints (listall.html) return CSV, not JSON.
        ct = r.headers.get("Content-Type", "")
        if "html" in ct or endpoint.endswith(".html"):
            r.encoding = r.apparent_encoding or "utf-8"
            return {"raw_text": r.text}
        return r.json()
    except Exception as e:
        return {"error": str(e), "endpoint": endpoint, "params": params}


# ── Book name normalisation ────────────────────────────────────────────────────
# listall.html returns rows like:  1,Gen,Genesis,創,創世記,Ge
#                                  idx, engs, full_en, zh_short, zh_full, alt_engs

_BOOK_FALLBACK_LIST = [
    # (num, engs, full_en, zh_short, zh_full)
    (1,"Gen","Genesis","創","創世記"), (2,"Ex","Exodus","出","出埃及記"),
    (3,"Lev","Leviticus","利","利未記"), (4,"Num","Numbers","民","民數記"),
    (5,"Deut","Deuteronomy","申","申命記"), (6,"Josh","Joshua","書","約書亞記"),
    (7,"Judg","Judges","士","士師記"), (8,"Ruth","Ruth","得","路得記"),
    (9,"1Sam","First Samuel","撒上","撒母耳記上"), (10,"2Sam","Second Samuel","撒下","撒母耳記下"),
    (11,"1Kin","First Kings","王上","列王紀上"), (12,"2Kin","Second Kings","王下","列王紀下"),
    (13,"1Chr","First Chronicles","代上","歷代志上"), (14,"2Chr","Second Chronicles","代下","歷代志下"),
    (15,"Ezra","Ezra","拉","以斯拉記"), (16,"Neh","Nehemiah","尼","尼希米記"),
    (17,"Esth","Esther","斯","以斯帖記"), (18,"Job","Job","伯","約伯記"),
    (19,"Ps","Psalms","詩","詩篇"), (20,"Prov","Proverbs","箴","箴言"),
    (21,"Eccl","Ecclesiastes","傳","傳道書"), (22,"Song","Song of Solomon","歌","雅歌"),
    (23,"Isa","Isaiah","賽","以賽亞書"), (24,"Jer","Jeremiah","耶","耶利米書"),
    (25,"Lam","Lamentations","哀","耶利米哀歌"), (26,"Ezek","Ezekiel","結","以西結書"),
    (27,"Dan","Daniel","但","但以理書"), (28,"Hos","Hosea","何","何西阿書"),
    (29,"Joel","Joel","珥","約珥書"), (30,"Amos","Amos","摩","阿摩司書"),
    (31,"Obad","Obadiah","俄","俄巴底亞書"), (32,"Jon","Jonah","拿","約拿書"),
    (33,"Mic","Micah","彌","彌迦書"), (34,"Nah","Nahum","鴻","那鴻書"),
    (35,"Hab","Habakkuk","哈","哈巴谷書"), (36,"Zeph","Zephaniah","番","西番雅書"),
    (37,"Hag","Haggai","該","哈該書"), (38,"Zech","Zechariah","亞","撒迦利亞書"),
    (39,"Mal","Malachi","瑪","瑪拉基書"),
    (40,"Matt","Matthew","太","馬太福音"), (41,"Mark","Mark","可","馬可福音"),
    (42,"Luke","Luke","路","路加福音"), (43,"John","John","約","約翰福音"),
    (44,"Acts","Acts","徒","使徒行傳"), (45,"Rom","Romans","羅","羅馬書"),
    (46,"1Cor","First Corinthians","林前","哥林多前書"), (47,"2Cor","Second Corinthians","林後","哥林多後書"),
    (48,"Gal","Galatians","加","加拉太書"), (49,"Eph","Ephesians","弗","以弗所書"),
    (50,"Phil","Philippians","腓","腓立比書"), (51,"Col","Colossians","西","歌羅西書"),
    (52,"1Thess","First Thessalonians","帖前","帖撒羅尼迦前書"), (53,"2Thess","Second Thessalonians","帖後","帖撒羅尼迦後書"),
    (54,"1Tim","First Timothy","提前","提摩太前書"), (55,"2Tim","Second Timothy","提後","提摩太後書"),
    (56,"Titus","Titus","多","提多書"), (57,"Phlm","Philemon","門","腓利門書"),
    (58,"Heb","Hebrews","來","希伯來書"), (59,"Jas","James","雅","雅各書"),
    (60,"1Pet","First Peter","彼前","彼得前書"), (61,"2Pet","Second Peter","彼後","彼得後書"),
    (62,"1John","First John","約一","約翰一書"), (63,"2John","Second John","約二","約翰二書"),
    (64,"3John","Third John","約三","約翰三書"), (65,"Jude","Jude","猶","猶大書"),
    (66,"Rev","Revelation","啟","啟示錄"),
]

_BOOK_FALLBACK = {}
for _num, _engs, _full_en, _zh_short, _zh_full in _BOOK_FALLBACK_LIST:
    for _key in (_engs, _full_en, _zh_short, _zh_full):
        _BOOK_FALLBACK[_key] = (_engs, _zh_short, _num)

_BOOK_TO_ENGS:  dict[str, str] = {}
_BOOK_TO_SHORT: dict[str, str] = {}
_BOOK_TO_NUM:   dict[str, int] = {}

def _load_book_table() -> None:
    """Fetch listall.html once at import time; fall back to static map on failure."""
    try:
        r = requests.get(f"{FHL_BASE}/listall.html", timeout=5)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        for line in r.text.splitlines():
            cols = [c.strip() for c in line.split(",")]
            if len(cols) < 5 or not cols[0].isdigit():
                continue
            num_str, engs, full_en, zh_short, zh_full, *rest = cols
            num = int(num_str)
            alt_engs = rest[0] if rest else ""
            for key in (engs, full_en, zh_short, zh_full, alt_engs):
                if key:
                    _BOOK_TO_ENGS[key]  = engs
                    _BOOK_TO_SHORT[key] = zh_short
                    _BOOK_TO_NUM[key]   = num
    except Exception:
        for key, (engs, short, num) in _BOOK_FALLBACK.items():
            _BOOK_TO_ENGS[key]  = engs
            _BOOK_TO_SHORT[key] = short
            _BOOK_TO_NUM[key]   = num

_load_book_table()
if len(_BOOK_TO_SHORT) < 100:
    print(f"⚠ FHL book table: using fallback ({len(_BOOK_TO_SHORT)} entries)")
else:
    print(f"✓ FHL book table: loaded {len(_BOOK_TO_SHORT)} entries from listall.html")


def _to_short_chinese(book: str) -> str:
    """Normalise any book name to the short Chinese code (e.g. '約翰福音' → '約')."""
    return _BOOK_TO_SHORT.get(book, book)


def _to_engs(book: str) -> str:
    """Normalise any book name to the FHL English code (e.g. '約翰福音' → 'John')."""
    return _BOOK_TO_ENGS.get(book, book)


# ── 1. Verse lookup ────────────────────────────────────────────────────────────

def get_bible_verse(book: str, chapter: int, verse: int, version: str = "unv") -> dict:
    """
    Retrieve a single Bible verse.

    Args:
        book: Book name — full Chinese (e.g. '約翰福音'), short Chinese ('約'),
              or English ('John'). Auto-normalised before the API call.
        chapter: Chapter number (1-based).
        verse: Verse number (1-based).
        version: FHL version code. Common codes:
                 'unv' (和合本, default), 'rcuv' (和合本修訂版),
                 'ncv' (新譯本), 'tcv' (現代中文譯本),
                 'kjv' (KJV English), 'wcb' (環球譯本).
                 Use list_bible_versions() to see all 87 codes.

    Returns:
        JSON dict with 'verses' list, each having 'chap', 'sec', 'text'.
    """
    data = _get("qb", {
        "chineses": _to_short_chinese(book),
        "chap": chapter, "sec": verse, "version": version, "gb": 0,
    })
    if "error" in data:
        return data
    return {"verses": [
        {"chap": r["chap"], "sec": r["sec"], "text": r["bible_text"]}
        for r in data.get("record", [])
    ]}


# ── 2. Chapter lookup ──────────────────────────────────────────────────────────

def get_bible_chapter(book: str, chapter: int, version: str = "unv") -> dict:
    """
    Retrieve all verses of an entire Bible chapter.

    Args:
        book: Book name in full Chinese, short Chinese, or English.
        chapter: Chapter number (1-based).
        version: Version code (see get_bible_verse for common codes).

    Returns:
        JSON dict with a 'record' list — one entry per verse.
    """
    data = _get("qb", {
        "chineses": _to_short_chinese(book),
        "chap": chapter, "version": version, "gb": 0,
    })
    if "error" in data:
        return data
    return {"book": _to_short_chinese(book), "chap": chapter, "verses": [
        {"sec": r["sec"], "text": r["bible_text"]}
        for r in data.get("record", [])
    ]}


# ── 3. Verse citation / cross-reference ────────────────────────────────────────

def query_verse_citation(reference: str, version: str = "unv") -> dict:
    """
    Look up verses by a citation string, including ranges.

    Args:
        reference: Citation like '約3:16', '約3:16-18', '羅8:28-30', 'John 3:16'.
                   Supports book abbreviations, chapter:verse, and verse ranges.
        version: Version code.

    Returns:
        JSON dict with 'record' list of matched verses.
    """
    data = _get("qsb", {"qstr": reference, "version": version, "gb": 0})
    if "error" in data:
        return data
    return {"verses": [
        {"book": r.get("chineses", ""), "chap": r["chap"], "sec": r["sec"], "text": r["bible_text"]}
        for r in data.get("record", [])
    ]}


# ── 4. Advanced search ─────────────────────────────────────────────────────────

def search_bible_advanced(
    keyword: str,
    version: str = "unv",
    limit: int = 10,
    book_range: Optional[str] = None,
    testament: Optional[str] = None,
) -> dict:
    """
    Full-text keyword search across the Bible.

    Use proactively when a user raises a theological theme — search for
    related passages even before being explicitly asked.

    Args:
        keyword: Search term or phrase (Chinese or English).
        version: Version code to search within.
        limit: Max results (default 10).
        book_range: Optional book short code to restrict scope, e.g. '約'.
                    Leave None for whole-Bible search.
        testament: 'OT' (舊約), 'NT' (新約), or None for both. Maps to
                   RANGE=OT/NT on the FHL server.

    Returns:
        JSON dict with 'record' list of matching verse dicts (each with
        'chineses','engs','chap','sec','bible_text').
    """
    params: dict = {"q": keyword, "VERSION": version, "limit": limit, "gb": 0}
    if book_range:
        book_num = _BOOK_TO_NUM.get(book_range) or _BOOK_TO_NUM.get(_to_short_chinese(book_range))
        if book_num:
            params["RANGE"] = 3
            params["range_bid"] = book_num
            params["range_eid"] = book_num
    elif testament == "NT":
        params["RANGE"] = 1
    elif testament == "OT":
        params["RANGE"] = 2
    data = _get("se", params)
    if "error" in data:
        return data
    return {"keyword": keyword, "results": [
        {"book": r.get("chineses", ""), "chap": r["chap"], "sec": r["sec"], "text": r["bible_text"]}
        for r in data.get("record", [])
    ]}


# ── 5. Original word analysis ──────────────────────────────────────────────────

def get_word_analysis(book: str, chapter: int, verse: int) -> dict:
    """
    Word-by-word original language (Hebrew/Greek) analysis for a verse.
    Returns lemma text and Strong's links. Use whenever the user asks about
    the meaning of a specific word or when exegetical depth is needed.

    Args:
        book: Book name (any form — normalised to English internally).
        chapter: Chapter number.
        verse: Verse number.

    Returns:
        JSON dict with 'record' list. Each entry has 'word' (original text).
    """
    data = _get("qp", {
        "engs": _to_engs(book),
        "chap": chapter, "sec": verse, "gb": 0,
    })
    if "error" in data:
        return data
    return {"words": [
        {"word": r.get("word", ""), "strongs": r.get("exp", "")}
        for r in data.get("record", [])
    ]}


# ── 6. Strong's dictionary lookup ──────────────────────────────────────────────

def lookup_strongs(strongs_number: str) -> dict:
    """
    Strong's Concordance entry for a Hebrew or Greek word.
    Always follow up get_word_analysis by calling this on key Strong's numbers.

    Args:
        strongs_number: With language prefix.
                        Greek NT: 'G' + number (e.g. 'G25' = ἀγαπάω, agapaō).
                        Hebrew OT: 'H' + number (e.g. 'H430' = אֱלֹהִים, elohim).

    Returns:
        JSON dict with 'record' list containing 'sn' and 'dic_text'
        (the dictionary entry body).
    """
    s = strongs_number.strip().upper()
    # sd.php: N=0 → Greek (NT), N=1 → Hebrew (OT)
    lang_code = 0 if s.startswith("G") else 1
    num = s[1:].lstrip("0") or "0"
    data = _get("sd", {"N": lang_code, "k": num, "gb": 0})
    if "error" in data:
        return data
    return {"entries": [
        {"sn": r.get("sn", ""), "definition": r.get("dic_text", ""), "orig": r.get("orig", "")}
        for r in data.get("record", [])
    ]}


# ── 7. Strong's occurrence search ──────────────────────────────────────────────

def search_strongs_occurrences(
    strongs_number: str,
    version: str = "unv",
    limit: int = 20,
) -> dict:
    """
    Find all verses containing a specific Strong's word.
    Traces how a Greek/Hebrew term is used across the canon.

    Args:
        strongs_number: e.g. 'G26' (ἀγάπη, agape), 'H2617' (חֶסֶד, hesed).
        version: Version for the verse text.
        limit: Max occurrences (default 20).

    Returns:
        JSON dict with 'record' list of verses.
    """
    # FHL's se.php wants the BARE digits (no G/H prefix) with orig=1.
    # Letter prefix is inferred from RANGE (NT for Greek, OT for Hebrew).
    s = strongs_number.strip().upper()
    num = s[1:].lstrip("0") or "0" if s.startswith(("G", "H")) else s
    params = {"q": num, "orig": 1, "VERSION": version, "limit": limit, "gb": 0}
    if s.startswith("G"):
        params["RANGE"] = 1
    elif s.startswith("H"):
        params["RANGE"] = 2
    data = _get("se", params)
    if "error" in data:
        return data
    return {"strongs": s, "occurrences": [
        {"book": r.get("chineses", ""), "chap": r["chap"], "sec": r["sec"], "text": r["bible_text"]}
        for r in data.get("record", [])
    ]}


# ── 8. Commentary retrieval ────────────────────────────────────────────────────

def get_commentary(book: str, chapter: int, verse: int,
                   commentary_id: Optional[str] = None) -> dict:
    """
    Commentary notes for a specific Bible verse or passage.
    Always call for exegesis questions, theological debates, or 'what does
    this mean' — even when commentary isn't explicitly requested.

    Args:
        book: Book name (any form).
        chapter: Chapter number.
        verse: Verse number.
        commentary_id: Optional commentary book-name filter (maps to 'book' param).

    Returns:
        JSON dict with 'record' list containing 'title', 'book_name',
        and 'com_text' (the commentary body).
    """
    params: dict = {"engs": _to_engs(book), "chap": chapter, "sec": verse, "gb": 0}
    if commentary_id:
        params["book"] = commentary_id
    data = _get("sc", params)
    if "error" in data:
        return data
    return {"commentaries": [
        {"title": r.get("title", ""), "source": r.get("book_name", ""), "text": r.get("com_text", "")}
        for r in data.get("record", [])
    ]}


# ── 9. List commentaries (no dedicated FHL endpoint) ───────────────────────────

def list_commentaries() -> dict:
    """
    List commentary collections accessible via FHL.
    NOTE: FHL has no dedicated list endpoint; these are the known built-in
    commentaries that ship with sc.php / ssc.php.

    Returns:
        Dict with 'commentaries' list, each entry having 'id', 'name',
        'language'. Use the 'id' as the 'commentary_id' / 'book' argument
        to get_commentary or search_commentary.
    """
    return {
        "commentaries": [
            {"id": None,              "name": "信望愛站註釋 (預設)",    "language": "zh-tw"},
            {"id": "新舊約輔讀",       "name": "新舊約輔讀",             "language": "zh-tw"},
            {"id": "活石新約聖經註釋", "name": "活石新約聖經註釋",        "language": "zh-tw"},
            {"id": "丁道爾聖經註釋",   "name": "丁道爾聖經註釋 (Tyndale)", "language": "zh-tw"},
        ],
        "note": "Pass the 'id' string as commentary_id / 'book' to narrow results.",
    }


# ── 10. Commentary search ──────────────────────────────────────────────────────

def search_commentary(keyword: str, commentary_id: Optional[str] = None) -> dict:
    """
    Full-text search within Bible commentaries.
    Use for thematic or doctrinal questions — find commentary passages on the
    topic before formulating your answer.

    Args:
        keyword: Search term (Chinese or English).
        commentary_id: Optional commentary name to restrict search
                       (see list_commentaries).

    Returns:
        JSON dict with 'record' list of matched commentary passages.
    """
    params: dict = {"key": keyword, "gb": 0}
    if commentary_id:
        params["book"] = commentary_id
    data = _get("ssc", params)
    if "error" in data:
        return data
    return {"results": [
        {"title": r.get("title", ""), "source": r.get("book_name", ""), "text": r.get("com_text", "")}
        for r in data.get("record", [])
    ]}


# ── 11. Topic study ────────────────────────────────────────────────────────────

def get_topic_study(topic: str, language: str = "zh-tw") -> dict:
    """
    Structured topic study — themed verses and notes on a Biblical subject.
    NOTE: FHL's topic index is English-keyed (e.g. 'Love', 'Grace', 'Faith',
    'Holy Spirit'). Chinese topic names may return 0 results; retry in English
    if so.

    Args:
        topic: Topic name, preferably English (e.g. 'Love', 'Holy Spirit').
        language: 'zh-tw' or 'en'.

    Returns:
        JSON dict with 'record' list of topics and verse references.
    """
    data = _get("st", {
        "keyword": topic,
        "gb": 0 if language.startswith("zh") else 1,
    })
    if "error" in data:
        return data
    return {"topic": topic, "entries": data.get("record", [])}


# ── 12. List Bible versions ────────────────────────────────────────────────────

def list_bible_versions() -> dict:
    """
    List all Bible translations available through the FHL API (87 total).
    Call when the user asks what's available, or to verify a version code.

    Returns:
        JSON dict with 'record' list. Each entry has 'book' (the version
        code to pass to other tools) and 'cname' (display name).
    """
    data = _get("ab", {"gb": 0})
    if "error" in data:
        return data
    return {"versions": [
        {"code": r.get("book", ""), "name": r.get("cname", "")}
        for r in data.get("record", [])
    ]}


# ── 13. Book list ──────────────────────────────────────────────────────────────

def get_book_list(version: str = "unv") -> dict:
    """
    List of Bible books — book numbers, English/Chinese names, short codes.

    Args:
        version: Bible version code (accepted for future compatibility; the
                 FHL book list itself is version-independent).

    Returns:
        Dict with 'books' list. Each entry has 'number', 'engs',
        'name_en', 'name_short_zh', 'name_full_zh'.
    """
    raw = _get("listall.html", {})
    if "error" in raw:
        return raw
    books = []
    for line in raw.get("raw_text", "").splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 5 or not cols[0].isdigit():
            continue
        books.append({
            "number":        int(cols[0]),
            "engs":          cols[1],
            "name_en":       cols[2],
            "name_short_zh": cols[3],
            "name_full_zh":  cols[4],
        })
    return {"version": version, "books": books, "total": len(books)}


# ── Master tool registry ───────────────────────────────────────────────────────

ALL_TOOLS = [
    get_bible_verse,
    get_bible_chapter,
    query_verse_citation,
    search_bible_advanced,
    get_word_analysis,
    lookup_strongs,
    search_strongs_occurrences,
    get_commentary,
    list_commentaries,
    search_commentary,
    get_topic_study,
    list_bible_versions,
    get_book_list,
]

TOOL_MAP = {fn.__name__: fn for fn in ALL_TOOLS}


# ── Interactive tool-selection menu ────────────────────────────────────────────

_SHORT_DESCRIPTIONS = {
    "get_bible_verse":            "Fetch a single verse (book, chapter, verse, version)",
    "get_bible_chapter":          "Fetch an entire chapter",
    "query_verse_citation":       "Lookup by citation string e.g. '約3:16'",
    "search_bible_advanced":      "Keyword search across the whole Bible",
    "get_word_analysis":          "Hebrew/Greek word breakdown for a verse",
    "lookup_strongs":             "Strong's dictionary entry (G#### / H####)",
    "search_strongs_occurrences": "All verses containing a Strong's word",
    "get_commentary":             "Commentary notes for a passage",
    "list_commentaries":          "List available commentary collections",
    "search_commentary":          "Full-text search within commentaries",
    "get_topic_study":            "Thematic study on a Biblical topic (English keys)",
    "list_bible_versions":        "List all available Bible versions",
    "get_book_list":              "List books + short codes (for any version)",
}


def list_tools_menu() -> None:
    """Print an interactive numbered menu of all available FHL tools."""
    print("\n" + "=" * 70)
    print("  Available FHL Bible Tools")
    print("=" * 70)
    for i, fn in enumerate(ALL_TOOLS, 1):
        print(f"  [{i:2d}] {fn.__name__:<32} {_SHORT_DESCRIPTIONS[fn.__name__]}")
    print("=" * 70)
    print("  Enter numbers separated by commas to select, or 'all' for all tools.")
    print("  Example: 1,4,5,6  or  all\n")


def select_tools_interactive() -> list:
    """
    Prompt the user to choose a subset of tools to enable.
    Returns a list of tool functions to pass to apply_chat_template.
    """
    list_tools_menu()
    raw = input("Your selection: ").strip().lower()
    if raw in ("", "all"):
        print(f"  ✓ All {len(ALL_TOOLS)} tools enabled.\n")
        return ALL_TOOLS
    try:
        indices  = [int(x.strip()) - 1 for x in raw.split(",") if x.strip()]
        selected = [ALL_TOOLS[i] for i in indices if 0 <= i < len(ALL_TOOLS)]
        if not selected:
            print("  No valid indices — defaulting to all tools.\n")
            return ALL_TOOLS
        print(f"  ✓ Enabled: {[fn.__name__ for fn in selected]}\n")
        return selected
    except (ValueError, IndexError):
        print("  Invalid input — defaulting to all tools.\n")
        return ALL_TOOLS
