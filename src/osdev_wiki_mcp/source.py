"""Fetch the OSDev wiki from its public WikiTeam dump on archive.org.

wiki.osdev.org sits behind a bot challenge, so its API can't be crawled.
WikiTeam (https://wiki.archiveteam.org/index.php/WikiTeam) publishes
periodic full dumps to archive.org as items named wiki-wiki.osdev.org-YYYYMMDD,
each with a zstd-compressed MediaWiki XML export of every page's history.
We pick the newest item, download the history file (a few MB compressed),
verify its MD5 against archive.org's manifest, and stream-parse it keeping
only the latest revision of each main-namespace page.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO, Any

import zstandard

USER_AGENT = "osdev-wiki-mcp (+https://github.com/0xmortuex/osdev-wiki-mcp)"
ITEM_PREFIX = "wiki-wiki.osdev.org-"
_NS = "{http://www.mediawiki.org/xml/export-0.11/}"


class SourceError(RuntimeError):
    pass


@dataclass
class Dump:
    identifier: str      # archive.org item, e.g. wiki-wiki.osdev.org-20251230
    filename: str        # path of the history .xml.zst inside the item
    size: int
    md5: str

    @property
    def url(self) -> str:
        return (f"https://archive.org/download/{self.identifier}/"
                + urllib.parse.quote(self.filename))

    @property
    def date(self) -> str:
        return self.identifier.removeprefix(ITEM_PREFIX)


def _get_json(url: str, timeout: float = 60) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except OSError as e:
        raise SourceError(f"could not reach archive.org ({url}): {e}") from e


def latest_dump() -> Dump:
    """Find the newest dated OSDev wiki dump on archive.org."""
    q = urllib.parse.urlencode({
        "q": f"identifier:{ITEM_PREFIX}*",
        "fl[]": "identifier",
        "rows": "100",
        "output": "json",
    })
    docs = _get_json(f"https://archive.org/advancedsearch.php?{q}")["response"]["docs"]
    dated = sorted(
        (d["identifier"] for d in docs
         if d["identifier"].removeprefix(ITEM_PREFIX).isdigit()),
        reverse=True,
    )
    if not dated:
        raise SourceError("no wiki.osdev.org dumps found on archive.org")
    for ident in dated:
        meta = _get_json(f"https://archive.org/metadata/{ident}")
        for f in meta.get("files", []):
            if f["name"].endswith("-history.xml.zst"):
                return Dump(ident, f["name"], int(f.get("size", 0)), f.get("md5", ""))
    raise SourceError(f"none of {len(dated)} OSDev dumps has a history.xml.zst file")


def download(dump: Dump, dest: str) -> str:
    """Download the dump to dest (atomically) and verify its MD5."""
    tmp = dest + ".part"
    md5 = hashlib.md5()
    req = urllib.request.Request(dump.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 20):
                md5.update(chunk)
                out.write(chunk)
    except OSError as e:
        raise SourceError(f"downloading {dump.url} failed: {e}") from e
    if dump.md5 and md5.hexdigest() != dump.md5:
        os.remove(tmp)
        raise SourceError(f"checksum mismatch for {dump.filename}: "
                          f"got {md5.hexdigest()}, archive.org says {dump.md5}")
    os.replace(tmp, dest)
    return dest


@dataclass
class RawPage:
    title: str
    text: str
    timestamp: str


def iter_pages(fh: IO[bytes]) -> Iterator[RawPage]:
    """Yield the latest revision of every main-namespace (ns 0) page.

    WikiTeam history dumps split a long page history across many <page>
    elements with the same title ("Projects" appears 371 times in the
    2025-12-30 dump), so the newest revision has to be chosen per *title*
    across the whole file, not per element.
    """
    latest: dict[str, RawPage] = {}
    for _event, el in ET.iterparse(fh):
        if el.tag != _NS + "page":
            continue
        if el.findtext(_NS + "ns") == "0":
            title = el.findtext(_NS + "title") or ""
            for rev in el.iter(_NS + "revision"):
                ts = rev.findtext(_NS + "timestamp") or ""
                cur = latest.get(title)
                if cur is None or ts >= cur.timestamp:
                    latest[title] = RawPage(title, rev.findtext(_NS + "text") or "", ts)
        el.clear()
    yield from latest.values()


def open_dump(path: str) -> IO[bytes]:
    """Open a .xml.zst (streamed, never fully decompressed to disk) or .xml."""
    fh = open(path, "rb")
    if path.endswith(".zst"):
        # WikiTeam dumps use a long-distance window larger than zstandard's
        # default 128 MB decoder limit.
        reader: IO[bytes] = zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(
            fh, closefd=True)
        return reader
    return fh
