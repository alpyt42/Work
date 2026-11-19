"""Markdown: folding, headings, the renderer and its link rules, task boxes and front matter."""

from __future__ import annotations

import posixpath
import re
import unicodedata
from array import array
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.token import Token

HEADING_ID_PREFIX = "h-"
DOC_OFF_TITLE = "File not shown here"
WHITESPACE_RE = re.compile(r"\s+")
FENCE_RE = re.compile(r"^ {0,3}(?:`{3,}|~{3,})")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_FOLD_CACHE: dict[str, str] = {}


def _fold_char(char: str) -> str:
    folded = _FOLD_CACHE.get(char)
    if folded is None:
        plain = "".join(item for item in unicodedata.normalize("NFKD", char) if not unicodedata.combining(item))
        folded = "".join(item for item in plain.casefold() if not unicodedata.combining(item))
        if len(_FOLD_CACHE) < 50_000:
            _FOLD_CACHE[char] = folded
    return folded


def fold_mapped(text: str) -> tuple[str, array]:
    """Accent-, case- and whitespace-insensitive form of ``text`` plus, for each folded character, the index of its source character."""
    out: list[str] = []
    origin = array("I")
    spaced = False
    for index, char in enumerate(text):
        folded = _fold_char(char)
        if not folded:
            continue
        if folded.isspace():
            if not spaced:
                out.append(" ")
                origin.append(index)
            spaced = True
            continue
        spaced = False
        out.append(folded)
        origin.extend([index] * len(folded))
    return "".join(out), origin


def fold(text: str) -> str:
    if text.isascii():
        return WHITESPACE_RE.sub(" ", text.casefold())
    return fold_mapped(text)[0]


def heading_slug(text: str) -> str:
    slug = re.sub(r"[^\w]+", "-", fold(text)).strip("-_")[:80].strip("-_")
    return slug or "section"


def _doc_link(href: str, env: dict) -> tuple[str, str, str]:
    """Classify a Markdown link: ("external"|"doc"|"off", target, anchor)."""
    try:
        parts = urlsplit(href)
    except ValueError:
        return "off", "", ""
    scheme = parts.scheme.lower()
    if scheme in {"http", "https", "mailto"}:
        return "external", href, ""
    if scheme or parts.netloc:
        return "off", "", ""
    path, fragment = unquote(parts.path), unquote(parts.fragment)
    anchor = HEADING_ID_PREFIX + heading_slug(fragment) if fragment else ""
    if not path:
        return ("doc", env["id"], anchor) if fragment else ("off", "", "")
    if path.startswith("/") or not path.lower().endswith(".md"):
        return "off", "", ""
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(env["id"]), path))
    if resolved in env["ids"]:
        return "doc", resolved, anchor
    return "off", "", ""


def _render_link_open(self, tokens, idx, options, env) -> str:
    token = tokens[idx]
    kind, target, anchor = _doc_link(token.attrGet("href") or "", env)
    env.setdefault("link_stack", []).append(kind != "off")
    if kind == "off":
        return f'<span class="doc-link-off" title="{DOC_OFF_TITLE}">'
    title = token.attrGet("title")
    extra = f' title="{escapeHtml(str(title))}"' if title and kind == "external" else ""
    if kind == "external":
        return f'<a href="{escapeHtml(target)}" target="_blank" rel="noopener noreferrer"{extra}>'
    data_anchor = f' data-anchor="{escapeHtml(anchor)}"' if anchor else ""
    return f'<a href="#doc" class="doc-link" data-doc="{escapeHtml(target)}"{data_anchor}>'


def _render_link_close(self, tokens, idx, options, env) -> str:
    stack = env.get("link_stack") or []
    return "</a>" if (stack.pop() if stack else True) else "</span>"


def _render_image(self, tokens, idx, options, env) -> str:
    token = tokens[idx]
    alt = self.renderInlineAsText(token.children, options, env) if token.children else ""
    return f'<span class="doc-image-off" title="Image not shown here">{escapeHtml(alt.strip() or "image")}</span>'


def _render_table_open(self, tokens, idx, options, env) -> str:
    return '<div class="table-wrap">' + self.renderToken(tokens, idx, options, env)


def _render_table_close(self, tokens, idx, options, env) -> str:
    return self.renderToken(tokens, idx, options, env) + "</div>\n"


UNDERLINE_CLOSE = re.compile(r"</u>", re.IGNORECASE)


