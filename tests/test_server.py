import shutil

import pytest

from osdev_wiki_mcp import server as S
from osdev_wiki_mcp import source
from conftest import FIXTURE


def test_search_output(wiki_dir):
    out = S.wiki_search("PIT", 3)
    assert out.startswith("1. Programmable Interval Timer *")
    with pytest.raises(ValueError):
        S.wiki_search("x", 0)


def test_sections_output_follows_redirect(wiki_dir):
    out = S.wiki_sections("IDT")
    assert out.startswith("Interrupt Descriptor Table  (https://wiki.osdev.org/Interrupt_Descriptor_Table)")
    assert "  2.   Gate Descriptor" in out and "redirects to" in out


def test_page_section_by_heading_includes_subsections(wiki_dir):
    out = S.wiki_page("IDT", section="Structure on IA-32")
    assert "### Gate Descriptor" in out and "63..48 | 47" in out
    assert "64-bit gate" not in out


def test_ambiguous_heading_is_reported(wiki_dir):
    out = S.wiki_page("Interrupt Descriptor Table", section="gate descriptor")
    assert "appears 2 times; showing section 2 under 'Structure on IA-32'" in out
    assert "Also: section 4 under 'Structure on x86-64'" in out


def test_page_section_by_number_and_errors(wiki_dir):
    assert "64-bit gate is 16 bytes" in S.wiki_page("IDT", section="4")
    with pytest.raises(ValueError, match="sections 0-5"):
        S.wiki_page("IDT", section="9")
    with pytest.raises(KeyError, match="no section 'Nope'"):
        S.wiki_page("IDT", section="Nope")


def test_code_is_kept_and_headings_inside_code_ignored(wiki_dir):
    out = S.wiki_page("IDT", section="Example Code")
    assert "uint16_t isr_low; // == not a heading ==" in out


def test_truncation_lists_remaining_sections(wiki_dir):
    out = S.wiki_page("IDT", max_chars=500)
    assert "[Cut at max_chars=500" in out
    assert "Fetch the remaining sections" in out and "Example Code" in out


def test_truncation_of_single_section_says_how_much(wiki_dir):
    out = S.wiki_page("Triple Fault", section="Causes", max_chars=500)
    assert "[... section truncated]" in out
    assert "Call again with max_chars=" in out and "Fetch the remaining" not in out


def test_status_and_links(wiki_dir):
    st = S.wiki_status()
    assert "4 pages, 2 redirects" in st and "wiki-wiki.osdev.org-20990101" in st
    links = S.wiki_links("Triple Fault")
    assert "Nonexistent Page  (no such page)" in links and "Linked from (1):" in links


def test_update_skips_when_current(tmp_path, monkeypatch):
    monkeypatch.setenv("OSDEV_WIKI_DIR", str(tmp_path))
    dump = source.Dump("wiki-wiki.osdev.org-20990101", "x-history.xml.zst", 1, "")
    monkeypatch.setattr(source, "latest_dump", lambda: dump)

    def fake_download(d, dest):
        import zstandard
        with open(FIXTURE, "rb") as f, open(dest, "wb") as o:
            o.write(zstandard.ZstdCompressor().compress(f.read()))
        return dest

    monkeypatch.setattr(source, "download", fake_download)
    first = S.update()
    assert first.startswith("Indexed 4 pages, 2 redirects")
    assert not list(tmp_path.glob("*.zst")), "downloaded dump is deleted after indexing"
    assert S.update() == "Already up to date: index built from wiki-wiki.osdev.org-20990101."
    assert S.update(force=True).startswith("Indexed 4 pages")
    shutil.rmtree(tmp_path)
