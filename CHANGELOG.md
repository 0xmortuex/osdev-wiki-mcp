# Changelog

## 0.1.0 - 2026-10-08

First release.

- `wiki_update` / `osdev-wiki-mcp --update`: find the newest WikiTeam dump of
  wiki.osdev.org on archive.org, verify its MD5, stream-decompress it, keep the
  latest revision of each article (across split `<page>` elements), and build a
  SQLite FTS5 index. Skips the download when the index is current.
- `wiki_search`: bm25 over title (10), redirect aliases (8), headings (3), body (1);
  exact title/alias matches first; all-words query with an any-word fallback.
- `wiki_page`, `wiki_sections`, `wiki_links`, `wiki_status`.
- Wikitext to plain text: templates, links, lists, code blocks kept verbatim,
  wikitables rendered one row per line with OSDev's bit-range idiom as `63..48`.
