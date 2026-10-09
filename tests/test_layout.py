"""Readable word wrapping, explicit line breaks, and display-width boundaries."""

import pytest

from study_p2v.scene import wrap


@pytest.mark.parametrize(
    ("text", "columns", "expected"),
    [
        ("Render frames", 11, "Render\nframes"),
        ("Explain the method", 14, "Explain the\nmethod"),
        ("alpha beta", 5, "alpha\nbeta"),
    ],
    ids=["render-frames", "explain-method", "exact-width-word-before-space"],
)
def test_english_words_stay_whole_when_they_fit(text, columns, expected):
    assert wrap(text, columns) == expected


@pytest.mark.parametrize(
    ("text", "columns", "expected"),
    [
        ("Render\nframes", 20, "Render\nframes"),
        ("alpha\n\nbeta", 8, "alpha\n\nbeta"),
    ],
    ids=["explicit-break", "explicit-blank-line"],
)
def test_explicit_newlines_are_preserved(text, columns, expected):
    assert wrap(text, columns) == expected


@pytest.mark.parametrize(
    ("text", "columns", "expected"),
    [
        ("abcdefghijkl", 5, "abcde\nfghij\nkl"),
        ("abcdefghij", 5, "abcde\nfghij"),
    ],
    ids=["partial-last-chunk", "exact-last-chunk"],
)
def test_oversized_unspaced_tokens_use_hard_breaks(text, columns, expected):
    assert wrap(text, columns) == expected


@pytest.mark.parametrize(
    ("text", "columns", "expected"),
    [
        ("\u754c\u754c\u754c", 4, "\u754c\u754c\n\u754c"),
        ("\uff21\uff22\uff23", 4, "\uff21\uff22\n\uff23"),
        ("A\u754cB\u754c", 3, "A\u754c\nB\u754c"),
    ],
    ids=["wide-characters", "full-width-letters", "mixed-width-token"],
)
def test_east_asian_display_width_counts_two_columns(text, columns, expected):
    assert wrap(text, columns) == expected
