/**
 * Rich-text clipboard copy. Answers are copied as HTML (text/html) so that
 * pasting into Word / PowerPoint / Outlook keeps verse citations as real
 * hyperlinks ("約翰福音 3:16" clickable) instead of long raw URLs. A
 * text/plain flavor (link labels only, markdown stripped) is included for
 * plain-text targets.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../api/types";
import {
  childrenToText,
  transformVerseHref,
  type VerseLinkMode,
} from "./verseLinks";

const escapeHtml = (s: string) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

/** Render an answer's markdown to HTML, with verse hrefs in the chosen mode. */
export function markdownToHtml(content: string, mode: VerseLinkMode): string {
  return renderToStaticMarkup(
    createElement(ReactMarkdown, {
      remarkPlugins: [remarkGfm],
      components: {
        a: ({ href, children }) =>
          createElement(
            "a",
            {
              href: transformVerseHref(href, mode, childrenToText(children)),
            },
            children,
          ),
      },
      children: content,
    }),
  );
}

/** Markdown → readable plain text: links become their label, markup dropped. */
export function markdownToPlain(content: string): string {
  return content
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/`([^`]+)`/g, "$1");
}

/** Whole conversation as {html, plain}, each turn labeled 問／答. */
export function conversationToClipboard(
  title: string,
  messages: Message[],
  mode: VerseLinkMode,
): { html: string; plain: string } {
  const htmlParts: string[] = [`<h2>${escapeHtml(title)}</h2>`];
  const plainParts: string[] = [title, ""];
  for (const m of messages) {
    if (!m.content) continue;
    if (m.role === "user") {
      htmlParts.push(
        `<p><b>問：</b>${escapeHtml(m.content).replace(/\n/g, "<br>")}</p>`,
      );
      plainParts.push(`問：${m.content}`, "");
    } else {
      htmlParts.push(`<p><b>答：</b></p>`, markdownToHtml(m.content, mode), "<hr>");
      plainParts.push(`答：`, markdownToPlain(m.content), "", "────────", "");
    }
  }
  return { html: htmlParts.join("\n"), plain: plainParts.join("\n") };
}

/** Put HTML + plain text on the clipboard. */
export async function copyRich(html: string, plain: string): Promise<void> {
  if (
    window.isSecureContext &&
    navigator.clipboard?.write &&
    typeof ClipboardItem !== "undefined"
  ) {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([plain], { type: "text/plain" }),
      }),
    ]);
    return;
  }
  // http:// / older-browser fallback: select an off-screen rendered copy and
  // execCommand("copy"), which also carries the HTML formatting.
  const div = document.createElement("div");
  div.innerHTML = html;
  div.style.position = "fixed";
  div.style.left = "-9999px";
  div.style.top = "0";
  document.body.appendChild(div);
  const range = document.createRange();
  range.selectNodeContents(div);
  const sel = window.getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
  try {
    if (!document.execCommand("copy")) throw new Error("copy failed");
  } finally {
    sel?.removeAllRanges();
    document.body.removeChild(div);
  }
}
