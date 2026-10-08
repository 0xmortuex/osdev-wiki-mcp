import hashlib
import io

import pytest
import zstandard

from osdev_wiki_mcp import source
from conftest import FIXTURE


def _pages(path):
    with source.open_dump(path) as fh:
        return {p.title: p for p in source.iter_pages(fh)}


def test_latest_revision_wins_across_split_page_elements():
    pages = _pages(FIXTURE)
    # "Triple Fault" appears twice; the second element holds the newer revision.
    assert pages["Triple Fault"].timestamp == "2014-07-17T05:58:04Z"
    assert "OLD REVISION" not in pages["Triple Fault"].text


def test_only_main_namespace_pages():
    pages = _pages(FIXTURE)
    assert "User:Someone" not in pages
    assert set(pages) == {"Triple Fault", "Interrupt Descriptor Table", "IDT",
                          "Programmable Interval Timer", "PIT", "APIC Timer"}


def test_zst_is_streamed(tmp_path):
    raw = open(FIXTURE, "rb").read()
    zst = tmp_path / "d.xml.zst"
    zst.write_bytes(zstandard.ZstdCompressor().compress(raw))
    assert _pages(str(zst)).keys() == _pages(FIXTURE).keys()


def test_latest_dump_picks_newest_dated_item(monkeypatch):
    calls = []

    def fake(url, timeout=60):
        calls.append(url)
        if "advancedsearch" in url:
            return {"response": {"docs": [
                {"identifier": "wiki-wiki.osdev.org-20240703"},
                {"identifier": "wiki-wiki.osdev.org"},           # undated: ignored
                {"identifier": "wiki-wiki.osdev.org-20251230"},
            ]}}
        assert url.endswith("wiki-wiki.osdev.org-20251230")
        return {"files": [{"name": "x-images.7z"},
                          {"name": "wiki.osdev.org-20251230-history.xml.zst",
                           "size": "5270521", "md5": "abc"}]}

    monkeypatch.setattr(source, "_get_json", fake)
    d = source.latest_dump()
    assert d.identifier == "wiki-wiki.osdev.org-20251230" and d.md5 == "abc"
    assert d.url.endswith("/wiki-wiki.osdev.org-20251230/wiki.osdev.org-20251230-history.xml.zst")
    assert d.date == "20251230"


def test_latest_dump_with_no_items_is_explicit(monkeypatch):
    monkeypatch.setattr(source, "_get_json", lambda url, timeout=60: {"response": {"docs": []}})
    with pytest.raises(source.SourceError, match="no wiki.osdev.org dumps"):
        source.latest_dump()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_verifies_md5(tmp_path, monkeypatch):
    body = b"dump bytes"
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda req, timeout: _Resp(body))
    good = source.Dump("i", "f.zst", len(body), hashlib.md5(body).hexdigest())
    dest = tmp_path / "out.zst"
    source.download(good, str(dest))
    assert dest.read_bytes() == body

    bad = source.Dump("i", "f.zst", len(body), "0" * 32)
    with pytest.raises(source.SourceError, match="checksum mismatch"):
        source.download(bad, str(tmp_path / "bad.zst"))
    assert not (tmp_path / "bad.zst").exists() and not (tmp_path / "bad.zst.part").exists()
