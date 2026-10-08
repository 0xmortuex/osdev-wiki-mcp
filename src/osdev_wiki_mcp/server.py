"""osdev-wiki-mcp: an MCP server giving agents offline, searchable access to the OSDev wiki."""

from __future__ import annotations

import argparse
import functools
import os
import sys
import time
from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import index as idx
from . import source

mcp = MCPServer(
    "osdev-wiki",
    instructions=(
        "Offline, searchable OSDev wiki (wiki.osdev.org) - the reference for hobby OS "
        "development: x86 descriptors and paging, interrupts, PIC/APIC, PIT, ACPI, ATA, PS/2, "
        "bootloaders, Multiboot, toolchains. Search before answering from memory: "
        "wiki_search -> wiki_sections (see a page's outline) -> wiki_page with section= "
        "for just the part you need. Abbreviations work (PIT, IDT, RSDP) because redirects "
        "are indexed. If a tool says there is no index, call wiki_update once."
    ),
)

F = TypeVar("F", bound=Callable[..., Any])

# Failures an agent can act on. MCPServer only forwards a ToolError's message
# to the client - anything else arrives as a bare "Error executing tool X" -
# so these are re-raised as ToolError with their text intact.
_EXPECTED = (idx.IndexError_, source.SourceError, KeyError, ValueError, OSError)


def tool(fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except _EXPECTED as e:
            # KeyError's str() wraps the message in quotes; use the raw text.
            msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            raise ToolError(str(msg)) from e

    mcp.tool()(wrapper)
    return fn


def _wiki() -> idx.Wiki:
    return idx.Wiki()


def _url(title: str) -> str:
    return "https://wiki.osdev.org/" + title.replace(" ", "_")


def update(force: bool = False, progress: Callable[[str], None] | None = None) -> str:
    """Download the newest dump (if newer than the index) and rebuild the index."""
    say = progress or (lambda _m: None)
    idx.require_fts5()
    dump = source.latest_dump()
    path = idx.db_path()
    if not force and os.path.isfile(path):
        with idx.Wiki(path) as w:
            current = w.meta().get("dump")
        if current == dump.identifier:
            return f"Already up to date: index built from {dump.identifier}."
    os.makedirs(idx.data_dir(), exist_ok=True)
    zst = os.path.join(idx.data_dir(), "history.xml.zst")
    say(f"downloading {dump.url} ({dump.size / 1e6:.1f} MB)")
    t0 = time.monotonic()
    source.download(dump, zst)
    say("parsing and indexing")
    # Close the stream before deleting the file: Windows refuses to remove an open file.
    with source.open_dump(zst) as fh:
        stats = idx.build(source.iter_pages(fh), path,
                          {"dump": dump.identifier, "dump_url": dump.url})
    os.remove(zst)
    return (f"Indexed {stats['pages']} pages, {stats['redirects']} redirects, "
            f"{stats['sections']} sections from {dump.identifier} "
            f"in {time.monotonic() - t0:.0f}s.\nIndex: {path}")


@tool
def wiki_update(force: bool = False) -> str:
    """Download the latest OSDev wiki dump from archive.org and (re)build the
    local search index. Needed once before the other tools work; afterwards
    only when you want newer content. Takes about a minute (a ~5 MB download,
    then parsing). force=True rebuilds even if the index is current."""
    return update(force)


@tool
def wiki_status() -> str:
    """Show the index: source dump date, page counts, when it was built, and where it lives."""
    with _wiki() as w:
        m = w.meta()
        age_days = (time.time() - int(m["built_at"])) / 86400
        return (f"OSDev wiki index: {m['pages']} pages, {m['redirects']} redirects, "
                f"{m['sections']} sections, {m['links']} links\n"
                f"source: {m['dump']} (WikiTeam dump of wiki.osdev.org on archive.org)\n"
                f"built {age_days:.1f} days ago; file: {w.path}")


@tool
def wiki_search(query: str, limit: int = 8) -> str:
    """Search the OSDev wiki. Returns page titles ranked by relevance with a
    snippet showing where the words matched ([brackets]). Titles and
    redirect names (e.g. "PIT", "IDT") weigh most; an exact title match is
    marked with *. limit is 1-25."""
    if not 1 <= limit <= 25:
        raise ValueError("limit must be between 1 and 25")
    with _wiki() as w:
        hits = w.search(query, limit)
    if not hits:
        return f"No OSDev wiki pages match {query!r}."
    lines = []
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h.title}{' *' if h.exact else ''}")
        if h.snippet:
            lines.append(f"   {h.snippet.strip()}")
    return "\n".join(lines)


@tool
def wiki_sections(title: str) -> str:
    """List a page's sections (number, heading, size) so you can fetch just
    the one you need with wiki_page(title, section=...)."""
    with _wiki() as w:
        real, note = w.resolve(title)
        rows = w.sections(real)
        lines = [f"{real}  ({_url(real)})"]
        for i, level, heading, size in rows:
            indent = "  " * max(level - 2, 0)
            lines.append(f"  {i}. {indent}{heading or '(introduction)'}  [{size} chars]")
        return "\n".join(lines) + (f"\n({note})" if note else "")


