"""Just enough MediaWiki wikitext handling to search and read OSDev wiki pages.

This is not a renderer. It turns wikitext into readable plain text (links
become their label, templates and markup disappear, code blocks are kept
verbatim because code is often exactly what an OS developer is looking for),
splits pages into sections by heading, and extracts outgoing links and
categories.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

_REDIRECT_RE = re.compile(r"^\s*#REDIRECT\s*\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", re.I)
_HEADING_RE = re.compile(r"^(={1,6})\s*(.*?)\s*\1\s*$", re.M)
_CODE_RE = re.compile(
    r"<(source|syntaxhighlight|pre|code)\b[^>]*>(.*?)</\1\s*>", re.S | re.I
)
_LINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
_EXTLINK_RE = re.compile(r"\[(?:https?|ftp)://[^\s\]]+(?:\s+([^\]]*))?\]")
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_REF_RE = re.compile(r"<ref\b[^>/]*/>|<ref\b[^>]*>.*?</ref>", re.S | re.I)

# Link namespaces that are not page links (files, interwiki, categories).
_NON_PAGE_PREFIXES = ("file:", "image:", "media:", "category:", "wikipedia:", "wp:", "w:")


@dataclass
class Section:
    level: int        # 1 for the lead (text before the first heading)
    heading: str      # "" for the lead
    text: str         # plain text of this section only


@dataclass
class Page:
    title: str
    redirect: str | None = None
    sections: list[Section] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


def normalize_title(title: str) -> str:
    """MediaWiki title rules: underscores are spaces, first letter uppercase."""
    t = title.replace("_", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t[:1].upper() + t[1:] if t else t


def _strip_templates(text: str) -> str:
    """Remove {{...}} templates, which nest, with a depth counter."""
    out = []
    depth = 0
    i = 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}" and depth:
            depth -= 1
            i += 2
            continue
        if depth == 0:
            out.append(text[i])
        i += 1
    return "".join(out)


# OSDev's bit-layout tables write a range as
#   63&nbsp;&nbsp;&nbsp;<span style="float: right;">48</span>
# (high bit left, low bit floated right). Render it as "63..48".
_BIT_RANGE_RE = re.compile(
    r"(\d+)\s*(?:&nbsp;\s*)+<span[^>]*float:\s*right[^>]*>\s*(\d+)\s*</span>", re.I)


def _cell_text(cell: str) -> str:
    # 'style="..." colspan=2 | value' -> value (attributes come before a single |)
    if "|" in cell:
        attrs, value = cell.split("|", 1)
        if "=" in attrs or not attrs.strip():
            cell = value
    return re.sub(r"<br\s*/?>", " ", cell, flags=re.I).strip()


def _strip_tables(text: str) -> str:
    """Render wikitables as one line per row, cells separated by ' | '."""
    lines: list[str] = []
    row: list[str] = []
    depth = 0

    def flush() -> None:
        if row:
            lines.append(" | ".join(c for c in row))
            row.clear()

    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("{|"):
            depth += 1
            continue
        if depth == 0:
            lines.append(line)
            continue
        if s.startswith("|}"):
            flush()
            depth -= 1
            continue
        if s.startswith("|-"):
            flush()
        elif s.startswith("|+"):
            lines.append(_cell_text(s[2:]))
        elif s.startswith(("|", "!")):
            row.extend(_cell_text(c) for c in re.split(r"\|\||!!", s[1:]))
        elif row:
            row[-1] += " " + s  # cell content continued on the next line
    flush()
    return "\n".join(lines)


def to_plain(wikitext: str) -> str:
    """Wikitext -> readable plain text. Code blocks are preserved verbatim."""
    codes: list[str] = []

    def stash(m: re.Match[str]) -> str:
        codes.append(html.unescape(m.group(2).strip("\n")))
        return f"\x00CODE{len(codes) - 1}\x00"

    t = _COMMENT_RE.sub("", wikitext)
    t = _CODE_RE.sub(stash, t)
    t = _REF_RE.sub("", t)
    t = _strip_templates(t)
    t = _BIT_RANGE_RE.sub(r"\1..\2", t)
    t = _strip_tables(t)

    def link(m: re.Match[str]) -> str:
        target, label = m.group(1).strip(), m.group(2)
        if target.lower().startswith(_NON_PAGE_PREFIXES):
            return ""
        if label is not None and label.strip():
            return label
        return target.lstrip(":").split("#")[0] or target

    t = _LINK_RE.sub(link, t)
    t = _EXTLINK_RE.sub(lambda m: m.group(1) or "", t)
    t = re.sub(r"'''''|'''|''", "", t)
    t = _TAG_RE.sub("", t)
    t = html.unescape(t)
    t = re.sub(r"^[*#:;]+\s*", lambda m: "- " if m.group(0).strip()[:1] in "*#" else "", t, flags=re.M)
    t = re.sub(r"\n{3,}", "\n\n", t)

    def unstash(m: re.Match[str]) -> str:
        return "\n```\n" + codes[int(m.group(1))] + "\n```\n"

    t = re.sub(r"\x00CODE(\d+)\x00", unstash, t)
    return t.strip()


def parse_page(title: str, wikitext: str) -> Page:
    page = Page(title=normalize_title(title))
    m = _REDIRECT_RE.match(wikitext)
    if m:
        page.redirect = normalize_title(m.group(1))
        return page

    for target, _label in _LINK_RE.findall(_COMMENT_RE.sub("", wikitext)):
        tgt = target.strip()
        low = tgt.lower()
        if low.startswith("category:"):
            page.categories.append(normalize_title(tgt.split(":", 1)[1]))
        elif low.startswith(_NON_PAGE_PREFIXES) or tgt.startswith(":"):
            continue
        else:
            name = normalize_title(tgt.split("#")[0])
            if name and name not in page.links:
                page.links.append(name)

    # Split on headings that aren't inside code blocks: blank out code first
    # (same length) so heading offsets still index into the original text.
    masked = _CODE_RE.sub(lambda m: " " * len(m.group(0)), wikitext)
    bounds = [(0, 1, "")]
    for h in _HEADING_RE.finditer(masked):
        bounds.append((h.start(), len(h.group(1)), to_plain(h.group(2))))
    for i, (start, level, heading) in enumerate(bounds):
        body_start = start if i == 0 else wikitext.index("\n", start) + 1 if "\n" in wikitext[start:] else len(wikitext)
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(wikitext)
        text = to_plain(wikitext[body_start:end])
        if i == 0 and not text:
            continue
        page.sections.append(Section(level, heading, text))
    return page
