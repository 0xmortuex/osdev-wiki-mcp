"""Ranking quality against the real OSDev wiki.

Runs only when OSDEV_WIKI_REAL_DIR points at a directory holding a real
index (build one with `OSDEV_WIKI_DIR=<dir> osdev-wiki-mcp --update`). CI
does this in a separate job. Each query is something an OS developer
actually asks; the obviously right page must rank in the top 3.
"""

import os

import pytest

from osdev_wiki_mcp import index
from osdev_wiki_mcp import server as S

REAL = os.environ.get("OSDEV_WIKI_REAL_DIR")
pytestmark = pytest.mark.skipif(not REAL, reason="set OSDEV_WIKI_REAL_DIR to a real index dir")

QUERIES = [
    ("triple fault", "Triple Fault"),
    ("PIT", "Programmable Interval Timer"),
    ("GDT tutorial", "GDT Tutorial"),
    ("RSDP", "RSDP"),
    ("PS/2 keyboard", "PS/2 Keyboard"),
    ("paging", "Paging"),
    ("IDT", "Interrupt Descriptor Table"),
    ("8259 PIC", "8259 PIC"),
    ("APIC timer", "APIC Timer"),
    ("ATA PIO", "ATA PIO Mode"),
    ("higher half kernel", "Higher Half Kernel"),
    ("serial port", "Serial Ports"),
    ("page fault error code", "Exceptions"),
    ("how to enter long mode", "Setting Up Long Mode"),
]


@pytest.fixture(scope="module")
def real_wiki():
    os.environ["OSDEV_WIKI_DIR"] = REAL or ""
    return index.Wiki(os.path.join(REAL or "", "index.sqlite"))


@pytest.mark.parametrize("query,expected", QUERIES)
def test_right_page_in_top_3(real_wiki, query, expected):
    titles = [h.title for h in real_wiki.search(query, 3)]
    assert expected in titles, f"{query!r} -> {titles}"


def test_index_is_substantial(real_wiki):
    m = real_wiki.meta()
    assert int(m["pages"]) > 500 and int(m["redirects"]) > 200


def test_bit_layout_tables_render(real_wiki):
    out = S.wiki_page("IDT", section="Gate Descriptor")
    assert "Offset 31..16 | P | DPL 1..0" in out
