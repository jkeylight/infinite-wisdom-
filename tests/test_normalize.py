from converter.normalize import clean_block, dehyphenate, expand_ligatures, normalize_document


def test_ligatures():
    assert expand_ligatures("ﬁle ﬂow") == "file flow"


def test_dehyphenate():
    assert dehyphenate("exam-\nple") == "example"
    assert dehyphenate("well-\nknown") == "wellknown"  # known limitation, acceptable for v1


def test_clean_block():
    assert clean_block("  hello   world \n next line ") == "hello world next line"


def test_normalize_document_collapses_blanks():
    out = normalize_document("a\n\n\n\n\nb\n")
    assert out == "a\n\nb\n"
    assert "\n\n\n" not in out


def test_normalize_document_strips_control():
    out = normalize_document("hello\x00 world")
    assert "\x00" not in out
