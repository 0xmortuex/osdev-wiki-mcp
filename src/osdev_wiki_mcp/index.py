"""SQLite FTS5 index over the OSDev wiki.

One database file in the data directory, rebuilt atomically by build().
Search ranks with bm25 over four fields, weighted so that a page *about* the
query beats a page that merely mentions it:

    title 10  >  aliases (redirect names, e.g. "PIT") 8  >  headings 3  >  body 1

and an exact title/alias match always ranks first.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass

from .source import RawPage
from .wikitext import Page, normalize_title, parse_page

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE pages (id INTEGER PRIMARY KEY, title TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL, categories TEXT NOT NULL);
CREATE TABLE redirects (alias TEXT PRIMARY KEY, target TEXT NOT NULL);
CREATE TABLE sections (page_id INTEGER NOT NULL, idx INTEGER NOT NULL, level INTEGER NOT NULL,
                       heading TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (page_id, idx));
CREATE TABLE links (src TEXT NOT NULL, dst TEXT NOT NULL);
CREATE INDEX links_dst ON links(dst);
CREATE VIRTUAL TABLE pages_fts USING fts5(title, aliases, headings, body,
                                          tokenize='porter unicode61');
"""

WEIGHTS = (10.0, 8.0, 3.0, 1.0)


class IndexError_(RuntimeError):
    """Index missing or unusable (named to avoid shadowing builtins.IndexError)."""


def data_dir() -> str:
    env = os.environ.get("OSDEV_WIKI_DIR")
    if env:
        return env
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "osdev-wiki-mcp")


def db_path() -> str:
    return os.path.join(data_dir(), "index.sqlite")


def require_fts5() -> None:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError as e:
        raise IndexError_(
            f"this Python's SQLite ({sqlite3.sqlite_version}) was built without FTS5, "
            "which the search index needs. Use a python.org / uv-managed Python, or a "
            "distro Python with full SQLite."
        ) from e


def build(pages: Iterable[RawPage], dest: str, meta: dict[str, str]) -> dict[str, int]:
    """Build a fresh index at dest (via a temp file, so readers never see half a DB)."""
    require_fts5()
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".building"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    parsed: list[tuple[Page, str]] = []
    for raw in pages:
        parsed.append((parse_page(raw.title, raw.text), raw.timestamp))

    redirects = {p.title: p.redirect for p, _ in parsed if p.redirect}
    aliases: dict[str, list[str]] = {}
    for alias, target in redirects.items():
        aliases.setdefault(target, []).append(alias)
    con.executemany("INSERT INTO redirects VALUES (?, ?)", redirects.items())

    n_pages = n_sections = n_links = 0
    for page, ts in parsed:
        if page.redirect:
            continue
        cur = con.execute("INSERT INTO pages (title, timestamp, categories) VALUES (?, ?, ?)",
                          (page.title, ts, "\n".join(page.categories)))
        pid = cur.lastrowid
        n_pages += 1
        con.executemany(
            "INSERT INTO sections VALUES (?, ?, ?, ?, ?)",
            [(pid, i, s.level, s.heading, s.text) for i, s in enumerate(page.sections)],
        )
        n_sections += len(page.sections)
        con.executemany("INSERT INTO links VALUES (?, ?)", [(page.title, d) for d in page.links])
        n_links += len(page.links)
        con.execute(
            "INSERT INTO pages_fts (rowid, title, aliases, headings, body) VALUES (?, ?, ?, ?, ?)",
            (pid, page.title, "\n".join(aliases.get(page.title, [])),
             "\n".join(s.heading for s in page.sections if s.heading),
             "\n\n".join(s.text for s in page.sections)),
        )
    stats = {"pages": n_pages, "redirects": len(redirects), "sections": n_sections, "links": n_links}
    meta = {**meta, **{k: str(v) for k, v in stats.items()}, "built_at": str(int(time.time()))}
    con.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    con.commit()
    con.execute("INSERT INTO pages_fts(pages_fts) VALUES ('optimize')")
    con.commit()
    con.close()
    os.replace(tmp, dest)
    return stats


@dataclass
class Hit:
    title: str
    snippet: str
    exact: bool


