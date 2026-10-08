# osdev-wiki-mcp

**The OSDev wiki, offline and searchable, for your AI agent.**

<!-- mcp-name: io.github.0xmortuex/osdev-wiki-mcp -->

[wiki.osdev.org](https://wiki.osdev.org) is the reference for hobby operating-system
development. It covers descriptor tables, paging, interrupt controllers, timers, ACPI,
disk controllers, bootloaders and toolchains. Agents writing kernel code tend to
reconstruct these details from memory and get bit layouts wrong. They also can't
browse the wiki themselves, because it sits behind a bot challenge.

osdev-wiki-mcp downloads the wiki's public archive once, indexes it locally with
SQLite full-text search, and gives the agent tools to search it, read a page or just
one section of it, and follow links.

## What it looks like

This is real output, from the 2025-12-30 dump:

```
> wiki_search("PIT", limit=3)
1. Programmable Interval Timer *
   The Programmable Interval Timer ([PIT]) chip (Intel 8253/8254) basically consists of an oscillator…
2. PC Speaker
   …When the [PIT] interrupts you, you need to program [PIT] timer 2 so that…
3. APIC Timer
   …Real Time Clock, TimeStamp Counter, [PIT] or even polling CMOS registers. In this tutorial…

> wiki_page("IDT", section="Gate Descriptor", max_chars=900)
# Interrupt Descriptor Table
https://wiki.osdev.org/Interrupt_Descriptor_Table · last edited 2025-06-05 · categories: X86 CPU, Interrupts
('IDT' redirects to 'Interrupt Descriptor Table'; 'Gate Descriptor' appears 2 times; showing
section 4 under 'Structure on IA-32'. Also: section 8 under 'Structure on x86-64')

### Gate Descriptor

Each entry in the table has a complex structure:

Gate Descriptor (32-bit):
63..48 | 47 | 46..45 | 44 | 43..40 | 39..32
Offset 31..16 | P | DPL 1..0 | 0 | Gate Type 3..0 | Reserved
31..16 | 15..0
Segment Selector 15..0 | Offset 15..0

- Offset: A 32-bit value, split in two parts. It represents the address of the entry point ...
[... section truncated]

[Cut at max_chars=900; the full text is 1567 chars. Call again with max_chars=1767 to read the rest.]
```

Notice what the output does for the agent:

- **Abbreviations work.** "PIT" and "IDT" are wiki redirects, and redirects are indexed
  as aliases of their target, so an abbreviation finds the right page first.
- **Bit-layout tables stay readable.** The wiki draws descriptor and page-table layouts
  as HTML tables. These are rendered as one row per line, with bit ranges shown as
  `63..48`.
- **Ambiguity is reported.** When a heading appears twice on a page, the agent is told
  where the other copy is.
- **Truncation explains itself.** A cut-off result says exactly what to call next.

## Install

```bash
pip install osdev-wiki-mcp
osdev-wiki-mcp --update          # one-time: download (~5 MB) and index (~15 s)
claude mcp add osdev-wiki -- osdev-wiki-mcp
```

You can skip `--update`. The agent can call `wiki_update` itself: every other tool
tells it to when there's no index yet.

The index (about 18 MB) lives in `%LOCALAPPDATA%\osdev-wiki-mcp` on Windows,
`~/Library/Application Support/osdev-wiki-mcp` on macOS, and
`$XDG_DATA_HOME/osdev-wiki-mcp` (or `~/.local/share/osdev-wiki-mcp`) elsewhere. Set
`OSDEV_WIKI_DIR` to put it somewhere else. Python 3.10+ is required, with SQLite
FTS5. python.org builds, uv-managed builds and most distro builds include FTS5, and
the server tells you if yours doesn't.

## Tools

| Tool | What it does |
|------|--------------|
| `wiki_search` | Ranked full-text search with match snippets. Titles and redirect names count most, and an exact title match is marked `*`. |
| `wiki_sections` | A page's outline: numbered headings with their sizes. |
| `wiki_page` | A page as plain text, or one section (by number or heading) including its subsections. Code blocks are kept verbatim and redirects are followed. |
| `wiki_links` | What a page links to (flagging links to pages that don't exist) and what links to it, including links made through a redirect. |
| `wiki_update` | Fetch the newest dump and rebuild the index. It does nothing if the index is already current. |
| `wiki_status` | Shows the source dump, page counts, the index's age and its location. |

## Where the content comes from, and its license

wiki.osdev.org can't be crawled: its API sits behind a Cloudflare bot challenge.
Instead, `wiki_update` finds the newest
[WikiTeam](https://wiki.archiveteam.org/index.php/WikiTeam) dump of the wiki on
archive.org (items named `wiki-wiki.osdev.org-YYYYMMDD`). It downloads that dump's
history file, checks the MD5 against archive.org's manifest, and keeps the latest
revision of each article. The dumps are periodic, so the index can be a few months
behind the live wiki. `wiki_status` shows which dump you have.

**This package contains no wiki content.** It downloads the public dump to your
machine and indexes it locally. On licensing, the wiki's own
[OSDev Wiki:Copyrights](https://wiki.osdev.org/OSDev_Wiki:Copyrights) page says content
added since June 6, 2011 is released under CC0. Its
[OSDev Wiki:License](https://wiki.osdev.org/OSDev_Wiki:License) page says *"the contents
of this wiki is of mixed licensing"*, because older material predates that policy. All
content belongs to the OSDev wiki and its contributors. Results link back to the page
on wiki.osdev.org.

(Note that [osdev0/wiki](https://github.com/osdev0/wiki) on GitHub is a separate,
unrelated wiki project, not a mirror of wiki.osdev.org.)

## Tests

```bash
pip install -e ".[test]" "ruff==0.16.0" "mypy==2.3.0"
ruff check src tests && mypy --strict src
pytest tests
```

The unit tests use a small fixture in the dump's real format, under
`tests/fixtures/mini-wiki.xml`. It includes a page whose history is split across
several `<page>` elements, which is how WikiTeam dumps store long histories. A
ranking test runs against the real wiki when `OSDEV_WIKI_REAL_DIR` points at a built
index. It checks 14 questions an OS developer actually asks ("PIT", "GDT tutorial",
"page fault error code", "how to enter long mode", …), and the right page must rank in
the top 3. CI builds the real index and runs that test too.

## License

MIT, for the code. The wiki content is not included. See above.
