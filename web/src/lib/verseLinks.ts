/**
 * Verse-link display mode. Stored answers always contain traditional
 * bible.fhl.net/new/read.php URLs (built server-side in
 * claude_bible_rag_v4.py); when the user picks the new UI, hrefs are
 * rewritten at render time — so the setting applies to old messages too
 * and no server change is needed.
 *
 * ── To change the endpoint or the default, edit the two constants below. ──
 */

export type VerseLinkMode = "traditional" | "vui";

/** Default for users who haven't chosen yet. */
export const DEFAULT_VERSE_LINK_MODE: VerseLinkMode = "traditional";

/** New-UI endpoint; the book short name + chapter are appended, e.g. .../創18 */
export const VUI_BIBLE_BASE = "https://tech.fhl.net/vui/#/bible/";

export const VERSE_LINK_STORAGE_KEY = "fhl_verse_link_mode";

export function loadVerseLinkMode(): VerseLinkMode {
  const saved = localStorage.getItem(VERSE_LINK_STORAGE_KEY);
  return saved === "vui" || saved === "traditional"
    ? saved
    : DEFAULT_VERSE_LINK_MODE;
}

export function saveVerseLinkMode(mode: VerseLinkMode): void {
  localStorage.setItem(VERSE_LINK_STORAGE_KEY, mode);
}

/**
 * Rewrite a traditional read.php verse link to the new UI when mode is
 * "vui". Anything that isn't a bible.fhl.net read.php link (Strong's
 * dictionary links, external links) is returned unchanged.
 *
 * Traditional: https://bible.fhl.net/new/read.php?chineses=詩&chap=75&...
 * New UI:      https://tech.fhl.net/vui/#/bible/詩75  (chapter)
 *              https://tech.fhl.net/vui/#/bible/創18:6 (verse anchor)
 *
 * Stored hrefs are chapter-only (traditional mode always opens the whole
 * chapter), so the verse number is recovered from the citation text of the
 * link (`linkText`, e.g. "約翰福音 3:16" or "詩23:1-3" — the first number
 * after the colon). Chapter-only citations like "羅馬書 8章" get no anchor.
 */
export function transformVerseHref(
  href: string | undefined,
  mode: VerseLinkMode,
  linkText?: string,
): string | undefined {
  if (!href || mode !== "vui") return href;
  try {
    const url = new URL(href);
    if (url.hostname !== "bible.fhl.net" || !url.pathname.endsWith("/read.php")) {
      return href;
    }
    const book = url.searchParams.get("chineses");
    const chap = url.searchParams.get("chap");
    if (!book || !chap) return href;
    const verseMatch = linkText?.match(/[:：]\s*(\d{1,3})/);
    const anchor = verseMatch ? `:${verseMatch[1]}` : "";
    return `${VUI_BIBLE_BASE}${encodeURIComponent(book + chap)}${anchor}`;
  } catch {
    return href; // malformed URL — leave as-is
  }
}
