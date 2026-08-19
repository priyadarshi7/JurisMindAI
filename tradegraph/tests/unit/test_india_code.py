"""Unit tests for src.rag.ingestion.india_code's pure parsing logic —
`parse_articles` operates on already-extracted text, no live PDF/pypdf
needed to test the splitting/filtering behavior itself.
"""

from __future__ import annotations

import pytest

from src.rag.ingestion.india_code import (
    ConstitutionParseError,
    parse_articles,
    slice_between_markers,
)

# Shaped like the real extracted text (verified live against the official
# legislative.gov.in PDF, 2026-08-19): a footnote/amendment marker ("1[Added
# by...") shares the "<number>. <text>" shape with a real article heading
# but uses a small number that must not be mistaken for one.
SAMPLE_TEXT = """
PART III
FUNDAMENTAL RIGHTS
General
12. Definition.— In this Part, unless the context otherwise requires, the
State includes the Government and Parliament of India.
13. Laws inconsistent with or in derogation of the fundamental rights.—
(1) All laws in force shall, to the extent of such inconsistency, be void.
1[Added by the Constitution (First Amendment) Act, 1951, s. 2]
21. Protection of life and personal liberty.— No person shall be deprived
of his life or personal liberty except according to procedure established
by law.
22. Protection against arrest and detention in certain cases.— No person
who is arrested shall be detained in custody without being informed of the
grounds for such arrest.
"""


def test_parse_articles_extracts_real_articles_in_range() -> None:
    parsed = parse_articles(SAMPLE_TEXT, min_article=12, max_article=35)

    names = [s.name for s in parsed.sections]
    assert names == ["Article 12", "Article 13", "Article 21", "Article 22"]


def test_parse_articles_excludes_footnote_markers_outside_range() -> None:
    """The "1[Added by..." footnote marker must never surface as "Article
    1" — it shares the regex shape but its number (1) falls outside any
    real Part III article range (12-35).
    """
    parsed = parse_articles(SAMPLE_TEXT, min_article=12, max_article=35)

    assert all(s.name != "Article 1" for s in parsed.sections)


def test_parse_articles_captures_article_body_text() -> None:
    parsed = parse_articles(SAMPLE_TEXT, min_article=12, max_article=35)

    article_21 = next(s for s in parsed.sections if s.name == "Article 21")
    assert "Protection of life and personal liberty" in article_21.text
    assert "No person shall be deprived" in article_21.text
    # Body must stop before the next article, not run past it.
    assert "Article 22" not in article_21.text


def test_parse_articles_raises_when_nothing_in_range() -> None:
    with pytest.raises(ConstitutionParseError):
        parse_articles(SAMPLE_TEXT, min_article=100, max_article=110)


def test_parse_articles_drops_garbled_titles() -> None:
    garbled_text = "\n14. P��� garbage title.— some body text.\n"
    with pytest.raises(ConstitutionParseError):
        parse_articles(garbled_text, min_article=12, max_article=35)


def test_slice_between_markers_bounds_to_one_part() -> None:
    text = "junk before\nPART III\nFUNDAMENTAL RIGHTS\n21. Right.\nPART IV\nDIRECTIVE PRINCIPLES\n36. Def."

    sliced = slice_between_markers(text, start_marker="PART III", end_marker="PART IV")

    assert "PART III" in sliced
    assert "36. Def." not in sliced
    assert "junk before" not in sliced


def test_slice_between_markers_raises_when_marker_missing() -> None:
    with pytest.raises(ConstitutionParseError):
        slice_between_markers("no markers here", start_marker="PART III", end_marker="PART IV")


def test_parse_articles_truncates_body_at_contamination_boundary() -> None:
    """Found live (2026-08-19) against the real official Constitution PDF:
    a regional-language (Kannada) rendering interleaved in the same page
    range decodes through pypdf as plausible-looking but meaningless
    Latin-alphabet text — not U+FFFD, so the title guard doesn't catch it.
    The real English clause before the contamination is genuine, accurate
    text — keep it (truncated), don't discard the whole article just
    because what comes after it is garbage.
    """
    text = (
        "\n29. Protection of interests of minorities.— real clean English body text here.\n"
        "\n30. Right of minorities to establish and administer educational institutions.— "
        "All minorities shall have the right to establish such institutions of their choice. "
        + ("ಅಕಟ " * 200)  # Kannada-block characters standing in for the garble
        + "\n32. Remedies for enforcement of rights conferred by this Part.— more clean text.\n"
    )

    with pytest.warns(UserWarning, match="truncated"):
        parsed = parse_articles(text, min_article=12, max_article=35)

    names = [s.name for s in parsed.sections]
    assert names == ["Article 29", "Article 30", "Article 32"]
    article_30 = next(s for s in parsed.sections if s.name == "Article 30")
    assert "All minorities shall have the right" in article_30.text
    assert "ಅ" not in article_30.text  # no Kannada leaked into the kept text


def test_parse_articles_drops_article_when_contamination_starts_immediately() -> None:
    """No clean prefix survives truncation (contamination fills the entire
    first window) — same "don't ship it" policy as a garbled title, just
    reached via the body instead.
    """
    text = (
        "\n29. Protection of interests of minorities.— real clean English body text here.\n"
        "\n30. Right.— " + ("ಅಕಟ " * 200) + "\n"
        "\n32. Remedies for enforcement of rights conferred by this Part.— more clean text.\n"
    )

    with pytest.warns(UserWarning, match="dropped"):
        parsed = parse_articles(text, min_article=12, max_article=35)

    names = [s.name for s in parsed.sections]
    assert names == ["Article 29", "Article 32"]


def test_parse_articles_last_article_body_stops_at_part_boundary() -> None:
    """The bug found live (2026-08-19): without a real end boundary, the
    last kept article's body ran to the end of whatever text was handed
    in — "Article 35" absorbed an entire next Part (85,000 tokens) because
    the caller's page range extended well past Part III. Bounding via
    slice_between_markers before parse_articles is what fixes this; this
    test pins that the fix actually stops the last article's body where
    the Part ends, not wherever the input text happens to end.
    """
    text = (
        "PART III\nFUNDAMENTAL RIGHTS\n"
        "21. Protection of life and personal liberty.— No person shall be deprived.\n"
        "PART IV\nDIRECTIVE PRINCIPLES OF STATE POLICY\n"
        "36. Definition.— unrelated Part IV text that must not leak into Article 21.\n"
    )

    sliced = slice_between_markers(text, start_marker="PART III", end_marker="PART IV")
    parsed = parse_articles(sliced, min_article=12, max_article=35)

    article_21 = next(s for s in parsed.sections if s.name == "Article 21")
    assert "unrelated Part IV text" not in article_21.text
