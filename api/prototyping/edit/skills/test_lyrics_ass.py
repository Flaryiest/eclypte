from api.prototyping.edit.skills.lyrics_ass import (
    AssEvent,
    AssStyle,
    ass_color,
    ass_timestamp,
    build_ass_document,
    kf_line_text,
    sanitize_ass_text,
)


def test_ass_color_is_alpha_first_bgr():
    # ASS colors are &HAABBGGRR — asymmetric channels catch an RGB/BGR swap.
    assert ass_color("#112233") == "&H00332211"
    assert ass_color("#E86A4F") == "&H004F6AE8"
    assert ass_color("112233") == "&H00332211"  # leading '#' optional


def test_ass_color_alpha_byte():
    # ASS alpha: 00 = opaque, FF = fully transparent.
    assert ass_color("#FFFFFF", alpha=1.0) == "&HFFFFFFFF"
    assert ass_color("#000000", alpha=0.5) == "&H80000000"


def test_ass_timestamp_format_and_carry():
    assert ass_timestamp(0.0) == "0:00:00.00"
    assert ass_timestamp(3661.239) == "1:01:01.24"
    # 59.999s rounds up to a full minute — centisecond carry must propagate.
    assert ass_timestamp(59.999) == "0:01:00.00"


def test_sanitize_ass_text_strips_override_syntax():
    # "{"/"}" open ASS override blocks; "\" can form \N/\h control sequences.
    assert sanitize_ass_text("hey {\\b1}you") == "hey you"
    assert sanitize_ass_text("back\\slash") == "backslash"
    assert sanitize_ass_text("line\nbreak  wide") == "line break wide"
    assert sanitize_ass_text("  padded  ") == "padded"


def _w(text, start, end):
    return {"text": text, "start_sec": start, "end_sec": end}


def test_kf_line_text_contiguous_words():
    text = kf_line_text([_w("hold", 0.0, 0.5), _w("me", 0.5, 1.0)], line_start_sec=0.0)
    assert text == "{\\kf50}hold {\\kf50}me"


def test_kf_line_text_fills_gaps_with_bare_kf():
    # A vocal pause between words becomes a textless \kf so the sweep waits.
    text = kf_line_text([_w("hold", 0.2, 0.5), _w("me", 0.9, 1.3)], line_start_sec=0.0)
    assert text == "{\\kf20}{\\kf30}hold {\\kf40}{\\kf40}me"


def test_kf_line_text_cumulative_rounding_spans_line_exactly():
    # Three 0.333s words: naive per-word rounding gives 33+33+33=99cs; the
    # cumulative scheme must make the total exactly 100cs.
    words = [_w("a", 0.0, 0.333), _w("b", 0.333, 0.666), _w("c", 0.666, 0.999)]
    text = kf_line_text(words, line_start_sec=0.0)
    assert text == "{\\kf33}a {\\kf34}b {\\kf33}c"


def test_kf_line_text_sanitizes_words():
    text = kf_line_text([_w("he{y}", 0.0, 0.5)], line_start_sec=0.0)
    assert text == "{\\kf50}hey"


def test_build_ass_document_structure():
    style = AssStyle(
        name="Line0",
        fontname="Bebas Neue",
        fontsize=96,
        primary=ass_color("#FFFFFF"),
        secondary=ass_color("#808080"),
        outline_colour=ass_color("#000000"),
        back_colour=ass_color("#000000", alpha=1.0),
        outline=3.0,
        shadow=0.0,
        alignment=2,
        margin_v=120,
    )
    event = AssEvent(
        start_sec=1.0,
        end_sec=2.5,
        style_name="Line0",
        text="{\\kf150}hello",
    )
    doc = build_ass_document(play_res=(1080, 1920), styles=[style], events=[event])

    assert "[Script Info]" in doc
    assert "ScriptType: v4.00+" in doc
    assert "PlayResX: 1080" in doc
    assert "PlayResY: 1920" in doc
    assert "WrapStyle: 2" in doc
    assert "ScaledBorderAndShadow: yes" in doc

    assert "[V4+ Styles]" in doc
    assert (
        "Style: Line0,Bebas Neue,96,&H00FFFFFF,&H00808080,&H00000000,&HFF000000,"
        "0,0,0,0,100,100,0,0,1,3.0,0.0,2,60,60,120,1" in doc
    )

    assert "[Events]" in doc
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,Line0,,0,0,0,,{\\kf150}hello" in doc


def test_build_ass_document_bold_and_position_margins():
    style = AssStyle(
        name="Pop",
        fontname="Anton",
        fontsize=140,
        primary=ass_color("#FFFFFF"),
        secondary=ass_color("#808080"),
        outline_colour=ass_color("#000000"),
        back_colour=ass_color("#000000", alpha=1.0),
        bold=True,
        alignment=5,
    )
    doc = build_ass_document(play_res=(1080, 1920), styles=[style], events=[])
    assert ",Anton,140," in doc
    assert ",-1,0,0,0,100,100,0,0,1," in doc  # Bold=-1 (ASS truthy)


def test_kf_line_text_row_breaks_become_hard_line_breaks():
    words = [_w("hold", 0.0, 0.5), _w("me", 0.5, 1.0), _w("close", 1.0, 1.5)]
    text = kf_line_text(words, line_start_sec=0.0, row_breaks=frozenset({2}))
    # the separator BEFORE the word starting a new row is \N, not a space
    assert text == "{\\kf50}hold {\\kf50}me\\N{\\kf50}close"
