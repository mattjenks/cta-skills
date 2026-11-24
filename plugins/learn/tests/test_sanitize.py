import sanitize

HOSTILE = "<script>alert(1)</script>|a\nb\r`x`[y](z)\x00\x1b[31m"


def test_name_keeps_plain_names():
    assert sanitize.name("cta:kept-skill_1.2") == "cta:kept-skill_1.2"


def test_name_neutralizes_hostile_text():
    out = sanitize.name(HOSTILE)
    assert not any(c in out for c in "<>|\n\r`[]()\x00\x1b")
    assert len(sanitize.name("a" * 500)) <= 80


def test_path_neutralizes_hostile_text():
    out = sanitize.path("/Users/x/<b>|\n/y")
    assert not any(c in out for c in "<>|\n")
    assert "/Users/x/" in out


def test_line_is_single_line_and_capped():
    out = sanitize.line("one\ntwo\r\nthree\x00" + "z" * 500)
    assert "\n" not in out and "\r" not in out and "\x00" not in out
    assert len(out) <= 200


def test_md_escapes_table_and_link_syntax():
    out = sanitize.md(HOSTILE)
    assert "\n" not in out and "\r" not in out
    assert "|" not in out.replace("\\|", "")
    assert "<script>" not in out
    assert "`" not in out.replace("\\`", "")


def test_html_escapes_markup():
    out = sanitize.html(HOSTILE)
    assert "<" not in out and ">" not in out
    assert "&lt;script&gt;" in out
    assert "\x00" not in out


def test_non_string_input_is_coerced():
    assert sanitize.name(None) == ""
    assert sanitize.line(5) == "5"