def _underline(state, silent: bool) -> bool:
    """Inline rule for `<u>text</u>`, the underline Obsidian notes use and Markdown lacks. It matches the bare tags only: no
    attribute, no other tag. The tags are emitted by the parser and so always balanced; an opening tag with no closing one in the
    same block (and any stray closing tag) stays what raw HTML is everywhere else, escaped text."""
    if state.src[state.pos : state.pos + 3].lower() != "<u>":
        return False
    close = UNDERLINE_CLOSE.search(state.src, state.pos + 3, state.posMax)
    if not close:
        return False
    if not silent:
        state.push("underline_open", "u", 1).markup = "<u>"
        end = state.posMax
        state.pos += 3
        state.posMax = close.start()
        state.md.inline.tokenize(state)
        state.posMax = end
        state.push("underline_close", "u", -1).markup = "</u>"
    state.pos = close.end()
    return True


def _heading_ids(state) -> None:
    used: dict[str, int] = {}
    tokens = state.tokens
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens) and tokens[index + 1].type == "inline":
            text = "".join(child.content for child in tokens[index + 1].children or [] if child.type in {"text", "code_inline"})
            slug = heading_slug(text)
            used[slug] = used.get(slug, 0) + 1
            token.attrSet("id", HEADING_ID_PREFIX + slug + ("" if used[slug] == 1 else f"-{used[slug]}"))


TASK_MARKER_RE = re.compile(r"^\[([ xX])\](?=[ \t]|$)")
TASK_LINE_RE = re.compile(rb"^(?:\xef\xbb\xbf)?((?:[ \t]*>)*[ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+)\[([ xX])\](?=[ \t\r]|$)")


def _task_items(state) -> None:
    """Turn a leading `[ ]` / `[x]` of a list item (on the line of the item itself) into a checkbox token."""
    tokens = state.tokens
    for index, item in enumerate(tokens[:-2]):
        if item.type != "list_item_open" or item.map is None or tokens[index + 1].type != "paragraph_open" or tokens[index + 2].type != "inline":
            continue
        inline = tokens[index + 2]
        # The raw source must start with the marker too: an escaped `\[ ]` reaches the first text child as a plain `[ ]`.
        if (inline.map is None or inline.map[0] != item.map[0] or not inline.children or inline.children[0].type != "text"
                or not TASK_MARKER_RE.match(inline.content)):
            continue
        first = inline.children[0]
        match = TASK_MARKER_RE.match(first.content)
        if not match:
            continue
        checked = match.group(1) != " "
        first.content = first.content[match.end():][1:]
        box = Token("task_box", "input", 0)
        box.meta = {"checked": checked, "line": item.map[0]}
        inline.children.insert(0, box)
        item.attrJoin("class", "task-item" + (" task-done" if checked else ""))


def _render_task_box(self, tokens, idx, options, env) -> str:
    meta = tokens[idx].meta
    return f'<input type="checkbox" class="task-box" data-line="{int(meta["line"]) + int(env.get("line_offset", 0))}"{" checked" if meta["checked"] else ""} disabled>'


def build_markdown() -> MarkdownIt:
    """Raw HTML in documents is escaped (never rendered), but for a bare `<u>…</u>` (underline); links and images are rewritten by the rules above."""
    markdown = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable(["table", "strikethrough"])
    for name, rule in (("link_open", _render_link_open), ("link_close", _render_link_close), ("image", _render_image),
                       ("table_open", _render_table_open), ("table_close", _render_table_close)):
        markdown.add_render_rule(name, rule)
    markdown.inline.ruler.before("html_inline", "underline", _underline)
    markdown.core.ruler.push("heading_ids", _heading_ids)
    markdown.core.ruler.push("task_items", _task_items)
    markdown.add_render_rule("task_box", _render_task_box)
    return markdown


MARKDOWN = build_markdown()


FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def split_front_matter(text: str) -> tuple[list[tuple[str, str]], str]:
    """Separate a leading YAML block (Obsidian properties) so it is not rendered as a setext heading."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return [], text
    properties: list[tuple[str, str]] = []
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line[:1].isspace() and not line.lstrip().startswith("-"):
            properties.append((key.strip(), value.strip()))
        elif line.strip() and properties:
            properties[-1] = (properties[-1][0], f"{properties[-1][1]} {line.strip()}".strip())
    return properties, text[match.end():]


def front_matter_html(properties: list[tuple[str, str]]) -> str:
    if not properties:
        return ""
    rows = "".join(f"<dt>{escapeHtml(key)}</dt><dd>{escapeHtml(value.strip(chr(34)).strip(chr(39)))}</dd>" for key, value in properties)
    return f'<dl class="doc-props">{rows}</dl>\n'
