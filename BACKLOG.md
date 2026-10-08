# Backlog

Real, finishable improvements - pick ONE, ship it end-to-end with tests.

## Features
- [ ] `wiki_category(name)`: list pages in a category (categories are already indexed per page).
- [ ] Render `<math>` and `{{Box}}`-style templates that carry real content instead of dropping them (audit which templates on the wiki hold text).
- [ ] Images: list a page's figures with their captions and wiki.osdev.org URLs (diagrams matter for paging/GDT pages).
- [ ] Search filters: `category=` on wiki_search.
- [ ] Incremental update: compare per-page timestamps and only re-parse changed pages.

## Quality
- [ ] Expand the real-wiki ranking set from 14 to ~50 queries harvested from r/osdev / forum thread titles.
- [ ] Table rendering for nested tables and rowspan (rare on the wiki; check which pages use them).
