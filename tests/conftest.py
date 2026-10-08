import os

import pytest

from osdev_wiki_mcp import index, source

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mini-wiki.xml")


@pytest.fixture
def wiki_dir(tmp_path, monkeypatch):
    """OSDEV_WIKI_DIR pointing at an index built from the fixture wiki."""
    monkeypatch.setenv("OSDEV_WIKI_DIR", str(tmp_path))
    with source.open_dump(FIXTURE) as fh:
        index.build(source.iter_pages(fh), index.db_path(),
                    {"dump": "wiki-wiki.osdev.org-20990101", "dump_url": "fixture"})
    return tmp_path


@pytest.fixture
def wiki(wiki_dir):
    return index.Wiki()