class Wiki:
    def __init__(self, path: str | None = None):
        self.path = path or db_path()
        if not os.path.isfile(self.path):
            raise IndexError_(
                f"no OSDev wiki index at {self.path} - call wiki_update first "
                "(downloads the wiki dump from archive.org and indexes it, ~1 minute)"
            )
        self.con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    # Connections must be closed promptly: on Windows an open handle stops
    # build() from replacing the index file during wiki_update.
    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Wiki:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def meta(self) -> dict[str, str]:
        return dict(self.con.execute("SELECT key, value FROM meta").fetchall())

    def resolve(self, title: str) -> tuple[str, str | None]:
        """Title (any case, underscores ok, redirects followed) -> (page title, note)."""
        t = normalize_title(title)
        row = self.con.execute("SELECT title FROM pages WHERE title = ? COLLATE NOCASE", (t,)).fetchone()
        if row:
            return row[0], None
        row = self.con.execute("SELECT target FROM redirects WHERE alias = ? COLLATE NOCASE", (t,)).fetchone()
        if row:
            tgt = self.con.execute("SELECT title FROM pages WHERE title = ? COLLATE NOCASE",
                                   (row[0],)).fetchone()
            if tgt:
                return tgt[0], f"{t!r} redirects to {tgt[0]!r}"
        hits = self.search(title, limit=5)
        hint = "; closest: " + ", ".join(h.title for h in hits) if hits else ""
        raise KeyError(f"no OSDev wiki page titled {title!r}{hint}. Use wiki_search to find pages.")

    @staticmethod
    def _fts_query(query: str, op: str) -> str:
        tokens = re.findall(r"\w+", query.lower())
        if not tokens:
            raise ValueError("search query has no words")
        return f" {op} ".join(f'"{t}"' for t in tokens)

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        exact_title = None
        t = normalize_title(query)
        row = self.con.execute(
            "SELECT title FROM pages WHERE title = ? COLLATE NOCASE "
            "UNION ALL SELECT target FROM redirects WHERE alias = ? COLLATE NOCASE", (t, t)
        ).fetchone()
        if row:
            exact_title = normalize_title(row[0])
        sql = (
            "SELECT title, snippet(pages_fts, 3, '[', ']', '…', 14) FROM pages_fts "
            f"WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts, {', '.join(map(str, WEIGHTS))}) LIMIT ?"
        )
        rows = self.con.execute(sql, (self._fts_query(query, "AND"), limit)).fetchall()
        if not rows:
            rows = self.con.execute(sql, (self._fts_query(query, "OR"), limit)).fetchall()
        hits = [Hit(r[0], r[1].replace("\n", " "), r[0] == exact_title) for r in rows]
        if exact_title:
            hits.sort(key=lambda h: not h.exact)
            if not any(h.exact for h in hits):
                snip = self.con.execute(
                    "SELECT substr(text, 1, 160) FROM sections s JOIN pages p ON p.id = s.page_id "
                    "WHERE p.title = ? ORDER BY idx LIMIT 1", (exact_title,)).fetchone()
                hits.insert(0, Hit(exact_title, (snip[0] if snip else "").replace("\n", " "), True))
                hits = hits[:limit]
        return hits

    def sections(self, title: str) -> list[tuple[int, int, str, int]]:
        return self.con.execute(
            "SELECT s.idx, s.level, s.heading, length(s.text) FROM sections s "
            "JOIN pages p ON p.id = s.page_id WHERE p.title = ? ORDER BY s.idx", (title,)
        ).fetchall()

    def section_texts(self, title: str) -> list[tuple[int, int, str, str]]:
        return self.con.execute(
            "SELECT s.idx, s.level, s.heading, s.text FROM sections s "
            "JOIN pages p ON p.id = s.page_id WHERE p.title = ? ORDER BY s.idx", (title,)
        ).fetchall()

    def page_info(self, title: str) -> tuple[str, list[str]]:
        ts, cats = self.con.execute("SELECT timestamp, categories FROM pages WHERE title = ?",
                                    (title,)).fetchone()
        return ts, [c for c in cats.split("\n") if c]

    def links_out(self, title: str) -> list[tuple[str, bool]]:
        rows = self.con.execute("SELECT dst FROM links WHERE src = ?", (title,)).fetchall()
        out = []
        for (dst,) in rows:
            exists = self.con.execute(
                "SELECT 1 FROM pages WHERE title = ? COLLATE NOCASE UNION ALL "
                "SELECT 1 FROM redirects WHERE alias = ? COLLATE NOCASE", (dst, dst)).fetchone()
            out.append((dst, exists is not None))
        return out

    def links_in(self, title: str) -> list[str]:
        names = [title] + [a for (a,) in self.con.execute(
            "SELECT alias FROM redirects WHERE target = ? COLLATE NOCASE", (title,))]
        marks = ",".join("?" * len(names))
        rows = self.con.execute(
            f"SELECT DISTINCT src FROM links WHERE dst COLLATE NOCASE IN ({marks}) ORDER BY src",
            names).fetchall()
        return [r[0] for r in rows if r[0] != title]
