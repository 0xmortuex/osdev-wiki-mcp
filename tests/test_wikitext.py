from osdev_wiki_mcp.wikitext import normalize_title, parse_page, to_plain


def test_normalize_title():
    assert normalize_title("triple_fault") == "Triple fault"
    assert normalize_title("  Interrupt   Descriptor_Table ") == "Interrupt Descriptor Table"


def test_links_become_labels_and_files_vanish():
    assert to_plain("See [[Paging|the paging page]] and [[GDT]].") == "See the paging page and GDT."
    assert to_plain("A [[File:x.png|thumb|caption]] picture") == "A  picture"
    assert to_plain("[https://intel.com SDM] and [https://x.org]") == "SDM and"


def test_nested_templates_are_removed():
    assert to_plain("a {{Q|b {{nested|c}} d}} e") == "a  e"


def test_bold_italic_and_lists():
    assert to_plain("'''Bold''' and ''it''\n* one\n# two") == "Bold and it\n- one\n- two"


def test_code_blocks_are_verbatim():
    text = to_plain('<syntaxhighlight lang="c">\nx = a[[b]] && \'\'c\'\';\n</syntaxhighlight>')
    assert "x = a[[b]] && ''c'';" in text and text.startswith("```")


def test_bit_layout_table_renders_rows():
    wt = ('{| class="wikitable"\n|+Gate:\n'
          '!style="w"|63&nbsp;&nbsp;<span style="float: right;">48</span>\n!47\n'
          "|-\n|'''Offset'''<br>31&nbsp;<span style=\"float:right\">16</span>\n"
          '|style="text-align: center;"|P\n|}')
    assert to_plain(wt) == "Gate:\n63..48 | 47\nOffset 31..16 | P"


def test_redirect():
    p = parse_page("PIT", "#REDIRECT [[Programmable_Interval_Timer#Ports]]")
    assert p.redirect == "Programmable Interval Timer" and p.sections == []


def test_sections_links_categories():
    wt = ("Intro [[Paging]] and [[paging]] again.\n== A ==\ntext [[Category:X86 CPU]]\n"
          "=== A.1 ===\nsub\n<pre>\n== not a heading ==\n</pre>\n== B ==\nb [[:Category:Y]]")
    p = parse_page("t", wt)
    assert [(s.level, s.heading) for s in p.sections] == [(1, ""), (2, "A"), (3, "A.1"), (2, "B")]
    assert "== not a heading ==" in p.sections[2].text
    assert p.links == ["Paging"]
    assert p.categories == ["X86 CPU"]