@tool
def wiki_page(title: str, section: str | None = None, max_chars: int = 12000) -> str:
    """Read an OSDev wiki page as plain text (code blocks kept verbatim).

    title is case-insensitive and redirects are followed ("PIT" works).
    section narrows to one section: its number from wiki_sections or its
    heading text (subsections are included). Pages longer than max_chars are
    cut off with a list of the remaining sections to request next.
    """
    if max_chars < 500:
        raise ValueError("max_chars must be at least 500")
    with _wiki() as w:
        real, note = w.resolve(title)
        rows = w.section_texts(real)
        if section is not None:
            start = None
            if section.strip().isdigit():
                start = int(section)
                if start >= len(rows):
                    raise ValueError(f"{real!r} has sections 0-{len(rows) - 1}")
            else:
                matches = [i for i, _lvl, heading, _t in rows
                           if heading.lower() == section.strip().lower()]
                if not matches:
                    names = ", ".join(h for _i, _l, h, _t in rows if h)
                    raise KeyError(f"no section {section!r} in {real!r}; sections: {names}")
                start = matches[0]
                if len(matches) > 1:
                    # Same heading under different parents (e.g. "Gate Descriptor"
                    # under both "Structure on IA-32" and "Structure on x86-64").
                    def parent(i: int) -> str:
                        lvl = rows[i][1]
                        for j in range(i - 1, -1, -1):
                            if rows[j][1] < lvl and rows[j][2]:
                                return rows[j][2]
                        return "top level"
                    others = "; ".join(f"section {i} under {parent(i)!r}" for i in matches[1:])
                    extra = (f"{section!r} appears {len(matches)} times; showing section {start} "
                             f"under {parent(start)!r}. Also: {others}")
                    note = f"{note}; {extra}" if note else extra
            # A section runs until the next heading at the same or a higher level;
            # the introduction (level 1, no heading) is just itself.
            level = rows[start][1]
            end = start + 1
            if rows[start][2]:
                while end < len(rows) and rows[end][1] > level:
                    end += 1
            rows = rows[start:end]
        ts, cats = w.page_info(real)
        header = [f"# {real}", f"{_url(real)} · last edited {ts[:10]}"
                  + (f" · categories: {', '.join(cats)}" if cats else "")]
        if note:
            header.append(f"({note})")
        out = "\n".join(header) + "\n"
        blocks = [(f"\n{'#' * min(level, 6)} {heading}\n\n" if heading else "\n") + text + "\n"
                  for _i, level, heading, text in rows]
        full = len(out) + sum(len(b) for b in blocks)
        for n, block in enumerate(blocks):
            if len(out) + len(block) > max_chars:
                room = max_chars - len(out)
                partial = room > 300
                if partial:
                    out += block[:room] + "\n[... section truncated]\n"
                rest = [f"{i}. {h}" for i, _l, h, _t in rows[n + (1 if partial else 0):] if h]
                out += f"\n[Cut at max_chars={max_chars}; the full text is {full} chars. "
                if rest:
                    out += ("Fetch the remaining sections with wiki_page(title, section=...): "
                            + "; ".join(rest) + "]")
                else:
                    out += f"Call again with max_chars={full + 200} to read the rest.]"
                break
            out += block
        return out.rstrip()


@tool
def wiki_links(title: str, limit: int = 60) -> str:
    """Show what a page links to (marking links to pages that don't exist)
    and which pages link to it - useful for finding related reading."""
    with _wiki() as w:
        real, note = w.resolve(title)
        out_links = w.links_out(real)
        in_links = w.links_in(real)
        lines = [f"{real}", f"\nLinks to ({len(out_links)}):"]
        lines += [f"  {d}{'' if ok else '  (no such page)'}" for d, ok in out_links[:limit]]
        lines.append(f"\nLinked from ({len(in_links)}):")
        lines += [f"  {s}" for s in in_links[:limit]]
        if len(in_links) > limit or len(out_links) > limit:
            lines.append(f"(lists cut at {limit})")
        return "\n".join(lines) + (f"\n({note})" if note else "")


def main() -> None:
    ap = argparse.ArgumentParser(prog="osdev-wiki-mcp",
                                 description="MCP server for the OSDev wiki (stdio).")
    ap.add_argument("--update", action="store_true",
                    help="download the latest wiki dump, rebuild the index, and exit")
    ap.add_argument("--force", action="store_true", help="with --update: rebuild even if current")
    args = ap.parse_args()
    if args.update:
        try:
            print(update(args.force, progress=lambda m: print(m, file=sys.stderr)))
        except (idx.IndexError_, source.SourceError, OSError) as e:
            sys.exit(f"osdev-wiki-mcp: {e}")
        return
    mcp.run()


if __name__ == "__main__":
    main()
