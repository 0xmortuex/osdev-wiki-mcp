import pytest

from osdev_wiki_mcp import index


def test_redirects_are_not_pages(wiki):
    m = wiki.meta()
    assert (m["pages"], m["redirects"]) == ("4", "2")


def test_exact_title_ranks_first(wiki):
    hits = wiki.search("triple fault")
    assert hits[0].title == "Triple Fault" and hits[0].exact


def test_redirect_alias_ranks_first(wiki):
    # "PIT" also appears in the APIC Timer body; the alias must win.
    hits = wiki.search("PIT")
    assert [h.title for h in hits][:2] == ["Programmable Interval Timer", "APIC Timer"]
    assert hits[0].exact


def test_all_words_then_any_word(wiki):
    assert [h.title for h in wiki.search("gate descriptor")] == ["Interrupt Descriptor Table"]
    # No page has both words: falls back to pages matching either.
    titles = {h.title for h in wiki.search("oscillator double")}
    assert titles == {"Programmable Interval Timer", "Triple Fault"}


def test_snippet_marks_matches(wiki):
    hit = wiki.search("oscillator")[0]
    assert "[oscillator]" in hit.snippet


def test_resolve(wiki):
    assert wiki.resolve("interrupt_descriptor_table") == ("Interrupt Descriptor Table", None)
    title, note = wiki.resolve("idt")
    assert title == "Interrupt Descriptor Table" and "redirects to" in note
    with pytest.raises(KeyError, match="closest: Triple Fault"):
        wiki.resolve("triple faults handling")


def test_sections_and_links(wiki):
    heads = [h for _i, _l, h, _n in wiki.sections("Interrupt Descriptor Table")]
    assert heads == ["", "Structure on IA-32", "Gate Descriptor", "Structure on x86-64",
                     "Gate Descriptor", "Example Code"]
    out = dict(wiki.links_out("Triple Fault"))
    assert out == {"Interrupt Descriptor Table": True, "Nonexistent Page": False,
                   "Task State Segment": False}
    # APIC Timer links to the PIT *redirect*; that still counts as linking the page.
    assert wiki.links_in("Programmable Interval Timer") == ["APIC Timer"]


def test_missing_index_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("OSDEV_WIKI_DIR", str(tmp_path))
    with pytest.raises(index.IndexError_, match="call wiki_update first"):
        index.Wiki()


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("OSDEV_WIKI_DIR", str(tmp_path))
    assert index.data_dir() == str(tmp_path)
